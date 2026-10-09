"""Audit log: append-only, each event chained to the one before by sha256 (computed by the database trigger)."""
from __future__ import annotations

from . import db


def record(conn, action: str, actor: dict | None = None, object_kind: str | None = None, object_id=None,
           detail: dict | None = None) -> None:
    db.insert(conn, "audit_event", dict(id=0, at="now", actor_id=(actor or {}).get("id"),
                                        actor=(actor or {}).get("email") or (actor or {}).get("name") or "system",
                                        action=action, object_kind=object_kind,
                                        object_id=None if object_id is None else str(object_id),
                                        detail=detail or {}, prev_hash="", hash=""), returning=None)


def recent(conn, limit: int = 300, before_id: int | None = None, kind: str | None = None) -> list[dict]:
    return db.all(conn, "SELECT id, at, actor, action, object_kind, object_id, detail, hash FROM audit_event "
                        "WHERE (%(b)s::BIGINT IS NULL OR id < %(b)s) AND (%(k)s::TEXT IS NULL OR object_kind = %(k)s) "
                        "ORDER BY id DESC LIMIT %(n)s", dict(b=before_id, k=kind, n=limit))


def verify_chain(conn) -> dict:
    """Recompute every link: an edit, deletion or out-of-order insertion breaks it."""
    rows = db.all(conn, "SELECT id, hash, prev_hash, encode(sha256(convert_to(audit_canon(e), 'UTF8')), 'hex') AS "
                        "recomputed, lag(hash) OVER (ORDER BY id) AS prev_actual FROM audit_event e ORDER BY id")
    bad = [r["id"] for r in rows if r["recomputed"] != r["hash"] or r["prev_hash"] != (r["prev_actual"] or "0" * 64)]
    return dict(events=len(rows), broken=bad[:20], ok=not bad)
