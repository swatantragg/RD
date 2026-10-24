"""The home dashboard: what is in the system for a client and what is waiting for someone."""
from __future__ import annotations

from .. import db
from . import access, enquiries


def overview(actor: dict, client_id: int) -> dict:
    with access.tx(actor, client_id) as conn:
        from .library import sync
        sync(conn, client_id)
        cat = db.one(conn, "SELECT count(*) AS works, count(*) FILTER (WHERE catalogue_status IN ('REVIEW', "
                           "'TO_REGISTER')) AS works_to_check FROM works WHERE client_id = %s AND deleted_at IS NULL",
                     (client_id,))
        cat.update(db.one(conn, "SELECT count(*) AS links, count(*) FILTER (WHERE mapping_status = 'PENDING') AS "
                                "pending FROM current_work_recordings WHERE client_id = %s", (client_id,)))
        cat["conflicts"] = db.scalar(conn, "SELECT count(*) FROM isrc_resolution WHERE client_id = %s AND "
                                           "mapping_status = 'CONFLICT'", (client_id,))
        sts = {r["import_status"]: r["n"] for r in db.all(conn, "SELECT import_status, count(*) AS n FROM statements "
                                                                 "WHERE client_id = %s GROUP BY 1", (client_id,))}
        # the statements that count: those received from IPRS, and the platform's reports per platform
        iprs = db.scalar(conn, "SELECT count(*) FROM statements WHERE client_id = %s AND statement_source = 'IPRS' AND "
                               "import_status = 'IMPORTED'", (client_id,))
        plats = db.all(conn, "SELECT coalesce(p.platform_name, 'Platform not stated') AS name, count(*) AS n FROM "
                             "statements s LEFT JOIN platforms p ON p.id = s.platform_id WHERE s.client_id = %s AND "
                             "s.statement_source = 'PLATFORM' AND s.import_status = 'IMPORTED' GROUP BY 1 ORDER BY 1",
                       (client_id,))
        runs = db.all(conn, "SELECT r.id, r.run_reference, r.usage_period_start, r.usage_period_end, r.summary, "
                            "r.started_at, p.platform_name FROM reconciliation_runs r JOIN platforms p ON p.id = "
                            "r.platform_id WHERE r.client_id = %s AND r.status = 'COMPLETED' ORDER BY r.id DESC LIMIT 4",
                      (client_id,))
        imports = db.scalar(conn, "SELECT count(*) FROM catalogue_imports WHERE client_id = %s AND status = 'PREVIEW'",
                            (client_id,))
    dash = enquiries.dashboard(actor, client_id)
    mine = [a for a in dash["actions"] if a["mine"]]
    return dict(catalogue=cat, statements=sts, statement_boxes=dict(iprs=iprs, platforms=plats), runs=runs,
                previews_waiting=imports,
                queues=dash["queues"], my_actions=mine[:8], overdue=sum(1 for a in dash["actions"] if a["overdue"]))
