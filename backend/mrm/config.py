"""Deployment settings, read from the environment and from backend/.env (see backend/.env.example).

A variable already set in the environment wins over the file. ENV_FILE points at another file (ENV_FILE=none reads
none). In production (APP_ENV=production) the application refuses to start with default or weak database passwords.
Numbers that change a result (tolerance, rates) live in the rule set, not here.
"""
from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
WEAK_PASSWORDS = {"devpass", "mrm-app-dev", "mrm-owner-dev", "postgres-dev", "postgres", "password", "change-me"}


def _load_env_file() -> Path | None:
    name = os.environ.get("ENV_FILE")
    if name is not None and name.strip().lower() in ("", "none"):
        return None
    path = Path(name) if name else ENV_FILE
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return path


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    if v.startswith("file:"):                               # docker secrets: VAR=file:/run/secrets/x
        return Path(v[5:]).read_text().strip()
    return v


def _bool(name: str, default: bool) -> bool:
    v = _env(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = _env(name)
    return default if v is None else int(v)


@dataclass(frozen=True)
class Settings:
    database_url: str
    migrator_database_url: str
    storage_root: Path
    app_env: str                                            # development | production
    api_docs: bool                                          # /api/docs (off in production)
    session_hours: int
    cookie_secure: str                                      # auto | true | false
    allow_signup: bool
    max_upload_mb: int
    max_unzipped_mb: int
    max_cells: int
    max_sheets: int
    max_zip_ratio: int
    login_max_failures: int
    pool_size: int
    log_level: str
    rd_worker: str


def load() -> Settings:
    _load_env_file()
    db_url = _env("DATABASE_URL", "postgresql://mrm_app:devpass@127.0.0.1:55433/mrm")
    app_env = (_env("APP_ENV", "development") or "development").strip().lower()
    s = Settings(
        database_url=db_url,
        migrator_database_url=_env("MIGRATOR_DATABASE_URL", db_url.replace("mrm_app:", "mrm_owner:")),
        storage_root=Path(_env("STORAGE_ROOT", str(Path.cwd() / "data" / "objects"))),
        app_env=app_env,
        api_docs=_bool("API_DOCS", app_env != "production"),
        session_hours=_int("SESSION_HOURS", 10),
        cookie_secure=_env("COOKIE_SECURE", "auto"),
        allow_signup=_bool("ALLOW_SIGNUP", True),
        max_upload_mb=_int("MAX_UPLOAD_MB", 64),
        max_unzipped_mb=_int("MAX_UNZIPPED_MB", 512),
        max_cells=_int("MAX_CELLS", 2_000_000),
        max_sheets=_int("MAX_SHEETS", 100),
        max_zip_ratio=_int("MAX_ZIP_RATIO", 200),
        login_max_failures=_int("LOGIN_MAX_FAILURES", 8),
        pool_size=_int("DB_POOL_SIZE", 10),
        log_level=_env("LOG_LEVEL", "INFO"),
        rd_worker=_env("RD_WORKER", "thread"),
    )
    if app_env == "production":
        _refuse_weak(s)
    return s


def _refuse_weak(s: Settings) -> None:
    """Production never runs on the development passwords or on short ones."""
    problems = []
    for name, url in (("DATABASE_URL", s.database_url), ("MIGRATOR_DATABASE_URL", s.migrator_database_url)):
        pw = urllib.parse.urlsplit(url).password or ""
        if pw.lower() in WEAK_PASSWORDS or len(pw) < 16:
            problems.append(f"{name} needs a strong password (16+ random characters, not a default)")
    if problems:
        raise SystemExit("Refusing to start in production: " + "; ".join(problems) + ". See backend/.env.example.")


settings = load()


def reload() -> Settings:
    global settings
    settings = load()
    return settings
