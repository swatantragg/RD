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

ROLES = ("SUPER_ADMIN", "ADMIN", "USER")              # exactly three application roles (app_user.role)
PASSWORD_MIN = 10


class Forbidden(Exception):
    pass


# ------------------------------------------------------------------ passwords (scrypt, stdlib)
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"passwords need at least {PASSWORD_MIN} characters")
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
        r = db.one(conn, "SELECT s.csrf, s.expires_at, u.id, u.email, u.name, u.active, u.deleted_at, u.role, "
                         "u.must_change_password FROM app_session s JOIN app_user u ON u.id = s.user_id "
                         "WHERE s.token_sha256 = %s AND s.revoked_at IS NULL AND s.expires_at > now()", (sha(token),))
    if not r or not r["active"] or r["deleted_at"] is not None:
        return None
    r["roles"] = [r["role"]]
    return r


def temporary_password() -> str:
    """A random password for a new or reset account. It is shown once to the person who set it and must be changed at
    the first sign-in; only its hash is stored."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))


def revoke_all(conn, user_id: int, keep_csrf: str | None = None) -> None:
    conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL AND csrf <> %s",
                 (user_id, keep_csrf or ""))


def revoke_session(token: str) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE app_session SET revoked_at = now() WHERE token_sha256 = %s", (sha(token),))
