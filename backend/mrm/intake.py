"""A. classify + B. validate (pages 2-3).

Every original is kept. A file's figures reach a comparison only when it is VALIDATED:
    A2 CLASSIFICATION_HOLD  the right being paid for is not clear
    B2 FILE_EXCEPTION       unreadable / not a workbook (a byte-identical repeat is logged and skipped)
    B3 DATA_EXCEPTION       required metadata missing, or invalid rows not yet accepted as exclusions
    B4 RECONCILIATION_HOLD  lines do not reconcile to the printed total / approved alternative control
    B5 DUPLICATE_REVIEW     overlapping report or copied rows not yet decided
"""
from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

from . import audit, db, storage
from .normalize import ZERO, amount, as_date, q2, s
from .parsing import detect, iprs, reader, safety, tabular
from .security import Forbidden, not_same_person

RECON_TOLERANCE = Decimal("0.01")
LINE_TABLE = {"PUBLISHING": "publishing_line", "RECORDING": "recording_line", "USAGE": "usage_line",
              "IDENTITY": "catalogue_line"}
ACTIVE = ("UPLOADED", "CLASSIFICATION_HOLD", "DATA_EXCEPTION", "RECONCILIATION_HOLD", "DUPLICATE_REVIEW", "VALIDATED")


class IntakeError(Exception):
    pass


# ------------------------------------------------------------------ A1 upload
def batch_for(conn, client_id: int, code: str | None, actor: dict) -> int:
    code = s(code) or dt.date.today().strftime("B%Y%m%d")
    bid = db.scalar(conn, "SELECT id FROM batch WHERE client_id = %s AND code = %s", (client_id, code))
    if bid:
        return bid
    return db.insert(conn, "batch", dict(client_id=client_id, code=code, label=code, created_by=actor["id"]))


def upload(conn, actor: dict, client_id: int, filename: str, data: bytes, batch_code: str | None = None,
           declared_type: str | None = None, meta: dict | None = None) -> dict:
    client = db.one(conn, "SELECT * FROM client WHERE id = %s", (client_id,))
    if not client:
        raise IntakeError("unknown client")
    sha = hashlib.sha256(data).hexdigest()
    repeat = db.one(conn, "SELECT id, filename, status FROM source_file WHERE client_id = %s AND sha256 = %s",
                    (client_id, sha))
    if repeat:
        audit.record(conn, "file.repeat_skipped", actor, "source_file", repeat["id"],
                     dict(filename=filename, sha256=sha, original=repeat["filename"]))
        return dict(id=repeat["id"], repeat=True,
                    message=f"repeat of file #{repeat['id']} ({repeat['filename']}) - logged and skipped; totals "
                            f"are not added twice")
    safe_name = "".join(c for c in filename if c not in "/\\\0")[:200] or "upload"
    key = f"{client['code']}/{sha}{'.csv' if safe_name.lower().endswith('.csv') else '.xlsx'}"
    storage.put("originals", key, data)
    meta_in = {k: v for k, v in (meta or {}).items() if k in detect.META_FIELDS and s(v)}
    fid = db.insert(conn, "source_file", dict(
        client_id=client_id, batch_id=batch_for(conn, client_id, batch_code, actor), filename=safe_name, sha256=sha,
        bytes=len(data), object_key=key, status="UPLOADED", meta={}, meta_source={}, uploaded_by=actor["id"]))
    audit.record(conn, "file.uploaded", actor, "source_file", fid, dict(filename=safe_name, sha256=sha,
                                                                       bytes=len(data), client=client["code"]))
    _extract(conn, fid, data, declared_type, meta_in)
    return dict(evaluate(conn, fid, actor), repeat=False)


