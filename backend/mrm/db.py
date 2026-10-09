"""PostgreSQL access: one pooled connection per unit of work, one transaction per request."""
from __future__ import annotations

import datetime as dt
import json
import threading
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterable, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb, set_json_dumps
from psycopg_pool import ConnectionPool

from . import config


def _json_default(o):
    if isinstance(o, Decimal):
        return format(o, "f")                    # money in JSON is exact text, never a binary float
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return sorted(o) if isinstance(o, (set, frozenset)) else list(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def dumps(v: Any) -> str:
    return json.dumps(v, default=_json_default, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


set_json_dumps(dumps)
J = Jsonb

_pool: ConnectionPool | None = None
_guard = threading.Lock()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _guard:
            if _pool is None:
                s = config.settings
                p = ConnectionPool(s.database_url, min_size=1, max_size=s.pool_size, open=False, name="mrm",
                                   kwargs={"row_factory": dict_row, "autocommit": False})
                p.open(wait=True, timeout=30)
                _pool = p
    return _pool


@contextmanager
def tx() -> Iterator[psycopg.Connection]:
    with pool().connection() as conn:
        with conn.transaction():
            yield conn


def reset() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def one(conn, sql: str, params: Sequence | dict | None = None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def all(conn, sql: str, params: Sequence | dict | None = None) -> list[dict]:   # noqa: A001 - mirrors SQL
    return conn.execute(sql, params).fetchall()


def scalar(conn, sql: str, params: Sequence | dict | None = None):
    r = conn.execute(sql, params).fetchone()
    return None if r is None else next(iter(r.values()))


def _adapt(v):
    if isinstance(v, dict) or (isinstance(v, list) and v and isinstance(v[0], dict)):
        return Jsonb(v)
    return v


def insert(conn, table: str, values: dict, returning: str | None = "id"):
    cols = list(values)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
           + (f" RETURNING {returning}" if returning else ""))
    cur = conn.execute(sql, [_adapt(values[c]) for c in cols])
    return next(iter(cur.fetchone().values())) if returning else None


def update(conn, table: str, row_id: int, values: dict) -> None:
    if not values:
        return
    sets = ", ".join(f"{c} = %s" for c in values)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = %s", [*(_adapt(v) for v in values.values()), row_id])


def insert_many(conn, table: str, cols: Sequence[str], rows: Iterable[Sequence]) -> int:
    """Multi-row INSERT batches (thousands of statement rows per file)."""
    per = max(1, min(1000, 30000 // max(1, len(cols))))
    head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
    one_row = "(" + ", ".join(["%s"] * len(cols)) + ")"
    n, batch, count = 0, [], 0
    for r in rows:
        batch.extend(_adapt(v) for v in r)
        count += 1
        n += 1
        if count >= per:
            conn.execute(head + ", ".join([one_row] * count), batch)
            batch, count = [], 0
    if count:
        conn.execute(head + ", ".join([one_row] * count), batch)
    return n
