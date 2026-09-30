"""S0 intake, S1 classify, S2-S4 extract - and the persistence of all of it.

    upload -> sha256 / dedupe / quarantine -> classify (shape + filename metadata)
           -> extract (statement lines / sheet entries / platform lines) -> reconcile
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re

from ..core import config, db
from ..domain.filename import SECTION_ORDER, parse_filename, parse_s_no, period_label
from ..domain.normalize import month_end, norm, s
from ..domain import sniff
from .platform import extract_platform
from .reader import preview, read_grid
from .sheets import catalogue_mapping, load_entries, user_sheet_proposal
from .statement import extract_statement

OVERRIDABLE = ("kind", "category_code", "dist_no", "period_from", "period_to", "society_code",
               "s_no", "stmt_date")


# ------------------------------------------------------------------ batches
def create_batch(conn, label: str, user: str | None = None, note: str | None = None) -> int:
    with db.tx(conn):
        return db.insert(conn, "ingest_batch", dict(label=label, note=note, created_at=db.now(),
                                                    created_by=user))


def batch_summary(conn, batch_id: int) -> dict | None:
    b = db.row(conn, "SELECT * FROM ingest_batch WHERE id = ?", (batch_id,))
    if not b:
        return None
    kinds = db.rows(conn, "SELECT kind, status, COUNT(*) n FROM source_file WHERE batch_id = ? "
                          "GROUP BY kind, status", (batch_id,))
    b["files"] = sum(k["n"] for k in kinds)
    b["by_kind"] = kinds
    b["statements"] = db.scalar(conn, "SELECT COUNT(*) FROM statement WHERE batch_id = ?", (batch_id,))
    b["failed_recon"] = db.scalar(conn, "SELECT COUNT(*) FROM statement WHERE batch_id = ? AND "
                                        "reconciled = 0", (batch_id,))
    b["statement_total"] = db.scalar(conn, "SELECT SUM(ROUND(extracted_total, 2)) FROM statement "
                                           "WHERE batch_id = ?", (batch_id,)) or 0.0
    b["pending"] = db.scalar(conn, "SELECT COUNT(*) FROM source_file WHERE batch_id = ? AND "
                                   "status = 'uploaded'", (batch_id,))
    last = db.row(conn, "SELECT id, label, status, created_at FROM build_run WHERE batch_id = ? "
                        "ORDER BY id DESC LIMIT 1", (batch_id,))
    b["last_build"] = last
    return b


# ------------------------------------------------------------------ S0 intake + S1 classify
def add_file(conn, batch_id: int, filename: str, data: bytes, user: str | None = None) -> dict:
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"{filename}: larger than MAX_UPLOAD_MB={config.MAX_UPLOAD_MB}")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.row(conn, "SELECT * FROM source_file WHERE batch_id = ? AND sha256 = ?",
                      (batch_id, sha))
    if existing:
        return dict(id=existing["id"], sha256=sha, duplicate=True,
                    detected_kind=existing["detected_kind"], filename=existing["filename"])
    config.ensure_dirs()
    path = config.STORAGE_DIR / sha[:2] / f"{sha}{os.path.splitext(filename)[1].lower() or '.xlsx'}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    try:
        _title, grid = read_grid(data, max_rows=260)
        kind = sniff.detect(grid)
        err = None
    except Exception as e:                                   # noqa: BLE001 - not a readable workbook
        grid, kind, err = [], sniff.UNKNOWN, f"cannot read workbook: {e}"
    meta = _classify_meta(conn, filename, data, kind)
    seq = (db.scalar(conn, "SELECT MAX(upload_seq) FROM source_file WHERE batch_id = ?",
                     (batch_id,)) or 0) + 1
    status = "quarantined" if kind == sniff.UNKNOWN else "uploaded"
    with db.tx(conn):
        fid = db.insert(conn, "source_file", dict(
            batch_id=batch_id, sha256=sha, filename=filename, size=len(data),
            stored_path=str(path), upload_seq=seq, detected_kind=kind, kind=kind, status=status,
            sniff_json=db.dumps(preview(grid)), meta_json=db.dumps(meta), override_json="{}",
            error=err or ("shape not recognised - quarantined; set the kind by hand to use it"
                          if kind == sniff.UNKNOWN else None),
            created_at=db.now()))
    return dict(id=fid, sha256=sha, duplicate=False, detected_kind=kind, filename=filename,
                status=status)


def _classify_meta(conn, filename: str, data: bytes, kind: str) -> dict:
    if kind in sniff.STATEMENT_KINDS:
        m = parse_filename(filename, data, db.get_categories(conn), db.get_societies(conn))
        return {k: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in m.items()}
    return dict(s_no=parse_s_no(filename))


def file_view(conn, f: dict) -> dict:
    f = dict(f)
    f["meta"] = db.loads(f.pop("meta_json"), {})
    f["override"] = db.loads(f.pop("override_json"), {})
    f["sniff"] = db.loads(f.pop("sniff_json"), [])
    f["kind_label"] = sniff.KIND_LABEL.get(f["kind"], f["kind"])
    st = db.row(conn, "SELECT id, s_no, dist_no, category, section, schema, period, stmt_date, "
                      "society, country, line_count, block_count, work_count, extracted_total, "
                      "file_total, reconciled FROM statement WHERE source_file_id = ?", (f["id"],))
    f["statement"] = st
    f["sheet"] = db.row(conn, "SELECT id, label, row_count, is_catalogue, mapping_status FROM "
                              "user_sheet WHERE source_file_id = ?", (f["id"],))
    f["report"] = db.row(conn, "SELECT id, kind, label, month_from, month_to, line_count, isrc_count, "
                               "total FROM platform_report WHERE source_file_id = ?", (f["id"],))
    f["anomalies"] = db.scalar(conn, "SELECT COUNT(*) FROM ingest_anomaly WHERE source_file_id = ?",
                               (f["id"],))
    f.pop("stored_path", None)
    return f


def list_files(conn, batch_id: int) -> list[dict]:
    return [file_view(conn, f) for f in db.rows(
        conn, "SELECT * FROM source_file WHERE batch_id = ? ORDER BY upload_seq", (batch_id,))]


def patch_file(conn, file_id: int, changes: dict) -> dict:
    f = db.row(conn, "SELECT * FROM source_file WHERE id = ?", (file_id,))
    if not f:
        raise KeyError(file_id)
    ov = db.loads(f["override_json"], {})
    for k, v in changes.items():
        if k not in OVERRIDABLE:
            raise ValueError(f"field {k!r} cannot be overridden")
        if v in (None, ""):
            ov.pop(k, None)
        else:
            ov[k] = v
    new_kind = ov.get("kind", f["detected_kind"])
    if new_kind not in sniff.ALL_KINDS:
        raise ValueError(f"unknown kind {new_kind!r}")
    with db.tx(conn):
        conn.execute("UPDATE source_file SET override_json = ? WHERE id = ?", (db.dumps(ov), file_id))
        if new_kind != f["kind"]:
            _drop_derived(conn, file_id)
            conn.execute("UPDATE source_file SET kind = ?, status = ?, error = NULL WHERE id = ?",
                         (new_kind, "quarantined" if new_kind == sniff.UNKNOWN else "uploaded", file_id))
        else:
            st = db.row(conn, "SELECT * FROM statement WHERE source_file_id = ?", (file_id,))
            if st:
                conn.execute("UPDATE statement SET s_no=?, dist_no=?, category_code=?, category=?, "
                             "section=?, society_code=?, society=?, country=?, p_start=?, p_end=?, "
                             "fy=?, period=?, stmt_date=? WHERE id=?",
                             (*_statement_meta_values(conn, f, ov, st["s_no"]), st["id"]))
    return file_view(conn, db.row(conn, "SELECT * FROM source_file WHERE id = ?", (file_id,)))


def file_in_use(conn, file_id: int) -> str | None:
    """Why this file's extracted data must not change (builds and runs are immutable), or None."""
    b = db.scalar(conn, "SELECT MIN(bs.build_id) FROM build_statement bs JOIN statement st ON st.id = bs.statement_id "
                        "WHERE st.source_file_id = ?", (file_id,)) or \
        db.scalar(conn, "SELECT MIN(br.build_id) FROM build_report br JOIN platform_report pr ON pr.id = br.report_id "
                        "WHERE pr.source_file_id = ?", (file_id,))
    if b:
        return f"this file is part of build #{b} - builds are immutable"
    sheet = db.scalar(conn, "SELECT id FROM user_sheet WHERE source_file_id = ?", (file_id,))
    return sheet_in_use(conn, sheet) if sheet else None