def _extract(conn, fid: int, data: bytes, declared_type: str | None, meta_in: dict, header_row: int | None = None,
             mapping: dict | None = None) -> None:
    f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,))
    rep = safety.Report()
    try:
        safety.check_bytes(data, f["filename"], rep)
        sheets = reader.parse(data, rep)
    except safety.Rejected as e:
        db.update(conn, "source_file", fid, dict(status="FILE_EXCEPTION", gate="B2", hold_reason=f"unusable file: {e}",
                                                 checks=rep.checks, format="REJECTED"))
        return
    except Exception as e:                                      # noqa: BLE001 - shown to the operator
        db.update(conn, "source_file", fid, dict(status="FILE_EXCEPTION", gate="B2",
                                                 hold_reason=f"unreadable: {e}", checks=rep.checks, format="DAMAGED"))
        return
    for t in LINE_TABLE.values():
        conn.execute(f"DELETE FROM {t} WHERE file_id = %s", (fid,))
    cls = detect.classify(sheets)
    kind = declared_type or cls["income_type"]
    sheet = next((sh for sh in sheets if sh["title"] == cls["sheet"]), None) or (sheets[0] if sheets else None)
    if mapping is not None and sheet is not None:
        cls.update(header_row=header_row, mapping={k: int(v) for k, v in mapping.items() if s(v) != ""})
    checks = list(rep.checks)
    checks.append(dict(gate="A2", check="classification", result="PASS" if kind != "OTHER" else "HOLD",
                       detail=(f"declared by operator as {kind}; detected {cls['income_type']}" if declared_type
                               else cls["why"])))
    lines: list[dict] = []
    extracted: dict = {}
    printed = None
    fmt = "UNKNOWN"
    try:
        if kind == "PUBLISHING":
            if iprs.header_row(sheet["rows"]) is None:
                raise ValueError("declared as publishing but no IPRS statement header (WORK INT NO) was found")
            extracted = iprs.extract(sheet["rows"], sheet["title"])
            lines, printed, fmt = extracted["lines"], extracted["printed_total"], "IPRS_STATEMENT"
            checks.append(dict(gate="B1", check="layout", result="PASS",
                               detail=f"IPRS statement: header row {extracted['header_row']}, {len(lines):,} money "
                                      f"lines, {extracted['works']:,} works"))
        elif kind in ("RECORDING", "USAGE", "IDENTITY"):
            h, m = cls["header_row"], cls["mapping"]
            if h is None or not m:
                found = tabular.find_header(sheet["rows"]) if sheet else None
                if not found:
                    raise ValueError("no header row with an ISRC or work-code column - map the layout")
                h, m = found
            fn = {"RECORDING": tabular.recording_rows, "USAGE": tabular.usage_rows,
                  "IDENTITY": tabular.catalogue_rows}[kind]
            lines = fn(sheet, h, m)
            fmt = {"RECORDING": "REVENUE_TABLE", "USAGE": "USAGE_TABLE", "IDENTITY": "CATALOGUE"}[kind]
            cls.update(header_row=h, mapping=m)
            checks.append(dict(gate="B1", check="layout", result="PASS",
                               detail=f"{fmt.replace('_', ' ').lower()}: header row {h + 1}, columns "
                                      f"{', '.join(sorted(m))}, {len(lines):,} rows"))
    except ValueError as e:
        db.update(conn, "source_file", fid, dict(income_type=kind, classified_by="operator" if declared_type else
                                                 "detected", status="DATA_EXCEPTION", gate="B3",
                                                 hold_reason=f"layout not recognised: {e}", checks=checks,
                                                 format="UNMAPPED", file_date=reader.zip_date(data)))
        return

    meta, src = {}, {}
    for origin, values in (("filename", detect.meta_from_filename(f["filename"])),
                           ("content", detect.meta_from_content(kind, extracted, lines)),
                           ("operator", meta_in)):
        for k, v in values.items():
            meta[k], src[k] = v, origin
    if kind == "PUBLISHING" and "currency" not in meta and meta.get("sender") == "IPRS":
        meta["currency"], src["currency"] = "INR", "content"          # IPRS distribution statements pay in INR
    if kind == "PUBLISHING" and "territory" not in meta and "overseas" not in f["filename"].lower() \
            and meta.get("sender") == "IPRS":
        meta["territory"], src["territory"] = "IN", "content"
    _store_lines(conn, fid, kind, lines)
    db.update(conn, "source_file", fid, dict(
        income_type=kind, classified_by="operator" if declared_type else "detected", format=fmt, meta=meta,
        meta_source=src, checks=checks, mapping=dict(sheet=cls.get("sheet"), header_row=cls.get("header_row"),
                                                     columns=cls.get("mapping"), pools=extracted.get("pools")),
        printed_total=printed, rows_total=len(lines), file_date=reader.zip_date(data),
        status="CLASSIFICATION_HOLD" if kind == "OTHER" else "UPLOADED",
        gate="A2" if kind == "OTHER" else None, hold_reason=cls["why"] if kind == "OTHER" else None))


