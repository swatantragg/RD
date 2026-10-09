"""Sign-in, account creation, sign-out and 'who am I' (roles, what this person can do, which clients they see)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from .. import __version__, audit, config, db, releases, security
from ..normalize import s
from ..rd import access
from .deps import COOKIE, J, Unauthorized, actor

router = APIRouter()


def me_out(a: dict) -> dict:
    with access.tx(a) as conn:
        ids = access.client_ids(conn, a)
        clients = db.all(conn, "SELECT id, code, name FROM client WHERE id = ANY(%s) AND active ORDER BY name", (ids,))
        u = db.one(conn, "SELECT name, seen_version, created_at, last_login_at FROM app_user WHERE id = %s", (a["id"],))
    return dict(id=a["id"], email=a["email"], name=u["name"], roles=a["roles"], csrf=a.get("csrf"),
                role_labels=[access.ROLE_LABEL.get(r, r) for r in a["roles"]],
                can={k: access.can(a, k) for k in access.CAN}, clients=clients,
                member_since=u["created_at"], last_sign_in=u["last_login_at"],
                version=__version__, whats_new=releases.unseen(u["seen_version"]),
                legacy=config.settings.legacy_comparison)


@router.get("/auth/options")
def options():
    """What the sign-in page may offer (no session needed)."""
    return J(dict(signup=config.settings.allow_signup, version=__version__))


EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/auth/signup")
def signup(request: Request, body: dict = Body(...)):
    """Create an account. The first account on an installation becomes the Administrator (and may prepare reports);
    every later account is a Viewer: it sees everyone's work and downloads published reports. An Administrator can
    give more rights in Settings."""
    if not config.settings.allow_signup:
        return JSONResponse({"detail": "Creating accounts is switched off here. Ask your administrator for an account."},
                            status_code=403)
    name, email, password = s(body.get("name")), s(body.get("email")).lower(), body.get("password") or ""
    if not name or len(name) > 120:
        raise ValueError("Please enter your name.")
    if not EMAIL_RX.match(email) or len(email) > 200:
        raise ValueError("Please enter a valid email address.")
    if len(password) < 10:
        raise ValueError("The password must be at least 10 characters long.")
    if password.lower() in (email, name.lower()):
        raise ValueError("Please choose a password that is not your name or email.")
    from ..seed import create_user
    with db.tx() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(84726200)")          # two first sign-ups cannot both be admin
        if db.scalar(conn, "SELECT id FROM app_user WHERE email = %s", (email,)):
            return JSONResponse({"detail": "An account with this email already exists. Please sign in."},
                                status_code=409)
        first = not db.scalar(conn, "SELECT count(*) FROM app_user u JOIN user_role r ON r.user_id = u.id "
                                    "WHERE u.active AND r.role = 'admin'")
        roles = ["admin", "importer"] if first else ["viewer"]
        uid = create_user(conn, email, name, roles, password)
        audit.record(conn, "auth.signed_up", dict(id=uid, email=email), "app_user", uid, dict(roles=roles))
    return login(request, dict(email=email, password=password))


@router.post("/auth/login")
def login(request: Request, body: dict = Body(...)):
    email, password = s(body.get("email")).lower(), body.get("password") or ""
    with db.tx() as conn:
        fails = db.scalar(conn, "SELECT count(*) FROM login_attempt WHERE email = %s AND NOT ok AND at > now() - "
                                "interval '15 minutes'", (email,))
        if fails >= config.settings.login_max_failures:
            return JSONResponse({"detail": "Too many failed sign-ins. Please wait 15 minutes and try again."},
                                status_code=429)
        u = db.one(conn, "SELECT * FROM app_user WHERE email = %s", (email,))
        ok = bool(u and u["active"] and security.check_password(password, u["password_hash"]))
        db.insert(conn, "login_attempt", dict(email=email, ok=ok), returning=None)
        if not ok:
            audit.record(conn, "auth.failed", None, "app_user", None, dict(email=email))
    if not ok:
        raise Unauthorized("The email or password was not recognised.")
    with db.tx() as conn:
        token, csrf, expires = security.new_session(conn, u["id"])
        conn.execute("UPDATE app_user SET last_login_at = now() WHERE id = %s", (u["id"],))
        audit.record(conn, "auth.signed_in", dict(id=u["id"], email=u["email"]), "app_user", u["id"])
    a = security.load_session(token)
    resp = J(me_out(a))
    secure = config.settings.cookie_secure == "true" or (config.settings.cookie_secure == "auto" and
                                                         request.url.scheme == "https")
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=secure, path="/",
                    expires=expires.strftime("%a, %d %b %Y %H:%M:%S GMT"))
    return resp


@router.post("/auth/logout")
def logout(request: Request):
    tok = request.cookies.get(COOKIE)
    if tok:
        security.revoke_session(tok)
    resp = J({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/auth/me")
def me(a: dict = Depends(actor)):
    return J(me_out(a))


@router.post("/me/seen")
def seen(a: dict = Depends(actor)):
    """The 'what's new' note was read: it is not shown again to this person, on any browser."""
    with db.tx() as conn:
        conn.execute("UPDATE app_user SET seen_version = %s WHERE id = %s", (__version__, a["id"]))
    return J({"ok": True})


@router.patch("/me")
def update_me(body: dict = Body(...), a: dict = Depends(actor)):
    """My profile: change the display name, or the password (the current password is needed)."""
    changed = []
    with db.tx() as conn:
        if "name" in body:
            name = s(body.get("name"))
            if not name or len(name) > 120:
                raise ValueError("Please enter your name.")
            conn.execute("UPDATE app_user SET name = %s WHERE id = %s", (name, a["id"]))
            changed.append("name")
        if body.get("new_password"):
            new = body["new_password"]
            u = db.one(conn, "SELECT password_hash FROM app_user WHERE id = %s", (a["id"],))
            if not security.check_password(body.get("current_password") or "", u["password_hash"]):
                raise ValueError("Your current password is not right.")
            if len(new) < 10:
                raise ValueError("The new password must be at least 10 characters long.")
            if "confirm_password" in body and body["confirm_password"] != new:
                raise ValueError("The two new passwords are not the same.")
            conn.execute("UPDATE app_user SET password_hash = %s WHERE id = %s", (security.hash_password(new), a["id"]))
            conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL AND "
                         "csrf <> %s", (a["id"], a.get("csrf") or ""))          # other signed-in browsers sign out
            changed.append("password")
        audit.record(conn, "user.profile_updated", a, "app_user", a["id"], dict(changed=changed))
    return J(me_out(a))                                   # me_out reads the saved name back
