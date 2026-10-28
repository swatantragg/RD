"""Request helpers: the signed-in actor, permission checks and exact JSON."""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from fastapi import Body, Request
from fastapi.responses import Response

from .. import db, security

COOKIE = "mrm_session"


class Unauthorized(Exception):
    pass


class J(Response):
    """JSON with Decimal as exact text and dates as ISO strings (never binary floats)."""
    media_type = "application/json"

    def __init__(self, content: Any, status_code: int = 200):
        super().__init__(db.dumps(content).encode("utf-8"), status_code=status_code)


# what a person signed in with a temporary password may still do: read who they are, change it, sign out
TEMPORARY_OK = {("GET", "/api/auth/me"), ("PATCH", "/api/me"), ("POST", "/api/auth/logout")}


def actor(request: Request) -> dict:
    a = security.load_session(request.cookies.get(COOKIE))
    if not a:
        raise Unauthorized("sign in first")
    if a.get("must_change_password") and (request.method, request.url.path) not in TEMPORARY_OK:
        raise security.Forbidden("Please change your temporary password before you continue.")
    return a


def page(limit: int | None, offset: int | None, cap: int = 500) -> tuple[int, int]:
    return max(1, min(cap, limit or 100)), max(0, offset or 0)


_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f"\\;]')


def attachment(name: str, data: bytes, media: str) -> Response:
    """A download. The file name is made safe for the header: no quotes, semicolons or line breaks (they could break
    or add a header), ASCII for old browsers and the full UTF-8 name beside it."""
    clean = _UNSAFE_NAME.sub("_", name).strip() or "download"
    ascii_name = clean.encode("ascii", "replace").decode().replace("?", "_")
    return Response(data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(clean)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


# ------------------------------------------------------------------ request bodies (1.7.3)
# Fields that are text: a number sent instead is read as its text, anything else (a list, an object, true) as empty -
# so a wrong type is refused with a plain message by the rules that follow, never a server error.
TEXT_FIELDS = frozenset((
    "action alias attachment_reference catalogue_status channel choice code confirm confirm_password "
    "confirmed_by_name current_password description draft_body email internal_work_number isrc kind message "
    "message_reference method name new_password note password reason received_from received_via recipient "
    "recording_title role sender status status_note subject summary temporary_password title to_work work_number "
    "work_title album language member_id iprs_currency revenue_basis").split())


def _clean(body: dict) -> dict:
    out = dict(body)
    for k in TEXT_FIELDS & out.keys():
        v = out[k]
        if v is None or isinstance(v, str):
            continue
        out[k] = str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else ""
    return out


def json_body(body: dict = Body(...)) -> dict:
    return _clean(body)


def json_body_opt(body: dict = Body(default={})) -> dict:
    return _clean(body)


def need_id(body: dict, key: str, what: str) -> int:
    """A required id in a request body (a whole number); missing or not a number is a plain 400."""
    v = body.get(key)
    if v is None or v == "" or isinstance(v, bool):
        raise ValueError(f"Please choose the {what}.")
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"The {what} is not valid.") from None


def id_list(body: dict, key: str, what: str) -> list[int]:
    v = body.get(key) or []
    if not isinstance(v, list):
        raise ValueError(f"The {what} must be a list.")
    try:
        return [int(x) for x in v if not isinstance(x, bool)]
    except (TypeError, ValueError):
        raise ValueError(f"The {what} are not valid.") from None