def _store_lines(conn, fid: int, kind: str, lines: list[dict]) -> None:
    if kind == "PUBLISHING":
        cols = ("file_id", "row_no", "sheet", "work_code", "title", "party", "role", "own_pct", "coll_pct", "pool",
                "source", "platform", "use_type", "right_scope", "amount", "is_valid", "invalid_reason")
    elif kind == "RECORDING":
        cols = ("file_id", "row_no", "sheet", "isrc", "title", "album", "upc", "content_type", "platform",
                "territory", "month", "amount", "currency", "is_valid", "invalid_reason")
        usage = [x for x in lines if x.get("streams") is not None]
        if usage:
            _store_lines(conn, fid, "USAGE", [dict(x, metric="streams") for x in usage])
    elif kind == "USAGE":
        cols = ("file_id", "row_no", "sheet", "isrc", "title", "album", "platform", "territory", "month", "streams",
                "metric", "is_valid", "invalid_reason")
    elif kind == "IDENTITY":
        cols = ("file_id", "row_no", "title", "work_codes", "isrcs", "raw_work", "film", "composer", "lyricist",
                "performer", "note", "is_valid", "invalid_reason")
        lines = [dict(x, note=x.get("status")) for x in lines]
    else:
        return
    db.insert_many(conn, LINE_TABLE[kind], cols, ([fid if c == "file_id" else x.get(c) for c in cols] for x in lines))


# ------------------------------------------------------------------ B3-B5 evaluation
def _revalidate(conn, f: dict) -> None:
    """Re-derive row validity from the stored row values and the confirmed file metadata (wrong period,
    currency, platform or territory rows are held, never silently dropped)."""
    m = f["meta"]
    p = dict(fid=f["id"], pf=as_date(m.get("period_from")), pt=as_date(m.get("period_to")),
             cur=s(m.get("currency")).upper() or None, plat=s(m.get("platform")) or None,
             terr=s(m.get("territory")).upper() or None)
    isrc_ok = "isrc ~ '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$'"
    common = (" WHEN %(pf)s::DATE IS NOT NULL AND month < %(pf)s THEN 'usage month before the declared period "
              "(wrong period)' WHEN %(pt)s::DATE IS NOT NULL AND month > %(pt)s THEN 'usage month after the declared "
              "period (wrong period)' WHEN %(plat)s::TEXT IS NOT NULL AND platform IS NOT NULL AND platform <> "
              "%(plat)s THEN 'platform ' || platform || ' differs from the file platform (scope)' WHEN "
              "%(terr)s::TEXT IS NOT NULL AND territory IS NOT NULL AND territory <> %(terr)s THEN 'territory ' || "
              "territory || ' differs from the file territory (scope)'")
    if f["income_type"] == "RECORDING":
        reason = (f"CASE WHEN isrc IS NULL OR NOT ({isrc_ok}) THEN 'ISRC missing or not a valid ISRC' "
                  "WHEN amount IS NULL THEN 'revenue blank or not a number (kept unknown, not zero)'" + common +
                  " WHEN %(cur)s::TEXT IS NOT NULL AND currency IS NOT NULL AND currency <> %(cur)s THEN 'currency ' "
                  "|| currency || ' differs from the file currency (wrong currency)' END")
        conn.execute(f"UPDATE recording_line SET invalid_reason = {reason}, is_valid = ({reason}) IS NULL "
                     "WHERE file_id = %(fid)s", p)
    elif f["income_type"] == "USAGE":
        reason = (f"CASE WHEN isrc IS NULL OR NOT ({isrc_ok}) THEN 'ISRC missing or not a valid ISRC' "
                  "WHEN streams IS NULL THEN 'stream count blank or not a whole number (kept unknown, not zero)'"
                  + common + " END")
        conn.execute(f"UPDATE usage_line SET invalid_reason = {reason}, is_valid = ({reason}) IS NULL "
                     "WHERE file_id = %(fid)s", p)
    if f["income_type"] == "RECORDING":           # streams carried in a revenue file follow the same checks
        reason = (f"CASE WHEN isrc IS NULL OR NOT ({isrc_ok}) THEN 'ISRC missing or not a valid ISRC' "
                  "WHEN streams IS NULL THEN 'stream count blank'" + common + " END")
        conn.execute(f"UPDATE usage_line SET invalid_reason = {reason}, is_valid = ({reason}) IS NULL "
                     "WHERE file_id = %(fid)s", p)