def sheet_in_use(conn, sheet_id: int) -> str | None:
    b = db.scalar(conn, "SELECT MIN(id) FROM build_run WHERE catalogue_sheet_id = ?", (sheet_id,))
    if b:
        return f"this sheet is the catalogue of build #{b} - builds are immutable"
    n = (db.scalar(conn, "SELECT COUNT(*) FROM coverage_run WHERE sheet_id = ?", (sheet_id,)) +
         db.scalar(conn, "SELECT COUNT(*) FROM mismatch_run WHERE sheet_id = ?", (sheet_id,)))
    if n:
        return f"this sheet was audited by {n} coverage / mismatch run(s), which record its entries"
    return None


def delete_file(conn, file_id: int) -> None:
    why = file_in_use(conn, file_id)
    if why:
        raise ValueError(f"{why}, so the file cannot be removed")
    with db.tx(conn):
        conn.execute("DELETE FROM source_file WHERE id = ?", (file_id,))


def _drop_derived(conn, file_id: int) -> None:
    why = file_in_use(conn, file_id)
    if why:
        raise ValueError(f"{why}; upload it into a new batch to extract it differently")
    for t in ("statement", "user_sheet", "platform_report", "ingest_anomaly"):
        conn.execute(f"DELETE FROM {t} WHERE source_file_id = ?", (file_id,))


