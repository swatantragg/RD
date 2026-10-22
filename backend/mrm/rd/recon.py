"""Reconciliation: the client's statements (the source revenue) against the statements received from IPRS (the IPRS
royalty) for the same platform and usage period, with an indicative reference benchmark. The side of a statement is
who sent it (Statements → Received from), never its layout: the client often forwards statements in the IPRS layout.
A run covers one usage period (every month on both sides), or one Indian financial year (the months both sides
cover, with the same months a year earlier beside them).

  eligible revenue          = source revenue (on the configured basis) x client interest
  indicative reference      = eligible revenue x benchmark %                    (4 % for the SVF proof of concept)
  indicative variance       = indicative reference - IPRS work royalty          (requires verification)
  observed percentage       = IPRS work royalty / eligible revenue x 100

None of these is a confirmed amount payable. Nothing is assumed:
  * a work's IPRS royalty is counted once, however many ISRCs the work has; the ISRC-level revenue stays visible;
  * revenue reaches a work only through a current catalogue link; unknown or conflicting ISRCs stay unmatched;
  * a missing IPRS entry is NULL with the exception "No corresponding IPRS entry found in the statements uploaded.",
    never zero;
  * an unknown client interest, an unclear revenue basis, an incomplete usage period or a currency difference stops
    the calculation for the affected items and says why; it is never replaced by 100 % or by a guess.
A run records its settings and the exact statements it used, and is never overwritten: run again for new data.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections import defaultdict
from decimal import Decimal

from .. import audit, db
from ..normalize import month_end, months_between
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border
from openpyxl.utils import get_column_letter

from . import access, excel, platforms, xlsx
from .detect import money
from .service import RDError

ZERO = Decimal("0")
HUNDRED = Decimal("100")
Q8 = Decimal("0.00000001")
MISSING_IPRS = "No corresponding IPRS entry found in the statements uploaded."
TOLERANCE = Decimal("0.005")               # differences below half a paisa are rounding, not a difference
EXC_LABEL = {
    "MISSING_IPRS_ENTRY": "No IPRS entry", "UNKNOWN_ISRC": "Unknown ISRC", "CONFLICTING_ISRC_MAPPING": "Conflicting ISRC",
    "WORK_NOT_FOUND": "Work not in catalogue", "AMBIGUOUS_WORK_MATCH": "Work needs review",
    "MISSING_USAGE_PERIOD": "Usage period incomplete", "MISSING_CURRENCY": "Currency missing",
    "REVENUE_BASIS_UNCLEAR": "Revenue basis unclear", "CLIENT_INTEREST_UNCLEAR": "Client interest unknown",
    "DUPLICATE_STATEMENT": "Duplicate statement", "AMOUNT_MISMATCH": "Client statement ≠ IPRS",
    "SOURCE_VALIDATION_ERROR": "Source data problem", "LATER_STATEMENT_REVIEW_REQUIRED": "Later statement to review",
    "MAPPING_NOT_VERIFIED": "Link not verified", "UNDERPAID": "Underpaid by IPRS",
    "NO_PLATFORM_REVENUE": "No platform revenue"}
CALC_LABEL = {"CALCULATED": "Calculated", "NOT_CALCULATED": "Not calculated", "NOT_COMPARABLE": "Not comparable"}
KIND_LABEL = {"WORK": "Work", "UNMATCHED_RECORDING": "Unmatched recording", "UNMATCHED_WORK": "Work not in catalogue"}
RUN_KIND_LABEL = {"PERIOD": "Usage period", "YEAR": "Financial year"}
REVIEW_LABEL = {"UNREVIEWED": "Not reviewed", "REVIEWED": "Reviewed", "NEEDS_INFO": "Needs information"}
MAPPING_LABEL = {"VERIFIED": "Verified", "PENDING": "Not verified", "CONFLICT": "Conflict", "UNKNOWN": "Not in catalogue",
                 "NO_ISRC": "No ISRC", "WORK_NOT_FOUND": "Work not in catalogue", "NO_WORK_NUMBER": "No work number"}


class ReconError(RDError):
    pass


PLAIN_NUMBER = re.compile(r"\d+(\.\d+)?")            # digits, optionally a decimal point and more digits - nothing else


def plain_number(v, commas: bool = False) -> Decimal | None:
    """A number typed by a person, or None when it is not one: '1e2', 'NaN', '4a', '-4' are not. commas: an amount
    may have thousands commas (1,250.50); a percentage may not ('1,5' is refused, not read as 15)."""
    t = str(v).strip().rstrip("%").strip()
    t = t.replace(",", "") if commas else t
    return Decimal(t) if PLAIN_NUMBER.fullmatch(t) else None


def _dec(v, what: str) -> Decimal | None:
    if v in (None, ""):
        return None
    d = plain_number(v)
    if d is None:
        raise ReconError(f"{what} must be a number, for example 4 or 4.5.")
    if not (ZERO < d <= HUNDRED):
        raise ReconError(f"{what} must be more than 0 and at most 100 (per cent).")
    return d


def _q(v: Decimal | None) -> Decimal | None:
    return None if v is None else v.quantize(Q8)


def _date(v) -> dt.date | None:
    if not v:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


# ================================================================== settings: benchmark and client interest
def current_settings(conn, client_id: int, platform_id: int | None) -> dict | None:
    return db.one(conn, "SELECT * FROM reconciliation_settings WHERE client_id = %s AND replaced_at IS NULL AND "
                        "(platform_id = %s OR platform_id IS NULL) ORDER BY platform_id NULLS LAST LIMIT 1",
                  (client_id, platform_id))


def statement_platforms(conn, client_id: int) -> list[dict]:
    """The platforms in the client's imported statements, with how many of each kind they have: platform reports,
    client statements and IPRS statements (revenue = platform reports + client statements, as before 1.5.0)."""
    return db.all(conn, "SELECT p.id AS platform_id, p.platform_name AS platform, count(*) FILTER (WHERE "
                        "s.statement_source = 'PLATFORM') AS platform_reports, count(*) FILTER (WHERE "
                        "s.statement_source = 'CLIENT') AS client, count(*) FILTER (WHERE s.statement_source <> 'IPRS') "
                        "AS revenue, count(*) FILTER (WHERE s.statement_source = "
                        "'IPRS') AS iprs FROM statements s JOIN platforms p ON p.id = s.platform_id WHERE "
                        "s.client_id = %s AND s.import_status = 'IMPORTED' GROUP BY 1, 2 ORDER BY 2", (client_id,))


def settings_view(actor: dict, client_id: int) -> dict:
    with access.tx(actor, client_id) as conn:
        from .library import sync
        sync(conn, client_id)
        rows = db.all(conn, "SELECT s.*, p.platform_name, u.name AS created_by_name, r.name AS replaced_by_name FROM "
                            "reconciliation_settings s LEFT JOIN platforms p ON p.id = s.platform_id LEFT JOIN app_user u "
                            "ON u.id = s.created_by LEFT JOIN app_user r ON r.id = s.replaced_by WHERE s.client_id = %s "
                            "ORDER BY s.replaced_at NULLS FIRST, s.id DESC LIMIT 80", (client_id,))
        cfg = (db.scalar(conn, "SELECT settings FROM client WHERE id = %s", (client_id,)) or {})
        plats = statement_platforms(conn, client_id)
    current = [r for r in rows if r["replaced_at"] is None]
    default = next((r for r in current if r["platform_id"] is None), None)
    own = {r["platform_id"]: r for r in current if r["platform_id"] is not None}
    seen = {p["platform_id"] for p in plats}
    plats += [dict(platform_id=pid, platform=r["platform_name"], revenue=0, iprs=0, platform_reports=0, client=0)
              for pid, r in own.items()
              if pid not in seen]
    for p in plats:
        r = own.get(p["platform_id"])
        p.update(own=r is not None, setting_id=(r or default or {}).get("id"),
                 benchmark_percentage=(r or default or {}).get("benchmark_percentage"),
                 client_interest_pct=(r or default or {}).get("client_interest_pct"),
                 revenue_basis=(r or default or {}).get("revenue_basis"))
    return dict(current=current, default=default, platforms=sorted(plats, key=lambda p: p["platform"]),
                history=[r for r in rows if r["replaced_at"]], iprs_currency=cfg.get("iprs_currency"),
                can_change=access.can(actor, "settings"))


def save_platform_settings(actor: dict, client_id: int, body: dict) -> dict:
    """The client-wide basis (benchmark, interest, revenue basis) and, per platform, either 'use the client-wide
    benchmark' or a benchmark of its own. A value in force is replaced, never edited; unchanged values are left alone."""
    access.require(actor, "settings")
    bench = _dec(body.get("benchmark_percentage"), "The benchmark")
    if bench is None:
        raise ReconError("Please enter the reference benchmark percentage.")
    interest = _dec(body.get("client_interest_pct"), "The client interest")
    basis = (body.get("revenue_basis") or "GROSS").upper()
    if basis not in ("GROSS", "NET"):
        raise ReconError("The revenue basis is gross or net.")
    note = (body.get("note") or "").strip()
    if not note:
        raise ReconError("Please say why the setting changes (for example who approved it).")
    with access.tx(actor, client_id) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(84726401, %s)", (client_id,))

        def current(pid):
            return db.one(conn, "SELECT * FROM reconciliation_settings WHERE client_id = %s AND replaced_at IS NULL AND "
                                "platform_id IS NOT DISTINCT FROM %s FOR UPDATE", (client_id, pid))

        def close(old):
            conn.execute("UPDATE reconciliation_settings SET replaced_at = now(), replaced_by = %s WHERE id = %s",
                         (actor["id"], old["id"]))

        def put(pid, b, name):
            old = current(pid)
            if old and old["benchmark_percentage"] == b and old["client_interest_pct"] == interest \
                    and old["revenue_basis"] == basis:
                return
            if old:
                close(old)
            sid = db.insert(conn, "reconciliation_settings", dict(
                client_id=client_id, platform_id=pid, benchmark_percentage=b, client_interest_pct=interest,
                revenue_basis=basis, note=note, created_by=actor["id"]))
            audit.record(conn, "settings.reconciliation_changed", actor, "reconciliation_settings", sid,
                         dict(platform_id=pid, platform=name, note=note),
                         before=None if not old else dict(benchmark_percentage=old["benchmark_percentage"],
                                                          client_interest_pct=old["client_interest_pct"],
                                                          revenue_basis=old["revenue_basis"]),
                         after=dict(benchmark_percentage=b, client_interest_pct=interest, revenue_basis=basis))

        put(None, bench, "every platform")
        for x in body.get("platforms") or []:
            p = platforms.require_platform(conn, int(x.get("platform_id") or 0))
            if x.get("use_default"):
                old = current(p["id"])
                if old:
                    close(old)
                    audit.record(conn, "settings.reconciliation_platform_default", actor, "reconciliation_settings",
                                 old["id"], dict(platform=p["platform_name"], note=note),
                                 before=dict(benchmark_percentage=old["benchmark_percentage"]),
                                 after=dict(benchmark_percentage=bench, follows="client-wide value"))
                continue
            own = _dec(x.get("benchmark_percentage"), f"The benchmark for {p['platform_name']}")
            if own is None:
                raise ReconError(f"Enter the benchmark for {p['platform_name']}, or tick it to use {bench} %.")
            put(p["id"], own, p["platform_name"])
        if "iprs_currency" in body:
            cur = (body.get("iprs_currency") or "").strip().upper() or None
            cfg = db.scalar(conn, "SELECT settings FROM client WHERE id = %s", (client_id,)) or {}
            if cfg.get("iprs_currency") != cur:
                conn.execute("UPDATE client SET settings = %s WHERE id = %s",
                             (db.J({**cfg, "iprs_currency": cur}), client_id))
                audit.record(conn, "settings.iprs_currency_changed", actor, "client", client_id,
                             before=dict(iprs_currency=cfg.get("iprs_currency")), after=dict(iprs_currency=cur))
    return settings_view(actor, client_id)


def save_settings(actor: dict, client_id: int, body: dict) -> dict:
    """A new value replaces the one in force; both stay, with who changed it and when (Super Admin only)."""
    access.require(actor, "settings")
    bench = _dec(body.get("benchmark_percentage"), "The benchmark")
    if bench is None:
        raise ReconError("Please enter the benchmark percentage.")
    interest = _dec(body.get("client_interest_pct"), "The client interest")
    basis = (body.get("revenue_basis") or "GROSS").upper()
    if basis not in ("GROSS", "NET"):
        raise ReconError("The revenue basis is gross or net.")
    note = (body.get("note") or "").strip()
    if not note:
        raise ReconError("Please say why the setting changes (for example who approved it).")
    pid = int(body["platform_id"]) if body.get("platform_id") else None
    with access.tx(actor, client_id) as conn:
        old = db.one(conn, "SELECT * FROM reconciliation_settings WHERE client_id = %s AND replaced_at IS NULL AND "
                           "platform_id IS NOT DISTINCT FROM %s FOR UPDATE", (client_id, pid))
        if old:
            conn.execute("UPDATE reconciliation_settings SET replaced_at = now(), replaced_by = %s WHERE id = %s",
                         (actor["id"], old["id"]))
        sid = db.insert(conn, "reconciliation_settings", dict(
            client_id=client_id, platform_id=pid, benchmark_percentage=bench, client_interest_pct=interest,
            revenue_basis=basis, note=note, created_by=actor["id"]))
        if "iprs_currency" in body:
            cur = (body.get("iprs_currency") or "").strip().upper() or None
            cfg = db.scalar(conn, "SELECT settings FROM client WHERE id = %s", (client_id,)) or {}
            if cfg.get("iprs_currency") != cur:
                conn.execute("UPDATE client SET settings = %s WHERE id = %s",
                             (db.J({**cfg, "iprs_currency": cur}), client_id))
                audit.record(conn, "settings.iprs_currency_changed", actor, "client", client_id,
                             before=dict(iprs_currency=cfg.get("iprs_currency")), after=dict(iprs_currency=cur))
        audit.record(conn, "settings.reconciliation_changed", actor, "reconciliation_settings", sid,
                     dict(platform_id=pid, note=note),
                     before=None if not old else dict(benchmark_percentage=old["benchmark_percentage"],
                                                      client_interest_pct=old["client_interest_pct"],
                                                      revenue_basis=old["revenue_basis"]),
                     after=dict(benchmark_percentage=bench, client_interest_pct=interest, revenue_basis=basis))
    return settings_view(actor, client_id)


