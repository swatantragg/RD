"""Accounts, the administrative activity log and platform names (people.py and rd/platforms.py hold the rules)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends

from .. import db, maintenance, people
from ..rd import access, platforms
from .deps import J, actor

router = APIRouter()


@router.get("/people")
def list_people(include_deleted: bool = False, a: dict = Depends(actor)):
    return J(people.list_people(a, include_deleted))


@router.post("/people")
def add_person(body: dict = Body(...), a: dict = Depends(actor)):
    return J(people.create_person(a, body))


@router.patch("/people/{uid}")
def update_person(uid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(people.update_person(a, uid, body))


@router.delete("/people/{uid}")
def delete_person(uid: int, a: dict = Depends(actor)):
    return J(people.delete_person(a, uid))


@router.post("/people/{uid}/reset-password")
def reset_password(uid: int, body: dict = Body(default={}), a: dict = Depends(actor)):
    return J(people.reset_password(a, uid, body))


@router.post("/people/{uid}/revoke-sessions")
def revoke_sessions(uid: int, a: dict = Depends(actor)):
    return J(people.revoke_sessions(a, uid))


@router.get("/assignees")
def assignees(a: dict = Depends(actor)):
    """People work can be assigned to (names only)."""
    with db.tx() as conn:
        return J(db.all(conn, "SELECT id, name, role FROM app_user WHERE active AND deleted_at IS NULL ORDER BY name"))


def _clear_client(a: dict, cid: int, what: str = "clear_statements") -> dict:
    access.require(a, what)
    with access.tx(a, cid) as conn:
        c = db.one(conn, "SELECT id, code, name FROM client WHERE id = %s", (cid,))
    if not c:
        raise maintenance.ClearRefused("This client does not exist.")
    return c


@router.get("/clients/{cid}/clear-statements")
def clear_statements_preview(cid: int, a: dict = Depends(actor)):
    """What 'Delete all statements' would remove for this client (nothing is changed)."""
    c = _clear_client(a, cid)
    return J(dict(client=c, counts=maintenance.clear_statements(c["code"], "", dry_run=True, echo=lambda *_: None)))


@router.post("/clients/{cid}/clear-statements")
def clear_statements(cid: int, body: dict = Body(...), a: dict = Depends(actor)):
    """Super Admin only: delete every statement of the client, with its reconciliations, enquiries and processing
    runs, to start fresh. The catalogue, settings, platforms, people and the activity log are kept."""
    c = _clear_client(a, cid)
    if (body.get("confirm") or "").strip().upper() != c["code"].upper():
        raise maintenance.ClearRefused(f"Type the client code {c['code']} to confirm.")
    reason = (body.get("reason") or "").strip() or "Start fresh (Statements page)"
    log = logging.getLogger("mrm.maintenance")
    counts = maintenance.clear_statements(c["code"], reason, actor=a, echo=log.info)
    return J(dict(client=c, counts=counts))


@router.get("/clients/{cid}/clear-catalogue")
def clear_catalogue_preview(cid: int, a: dict = Depends(actor)):
    """What 'Delete catalogue' would remove for this client (nothing is changed)."""
    c = _clear_client(a, cid, "clear_catalogue")
    return J(dict(client=c, counts=maintenance.clear_catalogue(c["code"], "", dry_run=True, echo=lambda *_: None)))


@router.post("/clients/{cid}/clear-catalogue")
def clear_catalogue(cid: int, body: dict = Body(...), a: dict = Depends(actor)):
    """Super Admin only: delete the client's catalogue (works, ISRC links, imports, song lists) with the
    reconciliations and enquiries built on it, to start fresh. Statements and reports are kept."""
    c = _clear_client(a, cid, "clear_catalogue")
    if (body.get("confirm") or "").strip().upper() != c["code"].upper():
        raise maintenance.ClearRefused(f"Type the client code {c['code']} to confirm.")
    reason = (body.get("reason") or "").strip() or "Start the catalogue fresh (Catalogue page)"
    counts = maintenance.clear_catalogue(c["code"], reason, actor=a, echo=logging.getLogger("mrm.maintenance").info)
    return J(dict(client=c, counts=counts))


@router.get("/audit")
def audit_log(area: str | None = None, q: str | None = None, before: int | None = None, a: dict = Depends(actor)):
    return J(people.audit_log(a, area or None, q or None, before))


@router.get("/platforms")
def list_platforms(a: dict = Depends(actor)):
    return J(dict(platforms=platforms.listing(a), can_change=access.can(a, "platforms")))


@router.post("/platforms")
def add_platform(body: dict = Body(...), a: dict = Depends(actor)):
    return J(platforms.add_platform(a, body))


@router.post("/platforms/{pid}/aliases")
def add_alias(pid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(platforms.add_alias(a, pid, body.get("alias") or ""))
