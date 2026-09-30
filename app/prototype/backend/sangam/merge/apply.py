"""§12.3-12.4 record merge decisions and apply them into a NEW build.

Applying never edits a delivered build. Decisions are data, stored against the lineage root
by stable row keys, and every apply folds the complete set of active decisions into the
root build - so un-ticking a group and re-applying produces a build identical to the one
before that decision existed (reversibility), and the same decisions always produce the
same build (determinism, I25).

The fold is the SKV8 E2 rule: numeric cells added; ISRCs and internal numbers joined,
registered first, then the unregistered ones; the merge written into the provenance notes.
Money neutrality is asserted, not assumed (I20): a merge that changes a total aborts.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from ..build.engine import _inv, build_layout, load_rows, persist_build
from ..core import config, db, jobs
from ..domain.normalize import r2
from ..build.derive import sort_rows
from ..build.model import Row
from .candidates import generate_candidates


class Forbidden(Exception):
    pass


def _expand(conn, row_ids: list[int]) -> dict[int, list[str]]:
    out = {}
    for r in db.rows(conn, f"SELECT id, row_key, merged_keys_json FROM rd_row WHERE id IN "
                           f"({','.join('?' * len(row_ids))})", row_ids):
        out[r["id"]] = [r["row_key"]] + db.loads(r["merged_keys_json"], [])
    return out


def record_decisions(conn, build_id: int, decisions: list[dict], user: str, role: str) -> list[int]:
    if role not in config.DECIDER_ROLES:
        raise Forbidden("only an analyst or admin may record a merge decision")
    b = db.row(conn, "SELECT id, root_build_id FROM build_run WHERE id = ?", (build_id,))
    if not b:
        raise KeyError(build_id)
    ids = []
    with db.tx(conn):
        for d in decisions:
            c = db.row(conn, "SELECT * FROM merge_candidate WHERE id = ? AND build_id = ?",
                       (d["candidate_id"], build_id))
            if not c:
                raise ValueError(f"candidate {d['candidate_id']} does not belong to build {build_id}")
            allowed = {r["rd_row_id"] for r in db.rows(conn, "SELECT rd_row_id FROM merge_candidate_member WHERE "
                                                             "candidate_id = ?", (c["id"],))}
            verdict = d["verdict"]
            if verdict not in ("MERGE", "NOT_THE_SAME"):
                raise ValueError("verdict must be MERGE or NOT_THE_SAME")
            members = [int(m) for m in (d.get("members") or sorted(allowed))]
            if not set(members) <= allowed:
                raise ValueError("members must be rows of the candidate group")
            survivor_key = None
            if verdict == "MERGE":
                if len(members) < 2:
                    raise ValueError("tick at least two rows to merge")
                surv = int(d.get("survivor_row") or c["default_survivor"])
                if surv not in members:
                    surv = members[0]
                survivor_key = db.scalar(conn, "SELECT row_key FROM rd_row WHERE id = ?", (surv,))
            conn.execute("UPDATE merge_decision SET active = 0, revoked_by = ?, revoked_at = ? WHERE "
                         "root_build_id = ? AND kind = ? AND name_key = ? AND active = 1",
                         (user, db.now(), b["root_build_id"], c["kind"], c["name_key"]))
            did = db.insert(conn, "merge_decision", dict(
                root_build_id=b["root_build_id"], source_build_id=build_id, candidate_id=c["id"], kind=c["kind"],
                name_key=c["name_key"], display_name=c["display_name"], verdict=verdict, survivor_key=survivor_key,
                confidence=c["confidence"], evidence_json=c["signals_json"], decided_by=user, decided_at=db.now(),
                note=d.get("note"), active=1))
            keys = []
            for ks in _expand(conn, members).values():
                keys += ks
            conn.executemany("INSERT OR IGNORE INTO merge_decision_member(decision_id, row_key) VALUES (?,?)",
                             [(did, k) for k in keys])
            conn.execute("UPDATE merge_candidate SET status = ? WHERE id = ?",
                         ("merged" if verdict == "MERGE" else "not_same", c["id"]))
            ids.append(did)
    return ids


def revoke_decision(conn, decision_id: int, user: str, role: str) -> dict:
    if role not in config.DECIDER_ROLES:
        raise Forbidden("only an analyst or admin may undo a merge decision")
    d = db.row(conn, "SELECT * FROM merge_decision WHERE id = ?", (decision_id,))
    if not d:
        raise KeyError(decision_id)
    with db.tx(conn):
        conn.execute("UPDATE merge_decision SET active = 0, revoked_by = ?, revoked_at = ? WHERE id = ?",
                     (user, db.now(), decision_id))
        conn.execute("UPDATE merge_candidate SET status = 'open' WHERE build_id IN (SELECT id FROM build_run "
                     "WHERE root_build_id = ?) AND kind = ? AND name_key = ?",
                     (d["root_build_id"], d["kind"], d["name_key"]))
    return dict(id=decision_id, active=False)


def decision_log(conn, root_build_id: int) -> list[dict]:
    out = db.rows(conn, "SELECT * FROM merge_decision WHERE root_build_id = ? ORDER BY id DESC", (root_build_id,))
    for d in out:
        d["members"] = [r["row_key"] for r in db.rows(conn, "SELECT row_key FROM merge_decision_member WHERE "
                                                            "decision_id = ? ORDER BY row_key", (d["id"],))]
        d["evidence"] = db.loads(d.pop("evidence_json"), [])
    return out


# ------------------------------------------------------------------ the fold
def fold(root_rows: list[Row], decisions: list[dict]) -> tuple[list[Row], list[dict]]:
    parent = {r.key: r.key for r in root_rows}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    survivor_of_group: dict[str, str] = {}
    for d in decisions:
        keys = [k for k in d["members"] if k in parent]
        for k in keys[1:]:
            a, b = find(keys[0]), find(k)
            if a != b:
                parent[b] = a
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in root_rows:
        groups[find(r.key)].append(r)
    for d in decisions:                                   # the latest decision names the survivor
        keys = [k for k in d["members"] if k in parent]
        if keys and d.get("survivor_key") in parent:
            survivor_of_group[find(keys[0])] = d["survivor_key"]
    dec_of = {}
    for d in decisions:
        for k in d["members"]:
            if k in parent:
                dec_of[find(k)] = d
    out, log = [], []
    for gk, members in groups.items():
        if len(members) == 1:
            out.append(members[0])
            continue
        skey = survivor_of_group.get(gk, gk)
        surv = next((m for m in members if m.key == skey), members[0])
        others = [m for m in members if m is not surv]
        d = dec_of.get(gk, {})
        merged = _merge(surv, others, d)
        out.append(merged)
        log.append(dict(decision=d.get("id"), survivor=surv.key, name=surv.name, absorbed=[o.key for o in others],
                        works=merged.ordered_works(), isrcs=merged.ordered_isrcs()))
    return out, log


def _merge(surv: Row, others: list[Row], decision: dict) -> Row:
    m = Row(key=surv.key, origin=surv.origin, name=surv.name, seq=surv.seq, entry_id=surv.entry_id,
            usage=surv.usage, booked_note=surv.booked_note, status_code=surv.status_code, status=surv.status)
    m.amounts, m.raw_amounts = dict(surv.amounts), dict(surv.raw_amounts)
    m.mrm, m.mrm_raw, m.fy = dict(surv.mrm), dict(surv.mrm_raw), dict(surv.fy)
    m.mrm_isrcs = dict(surv.mrm_isrcs)
    m.basis, m.notes = list(surv.basis), list(surv.notes)
    m.merged_keys = list(surv.merged_keys)
    m.total_amount, m.total_mrm = surv.total_amount, surv.total_mrm
    everyone = [surv] + others
    for i in [i for r in everyone for i in r.ordered_isrcs() if r.isrc_registered[i]]:
        m.add_isrc(i, True, next(r.isrc_via.get(i) for r in everyone if i in r.isrc_registered))
    for i in [i for r in everyone for i in r.ordered_isrcs() if not r.isrc_registered[i]]:
        m.add_isrc(i, False, next(r.isrc_via.get(i) for r in everyone if i in r.isrc_registered))
    for w in [w for r in everyone for w in r.ordered_works() if r.work_registered[w]]:
        m.add_work(w, True)
    for w in [w for r in everyone for w in r.ordered_works() if not r.work_registered[w]]:
        m.add_work(w, False)
    for o in others:
        for sid, a in o.amounts.items():
            m.amounts[sid] = r2(m.amounts.get(sid, 0.0) + a)
            m.raw_amounts[sid] = m.raw_amounts.get(sid, 0.0) + o.raw_amounts.get(sid, 0.0)
        for mo, a in o.mrm.items():
            m.mrm[mo] = r2(m.mrm.get(mo, 0.0) + a)
            m.mrm_raw[mo] = m.mrm_raw.get(mo, 0.0) + o.mrm_raw.get(mo, 0.0)
        for k, a in o.fy.items():
            m.fy[k] = r2(m.fy.get(k, 0.0) + a)
        m.total_amount = r2(m.total_amount + o.total_amount)
        m.total_mrm = r2(m.total_mrm + o.total_mrm)
        m.usage += o.usage
        m.mrm_isrcs.update(o.mrm_isrcs)
        for b in o.basis:
            m.add_basis(b)
        m.notes += [n for n in o.notes if n not in m.notes]
        if o.booked_note and o.booked_note not in (m.booked_note or ""):
            m.booked_note = " ; ".join(x for x in (m.booked_note, o.booked_note) if x)
        m.merged_keys += [o.key] + o.merged_keys
    m.fy = {k: m.fy[k] for k in sorted(m.fy, key=lambda k: (k == "NA", k))}
    absorbed_nos = [w for o in others for w in o.ordered_works()]
    who = f" - decision #{decision['id']} by {decision['decided_by']}" if decision.get("id") else ""
    m.notes.append(f"merged {len(others)} row(s) with the same song name "
                   f"(internal no {', '.join(absorbed_nos) or 'none'}){who}")
    unreg = [i for i in m.ordered_isrcs() if not m.isrc_registered[i]]
    if unreg and surv.origin == "catalogue":
        note = f"ISRC {', '.join(unreg)} reported by a platform but NOT registered in the catalogue"
        if note not in m.notes:
            m.notes.append(note)
    unreg_no = [w for w in m.ordered_works() if not m.work_registered[w]]
    if unreg_no and surv.origin == "catalogue":
        m.notes.append(f"internal no {', '.join(unreg_no)} paid by a statement but NOT in the catalogue")
    m.merged_from_decision = decision.get("id")
    return m


def content_sha(rows: list[Row]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps([r.key, r.name, r.ordered_isrcs(), r.ordered_works(), sorted(r.amounts.items()),
                             sorted(r.mrm.items()), sorted(r.fy.items()), r.total_amount, r.total_mrm, r.status,
                             r.notes, r.basis], sort_keys=True, default=str).encode())
    return h.hexdigest()


def _column_sums(rows: list[Row]) -> dict[str, float]:
    s: dict[str, float] = defaultdict(float)
    for r in rows:
        s["D"] += r.total_amount
        s["E"] += r.total_mrm
        for sid, a in r.amounts.items():
            s[f"stmt:{sid}"] += a
        for m, a in r.mrm.items():
            s[f"month:{m}"] += a
        for k, a in r.fy.items():
            s[f"fy:{k}"] += a
    return {k: r2(v) for k, v in s.items()}


def apply_merges(ctx, conn, build_id: int, user: str, role: str) -> dict:
    if role not in config.DECIDER_ROLES:
        raise Forbidden("only an analyst or admin may apply merges")
    b = db.row(conn, "SELECT * FROM build_run WHERE id = ?", (build_id,))
    if not b:
        raise KeyError(build_id)
    root = b["root_build_id"]
    with jobs.batch_lock(b["batch_id"]):
        decisions = db.rows(conn, "SELECT * FROM merge_decision WHERE root_build_id = ? AND active = 1 AND "
                                  "verdict = 'MERGE' ORDER BY id", (root,))
        for d in decisions:
            d["members"] = [r["row_key"] for r in db.rows(conn, "SELECT row_key FROM merge_decision_member WHERE "
                                                                "decision_id = ? ORDER BY row_key", (d["id"],))]
        ctx.progress(0.1, f"folding {len(decisions)} active merge decision(s) into the root build #{root}")
        root_rows = load_rows(conn, root)
        parent_rows = load_rows(conn, build_id) if build_id != root else root_rows
        rows, log = fold(root_rows, decisions)
        rows = sort_rows(rows)
        before, after = _column_sums(parent_rows), _column_sums(rows)
        drift = {k: (before.get(k, 0.0), after.get(k, 0.0)) for k in set(before) | set(after)
                 if abs(before.get(k, 0.0) - after.get(k, 0.0)) > 0.005}
        inv = [_inv("I20", "a merge apply changes no column total (D, E, every distribution, month and FY column)",
                    f"{len(before)} columns identical", f"{len(before) - len(drift)} identical", not drift,
                    "; ".join(f"{k}: {v[0]:,.2f} -> {v[1]:,.2f}" for k, v in list(drift.items())[:5]))]
        if drift:
            raise ValueError(f"money neutrality violated on {len(drift)} column(s) - apply aborted: {inv[0]['detail']}")
        root_i = {i for r in root_rows for i in r.isrcs}
        new_i = {i for r in rows for i in r.isrcs}
        root_w = {w for r in root_rows for w in r.works}
        new_w = {w for r in rows for w in r.works}
        inv.append(_inv("I21", "a merge loses no identifier", f"{len(root_w):,} internal nos · {len(root_i):,} ISRCs",
                        f"{len(new_w):,} · {len(new_i):,}", root_i <= new_i and root_w <= new_w))
        cat_nos = {w for r in root_rows if r.origin == "catalogue" for w in r.works if r.work_registered[w]}
        inv.append(_inv("I22", "every catalogue internal number still resolves to a row", f"{len(cat_nos):,}",
                        f"{len(cat_nos & new_w):,}", cat_nos <= new_w))
        where = {}
        for r in rows:
            for k in [r.key] + r.merged_keys:
                where[k] = r.key
        split = [d["id"] for d in decisions if len({where.get(k) for k in d["members"] if k in where}) > 1]
        inv.append(_inv("I23", "after apply, every MERGE decision's rows occupy exactly one row", 0, len(split),
                        not split))
        bad24 = [r.key for r in rows if abs(r2(sum(r.amounts.values())) - r.total_amount) > 0.005
                 or abs(r2(sum(r.mrm.values())) - r.total_mrm) > 0.005
                 or (r.fy and abs(r2(sum(r.fy.values())) - r.total_amount) > 0.005)]
        inv.append(_inv("I24", "every printed total equals the sum of its printed parts", len(rows), len(rows) - len(bad24),
                        not bad24))
        sha = content_sha(rows)
        dec_ids = sorted(d["id"] for d in decisions)
        twin = None
        for other in db.rows(conn, "SELECT id, decision_ids_json, stats_json FROM build_run WHERE root_build_id = ?",
                             (root,)):
            if sorted(db.loads(other["decision_ids_json"], [])) == dec_ids:
                twin = (other["id"], db.loads(other["stats_json"], {}).get("content_sha"))
        if twin and twin[1]:
            inv.append(_inv("I25", "same inputs + same decisions => identical build", f"build #{twin[0]} content",
                            "identical" if twin[1] == sha else "DIFFERENT", twin[1] == sha))
        statements = db.rows(conn, "SELECT st.*, sf.filename FROM statement st JOIN source_file sf ON sf.id = "
                                   "st.source_file_id JOIN build_statement bs ON bs.statement_id = st.id WHERE "
                                   "bs.build_id = ? ORDER BY st.s_no", (root,))
        reports = db.rows(conn, "SELECT pr.* FROM platform_report pr JOIN build_report br ON br.report_id = pr.id "
                                "WHERE br.build_id = ? ORDER BY pr.id", (root,))
        root_b = db.row(conn, "SELECT * FROM build_run WHERE id = ?", (root,))
        root_layout = db.loads(root_b["layout_json"], {})
        month_targets = {m["month"]: m["total"] for s in root_layout["sections"] if s["kind"] == "platform"
                         for m in s["months"]}
        layout = build_layout(statements, rows, month_targets, root_layout["cat_label"], root_layout["client"],
                              [r for r in reports if r["kind"] == "REVENUE"])
        by_status: dict[str, int] = defaultdict(int)
        for r in rows:
            by_status[r.status_code] += 1
        stats = dict(db.loads(root_b["stats_json"], {}), rows=len(rows), merged_away=len(root_rows) - len(rows),
                     merges=log, content_sha=sha, parent_build=build_id, decisions=dec_ids, by_status=dict(by_status),
                     **{f"{o}_rows": sum(1 for r in rows if r.origin == o)
                        for o in ("catalogue", "statement", "platform", "usage")},
                     siblings=by_status.get("IN_SIBLING", 0))
        stats.pop("merge_candidates", None)
        sheet = db.row(conn, "SELECT * FROM user_sheet WHERE id = ?", (root_b["catalogue_sheet_id"],)) \
            if root_b["catalogue_sheet_id"] else None
        ctx.progress(0.6, "persisting the new build")
        bid = persist_build(conn, batch_id=b["batch_id"], parent_id=build_id, root_id=root,
                            generation=b["generation"] + 1, cfg=dict(db.loads(root_b["config_json"], {}),
                                                                      applied_decisions=dec_ids),
                            rows=rows, layout=layout, stats=stats, statements=statements, reports=reports,
                            sheet=sheet, decision_ids=dec_ids, user=user)
        cands = generate_candidates(conn, bid)
        stats["merge_candidates"] = cands
        root_inv = [i for i in db.loads(root_b["invariants_json"], []) if i["id"] not in {x["id"] for x in inv}]
        allinv = root_inv + inv
        ok = all(i["passed"] for i in allinv)
        conn.execute("UPDATE build_run SET status = ?, invariants_json = ?, stats_json = ? WHERE id = ?",
                     ("ready" if ok else "invariant_failed", db.dumps(allinv), db.dumps(stats), bid))
        msg = (f"build #{bid} from #{build_id}: {len(decisions)} decision(s) applied, {len(root_rows) - len(rows)} "
               f"row(s) merged away, money-neutral on {len(before)} columns")
        ctx.log(msg)
        return dict(message=msg, build_id=bid, invariants_ok=ok)