def _totals(conn, f: dict) -> dict:
    t = f["income_type"]
    if t in ("PUBLISHING", "RECORDING"):
        r = db.one(conn, f"SELECT count(*) AS n, count(*) FILTER (WHERE NOT is_valid) AS bad, "
                         f"sum(amount) AS all_total, sum(amount) FILTER (WHERE is_valid) AS valid_total, "
                         f"sum(amount) FILTER (WHERE NOT is_valid) AS held_total, "
                         f"count(*) FILTER (WHERE amount = 0) AS zeros FROM {LINE_TABLE[t]} WHERE file_id = %s",
                   (f["id"],))
    elif t == "USAGE":
        r = db.one(conn, "SELECT count(*) AS n, count(*) FILTER (WHERE NOT is_valid) AS bad, sum(streams) AS all_total, "
                         "sum(streams) FILTER (WHERE is_valid) AS valid_total, sum(streams) FILTER (WHERE NOT "
                         "is_valid) AS held_total, 0 AS zeros FROM usage_line WHERE file_id = %s", (f["id"],))
    else:
        r = db.one(conn, "SELECT count(*) AS n, count(*) FILTER (WHERE NOT is_valid) AS bad, NULL::NUMERIC AS "
                         "all_total, NULL::NUMERIC AS valid_total, NULL::NUMERIC AS held_total, 0 AS zeros "
                         "FROM catalogue_line WHERE file_id = %s", (f["id"],))
    return r


def _fingerprint_sql(t: str) -> str:
    return {"PUBLISHING": "concat_ws('|', work_code, source, party, amount::TEXT)",
            "RECORDING": "concat_ws('|', isrc, month::TEXT, platform, territory, amount::TEXT)",
            "USAGE": "concat_ws('|', isrc, month::TEXT, platform, territory, streams::TEXT)"}[t]


def _overlaps(conn, f: dict) -> list[dict]:
    t = f["income_type"]
    if t not in ("PUBLISHING", "RECORDING", "USAGE"):
        return []
    m = f["meta"]
    pf, pt = as_date(m.get("period_from")), as_date(m.get("period_to"))
    others = db.all(conn, "SELECT id, filename, meta, status, uploaded_at FROM source_file WHERE client_id = %s AND "
                          "income_type = %s AND id <> %s AND status = ANY(%s)",
                    (f["client_id"], t, f["id"], list(ACTIVE)))
    out = []
    fp = _fingerprint_sql(t)
    table = LINE_TABLE[t]
    plats = {r["platform"] for r in db.all(conn, f"SELECT DISTINCT platform FROM {table} WHERE file_id = %s",
                                           (f["id"],))}
    for o in others:
        om = o["meta"]
        opf, opt = as_date(om.get("period_from")), as_date(om.get("period_to"))
        oplats = {r["platform"] for r in db.all(conn, f"SELECT DISTINCT platform FROM {table} WHERE file_id = %s",
                                                (o["id"],))}
        same_platform = bool(plats & oplats) or None in plats or None in oplats
        periods_overlap = bool(pf and pt and opf and opt and pf <= opt and opf <= pt)
        if t == "PUBLISHING" and m.get("distribution_ref") and om.get("distribution_ref") \
                and m["distribution_ref"] != om["distribution_ref"]:
            same_platform = False                   # different distributions: only identical rows are an overlap
        shared = db.scalar(conn, f"SELECT count(*) FROM (SELECT {fp} FROM {table} WHERE file_id = %s INTERSECT "
                                 f"SELECT {fp} FROM {table} WHERE file_id = %s) x", (f["id"], o["id"]))
        if (same_platform and periods_overlap) or shared:
            n = db.scalar(conn, f"SELECT count(*) FROM {table} WHERE file_id = %s", (f["id"],)) or 1
            out.append(dict(file_id=o["id"], filename=o["filename"], status=o["status"], shared_rows=shared,
                            share=round(shared / n, 3), period_overlap=periods_overlap, uploaded_at=o["uploaded_at"]))
    return out


