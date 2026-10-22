"""HTTP API. Money leaves the server as exact decimal strings; every state change needs the session's CSRF token."""
from __future__ import annotations

import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .. import __version__, config, db
from ..rd.service import RDError
from ..security import Forbidden
from . import routes_admin, routes_auth, routes_rd, routes_recon
from .deps import COOKIE, Unauthorized

logging.basicConfig(level=config.settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mrm.api")

app = FastAPI(title="Royalty Processing Platform", version=__version__, redoc_url=None,
              docs_url="/api/docs" if config.settings.api_docs else None,
              openapi_url="/api/openapi.json" if config.settings.api_docs else None)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
            and request.url.path not in ("/api/auth/login",) and request.cookies.get(COOKIE):
        from ..security import load_session
        s = load_session(request.cookies.get(COOKIE))
        if s and request.headers.get("x-csrf-token") != s["csrf"]:
            return JSONResponse({"detail": "Your session expired. Please reload the page."}, status_code=403)
    resp: Response = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def _err(status: int, msg: str) -> JSONResponse:
    return JSONResponse({"detail": msg}, status_code=status)


@app.exception_handler(Unauthorized)
async def _unauth(_, e):
    return _err(401, str(e) or "Please sign in.")


@app.exception_handler(Forbidden)
async def _forbidden(_, e):
    return _err(403, str(e))


for _cls in (ValueError, RDError):
    app.add_exception_handler(_cls, lambda _, e: _err(400, str(e)))


@app.exception_handler(psycopg.errors.InsufficientPrivilege)
async def _frozen(_, e):
    log.warning("refused by the database: %s", str(e).split("\n")[0])
    return _err(409, "This record is locked and cannot be changed. " + str(e).split("\n")[0])


@app.exception_handler(psycopg.errors.UniqueViolation)
async def _dupe(_, e):
    return _err(409, "This already exists.")


@app.exception_handler(Exception)
async def _unexpected(_, e):
    log.exception("unexpected error")
    return _err(500, "Something went wrong on the server. Please try again; if it keeps happening, contact your "
                     "administrator.")


@app.get("/api/health")
def health():
    with db.tx() as conn:
        conn.execute("SELECT 1")
    return {"ok": True, "version": __version__}


@app.on_event("startup")
def _start_worker():
    if config.settings.rd_worker == "thread":
        from ..rd import jobs
        jobs.start_worker()


app.include_router(routes_auth.router, prefix="/api")
app.include_router(routes_rd.router, prefix="/api")
app.include_router(routes_recon.router, prefix="/api")
app.include_router(routes_admin.router, prefix="/api")
