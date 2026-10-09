"""C. Work + recording identities (page 4).

A composition register (work codes / ISWC), a recording register (ISRC) and an approved link table. A composition
can have several recordings; a medley can link to several works (with an allocation). Fuzzy spellings only
propose candidates for a human decision - nothing is merged or deleted automatically. An approved identity version
is a frozen snapshot of the links a comparison uses.
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

from . import audit, db
from .normalize import ZERO, _FOLD, fold, s, similarity, title_key

ONE = Decimal(1)


class IdentityError(Exception):
    pass


def dup_key(title) -> str:
    """Candidate key that keeps version words: covers, lo-fi and adaptations stay distinct works."""
    x = title_key(title)
    for a, b in _FOLD:
        x = x.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", x)


# ------------------------------------------------------------------ C1 registers + catalogue links
def refresh(conn, client_id: int, actor: dict | None = None) -> dict:
    v = "s.status = 'VALIDATED' AND s.client_id = %(c)s"
    p = dict(c=client_id)
    # compositions: catalogue first, then works paid in statements
    conn.execute(f"""
        INSERT INTO composition (client_id, work_code, title, film, composer, lyricist, source)
        SELECT DISTINCT ON (w) %(c)s, w, coalesce(l.title, '(untitled)'), l.film, l.composer, l.lyricist, 'catalogue'
        FROM catalogue_line l JOIN source_file s ON s.id = l.file_id, unnest(l.work_codes) w
        WHERE {v} AND l.is_valid ORDER BY w, s.id DESC, l.row_no
        ON CONFLICT (client_id, work_code) DO UPDATE SET title = EXCLUDED.title, film = coalesce(EXCLUDED.film,
          composition.film), composer = coalesce(EXCLUDED.composer, composition.composer),
          lyricist = coalesce(EXCLUDED.lyricist, composition.lyricist), source = 'catalogue'""", p)
    conn.execute(f"""
        INSERT INTO composition (client_id, work_code, title, source)
        SELECT DISTINCT ON (l.work_code) %(c)s, l.work_code, coalesce(l.title, '(untitled)'), 'statement'
        FROM publishing_line l JOIN source_file s ON s.id = l.file_id
        WHERE {v} AND l.is_valid ORDER BY l.work_code, s.id DESC
        ON CONFLICT (client_id, work_code) DO NOTHING""", p)
    # recordings: report titles name the master; catalogue ISRCs fill the rest
    conn.execute(f"""
        INSERT INTO recording (client_id, isrc, title, source)
        SELECT DISTINCT ON (isrc) %(c)s, isrc, coalesce(title, '(untitled)'), 'report' FROM (
          SELECT l.isrc, l.title, s.id FROM recording_line l JOIN source_file s ON s.id = l.file_id
          WHERE {v} AND l.is_valid
          UNION ALL SELECT l.isrc, l.title, s.id FROM usage_line l JOIN source_file s ON s.id = l.file_id
          WHERE {v} AND l.is_valid) x ORDER BY isrc, id DESC
        ON CONFLICT (client_id, isrc) DO UPDATE SET title = EXCLUDED.title, source = 'report'""", p)
    conn.execute(f"""
        INSERT INTO recording (client_id, isrc, title, source)
        SELECT DISTINCT ON (i) %(c)s, i, coalesce(l.title, '(untitled)'), 'catalogue'
        FROM catalogue_line l JOIN source_file s ON s.id = l.file_id, unnest(l.isrcs) i
        WHERE {v} AND l.is_valid ORDER BY i, s.id DESC
        ON CONFLICT (client_id, isrc) DO NOTHING""", p)

    # catalogue links; an ISRC under several works is a conflict until a reviewer decides
    pairs = db.all(conn, f"""
        SELECT DISTINCT ON (w, i) w AS work_code, i AS isrc, l.file_id, l.row_no, l.title, l.note
        FROM catalogue_line l JOIN source_file s ON s.id = l.file_id, unnest(l.work_codes) w, unnest(l.isrcs) i
        WHERE {v} AND l.is_valid ORDER BY w, i, s.id DESC, l.row_no""", p)
    comp = {r["work_code"]: r["id"] for r in db.all(conn, "SELECT id, work_code FROM composition WHERE client_id = %s",
                                                    (client_id,))}
    rec = {r["isrc"]: r["id"] for r in db.all(conn, "SELECT id, isrc FROM recording WHERE client_id = %s",
                                              (client_id,))}
    works_per_isrc: dict[str, set] = defaultdict(set)
    for r in pairs:
        works_per_isrc[r["isrc"]].add(r["work_code"])
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_link (composition_id BIGINT, recording_id BIGINT, status TEXT, "
                 "evidence JSONB) ON COMMIT DROP")
    conn.execute("TRUNCATE tmp_link")
    db.insert_many(conn, "tmp_link", ("composition_id", "recording_id", "status", "evidence"), (
        (comp[r["work_code"]], rec[r["isrc"]], "APPROVED" if len(works_per_isrc[r["isrc"]]) == 1 else "PROPOSED",
         db.J(dict(file_id=r["file_id"], row=r["row_no"], catalogue_title=r["title"], note=r["note"],
                   basis="client catalogue")))
        for r in sorted(pairs, key=lambda x: (x["work_code"], x["isrc"]))))
    conn.execute("""
        INSERT INTO work_link (client_id, composition_id, recording_id, basis, evidence, status)
        SELECT %(c)s, composition_id, recording_id, 'CATALOGUE', evidence, status FROM tmp_link
        ORDER BY composition_id, recording_id
        ON CONFLICT (composition_id, recording_id) DO UPDATE SET evidence = EXCLUDED.evidence,
          status = EXCLUDED.status WHERE work_link.decided_by IS NULL AND work_link.basis = 'CATALOGUE'""", p)
    removed = conn.execute("""
        DELETE FROM work_link w WHERE w.client_id = %(c)s AND w.basis = 'CATALOGUE' AND w.decided_by IS NULL
        AND NOT EXISTS (SELECT 1 FROM tmp_link t WHERE t.composition_id = w.composition_id
                        AND t.recording_id = w.recording_id)""", p).rowcount
    issues = _issues(conn, client_id)
    cands = _candidates(conn, client_id)
    counts = summary(conn, client_id)
    if actor is not None:
        audit.record(conn, "identity.refreshed", actor, "client", client_id,
                     dict(issues=issues, candidates=cands, removed_links=removed))
    return dict(issues=issues, candidates=cands, removed_links=removed, **counts)


def _money_by_isrc(conn, client_id: int) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: dict(r=ZERO, n=0, title=None, has_r=False))
    for r in db.all(conn, "SELECT l.isrc, sum(l.amount) AS r, max(l.title) AS title FROM recording_line l "
                          "JOIN source_file s ON s.id = l.file_id WHERE s.client_id = %s AND s.status = 'VALIDATED' "
                          "AND l.is_valid AND l.duplicate_state <> 'SUPPRESSED' GROUP BY l.isrc", (client_id,)):
        out[r["isrc"]].update(r=r["r"], title=r["title"], has_r=True)
    for r in db.all(conn, "SELECT l.isrc, sum(l.streams) AS n, max(l.title) AS title FROM usage_line l "
                          "JOIN source_file s ON s.id = l.file_id WHERE s.client_id = %s AND s.status = 'VALIDATED' "
                          "AND l.is_valid AND l.duplicate_state <> 'SUPPRESSED' GROUP BY l.isrc", (client_id,)):
        out[r["isrc"]]["n"] = int(r["n"] or 0)
        out[r["isrc"]]["title"] = out[r["isrc"]]["title"] or r["title"]
    return out


def _issues(conn, client_id: int) -> int:
    money = _money_by_isrc(conn, client_id)
    comps = db.all(conn, "SELECT id, work_code, title, source FROM composition WHERE client_id = %s AND "
                         "canonical_id IS NULL", (client_id,))
    approved = {r["isrc"] for r in db.all(conn, "SELECT DISTINCT r.isrc FROM work_link w JOIN recording r ON "
                                                "r.id = w.recording_id WHERE w.client_id = %s AND w.status = "
                                                "'APPROVED'", (client_id,))}
    found: dict[tuple[str, str], dict] = {}
    by_fold = defaultdict(list)
    for c in comps:
        by_fold[fold(c["title"])[:4]].append(c)

    def candidates(title: str) -> list[dict]:
        pool = by_fold.get(fold(title)[:4], []) or comps
        scored = sorted(((similarity(title, c["title"]), c) for c in pool), key=lambda x: -x[0])
        return [dict(composition_id=c["id"], work_code=c["work_code"], title=c["title"], score=sc)
                for sc, c in scored[:3] if sc >= 0.6]

    for code, m in money.items():
        if code in approved:
            continue
        conflict = db.all(conn, "SELECT c.work_code, c.title, w.id AS link_id FROM work_link w JOIN recording r ON "
                                "r.id = w.recording_id JOIN composition c ON c.id = w.composition_id WHERE "
                                "w.client_id = %s AND r.isrc = %s AND w.status = 'PROPOSED' ORDER BY c.work_code",
                          (client_id, code))
        if conflict:
            found[("ISRC_CONFLICT", code)] = dict(title=m["title"], amount=m["r"] if m["has_r"] else None, detail=dict(
                isrc=code, streams=m["n"], works=conflict,
                why="the catalogue lists this ISRC under more than one work - choose the work, or allocate a "
                    "medley; income is never counted twice"))
        else:
            found[("UNMAPPED_RECORDING", code)] = dict(title=m["title"], amount=m["r"] if m["has_r"] else None,
                                                       detail=dict(isrc=code, streams=m["n"],
                                                                   candidates=candidates(m["title"] or ""),
                                                                   why="recording earns income but has no approved "
                                                                       "link to a work - no title-only merge"))
    paid = db.all(conn, "SELECT l.work_code, max(l.title) AS title, sum(l.amount) AS p FROM publishing_line l JOIN "
                        "source_file s ON s.id = l.file_id WHERE s.client_id = %s AND s.status = 'VALIDATED' AND "
                        "l.is_valid GROUP BY l.work_code", (client_id,))
    cat = {r["work_code"]: r for r in db.all(conn, "SELECT work_code, title FROM composition WHERE client_id = %s AND "
                                                   "source = 'catalogue'", (client_id,))}
    linked = {r["work_code"] for r in db.all(conn, "SELECT DISTINCT c.work_code FROM work_link w JOIN composition c ON "
                                                   "c.id = w.composition_id WHERE w.client_id = %s AND w.status = "
                                                   "'APPROVED'", (client_id,))}
    for r in paid:
        if r["work_code"] not in cat:
            found[("WORK_NOT_IN_CATALOGUE", r["work_code"])] = dict(
                title=r["title"], amount=r["p"], detail=dict(work_code=r["work_code"],
                                                             why="paid in a publishing statement but not in the "
                                                                 "client catalogue - confirm registration and link "
                                                                 "its recordings"))
        elif r["work_code"] not in linked:
            found[("WORK_WITHOUT_RECORDING", r["work_code"])] = dict(
                title=r["title"], amount=r["p"], detail=dict(work_code=r["work_code"],
                                                             why="work is in the catalogue but no recording is "
                                                                 "linked to it"))
        elif similarity(r["title"], cat[r["work_code"]]["title"]) < 0.5:
            found[("TITLE_MISMATCH", r["work_code"])] = dict(
                title=r["title"], amount=r["p"], detail=dict(work_code=r["work_code"], statement_title=r["title"],
                                                             catalogue_title=cat[r["work_code"]]["title"],
                                                             why="statement and catalogue titles differ for the same "
                                                                 "work code - check for a wrong code"))
    existing = {(r["kind"], r["subject_key"]): r for r in db.all(conn, "SELECT * FROM identity_issue WHERE "
                                                                         "client_id = %s", (client_id,))}
    for key, v in found.items():
        if key in existing:
            conn.execute("UPDATE identity_issue SET title = %s, amount = %s, detail = %s WHERE id = %s",
                         (v["title"], v["amount"], db.J(v["detail"]), existing[key]["id"]))
        else:
            db.insert(conn, "identity_issue", dict(client_id=client_id, kind=key[0], subject_key=key[1],
                                                   title=v["title"], amount=v["amount"], detail=v["detail"]))
    gone = [r["id"] for k, r in existing.items() if k not in found and r["status"] != "RESOLVED"]
    if gone:
        conn.execute("DELETE FROM identity_issue WHERE id = ANY(%s)", (gone,))
    return db.scalar(conn, "SELECT count(*) FROM identity_issue WHERE client_id = %s AND status = 'OPEN'",
                     (client_id,))


def _candidates(conn, client_id: int) -> int:
    """C4 proposals: works with money in scope whose titles are the same after transliteration folding
    (version words kept, so covers and lo-fi works never pair with the original)."""
    rows = db.all(conn, """
        SELECT c.id, c.work_code, c.title, c.film FROM composition c WHERE c.client_id = %(c)s AND c.canonical_id IS NULL
        AND (EXISTS (SELECT 1 FROM publishing_line l JOIN source_file s ON s.id = l.file_id WHERE s.client_id = %(c)s
                     AND s.status = 'VALIDATED' AND l.work_code = c.work_code)
          OR EXISTS (SELECT 1 FROM work_link w JOIN recording r ON r.id = w.recording_id JOIN recording_line l
                     ON l.isrc = r.isrc JOIN source_file s ON s.id = l.file_id WHERE w.composition_id = c.id AND
                     w.status = 'APPROVED' AND s.client_id = %(c)s AND s.status = 'VALIDATED'))""", dict(c=client_id))
    groups = defaultdict(list)
    for r in rows:
        k = dup_key(r["title"])
        if len(k) >= 4:
            groups[k].append(r)
    isrcs = defaultdict(set)
    for r in db.all(conn, "SELECT w.composition_id, r.isrc FROM work_link w JOIN recording r ON r.id = w.recording_id "
                          "WHERE w.client_id = %s AND w.status <> 'REJECTED'", (client_id,)):
        isrcs[r["composition_id"]].add(r["isrc"])
    n = 0
    for g in groups.values():
        g.sort(key=lambda x: x["work_code"])
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                a, b = g[i], g[j]
                diff = dict(titles=[a["title"], b["title"]], work_codes=[a["work_code"], b["work_code"]],
                            films=[a["film"], b["film"]], shared_isrcs=sorted(isrcs[a["id"]] & isrcs[b["id"]]),
                            isrcs_a=sorted(isrcs[a["id"]])[:20], isrcs_b=sorted(isrcs[b["id"]])[:20])
                conn.execute("""
                    INSERT INTO duplicate_candidate (client_id, entity, a_id, b_id, score, basis, differences)
                    VALUES (%s, 'COMPOSITION', %s, %s, %s, %s, %s)
                    ON CONFLICT (client_id, entity, a_id, b_id) DO UPDATE SET differences = EXCLUDED.differences""",
                             (client_id, a["id"], b["id"], similarity(a["title"], b["title"]),
                              "same title after transliteration folding; different work codes", db.J(diff)))
                n += 1
    return n


# ------------------------------------------------------------------ C2-C4 decisions
def link(conn, actor: dict, client_id: int, composition_id: int, recording_id: int, reason: str,
         allocation=None, issue_id: int | None = None) -> int:
    if not s(reason):
        raise IdentityError("record the evidence for the link (title, film, composer, performer, version)")
    c = db.one(conn, "SELECT * FROM composition WHERE id = %s AND client_id = %s", (composition_id, client_id))
    r = db.one(conn, "SELECT * FROM recording WHERE id = %s AND client_id = %s", (recording_id, client_id))
    if not c or not r:
        raise IdentityError("unknown work or recording for this client")
    alloc = Decimal(str(allocation)) if s(allocation) else None
    if alloc is not None and not (ZERO < alloc <= ONE):
        raise IdentityError("allocation is a fraction between 0 and 1")
    ev = dict(basis="reviewer decision", score=similarity(c["title"], r["title"]), recording_title=r["title"],
              work_title=c["title"], issue_id=issue_id)
    lid = db.scalar(conn, """
        INSERT INTO work_link (client_id, composition_id, recording_id, basis, evidence, allocation, status,
                               proposed_by, decided_by, decided_at, reason)
        VALUES (%s, %s, %s, 'REVIEWER', %s, %s, 'APPROVED', %s, %s, now(), %s)
        ON CONFLICT (composition_id, recording_id) DO UPDATE SET status = 'APPROVED', allocation = EXCLUDED.allocation,
          decided_by = EXCLUDED.decided_by, decided_at = now(), reason = EXCLUDED.reason
        RETURNING id""", (client_id, composition_id, recording_id, db.J(ev), alloc, actor["id"], actor["id"], reason))
    audit.record(conn, "identity.link_approved", actor, "work_link", lid,
                 dict(work=c["work_code"], isrc=r["isrc"], allocation=alloc, reason=reason, score=ev["score"]))
    return lid


def decide_link(conn, actor: dict, link_id: int, decision: str, reason: str, allocation=None) -> None:
    w = db.one(conn, "SELECT * FROM work_link WHERE id = %s FOR UPDATE", (link_id,))
    if not w:
        raise IdentityError("unknown link")
    if decision not in ("APPROVED", "REJECTED"):
        raise IdentityError("decision is APPROVED or REJECTED")
    if not s(reason):
        raise IdentityError("record the reason")
    alloc = Decimal(str(allocation)) if s(allocation) else None
    if alloc is not None and not (ZERO < alloc <= ONE):
        raise IdentityError("allocation is a fraction between 0 and 1")
    conn.execute("UPDATE work_link SET status = %s, allocation = %s, decided_by = %s, decided_at = now(), reason = %s "
                 "WHERE id = %s", (decision, alloc, actor["id"], reason, link_id))
    audit.record(conn, f"identity.link_{decision.lower()}", actor, "work_link", link_id,
                 dict(allocation=alloc, reason=reason, before=w["status"]))


def resolve_issue(conn, actor: dict, issue_id: int, resolution: str, status: str = "RESOLVED") -> None:
    if status not in ("RESOLVED", "DEFERRED", "OPEN"):
        raise IdentityError("status is RESOLVED, DEFERRED or OPEN")
    if not s(resolution):
        raise IdentityError("record the resolution")
    conn.execute("UPDATE identity_issue SET status = %s, resolution = %s, resolved_by = %s, resolved_at = now() "
                 "WHERE id = %s", (status, resolution, actor["id"], issue_id))
    audit.record(conn, "identity.issue_" + status.lower(), actor, "identity_issue", issue_id,
                 dict(resolution=resolution))


def resolve_conflict(conn, actor: dict, issue_id: int, choices: list[dict], reason: str) -> None:
    """choices: [{link_id, allocation|null, keep: bool}] - kept links' allocations must add up to 1 when more
    than one work keeps the recording."""
    i = db.one(conn, "SELECT * FROM identity_issue WHERE id = %s", (issue_id,))
    if not i or i["kind"] != "ISRC_CONFLICT":
        raise IdentityError("not an ISRC conflict")
    kept = [c for c in choices if c.get("keep")]
    if len(kept) > 1:
        total = sum((Decimal(str(c.get("allocation") or 0)) for c in kept), ZERO)
        if total != ONE:
            raise IdentityError(f"a recording kept under several works needs allocations adding up to 1 (now {total})")
    for c in choices:
        decide_link(conn, actor, int(c["link_id"]), "APPROVED" if c.get("keep") else "REJECTED", reason,
                    c.get("allocation") if len(kept) > 1 else None)
    resolve_issue(conn, actor, issue_id, reason)


def decide_candidate(conn, actor: dict, cand_id: int, decision: str, reason: str) -> None:
    c = db.one(conn, "SELECT * FROM duplicate_candidate WHERE id = %s FOR UPDATE", (cand_id,))
    if not c:
        raise IdentityError("unknown candidate")
    if decision not in ("SAME", "SEPARATE", "DEFERRED"):
        raise IdentityError("decision is SAME, SEPARATE or DEFERRED")
    if not s(reason):
        raise IdentityError("record the reason")
    conn.execute("UPDATE duplicate_candidate SET status = %s, decided_by = %s, decided_at = now(), reason = %s "
                 "WHERE id = %s", (decision, actor["id"], reason, cand_id))
    if decision == "SAME":                    # b points at a; nothing is deleted, the version resolves it
        conn.execute("UPDATE composition SET canonical_id = %s WHERE id = %s AND canonical_id IS NULL",
                     (c["a_id"], c["b_id"]))
    elif c["status"] == "SAME":
        conn.execute("UPDATE composition SET canonical_id = NULL WHERE id = %s AND canonical_id = %s",
                     (c["b_id"], c["a_id"]))
    audit.record(conn, "identity.candidate_" + decision.lower(), actor, "duplicate_candidate", cand_id,
                 dict(a=c["a_id"], b=c["b_id"], reason=reason, before=c["status"]))


# ------------------------------------------------------------------ C5 approved identity version
def _root(conn, client_id: int) -> dict[int, int]:
    parent = {r["id"]: r["canonical_id"] for r in db.all(conn, "SELECT id, canonical_id FROM composition WHERE "
                                                                "client_id = %s", (client_id,))}
    out = {}
    for cid in parent:
        x, seen = cid, set()
        while parent.get(x) and x not in seen:
            seen.add(x)
            x = parent[x]
        out[cid] = x
    return out


def snapshot(conn, client_id: int) -> list[dict]:
    root = _root(conn, client_id)
    rows = db.all(conn, "SELECT composition_id, recording_id, allocation FROM work_link WHERE client_id = %s AND "
                        "status = 'APPROVED'", (client_id,))
    out: dict[tuple[int, int], dict] = {}
    for r in rows:
        k = (root[r["composition_id"]], r["recording_id"])
        if k in out:                                       # two merged works both list this recording: once only
            continue
        out[k] = dict(composition_id=k[0], recording_id=k[1], allocation=r["allocation"])
    return list(out.values())


def version_checks(conn, client_id: int, note: str | None = None) -> tuple[list[dict], dict]:
    snap = snapshot(conn, client_id)
    checks = []
    pending = db.scalar(conn, "SELECT count(*) FROM duplicate_candidate WHERE client_id = %s AND status = 'PENDING'",
                        (client_id,))
    checks.append(dict(gate="C4", check="duplicate candidates decided", result="PASS" if not pending else "HOLD",
                       detail=f"{pending:,} candidate pair(s) awaiting a human decision" if pending else
                       "every proposed duplicate has been decided (same / separate / deferred)"))
    per_rec = defaultdict(list)
    for x in snap:
        per_rec[x["recording_id"]].append(x)
    multiplied = []
    for rid, ls in per_rec.items():
        if len(ls) > 1 and (any(x["allocation"] is None for x in ls) or sum(x["allocation"] for x in ls) != ONE):
            multiplied.append(rid)
        elif len(ls) == 1 and ls[0]["allocation"] is not None and ls[0]["allocation"] != ONE:
            multiplied.append(rid)
    isrc = {r["id"]: r["isrc"] for r in db.all(conn, "SELECT id, isrc FROM recording WHERE id = ANY(%s)",
                                               ([*multiplied] or [0],))}
    checks.append(dict(gate="C5", check="each recording links once at its own level",
                       result="PASS" if not multiplied else "HOLD",
                       detail="no recording income is multiplied across works" if not multiplied else
                       f"{len(multiplied)} recording(s) link to several works without allocations adding to 1: "
                       + ", ".join(sorted(isrc.values())[:10])))
    money = _money_by_isrc(conn, client_id)
    rec_isrc = {r["id"]: r["isrc"] for r in db.all(conn, "SELECT id, isrc FROM recording WHERE client_id = %s",
                                                   (client_id,))}
    mapped_isrcs = {rec_isrc[x["recording_id"]] for x in snap}
    r_mapped = sum((money[i]["r"] for i in mapped_isrcs if i in money), ZERO)
    r_alloc = sum((money[rec_isrc[x["recording_id"]]]["r"] * (x["allocation"] if x["allocation"] is not None else ONE)
                   for x in snap if rec_isrc[x["recording_id"]] in money), ZERO)
    r_all = sum((m["r"] for m in money.values()), ZERO)
    ok_tot = abs(r_mapped - r_alloc) < Decimal("0.000001") or bool(multiplied)
    checks.append(dict(gate="C5", check="totals preserved", result="PASS" if ok_tot else "HOLD",
                       detail=f"recording income on mapped masters {r_mapped:,.2f} = income allocated to works "
                              f"{r_alloc:,.2f}; unmapped {r_all - r_mapped:,.2f} stays visible as an exception"))
    prev = db.one(conn, "SELECT id, version_no FROM identity_version WHERE client_id = %s AND status = 'APPROVED'",
                  (client_id,))
    lost = 0
    if prev:
        old = {(r["composition_id"], r["recording_id"]) for r in db.all(
            conn, "SELECT composition_id, recording_id FROM identity_version_link WHERE version_id = %s", (prev["id"],))}
        new = {(x["composition_id"], x["recording_id"]) for x in snap}
        decided = {(r["composition_id"], r["recording_id"]) for r in db.all(
            conn, "SELECT composition_id, recording_id FROM work_link WHERE client_id = %s AND status = 'REJECTED' "
                  "AND decided_by IS NOT NULL", (client_id,))}
        root = _root(conn, client_id)
        lost = len({k for k in old - new if k not in decided and (root.get(k[0]), k[1]) not in new})
    checks.append(dict(gate="C5", check="no lost sources", result="PASS" if not lost or s(note) else "HOLD",
                       detail=f"{lost} link(s) of v{prev['version_no']} are gone without a reviewer rejection"
                              + (" - noted: " + note if note and lost else " - revert, repair or give a note")
                       if lost else "every earlier link is kept or was rejected by a reviewer"))
    counts = dict(links=len(snap), recordings_linked=len(per_rec), works_linked=len({x["composition_id"] for x in snap}),
                  r_mapped=r_mapped, r_unmapped=r_all - r_mapped, multiplied=len(multiplied))
    return checks, counts


def approve_version(conn, actor: dict, client_id: int, note: str | None = None) -> dict:
    checks, counts = version_checks(conn, client_id, note)
    if any(c["result"] != "PASS" for c in checks):
        audit.record(conn, "identity.rebuild_hold", actor, "client", client_id, dict(checks=checks))
        return dict(ok=False, checks=checks, counts=counts)
    snap = snapshot(conn, client_id)
    no = (db.scalar(conn, "SELECT max(version_no) FROM identity_version WHERE client_id = %s", (client_id,)) or 0) + 1
    conn.execute("UPDATE identity_version SET status = 'SUPERSEDED' WHERE client_id = %s AND status = 'APPROVED'",
                 (client_id,))
    vid = db.insert(conn, "identity_version", dict(client_id=client_id, version_no=no, status="APPROVED", checks=checks,
                                                   counts=counts, note=note, approved_by=actor["id"]))
    db.insert_many(conn, "identity_version_link", ("version_id", "composition_id", "recording_id", "allocation"),
                   ((vid, x["composition_id"], x["recording_id"], x["allocation"])
                    for x in sorted(snap, key=lambda x: (x["composition_id"], x["recording_id"]))))
    audit.record(conn, "identity.version_approved", actor, "identity_version", vid,
                 dict(version_no=no, counts=counts, note=note))
    return dict(ok=True, checks=checks, counts=counts, version_id=vid, version_no=no)


def summary(conn, client_id: int) -> dict:
    r = db.one(conn, """SELECT
        (SELECT count(*) FROM composition WHERE client_id = %(c)s AND canonical_id IS NULL) AS compositions,
        (SELECT count(*) FROM recording WHERE client_id = %(c)s) AS recordings,
        (SELECT count(*) FROM work_link WHERE client_id = %(c)s AND status = 'APPROVED') AS links_approved,
        (SELECT count(*) FROM work_link WHERE client_id = %(c)s AND status = 'PROPOSED') AS links_proposed,
        (SELECT count(*) FROM identity_issue WHERE client_id = %(c)s AND status = 'OPEN') AS issues_open,
        (SELECT count(*) FROM duplicate_candidate WHERE client_id = %(c)s AND status = 'PENDING') AS candidates_pending
        """, dict(c=client_id))
    v = db.one(conn, "SELECT id, version_no, approved_at FROM identity_version WHERE client_id = %s AND status = "
                     "'APPROVED'", (client_id,))
    r["version"] = v
    return r
