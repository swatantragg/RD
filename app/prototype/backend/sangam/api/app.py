"""FastAPI application: the REST API of architecture §17.3 plus the built React UI.

Every list endpoint returns deterministic ordering and X-Total-Count; every pipe column is
returned as an ARRAY - the '|' exists only inside a downloaded workbook (§16, §18.1).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .. import __version__
from ..core import config, db
from ..merge.apply import Forbidden
from . import routes

log = logging.getLogger("sangam")

@asynccontextmanager
async def lifespan(_app):
    config.ensure_dirs()
    db.connect().close()
    yield


app = FastAPI(title="Sangam - IPRS Royalty Intelligence Platform", version=__version__, lifespan=lifespan,
              description="Prototype of the SVF Entertainment IPRS Royalty Platform, architecture V2.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Total-Count"])
app.include_router(routes.router, prefix="/api")


@app.exception_handler(ValueError)
async def _bad_request(_req: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(KeyError)
async def _not_found(_req: Request, exc: KeyError):
    return JSONResponse({"detail": f"not found: {exc}"}, status_code=404)


@app.exception_handler(Forbidden)
async def _forbidden(_req: Request, exc: Forbidden):
    return JSONResponse({"detail": str(exc)}, status_code=403)


# ------------------------------------------------------------------ the single-page UI
DIST = Path(config.FRONTEND_DIST)


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    f = (DIST / path).resolve()
    if path and f.is_file() and DIST.resolve() in f.parents:
        return FileResponse(f)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "UI not built - run `npm run build` in app/prototype/frontend, "
                                   "or open the API docs at /docs"}, status_code=404)
