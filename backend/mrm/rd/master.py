"""The master view: every catalogue work with its linked ISRCs and what is behind it, platform by platform: the
platform revenue and usage (plays) from the platform reports, what the client's statements show and what IPRS paid.

Totals are always summed from the normalised source records (client_revenue_records, platform_usage_records,
iprs_royalty_records) at the moment they are read for the period chosen; nothing is stored separately, so nothing can
drift, and the usage of any period is there whenever it is needed. The kinds are shown side by side, never added
together. Facebook, Instagram, Meta (IPRS's single licence) and YouTube stay separate platforms.

The SKV export rebuilds the client's master workbook (the SVF-RD-SKV8 layout) from the same records with the
proven report engine: the catalogue is the song list, every imported statement in the selection is a distribution
(the client's statements with the platform revenue reports, or the statements received from IPRS).
"""
from __future__ import annotations

import datetime as dt
import threading
from collections import OrderedDict
from decimal import Decimal

from .. import audit, db
from ..normalize import month_end, title_key
from . import access, assemble, engine, excel, names, rules, verify, xlsx
from .model import SongEntry
from .service import SOFTWARE, RDError
from .store import load_data

ZERO = Decimal("0")
SORTS = {"revenue": "revenue_total DESC NULLS LAST", "royalty": "royalty_total DESC NULLS LAST",
         "usage": "usage_total DESC NULLS LAST", "client": "client_total DESC NULLS LAST",
         "revenue_asc": "revenue_total ASC NULLS LAST", "title": "lower(w.work_title)",
         "title_desc": "lower(w.work_title) DESC", "work": "w.internal_work_number NULLS LAST",
         "updated": "w.updated_at DESC"}


class MasterError(RDError):
    pass


def _filters(f: dict) -> dict:
    a = f.get("period_from")
    b = f.get("period_to")
    a = dt.date.fromisoformat(str(a)[:10]) if a else None
    b = dt.date.fromisoformat(str(b)[:10]) if b else None
    if a:
        a = a.replace(day=1)
    if b:
        b = month_end(b.year, b.month)
    if a and b and b < a:
        raise MasterError("The period ends before it starts.")
    return dict(a=a, b=b, pl=int(f["platform_id"]) if f.get("platform_id") else None,
                s=int(f["statement_id"]) if f.get("statement_id") else None)


_PERIOD_ISRC = ("(%(a)s::DATE IS NULL OR r.usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR r.usage_period_end "
                "<= %(b)s) AND (%(pl)s::BIGINT IS NULL OR r.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                "r.statement_id = %(s)s)")
_PERIOD_WORK = ("(%(a)s::DATE IS NULL OR (i.usage_period_start >= %(a)s AND i.usage_period_end <= %(b)s)) AND "
                "(%(pl)s::BIGINT IS NULL OR i.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR i.statement_id = "
                "%(s)s)")


def _work_lines(side: str) -> str:
    """Per-work lines of one kind (CLIENT = the client's statements, IPRS = what IPRS paid) that reach a work."""
    return ("SELECT i.work_id, coalesce(i.platform_id, 0) || ':W' AS platform_id, i.royalty_amount AS amount FROM "
            f"iprs_royalty_records i WHERE i.client_id = %(c)s AND i.import_status = 'IMPORTED' AND i.statement_source = "
            f"'{side}' AND i.work_id IS NOT NULL AND {_PERIOD_WORK}")


REV_LINES = ("SELECT r.work_id, coalesce(r.platform_id, 0) || ':R' AS platform_id, r.reported_amount AS amount FROM "
             "client_revenue_records r WHERE r.client_id = %(c)s AND r.import_status = 'IMPORTED' AND "
             "r.statement_source = 'PLATFORM' AND r.work_id IS NOT NULL AND r.mapping_status IN ('VERIFIED', 'PENDING') "
             f"AND {_PERIOD_ISRC}")
# plays: from the usage report of a month when there is one, otherwise from the revenue report's plays column
USE_LINES = ("SELECT r.work_id, coalesce(r.platform_id, 0) || ':R' AS platform_id, r.plays AS amount FROM "
             "platform_usage_records r LEFT JOIN (SELECT DISTINCT u.platform_id, u.usage_period_start FROM "
             "platform_usage_records u WHERE u.client_id = %(c)s AND u.import_status = 'IMPORTED' AND "
             "u.statement_source = 'PLATFORM' AND u.record_type = 'RECORDING_USAGE') um ON um.platform_id = "
             "r.platform_id AND um.usage_period_start = r.usage_period_start WHERE r.client_id = %(c)s AND "
             "r.import_status = 'IMPORTED' AND r.statement_source = 'PLATFORM' AND r.work_id IS NOT NULL AND "
             "r.mapping_status IN ('VERIFIED', 'PENDING') AND (r.record_type = 'RECORDING_USAGE' OR um.platform_id IS "
             f"NULL) AND {_PERIOD_ISRC}")


