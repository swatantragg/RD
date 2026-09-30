"""§13 Song-ID-Mismatch report - "where do my sheet, IPRS and the platform disagree about a
song they all know?"

Two fields agree -> the third disagreeing is the finding. A field a source does not carry
is a wildcard: it can never disagree, and it does not block the match either.

    A  Song Name + ISRC         agree  -> Different Internal Number
    B  Song Name + Internal No  agree  -> Different ISRC
    C  Internal No + ISRC       agree  -> Different Song Name

Sources: S2 = the song sheet (name, internal no, ISRC list), S3 = the statement works of
the selected statements (name, internal no), S4 = the platform report's distinct
(name, ISRC) pairs. V2 adds revenue, booked once per work / per ISRC.
"""
from __future__ import annotations

from collections import defaultdict

from ..build.engine import _inv, sheet_entries
from ..core import db
from ..coverage.engine import _month_in, select_inputs
from ..domain.normalize import is_work_no, norm, r2

PRIO = {"S2": 0, "S4": 1, "S3": 2}
KLBL = {"no": "Different Internal Number", "isrc": "Different ISRC", "name": "Different Song Name"}
ORDER = {"Different ISRC": 0, "Different Internal Number": 1, "Different Song Name": 2}


def _records(conn, build_id: int, cfg: dict):
    sel = select_inputs(conn, build_id, cfg)
    sheet = db.row(conn, "SELECT * FROM user_sheet WHERE id = ?", (cfg["sheet_id"],))
    recs = []
    for e in sheet_entries(conn, cfg["sheet_id"]):
        recs.append(dict(src="S2", ord=e["sheet_row"], ref=e["id"], name=e["name"],
                         no=e["work_nos"][0] if e["work_nos"] else None, isrcs=list(e["isrcs"])))
    n3 = 0
    for st in sel["statements"]:
        for b in db.rows(conn, "SELECT id, work_no, synthetic, title FROM statement_block WHERE statement_id = ? "
                               "ORDER BY ordinal", (st["id"],)):
            n3 += 1
            recs.append(dict(src="S3", ord=n3, ref=b["id"], name=b["title"],
                             no=None if b["synthetic"] else b["work_no"], isrcs=[]))
    seen = {}
    months = None
    for rp in sel["reports"]:
        if rp["kind"] != "REVENUE":
            continue
        for ln in db.rows(conn, "SELECT id, month, isrc, content_name FROM platform_line WHERE report_id = ? "
                                "ORDER BY ordinal", (rp["id"],)):
            if not _month_in(ln["month"], cfg.get("period_from"), cfg.get("period_to")):
                continue
            k = (norm(ln["content_name"]), ln["isrc"])
            if k not in seen:
                seen[k] = len(seen)
                recs.append(dict(src="S4", ord=seen[k], ref=ln["id"], name=ln["content_name"], no=None,
                                 isrcs=[ln["isrc"]]))
    for x in recs:
        x["nk"] = norm(x["name"])
    labels = dict(S2=f"{sheet['label']}" + (f" (S-{sheet['s_no']})" if sheet.get("s_no") else ""),
                  S3=_stmt_label(sel["statements"]), S4=_report_label(sel["reports"], cfg))
    return recs, sel, labels, dict(S2=sum(1 for r in recs if r["src"] == "S2"), S3=n3, S4=len(seen))


def _stmt_label(sts) -> str:
    if not sts:
        return "IPRS statements (none selected)"
    if len(sts) == 1:
        s = sts[0]
        return f"IPRS {s['category']} statement S-{s['s_no']} ({s['period']})"
    return f"IPRS statements ({len(sts)} selected)"


def _report_label(reps, cfg) -> str:
    rev = [r for r in reps if r["kind"] == "REVENUE"]
    if not rev:
        return "platform report (none selected)"
    r = rev[0]
    p0 = cfg.get("period_from") or r["month_from"]
    p1 = cfg.get("period_to") or r["month_to"]
    return f"{r['client']} raw MRM ({p0[:7]} to {p1[:7]})"


