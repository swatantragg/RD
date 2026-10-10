"""Who may do what, for which client - checked on the server for every request, then enforced again by the
database (row-level security on app.client_ids). The screen only hides what the server already refuses."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .. import db
from ..security import Forbidden

ROLE_LABEL = {"admin": "Administrator", "importer": "Preparer", "rights_reviewer": "Reviewer",
              "accounts": "Accounts", "viewer": "Viewer"}

CAN = {
    "view": ("admin", "importer", "rights_reviewer", "accounts", "viewer"),
    "prepare": ("admin", "importer", "rights_reviewer", "accounts"),     # upload, process, review, publish
    "draft_download": ("admin", "importer", "rights_reviewer", "accounts"),
    "clients": ("admin", "importer", "rights_reviewer", "accounts"),     # add a client, edit its settings
    "manage": ("admin",),                                                # people, grants, switching a client off
    "diagnostics": ("admin",),
}
WHY = {"prepare": "preparing reports needs the Preparer role",
       "draft_download": "draft reports can only be downloaded by the people preparing them",
       "clients": "adding or changing clients needs the Preparer or Administrator role",
       "manage": "only an Administrator can do this",
       "diagnostics": "technical details are for Administrators"}


def can(actor: dict, what: str) -> bool:
    return any(r in CAN[what] for r in actor.get("roles", ()))


def require(actor: dict, what: str) -> None:
    if not can(actor, what):
        raise Forbidden(WHY.get(what, "you do not have access to this"))


def client_ids(conn, actor: dict) -> list[int]:
    """Administrators and Viewers see every client (a Viewer follows everyone's work and downloads published reports);
    preparers see the clients they were given."""
    roles = actor.get("roles", ())
    if "admin" in roles or "viewer" in roles:
        return [r["id"] for r in db.all(conn, "SELECT id FROM client ORDER BY id")]
    return [r["client_id"] for r in db.all(conn, "SELECT client_id FROM client_grant WHERE user_id = %s "
                                                 "ORDER BY client_id", (actor["id"],))]


def set_scope(conn, ids: list[int]) -> None:
    conn.execute("SELECT set_config('app.client_ids', %s, true)", (",".join(str(int(i)) for i in ids),))


@contextmanager
def tx(actor: dict | None, client_id: int | None = None) -> Iterator:
    """One transaction scoped to the clients the person may see (or to one system client for background work)."""
    with db.tx() as conn:
        if actor is None:
            set_scope(conn, [client_id] if client_id else [])
        else:
            ids = client_ids(conn, actor)
            if client_id is not None and client_id not in ids:
                raise Forbidden("you do not have access to this client")
            set_scope(conn, ids)
        yield conn


def require_client(conn, actor: dict, client_id: int) -> None:
    if client_id not in client_ids(conn, actor):
        raise Forbidden("you do not have access to this client")
