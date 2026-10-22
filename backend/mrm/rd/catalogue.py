"""The song catalogue: works (IPRS internal work numbers), recordings (ISRCs) and the links between them.

A catalogue workbook is never applied straight away. It is stored, read row by row and compared with the current
catalogue (a preview); a person looks at the result and applies it. The import is incremental: it only ever adds
works, recordings and links, and flags what disagrees; it never removes or moves anything.

Rules, in the order they are checked for each row:
  * a row with an unreadable ISRC, or with neither a work number nor an ISRC, is INVALID and is not applied
    (documented partial-import policy: valid rows are applied, invalid rows are listed in the error report);
  * the same work number + ISRCs + title as an earlier row is a DUPLICATE row (nothing new);
  * an ISRC claimed by two different works (in the file, or the file against the catalogue) is a CONFLICT: both
    claims are recorded as CONFLICT links, never used for money, until an Admin rejects one and verifies the other;
  * the same work number with a different title is a version when only version words differ (male, cover, lofi …);
    otherwise it is a title conflict: the links are recorded as PENDING and the work is marked for review;
  * a row without an IPRS work number becomes a work 'to register'; its links are PENDING;
  * the same title under different work numbers is a warning only: titles never establish identity.
Clean links from the client's own catalogue are recorded as VERIFIED by the person who applies the import, with the
file and row as evidence (unless that person chooses to verify them later).
"""
from __future__ import annotations

import hashlib
from collections import defaultdict

from .. import audit, db, storage
from ..normalize import base_title, s, title_key, work_code
from ..parsing import reader, safety
from . import access, intake, parsers, xlsx
from .model import REVIEW_LIST, SONG_LIST
from .service import RDError

PAGE = 200
ACTION_LABEL = {
    "NEW_WORK": "New work",
    "EXISTING_WORK_NEW_ISRC": "Existing work, new ISRC",
    "EXISTING_WORK_KNOWN_ISRC": "Existing work, ISRCs already known",
    "NO_WORK_NUMBER": "No IPRS work number (work to register)",
    "CONFLICT": "ISRC linked to another work",
    "DUPLICATE_ROW": "Duplicate row in this file",
    "INVALID": "Invalid row (not applied)",
}
STATUS_LABEL = {"OK": "OK", "WARNING": "Check", "CONFLICT": "Conflict", "DUPLICATE": "Duplicate", "INVALID": "Invalid"}
MAPPING_LABEL = {"VERIFIED": "Verified", "PENDING": "Needs verification", "CONFLICT": "Conflict",
                 "REJECTED": "Rejected"}
WORK_STATUS_LABEL = {"ACTIVE": "Active", "TO_REGISTER": "To register", "REVIEW": "Needs review",
                     "INACTIVE": "Inactive"}


class CatalogueError(RDError):
    pass


# ================================================================== reading a catalogue workbook
def _rows_of(data: bytes, filename: str) -> tuple[str, int, list[dict]]:
    """-> (sheet(s), header row (1-based), rows) with the raw cells and their normalised codes.

    Read flexibly, so the client's catalogue can come in any of its usual shapes: the heading row is found in the
    first rows of each sheet; the song title, the IPRS work number ('Internal No', 'Work No', 'IPRS Song Code 1' …)
    and the ISRCs may be named in many ways; ISRCs (and work numbers) may sit in one cell or spread over several
    columns (ISRC 1 … ISRC 16); an album / film column and a language column are kept when present. Every visible
    sheet with a catalogue table is read."""
    rep = safety.Report()
    try:
        safety.check_bytes(data, filename, rep)
        sheets = reader.parse(data, rep)
    except safety.Rejected as e:
        raise CatalogueError(f"This file cannot be read safely: {e}") from None
    out, names, first_h = [], [], None
    for sh in [x for x in sheets if x.get("state", "visible") == "visible"] or sheets:
        found = parsers.find_table(sh["rows"])
        if not found:
            continue
        h, m = found
        if m["title"] is None or (m["work"] is None and m["isrc"] is None):
            continue
        names.append(sh["title"])
        first_h = first_h or h + 1
        wcols, icols = m.get("work_cols") or [m["work"]], m.get("isrc_cols") or [m["isrc"]]
        wcols, icols = [j for j in wcols if j is not None], [j for j in icols if j is not None]
        for i in range(h + 1, len(sh["rows"])):
            r = sh["rows"][i]
            if not r or all(v is None for v in r):
                continue
            cell = (lambda j: r[j] if j is not None and j < len(r) else None)  # noqa: E731
            raw_title = cell(m["title"])
            title = s(raw_title)
            works, other = parsers.codes_in(r, wcols, parsers.works_of)
            isrcs, bad = parsers.codes_in(r, icols, parsers.isrcs_of)
            if not title and not works and not isrcs and not other and not bad:
                continue
            if title.lower().startswith("total") and not works and not isrcs:
                continue                                   # a TOTAL line under the list, not a song
            album, language = s(cell(m.get("album"))), s(cell(m.get("language")))
            raw = dict(title=s(raw_title), work=" | ".join(s(cell(j)) for j in wcols if s(cell(j))),
                       isrc=" | ".join(s(cell(j)) for j in icols if s(cell(j))))
            if album:
                raw["album"] = album
            if language:
                raw["language"] = language
            out.append(dict(row=i + 1, sheet=sh["title"], title=title, works=works, other=other, isrcs=isrcs,
                            bad=bad, raw=raw))
    if not names:
        raise CatalogueError("We could not find the catalogue table in this workbook: it needs a heading row with the "
                             "song (track) name and the IPRS work number (song code) and/or ISRC columns.")
    return " + ".join(names)[:200], first_h, out


# ================================================================== the current catalogue
def fingerprint(conn, client_id: int) -> str:
    a = db.one(conn, "SELECT count(*) AS n, coalesce(max(id), 0) AS m, max(updated_at) AS u FROM works "
                     "WHERE client_id = %s", (client_id,))
    b = db.one(conn, "SELECT count(*) AS n, coalesce(max(id), 0) AS m, max(updated_at) AS u FROM work_recordings "
                     "WHERE client_id = %s", (client_id,))
    return hashlib.sha256(f"{a['n']}|{a['m']}|{a['u']}|{b['n']}|{b['m']}|{b['u']}".encode()).hexdigest()


def _current(conn, client_id: int) -> dict:
    works = db.all(conn, "SELECT id, internal_work_number, work_title, catalogue_status FROM works "
                         "WHERE client_id = %s AND deleted_at IS NULL", (client_id,))
    links = db.all(conn, "SELECT work_id, isrc, mapping_status FROM current_work_recordings WHERE client_id = %s",
                   (client_id,))
    known = {r["isrc"] for r in db.all(conn, "SELECT isrc FROM recordings")}
    by_no = {w["internal_work_number"]: w for w in works if w["internal_work_number"]}
    unreg = {title_key(w["work_title"]): w for w in works if not w["internal_work_number"]}
    no_of = {w["id"]: (w["internal_work_number"] or f"new:{title_key(w['work_title'])}") for w in works}
    claims: dict[str, set] = defaultdict(set)
    pairs = set()
    for ln in links:
        k = no_of.get(ln["work_id"])
        if k:
            claims[ln["isrc"]].add(k)
            pairs.add((k, ln["isrc"]))
    titles: dict[str, set] = defaultdict(set)
    for w in works:
        if w["internal_work_number"]:
            titles[title_key(w["work_title"])].add(w["internal_work_number"])
    return dict(by_no=by_no, unreg=unreg, claims=claims, pairs=pairs, known=known, titles=titles)