def _row_duplicates(conn, f: dict) -> int:
    t = f["income_type"]
    if t not in ("PUBLISHING", "RECORDING", "USAGE"):
        return 0
    table, fp = LINE_TABLE[t], _fingerprint_sql(t)
    conn.execute(f"UPDATE {table} SET duplicate_state = 'CANDIDATE' WHERE file_id = %(f)s AND duplicate_state = "
                 f"'NONE' AND {fp} IN (SELECT {fp} FROM {table} WHERE file_id = %(f)s GROUP BY 1 HAVING count(*) > 1)",
                 dict(f=f["id"]))
    return db.scalar(conn, f"SELECT count(*) FROM {table} WHERE file_id = %s AND duplicate_state = 'CANDIDATE'",
                     (f["id"],))


def evaluate(conn, fid: int, actor: dict | None = None) -> dict:
    f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,))
    before = f["status"]
    if f["status"] in ("FILE_EXCEPTION", "SUPERSEDED", "EXCLUDED") or f["income_type"] in (None, "OTHER"):
        return _result(conn, f)
    if f["format"] == "UNMAPPED":
        return _result(conn, f)
    _revalidate(conn, f)
    t = f["income_type"]
    tot = _totals(conn, f)
    checks = [c for c in (f["checks"] or []) if c.get("gate") not in ("B3", "B4", "B5")]
    status, gate, reason = "VALIDATED", None, None

    # B3 - required fields
    miss = detect.missing(t, f["meta"])
    accepted = (f["decisions"] or {}).get("rows_accepted")
    if miss:
        checks.append(dict(gate="B3", check="metadata", result="HOLD",
                           detail="not stated: " + ", ".join(x.replace("_", " ") for x in miss)))
        status, gate, reason = "DATA_EXCEPTION", "B3", "confirm " + ", ".join(x.replace("_", " ") for x in miss)
    else:
        checks.append(dict(gate="B3", check="metadata", result="PASS",
                           detail=", ".join(f"{k}={v}" for k, v in sorted(f["meta"].items()) if k in
                                            detect.REQUIRED_META[t])))
    if tot["bad"]:
        ok = accepted is not None and accepted.get("count") == tot["bad"]
        checks.append(dict(gate="B3", check="invalid rows", result="PASS" if ok else "HOLD",
                           detail=f"{tot['bad']:,} row(s) invalid and held out of every total"
                                  + (f" - exclusion accepted by {accepted.get('by')}" if ok else
                                     " - correct the source or accept their exclusion (rows stay listed)")))
        if not ok and status == "VALIDATED":
            status, gate, reason = "DATA_EXCEPTION", "B3", f"{tot['bad']:,} invalid row(s) to review"
    else:
        checks.append(dict(gate="B3", check="invalid rows", result="PASS", detail="every row valid"))

    # B4 - reconciliation (lines read vs printed total or approved alternative control)
    lines_total = tot["all_total"]
    recon = None
    if t in ("PUBLISHING", "RECORDING", "USAGE"):
        target, label = (f["printed_total"], "printed total") if f["printed_total"] is not None else \
            (f["control_total"], f"approved alternative control ({f['control_ref']})")
        bridge = sum((amount(b.get("amount")) or ZERO for b in (f["bridge"] or [])), ZERO)
        if target is None:
            recon = dict(result="HOLD", detail="no printed total - an approved alternative control (supplier "
                                               "confirmation or independently checked source total) is required")
        else:
            diff = (target - (lines_total or ZERO) - bridge)
            ok = abs(diff) <= RECON_TOLERANCE
            recon = dict(result="PASS" if ok else "HOLD",
                         detail=f"lines {_fmt(lines_total, t)} {'+ bridge ' + _fmt(bridge, t) + ' ' if bridge else ''}"
                                f"vs {label} {_fmt(target, t)}: difference {_fmt(diff, t)}"
                                + ("" if ok else " - find missed lines, fees, tax, rounding or adjustments; no "
                                                 "invented balancing entry"))
        checks.append(dict(gate="B4", check="reconciliation", **recon))
        if recon["result"] != "PASS" and status == "VALIDATED":
            status, gate, reason = "RECONCILIATION_HOLD", "B4", recon["detail"]

    # B5 - overlapping reports and copied rows
    if t in ("PUBLISHING", "RECORDING", "USAGE"):
        decided = (f["decisions"] or {}).get("overlaps", {})
        pending = [o for o in _overlaps(conn, f) if str(o["file_id"]) not in decided]
        dup_rows = _row_duplicates(conn, f)
        if pending:
            checks.append(dict(gate="B5", check="overlapping reports", result="HOLD",
                               detail="; ".join(f"file #{o['file_id']} {o['filename']} ({o['shared_rows']:,} identical "
                                                f"rows, period overlap {'yes' if o['period_overlap'] else 'no'})"
                                                for o in pending)))
        else:
            checks.append(dict(gate="B5", check="overlapping reports", result="PASS",
                               detail="no overlap" if not decided else
                               "; ".join(f"#{k}: {v['decision'].lower()} ({v['by']})" for k, v in decided.items())))
        checks.append(dict(gate="B5", check="copied rows", result="HOLD" if dup_rows else "PASS",
                           detail=f"{dup_rows:,} identical row(s) in this file - retain if legitimate repeated earnings, "
                                  f"suppress only an evidenced duplicate" if dup_rows else "no identical rows"))
        if (pending or dup_rows) and status == "VALIDATED":
            status, gate = "DUPLICATE_REVIEW", "B5"
            reason = "overlapping report(s) to decide" if pending else f"{dup_rows:,} identical row(s) to decide"

    db.update(conn, "source_file", fid, dict(status=status, gate=gate, hold_reason=reason, checks=checks,
                                             lines_total=lines_total, rows_invalid=tot["bad"]))
    if before != status:
        audit.record(conn, "file.status", actor, "source_file", fid, dict(before=before, after=status, gate=gate,
                                                                         reason=reason))
    f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,))
    return _result(conn, f)


