"""Accounts: who may create, change, switch off, delete and reset whom.

  ADMIN        creates Users and Admins; changes, switches off and deletes other Users and Admins; assigns clients.
               Never touches the Super Admin, never creates one, never resets passwords.
  SUPER_ADMIN  everything an Admin does, plus password resets (a temporary password that must be changed at the next
               sign-in; sessions are revoked) and signing an account out everywhere.
Nobody changes their own role, switches themselves off or deletes themselves here. The database guard
(super_admin_guard) refuses anything that would remove, demote or duplicate the Super Admin, even if this code were
wrong. Accounts are soft-deleted, so every recorded action keeps its person. Passwords are never shown or logged; a
generated temporary password is returned once, to the person who set it.
"""
from __future__ import annotations

import re

from . import audit, db, security
from .normalize import s
from .rd import access
from .rd.access import ADMIN, SUPER_ADMIN, USER
from .security import Forbidden

EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ASSIGNABLE = (USER, ADMIN)          # the Super Admin is never created or assigned through the application


class PeopleError(ValueError):
    pass


def _state(u: dict, clients: list[int] | None = None) -> dict:
    """What the audit log records about an account (never the password hash)."""
    out = dict(email=u["email"], name=u["name"], role=u["role"], active=u["active"],
               deleted=u.get("deleted_at") is not None)
    if clients is not None:
        out["clients"] = sorted(clients)
    return out


def _grants(conn, uid: int) -> list[int]:
    return [r["client_id"] for r in db.all(conn, "SELECT client_id FROM client_grant WHERE user_id = %s", (uid,))]


def _clients(conn, v) -> list[int]:
    """The clients granted to a User: existing clients only, each once (a wrong id is refused, not a server error)."""
    if v in (None, ""):
        return []
    if not isinstance(v, list):
        raise PeopleError("Choose the clients from the list.")
    try:
        ids = sorted({int(c) for c in v if not isinstance(c, bool)})
    except (TypeError, ValueError):
        raise PeopleError("Choose the clients from the list.") from None
    known = {r["id"] for r in db.all(conn, "SELECT id FROM client WHERE id = ANY(%s)", (ids,))}
    if set(ids) - known:
        raise PeopleError("One of the chosen clients does not exist.")
    return ids


def _person(conn, uid: int) -> dict:
    u = db.one(conn, "SELECT * FROM app_user WHERE id = %s", (uid,))
    if not u or u["deleted_at"] is not None:
        raise PeopleError("This account does not exist.")
    return u


def _may_change(actor: dict, u: dict) -> None:
    if u["id"] == actor["id"]:
        raise Forbidden("You cannot change your own role, switch yourself off or delete yourself. Use My profile for "
                        "your name and password.")
    if u["role"] == SUPER_ADMIN:
        raise Forbidden("The Super Admin account cannot be changed, switched off or deleted.")


def _flags(actor: dict, u: dict) -> dict:
    other = u["id"] != actor["id"] and u["role"] != SUPER_ADMIN and u["deleted_at"] is None
    return dict(can_edit=other, can_switch=other, can_delete=other,
                can_reset_password=other and access.can(actor, "reset_passwords"),
                can_revoke_sessions=other and access.can(actor, "reset_passwords"))


def list_people(actor: dict, include_deleted: bool = False) -> dict:
    access.require(actor, "manage")
    with db.tx() as conn:
        rows = db.all(conn, "SELECT u.id, u.email, u.name, u.role, u.active, u.deleted_at, u.must_change_password, "
                            "u.last_login_at, u.created_at, c.name AS created_by_name, coalesce(array_agg(g.client_id) "
                            "FILTER (WHERE g.client_id IS NOT NULL), '{}') AS clients FROM app_user u "
                            "LEFT JOIN app_user c ON c.id = u.created_by LEFT JOIN client_grant g ON g.user_id = u.id "
                            "WHERE %(all)s OR u.deleted_at IS NULL GROUP BY u.id, c.name "
                            "ORDER BY (u.role = 'SUPER_ADMIN') DESC, u.deleted_at NULLS FIRST, lower(u.name)",
                      {"all": include_deleted})
    for r in rows:
        r["role_label"] = access.ROLE_LABEL[r["role"]]
        r.update(_flags(actor, r))
        r["deleted"] = r.pop("deleted_at") is not None
    return dict(people=rows, roles=[dict(value=k, label=access.ROLE_LABEL[k]) for k in ASSIGNABLE],
                can_reset_passwords=access.can(actor, "reset_passwords"))