def _version_of(a: str, b: str) -> bool:
    return title_key(a) == title_key(b) or base_title(a) == base_title(b)


# ================================================================== classification (pure: rows + catalogue -> plan)
def classify(rows: list[dict], cur: dict) -> tuple[list[dict], dict]:
    """Each row -> proposed action, validation status, message and per-ISRC detail. Nothing is written."""
    claims: dict[str, set] = defaultdict(set, {k: set(v) for k, v in cur["claims"].items()})
    first_title: dict[str, str] = {}
    file_titles: dict[str, set] = defaultdict(set)
    for r in rows:
        if r["bad"] or (len(r["works"]) > 1):
            continue
        key = r["works"][0] if r["works"] else (f"new:{title_key(r['title'])}" if r["isrcs"] else None)
        if not key:
            continue
        for i in r["isrcs"]:
            claims[i].add(key)
        if r["works"]:
            first_title.setdefault(r["works"][0], r["title"])
            file_titles[title_key(r["title"])].add(r["works"][0])
    conflicted = {i for i, ks in claims.items() if len(ks) > 1}
    seen_sig: dict[tuple, int] = {}
    pairs_done: set = set(cur["pairs"])
    new_recs: set = set()
    new_works: set = set()
    out = []
    n = defaultdict(int)
    for r in rows:
        msgs, flags, detail = [], [], {}
        work = r["works"][0] if len(r["works"]) == 1 else None
        res = dict(row=r["row"], sheet=r.get("sheet"), title=r["title"], work=work, isrcs=r["isrcs"], invalid=r["bad"],
                   raw=r["raw"])
        sig = (work, tuple(sorted(r["isrcs"])), title_key(r["title"]))
        # ---- invalid rows are never applied
        problems = []
        if r["bad"]:
            problems.append("unreadable ISRC " + ", ".join(r["bad"][:5]) + " (an ISRC has 12 characters: 2 letters, "
                            "3 letters or digits, 7 digits)")
        if len(r["works"]) > 1:
            problems.append("more than one work number in one row (" + ", ".join(r["works"]) + ")")
        if not r["works"] and not r["isrcs"]:
            problems.append("no IPRS work number and no ISRC")
        if not r["title"]:
            problems.append("no track name")
        if problems:
            res.update(action="INVALID", status="INVALID", message="; ".join(problems).capitalize() + ".")
            n["invalid"] += 1
            out.append(res)
            continue
        if sig in seen_sig:
            res.update(action="DUPLICATE_ROW", status="DUPLICATE",
                       message=f"Same work number, ISRCs and title as row {seen_sig[sig]}; nothing new.")
            n["duplicate"] += 1
            out.append(res)
            continue
        seen_sig[sig] = r["row"]
        # ---- which work
        if work:
            exists = work in cur["by_no"]
            ref_title = cur["by_no"][work]["work_title"] if exists else first_title.get(work, r["title"])
            created_here = (not exists) and work in new_works
            if not exists and not created_here:
                new_works.add(work)
                action = "NEW_WORK"
            else:
                action = None
            if not _version_of(r["title"], ref_title):
                flags.append("TITLE_CONFLICT")
                msgs.append(f"Work {work} is called '{ref_title}' "
                            f"{'in the catalogue' if exists else 'earlier in this file'}; this row says "
                            f"'{r['title']}'. Its links need verification.")
            others = (cur["titles"].get(title_key(r["title"]), set()) | file_titles.get(title_key(r["title"]), set())) \
                - {work}
            if others:
                flags.append("SAME_TITLE_OTHER_WORK")
                msgs.append("The same title is used by work " + ", ".join(sorted(others)[:4]) + "; titles alone never "
                            "link a song.")
            key = work
        else:
            tk = title_key(r["title"])
            key = f"new:{tk}"
            if tk in cur["unreg"]:
                action = None
            elif key in new_works:
                action = None
            else:
                new_works.add(key)
                action = "NO_WORK_NUMBER"
            flags.append("NO_WORK_NUMBER")
            note = f" ('{', '.join(r['other'])}')" if r["other"] else ""
            msgs.append(f"No IPRS work number{note}: kept as a work to register; its links need verification.")
        # ---- each ISRC
        new_here = 0
        for i in r["isrcs"]:
            if i in conflicted:
                o = sorted(k for k in claims[i] if k != key)
                detail[i] = dict(state="CONFLICT", existing=(key, i) in cur["pairs"],
                                 others=[x if not x.startswith("new:") else "a work to register" for x in o])
                if (key, i) not in pairs_done:
                    pairs_done.add((key, i))
                    n["conflict_links"] += 1
                continue
            if (key, i) in pairs_done:
                detail[i] = dict(state="EXISTING")
                n["existing_links"] += 1
                continue
            pairs_done.add((key, i))
            detail[i] = dict(state="NEW", new_recording=i not in cur["known"] and i not in new_recs)
            if i not in cur["known"]:
                new_recs.add(i)
            new_here += 1
            n["new_links"] += 1
        conflict_isrcs = [i for i, d in detail.items() if d["state"] == "CONFLICT"]
        if conflict_isrcs:
            msgs.insert(0, "ISRC " + ", ".join(conflict_isrcs[:4]) + (" …" if len(conflict_isrcs) > 4 else "")
                        + " is also linked to work " + ", ".join(sorted({o for i in conflict_isrcs
                                                                          for o in detail[i]["others"]})[:4])
                        + ". Both links are kept as conflicts until an Admin decides; neither is used for money.")
        if action is None:
            action = "EXISTING_WORK_NEW_ISRC" if new_here else "EXISTING_WORK_KNOWN_ISRC"
        if conflict_isrcs and action not in ("NEW_WORK", "NO_WORK_NUMBER"):
            action = "CONFLICT"
        if not r["isrcs"]:
            flags.append("NO_ISRC")
            msgs.append("No ISRC in this row.")
        status = "CONFLICT" if conflict_isrcs else ("WARNING" if flags else "OK")
        res.update(action=action, status=status, message=" ".join(msgs) or None, flags=flags, detail=detail,
                   key=key)
        if status == "WARNING":
            n["warning"] += 1
        out.append(res)
    counts = dict(total_rows=len(rows), new_works=len(new_works), new_recordings=len(new_recs),
                  new_mappings=n["new_links"], existing_mappings=n["existing_links"],
                  conflicts=len({i for r in out for i, d in (r.get("detail") or {}).items()
                                 if d["state"] == "CONFLICT"}),
                  conflict_links=n["conflict_links"], duplicate_rows=n["duplicate"], invalid_rows=n["invalid"],
                  warning_rows=n["warning"],
                  by_action={a: sum(1 for r in out if r["action"] == a) for a in ACTION_LABEL})
    return out, counts


