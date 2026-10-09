"""Plain SQL migrations, applied in order by the owner login (never by the running app login)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent / "migrations"


def apply(url: str, echo=print) -> list[str]:
    done: list[str] = []
    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute("SELECT pg_advisory_lock(84726000)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
                     "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        conn.commit()
        applied = {r[0]: r[1] for r in conn.execute("SELECT version, sha256 FROM schema_migrations")}
        for f in sorted(HERE.glob("*.sql")):
            sql = f.read_text()
            sha = hashlib.sha256(sql.encode()).hexdigest()
            if f.name in applied:
                if applied[f.name] != sha:
                    raise RuntimeError(f"migration {f.name} changed after it was applied - add a new file instead")
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)", (f.name, sha))
            done.append(f.name)
            echo(f"  applied {f.name}")
        conn.execute("SELECT pg_advisory_unlock(84726000)")
        conn.commit()
    return done