# ================================================================== the three kinds of statement
SIDES = ("PLATFORM", "CLIENT", "IPRS")
_SIDE_TYPES = {"PLATFORM": ("RECORDING_REVENUE", "RECORDING_USAGE"), "CLIENT": ("WORK_ROYALTY",),
               "IPRS": ("WORK_ROYALTY",)}
SIDE_NAME = {"PLATFORM": "platform report", "CLIENT": "client statement", "IPRS": "IPRS statement"}


def _side_statements(conn, client_id: int, platform_id: int, source: str, a: dt.date, b: dt.date) -> list[dict]:
    """Imported statements of one kind for the platform that touch the months a..b (or state no period)."""
    return db.all(conn, "SELECT * FROM statements WHERE client_id = %s AND import_status = 'IMPORTED' AND platform_id = "
                        "%s AND statement_source = %s AND record_type = ANY(%s) AND (usage_period_start IS NULL OR "
                        "(usage_period_start <= %s AND usage_period_end >= %s)) ORDER BY id",
                  (client_id, platform_id, source, list(_SIDE_TYPES[source]), b, a))


def _lines(conn, sts: list[dict], a: dt.date, b: dt.date) -> list[dict]:
    """Every line of these statements in one shape (kind REVENUE, USAGE or WORK). A per-ISRC line reaches a work
    through the catalogue link of its ISRC; a per-work line through its IPRS work number. Per-ISRC lines are kept for
    the months a..b."""
    rev = [s["id"] for s in sts if s["record_type"] == "RECORDING_REVENUE"]
    use = [s["id"] for s in sts if s["record_type"] == "RECORDING_USAGE"]
    wrk = [s["id"] for s in sts if s["record_type"] == "WORK_ROYALTY"]
    out = []
    for x in db.all(conn, "SELECT r.*, pl.plays FROM client_revenue_records r JOIN rd_platform_line pl ON pl.file_id = "
                          "r.file_id AND pl.line_no = r.line_no WHERE r.statement_id = ANY(%s) AND r.usage_period_start "
                          "BETWEEN %s AND %s ORDER BY r.statement_id, r.line_no", (rev, a, b)):
        out.append(dict(layout="ISRC", kind="REVENUE", statement_id=x["statement_id"], file_id=x["file_id"],
                        line_no=x["line_no"], source_row_number=x["source_row_number"], isrc=x["isrc"],
                        internal_work_number=None,
                        work_id=x["work_id"] if x["mapping_status"] in ("VERIFIED", "PENDING") else None,
                        link=x["mapping_status"], amount=x["reported_amount"], plays=x["plays"],
                        month=x["usage_period_start"], title=x["reported_title"], party=None, role=None, share=None))
    for x in db.all(conn, "SELECT * FROM platform_usage_records WHERE statement_id = ANY(%s) AND usage_period_start "
                          "BETWEEN %s AND %s ORDER BY statement_id, line_no", (use, a, b)):
        out.append(dict(layout="ISRC", kind="USAGE", statement_id=x["statement_id"], file_id=x["file_id"],
                        line_no=x["line_no"], source_row_number=x["source_row_number"], isrc=x["isrc"],
                        internal_work_number=None,
                        work_id=x["work_id"] if x["mapping_status"] in ("VERIFIED", "PENDING") else None,
                        link=x["mapping_status"], amount=None, plays=x["plays"], month=x["usage_period_start"],
                        title=x["reported_title"], party=None, role=None, share=None))
    for x in db.all(conn, "SELECT * FROM iprs_royalty_records WHERE statement_id = ANY(%s) ORDER BY statement_id, "
                          "line_no", (wrk,)):
        out.append(dict(layout="WORK", kind="WORK", statement_id=x["statement_id"], file_id=x["file_id"],
                        line_no=x["line_no"], source_row_number=x["source_row_number"], isrc=None,
                        internal_work_number=x["internal_work_number"] or None, work_id=x["work_id"],
                        link=x["mapping_status"], amount=x["royalty_amount"], plays=None, month=None,
                        title=x["reported_title"], party=x["party_name"], role=x["role"], share=x["collection_share"]))
    return out


def _coverage(sts: list[dict], lines: list[dict]) -> set:
    """The usage months a side covers with money: months with revenue lines, and every month of a per-work
    statement. Usage (plays) never decides coverage."""
    cov = {x["month"] for x in lines if x["kind"] == "REVENUE" and x["month"]}
    for s in sts:
        if s["record_type"] == "WORK_ROYALTY" and s["usage_period_start"]:
            cov.update(months_between(s["usage_period_start"], s["usage_period_end"]))
    return cov


def _usage(lines: list[dict]) -> tuple[list[dict], set]:
    """The plays of the platform side, combined from the usage reports and the revenue reports: a month's plays come
    from the usage report when one covers that month, otherwise from the revenue report's plays. -> (lines, months)."""
    um = {x["month"] for x in lines if x["kind"] == "USAGE"}
    out = [x for x in lines if x["plays"] is not None and (x["kind"] == "USAGE" or (x["kind"] == "REVENUE"
                                                                                    and x["month"] not in um))]
    return out, {x["month"] for x in out}


def _keep(sts: list[dict], lines: list[dict], months: set) -> tuple[list, list, list]:
    """Only the months given: per-ISRC lines of other months are left out; a per-work statement stays only when its
    whole usage period is inside (a partial overlap is never prorated). -> (statements, lines, left out + why)."""
    used, out = [], []
    for s in sts:
        if s["record_type"] == "WORK_ROYALTY":
            if not s["usage_period_start"]:
                out.append((s, "its usage period is not stated"))
                continue
            if not set(months_between(s["usage_period_start"], s["usage_period_end"])) <= months:
                out.append((s, f"its usage period ({_label(s['usage_period_start'], s['usage_period_end'])}) is not "
                               "inside the compared months"))
                continue
        used.append(s)
    ids = {s["id"] for s in used}
    return used, [x for x in lines if x["statement_id"] in ids and (x["layout"] == "WORK" or x["month"] in months)], out


def _months_text(ms) -> str:
    ms = sorted(ms)
    if not ms:
        return "none"
    spans, start, prev = [], ms[0], ms[0]
    for m in ms[1:] + [None]:
        if m is not None and (m.year * 12 + m.month) == (prev.year * 12 + prev.month) + 1:
            prev = m
            continue
        spans.append(f"{start:%b %Y}" if start == prev else f"{start:%b %Y} - {prev:%b %Y}")
        if m is not None:
            start = prev = m
    return ", ".join(spans)


def _fy(d: dt.date) -> int:
    return d.year if d.month >= 4 else d.year - 1


# ================================================================== what can be reconciled
def options(actor: dict, client_id: int) -> dict:
    """Every platform in the client's statements, with what each kind covers: the platform reports (revenue and usage
    months), the client's statements and the IPRS statements (their usage periods), the IPRS periods to compare and
    the financial years. A platform can be reconciled when IPRS's statements and the platform revenue (or, without a
    platform report, the client's statements) cover the same months."""
    with access.tx(actor, client_id) as conn:
        sts = db.all(conn, "SELECT s.id, s.record_type, s.statement_source, s.platform_id, p.platform_name, "
                           "s.usage_period_start, s.usage_period_end, s.statement_reference, s.original_filename, "
                           "s.total_amount, s.total_usage FROM statements s JOIN platforms p ON p.id = s.platform_id "
                           "WHERE s.client_id = %s AND s.import_status = 'IMPORTED' ORDER BY p.platform_name, "
                           "s.usage_period_start NULLS LAST, s.id", (client_id,))
        rev_m = db.all(conn, "SELECT platform_id, array_agg(DISTINCT usage_period_start ORDER BY usage_period_start) AS "
                             "months FROM client_revenue_records WHERE client_id = %s AND import_status = 'IMPORTED' AND "
                             "statement_source = 'PLATFORM' AND usage_period_start IS NOT NULL GROUP BY 1", (client_id,))
        use_m = db.all(conn, "SELECT platform_id, array_agg(DISTINCT usage_period_start ORDER BY usage_period_start) AS "
                             "months FROM platform_usage_records WHERE client_id = %s AND import_status = 'IMPORTED' AND "
                             "statement_source = 'PLATFORM' AND usage_period_start IS NOT NULL GROUP BY 1", (client_id,))
        st = current_settings(conn, client_id, None)
        own = {r["platform_id"]: r for r in db.all(conn, "SELECT * FROM reconciliation_settings WHERE client_id = %s "
                                                         "AND replaced_at IS NULL AND platform_id IS NOT NULL",
                                                   (client_id,))}
        others = db.all(conn, "SELECT coalesce(reported_platform, category, 'Not stated') AS category, record_type, "
                              "statement_source, count(*) AS statements FROM statements WHERE client_id = %s AND "
                              "import_status = 'IMPORTED' AND platform_id IS NULL GROUP BY 1, 2, 3 ORDER BY 1",
                        (client_id,))
    revenue_months = {m["platform_id"]: set(m["months"]) for m in rev_m}
    usage_months = {m["platform_id"]: set(m["months"]) for m in use_m}
    out: dict[int, dict] = {}
    for s in sts:
        p = out.setdefault(s["platform_id"], dict(platform_id=s["platform_id"], platform=s["platform_name"],
                                                  platform_reports=[], client=[], iprs=[], suggestions=[]))
        key = {"PLATFORM": "platform_reports", "CLIENT": "client", "IPRS": "iprs"}[s["statement_source"]]
        p[key].append(dict(id=s["id"], reference=s["statement_reference"], filename=s["original_filename"],
                           layout=s["record_type"], period_start=s["usage_period_start"],
                           period_end=s["usage_period_end"], total=s["total_amount"], usage=s["total_usage"]))
    for p in out.values():
        pid = p["platform_id"]
        rev = revenue_months.get(pid, set())
        cli, ipr = set(), set()
        for side, c in (("client", cli), ("iprs", ipr)):
            for s in p[side]:
                if s["period_start"]:
                    c.update(months_between(s["period_start"], s["period_end"]))
        base = rev or cli                       # what the IPRS statements are compared with
        p["base"] = "PLATFORM" if rev else "CLIENT" if cli else None
        seen = set()
        for s in p["iprs"]:
            a, b = s["period_start"], s["period_end"]
            if not a or not b or (a, b) in seen:
                continue
            seen.add((a, b))
            need = months_between(a, b)
            got = [m for m in need if m in base]
            p["suggestions"].append(dict(period_start=a, period_end=b, iprs_statement=s["reference"] or s["filename"],
                                         revenue_months=len(got), months=len(need), complete=len(got) == len(need),
                                         usage_months=sum(1 for m in need if m in usage_months.get(pid, set())),
                                         client_months=sum(1 for m in need if m in cli)))
        years = sorted({_fy(m) for m in rev | cli | ipr}, reverse=True)
        p["years"] = [dict(fy=y, label=f"FY {y}-{str(y + 1)[2:]}",
                           client_months=sum(1 for m in base if _fy(m) == y),
                           platform_months=sum(1 for m in rev if _fy(m) == y),
                           statement_months=sum(1 for m in cli if _fy(m) == y),
                           iprs_months=sum(1 for m in ipr if _fy(m) == y),
                           common_months=sum(1 for m in base & ipr if _fy(m) == y)) for y in years]
        p["ready"] = any(x["complete"] for x in p["suggestions"])
        p["year_ready"] = any(x["common_months"] for x in p["years"])
        p["setting"] = own.get(pid) or st
        p["own_benchmark"] = pid in own
        rs = sorted(rev)
        us = sorted(usage_months.get(pid, set()))
        p["revenue_months"] = [rs[0], rs[-1]] if rs else None
        p["usage_months"] = [us[0], us[-1]] if us else None
        p["revenue"] = p["platform_reports"] + p["client"]            # before 1.5.0: everything compared with IPRS
        p["status"] = ("READY" if p["ready"] else "NO_REVENUE" if not base else "NO_IPRS" if not p["iprs"]
                       else "YEAR_ONLY" if p["year_ready"] else "NO_OVERLAP")
    return dict(platforms=sorted(out.values(), key=lambda x: (not (x["ready"] or x["year_ready"]), x["platform"])),
                settings=st, interest_known=bool(st and st["client_interest_pct"]), others=others)


# ================================================================== the calculation (pure: data in, items out)
def _share(lines: list[dict]) -> Decimal | None:
    """The client's collection share printed for the work: per party and role once, summed over the parties."""
    per: dict[tuple, Decimal] = {}
    for ln in lines:
        if ln.get("share") is None:
            continue
        k = (ln["party"], ln["role"])
        per[k] = max(per.get(k, ZERO), Decimal(ln["share"]))
    return sum(per.values(), ZERO) if per else None


def _total(lines: list[dict]) -> Decimal | None:
    amounts = [x["amount"] for x in lines if x["amount"] is not None]
    return sum(amounts, ZERO) if amounts else None


def _plays(lines: list[dict]) -> Decimal | None:
    plays = [x["plays"] for x in lines if x["plays"] is not None]
    return sum(plays, ZERO) if plays else None