# ================================================================== import: preview, apply, discard
def start_import(actor: dict, client_id: int, filename: str, data: bytes) -> dict:
    f, _ = intake.store(actor, client_id, filename, data,
                        {SONG_LIST: "a song catalogue (track name, IPRS work number, ISRC)",
                         REVIEW_LIST: "a song catalogue"},
                        {"STATEMENT": "This is an IPRS statement. Upload it under Statements.",
                         "PLATFORM_REVENUE": "This is a revenue report. Upload it under Statements.",
                         "PREVIOUS_OUTPUT": "This is a master report, not a catalogue."})
    return _preview_from_file(actor, client_id, f, data)


def import_stored(actor: dict, client_id: int, file_id: int) -> dict:
    """Preview a song list that was already uploaded (for example in a processing run)."""
    access.require(actor, "prepare")
    with access.tx(actor, client_id) as conn:
        f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s AND client_id = %s", (file_id, client_id))
    if not f or f["kind"] not in (SONG_LIST, REVIEW_LIST):
        raise CatalogueError("This stored file is not a song list.")
    return _preview_from_file(actor, client_id, f, storage.get("originals", f["object_key"]))


def _preview_from_file(actor: dict, client_id: int, f: dict, data: bytes, import_id: int | None = None) -> dict:
    sheet, header, rows = _rows_of(data, f["filename"])
    with access.tx(actor, client_id) as conn:
        cur = _current(conn, client_id)
        fp = fingerprint(conn, client_id)
        plan, counts = classify(rows, cur)
        vals = dict(status="PREVIEW", source_sheet=sheet, header_row=header, total_rows=counts["total_rows"],
                    new_works_count=counts["new_works"], new_recordings_count=counts["new_recordings"],
                    new_mappings_count=counts["new_mappings"], existing_mappings_count=counts["existing_mappings"],
                    conflict_count=counts["conflicts"], duplicate_rows_count=counts["duplicate_rows"],
                    invalid_rows_count=counts["invalid_rows"], warning_rows_count=counts["warning_rows"],
                    counts=db.J(counts), catalogue_fingerprint=fp)
        if import_id is None:
            import_id = db.insert(conn, "catalogue_imports", dict(
                client_id=client_id, file_id=f["id"], original_filename=f["filename"], file_hash=f["sha256"],
                uploaded_by=actor["id"], **vals))
            audit.record(conn, "catalogue.import_previewed", actor, "catalogue_imports", import_id,
                         dict(filename=f["filename"], **{k: v for k, v in counts.items() if k != "by_action"}))
        else:
            db.update(conn, "catalogue_imports", import_id, vals)
            conn.execute("DELETE FROM catalogue_import_rows WHERE catalogue_import_id = %s", (import_id,))
        db.insert_many(conn, "catalogue_import_rows", (
            "catalogue_import_id", "client_id", "source_sheet", "source_row_number", "raw_row_data",
            "normalized_work_number", "normalized_title", "normalized_isrcs", "invalid_tokens", "proposed_action",
            "validation_status", "validation_message", "details"),
            ((import_id, client_id, r.get("sheet") or sheet, r["row"], db.J(r["raw"]), r["work"], r["title"], r["isrcs"],
              r["invalid"], r["action"], r["status"], r.get("message"),
              db.J(dict(flags=r.get("flags") or [], isrcs=r.get("detail") or {}, key=r.get("key"))))
             for r in plan))
        prior = db.one(conn, "SELECT id, applied_at FROM catalogue_imports WHERE client_id = %s AND file_hash = %s "
                             "AND status = 'APPLIED' AND id <> %s ORDER BY id DESC LIMIT 1",
                       (client_id, f["sha256"], import_id))
    out = import_view(actor, import_id)
    if prior:
        out["note"] = f"This file was already applied on {prior['applied_at']:%d %b %Y} (import #{prior['id']}). " \
                      "Applying it again adds nothing that is already in the catalogue."
    return out


