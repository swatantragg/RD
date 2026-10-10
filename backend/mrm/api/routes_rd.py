"""The royalty processing platform: home, clients, processing runs, files, results, review, approval, downloads."""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .. import audit, config, db, security
from ..normalize import s
from ..rd import access, service
from .deps import J, actor

router = APIRouter()


# ------------------------------------------------------------------ home and history
@router.get("/home")
def home(a: dict = Depends(actor)):
    return J(service.home(a))


@router.get("/past-reports")
def past_reports(client_id: int | None = None, a: dict = Depends(actor)):
    return J(service.past_reports(a, client_id))


# ------------------------------------------------------------------ clients
@router.get("/clients")
def clients(a: dict = Depends(actor)):
    return J(service.list_clients(a))


@router.post("/clients")
def create_client(body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.save_client(a, body))


@router.patch("/clients/{cid}")
def update_client(cid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.save_client(a, body, cid))


# ------------------------------------------------------------------ runs and files
@router.get("/runs")
def runs(client_id: int | None = None, a: dict = Depends(actor)):
    return J(service.list_runs(a, client_id, limit=50))


@router.post("/runs")
def create_run(body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.create_run(a, int(body["client_id"]), body.get("title")))


@router.get("/runs/{rid}")
def run(rid: int, a: dict = Depends(actor)):
    return J(service.run_view(a, rid))


@router.post("/runs/{rid}/close")
def close_run(rid: int, a: dict = Depends(actor)):
    service.close_run(a, rid)
    return J({"ok": True})


@router.delete("/runs/{rid}")
def delete_run(rid: int, a: dict = Depends(actor)):
    return J(service.delete_run(a, rid))


@router.post("/runs/{rid}/files")
async def upload(rid: int, files: list[UploadFile] = File(...), a: dict = Depends(actor)):
    access.require(a, "prepare")
    limit = config.settings.max_upload_mb * 1024 * 1024
    out = []
    for f in files:
        data = await f.read(limit + 1)
        name = f.filename or "upload.xlsx"
        if len(data) > limit:
            out.append(dict(filename=name, error=f"This file is larger than {config.settings.max_upload_mb} MB."))
            continue
        try:
            out.append(await run_in_threadpool(service.add_file, a, rid, name, data))
        except service.RDError as e:
            out.append(dict(filename=name, error=str(e)))
    return J(out)


@router.post("/runs/{rid}/files/{fid}/answer")
def answer(rid: int, fid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.answer(a, rid, fid, body.get("answers") or {}))


@router.post("/runs/{rid}/files/{fid}/choice")
def choice(rid: int, fid: int, body: dict = Body(...), a: dict = Depends(actor)):
    service.choose(a, rid, fid, s(body.get("choice")))
    return J(service.run_view(a, rid))


@router.delete("/runs/{rid}/files/{fid}")
def remove(rid: int, fid: int, a: dict = Depends(actor)):
    service.remove_file(a, rid, fid)
    return J(service.run_view(a, rid))


@router.get("/files/{fid}/details")
def file_details(fid: int, a: dict = Depends(actor)):
    return J(service.file_details(a, fid))


@router.post("/runs/{rid}/process")
def process(rid: int, a: dict = Depends(actor)):
    return J(service.start_build(a, rid))


# ------------------------------------------------------------------ results and review
@router.get("/builds/{bid}")
def build(bid: int, a: dict = Depends(actor)):
    return J(service.build_view(a, bid))


@router.get("/builds/{bid}/findings")
def findings(bid: int, status: str | None = None, q: str | None = None, offset: int = 0, a: dict = Depends(actor)):
    return J(service.findings(a, bid, status or None, q or None, offset=offset))


@router.post("/builds/{bid}/issues/{no}/act")
def act(bid: int, no: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.act(a, bid, no, s(body.get("action")), body))


@router.post("/builds/{bid}/findings/status")
def set_status(bid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.set_status(a, bid, [int(x) for x in body.get("findings") or []], s(body.get("status")),
                                body.get("note")))


@router.post("/builds/{bid}/submit")
def submit(bid: int, a: dict = Depends(actor)):
    return J(service.submit(a, bid))


@router.post("/builds/{bid}/approve")
def approve(bid: int, a: dict = Depends(actor)):
    return J(service.approve_build(a, bid))


