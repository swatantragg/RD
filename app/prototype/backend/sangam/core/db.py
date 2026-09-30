"""SQLite access. One connection per request / job thread; WAL so readers never block."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config
from ..domain.filename import DEFAULT_CATEGORIES, DEFAULT_SOCIETIES

_init_lock = threading.Lock()
_initialised: set[str] = set()


def now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60, check_same_thread=False,
                           isolation_level=None)          # autocommit; explicit transactions
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 60000")
    key = str(path.resolve())
    if key not in _initialised:
        with _init_lock:
            if key not in _initialised:
                init_schema(conn)
                _initialised.add(key)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    sql = (Path(__file__).with_name("schema.sql")).read_text()
    conn.executescript(sql)
    with tx(conn):
        for code, name, country in DEFAULT_SOCIETIES:
            conn.execute("INSERT OR IGNORE INTO society(code, name, country) VALUES (?,?,?)",
                         (code, name, country))
        for code, label, rx, ordinal in DEFAULT_CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO category(code, label, matcher_regex, ordinal) "
                         "VALUES (?,?,?,?)", (code, label, rx, ordinal))
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")


@contextmanager
def tx(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT, rolled back on any exception. Re-entrant."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def row(conn, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def scalar(conn, sql: str, params=()):
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def insert(conn, table: str, values: dict) -> int:
    cols = list(values)
    cur = conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                       f"({', '.join('?' for _ in cols)})", [values[c] for c in cols])
    return cur.lastrowid


def dumps(v) -> str:
    return json.dumps(v, default=_json_default, ensure_ascii=False, separators=(",", ":"))


def loads(v, default=None):
    if v is None or v == "":
        return default
    return json.loads(v)


def _json_default(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def get_categories(conn) -> list[tuple]:
    return [(r["code"], r["label"], r["matcher_regex"], r["ordinal"])
            for r in rows(conn, "SELECT * FROM category ORDER BY ordinal")]


def get_societies(conn) -> list[tuple]:
    return [(r["code"], r["name"], r["country"]) for r in rows(conn, "SELECT * FROM society")]
