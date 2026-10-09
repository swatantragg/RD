"""One-time clean-up after upgrading from the demonstration version (1.0.0): python -m mrm.cli purge-demo --keep EMAIL

  1. the earlier comparison module's demo walkthrough data is removed (its tables held nothing else);
  2. work done while signed in with a demo account is moved to the kept account (the same person used it);
  3. the six demo accounts are deleted;
  4. the kept account gets every role.

Runs with the owner login (migrations), because evidence tables refuse changes to the application login. The audit
log is append-only and keeps its original entries; the clean-up itself is recorded in it.
"""
from __future__ import annotations

import psycopg

from . import config
from .seed import RETIRED_DEMO

LEGACY_TABLES = ("batch", "source_file", "publishing_line", "recording_line", "usage_line", "catalogue_line",
                 "composition", "recording", "work_link", "identity_issue", "duplicate_candidate", "identity_version",
                 "identity_version_link", "rule_version", "comparison_run", "comparison_group", "run_exception",
                 "report_pack", "enquiry_case", "case_event")
REASSIGN = [  # table, column, trigger that protects the row
    ("rd_file", "uploaded_by", "rd_file_guard"), ("rd_run", "created_by", None), ("rd_run_file", "added_by", None),
    ("rd_build", "created_by", "rd_build_guard"), ("rd_build", "submitted_by", "rd_build_guard"),
    ("rd_build", "approved_by", "rd_build_guard"), ("rd_decision", "made_by", "rd_decision_guard"),
    ("rd_decision", "checked_by", "rd_decision_guard")]
ALL_ROLES = ("admin", "importer", "rights_reviewer", "accounts", "approver")


def purge_demo(keep_email: str, echo=print) -> dict:
    with psycopg.connect(config.settings.migrator_database_url) as conn:
        with conn.transaction():
            row = conn.execute("SELECT id, email FROM app_user WHERE email = %s", (keep_email.strip().lower(),)).fetchone()
            if not row:
                raise SystemExit(f"no account {keep_email!r} - create it first (sign up), then run this again")
            keep = row[0]
            demo = [r[0] for r in conn.execute("SELECT id FROM app_user WHERE email = ANY(%s)", (list(RETIRED_DEMO),))]
            # moving work must never turn a two-person approval into a self-approval
            def m(v):
                return keep if v in demo else v
            clash = [b for b in conn.execute("SELECT created_by, submitted_by, approved_by FROM rd_build "
                                             "WHERE approved_by IS NOT NULL").fetchall()
                     if m(b[2]) in (m(b[0]), m(b[1]))] + \
                    [d for d in conn.execute("SELECT made_by, checked_by FROM rd_decision WHERE checked_by IS NOT NULL")
                     .fetchall() if m(d[0]) == m(d[1])]
            if clash:
                raise SystemExit("some work was prepared and approved by different people; moving it to one account "
                                 "would make it self-approved. Nothing was changed.")
            conn.execute("TRUNCATE " + ", ".join(LEGACY_TABLES))
            moved = 0
            for table in sorted({t for t, _, _ in REASSIGN}):
                trig = {g for t, _, g in REASSIGN if t == table and g}
                for g in trig:
                    conn.execute(f"ALTER TABLE {table} DISABLE TRIGGER {g}")
                for t, col, _ in REASSIGN:
                    if t == table:
                        moved += conn.execute(f"UPDATE {table} SET {col} = %s WHERE {col} = ANY(%s)", (keep, demo)).rowcount
                for g in trig:
                    conn.execute(f"ALTER TABLE {table} ENABLE TRIGGER {g}")
            conn.execute("UPDATE client_grant SET granted_by = NULL WHERE granted_by = ANY(%s)", (demo,))
            deleted = conn.execute("DELETE FROM app_user WHERE id = ANY(%s)", (demo,)).rowcount
            for r in ALL_ROLES:
                conn.execute("INSERT INTO user_role (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING", (keep, r))
            conn.execute("UPDATE app_user SET active = TRUE WHERE id = %s", (keep,))
            conn.execute("INSERT INTO audit_event (id, at, actor, action, object_kind, object_id, detail, prev_hash, hash) "
                         "VALUES (0, now(), 'maintenance', 'maintenance.demo_purged', 'app_user', %s, %s, '', '')",
                         (str(keep), psycopg.types.json.Jsonb(dict(kept=row[1], deleted_accounts=deleted,
                                                                    moved_records=moved, roles=list(ALL_ROLES)))))
    out = dict(kept=row[1], deleted_accounts=deleted, moved_records=moved, roles=list(ALL_ROLES))
    echo(f"  kept {row[1]} with every role; {deleted} demo account(s) deleted; {moved} record(s) moved to the kept "
         f"account; demo data of the earlier comparison module removed")
    return out