def _statement_meta_values(conn, f: dict, ov: dict, s_no: int) -> tuple:
    meta = db.loads(f["meta_json"], {})
    cats = {c[0]: c[1] for c in db.get_categories(conn)}
    socs = {c[0]: (c[1], c[2]) for c in db.get_societies(conn)}
    cat_code = ov.get("category_code", meta.get("category_code"))
    category = cats.get(cat_code, meta.get("category"))
    soc_code = ov.get("society_code", meta.get("society_code")) or ""
    soc, country = socs.get(soc_code, ("", ""))
    section = f"Overseas - {soc} ({country})" if (cat_code == "overseas" and soc) else category
    p_start, p_end, fy = meta.get("p_start"), meta.get("p_end"), meta.get("fy") or ""
    if "period_from" in ov and "period_to" in ov:
        y0, m0 = map(int, ov["period_from"].split("-")[:2])
        y1, m1 = map(int, ov["period_to"].split("-")[:2])
        p_start, p_end, fy = dt.date(y0, m0, 1).isoformat(), month_end(y1, m1).isoformat(), ""
    period = period_label(dt.date.fromisoformat(p_start) if p_start else None,
                          dt.date.fromisoformat(p_end) if p_end else None, fy)
    return (int(ov.get("s_no", s_no)), ov.get("dist_no", meta.get("dist_no") or ""), cat_code, category,
            section, soc_code or None, soc or None, country or None, p_start, p_end, fy or None, period,
            ov.get("stmt_date", meta.get("stmt_date")))


# ------------------------------------------------------------------ S2-S4 extract
def extract_batch(ctx, conn, batch_id: int, force: bool = False) -> dict:
    files = db.rows(conn, "SELECT * FROM source_file WHERE batch_id = ? ORDER BY upload_seq", (batch_id,))
    todo = [f for f in files if f["status"] in (("uploaded", "failed", "extracted") if force else
                                                  ("uploaded", "failed"))]
    kept = [f for f in todo if f["status"] == "extracted" and file_in_use(conn, f["id"])]
    todo = [f for f in todo if f not in kept]
    for f in kept:
        ctx.log(f"kept {f['filename']} - {file_in_use(conn, f['id'])}")
    explicit = [parse_s_no(f["filename"]) for f in files]
    prev_sno = {r["source_file_id"]: r["s_no"] for r in db.rows(
        conn, "SELECT source_file_id, s_no FROM statement WHERE batch_id = ?", (batch_id,))}
    taken = {n for n in explicit if n} | set(prev_sno.values())
    next_s = max(taken or {0}) + 1
    done, failed = 0, 0
    for i, f in enumerate(todo):
        ctx.progress(i / max(1, len(todo)), f"extracting {f['filename']}")
        try:
            data = open(f["stored_path"], "rb").read()
            _title, grid = read_grid(data)
            with db.tx(conn):
                _drop_derived(conn, f["id"])
                kind = f["kind"]
                if kind in sniff.STATEMENT_KINDS:
                    s_no = parse_s_no(f["filename"]) or prev_sno.get(f["id"])
                    if s_no is None:
                        s_no, next_s = next_s, next_s + 1
                    _persist_statement(conn, f, grid, s_no)
                elif kind in sniff.SHEET_KINDS:
                    _persist_sheet(conn, f, grid, kind)
                elif kind in sniff.PLATFORM_KINDS:
                    _persist_platform(conn, f, grid, kind)
                else:
                    conn.execute("UPDATE source_file SET status='quarantined' WHERE id=?", (f["id"],))
                    continue
                conn.execute("UPDATE source_file SET status='extracted', extracted_at=?, error=NULL "
                             "WHERE id=?", (db.now(), f["id"]))
            done += 1
        except Exception as e:                               # noqa: BLE001 - a bad file never aborts the batch
            failed += 1
            conn.execute("UPDATE source_file SET status='failed', error=? WHERE id=?", (str(e)[:1000], f["id"]))
            ctx.log(f"FAILED {f['filename']}: {e}")
    v = validation(conn, batch_id)
    msg = (f"{done} file(s) extracted, {failed} failed; statements {v['pass']} PASS / "
           f"{v['fail']} FAIL")
    ctx.log(msg)
    return dict(message=msg, extracted=done, failed=failed, validation=v["summary"])