@router.post("/builds/{bid}/return")
def return_build(bid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(service.return_build(a, bid, s(body.get("reason"))))


@router.get("/approvals")
def approvals(a: dict = Depends(actor)):
    return J(service.approvals(a))


@router.post("/decisions/{did}/approve")
def approve_decision(did: int, body: dict = Body(default={}), a: dict = Depends(actor)):
    return J(service.check_decision(a, did, True, body.get("note")))


@router.post("/decisions/{did}/reject")
def reject_decision(did: int, body: dict = Body(default={}), a: dict = Depends(actor)):
    return J(service.check_decision(a, did, False, body.get("note")))


def _attachment(name: str, data: bytes, media: str) -> Response:
    quoted = urllib.parse.quote(name)
    return Response(data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"{name.encode('ascii', 'replace').decode()}\"; "
                               f"filename*=UTF-8''{quoted}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.get("/reports/{rid}/download")
def download(rid: int, a: dict = Depends(actor)):
    name, data = service.report_file(a, rid)
    return _attachment(name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/builds/{bid}/download-all")
def download_all(bid: int, a: dict = Depends(actor)):
    name, data = service.report_bundle(a, bid)
    return _attachment(name, data, "application/zip")


# ------------------------------------------------------------------ settings: people, access, diagnostics
@router.get("/people")
def people(a: dict = Depends(actor)):
    access.require(a, "manage")
    with db.tx() as conn:
        rows = db.all(conn, "SELECT u.id, u.email, u.name, u.active, u.last_login_at, coalesce(array_agg(DISTINCT r.role) "
                            "FILTER (WHERE r.role IS NOT NULL), '{}') AS roles, coalesce(array_agg(DISTINCT g.client_id) "
                            "FILTER (WHERE g.client_id IS NOT NULL), '{}') AS clients FROM app_user u LEFT JOIN user_role "
                            "r ON r.user_id = u.id LEFT JOIN client_grant g ON g.user_id = u.id GROUP BY u.id "
                            "ORDER BY u.name")
    return J(dict(people=rows, roles=[dict(value=k, label=v) for k, v in access.ROLE_LABEL.items()
                                      if k != "sender"]))


@router.post("/people")
def add_person(body: dict = Body(...), a: dict = Depends(actor)):
    access.require(a, "manage")
    from ..seed import create_user
    roles = [r for r in body.get("roles") or [] if r in security.ROLES]
    email, name, pw = s(body.get("email")).lower(), s(body.get("name")), body.get("password") or ""
    if not email or not name or not roles:
        raise service.RDError("A person needs an email, a name and at least one role.")
    if len(pw) < 10:
        raise service.RDError("The first password must be at least 10 characters.")
    with db.tx() as conn:
        uid = create_user(conn, email, name, roles, pw)
        for cid in body.get("clients") or []:
            conn.execute("INSERT INTO client_grant (user_id, client_id, granted_by) VALUES (%s, %s, %s) ON CONFLICT "
                         "DO NOTHING", (uid, int(cid), a["id"]))
        audit.record(conn, "user.created", a, "app_user", uid, dict(email=email, roles=roles,
                                                                    clients=body.get("clients") or []))
    return J({"id": uid})


@router.patch("/people/{uid}")
def update_person(uid: int, body: dict = Body(...), a: dict = Depends(actor)):
    access.require(a, "manage")
    with db.tx() as conn:
        if "roles" in body:
            roles = [r for r in body["roles"] if r in security.ROLES]
            if uid == a["id"] and "admin" not in roles:
                raise service.RDError("You cannot remove your own administrator role.")
            conn.execute("DELETE FROM user_role WHERE user_id = %s", (uid,))
            for r in roles:
                conn.execute("INSERT INTO user_role (user_id, role) VALUES (%s, %s)", (uid, r))
        if "clients" in body:
            conn.execute("DELETE FROM client_grant WHERE user_id = %s", (uid,))
            for cid in body["clients"]:
                conn.execute("INSERT INTO client_grant (user_id, client_id, granted_by) VALUES (%s, %s, %s)",
                             (uid, int(cid), a["id"]))
        if "active" in body:
            if uid == a["id"] and not body["active"]:
                raise service.RDError("You cannot switch off your own account.")
            conn.execute("UPDATE app_user SET active = %s WHERE id = %s", (bool(body["active"]), uid))
            if not body["active"]:
                conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                             (uid,))
        if s(body.get("password")):
            if len(body["password"]) < 10:
                raise service.RDError("A password must be at least 10 characters.")
            conn.execute("UPDATE app_user SET password_hash = %s WHERE id = %s",
                         (security.hash_password(body["password"]), uid))
        audit.record(conn, "user.updated", a, "app_user", uid,
                     {k: v for k, v in body.items() if k != "password"} | ({"password": "changed"}
                                                                           if body.get("password") else {}))
    return J({"ok": True})


@router.delete("/people/{uid}")
def delete_person(uid: int, a: dict = Depends(actor)):
    """Delete an account that has no recorded work. Anyone who uploaded, prepared, approved or decided something stays
    (switched off), so every report remains traceable to a person."""
    import psycopg
    access.require(a, "manage")
    if uid == a["id"]:
        raise service.RDError("You cannot delete your own account.")
    with db.tx() as conn:
        u = db.one(conn, "SELECT email FROM app_user WHERE id = %s", (uid,))
        if not u:
            raise service.RDError("This person does not exist.")
        try:
            with conn.transaction():
                conn.execute("UPDATE client_grant SET granted_by = NULL WHERE granted_by = %s", (uid,))
                conn.execute("DELETE FROM app_user WHERE id = %s", (uid,))
        except psycopg.errors.ForeignKeyViolation:
            raise service.RDError(f"{u['email']} has uploaded, prepared, approved or decided something, so the account "
                                  "must stay to keep that history traceable. Switch it off instead.") from None
        audit.record(conn, "user.deleted", a, "app_user", uid, dict(email=u["email"]))
    return J({"ok": True})


@router.get("/diagnostics")
def diagnostics(a: dict = Depends(actor)):
    return J(service.diagnostics(a))
