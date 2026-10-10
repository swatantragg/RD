"""Command line: python -m mrm.cli migrate | seed | bootstrap | worker | create-user | verify-audit"""
from __future__ import annotations

import argparse
import sys
import time

import psycopg

from . import audit, config, db, migrate


def wait_for_db(url: str, seconds: int = 60) -> None:
    end = time.time() + seconds
    while True:
        try:
            with psycopg.connect(url, connect_timeout=3):
                return
        except psycopg.OperationalError:
            if time.time() > end:
                raise
            time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mrm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("bootstrap", help="migrate, then set up the first client (SVF)")
    u = sub.add_parser("create-user")
    u.add_argument("email")
    u.add_argument("name")
    u.add_argument("roles", help="comma separated: admin,importer,rights_reviewer,accounts,viewer")
    u.add_argument("--clients", default="", help="comma separated client codes this person may see (e.g. SVF)")
    u.add_argument("password")
    sub.add_parser("verify-audit")
    sub.add_parser("worker", help="process queued runs and publications (background jobs)")
    a = ap.parse_args(argv)
    s = config.settings
    if a.cmd in ("migrate", "bootstrap"):
        wait_for_db(s.migrator_database_url)
        print("migrations:")
        migrate.apply(s.migrator_database_url)
    if a.cmd in ("seed", "bootstrap"):
        from .seed import seed
        print("seed:")
        seed()
    if a.cmd == "create-user":
        from .seed import create_user
        with db.tx() as conn:
            uid = create_user(conn, a.email, a.name, a.roles.split(","), a.password)
            for code in [c.strip().upper() for c in a.clients.split(",") if c.strip()]:
                conn.execute("INSERT INTO client_grant (user_id, client_id) SELECT %s, id FROM client WHERE code = %s "
                             "ON CONFLICT DO NOTHING", (uid, code))
        print(f"user {a.email} ready")
    if a.cmd == "worker":
        wait_for_db(s.database_url)
        from .rd import jobs
        print("worker: waiting for processing jobs", flush=True)
        jobs.run_forever()
    if a.cmd == "verify-audit":
        with db.tx() as conn:
            r = audit.verify_chain(conn)
        print(r)
        return 0 if r["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
