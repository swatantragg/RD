"""Who may do what, for which client - checked on the server for every request, then enforced again by the
database (row-level security on app.client_ids). The screen only hides what the server already refuses.

There are exactly three roles (app_user.role):
  USER         every normal operational task: catalogue, statements, master view, reconciliation, exports, enquiry
               drafts, reports
  ADMIN        a User's work, plus accounts (Users and Admins, never the Super Admin), follow-up assignment, mapping
               verification, enquiry approval and closure, processing monitoring
  SUPER_ADMIN  an Admin's work, plus password resets, the administrative and security log, application settings
               (the reference benchmark and the client interest) and deleting all of a client's statements or its
               catalogue
Workflow duties (reviewing an enquiry, owning a follow-up) are assigned to people, not to extra roles.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .. import db
from ..security import Forbidden

SUPER_ADMIN, ADMIN, USER = "SUPER_ADMIN", "ADMIN", "USER"
ROLE_LABEL = {SUPER_ADMIN: "Super Admin", ADMIN: "Admin", USER: "User"}
ALL = (SUPER_ADMIN, ADMIN, USER)
ADMINS = (SUPER_ADMIN, ADMIN)

CAN = {
    "view": ALL,
    "prepare": ALL,                      # upload, import, process, reconcile, review, publish, export, draft enquiries
    "draft_download": ALL,
    "clients": ADMINS,                   # add a client, change its settings, switch it off
    "manage": ADMINS,                    # accounts (people.py adds the Super Admin rules)
    "diagnostics": ADMINS,               # failed processing, jobs, rule set
    "platforms": ADMINS,                 # platform names and the source spellings that mean them
    "verify_mappings": ADMINS,           # verify, reject or correct an ISRC-to-work link
    "approve_enquiries": ADMINS,         # approve or return an enquiry draft, record the manual sending
    "assign_followups": ADMINS,          # assign follow-ups and set their dates
    "close_enquiries": ADMINS,           # close an enquiry once its resolution is verified
    "audit": (SUPER_ADMIN,),             # administrative activity and security log
    "reset_passwords": (SUPER_ADMIN,),
    "settings": (SUPER_ADMIN,),          # reference benchmark, client interest, IPRS currency
    "clear_statements": (SUPER_ADMIN,),  # delete every statement of a client to start fresh (catalogue kept)
    "clear_catalogue": (SUPER_ADMIN,),   # delete a client's catalogue to start fresh (statements kept)
}
WHY = {"prepare": "your account cannot change data",
       "draft_download": "draft reports can only be downloaded by the people preparing them",
       "clients": "adding or changing clients needs an Admin",
       "manage": "only an Admin can manage accounts",
       "diagnostics": "technical details are for Admins",
       "platforms": "only an Admin can change platform names",
       "verify_mappings": "only an Admin can verify or correct a catalogue link",
       "approve_enquiries": "only an Admin can approve an enquiry or record that it was sent",
       "assign_followups": "only an Admin can assign follow-ups or change their dates",
       "close_enquiries": "only an Admin can close an enquiry",
       "audit": "the administrative activity log is for the Super Admin",
       "reset_passwords": "only the Super Admin can reset passwords",
       "settings": "only the Super Admin can change application settings",
       "clear_statements": "only the Super Admin can delete all statements",
       "clear_catalogue": "only the Super Admin can delete the catalogue"}


def role(actor: dict) -> str:
    return actor.get("role") or (actor.get("roles") or [USER])[0]


def can(actor: dict, what: str) -> bool:
    return role(actor) in CAN[what]


def require(actor: dict, what: str) -> None:
    if not can(actor, what):
        raise Forbidden(WHY.get(what, "you do not have access to this"))


def client_ids(conn, actor: dict) -> list[int]:
    """Admins and the Super Admin see every client; a User sees the clients granted to them."""
    if role(actor) in ADMINS:
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


def assignee(conn, user_id) -> int | None:
    """The person work is given to: an active account (None = nobody). A missing or switched-off account is refused
    with a plain message - work never goes to someone who cannot sign in."""
    if user_id in (None, ""):
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise ValueError("Choose a person from the list.") from None
    if not db.scalar(conn, "SELECT id FROM app_user WHERE id = %s AND active AND deleted_at IS NULL", (uid,)):
        raise ValueError("Choose an active person: this account does not exist or is switched off.")
    return uid
