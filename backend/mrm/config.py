"""Deployment settings. Numbers that change a result (benchmark rate, tolerance, stream rate) live in rule versions."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    secret_key: str
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
    db_url = _env("DATABASE_URL", "postgresql://mrm_app:devpass@127.0.0.1:55433/mrm")
    return Settings(
        database_url=db_url,
        migrator_database_url=_env("MIGRATOR_DATABASE_URL", db_url.replace("mrm_app:", "mrm_owner:")),
        storage_root=Path(_env("STORAGE_ROOT", str(Path.cwd() / "data" / "objects"))),
        secret_key=_env("SECRET_KEY", "dev-only-secret-change-me"),
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


settings = load()


def reload() -> Settings:
    global settings
    settings = load()
    return settings