def _persist_statement(conn, f: dict, grid, s_no: int) -> None:
    x = extract_statement(grid, f"S-{s_no}", config.RECON_TOLERANCE)
    ov = db.loads(f["override_json"], {})
    vals = _statement_meta_values(conn, f, ov, s_no)
    lh = x["letterhead"]
    sid = db.insert(conn, "statement", dict(
        source_file_id=f["id"], batch_id=f["batch_id"], s_no=vals[0], dist_no=vals[1],
        category_code=vals[2], category=vals[3], section=vals[4], schema=x["schema"],
        society_code=vals[5], society=vals[6], country=vals[7], p_start=vals[8], p_end=vals[9],
        fy=vals[10], period=vals[11], stmt_date=vals[12], redistribution=int(vals[2] == "redistribution"),
        member_no=lh["member_no"], member_name=lh["member_name"], ipi_name=lh["ipi_name"],
        ipi_base=lh["ipi_base"], file_total=x["file_total"], extracted_total=x["extracted_total"],
        subtotal_total=x["subtotal_total"], subtotal_lines=x["subtotal_lines"],
        line_count=len(x["lines"]), block_count=len(x["blocks"]), work_count=x["work_count"],
        recon_diff=x["recon_diff"], reconciled=int(x["reconciled"]), checks_json=db.dumps(x["checks"]),
        header_row=x["header_row"], stop_row=x["stop_row"], footer_json=db.dumps(x["footer"])))
    block_ids = {}
    for b in x["blocks"]:
        block_ids[b["ordinal"]] = db.insert(conn, "statement_block", dict(
            statement_id=sid, ordinal=b["ordinal"], sheet_row=b["sheet_row"], work_no=b["work_no"],
            raw_no=b["raw_no"], synthetic=int(b["synthetic"]), title=b["title"],
            name_key=norm(b["title"]), av=b["av"], language=b["language"], amount=b["amount"],
            money_lines=b["money_lines"]))
    conn.executemany(
        "INSERT INTO royalty_line(statement_id, block_id, sheet_row, work_no, party, role, society, "
        "own, coll, pool, source, buckets_json, amount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(sid, block_ids[ln["block"]], ln["sheet_row"], ln["work_no"], ln["party"], ln["role"],
          ln["society"], ln["own"], ln["coll"], ln["pool"], ln["source"],
          db.dumps(ln["buckets"]) if ln["buckets"] else None, ln["amount"]) for ln in x["lines"]])
    for a in x["anomalies"]:
        db.insert(conn, "ingest_anomaly", dict(source_file_id=f["id"], kind=a["kind"],
                                               sheet_row=a["sheet_row"], detail=a["detail"]))


def sheet_label(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"^\(S-\d+\)\s*", "", stem).strip() or stem