def import_view(actor: dict, import_id: int, status: str | None = None, action: str | None = None,
                offset: int = 0, q: str | None = None) -> dict:
    with access.tx(actor) as conn:
        imp = db.one(conn, "SELECT i.*, u.name AS uploaded_by_name, r.name AS reviewed_by_name FROM catalogue_imports i "
                           "LEFT JOIN app_user u ON u.id = i.uploaded_by LEFT JOIN app_user r ON r.id = i.reviewed_by "
                           "WHERE i.id = %s", (import_id,))
        if not imp:
            raise CatalogueError("This catalogue import does not exist.")
        where = ["catalogue_import_id = %(i)s"]
        p: dict = dict(i=import_id, o=max(0, offset), n=PAGE)
        if status:
            where.append("validation_status = %(s)s")
            p["s"] = status
        if action:
            where.append("proposed_action = %(a)s")
            p["a"] = action
        if q:
            where.append("(normalized_title ILIKE %(q)s OR raw_row_data->>'album' ILIKE %(q)s OR "
                         "normalized_work_number = %(qq)s OR %(qq)s = ANY(normalized_isrcs))")
            p.update(q=f"%{q}%", qq=q.strip().upper())
        rows = db.all(conn, f"SELECT source_row_number AS row, source_sheet AS sheet, normalized_title AS title, "
                            f"normalized_work_number AS work, "
                            f"normalized_isrcs AS isrcs, invalid_tokens AS invalid, proposed_action AS action, "
                            f"validation_status AS status, validation_message AS message, details, raw_row_data AS raw, "
                            f"applied FROM catalogue_import_rows WHERE {' AND '.join(where)} "
                            f"ORDER BY id OFFSET %(o)s LIMIT %(n)s", p)
        total = db.scalar(conn, f"SELECT count(*) FROM catalogue_import_rows WHERE {' AND '.join(where)}", p)
        stale = imp["status"] == "PREVIEW" and imp["catalogue_fingerprint"] != fingerprint(conn, imp["client_id"])
    for r in rows:
        r["action_label"] = ACTION_LABEL.get(r["action"], r["action"])
        r["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
    return dict(id=imp["id"], client_id=imp["client_id"], filename=imp["original_filename"], status=imp["status"],
                file_id=imp["file_id"], sheet=imp["source_sheet"], header_row=imp["header_row"],
                uploaded_by=imp["uploaded_by_name"], uploaded_at=imp["uploaded_at"],
                reviewed_by=imp["reviewed_by_name"], applied_at=imp["applied_at"], counts=imp["counts"],
                verify_mappings=imp["verify_mappings"], stale=stale, rows=rows, total=total, offset=offset, page=PAGE,
                actions=[dict(value=k, label=v) for k, v in ACTION_LABEL.items()],
                statuses=[dict(value=k, label=v) for k, v in STATUS_LABEL.items()], note=None)


def apply_import(actor: dict, import_id: int, verify: bool = True) -> dict:
    """Apply a reviewed preview in one transaction. A preview made against an older catalogue is refreshed instead."""
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        imp = db.one(conn, "SELECT * FROM catalogue_imports WHERE id = %s FOR UPDATE", (import_id,))
        if not imp:
            raise CatalogueError("This catalogue import does not exist.")
        if imp["status"] != "PREVIEW":
            raise CatalogueError(f"This import is {imp['status'].lower()} and cannot be applied again. Upload the file "
                                 "again for a new preview.")
        cid = imp["client_id"]
        conn.execute("SELECT pg_advisory_xact_lock(84726300, %s)", (cid,))      # one catalogue change at a time
        stale = imp["catalogue_fingerprint"] != fingerprint(conn, cid)
        f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (imp["file_id"],))
    if stale:
        out = _preview_from_file(actor, cid, f, storage.get("originals", f["object_key"]), import_id=import_id)
        out["note"] = "The catalogue changed since this preview was made, so the preview was refreshed. Please " \
                      "review it again, then apply."
        out["refreshed"] = True
        return out
    with access.tx(actor, cid) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(84726300, %s)", (cid,))
        if fingerprint(conn, cid) != imp["catalogue_fingerprint"]:
            raise CatalogueError("The catalogue changed while applying. Please try again.")
        rows = db.all(conn, "SELECT * FROM catalogue_import_rows WHERE catalogue_import_id = %s AND validation_status "
                            "NOT IN ('INVALID', 'DUPLICATE') ORDER BY id", (import_id,))
        cur = _current(conn, cid)
        label = f"client catalogue {imp['original_filename']}"
        # 1. works
        work_id: dict[str, int] = {k: w["id"] for k, w in cur["by_no"].items()}
        work_id.update({f"new:{k}": w["id"] for k, w in cur["unreg"].items()})
        review_works: dict[str, list] = defaultdict(list)
        for r in rows:
            key = r["details"].get("key")
            if key and key not in work_id:
                number = None if key.startswith("new:") else key
                work_id[key] = db.insert(conn, "works", dict(
                    client_id=cid, internal_work_number=number, work_title=r["normalized_title"],
                    album=(r["raw_row_data"] or {}).get("album") or None,
                    language=(r["raw_row_data"] or {}).get("language") or None,
                    catalogue_status="ACTIVE" if number else "TO_REGISTER",
                    status_note=None if number else "No IPRS work number in the client catalogue "
                                                    f"(row {r['source_row_number']}).",
                    source_import_id=import_id, created_by=actor["id"]))
            if "TITLE_CONFLICT" in r["details"].get("flags", []):
                review_works[key].append(f"row {r['source_row_number']}: '{r['normalized_title']}'")
        filled = 0                                         # album / language only where the work has none yet
        for r in rows:
            key, raw = r["details"].get("key"), r["raw_row_data"] or {}
            if key in work_id and (raw.get("album") or raw.get("language")):
                filled += conn.execute("UPDATE works SET album = coalesce(album, %s), language = coalesce(language, "
                                       "%s), updated_at = now() WHERE id = %s AND ((album IS NULL AND %s::TEXT IS NOT "
                                       "NULL) OR (language IS NULL AND %s::TEXT IS NOT NULL))",
                                       (raw.get("album") or None, raw.get("language") or None, work_id[key],
                                        raw.get("album") or None, raw.get("language") or None)).rowcount
        for key, notes in review_works.items():
            conn.execute("UPDATE works SET catalogue_status = 'REVIEW', status_note = %s, updated_at = now() "
                         "WHERE id = %s AND catalogue_status = 'ACTIVE'",
                         ("Different titles for this work number in " + label + ": " + "; ".join(notes[:5]),
                          work_id[key]))
        # 2. recordings
        isrcs = sorted({i for r in rows for i, d in r["details"].get("isrcs", {}).items() if d["state"] != "EXISTING"})
        if isrcs:
            conn.execute("INSERT INTO recordings (isrc) SELECT unnest(%s::TEXT[]) ON CONFLICT (isrc) DO NOTHING",
                         (isrcs,))
        rec_id = {r["isrc"]: r["id"] for r in db.all(conn, "SELECT id, isrc FROM recordings WHERE isrc = ANY(%s)",
                                                     (isrcs,))}
        # 3. links
        links, conflict_isrcs = [], set()
        for r in rows:
            key, flags = r["details"].get("key"), r["details"].get("flags", [])
            uncertain = "TITLE_CONFLICT" in flags or "NO_WORK_NUMBER" in flags
            for i, d in r["details"].get("isrcs", {}).items():
                if d["state"] == "EXISTING":
                    continue
                if d["state"] == "CONFLICT":
                    conflict_isrcs.add(i)
                    if d.get("existing"):
                        continue                         # already linked; flagged as a conflict in step 4
                st = "CONFLICT" if d["state"] == "CONFLICT" else ("PENDING" if uncertain or not verify else "VERIFIED")
                links.append((cid, work_id[key], rec_id[i], r["normalized_title"], st, "CLIENT_CATALOGUE", import_id,
                              r["source_row_number"], f"{label}, row {r['source_row_number']}",
                              actor["id"] if st == "VERIFIED" else None, "now" if st == "VERIFIED" else None,
                              actor["id"]))
        seen = set()
        links = [x for x in links if not ((x[1], x[2]) in seen or seen.add((x[1], x[2])))]
        db.insert_many(conn, "work_recordings", (
            "client_id", "work_id", "recording_id", "recording_title", "mapping_status", "mapping_source",
            "source_import_id", "source_row_number", "note", "verified_by", "verified_at", "created_by"), links)
        conn.execute("INSERT INTO mapping_events (client_id, mapping_id, event, to_status, note, actor_id) "
                     "SELECT client_id, id, 'CREATED', mapping_status, %s, %s FROM work_recordings "
                     "WHERE source_import_id = %s", (f"catalogue import #{import_id}", actor["id"], import_id))
        # 4. older links of conflicting ISRCs are flagged too (never moved, never removed)
        flagged = 0
        if conflict_isrcs:
            old = db.all(conn, "SELECT wr.id, wr.mapping_status FROM work_recordings wr JOIN recordings r ON "
                               "r.id = wr.recording_id WHERE wr.client_id = %s AND wr.valid_to IS NULL AND "
                               "wr.mapping_status IN ('PENDING', 'VERIFIED') AND r.isrc = ANY(%s) AND "
                               "(wr.source_import_id IS DISTINCT FROM %s)", (cid, sorted(conflict_isrcs), import_id))
            for o in old:
                conn.execute("UPDATE work_recordings SET mapping_status = 'CONFLICT', verified_by = NULL, "
                             "verified_at = NULL, updated_at = now() WHERE id = %s", (o["id"],))
                db.insert(conn, "mapping_events", dict(client_id=cid, mapping_id=o["id"], event="CONFLICT",
                                                       from_status=o["mapping_status"], to_status="CONFLICT",
                                                       note=f"another work claims this ISRC in import #{import_id}",
                                                       actor_id=actor["id"]), returning=None)
                flagged += 1
        conn.execute("UPDATE catalogue_import_rows SET applied = TRUE, linked_work_id = w.id FROM works w WHERE "
                     "catalogue_import_id = %s AND validation_status NOT IN ('INVALID', 'DUPLICATE') AND w.client_id = "
                     "%s AND w.internal_work_number = catalogue_import_rows.normalized_work_number",
                     (import_id, cid))
        conn.execute("UPDATE catalogue_import_rows SET applied = TRUE WHERE catalogue_import_id = %s AND "
                     "validation_status NOT IN ('INVALID', 'DUPLICATE')", (import_id,))
        db.update(conn, "catalogue_imports", import_id, dict(status="APPLIED", reviewed_by=actor["id"],
                                                             reviewed_at="now", applied_at="now",
                                                             verify_mappings=verify))
        summary = dict(works_created=sum(1 for k in work_id if k not in cur["by_no"] and
                                         k.removeprefix("new:") not in cur["unreg"]),
                       links_created=len(links), conflicts=len(conflict_isrcs), older_links_flagged=flagged,
                       albums_filled=filled,
                       verified=verify)
        audit.record(conn, "catalogue.import_applied", actor, "catalogue_imports", import_id,
                     dict(filename=imp["original_filename"], **summary))
    out = import_view(actor, import_id)
    out["applied"] = summary
    return out


