"""Build orchestration: S5-S8 on the ingested batch -> an immutable build_run (the SKV matrix).

    load inputs -> row universe + book-once -> platform cascade -> usage -> penny-exact cells
    -> FY split / totals / status -> sort -> persist -> invariants -> merge candidates
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..core import config, db, jobs
from ..domain.filename import SECTION_ORDER, dist_display
from ..domain.normalize import fy_label, month_end_of, month_label, norm, norm2, r2
from ..export.style import SECTION_PALETTE, section_palettes
from .derive import assign_status, round_month_cells, round_statement_cells, sort_rows, totals_and_fy
from .model import BASIS, Row
from .mrm import attach_revenue, attach_usage
from .universe import book_statement_money, catalogue_rows

TOL = 0.005


# ------------------------------------------------------------------ inputs
def catalogue_for(conn, batch_id: int, sheet_id: int | None = None) -> dict | None:
    if sheet_id:
        return db.row(conn, "SELECT * FROM user_sheet WHERE id = ?", (sheet_id,))
    return db.row(conn, "SELECT * FROM user_sheet WHERE batch_id = ? AND is_catalogue = 1 "
                        "ORDER BY id DESC LIMIT 1", (batch_id,))


def sheet_entries(conn, sheet_id: int) -> list[dict]:
    entries = db.rows(conn, "SELECT id, ordinal, sheet_row, name, name_key, raw_no FROM user_sheet_entry "
                            "WHERE sheet_id = ? ORDER BY ordinal", (sheet_id,))
    works, isrcs = defaultdict(list), defaultdict(list)
    for r in conn.execute("SELECT w.entry_id, w.work_no FROM user_sheet_entry_work w JOIN user_sheet_entry e "
                          "ON e.id = w.entry_id WHERE e.sheet_id = ? ORDER BY w.entry_id, w.ordinal", (sheet_id,)):
        works[r[0]].append(r[1])
    for r in conn.execute("SELECT i.entry_id, i.isrc FROM user_sheet_entry_isrc i JOIN user_sheet_entry e "
                          "ON e.id = i.entry_id WHERE e.sheet_id = ? ORDER BY i.entry_id, i.ordinal", (sheet_id,)):
        isrcs[r[0]].append(r[1])
    for e in entries:
        e["work_nos"] = works.get(e["id"], [])
        e["isrcs"] = isrcs.get(e["id"], [])
    return entries


def sheet_label(sheet: dict | None) -> str:
    if not sheet:
        return "no catalogue"
    return f"S-{sheet['s_no']}" if sheet.get("s_no") else sheet["label"]


def load_inputs(conn, batch_id: int, cfg: dict) -> dict:
    statements = db.rows(conn, "SELECT st.*, sf.filename FROM statement st JOIN source_file sf ON "
                               "sf.id = st.source_file_id WHERE st.batch_id = ? ORDER BY st.s_no", (batch_id,))
    if cfg.get("statement_ids"):
        keep = set(cfg["statement_ids"])
        statements = [s for s in statements if s["id"] in keep]
    bad = [s for s in statements if not s["reconciled"]]
    if bad and not cfg.get("force"):
        raise ValueError(f"{len(bad)} statement(s) failed reconciliation (e.g. S-{bad[0]['s_no']}) - "
                         "resolve them on the Validation tab, or build with force=true")
    pending = db.scalar(conn, "SELECT COUNT(*) FROM source_file WHERE batch_id = ? AND status = 'uploaded'",
                        (batch_id,))
    if pending:
        raise ValueError(f"{pending} uploaded file(s) are not extracted yet - run Extract first")
    sheet = catalogue_for(conn, batch_id, cfg.get("catalogue_sheet_id"))
    entries = sheet_entries(conn, sheet["id"]) if sheet else []
    sids = [s["id"] for s in statements]
    order = {sid: i for i, sid in enumerate(sids)}
    blocks = []
    if sids:
        q = ",".join("?" * len(sids))
        blocks = db.rows(conn, f"SELECT statement_id, ordinal, work_no, title, amount FROM statement_block "
                               f"WHERE money_lines > 0 AND statement_id IN ({q})", sids)
        blocks.sort(key=lambda b: (order[b["statement_id"]], b["ordinal"]))
    reports = db.rows(conn, "SELECT * FROM platform_report WHERE batch_id = ? ORDER BY id", (batch_id,))
    if cfg.get("report_ids"):
        keep = set(cfg["report_ids"])
        reports = [r for r in reports if r["id"] in keep]
    lines = {"REVENUE": [], "USAGE": []}
    for rp in reports:
        lines[rp["kind"]].extend(db.rows(conn, "SELECT month, isrc, content_name, album, upc, value FROM "
                                               "platform_line WHERE report_id = ? ORDER BY ordinal", (rp["id"],)))
    return dict(statements=statements, sheet=sheet, entries=entries, blocks=blocks, reports=reports,
                revenue_lines=lines["REVENUE"], usage_lines=lines["USAGE"])


# ------------------------------------------------------------------ compute (pure)
def compute_base(inp: dict, cfg: dict) -> dict:
    cat_label = sheet_label(inp["sheet"])
    rev_reports = [r for r in inp["reports"] if r["kind"] == "REVENUE"]
    client = rev_reports[0]["client"] if rev_reports else (inp["reports"][0]["client"] if inp["reports"] else "Spotify")
    rows: list[Row] = []
    by_key: dict[str, Row] = {}
    cat_by_work = catalogue_rows(inp["entries"], rows, by_key)
    book = book_statement_money(inp["blocks"], cat_by_work, rows, by_key)
    rev = attach_revenue(inp["revenue_lines"], rows, by_key, cat_label, client,
                         name_fallback=cfg.get("name_fallback", "exact"))
    use = attach_usage(inp["usage_lines"], rows, by_key)
    round_statement_cells(rows, inp["statements"])
    month_raw: dict[str, float] = defaultdict(float)
    for ln in inp["revenue_lines"]:
        month_raw[ln["month"]] += ln["value"]
    grand = r2(sum(r["total"] for r in rev_reports))
    targets = round_month_cells(rows, dict(month_raw), grand) if month_raw else {}
    totals_and_fy(rows, inp["statements"])
    assign_status(rows, cat_label, len(inp["statements"]), client)
    ordered = sort_rows(rows)
    return dict(rows=ordered, cat_label=cat_label, client=client, month_targets=targets,
                mrm_grand=grand, book=book, revenue=rev, usage=use)


# ------------------------------------------------------------------ layout (band plan)
def build_layout(statements: list[dict], rows: list[Row], month_targets: dict, cat_label: str,
                 client: str, rev_reports: list[dict]) -> dict:
    col_tot: dict[int, float] = defaultdict(float)
    for r in rows:
        for sid, a in r.amounts.items():
            col_tot[sid] += a
    present = sorted({s["section"] for s in statements})
    ordered = [x for x in SECTION_ORDER if x in present or (x == "Spotify MRM" and month_targets)]
    ordered += sorted(x for x in present if x not in SECTION_ORDER)
    pal = section_palettes([x for x in ordered])
    sections = []
    for sec in ordered:
        if sec == "Spotify MRM":
            months = sorted(month_targets)
            label = f"{month_label(months[0])} - {month_label(months[-1])}"
            dist = f"MRM {label}"
            sections.append(dict(
                key="platform", kind="platform", section=sec,
                title=f"{client.upper()} - GROSS REVENUE REPORTED BY {client.upper()} (MRM report)  "
                      f"({label}, {len(months)} month{'s' if len(months) > 1 else ''})",
                band=pal[sec][0], tint=pal[sec][1],
                months=[dict(month=m, label=month_label(m), date=month_end_of(m).isoformat(), dist=dist,
                             total=r2(month_targets[m])) for m in months],
                reports=[dict(id=r["id"], label=r["label"]) for r in rev_reports]))
            continue
        sts = sorted([s for s in statements if s["section"] == sec],
                     key=lambda s: (s["stmt_date"] or "", s["s_no"]))
        n = len(sts)
        base = sec.upper() + (" - ROYALTY DISTRIBUTED BY IPRS" if sec == "Spotify" else "")
        extra = (": " + " and ".join(s["period"] for s in sts)) if sec == "Spotify" else ""
        sections.append(dict(
            key=f"st:{sec}", kind="statement", section=sec,
            title=f"{base}  ({n} distribution{'s' if n > 1 else ''}{extra})",
            band=pal[sec][0], tint=pal[sec][1],
            statements=[dict(id=s["id"], s_no=s["s_no"], sheet=f"S-{s['s_no']}", dist_no=dist_display(s["dist_no"]),
                             date=s["stmt_date"], period=s["period"], category=s["category"],
                             file=s["filename"], total=r2(col_tot.get(s["id"], 0.0)))
                        for s in sts]))
    fy_keys = sorted({k for r in rows for k in r.fy if k != "NA"})
    if any("NA" in r.fy for r in rows):
        fy_keys.append("NA")
    fy_tot = {k: r2(sum(r.fy.get(k, 0.0) for r in rows)) for k in fy_keys}
    return dict(sections=sections, fy_keys=fy_keys, fy_labels={k: fy_label(k) for k in fy_keys},
                fy_totals=fy_tot, cat_label=cat_label, client=client, statement_count=len(statements),
                total_amount=r2(sum(r.total_amount for r in rows)),
                total_mrm=r2(sum(r.total_mrm for r in rows)),
                total_usage=sum(r.usage for r in rows), row_count=len(rows),
                basis_labels=BASIS, palette_known=sorted(SECTION_PALETTE))


# ------------------------------------------------------------------ persist
def persist_build(conn, *, batch_id: int, parent_id: int | None, root_id: int | None, generation: int,
                  cfg: dict, rows: list[Row], layout: dict, stats: dict, statements: list[dict],
                  reports: list[dict], sheet: dict | None, decision_ids: list[int], user: str | None) -> int:
    label = f"SVF-RD-SKV{config.SKV_BASE_GENERATION + generation}"
    with db.tx(conn):
        bid = db.insert(conn, "build_run", dict(
            batch_id=batch_id, parent_build_id=parent_id, root_build_id=root_id, generation=generation,
            label=label, status="building", config_json=db.dumps(cfg), layout_json=db.dumps(layout),
            stats_json=db.dumps(stats), decision_ids_json=db.dumps(decision_ids),
            catalogue_sheet_id=sheet["id"] if sheet else None, row_count=len(rows),
            total_amount=layout["total_amount"], total_mrm=layout["total_mrm"], created_at=db.now(),
            created_by=user))
        if root_id is None:
            conn.execute("UPDATE build_run SET root_build_id = ? WHERE id = ?", (bid, bid))
        conn.executemany("INSERT INTO build_statement(build_id, statement_id) VALUES (?,?)",
                         [(bid, s["id"]) for s in statements])
        conn.executemany("INSERT INTO build_report(build_id, report_id) VALUES (?,?)",
                         [(bid, r["id"]) for r in reports])
        amt, mrm, fy, isr, wrk, mis = [], [], [], [], [], []
        for n, r in enumerate(rows):
            rid = db.insert(conn, "rd_row", dict(
                build_id=bid, row_key=r.key, ordinal=n, origin=r.origin, name=r.name, name_key=norm(r.name),
                name_key2=norm2(r.name), catalogue_entry_id=r.entry_id, total_amount=r.total_amount,
                total_mrm=r.total_mrm, total_usage=r.usage, status=r.status, status_code=r.status_code,
                booked_note=r.booked_note, basis_json=db.dumps(r.basis), notes_json=db.dumps(r.notes),
                merged_keys_json=db.dumps(r.merged_keys), merged_from_decision=r.merged_from_decision))
            amt += [(rid, sid, a, r.raw_amounts.get(sid, 0.0)) for sid, a in r.amounts.items()]
            mrm += [(rid, m, a, r.mrm_raw.get(m, 0.0)) for m, a in r.mrm.items()]
            fy += [(rid, k, a) for k, a in r.fy.items()]
            isr += [(rid, i, j, int(r.isrc_registered[i]), r.isrc_via.get(i)) for j, i in enumerate(r.ordered_isrcs())]
            wrk += [(rid, w, j, int(r.work_registered[w])) for j, w in enumerate(r.ordered_works())]
            mis += [(rid, i, d["basis"], d["revenue"], d.get("title"), d.get("album")) for i, d in r.mrm_isrcs.items()]
        conn.executemany("INSERT INTO rd_row_amount(row_id, statement_id, amount, raw) VALUES (?,?,?,?)", amt)
        conn.executemany("INSERT INTO rd_row_mrm(row_id, month, amount, raw) VALUES (?,?,?,?)", mrm)
        conn.executemany("INSERT INTO rd_row_fy(row_id, fy, amount) VALUES (?,?,?)", fy)
        conn.executemany("INSERT INTO rd_row_isrc(row_id, isrc, ordinal, registered, via) VALUES (?,?,?,?,?)", isr)
        conn.executemany("INSERT INTO rd_row_work(row_id, work_no, ordinal, registered) VALUES (?,?,?,?)", wrk)
        conn.executemany("INSERT INTO rd_row_mrm_isrc(row_id, isrc, basis, revenue, title, album) "
                         "VALUES (?,?,?,?,?,?)", mis)
    return bid


def load_rows(conn, build_id: int) -> list[Row]:
    """Rehydrate a persisted build into Row objects (used by merge apply and exports)."""
    out, by_id = [], {}
    for d in db.rows(conn, "SELECT * FROM rd_row WHERE build_id = ? ORDER BY ordinal", (build_id,)):
        r = Row(key=d["row_key"], origin=d["origin"], name=d["name"], seq=d["ordinal"],
                entry_id=d["catalogue_entry_id"], usage=d["total_usage"], booked_note=d["booked_note"],
                basis=db.loads(d["basis_json"], []), notes=db.loads(d["notes_json"], []),
                merged_keys=db.loads(d["merged_keys_json"], []),
                merged_from_decision=d["merged_from_decision"], total_amount=d["total_amount"],
                total_mrm=d["total_mrm"], status_code=d["status_code"], status=d["status"])
        by_id[d["id"]] = r
        out.append(r)
    q = "SELECT x.* FROM {t} x JOIN rd_row r ON r.id = x.row_id WHERE r.build_id = ? ORDER BY x.row_id{o}"
    for x in conn.execute(q.format(t="rd_row_isrc", o=", x.ordinal"), (build_id,)):
        by_id[x["row_id"]].add_isrc(x["isrc"], bool(x["registered"]), x["via"])
    for x in conn.execute(q.format(t="rd_row_work", o=", x.ordinal"), (build_id,)):
        by_id[x["row_id"]].add_work(x["work_no"], bool(x["registered"]))
    for x in conn.execute(q.format(t="rd_row_amount", o=""), (build_id,)):
        by_id[x["row_id"]].amounts[x["statement_id"]] = x["amount"]
        by_id[x["row_id"]].raw_amounts[x["statement_id"]] = x["raw"]
    for x in conn.execute(q.format(t="rd_row_mrm", o=", x.month"), (build_id,)):
        by_id[x["row_id"]].mrm[x["month"]] = x["amount"]
        by_id[x["row_id"]].mrm_raw[x["month"]] = x["raw"]
    for x in conn.execute(q.format(t="rd_row_fy", o=", x.fy"), (build_id,)):
        by_id[x["row_id"]].fy[x["fy"]] = x["amount"]
    for x in conn.execute(q.format(t="rd_row_mrm_isrc", o=""), (build_id,)):
        by_id[x["row_id"]].mrm_isrcs[x["isrc"]] = dict(basis=x["basis"], revenue=x["revenue"],
                                                       title=x["title"], album=x["album"])
    return out


# ------------------------------------------------------------------ invariants (§20)
def _inv(id_, label, expected, actual, ok, detail=""):
    return dict(id=id_, label=label, expected=expected, actual=actual, passed=bool(ok), detail=detail)


def base_invariants(statements, reports, rows: list[Row], entries, book, month_targets, grand) -> list[dict]:
    out = []
    n = len(statements)
    p1 = sum(1 for s in statements if s["reconciled"])
    out.append(_inv("I1", "every statement: |Σ royalty lines − printed total| ≤ 0.05", f"{n}/{n} PASS",
                    f"{p1}/{n} PASS", p1 == n))
    three = sum(1 for s in statements if s["reconciled"] and (s["subtotal_lines"] == 0 or
                abs(s["extracted_total"] - (s["subtotal_total"] or 0)) <= config.RECON_TOLERANCE))
    out.append(_inv("I2", "every statement: money lines == sub-total lines == printed TOTAL ROYALTIES",
                    f"{n}/{n}", f"{three}/{n}", three == n))
    stopped = sum(1 for s in statements if s["stop_row"])
    out.append(_inv("I3", "extraction stopped before the TOTAL ROYALTIES row", f"{n}/{n}", f"{stopped}/{n}",
                    stopped == n))
    d = r2(sum(r.total_amount for r in rows))
    src = r2(sum(r2(s["file_total"] or 0) for s in statements))
    out.append(_inv("I4", "Σ Total Amount (col D) == Σ statement printed totals", f"{src:,.2f}", f"{d:,.2f}",
                    abs(d - src) <= TOL))
    e = r2(sum(r.total_mrm for r in rows))
    out.append(_inv("I5", "Σ Total platform revenue (col E) == Σ platform revenue report", f"{grand:,.2f}",
                    f"{e:,.2f}", abs(e - grand) <= TOL))
    fy = r2(sum(sum(r.fy.values()) for r in rows))
    out.append(_inv("I6", "Σ FY split == Σ Total Amount", f"{d:,.2f}", f"{fy:,.2f}", abs(fy - d) <= TOL))
    cat_rows = [r for r in rows if r.origin == "catalogue"]
    keys = {r.entry_id for r in cat_rows}
    out.append(_inv("I7", "every catalogue entry has exactly one row", f"{len(entries):,}",
                    f"{len(cat_rows):,} rows / {len(keys):,} entries", len(cat_rows) == len(entries) == len(keys)))
    booked: dict[str, int] = defaultdict(int)
    for r in rows:
        for w in r.owned_works:
            booked[w] += 1
    bad = [w for w, c in booked.items() if c != 1]
    sib = sum(1 for r in rows if r.sibling_of and not r.owned_works)
    out.append(_inv("I8", "every IPRS work with money is booked on exactly one row",
                    f"{len(book['work_amt']):,} works", f"{len(booked) - len(bad):,} booked once · {sib} siblings at 0.00",
                    not bad and len(booked) == len(book["work_amt"])))
    col = defaultdict(float)
    for r in rows:
        for m, a in r.mrm.items():
            col[m] += a
    bad_m = [m for m, t in month_targets.items() if abs(r2(col[m]) - t) > TOL]
    tsum = r2(sum(month_targets.values()))
    out.append(_inv("I9", "every month column sums to that month's total; months sum to the report",
                    f"{len(month_targets)} months → {grand:,.2f}", f"{len(month_targets) - len(bad_m)} ok → {tsum:,.2f}",
                    not bad_m and abs(tsum - grand) <= TOL))
    bad_rows = [r.key for r in rows if abs(r2(sum(r.mrm.values())) - r.total_mrm) > TOL
                or abs(r2(sum(r.amounts.values())) - r.total_amount) > TOL
                or (r.fy and abs(r2(sum(r.fy.values())) - r.total_amount) > TOL)]
    out.append(_inv("I24", "every printed total equals the sum of its printed parts (per row)",
                    f"{len(rows):,}/{len(rows):,}", f"{len(rows) - len(bad_rows):,}/{len(rows):,}", not bad_rows,
                    ", ".join(bad_rows[:5])))
    cat_isrcs = {i for e_ in entries for i in e_["isrcs"]}
    cat_nos = {w for e_ in entries for w in e_["work_nos"]}
    row_isrcs = {i for r in rows for i in r.isrcs}
    row_nos = {w for r in rows for w in r.works}
    lost_i, lost_n = cat_isrcs - row_isrcs, cat_nos - row_nos
    out.append(_inv("I22", "every catalogue internal number and ISRC resolves to a row",
                    f"{len(cat_nos):,} nos · {len(cat_isrcs):,} ISRCs",
                    f"{len(cat_nos - lost_n):,} · {len(cat_isrcs - lost_i):,}", not lost_i and not lost_n))
    return out


# ------------------------------------------------------------------ the job
def run_build(ctx, conn, batch_id: int, cfg: dict, user: str | None = None) -> dict:
    from ..merge.candidates import generate_candidates
    with jobs.batch_lock(batch_id):
        ctx.progress(0.05, "loading statements, catalogue and platform reports")
        inp = load_inputs(conn, batch_id, cfg)
        ctx.progress(0.25, f"S5-S8 over {len(inp['statements'])} statements, {len(inp['entries']):,} catalogue "
                           f"rows, {len(inp['revenue_lines']):,} revenue lines, {len(inp['usage_lines']):,} usage lines")
        res = compute_base(inp, cfg)
        rows = res["rows"]
        rev_reports = [r for r in inp["reports"] if r["kind"] == "REVENUE"]
        layout = build_layout(inp["statements"], rows, res["month_targets"], res["cat_label"], res["client"],
                              rev_reports)
        inv = base_invariants(inp["statements"], inp["reports"], rows, inp["entries"], res["book"],
                              res["month_targets"], res["mrm_grand"])
        by_status = defaultdict(int)
        for r in rows:
            by_status[r.status_code] += 1
        stats = dict(rows=len(rows), catalogue_rows=sum(1 for r in rows if r.origin == "catalogue"),
                     statement_rows=sum(1 for r in rows if r.origin == "statement"),
                     platform_rows=sum(1 for r in rows if r.origin == "platform"),
                     usage_rows=sum(1 for r in rows if r.origin == "usage"),
                     siblings=sum(1 for r in rows if r.status_code == "IN_SIBLING"),
                     by_status=dict(by_status), basis_counts=res["revenue"]["counts"],
                     revenue_isrcs=res["revenue"]["isrcs"], shared_isrc_ties=res["revenue"]["shared_isrcs"],
                     usage=res["usage"] and {
                         k: v for k, v in res["usage"].items() if k != "meta"},
                     name_attached=sum(1 for r in rows for d in r.mrm_isrcs.values()
                                       if d["basis"] in ("B4", "B5", "B6")),
                     statements=len(inp["statements"]), works_paid=len(res["book"]["work_amt"]))
        ctx.progress(0.6, "persisting rows")
        bid = persist_build(conn, batch_id=batch_id, parent_id=None, root_id=None, generation=0, cfg=cfg,
                            rows=rows, layout=layout, stats=stats, statements=inp["statements"],
                            reports=inp["reports"], sheet=inp["sheet"], decision_ids=[], user=user)
        ctx.progress(0.8, "proposing merge candidates (§12)")
        cands = generate_candidates(conn, bid)
        stats["merge_candidates"] = cands
        ok = all(i["passed"] for i in inv)
        conn.execute("UPDATE build_run SET status = ?, invariants_json = ?, stats_json = ? WHERE id = ?",
                     ("ready" if ok else "invariant_failed", db.dumps(inv), db.dumps(stats), bid))
        msg = (f"build #{bid}: {len(rows):,} rows, D={layout['total_amount']:,.2f}, "
               f"E={layout['total_mrm']:,.2f}, invariants {sum(i['passed'] for i in inv)}/{len(inv)}")
        ctx.log(msg)
        return dict(message=msg, build_id=bid, invariants_ok=ok)


def build_summary(conn, build_id: int) -> dict | None:
    b = db.row(conn, "SELECT * FROM build_run WHERE id = ?", (build_id,))
    if not b:
        return None
    b["config"] = db.loads(b.pop("config_json"), {})
    b["layout"] = db.loads(b.pop("layout_json"), {})
    b["stats"] = db.loads(b.pop("stats_json"), {})
    b["invariants"] = db.loads(b.pop("invariants_json"), [])
    b["decision_ids"] = db.loads(b.pop("decision_ids_json"), [])
    return b


def as_date(v):
    return dt.date.fromisoformat(v) if isinstance(v, str) and v else v
