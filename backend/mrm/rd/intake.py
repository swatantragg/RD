"""Storing an uploaded workbook once per client: safety checks and parsing (detect.identify), the write-once original,
the rd_file row and its parsed lines. Shared by the statement library and the catalogue import; processing runs keep
their own path (service.add_file)."""
from __future__ import annotations

import hashlib

from .. import audit, db, storage
from . import access, detect
from .model import KIND_LABEL, UNKNOWN
from .service import RDError, client_cfg


def safe_filename(filename: str) -> str:
    return "".join(ch for ch in (filename or "") if ch not in "/\\\0")[:200] or "upload.xlsx"


def existing(conn, client_id: int, data: bytes) -> dict | None:
    return db.one(conn, "SELECT * FROM rd_file WHERE client_id = %s AND sha256 = %s",
                  (client_id, hashlib.sha256(data).hexdigest()))


def store(actor: dict, client_id: int, filename: str, data: bytes, allowed: dict[str, str],
          refuse: dict[str, str] | None = None) -> tuple[dict, bool]:
    """-> (rd_file row, already_stored). allowed: kind -> what it is for; refuse: kind -> plain message.

    A file that was stored before (same bytes, same client) is reused, whatever path stored it. A file of another
    kind is refused with a message that says where it belongs, and is not stored."""
    access.require(actor, "prepare")
    name = safe_filename(filename)
    sha = hashlib.sha256(data).hexdigest()
    with access.tx(actor, client_id) as conn:
        f = db.one(conn, "SELECT * FROM rd_file WHERE client_id = %s AND sha256 = %s", (client_id, sha))
        code = db.scalar(conn, "SELECT code FROM client WHERE id = %s", (client_id,))
    if f:
        if f["kind"] not in allowed:
            raise RDError((refuse or {}).get(f["kind"]) or
                          f"This file was uploaded before as a {KIND_LABEL.get(f['kind'], f['kind']).lower()}, "
                          "so it cannot be used here.")
        return f, True
    parsed = detect.identify(name, data)                       # outside any transaction: CPU only
    if parsed.layout in ("REJECTED", "DAMAGED"):
        raise RDError(parsed.problems[0].message if parsed.problems else "We could not read this file.")
    if parsed.kind not in allowed:
        if parsed.kind == UNKNOWN:
            raise RDError("We could not recognise this file. Expected: " + "; ".join(allowed.values()) + ".")
        raise RDError((refuse or {}).get(parsed.kind) or
                      f"This file looks like a {KIND_LABEL.get(parsed.kind, parsed.kind).lower()}, which does not "
                      "belong here. Expected: " + "; ".join(allowed.values()) + ".")
    key = f"{code}/{sha}{'.csv' if name.lower().endswith('.csv') else '.xlsx'}"
    storage.put("originals", key, data)
    with access.tx(actor, client_id) as conn:
        cfg = client_cfg(conn, client_id)
        facts = parsed.summary.get("facts", {})
        ev = detect.evaluate(parsed.kind, facts, name, cfg, None, parsed.summary.get("file_date"))
        fid = db.insert(conn, "rd_file", dict(
            client_id=client_id, sha256=sha, filename=name, bytes=len(data), object_key=key, kind=parsed.kind,
            layout=parsed.layout, why=parsed.why, facts=db.J(facts), status=ev["status"], label=ev["label"],
            meta=db.J(ev["meta"]), meta_source=db.J(ev["meta_source"]), problems=db.J(ev["problems"]),
            summary=db.J(ev.get("summary") or {}), file_date=parsed.summary.get("file_date"),
            uploaded_by=actor["id"]))
        if parsed.data is not None:
            from .store import save_data
            save_data(conn, fid, client_id, parsed.kind, parsed.data)
        audit.record(conn, "file.uploaded", actor, "rd_file", fid, dict(filename=name, sha256=sha, kind=parsed.kind,
                                                                        status=ev["status"], via="library"))
        f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (fid,))
    return f, False


def original(actor: dict, file_id: int) -> tuple[str, bytes]:
    with access.tx(actor) as conn:
        f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (file_id,))
        if not f:
            raise RDError("This file does not exist, or you do not have access to it.")
        data = storage.get("originals", f["object_key"])
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise RDError("The stored original does not match its fingerprint. Please contact your Admin.")
        audit.record(conn, "statement.original_downloaded", actor, "rd_file", file_id, dict(filename=f["filename"]))
    return f["filename"], data