def discard_import(actor: dict, import_id: int) -> dict:
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        imp = db.one(conn, "SELECT * FROM catalogue_imports WHERE id = %s", (import_id,))
        if not imp or imp["status"] != "PREVIEW":
            raise CatalogueError("Only a preview that has not been applied can be discarded.")
        db.update(conn, "catalogue_imports", import_id, dict(status="DISCARDED", reviewed_by=actor["id"],
                                                             reviewed_at="now"))
        audit.record(conn, "catalogue.import_discarded", actor, "catalogue_imports", import_id,
                     dict(filename=imp["original_filename"]))
    return dict(ok=True)


def imports(actor: dict, client_id: int) -> list[dict]:
    with access.tx(actor, client_id) as conn:
        return db.all(conn, "SELECT i.id, i.original_filename AS filename, i.status, i.uploaded_at, i.applied_at, "
                            "i.total_rows, i.new_works_count, i.new_mappings_count, i.conflict_count, "
                            "i.invalid_rows_count, i.duplicate_rows_count, u.name AS uploaded_by FROM catalogue_imports i "
                            "LEFT JOIN app_user u ON u.id = i.uploaded_by WHERE i.client_id = %s ORDER BY i.id DESC "
                            "LIMIT 50", (client_id,))


def stored_song_lists(actor: dict, client_id: int) -> list[dict]:
    with access.tx(actor, client_id) as conn:
        return db.all(conn, "SELECT f.id, f.filename, f.uploaded_at, (f.summary->>'entries')::INT AS entries, "
                            "(SELECT max(applied_at) FROM catalogue_imports i WHERE i.file_id = f.id AND i.status = "
                            "'APPLIED') AS applied_at FROM rd_file f WHERE f.client_id = %s AND f.kind IN "
                            "('SONG_LIST', 'REVIEW_LIST') ORDER BY f.uploaded_at DESC LIMIT 20", (client_id,))


def import_report(actor: dict, import_id: int) -> tuple[str, bytes]:
    """The rows that were not applied as they stand: invalid, duplicate, conflicting and rows to check."""
    v = import_view(actor, import_id)
    with access.tx(actor) as conn:
        rows = db.all(conn, "SELECT * FROM catalogue_import_rows WHERE catalogue_import_id = %s AND validation_status "
                            "<> 'OK' ORDER BY source_row_number", (import_id,))
        audit.record(conn, "export.catalogue_import_report", actor, "catalogue_imports", import_id,
                     dict(rows=len(rows)))
    data = xlsx.book([dict(
        title="Rows to check", heading=[f"Catalogue import #{v['id']} - rows not applied as they stand",
                                        f"File: {v['filename']} (sheet {v['sheet']}, heading row {v['header_row']})",
                                        "Invalid and duplicate rows were not applied. Conflicting ISRCs were recorded as "
                                        "conflicts (not used for money). Rows to check were applied with links that "
                                        "need verification."],
        columns=[("Row", 7, None), ("Track name", 34, None), ("Work number (as written)", 16, None),
                 ("ISRC (as written)", 40, None), ("Result", 12, None), ("What happens", 30, None),
                 ("Why", 80, None)],
        rows=[[r["source_row_number"], r["raw_row_data"].get("title"), r["raw_row_data"].get("work"),
               r["raw_row_data"].get("isrc"), STATUS_LABEL.get(r["validation_status"]),
               ACTION_LABEL.get(r["proposed_action"]), r["validation_message"]] for r in rows])])
    return f"Catalogue_Import_{import_id}_Rows_To_Check.xlsx", data


# ================================================================== the catalogue itself
def _mapping_state(links: list[dict]) -> str:
    st = {ln["status"] for ln in links}
    if not st:
        return "NONE"
    if "CONFLICT" in st:
        return "CONFLICT"
    if "PENDING" in st:
        return "PENDING"
    return "VERIFIED"


def works(actor: dict, client_id: int, q: str | None = None, status: str | None = None, mapping: str | None = None,
          offset: int = 0, limit: int = 100, import_id: int | None = None) -> dict:
    with access.tx(actor, client_id) as conn:
        where, p = ["w.client_id = %(c)s", "w.deleted_at IS NULL"], dict(c=client_id, o=max(0, offset),
                                                                         n=max(1, min(limit, 500)))
        if q:
            where.append("(w.work_title ILIKE %(q)s OR w.album ILIKE %(q)s OR w.internal_work_number = %(qq)s OR EXISTS (SELECT 1 FROM "
                         "current_work_recordings x WHERE x.work_id = w.id AND (x.isrc = %(qu)s OR "
                         "x.recording_title ILIKE %(q)s)))")
            p.update(q=f"%{q.strip()}%", qq=q.strip(), qu=q.strip().upper().replace("-", ""))
        if status:
            where.append("w.catalogue_status = %(st)s")
            p["st"] = status
        if import_id:                                    # the works an import created or linked ISRCs to
            where.append("(w.source_import_id = %(imp)s OR EXISTS (SELECT 1 FROM current_work_recordings x WHERE "
                         "x.work_id = w.id AND x.source_import_id = %(imp)s) OR EXISTS (SELECT 1 FROM "
                         "catalogue_import_rows ir WHERE ir.catalogue_import_id = %(imp)s AND ir.linked_work_id = "
                         "w.id))")
            p["imp"] = int(import_id)
        if mapping == "NONE":
            where.append("NOT EXISTS (SELECT 1 FROM current_work_recordings x WHERE x.work_id = w.id)")
        elif mapping:
            where.append("EXISTS (SELECT 1 FROM current_work_recordings x WHERE x.work_id = w.id AND "
                         "x.mapping_status = %(m)s)")
            p["m"] = mapping
        sql = " AND ".join(where)
        total = db.scalar(conn, f"SELECT count(*) FROM works w WHERE {sql}", p)
        rows = db.all(conn, f"SELECT w.id, w.internal_work_number, w.work_title, w.album, w.language, "
                            f"w.catalogue_status, w.status_note, "
                            f"w.updated_at, coalesce((SELECT json_agg(json_build_object('id', x.id, 'isrc', x.isrc, "
                            f"'status', x.mapping_status, 'title', x.recording_title) ORDER BY x.isrc) FROM "
                            f"current_work_recordings x WHERE x.work_id = w.id), '[]') AS links FROM works w "
                            f"WHERE {sql} ORDER BY lower(w.work_title), w.internal_work_number NULLS LAST "
                            f"OFFSET %(o)s LIMIT %(n)s", p)
        counts = db.one(conn, "SELECT count(*) AS works, count(*) FILTER (WHERE catalogue_status = 'TO_REGISTER') AS "
                              "to_register, count(*) FILTER (WHERE catalogue_status = 'REVIEW') AS review FROM works "
                              "WHERE client_id = %s AND deleted_at IS NULL", (client_id,))
        counts.update(db.one(conn, "SELECT count(*) AS links, count(DISTINCT isrc) AS recordings, count(*) FILTER "
                                   "(WHERE mapping_status = 'VERIFIED') AS verified, count(*) FILTER (WHERE "
                                   "mapping_status = 'PENDING') AS pending, count(*) FILTER (WHERE mapping_status = "
                                   "'CONFLICT') AS conflict FROM current_work_recordings WHERE client_id = %s",
                                   (client_id,)))
        counts["conflict_isrcs"] = db.scalar(conn, "SELECT count(*) FROM isrc_resolution WHERE client_id = %s AND "
                                                   "mapping_status = 'CONFLICT'", (client_id,))
    for r in rows:
        r["mapping_state"] = _mapping_state(r["links"])
        r["status_label"] = WORK_STATUS_LABEL.get(r["catalogue_status"])
    return dict(rows=rows, total=total, offset=offset, counts=counts,
                statuses=[dict(value=k, label=v) for k, v in WORK_STATUS_LABEL.items()],
                mappings=[dict(value=k, label=v) for k, v in MAPPING_LABEL.items() if k != "REJECTED"]
                + [dict(value="NONE", label="No ISRC")])


