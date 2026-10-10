"""Roles and permissions (page 9: who builds, who reviews rights, who approves, who sends), passwords, sessions.

Checked on the server for every request; the screen only hides what the server already refuses. Maker and checker
are always different people: a rule or a report pack is never approved by the person who drafted it.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets

from . import config, db

ROLES = ("admin", "importer", "rights_reviewer", "accounts", "approver", "sender", "viewer")
ROLE_LABELS = {
    "admin": "Administrator",
    "importer": "Import & build",
    "rights_reviewer": "Rights & identity review",
    "accounts": "Accounts & payments",
    "approver": "Approver",
    "sender": "Authorised sender",
    "viewer": "Read only",
}

PERMISSIONS: dict[str, tuple[str, ...]] = {
    "view": ROLES,
    "upload": ("importer",),                           # A1-B5: upload, classify, confirm metadata
    "intake_review": ("importer", "accounts"),           # accept row exceptions, approve alternative control, duplicates
    "clients": ("rights_reviewer",),                    # mandate, member ID, controlled share
    "identity": ("rights_reviewer",),                   # C1-C4 decisions
    "identity_approve": ("rights_reviewer", "approver"),  # C5 freeze an identity version
    "rule_draft": ("accounts",),                        # E1-E5
    "rule_approve": ("approver",),
    "run": ("importer", "accounts"),                    # D-G comparison run
    "pack_build": ("importer", "accounts"),             # H1
    "pack_approve": ("approver",),                      # H3
    "send": ("sender", "approver"),                     # H4 send + log reply
    "case_update": ("rights_reviewer", "accounts", "approver"),  # H5
    "payment": ("accounts",),
    "users": ("admin",),
    "audit": ("admin", "approver"),
}


class Forbidden(Exception):
    pass


def has(actor: dict, permission: str) -> bool:
    roles = actor.get("roles", ())
    return "admin" in roles or any(r in PERMISSIONS[permission] for r in roles)


def require(actor: dict, permission: str) -> None:
    if not has(actor, permission):
        need = " or ".join(ROLE_LABELS[r] for r in PERMISSIONS[permission])
        raise Forbidden(f"this needs the {need} role")


def not_same_person(actor: dict, maker_id: int | None, what: str) -> None:
    if maker_id is not None and actor["id"] == maker_id:
        raise Forbidden(f"{what} must be approved by someone other than the person who prepared it")


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