def _fmt(v, t: str) -> str:
    if v is None:
        return "-"
    return f"{int(v):,} streams" if t == "USAGE" else f"{q2(v):,.2f}"


def _result(conn, f: dict) -> dict:
    return dict(id=f["id"], status=f["status"], gate=f["gate"], hold_reason=f["hold_reason"],
                income_type=f["income_type"])


# ------------------------------------------------------------------ operator actions
def _file(conn, fid: int) -> dict:
    f = db.one(conn, "SELECT * FROM source_file WHERE id = %s FOR UPDATE", (fid,))
    if not f:
        raise IntakeError("unknown file")
    return f


def reclassify(conn, actor: dict, fid: int, income_type: str, header_row: int | None = None,
               columns: dict | None = None) -> dict:
    """A2 / B3: the operator states the right being paid for, or maps an unknown layout; the file is re-read."""
    f = _file(conn, fid)
    if income_type not in ("PUBLISHING", "RECORDING", "USAGE", "IDENTITY", "OTHER"):
        raise IntakeError("income type must be PUBLISHING, RECORDING, USAGE, IDENTITY or OTHER")
    if f["status"] in ("SUPERSEDED", "EXCLUDED"):
        raise IntakeError(f"file is {f['status'].lower()}")
    data = storage.get("originals", f["object_key"])
    keep = {k: v for k, v in f["meta"].items() if f["meta_source"].get(k) == "operator"}
    db.update(conn, "source_file", fid, dict(status="UPLOADED", gate=None, hold_reason=None))
    _extract(conn, fid, data, income_type, keep, header_row, columns)
    audit.record(conn, "file.classified", actor, "source_file", fid,
                 dict(before=f["income_type"], after=income_type, header_row=header_row, columns=columns))
    return evaluate(conn, fid, actor)