def _persist_sheet(conn, f: dict, grid, kind: str) -> None:
    if kind == sniff.CATALOGUE:
        prop = catalogue_mapping(grid)
        status = "confirmed"
    else:
        prop = user_sheet_proposal(grid)
        status = "proposed"
        prev = db.row(conn, "SELECT us.id FROM user_sheet us WHERE us.header_fp = ? AND "
                            "us.mapping_status = 'confirmed' ORDER BY us.id DESC LIMIT 1",
                      (prop["fingerprint"],))
        if prev:                                             # confirmed map reused by fingerprint
            cm = db.rows(conn, "SELECT field, col_index, confidence FROM user_sheet_column_map "
                               "WHERE sheet_id = ?", (prev["id"],))
            prop["mapping"] = {m["field"]: dict(col_index=m["col_index"], confidence=m["confidence"],
                                                header=prop["header"][m["col_index"]]
                                                if m["col_index"] < len(prop["header"]) else "")
                               for m in cm}
            status = "confirmed"
    sid = db.insert(conn, "user_sheet", dict(
        source_file_id=f["id"], batch_id=f["batch_id"], label=sheet_label(f["filename"]),
        s_no=parse_s_no(f["filename"]), header_fp=prop["fingerprint"], header_row=prop["header_row"],
        header_json=db.dumps(prop["header"]), proposal_json=db.dumps(prop), row_count=0,
        is_catalogue=int(kind == sniff.CATALOGUE), mapping_status=status, created_at=db.now()))
    for field, m in prop["mapping"].items():
        conn.execute("INSERT INTO user_sheet_column_map(sheet_id, field, col_index, confidence, "
                     "confirmed_by) VALUES (?,?,?,?,?)",
                     (sid, field, m["col_index"], m["confidence"],
                      "system" if status == "confirmed" else None))
    load_sheet_entries(conn, sid, grid, prop["header_row"], prop["mapping"])


def load_sheet_entries(conn, sheet_id: int, grid, header_row: int, mapping: dict) -> int:
    conn.execute("DELETE FROM user_sheet_entry WHERE sheet_id = ?", (sheet_id,))
    entries = load_entries(grid, header_row, mapping)
    for e in entries:
        eid = db.insert(conn, "user_sheet_entry", dict(
            sheet_id=sheet_id, ordinal=e["ordinal"], sheet_row=e["sheet_row"], name=e["name"],
            name_key=e["name_key"], raw_no=e["raw_no"], amount=e["amount"], period=e["period"]))
        conn.executemany("INSERT INTO user_sheet_entry_work(entry_id, work_no, ordinal) VALUES (?,?,?)",
                         [(eid, n, j) for j, n in enumerate(e["work_nos"])])
        conn.executemany("INSERT INTO user_sheet_entry_isrc(entry_id, isrc, ordinal) VALUES (?,?,?)",
                         [(eid, i, j) for j, i in enumerate(e["isrcs"])])
    conn.execute("UPDATE user_sheet SET row_count = ? WHERE id = ?", (len(entries), sheet_id))
    return len(entries)


def confirm_mapping(conn, sheet_id: int, mapping: dict[str, int | None], user: str | None) -> dict:
    """Operator confirms or overrides the proposed column map; entries are reloaded."""
    sh = db.row(conn, "SELECT us.*, sf.stored_path FROM user_sheet us JOIN source_file sf ON "
                      "sf.id = us.source_file_id WHERE us.id = ?", (sheet_id,))
    if not sh:
        raise KeyError(sheet_id)
    clean = {f: int(c) for f, c in mapping.items() if c is not None and c != ""}
    bad = [f for f in clean if f not in sniff.FIELDS]
    if bad:
        raise ValueError(f"unknown field(s): {bad}")
    if not any(f in clean for f in sniff.IDENTITY_FIELDS):
        raise ValueError("at least one identity column (song name, internal number or ISRC) is required")
    current = {r["field"]: r["col_index"] for r in db.rows(
        conn, "SELECT field, col_index FROM user_sheet_column_map WHERE sheet_id = ?", (sheet_id,))}
    if current == clean:                                  # same map: confirming changes no entry
        with db.tx(conn):
            conn.execute("UPDATE user_sheet_column_map SET confirmed_by = ? WHERE sheet_id = ?",
                         (user or "operator", sheet_id))
            conn.execute("UPDATE user_sheet SET mapping_status = 'confirmed' WHERE id = ?", (sheet_id,))
        return dict(sheet_id=sheet_id, entries=sh["row_count"])
    why = sheet_in_use(conn, sheet_id)
    if why:
        raise ValueError(f"{why}; to map it differently, upload the file again into a new batch")
    _title, grid = read_grid(open(sh["stored_path"], "rb").read())
    prop = db.loads(sh["proposal_json"], {})
    confs = {f: m.get("confidence", 1.0) for f, m in prop.get("mapping", {}).items()}
    with db.tx(conn):
        conn.execute("DELETE FROM user_sheet_column_map WHERE sheet_id = ?", (sheet_id,))
        for f, c in clean.items():
            conn.execute("INSERT INTO user_sheet_column_map(sheet_id, field, col_index, confidence, "
                         "confirmed_by) VALUES (?,?,?,?,?)",
                         (sheet_id, f, c, confs.get(f, 1.0) if prop.get("mapping", {}).get(f, {}).get(
                             "col_index") == c else 1.0, user or "operator"))
        n = load_sheet_entries(conn, sheet_id, grid, sh["header_row"],
                               {f: dict(col_index=c) for f, c in clean.items()})
        conn.execute("UPDATE user_sheet SET mapping_status = 'confirmed' WHERE id = ?", (sheet_id,))
    return dict(sheet_id=sheet_id, entries=n)


