"""§11 Catalogue Coverage Audit - "here is my song sheet; show me every song that is NOT in
it but still earned money from a party".

A source record (a statement work, or a platform ISRC) is EXCLUDED - it is in the sheet -
when any rung fires; the rung and the sheet entry it matched are recorded, so every
excluded song can be explained:

    E1  the record's own internal number is in the sheet                     (L1)
    E2  the record's own ISRC is in the sheet                                (L2)
    E3  no ISRC; an exact title match, unique on both sides, supplies one
        from the platform report; that ISRC is in the sheet                  (L3)  RESOLVED only
    E4  no internal number; an exact title match, unique on both sides,
        supplies one from the statements; that number is in the sheet        (L3)  RESOLVED only

Survivors are merged into one finding per song by norm(name). No figure is copied from the
master build: every amount is recomputed from the raw statement / platform lines.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..build.engine import sheet_entries
from ..core import db
from ..domain.link import NameIndex, l3_recover
from ..domain.normalize import (fy_weights, is_work_no, month_label, norm, penny_fix, printed_total,
                                r2)
from ..build.mrm import aggregate_platform

EVIDENCE_ABSENT = "IDENTIFIERS ABSENT"
EVIDENCE_NAME = "NAME PRESENT, IDENTIFIERS DIFFER"


# ------------------------------------------------------------------ source selection
def available_sources(conn, build_id: int) -> dict:
    sts = db.rows(conn, "SELECT st.id, st.s_no, st.category_code, st.category, st.section, st.society, "
                        "st.period, st.p_start, st.p_end, st.extracted_total, st.dist_no FROM statement st "
                        "JOIN build_statement bs ON bs.statement_id = st.id WHERE bs.build_id = ? "
                        "ORDER BY st.s_no", (build_id,))
    cats: dict[str, dict] = {}
    for st in sts:
        code = f"overseas:{st['society']}" if st["category_code"] == "overseas" and st["society"] else st["category_code"]
        label = st["section"] if st["category_code"] == "overseas" else st["category"]
        c = cats.setdefault(code, dict(code=code, label=label, kind="statement", statements=0, total=0.0))
        c["statements"] += 1
        c["total"] = r2(c["total"] + st["extracted_total"])
    reps = db.rows(conn, "SELECT pr.* FROM platform_report pr JOIN build_report br ON br.report_id = pr.id "
                         "WHERE br.build_id = ? ORDER BY pr.id", (build_id,))
    for rp in reps:
        code = f"{rp['client'].lower()}_{'mrm' if rp['kind'] == 'REVENUE' else 'usage'}"
        label = f"{rp['client']} {'MRM revenue report' if rp['kind'] == 'REVENUE' else 'usage report'}"
        c = cats.setdefault(code, dict(code=code, label=label, kind="platform_" + rp["kind"].lower(),
                                       reports=0, total=0.0, months=[]))
        c["reports"] += 1
        c["total"] = r2(c["total"] + rp["total"])
        c["months"] = sorted(set(c["months"]) | {rp["month_from"], rp["month_to"]} - {None})
    return dict(sources=list(cats.values()), statements=sts, reports=reps)


def _month_in(mk: str, p0: str | None, p1: str | None) -> bool:
    return (not p0 or mk >= p0[:7]) and (not p1 or mk <= p1[:7])


def select_inputs(conn, build_id: int, cfg: dict) -> dict:
    av = available_sources(conn, build_id)
    wanted = set(cfg.get("sources") or [s["code"] for s in av["sources"]])
    p0, p1 = cfg.get("period_from"), cfg.get("period_to")
    q0 = dt.date.fromisoformat(p0[:7] + "-01") if p0 else None
    q1 = dt.date.fromisoformat(p1[:7] + "-01") if p1 else None
    sts = []
    for st in av["statements"]:
        code = f"overseas:{st['society']}" if st["category_code"] == "overseas" and st["society"] else st["category_code"]
        if code not in wanted and st["category_code"] not in wanted:
            continue
        if q0 or q1:
            if not st["p_start"]:
                continue                                   # period unknown - cannot be placed in the window
            s0, s1 = dt.date.fromisoformat(st["p_start"]), dt.date.fromisoformat(st["p_end"])
            if (q1 and s0 > dt.date(q1.year, q1.month, 28)) or (q0 and s1 < q0):
                continue
        sts.append(st)
    reps = [rp for rp in av["reports"]
            if f"{rp['client'].lower()}_{'mrm' if rp['kind'] == 'REVENUE' else 'usage'}" in wanted]
    return dict(statements=sts, reports=reps, sources=sorted(wanted), available=av)


# ------------------------------------------------------------------ the engine
def compute(conn, build_id: int, cfg: dict) -> dict:
    sel = select_inputs(conn, build_id, cfg)
    sheet_id = cfg["sheet_id"]
    entries = sheet_entries(conn, sheet_id)
    sheet_no, sheet_isrc, sheet_name = {}, {}, defaultdict(list)
    for e in entries:
        for w in e["work_nos"]:
            sheet_no.setdefault(w, e)
        for i in e["isrcs"]:
            sheet_isrc.setdefault(i, e)
        if e["name_key"]:
            sheet_name[e["name_key"]].append(e)
    if not entries:
        raise ValueError("the selected sheet has no entries")

    # statement works of the selected statements, by work number
    sids = [s["id"] for s in sel["statements"]]
    st_by_id = {s["id"]: s for s in sel["statements"]}
    works: dict[str, dict] = {}
    if sids:
        q = ",".join("?" * len(sids))
        blocks = db.rows(conn, f"SELECT b.statement_id, b.ordinal, b.work_no, b.synthetic, b.title, b.amount "
                               f"FROM statement_block b JOIN statement st ON st.id = b.statement_id "
                               f"WHERE b.money_lines > 0 AND b.statement_id IN ({q}) ORDER BY st.s_no, b.ordinal",
                         sids)
        for b in blocks:
            w = works.setdefault(b["work_no"], dict(kind="statement_work", ref=b["work_no"],
                                                    work_no=None if b["synthetic"] else b["work_no"],
                                                    name=b["title"], amounts=defaultdict(float), total=0.0))
            if not w["name"] and b["title"]:
                w["name"] = b["title"]
            w["amounts"][b["statement_id"]] += b["amount"]
            w["total"] += b["amount"]
    # platform ISRCs of the selected reports and months
    rev_lines, use_lines = [], []
    for rp in sel["reports"]:
        for ln in db.rows(conn, "SELECT month, isrc, content_name, album, upc, value FROM platform_line "
                                "WHERE report_id = ? ORDER BY ordinal", (rp["id"],)):
            if _month_in(ln["month"], cfg.get("period_from"), cfg.get("period_to")):
                (rev_lines if rp["kind"] == "REVENUE" else use_lines).append(ln)
    rev, rev_meta = aggregate_platform(rev_lines)
    use, use_meta = aggregate_platform(use_lines)
    isrcs: dict[str, dict] = {}
    for i, months in rev.items():
        isrcs[i] = dict(kind="platform_isrc", ref=i, isrc=i, name=rev_meta[i]["title"], album=rev_meta[i]["album"],
                        months=dict(months), total=sum(months.values()), streams=0.0)
    for i, months in use.items():
        rec = isrcs.setdefault(i, dict(kind="platform_isrc", ref=i, isrc=i, name=use_meta[i]["title"],
                                       album=use_meta[i]["album"], months={}, total=0.0, streams=0.0))
        rec["streams"] += sum(months.values())

    stmt_idx = NameIndex(works.values(), lambda r: r["name"])
    plat_idx = NameIndex(isrcs.values(), lambda r: r["name"])
    resolved = cfg.get("mode", "RESOLVED") == "RESOLVED"
    policy = cfg.get("l3_policy", "v2")

    def link_e3(w):
        """statement work (no ISRC) -> the ISRC a title link supplies, or None."""
        if policy == "reference":                     # as the published run: any linked ISRC in the sheet
            hits = plat_idx.get(w["name"])
            return next((h for h in hits if h["isrc"] in sheet_isrc), hits[0] if hits else None)
        return l3_recover(w["name"], stmt_idx, plat_idx)

    def link_e4(p):
        """platform ISRC (no internal number) -> the work a title link supplies, or None."""
        if policy == "reference":                     # as the published run: statement side unique
            return stmt_idx.unique(p["name"])
        return l3_recover(p["name"], plat_idx, stmt_idx)

    rule = "unique on both sides" if policy != "reference" else "reference-run title link"
    exclusions, strict_left, findings_rec = [], [], []
    for w in works.values():
        trace = []
        if w["work_no"] and w["work_no"] in sheet_no:
            exclusions.append(_excl(w, "E1", sheet_no[w["work_no"]], f"internal no {w['work_no']}"))
            continue
        trace.append(dict(rung="E1", passed=False, why=f"internal no {w['work_no'] or '(none)'} is not in the sheet"))
        strict_left.append(w)
        hit = link_e3(w)
        n_st, n_pl = len(stmt_idx.get(w["name"])), len(plat_idx.get(w["name"]))
        if hit and hit["isrc"] in sheet_isrc:
            if resolved:
                exclusions.append(_excl(w, "E3", sheet_isrc[hit["isrc"]],
                                        f"title '{w['name']}' -> ISRC {hit['isrc']} ({rule})"))
                continue
            trace.append(dict(rung="E3", passed=False, why=f"STRICT mode: title link to ISRC {hit['isrc']} "
                                                              "(in the sheet) not applied"))
        else:
            trace.append(dict(rung="E3", passed=False, why=(
                f"title '{w['name']}' -> ISRC {hit['isrc']} is not in the sheet" if hit else
                f"no usable title link: {n_st} statement work(s) and {n_pl} platform ISRC(s) carry this "
                f"title ({rule} required)")))
        w["trace"] = trace
        findings_rec.append(w)
    for p in isrcs.values():
        trace = []
        if p["isrc"] in sheet_isrc:
            exclusions.append(_excl(p, "E2", sheet_isrc[p["isrc"]], f"ISRC {p['isrc']}"))
            continue
        trace.append(dict(rung="E2", passed=False, why=f"ISRC {p['isrc']} is not in the sheet"))
        strict_left.append(p)
        hit = link_e4(p)
        n_st, n_pl = len(stmt_idx.get(p["name"])), len(plat_idx.get(p["name"]))
        if hit and hit["work_no"] and hit["work_no"] in sheet_no:
            if resolved:
                exclusions.append(_excl(p, "E4", sheet_no[hit["work_no"]],
                                        f"title '{p['name']}' -> internal no {hit['work_no']} ({rule})"))
                continue
            trace.append(dict(rung="E4", passed=False, why=f"STRICT mode: title link to internal no "
                                                              f"{hit['work_no']} (in the sheet) not applied"))
        else:
            trace.append(dict(rung="E4", passed=False, why=(
                f"title '{p['name']}' -> internal no {hit['work_no']} is not in the sheet" if hit and hit["work_no"] else
                f"no usable title link: {n_st} statement work(s) and {n_pl} platform ISRC(s) carry this "
                f"title ({rule} required)")))
        p["trace"] = trace
        findings_rec.append(p)

    # songs that would survive E1-E4 - stored with every run so the UI can show the
    # STRICT / RESOLVED delta without a second pass
    resolved_keys = set()
    for rec in findings_rec:
        if not resolved:
            if rec["kind"] == "statement_work":
                hit = link_e3(rec)
                if hit and hit["isrc"] in sheet_isrc:
                    continue
            else:
                hit = link_e4(rec)
                if hit and hit["work_no"] and hit["work_no"] in sheet_no:
                    continue
        resolved_keys.add(norm(rec["name"]) or f"{rec['kind']}:{rec['ref']}")

    # ---- merge survivors into songs by norm(name)
    songs: dict[str, dict] = {}
    for rec in findings_rec:
        key = norm(rec["name"]) or f"{rec['kind']}:{rec['ref']}"
        s = songs.setdefault(key, dict(name_key=key, name=rec["name"] or rec["ref"], stmt=[], plat=[]))
        (s["stmt"] if rec["kind"] == "statement_work" else s["plat"]).append(rec)
    weights = {st["id"]: fy_weights(dt.date.fromisoformat(st["p_start"]) if st["p_start"] else None,
                                    dt.date.fromisoformat(st["p_end"]) if st["p_end"] else None)
               for st in sel["statements"]}
    months_all = sorted({m for p in isrcs.values() for m in p["months"]})
    out = []
    for s in songs.values():
        amounts = defaultdict(float)
        for w in s["stmt"]:
            for sid, a in w["amounts"].items():
                amounts[sid] += a
        cells = {sid: r2(a) for sid, a in amounts.items()}
        months = defaultdict(float)
        for p in s["plat"]:
            for m, v in p["months"].items():
                months[m] += v
        mcells = {m: r2(v) for m, v in sorted(months.items())}
        royalty = printed_total(cells.values())
        platform = printed_total(mcells.values())
        raw_fy = defaultdict(float)
        for sid, a in cells.items():
            wts = weights.get(sid) or {}
            if not wts:
                raw_fy["NA"] += a
            for y, f in wts.items():
                raw_fy[str(y)] += a * f
        fy_keys = sorted(k for k in raw_fy if k != "NA") + (["NA"] if "NA" in raw_fy else [])
        fy = penny_fix({k: raw_fy[k] for k in fy_keys}, royalty) if raw_fy else {}
        nos = sorted({w["work_no"] for w in s["stmt"] if w["work_no"]})
        isr = sorted({p["isrc"] for p in s["plat"]})
        spellings = []
        for rec in s["stmt"] + s["plat"]:
            if rec["name"] and rec["name"] not in spellings:
                spellings.append(rec["name"])
        present = "both" if s["stmt"] and s["plat"] else ("statement" if s["stmt"] else "platform")
        evidence = EVIDENCE_NAME if s["name_key"] in sheet_name else EVIDENCE_ABSENT
        out.append(dict(
            song_name=s["name"], name_key=s["name_key"], work_nos=nos, isrcs=isr, present_in=present,
            evidence=evidence, royalty=royalty, platform_rev=platform,
            streams=sum(p["streams"] for p in s["plat"]),
            detail=dict(statements={str(k): v for k, v in cells.items()}, months=mcells, fy=fy,
                        raw_royalty=sum(amounts.values()), raw_platform=sum(months.values()),
                        spellings=spellings, albums=sorted({p["album"] for p in s["plat"] if p.get("album")}),
                        name_in_sheet=[dict(entry_id=e["id"], name=e["name"], work_nos=e["work_nos"],
                                            isrcs=e["isrcs"]) for e in sheet_name.get(s["name_key"], [])][:5],
                        trace=[dict(record=rec["ref"], kind=rec["kind"], name=rec["name"], tests=rec["trace"])
                               for rec in s["stmt"] + s["plat"]])))
    min_amount = float(cfg.get("min_amount") or 0)
    shown = [o for o in out if (o["royalty"] + o["platform_rev"]) >= min_amount or min_amount <= 0]
    shown.sort(key=lambda o: (-(o["platform_rev"] + o["royalty"]), o["song_name"].upper()))
    rung_counts = defaultdict(int)
    for x in exclusions:
        rung_counts[x["rung"]] += 1
    strict_works = sum(1 for r in strict_left if r["kind"] == "statement_work")
    return dict(
        findings=shown, hidden=len(out) - len(shown), exclusions=exclusions, entries=entries,
        sheet_no=sheet_no, sheet_isrc=sheet_isrc, works=works, isrcs=isrcs, selection=sel,
        months=months_all,
        stats=dict(finding_count=len(shown), strict_count=len(strict_left), strict_works=strict_works,
                   strict_isrcs=len(strict_left) - strict_works,
                   resolved_songs=len(resolved_keys), l3_policy=policy,
                   statement_only=sum(1 for o in shown if o["present_in"] == "statement"),
                   platform_only=sum(1 for o in shown if o["present_in"] == "platform"),
                   both=sum(1 for o in shown if o["present_in"] == "both"),
                   revenue_at_risk=r2(sum(o["platform_rev"] for o in shown)),
                   revenue_at_risk_raw=round(sum(o["detail"]["raw_platform"] for o in shown), 2),
                   royalty_received=r2(sum(o["royalty"] for o in shown)),
                   name_present=sum(1 for o in shown if o["evidence"] == EVIDENCE_NAME),
                   exclusions=dict(rung_counts), statement_works=len(works), platform_isrcs=len(isrcs),
                   statements=len(sel["statements"]), reports=len(sel["reports"]),
                   sheet_entries=len(entries)))


def _excl(rec: dict, rung: str, entry: dict, via: str) -> dict:
    return dict(src_kind=rec["kind"], src_ref=rec["ref"], src_name=rec["name"], rung=rung,
                matched_entry=entry["id"], matched_name=entry["name"], via=via,
                amount=rec["total"])


# ------------------------------------------------------------------ accuracy contract (§11.7)
def invariants(conn, res: dict) -> list[dict]:
    from ..build.engine import _inv
    f = res["findings"]
    leak_no = [o["song_name"] for o in f if any(n in res["sheet_no"] for n in o["work_nos"])]
    leak_is = [o["song_name"] for o in f if any(i in res["sheet_isrc"] for i in o["isrcs"])]
    out = [_inv("I14", "leak test - no finding's internal number is in the audited sheet", 0, len(leak_no),
                not leak_no, ", ".join(leak_no[:5])),
           _inv("I15", "leak test - no finding's ISRC is in the audited sheet", 0, len(leak_is), not leak_is,
                ", ".join(leak_is[:5]))]
    # I17 independent re-derivation: per-ISRC / per-work accumulation straight from the raw lines,
    # by SQL, compared with the engine's per-song figures
    sel = res["selection"]
    sids = [s["id"] for s in sel["statements"]]
    work_raw = defaultdict(float)
    if sids:
        q = ",".join("?" * len(sids))
        for r in conn.execute(f"SELECT work_no, statement_id, SUM(amount) FROM royalty_line WHERE statement_id "
                              f"IN ({q}) GROUP BY work_no, statement_id", sids):
            work_raw[(r[0], r[1])] = r[2]
    isrc_raw = defaultdict(float)
    months = set(res["months"])
    for rp in sel["reports"]:
        if rp["kind"] != "REVENUE":
            continue
        for r in conn.execute("SELECT isrc, month, SUM(value) FROM platform_line WHERE report_id = ? "
                              "GROUP BY isrc, month", (rp["id"],)):
            if r[1] in months:
                isrc_raw[(r[0], r[1])] += r[2]
    stmt_names = {k: v for k, v in res["works"].items()}
    bad = 0
    for o in f:
        keys = [w for w, rec in stmt_names.items() if (norm(rec["name"]) or f"statement_work:{w}") == o["name_key"]
                and rec.get("trace") is not None]
        for sid_s, cell in o["detail"]["statements"].items():
            raw = sum(work_raw.get((w, int(sid_s)), 0.0) for w in keys)
            if abs(r2(raw) - cell) > 0.005:
                bad += 1
        for m, cell in o["detail"]["months"].items():
            raw = sum(isrc_raw.get((i, m), 0.0) for i in o["isrcs"])
            if abs(r2(raw) - cell) > 0.005:
                bad += 1
    out.append(_inv("I17", "every coverage amount re-derived from the raw source lines by an independent pass",
                    "0 mismatches", f"{bad} mismatches", bad == 0))
    # I18 conservation per source
    tot_st = sum(w["total"] for w in res["works"].values())
    tot_pl = sum(p["total"] for p in res["isrcs"].values())
    fnd_st = sum(o["detail"]["raw_royalty"] for o in f)
    fnd_pl = sum(o["detail"]["raw_platform"] for o in f)
    hidden_st = hidden_pl = 0.0
    if res["hidden"]:
        shown = {o["name_key"] for o in f}
        for rec in list(res["works"].values()) + list(res["isrcs"].values()):
            if rec.get("trace") is not None and (norm(rec["name"]) or f"{rec['kind']}:{rec['ref']}") not in shown:
                if rec["kind"] == "statement_work":
                    hidden_st += rec["total"]
                else:
                    hidden_pl += rec["total"]
    ex_st = sum(x["amount"] for x in res["exclusions"] if x["src_kind"] == "statement_work")
    ex_pl = sum(x["amount"] for x in res["exclusions"] if x["src_kind"] == "platform_isrc")
    ok_st = abs((fnd_st + hidden_st + ex_st) - tot_st) <= 0.005
    ok_pl = abs((fnd_pl + hidden_pl + ex_pl) - tot_pl) <= 0.005
    out.append(_inv("I18", "Σ finding revenue + Σ excluded revenue == the source's own total, per source",
                    f"statements {tot_st:,.2f} · platform {tot_pl:,.2f}",
                    f"{fnd_st + hidden_st + ex_st:,.2f} · {fnd_pl + hidden_pl + ex_pl:,.2f}", ok_st and ok_pl))
    unexplained = [x for x in res["exclusions"] if not x["rung"] or not x["matched_entry"]]
    out.append(_inv("I19", "every excluded record carries its rung (E1-E4) and the sheet entry it matched",
                    f"{len(res['exclusions']):,} exclusions", f"{len(res['exclusions']) - len(unexplained):,} explained",
                    not unexplained))
    bad24 = [o["song_name"] for o in f if abs(printed_total(o["detail"]["months"].values()) - o["platform_rev"]) > 0.001
             or abs(printed_total(o["detail"]["statements"].values()) - o["royalty"]) > 0.001]
    out.append(_inv("I24", "a printed total equals the sum of its printed parts (monthly cells vs total)",
                    f"{len(f)}/{len(f)} rows", f"{len(f) - len(bad24)}/{len(f)} rows", not bad24))
    return out


def run_coverage(ctx, conn, build_id: int, cfg: dict, user: str | None = None) -> dict:
    cfg = dict(cfg)
    cfg.setdefault("mode", "RESOLVED")
    b = db.row(conn, "SELECT * FROM build_run WHERE id = ?", (build_id,))
    if not b:
        raise ValueError(f"build {build_id} not found")
    if not cfg.get("sheet_id"):
        cfg["sheet_id"] = b["catalogue_sheet_id"]
    if not cfg.get("sheet_id"):
        raise ValueError("pick the song sheet to audit")
    ctx.progress(0.1, "selecting sources")
    res = compute(conn, build_id, cfg)
    ctx.progress(0.6, f"{res['stats']['finding_count']} findings; checking the accuracy contract")
    inv = invariants(conn, res)
    st = res["stats"]
    with db.tx(conn):
        rid = db.insert(conn, "coverage_run", dict(
            build_id=build_id, sheet_id=cfg["sheet_id"], mode=cfg["mode"], sources_json=db.dumps(res["selection"]["sources"]),
            period_from=cfg.get("period_from"), period_to=cfg.get("period_to"), min_amount=float(cfg.get("min_amount") or 0),
            status="ready" if all(i["passed"] for i in inv) else "invariant_failed", finding_count=st["finding_count"],
            strict_count=st["strict_count"], resolved_count=st["resolved_songs"], revenue_at_risk=st["revenue_at_risk"],
            royalty_received=st["royalty_received"], name_present_count=st["name_present"],
            stats_json=db.dumps(dict(st, statement_ids=[s["id"] for s in res["selection"]["statements"]],
                                     report_ids=[r["id"] for r in res["selection"]["reports"]], months=res["months"])),
            invariants_json=db.dumps(inv), created_at=db.now(), created_by=user))
        for n, o in enumerate(res["findings"]):
            cid = db.insert(conn, "coverage_row", dict(
                run_id=rid, ordinal=n, song_name=o["song_name"], name_key=o["name_key"], evidence=o["evidence"],
                present_in=o["present_in"], royalty=o["royalty"], platform_rev=o["platform_rev"],
                streams=o["streams"], detail_json=db.dumps(o["detail"])))
            conn.executemany("INSERT INTO coverage_row_isrc(row_id, isrc, ordinal) VALUES (?,?,?)",
                             [(cid, i, j) for j, i in enumerate(o["isrcs"])])
            conn.executemany("INSERT INTO coverage_row_work(row_id, work_no, ordinal) VALUES (?,?,?)",
                             [(cid, w, j) for j, w in enumerate(o["work_nos"])])
        conn.executemany("INSERT INTO coverage_exclusion(run_id, src_kind, src_ref, src_name, rung, matched_entry, "
                         "via, amount) VALUES (?,?,?,?,?,?,?,?)",
                         [(rid, x["src_kind"], x["src_ref"], x["src_name"], x["rung"], x["matched_entry"], x["via"],
                           x["amount"]) for x in res["exclusions"]])
    msg = (f"coverage run #{rid} ({cfg['mode']}): {st['finding_count']} songs not in the sheet; "
           f"platform revenue at stake {st['revenue_at_risk']:,.2f}, royalty received {st['royalty_received']:,.2f}")
    ctx.log(msg)
    return dict(message=msg, run_id=rid)


def month_labels(months: list[str]) -> list[str]:
    return [month_label(m) for m in months]