def compute(conn, build_id: int, cfg: dict) -> dict:
    recs, sel, labels, counts = _records(conn, build_id, cfg)
    name_only, no_only, isrc_only, noint_by_name = (defaultdict(list) for _ in range(4))
    for x in recs:
        if not x["isrcs"]:
            name_only[x["nk"]].append(x)
            if x["no"]:
                no_only[x["no"]].append(x)
        if not x["no"]:
            noint_by_name[x["nk"]].append(x)
            for i in x["isrcs"]:
                isrc_only[i].append(x)
    merged: dict = {}

    def has(rec, kind):
        return bool(rec["no"] if kind == "no" else rec["isrcs"] if kind == "isrc" else rec["name"])

    def pick(kind, core, grp):
        cid = {id(y) for y in core}
        return sorted(grp, key=lambda y: (0 if has(y, kind) else 1, 0 if y["src"] == "S2" else 1,
                                          0 if id(y) in cid else 1, PRIO[y["src"]], y["ord"]))[0]

    def emit(kind, main, values, holders):
        values = {v for v in values if v}
        if not values:
            return
        e = merged.setdefault((main["src"], main["ord"], kind), dict(main=main, kind=kind, vals={}, sheets=set()))
        for v in values:
            e["vals"].setdefault(norm(v) if kind == "name" else v, v)
        e["sheets"] |= holders

    raw_groups = 0
    gA = defaultdict(list)                                           # A: name + ISRC -> internal no
    for x in recs:
        for i in x["isrcs"]:
            gA[(x["nk"], i)].append(x)
    for (n, _i), core in gA.items():
        grp = core + name_only.get(n, [])
        if len({y["no"] for y in grp if y["no"]}) < 2:
            continue
        raw_groups += 1
        main = pick("no", core, grp)
        other = {y["no"] for y in grp if y["no"] and y["no"] != main["no"]}
        emit("no", main, other, {y["src"] for y in grp if y["no"] in other})
    by_name_all = defaultdict(list)
    for x in recs:
        by_name_all[x["nk"]].append(x)
    for n, grp in by_name_all.items():                              # all-wildcard pass for rule A
        if any(y["isrcs"] for y in grp) or len({y["no"] for y in grp if y["no"]}) < 2:
            continue
        raw_groups += 1
        main = pick("no", grp, grp)
        other = {y["no"] for y in grp if y["no"] and y["no"] != main["no"]}
        emit("no", main, other, {y["src"] for y in grp if y["no"] in other})
    gB = defaultdict(list)                                           # B: name + internal no -> ISRC
    for x in recs:
        if x["no"]:
            gB[(x["nk"], x["no"])].append(x)
    for (n, _no), core in gB.items():
        if not any(y["isrcs"] for y in core):
            continue
        grp = core + noint_by_name.get(n, [])
        main = pick("isrc", core, grp)
        ref = set(main["isrcs"])
        extra = {i for y in grp for i in y["isrcs"] if i not in ref}
        if extra:
            raw_groups += 1
        emit("isrc", main, extra, {y["src"] for y in grp if set(y["isrcs"]) & extra})
    gC = defaultdict(list)                                           # C: internal no + ISRC -> name
    for x in recs:
        if x["no"]:
            for i in x["isrcs"]:
                gC[(x["no"], i)].append(x)
    for (no, i), core in gC.items():
        grp = core + no_only.get(no, []) + isrc_only.get(i, [])
        if len({y["nk"] for y in grp}) < 2:
            continue
        raw_groups += 1
        main = pick("name", core, grp)
        other = {}
        for y in grp:
            if y["nk"] != main["nk"]:
                other.setdefault(y["nk"], y["name"])
        emit("name", main, set(other.values()), {y["src"] for y in grp if y["nk"] in other})
    by_no_all = defaultdict(list)
    for x in recs:
        if x["no"]:
            by_no_all[x["no"]].append(x)
    for no, grp in by_no_all.items():                               # all-wildcard pass for rule C
        if any(y["isrcs"] for y in grp) or len({y["nk"] for y in grp}) < 2:
            continue
        raw_groups += 1
        main = pick("name", grp, grp)
        other = {}
        for y in grp:
            if y["nk"] != main["nk"]:
                other.setdefault(y["nk"], y["name"])
        emit("name", main, set(other.values()), {y["src"] for y in grp if y["nk"] in other})

    out = []
    for e in merged.values():
        m = e["main"]
        out.append(dict(kind=KLBL[e["kind"]], main_src=m["src"], main_ref=m["ref"], main_ord=m["ord"],
                        name=m["name"], no=m["no"], isrcs=list(m["isrcs"]),
                        values=sorted(e["vals"].items(), key=lambda kv: kv[1]),
                        sources=[s for s in ("S2", "S3", "S4") if s in e["sheets"]]))
    out.sort(key=lambda d: (ORDER[d["kind"]], norm(d["name"]), d["no"] or ""))

    # ---- V2 revenue, booked once: a work to the first row carrying it, an ISRC likewise
    iprs = defaultdict(float)
    sids = [s["id"] for s in sel["statements"]]
    if sids:
        q = ",".join("?" * len(sids))
        for r in conn.execute(f"SELECT work_no, SUM(amount) FROM royalty_line WHERE statement_id IN ({q}) "
                              f"GROUP BY work_no", sids):
            iprs[r[0]] = r[1]
    mrm = defaultdict(float)
    for rp in sel["reports"]:
        if rp["kind"] == "REVENUE":
            for ln in conn.execute("SELECT isrc, month, value FROM platform_line WHERE report_id = ?", (rp["id"],)):
                if _month_in(ln[1], cfg.get("period_from"), cfg.get("period_to")):
                    mrm[ln[0]] += ln[2]
    seen_no, seen_i = set(), set()
    for d in out:
        v = 0.0
        if d["no"] and d["no"] not in seen_no:
            seen_no.add(d["no"])
            v = iprs.get(d["no"], 0.0)
        d["royalty"] = r2(v)
        v = 0.0
        for i in d["isrcs"]:
            if i not in seen_i:
                seen_i.add(i)
                v += mrm.get(i, 0.0)
        d["gross"] = r2(v)
    totals = dict(iprs_file=r2(sum(iprs.values())), mrm_file=r2(sum(mrm.values())),
                  royalty=r2(sum(d["royalty"] for d in out)), gross=r2(sum(d["gross"] for d in out)))
    totals["both"] = r2(totals["royalty"] + totals["gross"])
    by_kind = {k: sum(1 for d in out if d["kind"] == k) for k in ORDER}
    return dict(rows=out, labels=labels, counts=counts, totals=totals, by_kind=by_kind,
                raw_groups=raw_groups, selection=sel)