def _persist_platform(conn, f: dict, grid, kind: str) -> None:
    x = extract_platform(grid, kind)
    rid = db.insert(conn, "platform_report", dict(
        source_file_id=f["id"], batch_id=f["batch_id"],
        kind="REVENUE" if kind == sniff.PLATFORM_REVENUE else "USAGE", client=x["client"],
        label=sheet_label(f["filename"]), month_from=x["months"][0] if x["months"] else None,
        month_to=x["months"][-1] if x["months"] else None, line_count=len(x["lines"]),
        isrc_count=x["isrc_count"], total=x["total"]))
    conn.executemany(
        "INSERT INTO platform_line(report_id, ordinal, sheet_row, month, isrc, content_name, album, upc, "
        "content_type, value) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(rid, ln["ordinal"], ln["sheet_row"], ln["month"], ln["isrc"], ln["content_name"], ln["album"],
          ln["upc"], ln["content_type"], ln["value"]) for ln in x["lines"]])
    if x["skipped"]:
        db.insert(conn, "ingest_anomaly", dict(source_file_id=f["id"], kind="skipped_lines", sheet_row=None,
                                               detail=f"{x['skipped']} line(s) without ISRC or month skipped"))


# ------------------------------------------------------------------ validation (S2 reconciliation)
def validation(conn, batch_id: int) -> dict:
    sts = db.rows(conn, "SELECT st.*, sf.filename FROM statement st JOIN source_file sf ON "
                        "sf.id = st.source_file_id WHERE st.batch_id = ? ORDER BY st.s_no", (batch_id,))
    out = []
    for st in sts:
        checks = db.loads(st["checks_json"], {})
        out.append(dict(
            statement_id=st["id"], source_file_id=st["source_file_id"], s_no=st["s_no"],
            sheet=f"S-{st['s_no']}", file=st["filename"], category=st["category"],
            section=st["section"], dist_no=st["dist_no"] or "Not specified", schema=st["schema"],
            period=st["period"], stmt_date=st["stmt_date"], lines=st["line_count"],
            works=st["work_count"], blocks=st["block_count"], extracted=st["extracted_total"],
            printed=st["file_total"], subtotal=st["subtotal_total"], subtotal_lines=st["subtotal_lines"],
            difference=st["recon_diff"], result="PASS" if st["reconciled"] else "FAIL", checks=checks,
            anomalies=db.rows(conn, "SELECT kind, sheet_row, detail FROM ingest_anomaly WHERE "
                                    "source_file_id = ?", (st["source_file_id"],)),
            footer=db.loads(st["footer_json"], None)))
    passed = sum(1 for x in out if x["result"] == "PASS")
    total = round(sum(round(x["extracted"], 2) for x in out), 2)
    printed = round(sum(round(x["printed"] or 0, 2) for x in out), 2)
    return dict(rows=out, **{"pass": passed, "fail": len(out) - passed},
                summary=dict(statements=len(out), passed=passed, failed=len(out) - passed,
                             extracted_total=total, printed_total=printed,
                             standard=sum(1 for x in out if x["schema"] == "Standard"),
                             overseas=sum(1 for x in out if x["schema"] == "Overseas"),
                             lines=sum(x["lines"] for x in out)))


def section_order_key(section: str):
    return (0, SECTION_ORDER.index(section)) if section in SECTION_ORDER else (1, section)
