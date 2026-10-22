"""Exceptional maintenance: the command line, and the Super Admin's "Delete all statements" on the Statements page.

clear-catalogue (Super Admin, Catalogue page): start the catalogue again from nothing; see clear_catalogue.

clear-statements: start the statement work of a client again from nothing, keeping its catalogue. Removes every
uploaded statement and report file (and their parsed lines), the statement library, reconciliation runs, enquiries
and the processing runs with their draft reports. Kept: the catalogue (works, ISRCs, links and their history, the
catalogue imports and the song-list file they came from), clients, people, platforms, reconciliation settings and the
activity log, which records the clean-up itself. Published reports stop it: they are never deleted.
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from . import audit, config, db, storage


class ClearRefused(ValueError):
    """Nothing was changed (unknown client, or published reports that are never deleted)."""

GUARDED = ("rd_file", "rd_royalty_line", "rd_platform_line", "rd_prior", "rd_build", "rd_report", "rd_decision",
           "reconciliation_runs", "reconciliation_items", "reconciliation_sources", "enquiry_events",
           "enquiry_communications")


def clear_statements(code: str, reason: str, dry_run: bool = False, echo=print, actor: dict | None = None) -> dict:
    with psycopg.connect(config.settings.migrator_database_url, row_factory=dict_row, autocommit=False) as conn:
        c = db.one(conn, "SELECT id, code, name FROM client WHERE code = %s", (code.strip().upper(),))
        if not c:
            raise ClearRefused(f"no client {code}")
        cid = c["id"]
        q = lambda sql, *a: [r["id"] for r in db.all(conn, sql, a or (cid,))]          # noqa: E731
        keep = q("SELECT id FROM rd_file WHERE client_id = %s AND (kind = 'SONG_LIST' OR id IN (SELECT file_id FROM "
                 "catalogue_imports WHERE client_id = %s))", cid, cid)
        drop = [f for f in q("SELECT id FROM rd_file WHERE client_id = %s") if f not in keep]
        runs = q("SELECT id FROM rd_run WHERE client_id = %s")
        builds = q("SELECT id FROM rd_build WHERE run_id = ANY(%s)", runs)
        if db.scalar(conn, "SELECT count(*) FROM rd_report WHERE build_id = ANY(%s) AND final", (builds,)):
            raise ClearRefused("This client has published reports; they are never deleted, so nothing was changed.")
        enq = q("SELECT id FROM enquiries WHERE client_id = %s")
        objects = [r["object_key"] for r in db.all(conn, "SELECT object_key FROM rd_file WHERE id = ANY(%s) AND "
                                                         "object_key IS NOT NULL", (drop,))]
        reports = [r["object_key"] for r in db.all(conn, "SELECT object_key FROM rd_report WHERE build_id = ANY(%s) AND "
                                                         "object_key IS NOT NULL", (builds,))]
        counts = dict(
            statement_files=len(drop), kept_catalogue_files=len(keep), processing_runs=len(runs), builds=len(builds),
            statements=db.scalar(conn, "SELECT count(*) FROM statements WHERE client_id = %s", (cid,)),
            reconciliation_runs=db.scalar(conn, "SELECT count(*) FROM reconciliation_runs WHERE client_id = %s", (cid,)),
            enquiries=len(enq), report_files=len(reports))
        echo(f"{c['code']}: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()))
        if dry_run:
            conn.rollback()
            return counts
        conn.execute("SELECT set_config('app.client_ids', %s, true)", (str(cid),))
        for t in GUARDED:
            conn.execute(f"ALTER TABLE {t} DISABLE TRIGGER USER")
        steps = [
            ("DELETE FROM enquiry_communications WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiry_events WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiry_actions WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiry_items WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiries WHERE id = ANY(%s)", (enq,)),
            ("DELETE FROM reconciliation_exceptions WHERE client_id = %s", (cid,)),
            ("DELETE FROM reconciliation_sources WHERE client_id = %s", (cid,)),
            ("DELETE FROM reconciliation_items WHERE client_id = %s", (cid,)),
            ("DELETE FROM reconciliation_runs WHERE client_id = %s", (cid,)),
            ("UPDATE statements SET related_statement_id = NULL, superseded_by = NULL WHERE client_id = %s", (cid,)),
            ("DELETE FROM statements WHERE client_id = %s", (cid,)),
            ("DELETE FROM rd_job WHERE build_id = ANY(%s)", (builds,)),
            ("DELETE FROM rd_finding WHERE build_id = ANY(%s)", (builds,)),
            ("DELETE FROM rd_issue WHERE build_id = ANY(%s)", (builds,)),
            ("DELETE FROM rd_report WHERE build_id = ANY(%s)", (builds,)),
            ("DELETE FROM rd_decision WHERE build_id = ANY(%s) OR run_id = ANY(%s)", (builds, runs)),
            ("DELETE FROM rd_build WHERE id = ANY(%s)", (builds,)),
            ("DELETE FROM rd_run_file WHERE run_id = ANY(%s) OR file_id = ANY(%s)", (runs, drop)),
            ("DELETE FROM rd_run WHERE id = ANY(%s)", (runs,)),
            ("DELETE FROM rd_royalty_line WHERE file_id = ANY(%s)", (drop,)),
            ("DELETE FROM rd_platform_line WHERE file_id = ANY(%s)", (drop,)),
            ("DELETE FROM rd_prior WHERE file_id = ANY(%s)", (drop,)),
            ("DELETE FROM rd_song_entry WHERE file_id = ANY(%s)", (drop,)),
            ("DELETE FROM rd_file WHERE id = ANY(%s)", (drop,)),
        ]
        for sql, args in steps:
            conn.execute(sql, args)
        for t in GUARDED:
            conn.execute(f"ALTER TABLE {t} ENABLE TRIGGER USER")
        audit.record(conn, "maintenance.statements_cleared", actor, "client", cid,
                     dict(client=c["code"], reason=reason, kept="catalogue, settings, platforms, people, activity log",
                          **counts))
        conn.commit()
    gone = 0
    for bucket, keys in (("originals", objects), ("reports", reports)):
        for k in keys:
            try:
                p = storage._path(bucket, k)
                if p.exists():
                    p.unlink()
                    gone += 1
            except (OSError, storage.StorageError) as e:
                echo(f"  could not remove {bucket}/{k}: {e}")
    echo(f"done: {gone} stored file(s) removed")
    return dict(counts, files_removed=gone)


CATALOGUE_GUARDED = ("mapping_events", "work_recordings", "rd_song_entry", "rd_file", "reconciliation_runs",
                     "reconciliation_items", "reconciliation_sources", "enquiry_events", "enquiry_communications")


def clear_catalogue(code: str, reason: str, dry_run: bool = False, echo=print, actor: dict | None = None) -> dict:
    """Start the catalogue of a client again from nothing (the Super Admin's "Delete catalogue"): its works, ISRC links
    and their history, the catalogue imports and the uploaded song lists. Reconciliations and enquiries are built on the
    catalogue's works, so they go with it. Kept: the statements and reports (they find the new catalogue's works as
    soon as it is imported), clients, people, platforms, reconciliation settings and the activity log. A song list that
    a processing run used stays stored as that run's evidence."""
    with psycopg.connect(config.settings.migrator_database_url, row_factory=dict_row, autocommit=False) as conn:
        c = db.one(conn, "SELECT id, code, name FROM client WHERE code = %s", (code.strip().upper(),))
        if not c:
            raise ClearRefused(f"no client {code}")
        cid = c["id"]
        q = lambda sql, *a: [r["id"] for r in db.all(conn, sql, a or (cid,))]          # noqa: E731
        lists = q("SELECT id FROM rd_file WHERE client_id = %s AND (kind IN ('SONG_LIST', 'REVIEW_LIST') OR id IN "
                  "(SELECT file_id FROM catalogue_imports WHERE client_id = %s))", cid, cid)
        in_runs = set(q("SELECT DISTINCT file_id AS id FROM rd_run_file WHERE file_id = ANY(%s)", lists))
        in_statements = set(q("SELECT DISTINCT file_id AS id FROM statements WHERE file_id = ANY(%s)", lists))
        drop = [f for f in lists if f not in in_runs and f not in in_statements]
        enq = q("SELECT id FROM enquiries WHERE client_id = %s")
        objects = [r["object_key"] for r in db.all(conn, "SELECT object_key FROM rd_file WHERE id = ANY(%s) AND "
                                                         "object_key IS NOT NULL", (drop,))]
        counts = dict(
            works=db.scalar(conn, "SELECT count(*) FROM works WHERE client_id = %s", (cid,)),
            isrc_links=db.scalar(conn, "SELECT count(*) FROM work_recordings WHERE client_id = %s AND valid_to IS NULL",
                                 (cid,)),
            catalogue_imports=db.scalar(conn, "SELECT count(*) FROM catalogue_imports WHERE client_id = %s", (cid,)),
            song_list_files=len(drop), song_lists_kept_for_runs=len(lists) - len(drop),
            reconciliation_runs=db.scalar(conn, "SELECT count(*) FROM reconciliation_runs WHERE client_id = %s", (cid,)),
            enquiries=len(enq),
            statements_kept=db.scalar(conn, "SELECT count(*) FROM statements WHERE client_id = %s", (cid,)))
        echo(f"{c['code']}: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()))
        if dry_run:
            conn.rollback()
            return counts
        conn.execute("SELECT set_config('app.client_ids', %s, true)", (str(cid),))
        for t in CATALOGUE_GUARDED:
            conn.execute(f"ALTER TABLE {t} DISABLE TRIGGER USER")
        steps = [
            ("DELETE FROM enquiry_communications WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiry_events WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiry_actions WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiry_items WHERE enquiry_id = ANY(%s)", (enq,)),
            ("DELETE FROM enquiries WHERE id = ANY(%s)", (enq,)),
            ("DELETE FROM reconciliation_exceptions WHERE client_id = %s", (cid,)),
            ("DELETE FROM reconciliation_sources WHERE client_id = %s", (cid,)),
            ("DELETE FROM reconciliation_items WHERE client_id = %s", (cid,)),
            ("DELETE FROM reconciliation_runs WHERE client_id = %s", (cid,)),
            ("DELETE FROM mapping_events WHERE client_id = %s", (cid,)),
            ("DELETE FROM catalogue_import_rows WHERE client_id = %s", (cid,)),
            ("DELETE FROM work_recordings WHERE client_id = %s", (cid,)),
            ("DELETE FROM works WHERE client_id = %s", (cid,)),
            ("DELETE FROM catalogue_imports WHERE client_id = %s", (cid,)),
            ("DELETE FROM rd_song_entry WHERE file_id = ANY(%s)", (drop,)),
            ("DELETE FROM rd_file WHERE id = ANY(%s)", (drop,)),
            ("DELETE FROM recordings r WHERE NOT EXISTS (SELECT 1 FROM work_recordings wr WHERE wr.recording_id = "
             "r.id)", None),                               # ISRCs no client links any more
        ]
        for sql, args in steps:
            conn.execute(sql, args)
        for t in CATALOGUE_GUARDED:
            conn.execute(f"ALTER TABLE {t} ENABLE TRIGGER USER")
        audit.record(conn, "maintenance.catalogue_cleared", actor, "client", cid,
                     dict(client=c["code"], reason=reason, kept="statements, reports, settings, platforms, people, "
                                                               "activity log", **counts))
        conn.commit()
    gone = 0
    for k in objects:
        try:
            p = storage._path("originals", k)
            if p.exists():
                p.unlink()
                gone += 1
        except (OSError, storage.StorageError) as e:
            echo(f"  could not remove originals/{k}: {e}")
    echo(f"done: {gone} stored file(s) removed")
    return dict(counts, files_removed=gone)