def _cte(name: str, lines: str) -> str:
    return f"{name} AS (SELECT work_id, platform_id, sum(amount) AS amount, count(*) AS lines FROM ({lines}) x GROUP BY 1, 2)"


REV_CTE = _cte("rev", REV_LINES)
USE_CTE = _cte("use", USE_LINES)
CLI_CTE = _cte("cli", _work_lines("CLIENT"))
ROY_CTE = _cte("roy", _work_lines("IPRS"))
WORK_CTE = ", ".join(f"{k}_w AS (SELECT work_id, jsonb_object_agg(platform_id, amount) AS by_platform, sum(amount) AS "
                     f"total FROM {k} GROUP BY 1)" for k in ("rev", "use", "cli", "roy"))
ALL_CTE = f"WITH {REV_CTE}, {USE_CTE}, {CLI_CTE}, {ROY_CTE}, {WORK_CTE} "
KINDS = {"R": "rev", "U": "use", "C": "cli", "I": "roy"}


def _where(f: dict, p: dict) -> str:
    where = ["w.client_id = %(c)s", "w.deleted_at IS NULL"]
    if f.get("q"):
        where.append("(w.work_title ILIKE %(q)s OR w.internal_work_number = %(qq)s OR EXISTS (SELECT 1 FROM "
                     "current_work_recordings x WHERE x.work_id = w.id AND x.isrc = %(qu)s))")
        q = f["q"].strip()
        p.update(q=f"%{q}%", qq=q, qu=q.upper().replace("-", ""))
    if f.get("status"):
        where.append("w.catalogue_status = %(st)s")
        p["st"] = f["status"]
    if f.get("mapping") == "NONE":
        where.append("NOT EXISTS (SELECT 1 FROM current_work_recordings x WHERE x.work_id = w.id)")
    elif f.get("mapping"):
        where.append("EXISTS (SELECT 1 FROM current_work_recordings x WHERE x.work_id = w.id AND x.mapping_status = "
                     "%(m)s)")
        p["m"] = f["mapping"]
    if f.get("money") == "any":
        where.append("(rev_w.total IS NOT NULL OR cli_w.total IS NOT NULL OR roy_w.total IS NOT NULL)")
    elif f.get("money") == "revenue_no_iprs":
        where.append("(rev_w.total IS NOT NULL AND roy_w.total IS NULL)")
    elif f.get("money") == "usage":
        where.append("use_w.total IS NOT NULL")
    elif f.get("money") == "none":
        where.append("(rev_w.work_id IS NULL AND use_w.work_id IS NULL AND cli_w.work_id IS NULL AND roy_w.work_id IS "
                     "NULL)")
    return " AND ".join(where)


