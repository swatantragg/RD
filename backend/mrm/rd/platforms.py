"""Normalised platforms. Sources spell platforms in many ways ('SPOTIFY AB', 'Spotify', 'YouTube Pre-Claims'); each
spelling maps to exactly one platform through platform_aliases. Facebook, Instagram and YouTube stay separate
platforms; IPRS's single Meta licence is its own platform (META) and is never merged with Facebook or Instagram."""
from __future__ import annotations

import re

from .. import audit, db
from . import access, names


class PlatformError(ValueError):
    pass


def key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def resolve(conn, *texts: str | None) -> dict | None:
    """The platform a source's wording means: an exact alias first, then a known platform word inside the text."""
    for t in texts:
        k = key(t)
        if not k:
            continue
        p = db.one(conn, "SELECT p.* FROM platform_aliases a JOIN platforms p ON p.id = a.platform_id "
                         "WHERE a.alias_key = %s", (k,))
        if p:
            return p
    for t in texts:
        word = names.platform_from_text(t or "")
        if word:
            p = db.one(conn, "SELECT p.* FROM platform_aliases a JOIN platforms p ON p.id = a.platform_id "
                             "WHERE a.alias_key = %s", (key(word),))
            if p:
                return p
    return None


def ensure(conn, name: str | None, actor: dict | None = None) -> dict | None:
    """The platform for a statement category that is not a known platform (Radio, Zee TV Broadcast, Overseas - SACEM
    (France), Other / Unclassified …): made once, named as the statement names it, so every category can be
    reconciled and listed on its own. Spellings never merge two categories."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    k = key(name)
    if not k:
        return None
    conn.execute("SELECT pg_advisory_xact_lock(84726500)")
    p = db.one(conn, "SELECT p.* FROM platform_aliases a JOIN platforms p ON p.id = a.platform_id WHERE a.alias_key = %s",
               (k,))
    if p:
        return p
    base = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:28] or "CATEGORY"
    if not base[0].isalpha():
        base = f"C_{base}"[:28]
    code, n = base, 1
    while db.scalar(conn, "SELECT id FROM platforms WHERE platform_code = %s", (code,)):
        n += 1
        code = f"{base}_{n}"
    pid = db.insert(conn, "platforms", dict(platform_code=code, platform_name=name,
                                            note="Added from a statement category"))
    db.insert(conn, "platform_aliases", dict(platform_id=pid, alias=name, alias_key=k,
                                             created_by=actor["id"] if actor else None), returning=None)
    audit.record(conn, "platform.created", actor, "platforms", pid, after=dict(code=code, name=name, automatic=True))
    return db.one(conn, "SELECT * FROM platforms WHERE id = %s", (pid,))


def all_platforms(conn) -> list[dict]:
    return db.all(conn, "SELECT id, platform_code, platform_name, status, note FROM platforms ORDER BY platform_name")


def listing(actor: dict) -> list[dict]:
    with db.tx() as conn:
        ps = all_platforms(conn)
        aliases = db.all(conn, "SELECT id, platform_id, alias FROM platform_aliases ORDER BY alias")
    for p in ps:
        p["aliases"] = [a["alias"] for a in aliases if a["platform_id"] == p["id"]]
    return ps


def add_platform(actor: dict, body: dict) -> dict:
    access.require(actor, "platforms")
    name = (body.get("name") or "").strip()
    code = re.sub(r"[^A-Z0-9_]", "_", (body.get("code") or name).strip().upper()).strip("_")[:32]
    if not name or not re.match(r"^[A-Z][A-Z0-9_]{1,31}$", code):
        raise PlatformError("A platform needs a name (and a code of letters, digits and _).")
    with db.tx() as conn:
        if db.scalar(conn, "SELECT id FROM platforms WHERE platform_code = %s", (code,)):
            raise PlatformError(f"A platform with the code {code} already exists.")
        if db.scalar(conn, "SELECT id FROM platform_aliases WHERE alias_key = %s", (key(name),)):
            raise PlatformError(f"'{name}' already means another platform.")
        pid = db.insert(conn, "platforms", dict(platform_code=code, platform_name=name))
        db.insert(conn, "platform_aliases", dict(platform_id=pid, alias=name, alias_key=key(name),
                                                 created_by=actor["id"]), returning=None)
        audit.record(conn, "platform.created", actor, "platforms", pid, after=dict(code=code, name=name))
    return dict(id=pid)


def add_alias(actor: dict, platform_id: int, alias: str) -> dict:
    """A source's own spelling of a platform (e.g. 'Spotify AB'). One spelling can only ever mean one platform."""
    access.require(actor, "platforms")
    alias = (alias or "").strip()
    if not key(alias):
        raise PlatformError("Please enter the name as the source writes it.")
    with db.tx() as conn:
        p = db.one(conn, "SELECT * FROM platforms WHERE id = %s", (platform_id,))
        if not p:
            raise PlatformError("This platform does not exist.")
        other = db.one(conn, "SELECT p.platform_name FROM platform_aliases a JOIN platforms p ON p.id = a.platform_id "
                             "WHERE a.alias_key = %s", (key(alias),))
        if other:
            raise PlatformError(f"'{alias}' already means {other['platform_name']}.")
        db.insert(conn, "platform_aliases", dict(platform_id=platform_id, alias=alias, alias_key=key(alias),
                                                 created_by=actor["id"]), returning=None)
        audit.record(conn, "platform.alias_added", actor, "platforms", platform_id,
                     dict(platform=p["platform_name"], alias=alias))
    return dict(ok=True)


def require_platform(conn, platform_id: int | None) -> dict:
    p = db.one(conn, "SELECT * FROM platforms WHERE id = %s", (platform_id,)) if platform_id else None
    if not p:
        raise PlatformError("Please choose a platform.")
    return p