def create_person(actor: dict, body: dict) -> dict:
    access.require(actor, "manage")
    email, name, role = s(body.get("email")).lower(), s(body.get("name")), s(body.get("role")).upper() or USER
    if role not in ASSIGNABLE:
        raise Forbidden("New accounts are Users or Admins. There is only one Super Admin.")
    if not name or len(name) > 120:
        raise PeopleError("Please enter the person's name.")
    if not EMAIL_RX.match(email) or len(email) > 200:
        raise PeopleError("Please enter a valid email address.")
    pw = body.get("password") or ""
    generated = not pw
    if generated:
        pw = security.temporary_password()
    elif len(pw) < security.PASSWORD_MIN:
        raise PeopleError(f"The first password must be at least {security.PASSWORD_MIN} characters.")
    from .seed import create_user
    with db.tx() as conn:
        if db.scalar(conn, "SELECT id FROM app_user WHERE email = %s", (email,)):
            raise PeopleError("An account with this email already exists.")
        uid = create_user(conn, email, name, role, pw, created_by=actor["id"], must_change_password=True)
        clients = _clients(conn, body.get("clients")) if role == USER else []
        for cid in clients:
            conn.execute("INSERT INTO client_grant (user_id, client_id, granted_by) VALUES (%s, %s, %s) "
                         "ON CONFLICT DO NOTHING", (uid, cid, actor["id"]))
        u = db.one(conn, "SELECT * FROM app_user WHERE id = %s", (uid,))
        audit.record(conn, "user.created", actor, "app_user", uid, dict(temporary_password=True),
                     after=_state(u, clients))
    return dict(id=uid, temporary_password=pw if generated else None,
                message=f"{name} can now sign in. They will be asked to choose their own password first.")


def update_person(actor: dict, uid: int, body: dict) -> dict:
    access.require(actor, "manage")
    with db.tx() as conn:
        u = _person(conn, uid)
        _may_change(actor, u)
        before = _state(u, _grants(conn, uid))
        vals: dict = {}
        if "name" in body:
            name = s(body.get("name"))
            if not name or len(name) > 120:
                raise PeopleError("Please enter the person's name.")
            vals["name"] = name
        if "role" in body:
            role = s(body.get("role")).upper()
            if role not in ASSIGNABLE:
                raise Forbidden("Accounts can be Users or Admins. Nobody can be made Super Admin here.")
            vals["role"] = role
        if "active" in body:
            if not isinstance(body["active"], bool):
                raise PeopleError("Say whether the account is switched on or off.")
            vals["active"] = body["active"]
        if vals:
            db.update(conn, "app_user", uid, vals)
            conn.execute("UPDATE app_user SET updated_at = now() WHERE id = %s", (uid,))
        if vals.get("active") is False or ("role" in vals and vals["role"] != u["role"]):
            security.revoke_all(conn, uid)                   # a switched-off or re-roled account signs in again
        if "clients" in body:
            granted = _clients(conn, body.get("clients"))
            conn.execute("DELETE FROM client_grant WHERE user_id = %s", (uid,))
            for cid in granted:
                conn.execute("INSERT INTO client_grant (user_id, client_id, granted_by) VALUES (%s, %s, %s)",
                             (uid, int(cid), actor["id"]))
        after_u = db.one(conn, "SELECT * FROM app_user WHERE id = %s", (uid,))
        after = _state(after_u, _grants(conn, uid))
        if before["role"] != after["role"]:
            audit.record(conn, "user.role_changed", actor, "app_user", uid, dict(email=u["email"]),
                         before=dict(role=before["role"]), after=dict(role=after["role"]))
        if before["active"] != after["active"]:
            audit.record(conn, "user.deactivated" if not after["active"] else "user.reactivated", actor, "app_user",
                         uid, dict(email=u["email"]))
        if before.get("clients") != after.get("clients") or before["name"] != after["name"]:
            audit.record(conn, "user.updated", actor, "app_user", uid, dict(email=u["email"]), before=before,
                         after=after)
    return dict(ok=True)