def view(actor: dict, client_id: int, f: dict, offset: int = 0, limit: int = 100) -> dict:
    p = dict(c=client_id, o=max(0, offset), n=max(1, min(500, limit)), **_filters(f))
    with access.tx(actor, client_id) as conn:
        from .library import sync
        sync(conn, client_id)
        where = _where(f, p)
        base = ALL_CTE
        frm = "FROM works w " + " ".join(f"LEFT JOIN {k}_w ON {k}_w.work_id = w.id" for k in KINDS.values())
        order = SORTS.get(f.get("sort") or "revenue", SORTS["revenue"])
        rows = db.all(conn, base + f"SELECT w.id, w.internal_work_number, w.work_title, w.catalogue_status, "
                                   f"w.updated_at, rev_w.by_platform AS revenue, rev_w.total AS revenue_total, "
                                   f"use_w.by_platform AS usage, use_w.total AS usage_total, cli_w.by_platform AS "
                                   f"client, cli_w.total AS client_total, "
                                   f"roy_w.by_platform AS royalty, roy_w.total AS royalty_total {frm} WHERE {where} "
                                   f"ORDER BY {order}, lower(w.work_title), w.id OFFSET %(o)s LIMIT %(n)s", p)
        total = db.scalar(conn, base + f"SELECT count(*) {frm} WHERE {where}", p)
        tots = db.all(conn, base + " UNION ALL ".join(
            f"SELECT '{k}' AS k, {t}.platform_id, sum({t}.amount) AS amount FROM {t} JOIN works w ON w.id = {t}.work_id "
            + " ".join(f"LEFT JOIN {x}_w ON {x}_w.work_id = w.id" for x in KINDS.values()) + f" WHERE {where} GROUP BY 2"
            for k, t in KINDS.items()), p)
        ids = [r["id"] for r in rows]
        links = db.all(conn, "SELECT work_id, isrc, mapping_status, updated_at FROM current_work_recordings WHERE "
                             "work_id = ANY(%s) ORDER BY isrc", (ids,))
        exc = {r["work_id"]: r["n"] for r in db.all(
            conn, "SELECT i.work_id, count(*) AS n FROM reconciliation_exceptions e JOIN reconciliation_items i ON i.id = "
                  "e.reconciliation_item_id WHERE i.work_id = ANY(%s) AND e.status IN ('OPEN', 'IN_REVIEW') GROUP BY 1",
            (ids,))}
        unmatched = db.all(conn, "SELECT 'R' AS k, "
                                 "coalesce(platform_id, 0) AS platform_id, mapping_status, count(*) AS lines, "
                                 "sum(reported_amount) AS amount FROM client_revenue_records WHERE client_id = %(c)s AND import_status = "
                                 "'IMPORTED' AND mapping_status NOT IN ('VERIFIED', 'PENDING') AND (%(a)s::DATE IS NULL OR "
                                 "usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR usage_period_end <= %(b)s) AND "
                                 "(%(pl)s::BIGINT IS NULL OR platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                                 "statement_id = %(s)s) GROUP BY 1, 2, 3 UNION ALL SELECT CASE WHEN statement_source = "
                                 "'CLIENT' THEN 'C' ELSE 'I' END, coalesce(platform_id, 0), "
                                 "mapping_status, count(*), sum(royalty_amount) FROM iprs_royalty_records WHERE client_id "
                                 "= %(c)s AND import_status = 'IMPORTED' AND mapping_status <> 'MATCHED' AND "
                                 "(%(a)s::DATE IS NULL OR (usage_period_start >= %(a)s AND usage_period_end <= %(b)s)) "
                                 "AND (%(pl)s::BIGINT IS NULL OR platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                                 "statement_id = %(s)s) GROUP BY 1, 2, 3", p)
        partial = db.scalar(conn, "SELECT count(*) FROM statements WHERE client_id = %(c)s AND import_status = 'IMPORTED' "
                                  "AND record_type = 'WORK_ROYALTY' AND %(a)s::DATE IS NOT NULL AND (usage_period_start "
                                  "IS NULL OR (usage_period_start <= %(b)s AND usage_period_end >= %(a)s AND NOT "
                                  "(usage_period_start >= %(a)s AND usage_period_end <= %(b)s)))", p)
        plat = {x["id"]: x["platform_name"] for x in db.all(conn, "SELECT id, platform_name FROM platforms")}
        stmts = db.all(conn, "SELECT id, original_filename, record_type, statement_source, statement_reference FROM statements WHERE "
                             "client_id = %s AND import_status = 'IMPORTED' ORDER BY uploaded_at DESC", (client_id,))
    by_work: dict = {}
    for ln in links:
        by_work.setdefault(ln["work_id"], []).append(ln)
    for r in rows:
        ls = by_work.get(r["id"], [])
        r["isrcs"] = [dict(isrc=x["isrc"], status=x["mapping_status"]) for x in ls]
        st = {x["mapping_status"] for x in ls}
        r["mapping_state"] = "NONE" if not st else "CONFLICT" if "CONFLICT" in st else "PENDING" if "PENDING" in st \
            else "VERIFIED"
        r["open_exceptions"] = exc.get(r["id"], 0)
        r["last_updated"] = max([r["updated_at"]] + [x["updated_at"] for x in ls])
    def col(key: str) -> dict:                    # 'platform:R' = per-ISRC revenue report, 'platform:W' = per work
        pid, lay = key.split(":")
        name = plat.get(int(pid), "Other statements")
        return dict(id=key, name=f"{name} - revenue report" if lay == "R" else name)

    def order(key: str):
        pid, lay = key.split(":")
        return (pid == "0", plat.get(int(pid), ""), lay)
    names = {"R": "revenue", "U": "usage", "C": "client", "I": "royalty"}
    cols = {names[k]: sorted({t["platform_id"] for t in tots if t["k"] == k}, key=order) for k in KINDS}
    return dict(rows=rows, total=total, offset=offset,
                columns={n: [dict(col(k), name=plat.get(int(k.split(":")[0]), "Other statements")) for k in ks]
                         for n, ks in cols.items()},
                totals={names[k]: {str(t["platform_id"]): t["amount"] for t in tots if t["k"] == k} for k in KINDS},
                unmatched=[dict(kind={"R": "revenue", "C": "client"}.get(u["k"], "royalty"),
                                platform=plat.get(u["platform_id"], "Other IPRS distributions"),
                                status=u["mapping_status"], lines=u["lines"], amount=u["amount"]) for u in unmatched],
                partial_statements=partial, statements=stmts,
                platforms=[dict(id=k, name=v) for k, v in sorted(plat.items(), key=lambda kv: kv[1])])


