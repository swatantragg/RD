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
    u.add_argument("role", help="SUPER_ADMIN (only when there is none yet), ADMIN or USER")
    u.add_argument("--clients", default="", help="comma separated client codes a USER may see (e.g. SVF)")
    u.add_argument("password")
    r = sub.add_parser("recover-super-admin",
                       help="exceptional recovery: make an existing account the Super Admin (audited)")
    r.add_argument("email", help="the account that becomes the Super Admin")
    r.add_argument("--reason", required=True, help="why the recovery is needed (kept in the audit log)")
    r.add_argument("--demote-current", action="store_true",
                   help="also make the current Super Admin an Admin")
    c = sub.add_parser("clear-statements",
                       help="exceptional: remove a client's statements, reconciliations, enquiries and processing runs, "
                            "keeping its catalogue (audited)")
    c.add_argument("client", help="client code, e.g. SVF")
    c.add_argument("--reason", required=True, help="why (kept in the activity log)")
    c.add_argument("--confirm", default="", help="repeat the client code to really do it; without it nothing changes")
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
            uid = create_user(conn, a.email, a.name, a.role.strip().upper(), a.password)
            for code in [c.strip().upper() for c in a.clients.split(",") if c.strip()]:
                conn.execute("INSERT INTO client_grant (user_id, client_id) SELECT %s, id FROM client WHERE code = %s "
                             "ON CONFLICT DO NOTHING", (uid, code))
        print(f"user {a.email} ready")
    if a.cmd == "recover-super-admin":
        with db.tx() as conn:
            u = db.one(conn, "SELECT id, email, role, active, deleted_at FROM app_user WHERE email = %s",
                       (a.email.lower(),))
            if not u or u["deleted_at"] is not None:
                print(f"no account {a.email}")
                return 1
            olds = db.all(conn, "SELECT id, email FROM app_user WHERE role = 'SUPER_ADMIN' AND id <> %s", (u["id"],))
            conn.execute("SELECT set_config('app.recovery', 'on', true)")       # this transaction only
            conn.execute("UPDATE app_user SET role = 'SUPER_ADMIN', active = TRUE, updated_at = now() WHERE id = %s",
                         (u["id"],))
            if a.demote_current:
                for o in olds:
                    conn.execute("UPDATE app_user SET role = 'ADMIN', updated_at = now() WHERE id = %s", (o["id"],))
                    conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                                 (o["id"],))
            audit.record(conn, "security.super_admin_recovery", None, "app_user", u["id"],
                         dict(email=u["email"], reason=a.reason, previous_role=u["role"],
                              demoted=[o["email"] for o in olds] if a.demote_current else []))
        print(f"{a.email} is now the Super Admin")
    if a.cmd == "worker":
        wait_for_db(s.database_url)
        from .rd import jobs
        print("worker: waiting for processing jobs", flush=True)
        jobs.run_forever()
    if a.cmd == "clear-statements":
        from .maintenance import ClearRefused, clear_statements
        real = a.confirm.strip().upper() == a.client.strip().upper()
        if not real:
            print("dry run (add --confirm CODE to do it):")
        try:
            clear_statements(a.client, a.reason, dry_run=not real)
        except ClearRefused as e:
            raise SystemExit(str(e)) from None
    if a.cmd == "verify-audit":
        with db.tx() as conn:
            r = audit.verify_chain(conn)
        print(r)
        return 0 if r["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