def work_detail(actor: dict, work_id: int) -> dict:
    with access.tx(actor) as conn:
        w = db.one(conn, "SELECT w.*, u.name AS created_by_name FROM works w LEFT JOIN app_user u ON u.id = "
                         "w.created_by WHERE w.id = %s", (work_id,))
        if not w:
            raise CatalogueError("This work does not exist, or you do not have access to it.")
        links = db.all(conn, "SELECT wr.id, r.isrc, wr.recording_title, wr.mapping_status AS status, wr.mapping_source "
                             "AS source, wr.note, wr.valid_from, wr.valid_to, v.name AS verified_by, wr.verified_at, "
                             "wr.source_import_id, wr.source_row_number FROM work_recordings wr JOIN recordings r ON "
                             "r.id = wr.recording_id LEFT JOIN app_user v ON v.id = wr.verified_by WHERE wr.work_id = "
                             "%s ORDER BY wr.valid_to NULLS FIRST, r.isrc", (work_id,))
        isrcs = [ln["isrc"] for ln in links if ln["valid_to"] is None]
        others = db.all(conn, "SELECT x.isrc, x.work_id, x.internal_work_number, x.work_title, x.mapping_status FROM "
                              "current_work_recordings x WHERE x.client_id = %s AND x.isrc = ANY(%s) AND x.work_id <> %s",
                        (w["client_id"], isrcs, work_id))
        events = db.all(conn, "SELECT e.at, e.event, e.from_status, e.to_status, e.note, u.name AS actor, r.isrc FROM "
                              "mapping_events e JOIN work_recordings wr ON wr.id = e.mapping_id JOIN recordings r ON "
                              "r.id = wr.recording_id LEFT JOIN app_user u ON u.id = e.actor_id WHERE wr.work_id = %s "
                              "ORDER BY e.id DESC LIMIT 100", (work_id,))
    for ln in links:
        ln["status_label"] = MAPPING_LABEL.get(ln["status"])
        ln["current"] = ln["valid_to"] is None
        ln["other_works"] = [o for o in others if o["isrc"] == ln["isrc"]]
    w["status_label"] = WORK_STATUS_LABEL.get(w["catalogue_status"])
    return dict(work=w, links=links, events=events, can_verify=access.can(actor, "verify_mappings"))


def update_work(actor: dict, work_id: int, body: dict) -> dict:
    access.require(actor, "verify_mappings")
    with access.tx(actor) as conn:
        w = db.one(conn, "SELECT * FROM works WHERE id = %s", (work_id,))
        if not w:
            raise CatalogueError("This work does not exist.")
        vals = {}
        if body.get("work_title") is not None:
            t = s(body.get("work_title"))
            if not t:
                raise CatalogueError("A work needs a title.")
            vals["work_title"] = t
        if body.get("catalogue_status"):
            if body["catalogue_status"] not in WORK_STATUS_LABEL:
                raise CatalogueError("Unknown catalogue status.")
            vals["catalogue_status"] = body["catalogue_status"]
        if "status_note" in body:
            vals["status_note"] = s(body.get("status_note")) or None
        for k in ("album", "language"):
            if k in body:
                vals[k] = s(body.get(k)) or None
        if "internal_work_number" in body and not w["internal_work_number"]:
            no = work_code(body.get("internal_work_number"))
            if not no or not no.isdigit():
                raise CatalogueError("An IPRS work number has digits only.")
            if db.scalar(conn, "SELECT id FROM works WHERE client_id = %s AND internal_work_number = %s",
                         (w["client_id"], no)):
                raise CatalogueError(f"Work number {no} is already in the catalogue.")
            vals["internal_work_number"] = no
        if vals:
            db.update(conn, "works", work_id, vals)
            conn.execute("UPDATE works SET updated_at = now() WHERE id = %s", (work_id,))
            audit.record(conn, "catalogue.work_updated", actor, "works", work_id,
                         before={k: w[k] for k in vals}, after=vals)
    return work_detail(actor, work_id)


def _event(conn, client_id, mapping_id, event, frm, to, note, actor) -> None:
    db.insert(conn, "mapping_events", dict(client_id=client_id, mapping_id=mapping_id, event=event, from_status=frm,
                                           to_status=to, note=note, actor_id=actor["id"]), returning=None)


def add_link(actor: dict, work_id: int, body: dict) -> dict:
    """Link an ISRC to a work by hand (for example an ISRC found only in a revenue report). It needs an Admin's
    verification before it can support an enquiry; another work's claim on the same ISRC makes both a conflict."""
    access.require(actor, "prepare")
    from ..normalize import is_isrc, isrc as norm_isrc
    code = norm_isrc(body.get("isrc"))
    if not is_isrc(code):
        raise CatalogueError("Please enter a valid ISRC (12 characters, for example INS2X1400012).")
    verify = bool(body.get("verify")) and access.can(actor, "verify_mappings")
    note = s(body.get("note")) or None
    with access.tx(actor) as conn:
        w = db.one(conn, "SELECT * FROM works WHERE id = %s AND deleted_at IS NULL", (work_id,))
        if not w:
            raise CatalogueError("This work does not exist.")
        conn.execute("SELECT pg_advisory_xact_lock(84726300, %s)", (w["client_id"],))
        conn.execute("INSERT INTO recordings (isrc) VALUES (%s) ON CONFLICT (isrc) DO NOTHING", (code,))
        rid = db.scalar(conn, "SELECT id FROM recordings WHERE isrc = %s", (code,))
        if db.scalar(conn, "SELECT id FROM work_recordings WHERE work_id = %s AND recording_id = %s AND valid_to IS "
                           "NULL", (work_id, rid)):
            raise CatalogueError(f"{code} is already linked to this work.")
        others = db.all(conn, "SELECT id, mapping_status FROM work_recordings WHERE client_id = %s AND recording_id = %s "
                              "AND valid_to IS NULL AND mapping_status <> 'REJECTED'", (w["client_id"], rid))
        st = "CONFLICT" if others else ("VERIFIED" if verify else "PENDING")
        mid = db.insert(conn, "work_recordings", dict(
            client_id=w["client_id"], work_id=work_id, recording_id=rid, recording_title=s(body.get("recording_title"))
            or None, mapping_status=st, mapping_source="MANUAL", note=note,
            verified_by=actor["id"] if st == "VERIFIED" else None, verified_at="now" if st == "VERIFIED" else None,
            created_by=actor["id"]))
        _event(conn, w["client_id"], mid, "CREATED", None, st, note or "linked by hand", actor)
        for o in others:
            if o["mapping_status"] != "CONFLICT":
                conn.execute("UPDATE work_recordings SET mapping_status = 'CONFLICT', verified_by = NULL, verified_at = "
                             "NULL, updated_at = now() WHERE id = %s", (o["id"],))
                _event(conn, w["client_id"], o["id"], "CONFLICT", o["mapping_status"], "CONFLICT",
                       f"{code} was also linked to work {w['internal_work_number'] or w['work_title']}", actor)
        audit.record(conn, "mapping.created", actor, "work_recordings", mid,
                     dict(isrc=code, work=w["internal_work_number"], work_title=w["work_title"], status=st))
    return work_detail(actor, work_id)