def set_meta(conn, actor: dict, fid: int, fields: dict) -> dict:
    f = _file(conn, fid)
    meta, src = dict(f["meta"]), dict(f["meta_source"])
    changed = {}
    for k, v in fields.items():
        if k not in detect.META_FIELDS:
            continue
        v = s(v)
        if k in ("period_from", "period_to") and v and not as_date(v):
            raise IntakeError(f"{k.replace('_', ' ')} must be a date (YYYY-MM-DD)")
        if k == "share" and v:
            a = amount(v)
            if a is None or not (ZERO < a <= 1):
                raise IntakeError("share is a fraction between 0 and 1 (e.g. 1 for 100%) - never assumed")
        if k in ("currency", "territory") and v:
            v = v.upper()
        if k == "basis" and v and v.upper() not in ("GROSS", "NET"):
            raise IntakeError("revenue basis is GROSS or NET")
        if k == "basis":
            v = v.upper()
        if meta.get(k) != (v or None):
            changed[k] = dict(before=meta.get(k), after=v or None)
        if v:
            meta[k], src[k] = v, "operator"
        else:
            meta.pop(k, None)
            src.pop(k, None)
    db.update(conn, "source_file", fid, dict(meta=meta, meta_source=src))
    if changed:
        audit.record(conn, "file.metadata", actor, "source_file", fid, changed)
    return evaluate(conn, fid, actor)


def accept_row_exceptions(conn, actor: dict, fid: int, note: str) -> dict:
    f = _file(conn, fid)
    if not s(note):
        raise IntakeError("give the reason the invalid rows can be held out")
    bad = f["rows_invalid"]
    dec = dict(f["decisions"] or {})
    dec["rows_accepted"] = dict(count=bad, by=actor["email"], at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                note=note)
    db.update(conn, "source_file", fid, dict(decisions=dec, row_exceptions_accepted=actor["id"]))
    audit.record(conn, "file.rows_accepted", actor, "source_file", fid, dict(count=bad, note=note))
    return evaluate(conn, fid, actor)


def approve_control(conn, actor: dict, fid: int, control_total, reference: str, bridge: list[dict] | None = None) -> dict:
    """B4: approved alternative control when no total is printed, and/or an evidenced bridge."""
    f = _file(conn, fid)
    if f["uploaded_by"] == actor["id"] and "admin" not in actor["roles"]:
        raise Forbidden("the alternative control must be approved by someone other than the uploader")
    ct = amount(control_total) if s(control_total) else None
    if f["printed_total"] is None and ct is None:
        raise IntakeError("enter the independently checked control total")
    if ct is not None and not s(reference):
        raise IntakeError("give the evidence reference for the control total (supplier confirmation, portal total)")
    items = []
    for b in bridge or []:
        a = amount(b.get("amount"))
        if a is None or not s(b.get("label")) or not s(b.get("evidence")):
            raise IntakeError("each bridge item needs a label, an amount and its evidence")
        items.append(dict(label=s(b["label"]), amount=format(a, "f"), evidence=s(b["evidence"])))
    upd = dict(bridge=items or None)
    if ct is not None:
        upd.update(control_total=ct, control_ref=s(reference), control_by=actor["id"])
    db.update(conn, "source_file", fid, upd)
    audit.record(conn, "file.control_approved", actor, "source_file", fid,
                 dict(control_total=ct, reference=reference, bridge=items))
    return evaluate(conn, fid, actor)


