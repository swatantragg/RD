"""Request helpers: the signed-in actor, permission checks and exact JSON."""
from __future__ import annotations

from typing import Any

from fastapi import Request
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


def actor(request: Request) -> dict:
    a = security.load_session(request.cookies.get(COOKIE))
    if not a:
        raise Unauthorized("sign in first")
    return a


def page(limit: int | None, offset: int | None, cap: int = 500) -> tuple[int, int]:
    return max(1, min(cap, limit or 100)), max(0, offset or 0)