def invariants(res: dict) -> list[dict]:
    rows = res["rows"]
    bad10 = 0
    for d in rows:
        own = {"Different Internal Number": d["no"], "Different ISRC": None, "Different Song Name": norm(d["name"])}[d["kind"]]
        for key, text in d["values"]:
            if d["kind"] == "Different ISRC" and text in d["isrcs"]:
                bad10 += 1
            elif own is not None and key == own:
                bad10 += 1
    keys = [(d["main_src"], d["main_ref"], d["kind"]) for d in rows]
    t = res["totals"]
    return [
        _inv("I10", "no conflicting value equals its own row's main value", 0, bad10, bad10 == 0),
        _inv("I11", "no two mismatch rows share (identity record, kind)", f"{len(rows)} rows",
             f"{len(set(keys))} distinct", len(keys) == len(set(keys)),
             f"{res['raw_groups']} raw groups -> {len(rows)} rows"),
        _inv("I13", "V2 royalty ≤ statement total, gross ≤ platform total, TOTAL == column sums",
             f"≤ {t['iprs_file']:,.2f} · ≤ {t['mrm_file']:,.2f}", f"{t['royalty']:,.2f} · {t['gross']:,.2f}",
             t["royalty"] <= t["iprs_file"] + 0.005 and t["gross"] <= t["mrm_file"] + 0.005
             and abs(t["both"] - (t["royalty"] + t["gross"])) <= 0.005),
    ]


def run_mismatch(ctx, conn, build_id: int, cfg: dict, user: str | None = None) -> dict:
    cfg = dict(cfg)
    b = db.row(conn, "SELECT * FROM build_run WHERE id = ?", (build_id,))
    if not b:
        raise ValueError(f"build {build_id} not found")
    cfg["sheet_id"] = cfg.get("sheet_id") or b["catalogue_sheet_id"]
    if not cfg["sheet_id"]:
        raise ValueError("pick the song sheet to compare")
    ctx.progress(0.1, "collecting identity records")
    res = compute(conn, build_id, cfg)
    inv = invariants(res)
    with db.tx(conn):
        rid = db.insert(conn, "mismatch_run", dict(
            build_id=build_id, sheet_id=cfg["sheet_id"], sources_json=db.dumps(res["selection"]["sources"]),
            period_from=cfg.get("period_from"), period_to=cfg.get("period_to"),
            status="ready" if all(i["passed"] for i in inv) else "invariant_failed", row_count=len(res["rows"]),
            counts_json=db.dumps(dict(records=res["counts"], by_kind=res["by_kind"], labels=res["labels"],
                                      raw_groups=res["raw_groups"])),
            totals_json=db.dumps(res["totals"]), invariants_json=db.dumps(inv), created_at=db.now(), created_by=user))
        for n, d in enumerate(res["rows"]):
            mid = db.insert(conn, "mismatch", dict(run_id=rid, ordinal=n, kind=d["kind"], main_src=d["main_src"],
                                                   main_ref=d["main_ref"], main_name=d["name"], main_no=d["no"],
                                                   royalty=d["royalty"], gross=d["gross"]))
            conn.executemany("INSERT INTO mismatch_main_isrc(mismatch_id, isrc, ordinal) VALUES (?,?,?)",
                             [(mid, i, j) for j, i in enumerate(d["isrcs"])])
            conn.executemany("INSERT INTO mismatch_value(mismatch_id, value_key, value_text) VALUES (?,?,?)",
                             [(mid, k, v) for k, v in d["values"]])
            conn.executemany("INSERT INTO mismatch_source(mismatch_id, source) VALUES (?,?)",
                             [(mid, s) for s in d["sources"]])
    msg = (f"mismatch run #{rid}: {len(res['rows'])} rows ({res['by_kind']['Different ISRC']} ISRC · "
           f"{res['by_kind']['Different Internal Number']} internal no · {res['by_kind']['Different Song Name']} name)")
    ctx.log(msg)
    return dict(message=msg, run_id=rid)