def sources(actor: dict, work_id: int, f: dict) -> dict:
    """Every statement line behind a work's amounts, with its statement and sheet row."""
    with access.tx(actor) as conn:
        w = db.one(conn, "SELECT * FROM works WHERE id = %s", (work_id,))
        if not w:
            raise MasterError("This work does not exist.")
        p = dict(c=w["client_id"], w=work_id, **_filters(f))
        rev = db.all(conn, "SELECT r.statement_id, s.original_filename, r.source_row_number, r.usage_period_start AS "
                           "month, r.isrc, r.reported_title, r.reported_amount AS amount, pl.plays, r.mapping_status, "
                           "p.platform_name, r.statement_source, s.record_type FROM client_revenue_records r JOIN "
                           "statements s ON s.id = r.statement_id JOIN rd_platform_line pl ON pl.file_id = r.file_id AND "
                           "pl.line_no = r.line_no LEFT JOIN platforms "
                           "p ON p.id = r.platform_id WHERE r.work_id = %(w)s AND r.import_status = 'IMPORTED' AND "
                           "(%(a)s::DATE IS NULL OR r.usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR "
                           "r.usage_period_end <= %(b)s) AND (%(pl)s::BIGINT IS NULL OR r.platform_id = %(pl)s) AND "
                           "(%(s)s::BIGINT IS NULL OR r.statement_id = %(s)s) ORDER BY r.usage_period_start, r.isrc, "
                           "r.statement_id, r.line_no LIMIT 2000", p)
        use = db.all(conn, "SELECT r.statement_id, s.original_filename, r.source_row_number, r.usage_period_start AS "
                           "month, r.isrc, r.reported_title, NULL AS amount, r.plays, r.mapping_status, p.platform_name, "
                           "r.statement_source, r.record_type FROM platform_usage_records r JOIN statements s ON s.id = "
                           "r.statement_id LEFT JOIN platforms p ON p.id = r.platform_id WHERE r.work_id = %(w)s AND "
                           "r.import_status = 'IMPORTED' AND r.record_type = 'RECORDING_USAGE' AND (%(a)s::DATE IS NULL OR "
                           "r.usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR r.usage_period_end <= %(b)s) AND "
                           "(%(pl)s::BIGINT IS NULL OR r.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                           "r.statement_id = %(s)s) ORDER BY r.usage_period_start, r.isrc, r.statement_id, r.line_no "
                           "LIMIT 2000", p)
        roy = db.all(conn, "SELECT i.statement_id, s.original_filename, i.source_row_number, i.category, "
                           "i.statement_reference, i.usage_period_start, i.usage_period_end, i.party_name, i.role, "
                           "i.collection_share, i.source_reference, i.royalty_amount AS amount, p.platform_name, i.statement_source FROM "
                           "iprs_royalty_records i JOIN statements s ON s.id = i.statement_id LEFT JOIN platforms p ON "
                           "p.id = i.platform_id WHERE i.work_id = %(w)s AND i.import_status = 'IMPORTED' AND "
                           "(%(a)s::DATE IS NULL OR (i.usage_period_start >= %(a)s AND i.usage_period_end <= %(b)s)) AND "
                           "(%(pl)s::BIGINT IS NULL OR i.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                           "i.statement_id = %(s)s) ORDER BY i.usage_period_start NULLS LAST, i.statement_id, i.line_no "
                           "LIMIT 2000", p)
    return dict(work=w, revenue=sorted(rev + use, key=lambda x: (x["month"] or dt.date.min, x["isrc"] or "",
                                                                 x["record_type"])), royalty=roy)


def unmatched(actor: dict, client_id: int, f: dict) -> dict:
    """Revenue that reaches no work (unknown or conflicting ISRCs, no ISRC) and IPRS royalty for works that are not in
    the catalogue. Kept and shown - never discarded."""
    p = dict(c=client_id, **_filters(f))
    with access.tx(actor, client_id) as conn:
        rev = db.all(conn, "SELECT r.isrc, r.mapping_status, p.platform_name, r.statement_source, min(r.reported_title) AS title, count(*) AS "
                           "lines, sum(r.reported_amount) AS amount, min(r.usage_period_start) AS first_month, "
                           "max(r.usage_period_start) AS last_month FROM client_revenue_records r LEFT JOIN platforms p ON "
                           "p.id = r.platform_id WHERE r.client_id = %(c)s AND r.import_status = 'IMPORTED' AND "
                           "r.mapping_status NOT IN ('VERIFIED', 'PENDING') AND (%(a)s::DATE IS NULL OR "
                           "r.usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR r.usage_period_end <= %(b)s) AND "
                           "(%(pl)s::BIGINT IS NULL OR r.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                           "r.statement_id = %(s)s) GROUP BY 1, 2, 3, 4 ORDER BY sum(r.reported_amount) DESC NULLS LAST "
                           "LIMIT 1000", p)
        roy = db.all(conn, "SELECT i.internal_work_number, i.mapping_status, coalesce(p.platform_name, i.category) AS "
                           "platform_name, i.statement_source, min(i.reported_title) AS title, count(*) AS lines, sum(i.royalty_amount) AS "
                           "amount FROM iprs_royalty_records i LEFT JOIN platforms p ON p.id = i.platform_id WHERE "
                           "i.client_id = %(c)s AND i.import_status = 'IMPORTED' AND i.mapping_status <> 'MATCHED' AND "
                           "(%(a)s::DATE IS NULL OR (i.usage_period_start >= %(a)s AND i.usage_period_end <= %(b)s)) AND "
                           "(%(pl)s::BIGINT IS NULL OR i.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR "
                           "i.statement_id = %(s)s) GROUP BY 1, 2, 3, 4 ORDER BY sum(i.royalty_amount) DESC LIMIT 1000", p)
        if rev:
            conflict = {r["isrc"]: r["works"] for r in db.all(
                conn, "SELECT isrc, array_agg(coalesce(internal_work_number, work_title)) AS works FROM "
                      "current_work_recordings WHERE client_id = %s AND isrc = ANY(%s) GROUP BY isrc",
                (client_id, [r["isrc"] for r in rev if r["isrc"]]))}
            for r in rev:
                r["claimed_by"] = conflict.get(r["isrc"], [])
    return dict(revenue=rev, royalty=roy)