def delete_person(actor: dict, uid: int) -> dict:
    """Soft delete: the account can no longer sign in and disappears from the lists; its recorded work keeps its name."""
    access.require(actor, "manage")
    with db.tx() as conn:
        u = _person(conn, uid)
        _may_change(actor, u)
        conn.execute("UPDATE app_user SET active = FALSE, deleted_at = now(), deleted_by = %s, updated_at = now() "
                     "WHERE id = %s", (actor["id"], uid))
        security.revoke_all(conn, uid)
        audit.record(conn, "user.deleted", actor, "app_user", uid, dict(email=u["email"]),
                     before=_state(u), after=dict(_state(u), active=False, deleted=True))
    return dict(ok=True, message=f"{u['name']}'s account was deleted. Their recorded work keeps their name.")


def reset_password(actor: dict, uid: int, body: dict) -> dict:
    """The Super Admin issues a temporary password. Existing passwords are never shown (only hashes are stored)."""
    access.require(actor, "reset_passwords")
    pw = body.get("temporary_password") or ""
    generated = not pw
    if generated:
        pw = security.temporary_password()
    elif len(pw) < security.PASSWORD_MIN:
        raise PeopleError(f"A temporary password must be at least {security.PASSWORD_MIN} characters.")
    with db.tx() as conn:
        u = _person(conn, uid)
        _may_change(actor, u)
        conn.execute("UPDATE app_user SET password_hash = %s, must_change_password = TRUE, updated_at = now() "
                     "WHERE id = %s", (security.hash_password(pw), uid))
        security.revoke_all(conn, uid)
        audit.record(conn, "security.password_reset", actor, "app_user", uid,
                     dict(email=u["email"], sessions_revoked=True, generated=generated))
    return dict(ok=True, temporary_password=pw if generated else None,
                message=f"{u['name']} must choose a new password at the next sign-in. They were signed out everywhere.")


def revoke_sessions(actor: dict, uid: int) -> dict:
    access.require(actor, "reset_passwords")
    with db.tx() as conn:
        u = _person(conn, uid)
        _may_change(actor, u)
        n = db.scalar(conn, "SELECT count(*) FROM app_session WHERE user_id = %s AND revoked_at IS NULL "
                            "AND expires_at > now()", (uid,))
        security.revoke_all(conn, uid)
        audit.record(conn, "security.sessions_revoked", actor, "app_user", uid, dict(email=u["email"], sessions=n))
    return dict(ok=True, message=f"{u['name']} was signed out of {n} session{'s' if n != 1 else ''}.")


AUDIT_AREAS = {
    "accounts": ["user", "auth", "security"],
    "catalogue": ["catalogue", "mapping"],
    "statements": ["statement", "file"],
    "reconciliation": ["recon"],
    "enquiries": ["enquiry"],
    "settings": ["settings", "platform", "client"],
    "reports": ["run", "build", "report", "review", "decision"],
    "exports": ["export"],
}


def audit_log(actor: dict, area: str | None = None, q: str | None = None, before: int | None = None,
              limit: int = 200) -> dict:
    """The administrative activity and security log (Super Admin). The chain check proves nothing was edited."""
    access.require(actor, "audit")
    with db.tx() as conn:
        events = audit.recent(conn, limit=min(500, max(1, limit)), before_id=before,
                              prefixes=AUDIT_AREAS.get(area or ""), q=q or None)
        chain = audit.verify_chain(conn) if before is None else None
        people = {r["id"]: r["name"] for r in db.all(conn, "SELECT id, name FROM app_user")}
    for e in events:
        e["detail"] = {k: v for k, v in (e["detail"] or {}).items() if "password" not in k.lower()
                       or k == "temporary_password"}
    return dict(events=events, chain=chain, areas=list(AUDIT_AREAS), people=people)