def decide_overlap(conn, actor: dict, fid: int, other_id: int, decision: str, note: str) -> dict:
    """B2/B5: SUPERSEDES - this file corrects the other (the other stops counting); SEPARATE - both are
    legitimate reports (different distributions)."""
    f = _file(conn, fid)
    o = _file(conn, other_id)
    if decision not in ("SUPERSEDES", "SEPARATE"):
        raise IntakeError("decision is SUPERSEDES or SEPARATE")
    if not s(note):
        raise IntakeError("record the evidence for the decision")
    if o["client_id"] != f["client_id"]:
        raise IntakeError("files belong to different clients")
    not_same_person(actor, f["uploaded_by"], "a supersession or overlap decision")
    dec = dict(f["decisions"] or {})
    dec.setdefault("overlaps", {})[str(other_id)] = dict(decision=decision, by=actor["email"], note=note,
                                                         at=dt.datetime.now(dt.timezone.utc).isoformat())
    upd = dict(decisions=dec)
    if decision == "SUPERSEDES":
        upd.update(supersedes_id=other_id, supersession_approved_by=actor["id"])
        db.update(conn, "source_file", other_id, dict(status="SUPERSEDED", gate=None,
                                                      hold_reason=f"superseded by file #{fid} {f['filename']}"))
        audit.record(conn, "file.status", actor, "source_file", other_id,
                     dict(before=o["status"], after="SUPERSEDED", by_file=fid))
    else:
        odec = dict(o["decisions"] or {})
        odec.setdefault("overlaps", {})[str(fid)] = dec["overlaps"][str(other_id)]
        db.update(conn, "source_file", other_id, dict(decisions=odec))
    db.update(conn, "source_file", fid, upd)
    audit.record(conn, "file.overlap_decided", actor, "source_file", fid, dict(other=other_id, decision=decision,
                                                                              note=note))
    if decision == "SEPARATE":
        evaluate(conn, other_id, actor)
    return evaluate(conn, fid, actor)


def decide_row_duplicates(conn, actor: dict, fid: int, decision: str, note: str) -> dict:
    f = _file(conn, fid)
    if decision not in ("RETAIN", "SUPPRESS"):
        raise IntakeError("decision is RETAIN (legitimate repeated earnings) or SUPPRESS (evidenced duplicate)")
    if not s(note):
        raise IntakeError("record the evidence for the decision")
    t = LINE_TABLE[f["income_type"]]
    if decision == "RETAIN":
        n = conn.execute(f"UPDATE {t} SET duplicate_state = 'LEGITIMATE' WHERE file_id = %s AND duplicate_state = "
                         "'CANDIDATE'", (fid,)).rowcount
    else:
        fp = _fingerprint_sql(f["income_type"])
        n = conn.execute(f"UPDATE {t} l SET duplicate_state = CASE WHEN l.id = x.keep THEN 'LEGITIMATE' ELSE "
                         f"'SUPPRESSED' END FROM (SELECT {fp} AS k, min(id) AS keep FROM {t} WHERE file_id = %(f)s AND "
                         f"duplicate_state = 'CANDIDATE' GROUP BY 1) x WHERE l.file_id = %(f)s AND "
                         f"l.duplicate_state = 'CANDIDATE' AND {fp} = x.k",
                         dict(f=fid)).rowcount
    dec = dict(f["decisions"] or {})
    dec["row_duplicates"] = dict(decision=decision, rows=n, by=actor["email"], note=note)
    db.update(conn, "source_file", fid, dict(decisions=dec))
    audit.record(conn, "file.row_duplicates", actor, "source_file", fid, dict(decision=decision, rows=n, note=note))
    return evaluate(conn, fid, actor)


def exclude(conn, actor: dict, fid: int, note: str) -> dict:
    f = _file(conn, fid)
    if not s(note):
        raise IntakeError("give the reason for excluding the file")
    db.update(conn, "source_file", fid, dict(status="EXCLUDED", gate=None, hold_reason=note))
    audit.record(conn, "file.status", actor, "source_file", fid, dict(before=f["status"], after="EXCLUDED", note=note))
    return _result(conn, db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,)))


# ------------------------------------------------------------------ reads
def file_rows(conn, fid: int, only: str = "all", limit: int = 200, offset: int = 0) -> dict:
    f = db.one(conn, "SELECT income_type FROM source_file WHERE id = %s", (fid,))
    if not f or f["income_type"] not in LINE_TABLE:
        return dict(rows=[], total=0)
    t = LINE_TABLE[f["income_type"]]
    where = {"all": "", "invalid": " AND NOT is_valid",
             "duplicates": " AND duplicate_state <> 'NONE'" if t != "catalogue_line" else " AND FALSE"}[only]
    total = db.scalar(conn, f"SELECT count(*) FROM {t} WHERE file_id = %s{where}", (fid,))
    rows = db.all(conn, f"SELECT * FROM {t} WHERE file_id = %s{where} ORDER BY row_no LIMIT %s OFFSET %s",
                  (fid, limit, offset))
    return dict(rows=rows, total=total, table=t)