def _span(f: dict, stmts: list[dict] | None = None) -> str:
    if f.get("a") and f.get("b"):
        return f"{f['a']:%Y-%m}_to_{f['b']:%Y-%m}"
    if stmts and all(s["usage_period_start"] for s in stmts):
        return f"{min(s['usage_period_start'] for s in stmts):%Y-%m}_to_{max(s['usage_period_end'] for s in stmts):%Y-%m}"
    return "All_Periods"


def export_view(actor: dict, client_id: int, f: dict) -> tuple[str, bytes]:
    """The filtered master view as a table: one row per work, platforms side by side (no paging)."""
    v = view(actor, client_id, f, 0, 500)
    rows, off = list(v["rows"]), 500
    while off < v["total"]:
        more = view(actor, client_id, f, off, 500)
        rows += more["rows"]
        off += 500
    ff = _filters(f)
    with access.tx(actor, client_id) as conn:
        code = db.scalar(conn, "SELECT code FROM client WHERE id = %s", (client_id,))
        audit.record(conn, "export.master_view", actor, "client", client_id,
                     dict(rows=len(rows), filters={k: v for k, v in f.items() if v}))
    groups = (("revenue", "Platform revenue", "money"), ("usage", "Usage (plays)", None),
              ("client", "Client statement", "money"), ("royalty", "IPRS paid", "money"))
    cols = [("Song name", 36, None), ("Internal work number", 14, None), ("ISRCs", 40, None), ("Catalogue status", 12,
                                                                                                None),
            ("Mapping status", 14, None)]
    for key, label, kind in groups:
        cs = v["columns"][key]
        if cs:
            cols += [(f"[{label}] {c['name']}", 15, kind) for c in cs] + [(f"[{label}] Total", 16, kind)]
    cols += [("Open exceptions", 10, None), ("Last updated", 18, "date")]
    out = []
    for r in rows:
        row = [r["work_title"], r["internal_work_number"], [x["isrc"] for x in r["isrcs"]],
               r["catalogue_status"].replace("_", " ").title(), r["mapping_state"].title()]
        for key, _label, _kind in groups:
            cs = v["columns"][key]
            if cs:
                vals = r[key] or {}
                row += [Decimal(str(vals[str(c["id"])])) if vals.get(str(c["id"])) is not None else None for c in cs]
                row += [r[f"{key}_total"]]
        out.append(row + [r["open_exceptions"], r["last_updated"].replace(tzinfo=None)])
    plat = next((p["name"] for p in v["platforms"] if p["id"] == ff["pl"]), None)
    heading = [f"{code} master view", "Filters: " + ", ".join(x for x in (
        f"platform {plat}" if plat else "all platforms",
        f"usage {ff['a']:%b %Y} to {ff['b']:%b %Y}" if ff["a"] and ff["b"] else "all periods",
        f"statement #{ff['s']}" if ff["s"] else None, f"search '{f['q']}'" if f.get("q") else None,
        f"catalogue status {f['status']}" if f.get("status") else None,
        f"mapping {f['mapping']}" if f.get("mapping") else None) if x),
               "Platform revenue and usage (the platform reports), the client's statements and what IPRS paid are never "
               "added together. They reach a work only through its ISRC links or its work number; unmatched lines are "
               "listed separately in the application. An empty cell means no record, not zero."]
    name = f"{code}_Master_View_{xlsx.safe_name(plat) + '_' if plat else ''}{_span(ff)}.xlsx"
    return name, xlsx.book([dict(title="Master view", heading=heading, columns=cols, rows=out)])