def set_link_status(actor: dict, mapping_id: int, status: str, note: str | None) -> dict:
    """Verify, reject or reopen a link (Admin). Rejecting closes the link; it stays in the history."""
    access.require(actor, "verify_mappings")
    if status not in ("VERIFIED", "REJECTED", "PENDING"):
        raise CatalogueError("Choose verify, reject or 'needs verification'.")
    with access.tx(actor) as conn:
        m = db.one(conn, "SELECT wr.*, r.isrc FROM work_recordings wr JOIN recordings r ON r.id = wr.recording_id "
                         "WHERE wr.id = %s", (mapping_id,))
        if not m or m["valid_to"] is not None:
            raise CatalogueError("This link is no longer current.")
        conn.execute("SELECT pg_advisory_xact_lock(84726300, %s)", (m["client_id"],))
        if status == "VERIFIED":
            rivals = db.all(conn, "SELECT x.internal_work_number, x.work_title FROM current_work_recordings x WHERE "
                                  "x.client_id = %s AND x.isrc = %s AND x.id <> %s",
                            (m["client_id"], m["isrc"], mapping_id))
            if rivals:
                raise CatalogueError(f"{m['isrc']} is also linked to work " + ", ".join(
                    r["internal_work_number"] or r["work_title"] for r in rivals) + ". Reject that link first, then "
                    "verify this one.")
            conn.execute("UPDATE work_recordings SET mapping_status = 'VERIFIED', verified_by = %s, verified_at = now(), "
                         "note = coalesce(%s, note), updated_at = now() WHERE id = %s", (actor["id"], note, mapping_id))
        elif status == "REJECTED":
            conn.execute("UPDATE work_recordings SET mapping_status = 'REJECTED', verified_by = NULL, verified_at = NULL, "
                         "valid_to = now(), note = coalesce(%s, note), updated_at = now() WHERE id = %s",
                         (note, mapping_id))
        else:
            conn.execute("UPDATE work_recordings SET mapping_status = 'PENDING', verified_by = NULL, verified_at = NULL, "
                         "updated_at = now() WHERE id = %s", (mapping_id,))
        _event(conn, m["client_id"], mapping_id, {"VERIFIED": "VERIFIED", "REJECTED": "REJECTED",
                                                  "PENDING": "REOPENED"}[status], m["mapping_status"], status, note,
               actor)
        audit.record(conn, f"mapping.{status.lower()}", actor, "work_recordings", mapping_id,
                     dict(isrc=m["isrc"], note=note), before=dict(status=m["mapping_status"]), after=dict(status=status))
    return work_detail(actor, m["work_id"])


def move_link(actor: dict, mapping_id: int, to_work: str, note: str | None) -> dict:
    """Correct a link: the old one is closed (kept in the history) and a verified link to the right work is made."""
    access.require(actor, "verify_mappings")
    if not note:
        raise CatalogueError("Please say why the link is corrected.")
    with access.tx(actor) as conn:
        m = db.one(conn, "SELECT wr.*, r.isrc FROM work_recordings wr JOIN recordings r ON r.id = wr.recording_id "
                         "WHERE wr.id = %s", (mapping_id,))
        if not m or m["valid_to"] is not None:
            raise CatalogueError("This link is no longer current.")
        t = db.one(conn, "SELECT * FROM works WHERE client_id = %s AND deleted_at IS NULL AND (internal_work_number = %s "
                         "OR id::TEXT = %s)", (m["client_id"], s(to_work), s(to_work).removeprefix("id:")))
        if not t or t["id"] == m["work_id"]:
            raise CatalogueError("Choose another work (by its IPRS work number).")
        conn.execute("SELECT pg_advisory_xact_lock(84726300, %s)", (m["client_id"],))
        rivals = db.scalar(conn, "SELECT count(*) FROM current_work_recordings WHERE client_id = %s AND isrc = %s AND "
                                 "id <> %s AND work_id <> %s", (m["client_id"], m["isrc"], mapping_id, t["id"]))
        if rivals:
            raise CatalogueError(f"{m['isrc']} is linked to other works too. Reject those links first.")
        conn.execute("UPDATE work_recordings SET mapping_status = 'REJECTED', valid_to = now(), verified_by = NULL, "
                     "verified_at = NULL, note = %s, updated_at = now() WHERE id = %s",
                     (f"moved to work {t['internal_work_number'] or t['work_title']}: {note}", mapping_id))
        _event(conn, m["client_id"], mapping_id, "MOVED", m["mapping_status"], "REJECTED", note, actor)
        existing = db.one(conn, "SELECT id, mapping_status FROM work_recordings WHERE work_id = %s AND recording_id = %s "
                                "AND valid_to IS NULL", (t["id"], m["recording_id"]))
        if existing:
            conn.execute("UPDATE work_recordings SET mapping_status = 'VERIFIED', verified_by = %s, verified_at = now(), "
                         "updated_at = now() WHERE id = %s", (actor["id"], existing["id"]))
            new_id = existing["id"]
            _event(conn, m["client_id"], new_id, "VERIFIED", existing["mapping_status"], "VERIFIED", note, actor)
        else:
            new_id = db.insert(conn, "work_recordings", dict(
                client_id=m["client_id"], work_id=t["id"], recording_id=m["recording_id"],
                recording_title=m["recording_title"], mapping_status="VERIFIED", mapping_source="CORRECTION",
                note=note, verified_by=actor["id"], verified_at="now", created_by=actor["id"]))
            _event(conn, m["client_id"], new_id, "CREATED", None, "VERIFIED", f"corrected from link {mapping_id}", actor)
        audit.record(conn, "mapping.corrected", actor, "work_recordings", new_id,
                     dict(isrc=m["isrc"], note=note), before=dict(work_id=m["work_id"]), after=dict(work_id=t["id"]))
    return work_detail(actor, t["id"])