def _pc(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'))} %"


SOURCE_OF = {"REVENUE": "PLATFORM_REVENUE", "USAGE": "PLATFORM_USAGE"}


def compute(rev: list[dict], use: list[dict], cli: list[dict], iprs: list[dict], works: dict, conflict_works: dict,
            ctx: dict) -> list[dict]:
    """rev: platform revenue lines; use: platform usage lines (plays, see _usage); cli: the client's statement lines;
    iprs: IPRS's lines - all in the shape of _lines. works: id -> work. conflict_works: isrc -> [work numbers].
    ctx: period, settings, run-level comparability, and for a yearly run the lines of the same months a year earlier
    (prev_rev, prev_iprs). Returns items with their sources and exceptions.

    Per work: the platform revenue, its usage, the client's statement and what IPRS paid. The indicative reference is
    the benchmark (4 %) of the eligible revenue; when IPRS paid less, the work is UNDERPAID by the difference."""
    bench, interest, basis_ok = ctx["benchmark"], ctx["interest"], ctx["basis_ok"]
    share = interest if interest is not None else HUNDRED          # not set: the whole revenue (stated on the run)
    comparable, problems = ctx["comparable"], ctx["run_exceptions"]       # run-wide: (type, text)
    have_iprs, have_revenue = ctx["have_iprs"], ctx["have_revenue"]
    period = ctx["period_label"]
    by_work: dict[int, dict] = defaultdict(lambda: dict(rev=[], use=[], cli=[], iprs=[]))
    unmatched: dict[tuple, dict] = {}
    for side, lines in (("rev", rev), ("use", use), ("cli", cli), ("iprs", iprs)):
        for ln in lines:
            if ln["work_id"]:
                by_work[ln["work_id"]][side].append(ln)
            else:
                k = ("ISRC", ln["isrc"] or "") if ln["layout"] == "ISRC" else ("WORK", ln["internal_work_number"] or "")
                unmatched.setdefault(k, dict(rev=[], use=[], cli=[], iprs=[]))[side].append(ln)
    prev: dict[int, dict] = defaultdict(lambda: dict(rev=[], iprs=[]))
    for side, lines in (("rev", ctx.get("prev_rev")), ("iprs", ctx.get("prev_iprs"))):
        for ln in lines or []:
            if ln["work_id"]:
                prev[ln["work_id"]][side].append(ln)
    yearly = ctx.get("yearly", False)
    items = []

    def src(lines, kind=None):
        return [dict(source_type=kind or SOURCE_OF[x["kind"]], statement_id=x["statement_id"], file_id=x["file_id"],
                     line_no=x["line_no"], source_row_number=x["source_row_number"], isrc=x["isrc"],
                     internal_work_number=x["internal_work_number"], usage_month=x["month"],
                     contribution_amount=x["plays"] if x["kind"] == "USAGE" else x["amount"]) for x in lines]

    for wid, g in by_work.items():
        w = works[wid]
        revenue = _total(g["rev"])
        plays = _plays(g["use"])
        blank = sum(1 for x in g["rev"] if x["amount"] is None)
        royalty = _total(g["iprs"]) if g["iprs"] else None
        client = _total(g["cli"]) if g["cli"] else None
        isrcs = sorted({x["isrc"] for x in g["rev"] + g["use"] if x["isrc"]} | set(w.get("isrcs") or []))
        mapping = "PENDING" if any(x["link"] == "PENDING" for x in g["rev"] + g["use"]) else "VERIFIED"
        exc, checks = [], []
        if mapping == "PENDING":
            pend = sorted({x["isrc"] for x in g["rev"] + g["use"] if x["link"] == "PENDING"})
            exc.append(("MAPPING_NOT_VERIFIED", "WARNING", "The catalogue link of " + ", ".join(pend[:6])
                        + (" …" if len(pend) > 6 else "") + " to this work is not verified yet; it cannot support a "
                        "final enquiry until an Admin verifies it."))
        if w["catalogue_status"] in ("REVIEW", "TO_REGISTER"):
            exc.append(("AMBIGUOUS_WORK_MATCH", "WARNING",
                        f"The catalogue marks this work '{'needs review' if w['catalogue_status'] == 'REVIEW' else 'to register'}'"
                        + (f": {w['status_note']}" if w.get("status_note") else ".")))
        if blank:
            checks.append("BLANK_AMOUNTS")
            exc.append(("SOURCE_VALIDATION_ERROR", "WARNING", f"{blank} revenue line(s) for this work have no amount; "
                        "they are left out of the total as unknown (not zero)."))
        calc, eligible, reference, variance, observed = "NOT_COMPARABLE", None, None, None, None
        if revenue is None:
            if have_revenue and (royalty is not None or client is not None):
                exc.append(("NO_PLATFORM_REVENUE", "WARNING", f"The {ctx['platform']} reports show no revenue for this "
                            f"work in {period}, but " + " and ".join(x for x, ok in (
                                ("the client's statement", client is not None), ("IPRS", royalty is not None)) if ok)
                            + " show an amount. Check that its ISRCs are linked to it in the catalogue."))
            action = ("No comparison with the revenue: no platform revenue for this work in these months." if have_revenue
                      else "Client statement and IPRS compared; no platform report covers these months, so no "
                           "benchmark is calculated.")
        elif not have_iprs:
            action = "Nothing to compare yet: no IPRS statement for this platform and these months has been uploaded."
            checks.append("NO_IPRS_STATEMENT")
        elif not comparable:
            action = "Not comparable for this period: " + "; ".join(t for _, t in problems if t) + "."
            for t, text in problems:
                exc.append((t, "WARNING", text))
            checks.append("NOT_COMPARABLE")
        elif not basis_ok:
            calc = "NOT_CALCULATED"
            for t, text in problems:
                exc.append((t, "WARNING", text))
            checks.append("BASIS_UNCLEAR")
            action = "Establish the revenue basis (Settings → Reconciliation), then run again."
        else:
            calc = "CALCULATED"
            eligible = revenue * share / HUNDRED
            reference = eligible * bench / HUNDRED
            if royalty is not None:
                variance = reference - royalty
                observed = royalty / eligible * HUNDRED if eligible else None
            action = None
        diff = client - royalty if client is not None and royalty is not None else None
        if (revenue is not None or client is not None) and royalty is None and have_iprs and comparable:
            wno = w["internal_work_number"] or "without a work number"
            exc.append(("MISSING_IPRS_ENTRY", "HIGH", MISSING_IPRS + f" (work {wno}, {ctx['platform']}, "
                        f"{period}). This does not mean the royalty is zero or that an amount is owed."))
        if variance is not None and variance > TOLERANCE:
            exc.append(("UNDERPAID", "HIGH", f"IPRS paid {money(royalty)} for {period}: "
                        + (f"{_pc(observed)}" if observed is not None else "a share")
                        + f" of the platform revenue of {money(revenue)}"
                        + (f" ({int(plays):,} plays in {_months_text({x['month'] for x in g['use']})})" if plays else "")
                        + f". At {bench.normalize()} % the indicative reference is {money(reference)}, so IPRS paid "
                          f"{money(variance)} less. Ask IPRS why."))
        if diff is not None and abs(diff) > TOLERANCE and comparable:
            exc.append(("AMOUNT_MISMATCH", "WARNING", f"The client's statement shows {money(client)} for this work; IPRS "
                        f"paid {money(royalty)} (difference {money(diff)})."))
        if action is None:
            if mapping != "VERIFIED" or any(e[0] == "AMBIGUOUS_WORK_MATCH" for e in exc):
                action = "Verify the catalogue links of this work before using it in a query to IPRS."
            elif royalty is None:
                action = "Raise a query: no corresponding IPRS entry for this work."
            elif variance is not None and variance > TOLERANCE:
                action = (f"Underpaid: raise a query asking IPRS why this work received "
                          + (f"{_pc(observed)}" if observed is not None else "less")
                          + f" instead of {bench.normalize()} % of its {ctx['platform']} revenue for {period}.")
            else:
                action = "No action: IPRS paid at or above the indicative reference."
        pg = prev.get(wid) if yearly else None
        items.append(dict(
            item_kind="WORK", work_id=wid, internal_work_number=w["internal_work_number"], work_title=w["work_title"],
            isrcs=isrcs, sound_recording_revenue=revenue, revenue_lines=len(g["rev"]), eligible_revenue_basis=_q(eligible),
            client_interest_share=interest, iprs_client_share=_share(g["iprs"]), benchmark_percentage=bench,
            reference_benchmark_amount=_q(reference), iprs_royalty_amount=royalty, iprs_lines=len(g["iprs"]),
            observed_percentage=_q(observed), indicative_variance=_q(variance), mapping_status=mapping,
            usage_plays=plays, usage_lines=len(g["use"]), client_statement_amount=client,
            client_statement_lines=len(g["cli"]), client_iprs_difference=_q(diff),
            data_validation_status=",".join(checks) or "OK", calculation_status=calc, recommended_action=action,
            previous_revenue=_total(pg["rev"]) if pg else None, previous_iprs_royalty=_total(pg["iprs"]) if pg else None,
            exceptions=exc, sources=src(g["rev"]) + src(g["use"]) + src(g["cli"], "CLIENT_STATEMENT")
            + src(g["iprs"], "IPRS_ROYALTY")))
    for (layout, code), g in unmatched.items():
        lines = g["rev"] + g["use"] + g["cli"] + g["iprs"]
        title = next((x["title"] for x in lines if x["title"]), None)
        if layout == "ISRC":
            st = lines[0]["link"]
            if not code:
                exc = [("SOURCE_VALIDATION_ERROR", "WARNING", f"{len(lines)} line(s) have no ISRC, so they cannot be "
                        "linked to a work. They are kept as unmatched.")]
                action, mapping = "Ask for the missing ISRCs, or correct the source file.", "NO_ISRC"
            elif st == "CONFLICT":
                others = conflict_works.get(code) or []
                exc = [("CONFLICTING_ISRC_MAPPING", "HIGH", f"{code} is linked to more than one work in the catalogue ("
                        + ", ".join(others[:5]) + "); its money is not counted for any work until the conflict is "
                        "resolved.")]
                action, mapping = "Resolve the conflicting catalogue links for this ISRC (Catalogue → Conflicts).", \
                    "CONFLICT"
            else:
                exc = [("UNKNOWN_ISRC", "WARNING", f"{code} is not in the catalogue, so its revenue and usage are not "
                        "linked to any work.")]
                action, mapping = "Link this ISRC to its work in the catalogue (a title match alone is not enough).", \
                    "UNKNOWN"
            kind = "UNMATCHED_RECORDING"
        else:
            if code:
                where = " and ".join(x for x, ok in (("the client's statements", g["cli"]), ("IPRS's statements",
                                                                                              g["iprs"])) if ok)
                exc = [("WORK_NOT_FOUND", "WARNING", f"Work {code} ('{title}') is in {where} but not in the catalogue.")]
                action, mapping = "Check whether this work belongs to the client; add it to the catalogue if it does.", \
                    "WORK_NOT_FOUND"
            else:
                exc = [("SOURCE_VALIDATION_ERROR", "WARNING", f"{len(lines)} line(s) have no work number.")]
                action, mapping = "Ask for the work numbers of these lines.", "NO_WORK_NUMBER"
            kind = "UNMATCHED_WORK"
        client = _total(g["cli"]) if g["cli"] else None
        royalty = _total(g["iprs"]) if g["iprs"] else None
        items.append(dict(
            item_kind=kind, work_id=None, internal_work_number=code if layout == "WORK" and code else None,
            work_title=title, isrcs=[code] if layout == "ISRC" and code else [],
            sound_recording_revenue=_total(g["rev"]), revenue_lines=len(g["rev"]), eligible_revenue_basis=None,
            client_interest_share=None, iprs_client_share=_share(g["iprs"]), benchmark_percentage=bench,
            reference_benchmark_amount=None, iprs_royalty_amount=royalty, iprs_lines=len(g["iprs"]),
            observed_percentage=None, indicative_variance=None, mapping_status=mapping,
            usage_plays=_plays(g["use"]), usage_lines=len(g["use"]), client_statement_amount=client,
            client_statement_lines=len(g["cli"]),
            client_iprs_difference=_q(client - royalty) if client is not None and royalty is not None else None,
            data_validation_status="UNMATCHED", calculation_status="NOT_COMPARABLE", recommended_action=action,
            previous_revenue=None, previous_iprs_royalty=None,
            exceptions=exc, sources=src(g["rev"]) + src(g["use"]) + src(g["cli"], "CLIENT_STATEMENT")
            + src(g["iprs"], "IPRS_ROYALTY")))
    rank = {"WORK": 0, "UNMATCHED_RECORDING": 1, "UNMATCHED_WORK": 2}
    items.sort(key=lambda i: (rank[i["item_kind"]], -(i["sound_recording_revenue"] or i["client_statement_amount"]
                                                      or i["iprs_royalty_amount"] or ZERO),
                              -(i["usage_plays"] or ZERO), i["work_title"] or "", i["internal_work_number"] or "",
                              ",".join(i["isrcs"])))
    return items


# ================================================================== running a reconciliation
def _period(a, b) -> tuple[dt.date, dt.date]:
    a, b = _date(a), _date(b)
    if not a or not b:
        raise ReconError("Choose the usage period (first and last month).")
    a, b = dt.date(a.year, a.month, 1), month_end(b.year, b.month)
    if b < a:
        raise ReconError("The period ends before it starts.")
    if len(months_between(a, b)) > 36:
        raise ReconError("Choose a usage period of at most 36 months.")
    return a, b


def _label(a: dt.date, b: dt.date) -> str:
    return f"{a:%b %Y} - {b:%b %Y}"


def _fy_label(a: dt.date) -> str:
    return f"FY {a.year}-{str(a.year + 1)[2:]}"


def _gather(conn, client_id: int, platform_id: int, a: dt.date, b: dt.date, months: set) -> dict:
    """The three kinds of statement for the platform and months: platform reports (revenue + usage), the client's
    statements and IPRS's statements, each kept to the months given."""
    out = {}
    for side in SIDES:
        sts = _side_statements(conn, client_id, platform_id, side, a, b)
        lines = _lines(conn, sts, a, b)
        used, kept, left = _keep(sts, lines, months)
        out[side] = dict(all=sts, all_lines=lines, used=used, lines=kept, left=left)
    return out


def start_run(actor: dict, client_id: int, platform_id: int, period_from, period_to, mode: str = "PERIOD",
              fy=None) -> dict:
    """PERIOD: one usage period; every month must be covered by IPRS's statements and by the platform revenue (or,
    without a platform report, by the client's statements). YEAR: one Indian financial year (Apr-Mar); the months both
    cover are compared (the others are named and left out), with the same months a year earlier beside them. The
    client's statements are compared too when their usage period is inside the compared months."""
    access.require(actor, "prepare")
    yearly = mode == "YEAR"
    if yearly:
        try:
            y = int(fy)
        except (TypeError, ValueError):
            raise ReconError("Choose the financial year.") from None
        a, b = dt.date(y, 4, 1), dt.date(y + 1, 3, 31)
    else:
        a, b = _period(period_from, period_to)
    with access.tx(actor, client_id) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(84726400, %s)", (client_id,))
        p = platforms.require_platform(conn, platform_id)
        c = db.one(conn, "SELECT code, name FROM client WHERE id = %s", (client_id,))
        setting = current_settings(conn, client_id, platform_id)
        if not setting:
            raise ReconError("No reference benchmark is set for this client. The Super Admin sets it under Settings → "
                             "Reconciliation.")
        span = _fy_label(a) if yearly else _label(a, b)
        need = set(months_between(a, b))
        g = _gather(conn, client_id, platform_id, a, b, need)
        if not any(g[s]["all"] for s in SIDES):
            raise ReconError(f"There is no imported {p['platform_name']} statement for {span}. Upload the platform "
                             "report, the client's statement and the IPRS statement under Statements first, in any "
                             "order.")
        have_revenue = any(x["kind"] == "REVENUE" for x in g["PLATFORM"]["lines"])
        base = "PLATFORM" if have_revenue else "CLIENT"            # what IPRS's statements are compared with
        notes, run_exc = [], []
        compared = need
        if yearly:                                  # like with like: only the months both cover
            for _ in range(6):
                common = _coverage(g[base]["used"], g[base]["lines"]) & _coverage(g["IPRS"]["used"], g["IPRS"]["lines"]) \
                    & need
                if common == compared:
                    break
                compared = common
                for side in SIDES:
                    used, kept, left = _keep(g[side]["used"], g[side]["lines"], compared)
                    g[side].update(used=used, lines=kept)
                    g[side]["left"] += left
            only_b = (_coverage(g[base]["all"], g[base]["all_lines"]) & need) - compared
            only_i = (_coverage(g["IPRS"]["all"], g["IPRS"]["all_lines"]) & need) - compared
            what = "the platform revenue" if base == "PLATFORM" else "the client's statements"
            if compared:
                notes.append(f"Yearly comparison for {span}: the {len(compared)} month(s) covered by both {what} and "
                             f"IPRS's statements are compared ({_months_text(compared)}).")
            if only_b:
                notes.append(f"Months only {what} cover are left out: {_months_text(only_b)}.")
            if only_i:
                notes.append(f"Months only IPRS's statements cover are left out: {_months_text(only_i)}.")
            if not compared:
                t = f"no month of {span} is covered by both {what} and IPRS's statements"
                notes.append(t[0].upper() + t[1:] + ".")
                run_exc.append(("MISSING_USAGE_PERIOD", t[0].upper() + t[1:]))
            miss_base = miss_iprs = []
        else:
            miss_base = sorted(need - _coverage(g[base]["used"], g[base]["lines"]))
            miss_iprs = sorted(need - _coverage(g["IPRS"]["used"], g["IPRS"]["lines"]))
            if not g["PLATFORM"]["used"] and not g["CLIENT"]["used"]:
                notes.append(f"No platform report and no client statement for {p['platform_name']} covers {span}.")
            elif miss_base:
                t = ("The platform revenue is missing " if base == "PLATFORM" else
                     "The client's statements are missing ") + _months_text(miss_base)
                notes.append(t + ".")
                run_exc.append(("MISSING_USAGE_PERIOD", t))
            if not g["IPRS"]["used"]:
                notes.append(f"No IPRS statement for {p['platform_name']} with a usage period inside {span} has been "
                             "uploaded, so nothing can be compared and no missing-entry exception is raised.")
            elif miss_iprs:
                t = "The IPRS statements do not cover " + _months_text(miss_iprs)
                notes.append(t + ".")
                run_exc.append(("MISSING_USAGE_PERIOD", t))
        rev = [x for x in g["PLATFORM"]["lines"] if x["kind"] == "REVENUE"]
        use, use_months = _usage(g["PLATFORM"]["lines"])
        cli, iprs = g["CLIENT"]["lines"], g["IPRS"]["lines"]
        if base == "PLATFORM":
            cm = sorted(compared)
            if use_months:
                notes.append(f"Usage (plays) from the platform reports covers {_months_text(use_months)}"
                             + (f"; no usage report for {_months_text(set(cm) - use_months)}." if set(cm) - use_months
                                else "."))
            else:
                notes.append("No usage (plays) for these months in the platform reports.")
        else:
            notes.append(f"No {p['platform_name']} platform report covers {span}: the client's statements are compared "
                         "with IPRS's statements, and no benchmark is calculated.")
        if base == "PLATFORM" and not g["CLIENT"]["used"]:
            notes.append(f"No client statement for {p['platform_name']} with a usage period inside {span}; the client "
                         "statement column stays empty.")
        for side in SIDES:
            for s, why in g[side]["left"]:
                notes.append(f"{SIDE_NAME[side].capitalize()} #{s['id']} ({s['original_filename']}) was left out: "
                             f"{why}.")
        money_sts = [s for s in g["PLATFORM"]["used"] if s["record_type"] == "RECORDING_REVENUE"] + \
            g["CLIENT"]["used"] + g["IPRS"]["used"]
        curs = {s["currency"] for s in money_sts}
        currency = None
        if None in curs:
            t = "the currency of a statement is not known"
            notes.append(t.capitalize() + ".")
            run_exc.append(("MISSING_CURRENCY", t.capitalize()))
        elif len(curs) > 1:
            t = "the statements are in different currencies (" + ", ".join(sorted(curs)) + ")"
            notes.append(t.capitalize() + "; amounts in different currencies are never compared.")
            run_exc.append(("MISSING_CURRENCY", t.capitalize()))
        else:
            currency = next(iter(curs), None)
        terr = {s["territory"] for s in money_sts}
        territory = next(iter(terr - {None}), None) if len(terr - {None}) == 1 else None
        terr_bad = len(terr - {None}) > 1
        if terr_bad:
            t = "the statements state different territories"
            notes.append(t.capitalize() + ".")
            run_exc.append(("SOURCE_VALIDATION_ERROR", t.capitalize()))
        base_ok = bool(g[base]["used"]) and (bool(compared) if yearly else not miss_base)
        comparable = base_ok and bool(g["IPRS"]["used"]) and (bool(compared) if yearly else not miss_iprs) \
            and currency is not None and not terr_bad
        bases = {s["revenue_basis"] for s in g["PLATFORM"]["used"] if s["record_type"] == "RECORDING_REVENUE"}
        basis_ok = not bases or bases == {setting["revenue_basis"]}
        if not basis_ok:
            t = (f"the revenue basis of the platform report ({', '.join(sorted(x or 'not stated' for x in bases))})"
                 f" is not the configured basis ({setting['revenue_basis']})")
            notes.append(t.capitalize() + ".")
            run_exc.append(("REVENUE_BASIS_UNCLEAR", t.capitalize()))
        interest = setting["client_interest_pct"]
        if base == "PLATFORM":
            notes.append(f"Indicative reference = {setting['benchmark_percentage'].normalize()} % of the "
                         + (f"eligible revenue ({interest.normalize()} % client interest)." if interest is not None
                            else "platform revenue (the client interest is not set, so the whole revenue counts).")
                         + " A work is underpaid when IPRS paid less than that.")
        # ---- the year before, for the same months (yearly runs)
        prev_rev, prev_iprs, pa, pb, prev_pl, prev_ip = [], [], None, None, [], []
        if yearly and compared:
            pm = {dt.date(m.year - 1, m.month, 1) for m in compared}
            pa, pb = min(pm), month_end(max(pm).year, max(pm).month)
            pg = _gather(conn, client_id, platform_id, pa, pb, pm)
            prev_pl, prev_ip = pg[base]["used"], pg["IPRS"]["used"]
            prev_rev = [x for x in pg[base]["lines"] if x["kind"] in ("REVENUE", "WORK")]
            prev_iprs = pg["IPRS"]["lines"]
            cc, ci = _coverage(prev_pl, prev_rev) & pm, _coverage(prev_ip, prev_iprs) & pm
            notes.append(f"Year before ({_months_text(pm)}): "
                         + ("the platform revenue covers" if base == "PLATFORM" else "the client's statements cover")
                         + f" {len(cc)} of {len(pm)} month(s), IPRS's statements {len(ci)} of {len(pm)}. "
                         "Year-on-year figures are shown beside the comparison; they are not part of the calculation.")
        if base == "CLIENT":                       # no platform report: the client's statement stands beside IPRS
            rev = []
        wids = {x["work_id"] for x in rev + use + cli + iprs if x["work_id"]}
        works = {w["id"]: w for w in db.all(conn, "SELECT w.id, w.internal_work_number, w.work_title, "
                                                  "w.catalogue_status, w.status_note, coalesce(array_agg(x.isrc) FILTER "
                                                  "(WHERE x.isrc IS NOT NULL), '{}') AS isrcs FROM works w LEFT JOIN "
                                                  "current_work_recordings x ON x.work_id = w.id WHERE w.id = ANY(%s) "
                                                  "GROUP BY w.id", (sorted(wids),))}
        conflict_works = {r["isrc"]: r["works"] for r in db.all(
            conn, "SELECT isrc, array_agg(coalesce(internal_work_number, work_title) ORDER BY internal_work_number) AS "
                  "works FROM current_work_recordings WHERE client_id = %s AND isrc = ANY(%s) GROUP BY isrc",
            (client_id, sorted({x["isrc"] for x in rev + use if x["link"] == "CONFLICT" and x["isrc"]})))}
        n = (db.scalar(conn, "SELECT count(*) FROM reconciliation_runs WHERE client_id = %s", (client_id,)) or 0) + 1
        ref = f"{c['code']}-REC-{n:04d}"

        def snap(sts):
            return [dict(id=s["id"], file=s["original_filename"], sha256=s["file_hash"], reference=s["statement_reference"],
                         period=[s["usage_period_start"], s["usage_period_end"]], layout=s["record_type"],
                         basis=s["revenue_basis"], currency=s["currency"], total=s["total_amount"],
                         usage=s["total_usage"]) for s in sts]
        snapshot = dict(platform_reports=snap(g["PLATFORM"]["used"]), client_statements=snap(g["CLIENT"]["used"]),
                        iprs_statements=snap(g["IPRS"]["used"]), base=base,
                        revenue_statements=snap(g[base]["used"]),
                        previous_revenue_statements=snap(prev_pl), previous_iprs_statements=snap(prev_ip),
                        left_out=[s["id"] for side in SIDES for s, _w in g[side]["left"]], revenue_lines=len(rev),
                        usage_lines=len(use), client_lines=len(cli), iprs_lines=len(iprs),
                        usage_months=sorted(use_months),
                        catalogue_links=db.scalar(conn, "SELECT count(*) FROM current_work_recordings WHERE client_id "
                                                        "= %s", (client_id,)), settings_id=setting["id"])
        snap_sha = hashlib.sha256(db.dumps(snapshot).encode()).hexdigest()
        rid = db.insert(conn, "reconciliation_runs", dict(
            client_id=client_id, run_reference=ref, platform_id=platform_id, usage_period_start=a, usage_period_end=b,
            benchmark_percentage=setting["benchmark_percentage"], client_interest_pct=interest,
            revenue_basis=setting["revenue_basis"], settings_id=setting["id"], run_kind="YEAR" if yearly else "PERIOD",
            compared_months=db.J(sorted(compared)), previous_period_start=pa, previous_period_end=pb,
            filters_json=dict(platform=p["platform_code"], period_from=a, period_to=b, mode=mode),
            source_snapshot=snapshot, source_snapshot_sha256=snap_sha, notes=db.J(notes), status="RUNNING",
            started_by=actor["id"]))
        items = compute(rev, use, cli, iprs, works, conflict_works, dict(
            benchmark=setting["benchmark_percentage"], interest=interest, basis_ok=basis_ok, comparable=comparable,
            run_exceptions=run_exc, have_iprs=bool(g["IPRS"]["used"]), have_revenue=base == "PLATFORM",
            platform=p["platform_name"], period_label=span, yearly=yearly, prev_rev=prev_rev, prev_iprs=prev_iprs))
        _store(conn, client_id, rid, items, platform_id, a, b, territory, currency)
        summary = _summary(items)
        summary.update(comparable=comparable, interest_known=interest is not None, basis_ok=basis_ok,
                       currency=currency, compared_months=len(compared), base=base)
        conn.execute("UPDATE reconciliation_runs SET status = 'COMPLETED', summary = %s, completed_at = now() WHERE "
                     "id = %s", (db.J(summary), rid))
        audit.record(conn, "recon.run_completed", actor, "reconciliation_runs", rid,
                     dict(reference=ref, platform=p["platform_name"], period=span, kind="YEAR" if yearly else "PERIOD",
                          items=len(items), snapshot_sha256=snap_sha, benchmark=setting["benchmark_percentage"],
                          client_interest=interest, underpaid=summary["underpaid"]))
    return run_view(actor, rid)


def _store(conn, client_id, rid, items, platform_id, a, b, territory, currency) -> None:
    for no, it in enumerate(items, 1):
        exc, srcs = it.pop("exceptions"), it.pop("sources")
        iid = db.insert(conn, "reconciliation_items", dict(
            it, reconciliation_run_id=rid, client_id=client_id, item_no=no, platform_id=platform_id,
            usage_period_start=a, usage_period_end=b, territory=territory, currency=currency,
            exception_status="OPEN" if exc else "NONE"))
        it["id"], it["exceptions"] = iid, exc
        db.insert_many(conn, "reconciliation_sources", (
            "reconciliation_item_id", "client_id", "source_type", "statement_id", "file_id", "line_no",
            "source_row_number", "isrc", "internal_work_number", "usage_month", "contribution_amount"),
            ((iid, client_id, x["source_type"], x["statement_id"], x["file_id"], x["line_no"], x["source_row_number"],
              x["isrc"], x["internal_work_number"], x["usage_month"], x["contribution_amount"]) for x in srcs))
    db.insert_many(conn, "reconciliation_exceptions", (
        "reconciliation_item_id", "reconciliation_run_id", "client_id", "exception_type", "severity", "description"),
        ((it["id"], rid, client_id, t, sev, text) for it in items for (t, sev, text) in it["exceptions"]))


def _summary(items: list[dict]) -> dict:
    works = [i for i in items if i["item_kind"] == "WORK"]
    calc = [i for i in works if i["calculation_status"] == "CALCULATED"]
    under = [i for i in calc if i["indicative_variance"] is not None and i["indicative_variance"] > TOLERANCE]
    exc = defaultdict(int)
    for i in items:
        for t, _s, _x in i["exceptions"]:
            exc[t] += 1
    tot = lambda xs, k: sum((x[k] for x in xs if x[k] is not None), ZERO)      # noqa: E731
    rest = [i for i in items if i["item_kind"] != "WORK"]
    return dict(items=len(items), works=len(works), calculated=len(calc),
                compared=sum(1 for i in calc if i["iprs_royalty_amount"] is not None),
                missing_iprs=exc.get("MISSING_IPRS_ENTRY", 0),
                unmatched_recordings=sum(1 for i in items if i["item_kind"] == "UNMATCHED_RECORDING"),
                unmatched_works=sum(1 for i in items if i["item_kind"] == "UNMATCHED_WORK"),
                revenue_matched=tot(works, "sound_recording_revenue"),
                revenue_unmatched=tot(rest, "sound_recording_revenue"),
                iprs_matched=tot(works, "iprs_royalty_amount"),
                iprs_unmatched=tot(rest, "iprs_royalty_amount"),
                previous_revenue=tot(works, "previous_revenue") if any(i["previous_revenue"] is not None
                                                                        for i in works) else None,
                previous_iprs=tot(works, "previous_iprs_royalty") if any(i["previous_iprs_royalty"] is not None
                                                                         for i in works) else None,
                eligible=tot(calc, "eligible_revenue_basis"), reference=tot(calc, "reference_benchmark_amount"),
                positive_variance=sum((i["indicative_variance"] for i in calc if i["indicative_variance"] is not None
                                       and i["indicative_variance"] > 0), ZERO),
                underpaid=len(under), shortfall=tot(under, "indicative_variance"),
                underpaid_revenue=tot(under, "sound_recording_revenue"), underpaid_paid=tot(under, "iprs_royalty_amount"),
                usage=tot(works, "usage_plays") if any(i["usage_plays"] is not None for i in works) else None,
                usage_unmatched=tot(rest, "usage_plays") if any(i["usage_plays"] is not None for i in rest) else None,
                client_matched=tot(works, "client_statement_amount") if any(i["client_statement_amount"] is not None
                                                                             for i in works) else None,
                client_differences=exc.get("AMOUNT_MISMATCH", 0), no_platform_revenue=exc.get("NO_PLATFORM_REVENUE", 0),
                iprs_compared=tot([i for i in calc if i["iprs_royalty_amount"] is not None], "iprs_royalty_amount"),
                revenue_compared=tot([i for i in calc if i["iprs_royalty_amount"] is not None],
                                     "sound_recording_revenue"),
                exceptions=dict(exc))


# ================================================================== reading runs and items
def _later(conn, run: dict) -> dict:
    """IPRS statements for the run's platform that arrived after the run (or were not in it) and overlap its period:
    work number -> [statements]. They may already address a difference, so they are reviewed before any enquiry."""
    used = {s["id"] for s in run["source_snapshot"].get("iprs_statements", [])}
    sts = db.all(conn, "SELECT id, original_filename, statement_reference, usage_period_start, usage_period_end, "
                       "uploaded_at FROM statements WHERE client_id = %s AND statement_source = 'IPRS' AND "
                       "record_type = 'WORK_ROYALTY' AND import_status = 'IMPORTED' AND platform_id = %s AND (usage_period_start IS NULL OR "
                       "(usage_period_start <= %s AND usage_period_end >= %s)) AND NOT (id = ANY(%s))",
                 (run["client_id"], run["platform_id"], run["usage_period_end"], run["usage_period_start"], sorted(used)))
    out: dict[str, list] = defaultdict(list)
    for s in sts:
        for r in db.all(conn, "SELECT DISTINCT internal_work_number FROM iprs_royalty_records WHERE statement_id = %s "
                              "AND internal_work_number IS NOT NULL", (s["id"],)):
            out[r["internal_work_number"]].append(dict(id=s["id"], filename=s["original_filename"],
                                                       reference=s["statement_reference"],
                                                       uploaded_at=s["uploaded_at"]))
    return out


# ================================================================== period by period (as in the master)
_BUCKET = ("coalesce(s.usage_month, st.usage_period_start) AS a, CASE WHEN s.usage_month IS NOT NULL THEN "
           "(s.usage_month + interval '1 month' - interval '1 day')::DATE ELSE st.usage_period_end END AS b")


REVENUE_TYPES = ("CLIENT_REVENUE", "PLATFORM_REVENUE")       # CLIENT_REVENUE: runs before 1.5.0
BAND_OF = {"CLIENT_REVENUE": "source", "PLATFORM_REVENUE": "source", "PLATFORM_USAGE": "usage",
           "CLIENT_STATEMENT": "client", "IPRS_ROYALTY": "iprs"}


def _pkey(a, b) -> str:
    return f"{a}|{b}"


def _plabel(a: dt.date, b: dt.date) -> str:
    return f"{a:%b %Y}" if (a.year, a.month) == (b.year, b.month) else f"{a:%b %Y} - {b:%b %Y}"


def period_columns(conn, run_id: int) -> dict:
    """The usage periods of a run on each side, in order: a month for per-ISRC lines, the statement's period for
    per-work statements (with their distribution numbers). The columns of the master-like report."""
    rows = db.all(conn, f"SELECT s.source_type, {_BUCKET}, array_agg(DISTINCT st.statement_reference) FILTER (WHERE "
                        "s.usage_month IS NULL AND st.statement_reference IS NOT NULL) AS refs FROM "
                        "reconciliation_sources s JOIN reconciliation_items i ON i.id = s.reconciliation_item_id JOIN "
                        "statements st ON st.id = s.statement_id WHERE i.reconciliation_run_id = %s GROUP BY 1, 2, 3 "
                        "ORDER BY 2, 3", (run_id,))
    out: dict[str, list] = dict(source=[], usage=[], client=[], iprs=[])
    for r in rows:
        if r["a"] is None:
            continue
        out[BAND_OF[r["source_type"]]].append(dict(
            key=_pkey(r["a"], r["b"]), start=r["a"], end=r["b"], label=_plabel(r["a"], r["b"]),
            refs=sorted(r["refs"] or [])))
    return out


def period_amounts(conn, item_ids: list[int]) -> dict:
    """item id -> {source: {period key: amount}, iprs: {…}}; a period with only blank amounts stays out (not zero)."""
    rows = db.all(conn, f"SELECT s.reconciliation_item_id AS item, s.source_type, {_BUCKET}, sum(s.contribution_amount) "
                        "AS amount FROM reconciliation_sources s JOIN statements st ON st.id = s.statement_id WHERE "
                        "s.reconciliation_item_id = ANY(%s) GROUP BY 1, 2, 3, 4", (item_ids,))
    out: dict = defaultdict(lambda: dict(source={}, usage={}, client={}, iprs={}))
    for r in rows:
        if r["a"] is not None and r["amount"] is not None:
            out[r["item"]][BAND_OF[r["source_type"]]][_pkey(r["a"], r["b"])] = r["amount"]
    return out


# ================================================================== statement by statement (the song report layout)
SIDE_BAND = {"PLATFORM": "platform", "CLIENT": "client statement", "IPRS": "IPRS royalty"}


def run_blocks(conn, run: dict) -> list[dict]:
    """The statements of a run as report blocks, in order: the platform's revenue reports, the client's statements,
    the IPRS statements. Each block is one statement: its date, the usage period it covers in the run, its
    distribution number, and how much of that period the platform's usage (plays) covers."""
    snap = run["source_snapshot"] or {}
    if "platform_reports" in snap:
        groups = [("PLATFORM", [x for x in snap["platform_reports"] if x.get("layout") == "RECORDING_REVENUE"]),
                  ("CLIENT", snap.get("client_statements") or []), ("IPRS", snap.get("iprs_statements") or [])]
    else:                                                  # runs before 1.5.0: the client's side was the revenue
        groups = [("CLIENT", snap.get("revenue_statements") or []), ("IPRS", snap.get("iprs_statements") or [])]
    ids = [x["id"] for _, xs in groups for x in xs]
    sts = {r["id"]: r for r in db.all(conn, "SELECT id, original_filename, statement_reference, usage_period_start, "
                                            "usage_period_end, statement_date, payment_date, uploaded_at FROM "
                                            "statements WHERE id = ANY(%s)", (ids,))}
    used = {r["statement_id"] for r in db.all(conn, "SELECT DISTINCT s.statement_id FROM reconciliation_sources s "
                                                    "JOIN reconciliation_items i ON i.id = s.reconciliation_item_id "
                                                    "WHERE i.reconciliation_run_id = %s AND s.source_type <> "
                                                    "'PLATFORM_USAGE'", (run["id"],))}
    cm = sorted(_date(m) for m in (run.get("compared_months") or []))
    ra, rb = (cm[0], month_end(cm[-1].year, cm[-1].month)) if cm else (run["usage_period_start"], run["usage_period_end"])
    um = {_date(m) for m in (snap.get("usage_months") or [])}
    out = []
    for side, xs in groups:
        rows = []
        for x in xs:
            st = sts.get(x["id"])
            if not st or x["id"] not in used:
                continue
            a = max(filter(None, (st["usage_period_start"], ra)))
            b = min(filter(None, (st["usage_period_end"], rb)))
            need = set(months_between(a, b)) if a and b and a <= b else set()
            have = need & um
            usage_label = ("plays" if have == need and need else
                           f"plays, {_months_text(have)} only" if have else "no usage report")
            rows.append(dict(key=str(x["id"]), side=side, statement_id=x["id"], file=st["original_filename"],
                             reference=st["statement_reference"] or st["original_filename"].rsplit(".", 1)[0],
                             date=st["statement_date"] or st["payment_date"] or st["uploaded_at"].date(),
                             period_start=a, period_end=b, period_label=_plabel(a, b) if a and b else "not stated",
                             usage_label=usage_label))
        out += sorted(rows, key=lambda r: (r["period_start"] or dt.date.min, r["statement_id"]))
    return out


def block_values(conn, item_ids: list[int], blocks: list[dict]) -> dict:
    """item id -> {block key: {amount, lines, usage}}: the amount of each statement for the song, and the plays the
    platform reported for the song in that statement's period (never 0 for 'no record')."""
    keys = {b["statement_id"]: b for b in blocks}
    out: dict = defaultdict(dict)
    for r in db.all(conn, "SELECT reconciliation_item_id AS item, statement_id, sum(contribution_amount) AS amount, "
                          "count(*) AS lines FROM reconciliation_sources WHERE reconciliation_item_id = ANY(%s) AND "
                          "source_type <> 'PLATFORM_USAGE' GROUP BY 1, 2", (item_ids,)):
        b = keys.get(r["statement_id"])
        if b:
            out[r["item"]][b["key"]] = dict(amount=r["amount"], lines=r["lines"], usage=None)
    plays = db.all(conn, "SELECT reconciliation_item_id AS item, usage_month, sum(contribution_amount) AS plays FROM "
                         "reconciliation_sources WHERE reconciliation_item_id = ANY(%s) AND source_type = "
                         "'PLATFORM_USAGE' AND usage_month IS NOT NULL GROUP BY 1, 2", (item_ids,))
    for r in plays:
        for b in blocks:
            if b["period_start"] and b["period_start"] <= r["usage_month"] <= b["period_end"]:
                d = out[r["item"]].setdefault(b["key"], dict(amount=None, lines=0, usage=None))
                d["usage"] = (d["usage"] or ZERO) + r["plays"]
    return out


def _q2(v):
    return None if v is None else Decimal(v).quantize(Decimal("0.01"))


def variance_pct(i: dict) -> Decimal | None:
    """The variance as a share of the expected royalty: + underpaid, - paid more than expected."""
    ref, var = i.get("reference_benchmark_amount"), i.get("indicative_variance")
    if ref is None or var is None or not Decimal(ref):
        return None
    return (Decimal(var) / Decimal(ref) * HUNDRED).quantize(Decimal("0.01"))


def result_of(i: dict) -> str:
    if i["item_kind"] != "WORK":
        return KIND_LABEL[i["item_kind"]]
    if i["iprs_royalty_amount"] is None and i["sound_recording_revenue"] is not None:
        return "No IPRS entry"
    if i["indicative_variance"] is None:
        return "Not calculated" if i["sound_recording_revenue"] is not None else "No platform revenue"
    return "Underpaid" if Decimal(i["indicative_variance"]) > TOLERANCE else "Paid in full"


def block_sheet(wb: Workbook, title: str, *, platform: str, client_code: str, benchmark, blocks: list[dict],
                items: list[dict], values: dict, notes: list[str], status: dict | None = None, interest=None) -> None:
    """The song report: Internal No · Song name · ISRC, then one section per kind - the platform (e.g. SPOTIFY),
    the client's statements, IPRS ROYALTY - with, for each statement, Amount · Date · Period (period, usage) ·
    Distribution number; then the check: the revenue the benchmark is taken of, expected (benchmark % of it), IPRS
    paid, % paid, variance % and variance. status: optional extra columns per item (exceptions, review …). Three
    heading rows; they and Internal No, Song name and ISRC are frozen. interest: the client interest %, if set."""
    ws = wb.create_sheet(title[:31]) if wb.worksheets and wb.active.max_row > 1 else wb.active
    ws.title = title[:31]
    bench = Decimal(benchmark).normalize() if benchmark is not None else None
    fills = {"IDENT": "D9D9D9", "PLATFORM": RG["SOURCE"][0], "CLIENT": RG["CLIENT"][0], "IPRS": RG["IPRS"][0],
             "CHECK": RG["CALC"][0], "STATUS": RG["STATUS"][0]}
    tints = {"PLATFORM": RG["SOURCE"][1], "CLIENT": RG["CLIENT"][1], "IPRS": RG["IPRS"][1], "CHECK": RG["CALC"][1],
             "STATUS": RG["STATUS"][1]}
    band_name = {"PLATFORM": platform.upper(), "CLIENT": f"CLIENT STATEMENT ({client_code})", "IPRS": "IPRS ROYALTY"}
    cols: list[dict] = []                                  # one per sheet column
    sections: list[tuple] = []                             # (kind, first col, last col)

    def add(kind, head, width, fmt=None, sub=None, value=None, total=None):
        cols.append(dict(kind=kind, head=head, width=width, fmt=fmt, sub=sub, value=value, total=total))

    add("IDENT", "Internal No", 13, value=lambda i: i["internal_work_number"])
    add("IDENT", "Song name", 36, value=lambda i: i["work_title"] or (i["isrcs"][0] if i["isrcs"] else None))
    add("IDENT", "ISRC", 30, value=lambda i: " | ".join(i["isrcs"]))
    sections.append(("IDENT", 1, 3))
    for side in ("PLATFORM", "CLIENT", "IPRS"):
        bs = [b for b in blocks if b["side"] == side]
        if not bs:
            continue
        a = len(cols) + 1
        for b in bs:
            k = b["key"]
            has = (lambda k: lambda i: bool(values.get(i["id"], {}).get(k)))(k)
            v = (lambda k: lambda i: values.get(i["id"], {}).get(k, {}))(k)
            add(side, "Amount", 14, xlsx.MONEY, value=(lambda v: lambda i: v(i).get("amount"))(v), total="sum")
            add(side, "Date", 12, xlsx.DATE, value=(lambda h, b: lambda i: b["date"] if h(i) else None)(has, b))
            add(side, "Period", 19, sub="Period", value=(lambda h, b: lambda i: b["period_label"] if h(i) else None)(has, b))
            add(side, "Period", 14, "#,##0", sub=f"Usage ({b['usage_label']})",
                value=(lambda v: lambda i: int(v(i)["usage"]) if v(i).get("usage") is not None else None)(v),
                total="sum")
            add(side, "Distribution No", 16, value=(lambda h, b: lambda i: b["reference"] if h(i) else None)(has, b),
                total=b["reference"])
        sections.append((side, a, len(cols)))
    a = len(cols) + 1
    share = Decimal(interest).normalize() if interest is not None else None
    add("CHECK", f"Revenue counted ({share} % client interest)" if share is not None else "Total revenue", 15,
        xlsx.MONEY, value=lambda i: i["eligible_revenue_basis"] if share is not None else i["sound_recording_revenue"],
        total="sum")
    add("CHECK", f"Expected value ({bench} % of revenue)" if bench is not None else "Expected value", 15, xlsx.MONEY,
        value=lambda i: i["reference_benchmark_amount"], total="sum")
    add("CHECK", "IPRS paid", 14, xlsx.MONEY, value=lambda i: i["iprs_royalty_amount"], total="sum")
    add("CHECK", "IPRS paid % of revenue", 11, "0.00", value=lambda i: Decimal(i["observed_percentage"]).quantize(
        Decimal("0.01")) if i["observed_percentage"] is not None else None)
    add("CHECK", "Variance %", 11, "0.00", value=variance_pct)
    add("CHECK", "Variance amount", 14, xlsx.MONEY, value=lambda i: i["indicative_variance"], total="sum")
    add("CHECK", "Result", 16, value=result_of)
    sections.append(("CHECK", a, len(cols)))
    if status:
        a = len(cols) + 1
        for head, (width, fn) in status.items():
            add("STATUS", head, width, value=fn)
        sections.append(("STATUS", a, len(cols)))
    # ---- headings: row 1 sections, row 2 columns ('Period' over two), row 3 the period's two parts
    for kind, a, z in sections:
        label = band_name.get(kind, {"IDENT": "", "CHECK": "CHECK - EXPECTED VS PAID", "STATUS": "STATUS"}.get(kind))
        excel.put(ws, 1, a, label, font=excel.BAND_F, al=excel.CTR)
        for k in range(a, z + 1):
            ws.cell(1, k).fill = excel.fill(fills[kind])
            ws.cell(1, k).border = Border(top=_MED, bottom=excel.THIN, left=_MED if k == a else None,
                                          right=_MED if k == z else None)
        if z > a:
            ws.merge_cells(start_row=1, start_column=a, end_row=1, end_column=z)
    c = 1
    while c <= len(cols):
        col = cols[c - 1]
        fl = excel.fill(fills[col["kind"]])
        brd = Border(left=excel.THIN, right=excel.THIN, top=excel.THIN, bottom=_MED)
        if col["sub"] is not None:                         # 'Period' with its two parts below
            excel.put(ws, 2, c, "Period", font=excel.BOLD, al=excel.WRAP)
            for k in (c, c + 1):
                ws.cell(2, k).fill = fl
                ws.cell(3, k).fill = fl
                excel.put(ws, 3, k, cols[k - 1]["sub"], font=excel.BOLD, al=excel.WRAP)
                ws.cell(3, k).border = brd
                ws.column_dimensions[get_column_letter(k)].width = cols[k - 1]["width"]
            ws.merge_cells(start_row=2, start_column=c, end_row=2, end_column=c + 1)
            c += 2
            continue
        excel.put(ws, 2, c, col["head"], font=excel.BOLD, al=excel.WRAP)
        ws.cell(2, c).fill = fl
        ws.cell(3, c).fill = fl
        ws.cell(3, c).border = brd
        ws.merge_cells(start_row=2, start_column=c, end_row=3, end_column=c)
        ws.column_dimensions[get_column_letter(c)].width = col["width"]
        c += 1
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 30
    ws.row_dimensions[3].height = 44
    # ---- one row per song, then the TOTAL row and the notes
    first = 4
    for n, i in enumerate(items):
        r = first + n
        for k, col in enumerate(cols, 1):
            v = col["value"](i)
            cell = _xcell(ws, r, k, v, "pct" if col["fmt"] == "0.00" else None)
            if col["fmt"] and v is not None:
                cell.number_format = col["fmt"]
            if col["kind"] in tints:
                cell.fill = excel.fill(tints[col["kind"]])
        ws.cell(r, 2).font = excel.BOLD
        for kind, a, z in sections:
            ws.cell(r, a).border = Border(left=_MED)
            ws.cell(r, z).border = Border(right=_MED)
    tr = first + len(items) + 1
    for k, col in enumerate(cols, 1):
        v = None
        if k == 2:
            v = f"TOTAL ({len(items):,} songs)"
        elif col["total"] == "sum":
            vals = [col["value"](i) for i in items]
            vals = [x for x in vals if isinstance(x, (int, Decimal)) and not isinstance(x, bool)]
            v = sum(vals, 0) if vals else None
        elif col["total"]:
            v = col["total"]
        cell = _xcell(ws, tr, k, v, None)
        if col["fmt"] and v is not None and not isinstance(v, str):
            cell.number_format = col["fmt"]
        cell.font = excel.BOLD
        cell.fill = excel.fill(fills[col["kind"]])
        cell.border = Border(top=_MED, bottom=_MED)
    if notes:
        excel.put(ws, tr + 2, 1, " ".join(notes), font=excel.NOTE_F, al=Alignment(vertical="top", wrap_text=True))
        ws.merge_cells(start_row=tr + 2, start_column=1, end_row=tr + 2, end_column=min(len(cols), 14))
        ws.row_dimensions[tr + 2].height = 75
    ws.freeze_panes = "D4"                                 # Internal No, Song name, ISRC and the headings stay in view
    ws.auto_filter.ref = f"A3:{get_column_letter(len(cols))}{max(first + len(items) - 1, 3)}"


def runs(actor: dict, client_id: int) -> list[dict]:
    with access.tx(actor, client_id) as conn:
        return db.all(conn, "SELECT r.id, r.run_reference, r.status, r.run_kind, r.usage_period_start, r.usage_period_end, "
                            "r.benchmark_percentage, r.client_interest_pct, r.summary, r.started_at, p.platform_name, "
                            "u.name AS started_by, (SELECT json_build_object('items', count(*), 'reviewed', count(*) "
                            "FILTER (WHERE i.review_status = 'REVIEWED'), 'needs_info', count(*) FILTER (WHERE "
                            "i.review_status = 'NEEDS_INFO')) FROM reconciliation_items i WHERE i.reconciliation_run_id "
                            "= r.id) AS review FROM reconciliation_runs r JOIN platforms p ON p.id = r.platform_id "
                            "LEFT JOIN app_user u ON u.id = r.started_by WHERE r.client_id = %s ORDER BY r.id DESC "
                            "LIMIT 50", (client_id,))


def run_view(actor: dict, run_id: int) -> dict:
    with access.tx(actor) as conn:
        r = db.one(conn, "SELECT r.*, p.platform_name, u.name AS started_by_name, c.code AS client_code, c.name AS "
                         "client_name FROM reconciliation_runs r JOIN platforms p ON p.id = r.platform_id JOIN client c "
                         "ON c.id = r.client_id LEFT JOIN app_user u ON u.id = r.started_by WHERE r.id = %s", (run_id,))
        if not r:
            raise ReconError("This reconciliation does not exist, or you do not have access to it.")
        # per exception type, in items: still to review (open exception, item not reviewed), reviewed, closed
        exc = db.all(conn, "SELECT e.exception_type, count(DISTINCT i.id) FILTER (WHERE e.status IN ('OPEN', 'IN_REVIEW') "
                           "AND i.review_status <> 'REVIEWED') AS todo, count(DISTINCT i.id) FILTER (WHERE e.status IN "
                           "('OPEN', 'IN_REVIEW') AND i.review_status = 'REVIEWED') AS reviewed, count(DISTINCT i.id) "
                           "FILTER (WHERE e.status NOT IN ('OPEN', 'IN_REVIEW')) AS closed, count(DISTINCT i.id) AS "
                           "items FROM reconciliation_exceptions e JOIN reconciliation_items i ON i.id = "
                           "e.reconciliation_item_id WHERE e.reconciliation_run_id = %s GROUP BY 1", (run_id,))
        later = _later(conn, r)
        hit = db.scalar(conn, "SELECT count(*) FROM reconciliation_items WHERE reconciliation_run_id = %s AND "
                              "internal_work_number = ANY(%s)", (run_id, sorted(later)))
        reviewed = db.one(conn, "SELECT count(*) FILTER (WHERE review_status = 'REVIEWED') AS reviewed, count(*) FILTER "
                                "(WHERE review_status = 'NEEDS_INFO') AS needs_info, count(*) AS items FROM "
                                "reconciliation_items WHERE reconciliation_run_id = %s", (run_id,))
        periods = period_columns(conn, run_id)
        blocks = run_blocks(conn, r)
    by_type = {e["exception_type"]: dict(open=e["todo"], reviewed=e["reviewed"], closed=e["closed"], items=e["items"])
               for e in exc}
    return dict(run=r, exceptions=[dict(type=k, label=EXC_LABEL[k], **v) for k, v in sorted(
        by_type.items(), key=lambda kv: -kv[1]["items"])], later_statements=dict(
        statements=sorted({(s["id"], s["filename"]) for v in later.values() for s in v}), items=hit),
                reviewed=reviewed, missing_text=MISSING_IPRS, periods=periods, blocks=blocks,
                labels=dict(exceptions=EXC_LABEL, calc=CALC_LABEL, kinds=KIND_LABEL, review=REVIEW_LABEL,
                            mapping=MAPPING_LABEL, run_kind=RUN_KIND_LABEL))


SORTS = {"revenue": "sound_recording_revenue DESC NULLS LAST", "variance": "indicative_variance DESC NULLS LAST",
         "iprs": "iprs_royalty_amount DESC NULLS LAST", "title": "lower(work_title)", "no": "item_no",
         "observed": "observed_percentage ASC NULLS LAST"}


def _item_filter(run_id: int, f: dict) -> tuple[str, dict]:
    where, p = ["i.reconciliation_run_id = %(r)s"], dict(r=run_id)
    if f.get("kind"):
        where.append("i.item_kind = %(k)s")
        p["k"] = f["kind"]
    if f.get("calc"):
        where.append("i.calculation_status = %(c)s")
        p["c"] = f["calc"]
    if f.get("mapping"):
        where.append("i.mapping_status = %(m)s")
        p["m"] = f["mapping"]
    if f.get("review"):
        where.append("i.review_status = %(rv)s")
        p["rv"] = f["review"]
    if f.get("exception"):
        where.append("EXISTS (SELECT 1 FROM reconciliation_exceptions e WHERE e.reconciliation_item_id = i.id AND "
                     "e.exception_type = %(e)s)")
        p["e"] = f["exception"]
    if f.get("open"):
        where.append("i.exception_status = 'OPEN'")
    if f.get("variance") == "positive":
        where.append("i.indicative_variance > 0")
    elif f.get("variance") == "underpaid":
        where.append("i.indicative_variance > 0.005")
    elif f.get("variance") == "client_diff":
        where.append("abs(i.client_iprs_difference) > 0.005")
    if f.get("q"):
        where.append("(i.work_title ILIKE %(q)s OR i.internal_work_number = %(qq)s OR %(qu)s = ANY(i.isrcs))")
        p.update(q=f"%{f['q'].strip()}%", qq=f["q"].strip(), qu=f["q"].strip().upper())
    return " AND ".join(where), p


def _enquiry_status(conn, client_id: int, keys: list[tuple]) -> dict:
    """(work_id, platform_id) -> the latest enquiry about it (any period overlapping)."""
    if not keys:
        return {}
    rows = db.all(conn, "SELECT ei.work_id, ei.platform_id, ei.usage_period_start, ei.usage_period_end, e.id, "
                        "e.enquiry_reference, e.status FROM enquiry_items ei JOIN enquiries e ON e.id = ei.enquiry_id "
                        "WHERE ei.client_id = %s AND ei.item_status <> 'REMOVED' AND ei.work_id = ANY(%s) "
                        "ORDER BY e.id", (client_id, sorted({k[0] for k in keys if k[0]})))
    out = {}
    for r in rows:
        out[(r["work_id"], r["platform_id"])] = r
    return out


def items(actor: dict, run_id: int, f: dict, offset: int = 0, limit: int = 100) -> dict:
    with access.tx(actor) as conn:
        run = db.one(conn, "SELECT * FROM reconciliation_runs WHERE id = %s", (run_id,))
        if not run:
            raise ReconError("This reconciliation does not exist.")
        sql, p = _item_filter(run_id, f)
        p.update(o=max(0, offset), n=max(1, min(500, limit)))
        rows = db.all(conn, f"SELECT i.*, coalesce((SELECT array_agg(DISTINCT e.exception_type) FROM "
                            f"reconciliation_exceptions e WHERE e.reconciliation_item_id = i.id AND e.status IN ('OPEN', "
                            f"'IN_REVIEW')), '{{}}') AS open_exceptions FROM reconciliation_items i WHERE {sql} "
                            f"ORDER BY {SORTS.get(f.get('sort') or 'no', 'item_no')}, i.item_no OFFSET %(o)s LIMIT %(n)s",
                      p)
        total = db.scalar(conn, f"SELECT count(*) FROM reconciliation_items i WHERE {sql}", p)
        later = _later(conn, run)
        enq = _enquiry_status(conn, run["client_id"], [(r["work_id"], r["platform_id"]) for r in rows])
        amounts = period_amounts(conn, [r["id"] for r in rows])
        bvals = block_values(conn, [r["id"] for r in rows], run_blocks(conn, run))
    for r in rows:
        r["periods"] = amounts.get(r["id"], dict(source={}, iprs={}))
        r["blocks"] = bvals.get(r["id"], {})
        r["variance_pct"] = variance_pct(r)
        r["later_statements"] = later.get(r["internal_work_number"] or "", [])
        e = enq.get((r["work_id"], r["platform_id"]))
        r["enquiry"] = dict(id=e["id"], reference=e["enquiry_reference"], status=e["status"]) if e else None
    return dict(rows=rows, total=total, offset=offset)


def why_not_query(it: dict) -> str | None:
    """Why an item cannot go into a query to IPRS (an enquiry), or None: a work in the catalogue that IPRS underpaid
    against the indicative reference, paid less than the client's statement shows, or did not list at all."""
    if it["item_kind"] != "WORK":
        return "only works in the catalogue can be enquired about (link or add the work first)"
    checks = it.get("data_validation_status") or ""
    if "NOT_COMPARABLE" in checks or "NO_IPRS_STATEMENT" in checks:
        return "the statements are not comparable for this period"
    if it["iprs_royalty_amount"] is None:
        if it["sound_recording_revenue"] is None and it.get("client_statement_amount") is None:
            return "there is no platform revenue or client statement for this work in the period"
        return None
    if it["indicative_variance"] is not None and it["indicative_variance"] > TOLERANCE:
        return None
    if it.get("client_iprs_difference") is not None and it["client_iprs_difference"] > TOLERANCE:
        return None
    return "IPRS paid at or above the indicative reference and the client's statement"


def item_ids(actor: dict, run_id: int, f: dict) -> dict:
    """Every item of a run that matches the filters (all pages), and those that can go into an enquiry - for 'tick all
    matching items'."""
    with access.tx(actor) as conn:
        run = db.one(conn, "SELECT * FROM reconciliation_runs WHERE id = %s", (run_id,))
        if not run:
            raise ReconError("This reconciliation does not exist.")
        sql, p = _item_filter(run_id, f)
        rows = db.all(conn, f"SELECT i.id, i.item_kind, i.work_id, i.platform_id, i.sound_recording_revenue, "
                            f"i.calculation_status, i.iprs_royalty_amount, i.indicative_variance, "
                            f"i.client_statement_amount, i.client_iprs_difference, i.data_validation_status FROM "
                            f"reconciliation_items i WHERE {sql} ORDER BY i.item_no", p)
        enq = _enquiry_status(conn, run["client_id"], [(r["work_id"], r["platform_id"]) for r in rows])
    elig = [r["id"] for r in rows if why_not_query(r) is None and (r["work_id"], r["platform_id"]) not in enq]
    return dict(ids=[r["id"] for r in rows], eligible=elig, total=len(rows))


def item_detail(actor: dict, item_id: int) -> dict:
    with access.tx(actor) as conn:
        it = db.one(conn, "SELECT * FROM reconciliation_items WHERE id = %s", (item_id,))
        if not it:
            raise ReconError("This reconciliation item does not exist.")
        run = db.one(conn, "SELECT * FROM reconciliation_runs WHERE id = %s", (it["reconciliation_run_id"],))
        srcs = db.all(conn, "SELECT s.*, st.original_filename, st.statement_reference FROM reconciliation_sources s JOIN "
                            "statements st ON st.id = s.statement_id WHERE s.reconciliation_item_id = %s ORDER BY "
                            "s.source_type, s.usage_month, s.isrc, s.statement_id, s.line_no", (item_id,))
        exc = db.all(conn, "SELECT e.*, a.name AS assigned_to_name, r.name AS reviewed_by_name FROM "
                           "reconciliation_exceptions e LEFT JOIN app_user a ON a.id = e.assigned_to LEFT JOIN app_user "
                           "r ON r.id = e.reviewed_by WHERE e.reconciliation_item_id = %s ORDER BY e.id", (item_id,))
        later = _later(conn, run).get(it["internal_work_number"] or "", [])
        enq = db.all(conn, "SELECT e.id, e.enquiry_reference, e.status, ei.item_status FROM enquiry_items ei JOIN "
                           "enquiries e ON e.id = ei.enquiry_id WHERE ei.reconciliation_item_id = %s OR (ei.work_id = %s "
                           "AND ei.platform_id = %s AND ei.item_status <> 'REMOVED') ORDER BY e.id",
                     (item_id, it["work_id"], it["platform_id"]))
        reviewer = db.scalar(conn, "SELECT name FROM app_user WHERE id = %s", (it["reviewed_by"],))
    for e in exc:
        e["label"] = EXC_LABEL[e["exception_type"]]
    by_isrc: dict = defaultdict(lambda: dict(lines=0, amount=ZERO, blank=0, plays=None))
    for s in srcs:
        if s["source_type"] in REVENUE_TYPES:
            g = by_isrc[s["isrc"] or ""]
            g["lines"] += 1
            if s["contribution_amount"] is None:
                g["blank"] += 1
            else:
                g["amount"] += s["contribution_amount"]
        elif s["source_type"] == "PLATFORM_USAGE" and s["contribution_amount"] is not None:
            g = by_isrc[s["isrc"] or ""]
            g["plays"] = (g["plays"] or ZERO) + s["contribution_amount"]
    return dict(item=dict(it, reviewed_by_name=reviewer), run=dict(id=run["id"], reference=run["run_reference"]),
                sources=srcs, exceptions=exc, later_statements=later, enquiries=enq,
                isrc_breakdown=[dict(isrc=k, **v) for k, v in sorted(by_isrc.items())], missing_text=MISSING_IPRS)


def review_item(actor: dict, item_id: int, status: str, note: str | None) -> dict:
    access.require(actor, "prepare")
    if status not in REVIEW_LABEL:
        raise ReconError("Unknown review status.")
    with access.tx(actor) as conn:
        it = db.one(conn, "SELECT * FROM reconciliation_items WHERE id = %s", (item_id,))
        if not it:
            raise ReconError("This reconciliation item does not exist.")
        conn.execute("UPDATE reconciliation_items SET review_status = %s, reviewed_by = %s, reviewed_at = now(), "
                     "review_note = %s, updated_at = now() WHERE id = %s",
                     (status, actor["id"], (note or "").strip() or None, item_id))
        audit.record(conn, "recon.item_reviewed", actor, "reconciliation_items", item_id, dict(note=note),
                     before=dict(review_status=it["review_status"]), after=dict(review_status=status))
    return item_detail(actor, item_id)


def review_items(actor: dict, run_id: int, item_ids: list, status: str, note: str | None) -> dict:
    """Review several items of one run at once: reviewed, needs information, or back to not reviewed. One activity-log
    event records which items moved from which status; the calculated values never change."""
    access.require(actor, "prepare")
    if status not in REVIEW_LABEL:
        raise ReconError("Unknown review status.")
    try:
        ids = sorted({int(x) for x in item_ids or []})
    except (TypeError, ValueError):
        raise ReconError("Choose the items to review.") from None
    if not ids:
        raise ReconError("Tick at least one item.")
    if len(ids) > 50000:
        raise ReconError("Choose at most 50,000 items at a time.")
    note = (note or "").strip() or None
    with access.tx(actor) as conn:
        rows = db.all(conn, "SELECT id, review_status FROM reconciliation_items WHERE reconciliation_run_id = %s AND id = "
                            "ANY(%s)", (run_id, ids))
        if len(rows) != len(ids):
            raise ReconError("Some of the ticked items are not in this reconciliation. Refresh the page and try again.")
        if status == "UNREVIEWED":
            conn.execute("UPDATE reconciliation_items SET review_status = 'UNREVIEWED', reviewed_by = NULL, reviewed_at = "
                         "NULL, review_note = %s, updated_at = now() WHERE id = ANY(%s)", (note, ids))
        else:
            conn.execute("UPDATE reconciliation_items SET review_status = %s, reviewed_by = %s, reviewed_at = now(), "
                         "review_note = %s, updated_at = now() WHERE id = ANY(%s)", (status, actor["id"], note, ids))
        before: dict = defaultdict(int)
        for r in rows:
            before[r["review_status"]] += 1
        audit.record(conn, "recon.items_reviewed", actor, "reconciliation_runs", run_id,
                     dict(items=len(ids), item_ids=ids[:200], note=note), before=dict(before),
                     after=dict(review_status=status))
    return dict(updated=len(ids), status=status, label=REVIEW_LABEL[status])


def mark_addressed(actor: dict, item_id: int, body: dict) -> dict:
    """A later statement, payment or adjustment already addressed this item: record the verified evidence, close its
    open exceptions with that note and mark the item reviewed. Nothing is changed in the calculated values."""
    access.require(actor, "prepare")
    kind = body.get("kind") if body.get("kind") in ("LATER_STATEMENT", "PAYMENT", "ADJUSTMENT") else "LATER_STATEMENT"
    note = (body.get("note") or "").strip()
    if not note:
        raise ReconError("Please describe the evidence (statement, distribution, payment reference, amount).")
    amount = body.get("amount")
    if amount not in (None, ""):
        if plain_number(amount, commas=True) is None:
            raise ReconError("The amount must be a number, for example 1250 or 1250.50.")
        amount = str(plain_number(amount, commas=True))
    else:
        amount = None
    if body.get("statement_id") and not str(body["statement_id"]).strip().isdigit():
        raise ReconError("The statement number must be a number, as shown under Statements.")
    sid = int(body["statement_id"]) if body.get("statement_id") else None
    label = {"LATER_STATEMENT": "a later statement", "PAYMENT": "a payment", "ADJUSTMENT": "an adjustment"}[kind]
    text = f"Addressed by {label}" + (f" (statement #{sid})" if sid else "") + (f", amount {amount}" if amount else "") \
        + f": {note}"
    with access.tx(actor) as conn:
        it = db.one(conn, "SELECT * FROM reconciliation_items WHERE id = %s", (item_id,))
        if not it:
            raise ReconError("This reconciliation item does not exist.")
        if sid and not db.scalar(conn, "SELECT id FROM statements WHERE id = %s AND client_id = %s",
                                 (sid, it["client_id"])):
            raise ReconError("That statement does not exist.")
        conn.execute("UPDATE reconciliation_exceptions SET status = 'RESOLVED', reviewed_by = %s, reviewed_at = now(), "
                     "resolution_note = %s, updated_at = now() WHERE reconciliation_item_id = %s AND status IN "
                     "('OPEN', 'IN_REVIEW')", (actor["id"], text, item_id))
        conn.execute("UPDATE reconciliation_items SET review_status = 'REVIEWED', reviewed_by = %s, reviewed_at = now(), "
                     "review_note = %s, exception_status = CASE WHEN exception_status = 'OPEN' THEN 'RESOLVED' ELSE "
                     "exception_status END, later_statement_status = CASE WHEN later_statement_status = "
                     "'REVIEW_REQUIRED' THEN 'REVIEWED' ELSE later_statement_status END, updated_at = now() WHERE id = %s",
                     (actor["id"], text, item_id))
        audit.record(conn, "recon.item_addressed", actor, "reconciliation_items", item_id,
                     dict(kind=kind, statement_id=sid, amount=amount, note=note))
    return item_detail(actor, item_id)


def update_exception(actor: dict, exception_id: int, body: dict) -> dict:
    """Review an exception. Resolving or dismissing needs a note; assigning it to someone is for Admins."""
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        e = db.one(conn, "SELECT * FROM reconciliation_exceptions WHERE id = %s", (exception_id,))
        if not e:
            raise ReconError("This exception does not exist.")
        vals = {}
        status = body.get("status")
        if status:
            if status not in ("OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED"):
                raise ReconError("Unknown status.")
            note = (body.get("note") or "").strip()
            if status in ("RESOLVED", "DISMISSED") and not note:
                raise ReconError("Please say how this was resolved, or why it is dismissed.")
            vals.update(status=status, reviewed_by=actor["id"], reviewed_at=dt.datetime.now(dt.timezone.utc),
                        resolution_note=note or e["resolution_note"])
        if "assigned_to" in body:
            access.require(actor, "assign_followups")
            vals["assigned_to"] = int(body["assigned_to"]) if body.get("assigned_to") else None
        if vals:
            db.update(conn, "reconciliation_exceptions", exception_id, vals)
            conn.execute("UPDATE reconciliation_exceptions SET updated_at = now() WHERE id = %s", (exception_id,))
            still = db.scalar(conn, "SELECT count(*) FROM reconciliation_exceptions WHERE reconciliation_item_id = %s "
                                    "AND status IN ('OPEN', 'IN_REVIEW')", (e["reconciliation_item_id"],))
            conn.execute("UPDATE reconciliation_items SET exception_status = %s, updated_at = now() WHERE id = %s",
                         ("OPEN" if still else "RESOLVED", e["reconciliation_item_id"]))
            audit.record(conn, "recon.exception_updated", actor, "reconciliation_exceptions", exception_id,
                         dict(type=e["exception_type"]),
                         before=dict(status=e["status"], assigned_to=e["assigned_to"]),
                         after={k: v for k, v in vals.items() if k in ("status", "assigned_to", "resolution_note")})
    return item_detail(actor, e["reconciliation_item_id"])


# ================================================================== the reconciliation report (Excel)
def _pct(v):
    return None if v is None else Decimal(v)


def _cnt(v):
    return None if v is None else int(v)


def _isrc_rows(by_id: dict, srcs: list[dict]) -> list[list]:
    agg: dict = {}
    for x in srcs:
        if x["source_type"] not in REVENUE_TYPES + ("PLATFORM_USAGE",):
            continue
        k = (x["reconciliation_item_id"], x["isrc"] or "")
        g = agg.setdefault(k, [0, 0, None, None])
        if x["source_type"] == "PLATFORM_USAGE":
            if x["contribution_amount"] is not None:
                g[3] = (g[3] or ZERO) + x["contribution_amount"]
            continue
        g[0] += 1
        if x["contribution_amount"] is None:
            g[1] += 1
        else:
            g[2] = (g[2] or ZERO) + x["contribution_amount"]
    rows = []
    for (iid, isrc), (n, blank, amt, plays) in sorted(agg.items(), key=lambda kv: (by_id[kv[0][0]]["item_no"],
                                                                                    kv[0][1])):
        i = by_id[iid]
        rows.append([i["item_no"], i["internal_work_number"], i["work_title"], isrc or "no ISRC", n, blank, amt, plays])
    return rows


SOURCE_TYPE_LABEL = {"CLIENT_REVENUE": "Revenue", "PLATFORM_REVENUE": "Platform revenue",
                     "PLATFORM_USAGE": "Platform usage (plays)", "CLIENT_STATEMENT": "Client statement",
                     "IPRS_ROYALTY": "IPRS paid"}


# report bands: (header fill, row tint) - the master's look, in the application's colours
RG = {"IDENT": ("D9D9D9", None), "SOURCE": ("D8E9A8", "F4F9E6"), "USAGE": ("D6E4DA", "F1F6F2"),
      "CLIENT": ("E8DDC8", "FAF6EE"), "IPRS": ("CFDCCB", "EFF4EE"),
      "CALC": ("E6E1D3", "F8F6F0"), "YOY": ("D3E0E6", "EEF3F6"), "STATUS": ("DCD6CC", "F6F4F0")}
_MED = excel.MED


def _xcell(ws, r: int, c: int, v, kind: str | None):
    if kind == "count" and isinstance(v, (int, Decimal)) and not isinstance(v, bool):
        cell = ws.cell(r, c, int(v))
        cell.number_format = "#,##0"
        return cell
    if isinstance(v, Decimal):
        cell = ws.cell(r, c, v)                  # exact value; the format rounds only what is shown
        cell.number_format = xlsx.PCT if kind == "pct" else xlsx.MONEY
        return cell
    if isinstance(v, (dt.date, dt.datetime)):
        cell = ws.cell(r, c, v)
        cell.number_format = xlsx.DATE
        return cell
    if isinstance(v, (list, tuple)):
        v = " | ".join(str(x) for x in v if x not in (None, ""))
    return excel.put(ws, r, c, v)


def _master_sheet(wb: Workbook, title: str, groups: list[dict], rows: list[list], totals: list, note: str) -> None:
    """The reconciliation laid out like the master workbook: row 1 the bands (platform, source revenue, IPRS royalty,
    calculation …), row 2 the headers, the song title frozen, one row per item, a TOTAL row and the notes under it."""
    ws = wb.active
    ws.title = title
    c, spans = 1, []
    for g in groups:
        a = c
        for j, (h, w, _k) in enumerate(g["cols"]):
            excel._head(ws, c, h, g["fill"], w, sep=(j == len(g["cols"]) - 1))
            c += 1
        spans.append((g, a, c - 1))
        excel._band_header(ws, a, c - 1, g["label"], g["fill"])
    end = c - 1
    kinds = [k for g in groups for (_h, _w, k) in g["cols"]]
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 46
    for n, row in enumerate(rows):
        rr = 3 + n
        for col, v in enumerate(row, 1):
            _xcell(ws, rr, col, v, kinds[col - 1])
        ws.cell(rr, 1).font = excel.BOLD
        for g, a, z in spans:
            for k in range(a, z + 1):
                if g["tint"]:
                    ws.cell(rr, k).fill = excel.fill(g["tint"])
                elif rr % 2 == 1:
                    ws.cell(rr, k).fill = excel.fill(excel.GREY_R)
            ws.cell(rr, a).border = Border(left=_MED)
            ws.cell(rr, z).border = Border(right=_MED)
    last = 2 + len(rows)
    tr = last + 2
    for g, a, z in spans:
        for k in range(a, z + 1):
            cell = _xcell(ws, tr, k, totals[k - 1], kinds[k - 1])
            cell.font = excel.BOLD
            cell.fill = excel.fill(g["fill"])
            cell.border = Border(top=_MED, bottom=_MED, left=_MED if k == a else None, right=_MED if k == z else None)
    excel.put(ws, tr + 2, 1, note, font=excel.NOTE_F, al=Alignment(vertical="top", wrap_text=True))
    ws.merge_cells(start_row=tr + 2, start_column=1, end_row=tr + 2, end_column=min(end, 14))
    ws.row_dimensions[tr + 2].height = 90
    ws.freeze_panes = "B3"                        # the song title and the two header rows stay in view
    ws.auto_filter.ref = f"A2:{get_column_letter(end)}{max(last, 2)}"


def report(actor: dict, run_id: int, f: dict) -> tuple[str, bytes]:
    with access.tx(actor) as conn:
        r = db.one(conn, "SELECT r.*, p.platform_name, c.code, c.name AS client_name, c.kind AS client_kind, "
                         "u.name AS started_by_name FROM "
                         "reconciliation_runs r JOIN platforms p ON p.id = r.platform_id JOIN client c ON c.id = "
                         "r.client_id LEFT JOIN app_user u ON u.id = r.started_by WHERE r.id = %s", (run_id,))
        if not r:
            raise ReconError("This reconciliation does not exist.")
        sql, p = _item_filter(run_id, f)
        its = db.all(conn, f"SELECT i.* FROM reconciliation_items i WHERE {sql} ORDER BY i.item_no", p)
        ids = [i["id"] for i in its]
        excs = db.all(conn, "SELECT * FROM reconciliation_exceptions WHERE reconciliation_item_id = ANY(%s) ORDER BY "
                            "reconciliation_item_id, id", (ids,))
        srcs = db.all(conn, "SELECT s.*, st.original_filename, st.statement_reference FROM reconciliation_sources s "
                            "JOIN statements st ON st.id = s.statement_id WHERE s.reconciliation_item_id = ANY(%s) "
                            "ORDER BY s.reconciliation_item_id, s.source_type, s.statement_id, s.line_no", (ids,))
        later = _later(conn, r)
        enq = _enquiry_status(conn, r["client_id"], [(i["work_id"], i["platform_id"]) for i in its])
        people = {x["id"]: x["name"] for x in db.all(conn, "SELECT id, name FROM app_user")}
        audit.record(conn, "export.reconciliation_report", actor, "reconciliation_runs", run_id,
                     dict(reference=r["run_reference"], items=len(its), filters={k: v for k, v in f.items() if v}))
    by_id = {i["id"]: i for i in its}
    ex_by: dict = defaultdict(list)
    for e in excs:
        ex_by[e["reconciliation_item_id"]].append(e)
    src_by: dict = defaultdict(list)
    for s in srcs:
        src_by[s["reconciliation_item_id"]].append(s)
    yearly = r["run_kind"] == "YEAR"
    period = _fy_label(r["usage_period_start"]) if yearly else _label(r["usage_period_start"], r["usage_period_end"])
    prev_label = _label(r["previous_period_start"], r["previous_period_end"]) if r["previous_period_start"] else None

    def change(cur, old):
        return None if cur is None or not old else (cur - old) / old * HUNDRED

    kinds = {"PUBLISHER": "publisher", "LABEL": "label", "PUBLISHER_AND_LABEL": "publisher and label"}

    def refs(i):
        ss = src_by[i["id"]]
        stm = sorted({f"#{s['statement_id']} {s['statement_reference'] or s['original_filename']}" for s in ss})
        rows = defaultdict(list)
        for s in ss:
            rows[s["statement_id"]].append(s["source_row_number"])
        rr = "; ".join(f"#{k}: rows " + ", ".join(str(x) for x in sorted(v)[:25]) + (f" (+{len(v) - 25} more)"
                                                                                      if len(v) > 25 else "")
                       for k, v in sorted(rows.items()))
        return "; ".join(stm), rr

    with access.tx(actor) as conn:
        blocks = run_blocks(conn, r)
        bvals = block_values(conn, ids, blocks)
    head = [f"{r['client_name']} - {r['platform_name']} reconciliation {r['run_reference']} ({period})",
            f"Run by {r['started_by_name']} on {r['started_at']:%d %b %Y %H:%M}. Reference benchmark "
            f"{r['benchmark_percentage'].normalize()} %; client interest "
            + (f"{r['client_interest_pct'].normalize()} %" if r["client_interest_pct"] else "not established")
            + f"; revenue basis {r['revenue_basis'].lower()}.",
            "Per statement: Amount, Date, Period (the period and the plays the platform reported for the song in it) and "
            "Distribution number. Expected = the reference benchmark of the revenue; Variance = expected - IPRS paid "
            "(positive: underpaid); Variance % = variance / expected. Indicative only, not amounts payable by IPRS. An "
            "empty cell means no record - never zero."]
    if any(v for v in f.values()):
        head.append("Filters: " + ", ".join(f"{k} = {v}" for k, v in f.items() if v))
    plat = r["platform_name"]

    def later_text(i):
        lt = later.get(i["internal_work_number"] or "", [])
        return ("Review required: " + ", ".join(f"#{x['id']} {x['reference'] or x['filename']}" for x in lt)) if lt \
            else None

    def enq_text(i):
        e = enq.get((i["work_id"], i["platform_id"]))
        return f"{e['enquiry_reference']} ({e['status'].replace('_', ' ').lower()})" if e else None
    status_cols = {
        "Exceptions": (30, lambda i: "; ".join(sorted({EXC_LABEL[x["exception_type"]] for x in ex_by[i["id"]]})) or None),
        "Catalogue link": (13, lambda i: MAPPING_LABEL.get(i["mapping_status"], i["mapping_status"])),
        "Recommended next action": (50, lambda i: i["recommended_action"]),
        "Query to IPRS": (20, enq_text), "Later statement": (24, later_text),
        "Review status": (14, lambda i: REVIEW_LABEL[i["review_status"]]),
        "Reviewed by": (16, lambda i: people.get(i["reviewed_by"])), "Review note": (30, lambda i: i["review_note"]),
        "Source rows": (50, lambda i: refs(i)[1] or None)}
    if yearly:
        status_cols = {f"Revenue, year before ({prev_label or 'no statements'})": (16, lambda i: i["previous_revenue"]),
                       "Revenue change %": (10, lambda i: _q2(change(i["sound_recording_revenue"], i["previous_revenue"]))),
                       "IPRS paid, year before": (16, lambda i: i["previous_iprs_royalty"]),
                       "IPRS paid change %": (10, lambda i: _q2(change(i["iprs_royalty_amount"],
                                                                       i["previous_iprs_royalty"])))} | status_cols
    s = r["summary"] or {}
    summary_rows = [["Client", f"{r['client_name']} ({kinds.get(r['client_kind'], r['client_kind'])})"],
                    ["Reference", r["run_reference"]], ["Platform", r["platform_name"]],
                    ["Compares", RUN_KIND_LABEL[r["run_kind"]]], ["Usage period", period],
                    ["Months compared", _months_text([_date(m) for m in (r["compared_months"] or [])])],
                    ["Year before (same months)", prev_label or "Not part of this run"],
                    ["Territory", next((i["territory"] for i in its if i["territory"]), None) or "Not stated"],
                    ["Currency", (r["summary"] or {}).get("currency") or "Not established"],
                    ["Reference benchmark %", Decimal(r["benchmark_percentage"])],
                    ["Client interest %", Decimal(r["client_interest_pct"]) if r["client_interest_pct"] else
                     "Not established"],
                    ["Revenue basis", r["revenue_basis"].title()], ["Items", s.get("items")],
                    ["Works compared", s.get("compared")], ["Works with no corresponding IPRS entry",
                                                            s.get("missing_iprs")],
                    ["Unmatched recordings", s.get("unmatched_recordings")],
                    ["IPRS works not in catalogue", s.get("unmatched_works")],
                    ["[Source] Revenue linked to works", Decimal(s["revenue_matched"]) if s.get("revenue_matched")
                     else None],
                    ["[Source] Revenue not linked to a work", Decimal(s["revenue_unmatched"])
                     if s.get("revenue_unmatched") else None],
                    ["[Source] IPRS royalty on catalogue works", Decimal(s["iprs_matched"]) if s.get("iprs_matched")
                     else None],
                    ["[Source] IPRS royalty on works not in catalogue", Decimal(s["iprs_unmatched"])
                     if s.get("iprs_unmatched") else None],
                    ["[Calculated] Expected - indicative reference (calculated items)", Decimal(s["reference"])
                     if s.get("reference") else None],
                    ["Works underpaid by IPRS", s.get("underpaid")],
                    ["[Calculated] Total shortfall of the underpaid works", Decimal(s["shortfall"])
                     if s.get("shortfall") else None],
                    ["[Source] Usage (plays) on catalogue works", Decimal(s["usage"]) if s.get("usage") else None],
                    ["[Source] Client statements on catalogue works", Decimal(s["client_matched"])
                     if s.get("client_matched") else None],
                    ["Works where the client statement and IPRS differ", s.get("client_differences")],
                    ["Source snapshot sha256", r["source_snapshot_sha256"]]]
    summary_rows += [["Note", n] for n in r["notes"]]
    snap = r["source_snapshot"]
    first = (("platform_reports", "Platform report"), ("client_statements", "Client statement")) \
        if "platform_reports" in snap else (("revenue_statements", "Client statement"),)
    for key, what in first + (("iprs_statements", "IPRS statement"),
                      ("previous_revenue_statements", "Revenue statement, year before"),
                      ("previous_iprs_statements", "IPRS statement, year before")):
        summary_rows += [[what, f"#{x['id']} {x['file']} (sha256 {x['sha256'][:12]}…)"]
                         for x in r["source_snapshot"].get(key, [])]
    wb = Workbook()
    block_sheet(wb, "Reconciliation", platform=plat, client_code=r["code"], benchmark=r["benchmark_percentage"],
                blocks=blocks, items=its, values=bvals, notes=head, status=status_cols,
                interest=r["client_interest_pct"])
    other = [
        dict(title="Summary", heading=head, columns=[("", 44, None), ("", 90, None)], rows=summary_rows),
        dict(title="Exceptions", heading=head, columns=[("Item", 6, None), ("Work number", 12, None),
                                                        ("Title / ISRC", 34, None), ("Exception", 24, None),
                                                        ("Severity", 9, None), ("Description", 90, None),
                                                        ("Status", 10, None), ("Resolution note", 40, None)],
             rows=[[by_id[e["reconciliation_item_id"]]["item_no"],
                    by_id[e["reconciliation_item_id"]]["internal_work_number"],
                    by_id[e["reconciliation_item_id"]]["work_title"] or ", ".join(by_id[e["reconciliation_item_id"]][
                        "isrcs"]),
                    EXC_LABEL[e["exception_type"]], e["severity"].title(), e["description"], e["status"].title(),
                    e["resolution_note"]] for e in excs]),
        dict(title="ISRC detail", heading=[head[0], "Revenue of each linked ISRC, per work (the IPRS "
                                                    "royalty is counted once per work, never per ISRC)."],
             columns=[("Item", 6, None), ("Work number", 12, None), ("Song title", 34, None), ("ISRC", 16, None),
                      ("Revenue lines", 9, None), ("Blank amounts", 9, None), ("[Source] Revenue", 15, "money"),
                      ("[Source] Plays", 13, None)],
             rows=_isrc_rows(by_id, srcs)),
        dict(title="Source lines", heading=[head[0], "Every statement line behind every item (statement and sheet row "
                                                     "as received)."],
             columns=[("Item", 6, None), ("Type", 14, None), ("Statement", 10, None), ("Source file", 40, None),
                      ("Source row", 9, None), ("ISRC", 16, None), ("Work number", 12, None), ("Usage month", 12, "date"),
                      ("[Source] Amount (plays for usage)", 14, None)],
             rows=[[by_id[s["reconciliation_item_id"]]["item_no"], SOURCE_TYPE_LABEL[s["source_type"]],
                    s["statement_id"], s["original_filename"], s["source_row_number"], s["isrc"],
                    s["internal_work_number"], s["usage_month"], s["contribution_amount"]] for s in srcs])]
    for sh in other:
        xlsx.sheet(wb, sh["title"], sh["columns"], sh["rows"], sh.get("heading"))
    data = excel.stable(wb)
    span = f"FY{r['usage_period_start'].year}-{str(r['usage_period_start'].year + 1)[2:]}" if yearly else \
        f"{r['usage_period_start']:%Y-%m}_to_{r['usage_period_end']:%Y-%m}"
    name = f"{r['code']}_Reconciliation_{xlsx.safe_name(r['platform_name'])}_{span}_{r['run_reference']}.xlsx"
    return name, data

