"""What is this file, and can it be used?

identify(): reads the bytes once, decides the kind from the content (never from the name alone) and extracts the data
            plus a JSON-safe 'facts' summary.
evaluate(): applies the client's settings and the user's answers to the facts and returns the metadata (with the
            source of every value), the problems in plain language and the file status. It never re-reads the file,
            so answering a question is instant.

Kind detection order (V3 §2.4): our own '_rd_meta' sheet -> SKV layout -> IPRS 'WORK INT NO' header ->
ISRC + month + revenue -> ISRC + month + plays -> title + work number / ISRC -> unknown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter
from decimal import Decimal

from ..normalize import s
from ..parsing import reader, safety
from . import names, parsers
from .model import (KIND_LABEL, PLATFORM_REVENUE, PLATFORM_USAGE, PREVIOUS_OUTPUT, REVIEW_LIST, SONG_LIST, STATEMENT,
                    UNKNOWN, Parsed, PlatformData, PriorOutputData, Problem, SongListData, StatementData)
from .rules import STATUS_LABEL, map_status

ZERO = Decimal("0")
READY, NEEDS_REVIEW, UNSUPPORTED, ERROR, LEFT_OUT = "READY", "NEEDS_REVIEW", "UNSUPPORTED", "ERROR", "LEFT_OUT"
STATUS_TEXT = {READY: "Ready", NEEDS_REVIEW: "Needs review", UNSUPPORTED: "Unsupported", ERROR: "Error",
               LEFT_OUT: "Not included"}
CATEGORIES = ["YouTube Pre-Claims", "YouTube Post-Claims", "Facebook / Meta", "Spotify", "Apple Music", "Radio",
              "Zee TV Broadcast", "Mechanical (MUSERK)", "Mechanical", "Other / Unclassified", "Redistribution",
              "Overseas"]


def money(v) -> str:
    """₹ 1,23,456.78 style (Indian grouping) for messages."""
    d = names.q2(Decimal(v))
    neg = d < 0
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}₹{whole}.{frac}"


# ================================================================== identify
def identify(filename: str, data: bytes, forced_kind: str | None = None) -> Parsed:
    rep = safety.Report()
    try:
        safety.check_bytes(data, filename, rep)
        sheets = reader.parse(data, rep)
    except safety.Rejected as e:
        return Parsed(kind=UNKNOWN, layout="REJECTED", confidence="HIGH", why=str(e), data=None,
                      problems=[Problem("UNREADABLE", "ERROR", _rejected_message(str(e)), str(e))])
    except Exception as e:                                       # noqa: BLE001 - shown in 'More details'
        return Parsed(kind=UNKNOWN, layout="DAMAGED", confidence="HIGH", why="unreadable", data=None,
                      problems=[Problem("UNREADABLE", "ERROR", "We could not open this file. It may be damaged or "
                                        "password-protected. Please save it again as an Excel (.xlsx) file and "
                                        "upload it again.", f"{type(e).__name__}: {e}")])
    file_date = reader.zip_date(data) if rep.kind == "xlsx" else None
    p = _identify_sheets(sheets, filename, forced_kind)
    p.summary["file_date"] = file_date.isoformat() if file_date else None
    p.summary["sheets"] = [sh["title"] for sh in sheets]
    return p


def _rejected_message(msg: str) -> str:
    low = msg.lower()
    if "macro" in low or "active-content" in low:
        return "This workbook contains macros or embedded content, which we do not accept for safety. Save it as " \
               "a plain Excel workbook (.xlsx) and upload it again."
    if "size" in low or "limit" in low or "cells" in low:
        return "This file is too large to process. Please split it or contact your administrator."
    return "This is not a file type we can read. Please upload Excel (.xlsx) or CSV files."


def _identify_sheets(sheets: list[dict], filename: str, forced: str | None) -> Parsed:
    visible = [sh for sh in sheets if sh.get("state", "visible") == "visible"] or sheets
    meta_sheet = next((sh for sh in sheets if sh["title"] == "_rd_meta"), None)
    if forced in (None, PREVIOUS_OUTPUT):
        for sh in visible:
            if parsers.looks_like_skv(sh["rows"]):
                gen = sh["title"] if not sh["title"].lower().startswith("sheet") else names.stem(filename)
                data = parsers.parse_skv(sh["rows"], sh["title"], gen)
                if meta_sheet:
                    data.native = True
                    data.meta = _read_meta(meta_sheet["rows"])
                why = "previous master report (row 1 section bands, row 2 'ISRC · Song Name · Internal No · " \
                      "Total Amount')" + (" with its _rd_meta sheet" if meta_sheet else "")
                return _wrap(PREVIOUS_OUTPUT, "SKV_NATIVE" if meta_sheet else "SKV_LEGACY", why, data)
    if forced in (None, REVIEW_LIST, SONG_LIST):
        for sh in visible:
            if parsers.looks_like_companion(sh["rows"]):
                m = parsers.map_header(sh["rows"][1])
                m.update(month=None, revenue=None, usage=None)
                data = parsers.parse_song_list(sh["rows"], sh["title"], 1, m)
                return _wrap(data.kind, "COMPANION", "a Missing Songs / out-of-scope report produced here"
                             + (", with review statuses" if data.kind == REVIEW_LIST else ""), data)
    if forced in (None, STATEMENT):
        for sh in visible:
            if parsers.statement_header(sh["rows"]) is not None:
                data = parsers.parse_statement(sh["rows"], sh["title"])
                return _wrap(STATEMENT, data.layout, "IPRS statement layout ('WORK INT NO' … 'ROYALTY AMT')", data)
        if forced == STATEMENT:
            return Parsed(kind=UNKNOWN, layout="", confidence="HIGH", why="no statement header", data=None,
                          problems=[Problem("NOT_A_STATEMENT", "ERROR", "This file does not look like a royalty "
                                            "statement we can read: it has no 'WORK INT NO' heading row.")])
    for sh in visible:
        found = parsers.find_table(sh["rows"])
        if not found:
            continue
        h, m = found
        kind = parsers.table_kind(m)
        if forced in (PLATFORM_REVENUE, PLATFORM_USAGE, SONG_LIST, REVIEW_LIST):
            kind = forced if _compatible(forced, m) else None
        if kind in (PLATFORM_REVENUE, PLATFORM_USAGE):
            data = parsers.parse_platform(sh["rows"], sh["title"], h, m, kind)
            return _wrap(kind, "TABLE", f"columns {', '.join(_cols(m))}", data)
        if kind in (SONG_LIST, REVIEW_LIST):
            data = parsers.parse_song_list(sh["rows"], sh["title"], h, m)
            if forced == REVIEW_LIST and data.kind != REVIEW_LIST:
                continue
            return _wrap(data.kind, "TABLE", f"columns {', '.join(_cols(m))}"
                         + (" and a review status column" if data.kind == REVIEW_LIST else ""), data)
    return Parsed(kind=UNKNOWN, layout="", confidence="LOW", why="no recognised layout", data=None,
                  problems=[Problem("UNKNOWN_KIND", "REVIEW", "We couldn't identify this file's format. What type "
                                    "of file is it?", "no statement header, previous-report layout or identifier "
                                    "columns were found", field="kind")])


def _compatible(kind: str, m: dict) -> bool:
    if kind == PLATFORM_REVENUE:
        return m["isrc"] is not None and m["revenue"] is not None
    if kind == PLATFORM_USAGE:
        return m["isrc"] is not None and m["usage"] is not None
    return m["title"] is not None or m["isrc"] is not None or m["work"] is not None


def _cols(m: dict) -> list[str]:
    hs = m.get("headers") or []
    return [hs[v] for k, v in m.items() if isinstance(v, int) and v < len(hs) and k not in ("basis_hint",)][:8]


def _read_meta(rows: list[list]) -> dict:
    out: dict = {}
    for r in rows:
        if r and s(r[0]) and len(r) > 1:
            out[s(r[0])] = s(r[1])
    return out


def _wrap(kind: str, layout: str, why: str, data) -> Parsed:
    p = Parsed(kind=kind, layout=layout, confidence="HIGH", why=why, data=data)
    p.summary["facts"] = facts_of(kind, data)
    return p


# ================================================================== facts (JSON-safe summary of what was read)
def facts_of(kind: str, data) -> dict:
    if kind == STATEMENT:
        d: StatementData = data
        no_code = [x for x in d.lines if x.work_no is None]
        works = {x.work_no for x in d.lines if x.work_no}
        neg = [x for x in d.lines if x.amount < 0]
        return dict(layout=d.layout, sheet=d.sheet, holder_member=d.holder_member, holder_name=d.holder_name,
                    ipi_name_no=d.ipi_name_no, ipi_base_no=d.ipi_base_no,
                    printed_total=_str(d.printed_total), lines_total=_str(d.lines_total),
                    subtotal_total=_str(d.subtotal_total), lines=len(d.lines), works=len(works),
                    footers=[dict(name=f.name, rows_total=_str(f.rows_total), grand_total=_str(f.grand_total))
                             for f in d.footers],
                    blank_amount_rows=d.blank_amount_rows[:50], blank_amounts=len(d.blank_amount_rows),
                    no_code_lines=len(no_code), no_code_amount=_str(sum((x.amount for x in no_code), ZERO)),
                    negative_lines=len(neg), pool_sources=d.pool_sources[:40],
                    content_sha256=statement_fingerprint(d))
    if kind in (PLATFORM_REVENUE, PLATFORM_USAGE):
        p: PlatformData = data
        months = sorted({x.month for x in p.lines if x.month})
        amt = [x.amount for x in p.lines if x.amount is not None]
        return dict(sheet=p.sheet, lines=len(p.lines), recordings=len({x.isrc for x in p.lines if x.isrc}),
                    months=[m.isoformat() for m in months], no_month=sum(1 for x in p.lines if not x.month),
                    blank_isrc=sum(1 for x in p.lines if not x.isrc),
                    blank_amount=sum(1 for x in p.lines if kind == PLATFORM_REVENUE and x.amount is None),
                    negative=sum(1 for a in amt if a < 0), total=_str(sum(amt, ZERO)) if amt else None,
                    plays=_str(sum((x.plays for x in p.lines if x.plays is not None), ZERO)),
                    platform_values=p.platform_values[:10], currency_values=p.currency_values[:10],
                    basis_hint=p.basis_hint, headers=p.mapping)
    if kind in (SONG_LIST, REVIEW_LIST):
        sl: SongListData = data
        st = Counter(map_status(e.status_text) for e in sl.entries if e.status_text)
        unrec = sorted({e.status_text for e in sl.entries if e.status_text and map_status(e.status_text) == "NEEDS_CHECK"
                        and "confirm" not in e.status_text.lower()})
        return dict(sheet=sl.sheet, entries=len(sl.entries), works=len({w for e in sl.entries for w in e.work_nos}),
                    isrcs=len({i for e in sl.entries for i in e.isrcs}),
                    no_codes=sum(1 for e in sl.entries if not e.work_nos and not e.isrcs),
                    odd_codes=sum(1 for e in sl.entries if e.other_codes),
                    statuses={k: v for k, v in st.items() if k}, unrecognised_statuses=unrec[:20],
                    with_status=sum(1 for e in sl.entries if e.status_text), mapping=sl.mapping)
    if kind == PREVIOUS_OUTPUT:
        po: PriorOutputData = data
        return dict(sheet=po.sheet, generation=po.generation, native=po.native, rows=len(po.rows),
                    distributions=sum(1 for c in po.columns if c.kind == "ROYALTY"),
                    platform_months=sum(1 for c in po.columns if c.kind == "PLATFORM"),
                    grand_total=_str(po.grand_total), platform_grand={k: _str(v) for k, v in po.platform_grand.items()},
                    integrity=po.integrity[:20],
                    columns=[dict(kind=c.kind, section=c.section, dist_no=c.dist_no, period_label=c.period_label,
                                  total=_str(c.total), platform=c.platform, distributor=c.distributor,
                                  month=c.month.isoformat() if c.month else None) for c in po.columns],
                    title_placed=sum(1 for r in po.rows if r.basis.lower().startswith("song name")
                                     or "; song name" in r.basis.lower()))
    return {}


def _str(v) -> str | None:
    return None if v is None else format(v, "f")


def statement_fingerprint(d: StatementData) -> str:
    h = hashlib.sha256()
    for x in d.lines:
        h.update(f"{x.work_no or x.raw_work}|{x.source or x.pool}|{x.party}|{format(x.amount.normalize(), 'f')}\n"
                 .encode())
    return h.hexdigest()


# ================================================================== evaluate
def evaluate(kind: str, facts: dict, filename: str, client: dict, overrides: dict | None = None,
             file_date: str | None = None) -> dict:
    """-> dict(status, meta, meta_source, problems[], label, summary) for one file of one client.

    client: dict(code, name, holders=[{member_no, name}], settings={distributors: [...], ...})
    overrides: the user's answers (field -> value); they always win and are recorded as 'you entered'.
    """
    ov = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    if kind == STATEMENT:
        out = _eval_statement(facts, filename, client, ov, file_date)
    elif kind in (PLATFORM_REVENUE, PLATFORM_USAGE):
        out = _eval_platform(kind, facts, filename, client, ov)
    elif kind in (SONG_LIST, REVIEW_LIST):
        out = _eval_list(kind, facts, filename, client, ov)
    elif kind == PREVIOUS_OUTPUT:
        out = _eval_prior(facts, filename, client, ov)
    else:
        out = dict(meta={}, meta_source={}, problems=[], label="Unknown file", summary={})
    probs: list[Problem] = out["problems"]
    if any(p.severity == "ERROR" for p in probs):
        status = ERROR
    elif any(p.severity == "EXCLUDE" for p in probs):
        status = LEFT_OUT
    elif any(p.severity == "REVIEW" for p in probs):
        status = NEEDS_REVIEW
    else:
        status = READY
    out["status"] = status
    out["problems"] = [p.as_dict() for p in probs]
    return out


def _set(meta: dict, src: dict, field: str, value, source: str) -> None:
    if value in (None, ""):
        return
    meta[field] = value
    src[field] = source


def _eval_statement(f: dict, filename: str, client: dict, ov: dict, file_date: str | None) -> dict:
    tol = Decimal(client.get("tolerance") or "0.05")
    meta, src, probs = {}, {}, []
    by_name = names.statement_meta_from_name(filename)
    for k in ("label", "category", "dist_no", "overseas_society", "overseas_country", "fy"):
        _set(meta, src, k, by_name.get(k), "file name")
    if by_name.get("period_start"):
        _set(meta, src, "period_start", by_name["period_start"].isoformat(), "file name")
        _set(meta, src, "period_end", by_name["period_end"].isoformat(), "file name")
    overseas = f.get("layout") == "IPRS_OVERSEAS"
    if "category" not in meta or (overseas and meta.get("category") == "Other / Unclassified"):
        cat = names.category_from_footer(f.get("pool_sources") or [], overseas)
        _set(meta, src, "category", cat, "file content")
    if meta.get("category") and meta["category"] != "Overseas" and overseas and "category" not in ov:
        probs.append(Problem("CATEGORY_CONFLICT", "WARNING",
                             f"The file name says '{meta['category']}', but the file has the overseas layout.",
                             "name and content disagree"))
    _set(meta, src, "file_date", file_date, "file (date it was last saved)")
    for k in ("category", "dist_no", "overseas_society", "period", "date"):
        if k in ov:
            if k == "period":
                a, b = names.parse_period_label(ov[k])
                if a:
                    _set(meta, src, "period_start", a.isoformat(), "you entered")
                    _set(meta, src, "period_end", b.isoformat(), "you entered")
                    meta.pop("fy", None)
                elif str(ov[k]).lower() in ("not stated", "not specified", "none"):
                    meta.pop("period_start", None)
                    meta.pop("period_end", None)
                    _set(meta, src, "period_not_stated", True, "you entered")
            else:
                _set(meta, src, k, ov[k], "you entered")
    if meta.get("category") == "Overseas" and meta.get("overseas_society") and not meta.get("overseas_country"):
        from .rules import OVERSEAS_SOCIETIES
        for code, (soc, country) in OVERSEAS_SOCIETIES.items():
            if soc.upper() == str(meta["overseas_society"]).upper():
                meta["overseas_country"] = country
    meta["holder_member"] = f.get("holder_member")
    meta["holder_name"] = f.get("holder_name")
    src["holder_member"] = src["holder_name"] = "file content (letterhead)"
    section = names.section_of(meta.get("category"), meta.get("overseas_society"), meta.get("overseas_country"))
    if section:
        meta["section"] = section
    a = dt.date.fromisoformat(meta["period_start"]) if meta.get("period_start") else None
    b = dt.date.fromisoformat(meta["period_end"]) if meta.get("period_end") else None
    meta["period_label"] = names.period_label(a, b, meta.get("fy", ""))
    meta["date"] = meta.get("date") or meta.get("file_date")
    meta["date_estimated"] = "date" not in ov
    meta["dist_no_label"] = meta.get("dist_no") or "Not specified"

    # ---- money checks (I1-I3)
    printed = Decimal(f["printed_total"]) if f.get("printed_total") else None
    lines_total = Decimal(f["lines_total"] or "0")
    sub = Decimal(f["subtotal_total"] or "0")
    if printed is None:
        probs.append(Problem("NO_PRINTED_TOTAL", "ERROR", "We could not find the statement's printed total "
                             "('TOTAL ROYALTIES'), so its entries cannot be checked. Please upload the complete "
                             "statement as received.", "no TOTAL ROYALTIES row"))
    else:
        diff = lines_total - printed
        if abs(diff) > tol:
            probs.append(Problem("RECON_MISMATCH", "ERROR",
                                 f"We extracted the royalty entries, but their total ({money(lines_total)}) does not "
                                 f"match the total printed in the statement ({money(printed)}). The difference is "
                                 f"{money(diff)}. This statement will be left out until a corrected file is "
                                 f"uploaded.", f"lines {lines_total} vs printed {printed}; tolerance {tol}"))
        elif abs(sub - printed) > tol and f.get("lines", 0):
            probs.append(Problem("SUBTOTAL_MISMATCH", "ERROR",
                                 f"The song sub-totals in this statement add up to {money(sub)}, but the printed "
                                 f"total is {money(printed)}. The statement will be left out until this is "
                                 f"explained.", f"sub-totals {sub} vs printed {printed}"))
        for ft in f.get("footers") or []:
            for which in ("grand_total", "rows_total"):
                v = ft.get(which)
                if v is not None and abs(Decimal(v) - lines_total) > tol:
                    probs.append(Problem("FOOTER_MISMATCH", "ERROR",
                                         f"The '{ft['name'].title()}' table at the bottom of the statement adds up to "
                                         f"{money(Decimal(v))}, but the entries add up to {money(lines_total)}.",
                                         f"footer {ft['name']} {which} {v} vs lines {lines_total}"))
                    break
    if f.get("blank_amounts"):
        probs.append(Problem("BLANK_AMOUNTS", "WARNING", f"{f['blank_amounts']} royalty entr"
                             f"{'y has' if f['blank_amounts'] == 1 else 'ies have'} no amount. They are kept as "
                             f"'unknown', not zero.", f"rows {f.get('blank_amount_rows')}"))
    if f.get("no_code_lines"):
        probs.append(Problem("NO_WORK_NUMBER", "WARNING",
                             f"{f['no_code_lines']} entr{'y has' if f['no_code_lines'] == 1 else 'ies have'} no "
                             f"work number ({money(Decimal(f['no_code_amount']))}). The money is kept and shown as "
                             f"'held' until someone decides where it belongs.", "G6 no code"))
    if f.get("negative_lines"):
        probs.append(Problem("NEGATIVE_LINES", "INFO", f"{f['negative_lines']} entries are negative adjustments. "
                             "They are kept as they are."))
    if f.get("lines", 0) == 0 and printed not in (None, ZERO):
        probs.append(Problem("NO_LINES", "ERROR", "We could not read any royalty entries from this statement.",
                             "0 money lines"))
    # ---- whose statement is it?
    holders = [str(h.get("member_no")) for h in client.get("holders", []) if h.get("member_no")]
    member = str(f.get("holder_member") or "")
    if not member:
        probs.append(Problem("NO_HOLDER", "REVIEW", "We could not read whose statement this is (the member number "
                             "at the top of the statement is missing).", "letterhead B1 blank"))
    elif holders and member not in holders:
        probs.append(Problem("OTHER_HOLDER", "EXCLUDE",
                             f"This statement is for member {member} ({f.get('holder_name') or 'name not shown'}), "
                             f"not for {client.get('name')}. It will be left out of {client.get('code')}'s reports.",
                             f"letterhead member {member}; client holders {holders}"))
    # ---- missing metadata
    if not meta.get("category"):
        probs.append(Problem("NO_CATEGORY", "REVIEW", "We couldn't tell what kind of royalty this statement pays "
                             "(for example YouTube, Spotify or Radio). Please choose one.", field="category"))
    elif meta["category"] == "Overseas" and not meta.get("overseas_society"):
        probs.append(Problem("NO_SOCIETY", "REVIEW", "This is an overseas statement, but we couldn't tell which "
                             "foreign society it comes from. Please enter it (for example BMI or SACEM).",
                             field="overseas_society"))
    if not meta.get("period_start") and not meta.get("period_not_stated"):
        probs.append(Problem("NO_PERIOD", "WARNING", "This statement's reporting period could not be identified. "
                             "Add it if you know it; otherwise its money is shown under 'Period Not Stated'.",
                             field="period"))
    if not meta.get("dist_no"):
        probs.append(Problem("NO_DIST_NO", "INFO", "No distribution number was found in the file name. It will "
                             "be shown as 'Not specified'. You can add it if you know it.", field="dist_no"))
    meta["identity_key"] = "|".join(str(x or "") for x in (
        "IPRS", meta.get("holder_member"), meta.get("section"), meta.get("dist_no"), meta.get("period_start"),
        meta.get("period_end")))
    sec = meta.get("section") or "Royalty statement"
    label = " · ".join(x for x in (sec, meta.get("dist_no"), meta.get("period_label")
                                   if meta.get("period_label") != "Not specified" else None) if x)
    summary = dict(total=f.get("printed_total"), lines=f.get("lines"), works=f.get("works"))
    return dict(meta=meta, meta_source=src, problems=probs, label=label, summary=summary)


def _eval_platform(kind: str, f: dict, filename: str, client: dict, ov: dict) -> dict:
    meta, src, probs = {}, {}, []
    settings = client.get("settings") or {}
    dists = settings.get("distributors") or []
    pv = f.get("platform_values") or []
    if len(pv) == 1:
        _set(meta, src, "platform", names.platform_from_text(pv[0]) or pv[0], "file content")
    else:
        _set(meta, src, "platform", names.platform_from_text(filename), "file name")
    dname = names.distributor_from_name(filename, [d["name"] for d in dists])
    if dname:
        _set(meta, src, "distributor", dname, "file name")
    elif len(dists) == 1:
        _set(meta, src, "distributor", dists[0]["name"], "client setting")
    for k in ("platform", "distributor", "currency", "basis"):
        if k in ov:
            _set(meta, src, k, str(ov[k]).strip(), "you entered")
    dcfg = next((d for d in dists if d["name"].lower() == str(meta.get("distributor", "")).lower()), None)
    if kind == PLATFORM_REVENUE:
        cv = f.get("currency_values") or []
        if "currency" not in meta:
            if len(cv) == 1:
                _set(meta, src, "currency", cv[0], "file content")
            elif dcfg and dcfg.get("currency"):
                _set(meta, src, "currency", dcfg["currency"], "client setting")
        if "basis" not in meta:
            if f.get("basis_hint"):
                _set(meta, src, "basis", f["basis_hint"], "file content (column heading)")
            elif dcfg and dcfg.get("basis"):
                _set(meta, src, "basis", dcfg["basis"], "client setting")
        if len(f.get("currency_values") or []) > 1:
            probs.append(Problem("MIXED_CURRENCY", "ERROR", "This report mixes currencies ("
                                 + ", ".join(f["currency_values"]) + "). Please split it by currency."))
        if meta.get("currency") and str(meta["currency"]).upper() != "INR":
            probs.append(Problem("FOREIGN_CURRENCY", "ERROR", f"This report is in {meta['currency']}. Exchange "
                                 "rates are not set up yet, so only rupee (INR) reports can be processed.",
                                 field="currency"))
        if not meta.get("currency"):
            probs.append(Problem("NO_CURRENCY", "REVIEW", "Which currency is this report in?", field="currency"))
        if not meta.get("basis"):
            probs.append(Problem("NO_BASIS", "REVIEW", "Is this revenue before the distributor's fee (gross) or "
                                 "after it (net)?", field="basis"))
        if f.get("blank_amount"):
            probs.append(Problem("BLANK_AMOUNTS", "WARNING", f"{f['blank_amount']} lines have no revenue amount. "
                                 "They are kept as 'unknown', not zero."))
        if f.get("total") is not None:
            probs.append(Problem("NO_PRINTED_TOTAL_PLATFORM", "INFO",
                                 f"This report has no printed total, so its total ({money(Decimal(f['total']))} "
                                 f"across {f['lines']:,} lines) is calculated from its lines and shown for approval."))
    if not meta.get("platform"):
        probs.append(Problem("NO_PLATFORM", "REVIEW", "Which platform is this report from (for example Spotify)?",
                             field="platform"))
    if not meta.get("distributor"):
        probs.append(Problem("NO_DISTRIBUTOR", "REVIEW", "Which distributor sent this report?", field="distributor"))
    if f.get("blank_isrc"):
        probs.append(Problem("BLANK_ISRC", "WARNING", f"{f['blank_isrc']} lines have no ISRC. Their money is kept "
                             "and shown as 'held' until someone decides where it belongs."))
    if f.get("no_month"):
        probs.append(Problem("NO_MONTH", "ERROR", f"{f['no_month']} lines have no month, so they cannot be placed "
                             "in the report. Please correct the file and upload it again."))
    months = f.get("months") or []
    meta["months"] = months
    if months:
        a, b = dt.date.fromisoformat(months[0]), dt.date.fromisoformat(months[-1])
        meta["period_label"] = names.period_label(a, names.month_end_of(b))
    lbl = KIND_LABEL[kind]
    label = " · ".join(x for x in (meta.get("platform"), meta.get("distributor"), meta.get("period_label")) if x)
    summary = dict(total=f.get("total"), lines=f.get("lines"), recordings=f.get("recordings"), plays=f.get("plays"))
    return dict(meta=meta, meta_source=src, problems=probs, label=f"{lbl} · {label}" if label else lbl,
                summary=summary)


def _eval_list(kind: str, f: dict, filename: str, client: dict, ov: dict) -> dict:
    meta, src, probs = {}, {}, []
    meta["label"] = names.short_label(filename)
    src["label"] = "file name"
    if f.get("entries", 0) == 0:
        probs.append(Problem("EMPTY_LIST", "ERROR", "We found no songs in this list."))
    if f.get("no_codes"):
        probs.append(Problem("TITLE_ONLY", "WARNING", f"{f['no_codes']} songs have no ISRC and no work number. They "
                             "can only be matched by title, which never moves money on its own."))
    if f.get("odd_codes"):
        probs.append(Problem("ODD_CODES", "INFO", f"{f['odd_codes']} songs carry a code we could not read as an ISRC "
                             "or work number (for example 'NEED TO REGISTER'). It is kept as written."))
    if kind == REVIEW_LIST:
        st = f.get("statuses") or {}
        parts = [f"{v} {STATUS_LABEL[k].lower()}" for k, v in sorted(st.items(), key=lambda kv: -kv[1])]
        probs.append(Problem("REVIEW_STATUSES", "INFO", "Review statuses found: " + "; ".join(parts) + ". They will "
                             "be applied to the matching songs and kept with your original wording."))
        if f.get("unrecognised_statuses"):
            probs.append(Problem("UNRECOGNISED_STATUS", "WARNING", "Some statuses were not recognised and are marked "
                                 "'Needs check': " + "; ".join(f["unrecognised_statuses"][:5])))
    label = f"{KIND_LABEL[kind]} · {f.get('entries', 0):,} songs"
    return dict(meta=meta, meta_source=src, problems=probs, label=label,
                summary=dict(entries=f.get("entries"), works=f.get("works"), isrcs=f.get("isrcs")))


def _eval_prior(f: dict, filename: str, client: dict, ov: dict) -> dict:
    meta, src, probs = {}, {}, []
    _set(meta, src, "generation", f.get("generation"), "file content (sheet name)")
    holders = [h for h in client.get("holders", []) if h.get("member_no")]
    if holders:
        _set(meta, src, "holder_member", str(holders[0]["member_no"]), "assumed from the client you selected")
    if f.get("integrity"):
        if ov.get("accept_edited") in (True, "true", "yes", "1"):
            _set(meta, src, "accept_edited", True, "you entered")
            probs.append(Problem("EDITED_BASE_ACCEPTED", "WARNING", "This report was changed after it was produced. "
                                 "You chose to use it anyway; the differences are listed in the run summary.",
                                 "; ".join(f["integrity"][:10])))
        else:
            probs.append(Problem("EDITED_BASE", "REVIEW", "This report seems to have been changed after it was "
                                 "produced: some totals no longer add up. Use it anyway?",
                                 "; ".join(f["integrity"][:10]), field="accept_edited"))
    if f.get("title_placed"):
        probs.append(Problem("TITLE_PLACED_IN_BASE", "INFO", f"{f['title_placed']} songs in this report received "
                             "platform money through a song-name match. Their money is carried as it is and listed "
                             "for confirmation."))
    label = f"{KIND_LABEL[PREVIOUS_OUTPUT]} · {f.get('generation')} · {f.get('rows', 0):,} songs"
    return dict(meta=meta, meta_source=src, problems=probs, label=label,
                summary=dict(total=f.get("grand_total"), rows=f.get("rows"), distributions=f.get("distributions")))