def create_work(actor: dict, client_id: int, body: dict) -> dict:
    """Add a work outside a catalogue import (the catalogue is a reference, not a limit): for example an IPRS work that
    the client confirms is theirs. Its ISRC links start as 'needs verification'."""
    access.require(actor, "prepare")
    from ..normalize import is_isrc, isrc as norm_isrc
    title = s(body.get("work_title"))
    no = work_code(body.get("internal_work_number")) if s(body.get("internal_work_number")) else None
    if not title:
        raise CatalogueError("A work needs a title.")
    if no is not None and not no.isdigit():
        raise CatalogueError("An IPRS work number has digits only.")
    isrcs = [norm_isrc(x) for x in parsers.split_codes(body.get("isrcs") or "")]
    bad = [x for x in isrcs if not is_isrc(x)]
    if bad:
        raise CatalogueError("Not a valid ISRC: " + ", ".join(bad[:5]) + ".")
    note = s(body.get("note")) or None
    with access.tx(actor, client_id) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(84726300, %s)", (client_id,))
        if no and db.scalar(conn, "SELECT id FROM works WHERE client_id = %s AND internal_work_number = %s",
                            (client_id, no)):
            raise CatalogueError(f"Work number {no} is already in the catalogue.")
        wid = db.insert(conn, "works", dict(client_id=client_id, internal_work_number=no, work_title=title,
                                            catalogue_status="ACTIVE" if no else "TO_REGISTER",
                                            status_note=note or "added by hand", created_by=actor["id"]))
        audit.record(conn, "catalogue.work_created", actor, "works", wid,
                     dict(work_number=no, title=title, isrcs=isrcs, note=note))
    for i in dict.fromkeys(isrcs):
        add_link(actor, wid, dict(isrc=i, recording_title=title, note=note or "added with the work"))
    return work_detail(actor, wid)


def link_by_number(actor: dict, client_id: int, body: dict) -> dict:
    """Link an ISRC to the work with this IPRS work number (from an unmatched revenue line)."""
    with access.tx(actor, client_id) as conn:
        w = db.one(conn, "SELECT id FROM works WHERE client_id = %s AND internal_work_number = %s AND deleted_at IS "
                         "NULL", (client_id, work_code(body.get("work_number")) or ""))
    if not w:
        raise CatalogueError("No work with this IPRS work number is in the catalogue. Add the work first.")
    return add_link(actor, w["id"], body)


def find_works(actor: dict, client_id: int, q: str) -> list[dict]:
    """Suggestions while someone types a work number or a title: the exact number first, then numbers that start with
    what was typed, then titles that contain it."""
    qq = q.strip()
    if not qq:
        return []
    with access.tx(actor, client_id) as conn:
        return db.all(conn, "SELECT w.id, w.internal_work_number, w.work_title, w.catalogue_status, (SELECT count(*) "
                            "FROM current_work_recordings x WHERE x.work_id = w.id) AS isrcs FROM works w WHERE "
                            "w.client_id = %(c)s AND w.deleted_at IS NULL AND (w.internal_work_number LIKE %(p)s OR "
                            "w.work_title ILIKE %(q)s) ORDER BY (w.internal_work_number = %(qq)s) IS TRUE DESC, "
                            "(w.internal_work_number LIKE %(p)s) IS TRUE DESC, length(w.internal_work_number), "
                            "lower(w.work_title) LIMIT 12",
                      dict(c=client_id, q=f"%{qq}%", qq=qq, p=f"{qq.replace('%', '').replace('_', '')}%"))


def conflicts(actor: dict, client_id: int) -> list[dict]:
    """ISRCs claimed by more than one work, or flagged as a conflict: none of them moves money until resolved."""
    with access.tx(actor, client_id) as conn:
        rows = db.all(conn, "SELECT r.isrc, json_agg(json_build_object('link_id', x.id, 'work_id', x.work_id, "
                            "'work_number', x.internal_work_number, 'work_title', x.work_title, 'status', "
                            "x.mapping_status, 'recording_title', x.recording_title) ORDER BY x.internal_work_number) "
                            "AS claims FROM isrc_resolution r JOIN current_work_recordings x ON x.client_id = "
                            "r.client_id AND x.isrc = r.isrc WHERE r.client_id = %s AND r.mapping_status = 'CONFLICT' "
                            "GROUP BY r.isrc ORDER BY r.isrc", (client_id,))
    return rows


def export(actor: dict, client_id: int) -> tuple[str, bytes]:
    with access.tx(actor, client_id) as conn:
        code = db.scalar(conn, "SELECT code FROM client WHERE id = %s", (client_id,))
        ws = db.all(conn, "SELECT w.id, w.work_title, w.internal_work_number, w.album, w.language, w.catalogue_status, "
                          "w.status_note, "
                          "coalesce(array_agg(x.isrc ORDER BY x.isrc) FILTER (WHERE x.isrc IS NOT NULL), '{}') AS isrcs, "
                          "coalesce(array_agg(x.mapping_status) FILTER (WHERE x.isrc IS NOT NULL), '{}') AS sts FROM "
                          "works w LEFT JOIN current_work_recordings x ON x.work_id = w.id WHERE w.client_id = %s AND "
                          "w.deleted_at IS NULL GROUP BY w.id ORDER BY lower(w.work_title)", (client_id,))
        links = db.all(conn, "SELECT x.internal_work_number, x.work_title, x.isrc, x.recording_title, x.mapping_status, "
                             "x.mapping_source, v.name AS verified_by, x.verified_at, x.note FROM current_work_recordings "
                             "x LEFT JOIN app_user v ON v.id = x.verified_by WHERE x.client_id = %s ORDER BY "
                             "lower(x.work_title), x.isrc", (client_id,))
        audit.record(conn, "export.catalogue", actor, "client", client_id, dict(works=len(ws), links=len(links)))
    data = xlsx.book([
        dict(title="Catalogue", heading=[f"{code} song catalogue", f"{len(ws):,} works, {len(links):,} current ISRC "
                                         "links. ISRCs are joined with ' | ' as in the client's song list."],
             columns=[("Track Name", 40, None), ("Internal NO", 14, None), ("ISRC", 60, None),
                      ("Album / film", 36, None), ("Language", 14, None),
                      ("Catalogue status", 14, None), ("Link status", 18, None), ("Note", 50, None)],
             rows=[[w["work_title"], int(w["internal_work_number"]) if w["internal_work_number"] else None,
                    " | ".join(w["isrcs"]), w["album"], w["language"], WORK_STATUS_LABEL.get(w["catalogue_status"]),
                    MAPPING_LABEL.get(_mapping_state([dict(status=x) for x in w["sts"]]), "No ISRC"),
                    w["status_note"]] for w in ws]),
        dict(title="ISRC links", heading=[f"{code} ISRC-to-work links (current)"],
             columns=[("Internal NO", 14, None), ("Work title", 36, None), ("ISRC", 16, None),
                      ("Recording title", 36, None), ("Status", 18, None), ("Source", 16, None),
                      ("Verified by", 18, None), ("Verified at", 18, "date"), ("Note", 50, None)],
             rows=[[ln["internal_work_number"], ln["work_title"], ln["isrc"], ln["recording_title"],
                    MAPPING_LABEL.get(ln["mapping_status"]), ln["mapping_source"].replace("_", " ").title(),
                    ln["verified_by"], ln["verified_at"].replace(tzinfo=None) if ln["verified_at"] else None,
                    ln["note"]] for ln in links])])
    return f"{code}_Catalogue.xlsx", data


