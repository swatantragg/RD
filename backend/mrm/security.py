"""Roles, passwords and sessions. What each role may do is in rd/access.py and is checked on the server for every
request; the screen only hides what the server already refuses.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets

from . import config, db

ROLES = ("admin", "importer", "rights_reviewer", "accounts", "viewer")


class Forbidden(Exception):
    pass


# ------------------------------------------------------------------ passwords (scrypt, stdlib)
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("passwords need at least 10 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        hashlib.scrypt(b"x", salt=b"0" * 16, n=_N, r=_R, p=_P, dklen=32)     # same cost either way
        return False
    _, n, r, p, salt, dk = stored.split("$")
    got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    return hmac.compare_digest(got, base64.b64decode(dk))


# ------------------------------------------------------------------ sessions (server side)
def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(conn, user_id: int) -> tuple[str, str, dt.datetime]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=config.settings.session_hours)
    db.insert(conn, "app_session", dict(token_sha256=sha(token), user_id=user_id, csrf=csrf, expires_at=expires),
              returning=None)
    return token, csrf, expires


def load_session(token: str | None) -> dict | None:
    if not token:
        return None
    with db.tx() as conn:
        r = db.one(conn, "SELECT s.csrf, s.expires_at, u.id, u.email, u.name, u.active FROM app_session s "
                         "JOIN app_user u ON u.id = s.user_id WHERE s.token_sha256 = %s AND s.revoked_at IS NULL "
                         "AND s.expires_at > now()", (sha(token),))
        if not r or not r["active"]:
            return None
        r["roles"] = [x["role"] for x in db.all(conn, "SELECT role FROM user_role WHERE user_id = %s ORDER BY role",
                                                    (r["id"],))]
    return r


def revoke_session(token: str) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE app_session SET revoked_at = now() WHERE token_sha256 = %s", (sha(token),))