def export_skv(actor: dict, client_id: int, f: dict) -> tuple[str, bytes]:
    """The master statement in the SKV layout, rebuilt from the statement library and the catalogue."""
    access.require(actor, "prepare")
    ff = _filters(f)
    side = "IPRS" if f.get("side") == "IPRS" else "CLIENT"
    c, res, inp, inputs, sts = _build(actor, client_id, ff, export=True, side=side)
    data, _meta = excel.master(res, client_code=c["code"], generation=inp.generation, state="EXPORT",
                               build_ref=f"master export by {actor.get('name') or actor['email']}",
                               ruleset=rules.RULESET_V1, software=SOFTWARE, inputs=inputs, left_out=[], decisions=[],
                               people={"prepared_by": actor.get("name")})
    plat = None
    if ff["pl"]:
        with access.tx(actor, client_id) as conn:
            plat = db.scalar(conn, "SELECT platform_name FROM platforms WHERE id = %s", (ff["pl"],))
    name = f"{c['code']}_Master_Statement_{'IPRS_' if side == 'IPRS' else ''}" \
           f"{xlsx.safe_name(plat) + '_' if plat else ''}{_span(ff, sts)}.xlsx"
    return name, data


def _build(actor: dict, client_id: int, ff: dict, export: bool = False, side: str = "CLIENT"):
    """The SKV master of the selection, built with the report engine from the imported statements and the catalogue,
    and checked. Returns (client, result, engine input, input list, statements)."""
    with access.tx(actor, client_id) as conn:
        from .library import sync
        sync(conn, client_id)
        c = db.one(conn, "SELECT * FROM client WHERE id = %s", (client_id,))
        sts = db.all(conn, "SELECT s.*, f.facts, f.meta, f.kind, f.filename, f.sha256, f.label FROM statements s JOIN "
                           "rd_file f ON f.id = s.file_id WHERE s.client_id = %(c)s AND s.import_status = 'IMPORTED' AND "
                           "s.statement_source = ANY(%(sides)s) AND s.record_type <> 'RECORDING_USAGE' AND "
                           "(%(pl)s::BIGINT IS NULL OR s.platform_id = %(pl)s) AND (%(s)s::BIGINT IS NULL OR s.id = "
                           "%(s)s) AND (%(a)s::DATE IS NULL OR (s.record_type = 'WORK_ROYALTY' AND s.usage_period_start "
                           ">= %(a)s AND s.usage_period_end <= %(b)s) OR (s.record_type = 'RECORDING_REVENUE' AND "
                           "s.usage_period_start <= %(b)s AND s.usage_period_end >= %(a)s)) ORDER BY s.uploaded_at, s.id",
                     dict(c=client_id, sides=["IPRS"] if side == "IPRS" else ["CLIENT", "PLATFORM"], **ff))
        if not sts:
            raise MasterError(f"No imported {'client statement or platform revenue report' if side == 'CLIENT' else 'IPRS statement'} matches this selection"
                              + (" (switch the side to see the other statements)." if not ff["s"] else "."))
        inp = engine.RunInput(client_code=c["code"], client_name=c["name"], ruleset=rules.RULESET_V1)
        inputs = []
        for s in sts:
            data = load_data(conn, s["file_id"], s["kind"], s["facts"])
            if s["record_type"] == "WORK_ROYALTY":
                src = assemble.statement_src(s["file_id"], s["filename"], data, dict(s["meta"]))
                if s["relation"] in ("SUPPLEMENTARY", "CORRECTION"):
                    src.relation = "SUPPLEMENTARY"
                    src.identity_key += f"#{s['relation'].lower()}:{s['file_id']}"
                inp.statements.append(src)
            else:
                if ff["a"]:
                    data.lines = [x for x in data.lines if x.month and ff["a"] <= x.month <= ff["b"]]
                inp.platforms.append(assemble.platform_src(s["file_id"], s["filename"], data, dict(s["meta"])))
            inputs.append(dict(file_id=s["file_id"], filename=s["filename"], kind=s["kind"], label=s["label"],
                               sha256=s["sha256"], total=s["total_amount"], check="PASS", included="yes"))
        ws = db.all(conn, "SELECT w.id, w.work_title, w.internal_work_number, coalesce(array_agg(x.isrc ORDER BY "
                          "x.isrc) FILTER (WHERE x.isrc IS NOT NULL), '{}') AS isrcs FROM works w LEFT JOIN "
                          "current_work_recordings x ON x.work_id = w.id WHERE w.client_id = %s AND w.deleted_at IS NULL "
                          "GROUP BY w.id ORDER BY w.id", (client_id,))
        if ws:
            inp.song_list = engine.SrcList(file_id=0, label=f"{c['code']} catalogue", entries=[
                SongEntry(entry_no=n, row_no=n, title=w["work_title"],
                          work_nos=[w["internal_work_number"]] if w["internal_work_number"] else [], isrcs=w["isrcs"])
                for n, w in enumerate(ws, 1)])
        prefix = (c["settings"] or {}).get("output_prefix") or f"{c['code']}-RD-SKV"
        inp.generation = f"{prefix}-EXPORT"
        if export:
            audit.record(conn, "export.master_statement", actor, "client", client_id,
                         dict(statements=len(sts), works=len(ws), side=side,
                              filters={k: str(v) for k, v in ff.items() if v}))
    res = engine.build(inp)
    checks = res.checks + verify.master(res)
    failed = [x for x in checks if not x["ok"] and x.get("blocking", True)]
    if failed:
        raise MasterError(("The export" if export else "The master sheet") + " did not pass its financial checks, so "
                          "it was not produced: " + "; ".join(x["text"] for x in failed[:3]) + ".")
    return c, res, inp, inputs, sts


