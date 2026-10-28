"""Sign-in, account creation, sign-out and 'who am I' (roles, what this person can do, which clients they see)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import __version__, audit, config, db, releases, security
from ..normalize import s
from ..rd import access
from .deps import COOKIE, J, Unauthorized, actor, json_body

router = APIRouter()


def me_out(a: dict) -> dict:
    with access.tx(a) as conn:
        ids = access.client_ids(conn, a)
        clients = db.all(conn, "SELECT id, code, name FROM client WHERE id = ANY(%s) AND active ORDER BY name", (ids,))
        u = db.one(conn, "SELECT name, seen_version, created_at, last_login_at, role, must_change_password "
                         "FROM app_user WHERE id = %s", (a["id"],))
    return dict(id=a["id"], email=a["email"], name=u["name"], role=u["role"], roles=[u["role"]], csrf=a.get("csrf"),
                role_label=access.ROLE_LABEL[u["role"]], role_labels=[access.ROLE_LABEL[u["role"]]],
                must_change_password=u["must_change_password"],
                can={k: access.can(a, k) for k in access.CAN}, clients=clients,
                member_since=u["created_at"], last_sign_in=u["last_login_at"],
                version=__version__, whats_new=[] if u["must_change_password"] else releases.unseen(u["seen_version"]))


def _signup_open(conn) -> bool:
    """Self sign-up only sets up a new installation: the first account becomes the Super Admin. After that, Admins
    create accounts (Settings -> People and access)."""
    return config.settings.allow_signup and not db.scalar(
        conn, "SELECT count(*) FROM app_user WHERE role = 'SUPER_ADMIN' AND active AND deleted_at IS NULL")


@router.get("/auth/options")
def options():
    """What the sign-in page may offer (no session needed)."""
    with db.tx() as conn:
        signup = _signup_open(conn)
    return J(dict(signup=signup, version=__version__))


def _text(v) -> str:
    """A password field: text only (a number, list or object sent instead counts as empty)."""
    return v if isinstance(v, str) else ""


EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/auth/signup")
def signup(request: Request, body: dict = Depends(json_body)):
    """Set up a new installation: the first account becomes the Super Admin. Once there is a Super Admin, accounts
    are created by an Admin and this endpoint refuses."""
    name, email, password = s(body.get("name")), s(body.get("email")).lower(), _text(body.get("password"))
    if not name or len(name) > 120:
        raise ValueError("Please enter your name.")
    if not EMAIL_RX.match(email) or len(email) > 200:
        raise ValueError("Please enter a valid email address.")
    if len(password) < security.PASSWORD_MIN:
        raise ValueError(f"The password must be at least {security.PASSWORD_MIN} characters long.")
    if len(password) > security.PASSWORD_MAX:
        raise ValueError(f"The password can have at most {security.PASSWORD_MAX} characters.")
    if password.lower() in (email, name.lower()):
        raise ValueError("Please choose a password that is not your name or email.")
    from ..seed import create_user
    with db.tx() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(84726200)")          # two first sign-ups cannot both be it
        if not _signup_open(conn):
            return JSONResponse({"detail": "Accounts are created by an Admin. Please ask your Admin for an account."},
                                status_code=403)
        if db.scalar(conn, "SELECT id FROM app_user WHERE email = %s", (email,)):
            return JSONResponse({"detail": "An account with this email already exists. Please sign in."},
                                status_code=409)
        uid = create_user(conn, email, name, "SUPER_ADMIN", password)
        audit.record(conn, "auth.signed_up", dict(id=uid, email=email, role="SUPER_ADMIN"), "app_user", uid,
                     dict(role="SUPER_ADMIN", first_account=True))
    return login(request, dict(email=email, password=password))


@router.post("/auth/login")
def login(request: Request, body: dict = Depends(json_body)):
    email, password = s(body.get("email")).lower()[:200], _text(body.get("password"))
    with db.tx() as conn:
        fails = db.scalar(conn, "SELECT count(*) FROM login_attempt WHERE email = %s AND NOT ok AND at > now() - "
                                "interval '15 minutes'", (email,))
        if fails >= config.settings.login_max_failures:
            return JSONResponse({"detail": "Too many failed sign-ins. Please wait 15 minutes and try again."},
                                status_code=429)
        u = db.one(conn, "SELECT * FROM app_user WHERE email = %s", (email,))
        pw_ok = security.check_password(password, u["password_hash"] if u else None)
        ok = bool(u and u["active"] and u["deleted_at"] is None and pw_ok)
        db.insert(conn, "login_attempt", dict(email=email, ok=ok), returning=None)
        if not ok:
            why = ("unknown email" if not u else "account deleted" if u["deleted_at"] is not None
                   else "account switched off" if not u["active"] else "wrong password")
            audit.record(conn, "auth.failed", None, "app_user", u["id"] if u else None, dict(email=email, reason=why))
    if not ok:
        raise Unauthorized("The email or password was not recognised.")
    with db.tx() as conn:
        token, csrf, expires = security.new_session(conn, u["id"])
        conn.execute("UPDATE app_user SET last_login_at = now() WHERE id = %s", (u["id"],))
        audit.record(conn, "auth.signed_in", dict(id=u["id"], email=u["email"], role=u["role"]), "app_user", u["id"],
                     dict(temporary_password=u["must_change_password"]))
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
        a = security.load_session(tok)
        security.revoke_session(tok)
        if a:
            with db.tx() as conn:
                audit.record(conn, "auth.signed_out", a, "app_user", a["id"])
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


@router.get("/releases")
def release_notes(a: dict = Depends(actor)):
    """Every version's notes, newest first (the version in the footer opens them)."""
    return J(dict(version=__version__, releases=releases.RELEASES))


@router.patch("/me")
def update_me(body: dict = Depends(json_body), a: dict = Depends(actor)):
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
            new = _text(body["new_password"])
            u = db.one(conn, "SELECT password_hash, must_change_password FROM app_user WHERE id = %s", (a["id"],))
            if not security.check_password(_text(body.get("current_password")), u["password_hash"]):
                raise ValueError("Your current password is not right.")
            if len(new) < security.PASSWORD_MIN:
                raise ValueError(f"The new password must be at least {security.PASSWORD_MIN} characters long.")
            if len(new) > security.PASSWORD_MAX:
                raise ValueError(f"The new password can have at most {security.PASSWORD_MAX} characters.")
            if "confirm_password" in body and body["confirm_password"] != new:
                raise ValueError("The two new passwords are not the same.")
            if security.check_password(new, u["password_hash"]):
                raise ValueError("Please choose a new password that is different from the current one.")
            conn.execute("UPDATE app_user SET password_hash = %s, must_change_password = FALSE, updated_at = now() "
                         "WHERE id = %s", (security.hash_password(new), a["id"]))
            security.revoke_all(conn, a["id"], keep_csrf=a.get("csrf"))       # other signed-in browsers sign out
            changed.append("password")
            if u["must_change_password"]:
                changed.append("temporary password replaced")
        audit.record(conn, "user.profile_updated" if changed != ["name"] else "user.name_changed", a, "app_user",
                     a["id"], dict(changed=changed))
    return J(me_out(a))                                   # me_out reads the saved name back
