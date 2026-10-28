"""Pop-up notifications (1.7.1): when someone hands a person work - an enquiry assigned to them, a report to confirm, a
follow-up, a reconciliation exception, or a report returned to / confirmed for its preparer - that person sees a pop-up
in the top-right corner (the screen asks every 30 seconds). Opening or dismissing it marks it read. Nobody is notified
of what they did themselves."""
from __future__ import annotations

from .. import db
from . import access

KEEP = 20                                              # unread pop-ups shown at most (the newest)


def send(conn, actor: dict | None, user_id: int | None, client_id: int, kind: str, title: str, body: str | None = None,
         link: str | None = None) -> None:
    """Called inside the transaction that hands over the work."""
    if not user_id or (actor and user_id == actor["id"]):
        return
    db.insert(conn, "notifications", dict(client_id=client_id, user_id=user_id, kind=kind, title=title, body=body,
                                          link=link, created_by=actor["id"] if actor else None), returning=None)


def unread(actor: dict) -> dict:
    with access.tx(actor) as conn:
        rows = db.all(conn, "SELECT n.id, n.kind, n.title, n.body, n.link, n.client_id, n.created_at, u.name AS from_name "
                            "FROM notifications n LEFT JOIN app_user u ON u.id = n.created_by WHERE n.user_id = %s AND "
                            "n.read_at IS NULL ORDER BY n.id DESC LIMIT %s", (actor["id"], KEEP))
        total = db.scalar(conn, "SELECT count(*) FROM notifications WHERE user_id = %s AND read_at IS NULL",
                          (actor["id"],))
    return dict(rows=rows, total=total)


def mark_read(actor: dict, ids: list[int] | None) -> dict:
    """ids None: every unread notification of the person."""
    with access.tx(actor) as conn:
        if ids is None:
            conn.execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL", (actor["id"],))
        elif ids:
            conn.execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL AND id = "
                         "ANY(%s)", (actor["id"], ids))
    return unread(actor)