# ================================================================== the master sheet on screen (SKV layout)
_SHEETS: OrderedDict = OrderedDict()            # (client, filters, data fingerprint) -> sheet; a few, newest last
_LOCK = threading.Lock()
FY_LABEL = "TOTAL REVENUE  (by Indian Financial Year, 1 Apr - 31 Mar, of the period the royalty was earned in)"


def _fingerprint(actor: dict, client_id: int) -> str:
    """Changes whenever a statement, a work or an ISRC link of the client changes, so a cached sheet is never stale."""
    with access.tx(actor, client_id) as conn:
        from .library import sync
        sync(conn, client_id)
        r = db.one(conn, "SELECT (SELECT md5(coalesce(string_agg(id || ':' || import_status || ':' || updated_at, ',' "
                         "ORDER BY id), '')) FROM statements WHERE client_id = %(c)s) AS s, (SELECT count(*) || ':' || "
                         "coalesce(max(updated_at)::TEXT, '') FROM works WHERE client_id = %(c)s) AS w, (SELECT "
                         "count(*) || ':' || coalesce(max(updated_at)::TEXT, '') FROM work_recordings WHERE client_id = "
                         "%(c)s) AS l", dict(c=client_id))
    return f"{r['s']}|{r['w']}|{r['l']}"


def _txt(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(names.q2(v))
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    return v


def _sheet_of(res) -> dict:
    """The master workbook's first sheet as data: column groups (row 1 bands), columns (row 2), rows and the TOTAL
    row, in exactly the column order of excel.master."""
    plat_bands = [b for b in res.bands if b.kind == "PLATFORM"]
    cols: list[dict] = []
    groups: list[dict] = []
    ident = [("ISRC", "text"), ("Song Name", "text"), ("Internal No", "text"), ("Total Amount", "money")] + \
            [(b.total_header, "money") for b in plat_bands]
    cols += [dict(h=h, t=t) for h, t in ident]
    groups.append(dict(label="", kind="IDENT", start=0, span=len(ident)))
    for b in res.bands:
        start = len(cols)
        for _c in b.cols:
            cols += [dict(h="Date", t="date"), dict(h="Amount", t="money"), dict(h="Period", t="text"),
                     dict(h="Distribution Number", t="text", sep=True)]
        groups.append(dict(label=b.label, kind=b.kind, fill=b.fill, tint=b.tint, start=start, span=len(cols) - start,
                           distributions=len(b.cols)))
    start = len(cols)
    cols += [dict(h=names.fy_label(k) if k != "NA" else "Period Not Stated", t="money") for k in res.fy_keys]
    cols.append(dict(h="Total Revenue", t="money"))
    groups.append(dict(label=FY_LABEL, kind="FY", fill=excel.FY_BAND, tint=excel.FY_TOTAL, start=start,
                       span=len(cols) - start))
    start = len(cols)
    cols += [dict(h=h, t="text") for h in ["Catalogue Status", "Royalty Booked On"]
             + [b.basis_header for b in plat_bands] + ["Held / Flags"]]
    groups.append(dict(label="AUDIT / TRACEABILITY", kind="AUDIT", fill=excel.AUD_BAND, tint=excel.AUD_TINT,
                       start=start, span=len(cols) - start))
    rows, keys = [], []
    for row in res.rows:
        vals = [" | ".join(row.all_isrcs) or None, row.title, " | ".join(row.all_works) or None, row.royalty] + \
               [row.platform.get(b.key, ZERO) for b in plat_bands]
        for b in res.bands:
            for c in b.cols:
                cl = row.cells.get(c.key)
                vals += [None] * 4 if cl is None or cl.sibling else [c.date, cl.shown, c.period_label, c.dist_no]
        vals += [row.fy.get(k, ZERO) for k in res.fy_keys] + [row.royalty]
        vals += [row.status, " ; ".join(row.booked_on) or None] + \
                [" ; ".join(dict.fromkeys(row.basis.get(b.key, []))) or None for b in plat_bands] + \
                [" ; ".join(dict.fromkeys(row.flags)) or None]
        rows.append([_txt(v) for v in vals])
        keys.append(" ".join([row.title or ""] + row.all_isrcs + row.all_works).lower())
    total = [None, "TOTAL", None, sum((x.royalty for x in res.rows), ZERO)] + \
            [sum((x.platform.get(b.key, ZERO) for x in res.rows), ZERO) for b in plat_bands]
    for b in res.bands:
        for c in b.cols:
            total += [None, c.shown_total, None, c.dist_no if b.kind == "ROYALTY" else c.period_label]
    total += [sum((x.fy.get(k, ZERO) for x in res.rows), ZERO) for k in res.fy_keys] + \
             [sum((x.royalty for x in res.rows), ZERO)]
    total += [f"{len(res.rows):,} song rows"] + [None] * (len(cols) - len(total) - 1)
    return dict(columns=cols, groups=groups, rows=rows, keys=keys, total=[_txt(v) for v in total],
                plat_n=len(plat_bands))


TITLE_COL, AMOUNT_COL, PLAT_COL = 1, 3, 4         # Song Name, Total Amount, then one Total <platform> Revenue per band
SHEET_SORTS = ("amount_desc", "amount_asc", "title_asc", "title_desc", "platform_desc", "platform_asc")


def _sheet_order(sh: dict, idx: list[int], sort: str) -> list[int]:
    """The rows in the order chosen. The engine's order is already Total Amount, highest first."""
    rows, n = sh["rows"], sh["plat_n"]
    if sort in ("title_asc", "title_desc"):
        return sorted(idx, key=lambda i: title_key(rows[i][TITLE_COL]), reverse=sort == "title_desc")
    if sort == "amount_asc":
        return sorted(idx, key=lambda i: Decimal(rows[i][AMOUNT_COL] or 0))
    if sort in ("platform_desc", "platform_asc") and n:
        val = lambda i: sum((Decimal(x or 0) for x in rows[i][PLAT_COL:PLAT_COL + n]), ZERO)   # noqa: E731
        return sorted(idx, key=val, reverse=sort == "platform_desc")
    return idx


def sheet(actor: dict, client_id: int, f: dict, offset: int = 0, limit: int = 100) -> dict:
    """One page of the master sheet in the SKV layout. Building it takes the report engine a few seconds, so the
    result is kept while the client's statements and catalogue stay the same. With every platform only the Total
    Amount is shown; with one platform also its Total <platform> Revenue (from its revenue reports)."""
    ff = _filters(f)
    side = "IPRS" if f.get("side") == "IPRS" else "CLIENT"
    key = (client_id, side, ff["a"], ff["b"], ff["pl"], ff["s"], _fingerprint(actor, client_id))
    with _LOCK:
        sh = _SHEETS.get(key)
        if sh:
            _SHEETS.move_to_end(key)
    if sh is None:
        c, res, _inp, _inputs, sts = _build(actor, client_id, ff, side=side)
        sh = _sheet_of(res)
        sh.update(client=c["code"], statements=len(sts), built_at=dt.datetime.now(dt.timezone.utc))
        with _LOCK:
            _SHEETS[key] = sh
            while len(_SHEETS) > 6:
                _SHEETS.popitem(last=False)
    q = (f.get("q") or "").strip().lower()
    idx = [i for i, k in enumerate(sh["keys"]) if q in k] if q else list(range(len(sh["rows"])))
    sort = f.get("sort") if f.get("sort") in SHEET_SORTS else "amount_desc"
    if sort.startswith("platform") and not (ff["pl"] and sh["plat_n"]):
        sort = "amount_desc"
    idx = _sheet_order(sh, idx, sort)
    n = sh["plat_n"]
    drop = 0 if ff["pl"] else n                    # every platform: the platform totals are left out of the sheet
    keep = lambda r: r[:PLAT_COL] + r[PLAT_COL + drop:]                                         # noqa: E731
    by = {TITLE_COL: "title", AMOUNT_COL: "amount", **{PLAT_COL + k: "platform" for k in range(n - drop)}}
    cols = [dict(c, sort=by[i]) if i in by else c for i, c in enumerate(keep(sh["columns"]))]
    groups = [dict(g, span=g["span"] - drop) if g["kind"] == "IDENT" else dict(g, start=g["start"] - drop)
              for g in sh["groups"]]
    offset, limit = max(0, offset), max(1, min(500, limit))
    page = [keep(sh["rows"][i]) for i in idx[offset:offset + limit]]
    return dict(columns=cols, groups=groups, rows=page, total_row=keep(sh["total"]), total=len(idx),
                all_rows=len(sh["rows"]), offset=offset, statements=sh["statements"], built_at=sh["built_at"],
                sort=sort, platform_revenue=n > 0)
