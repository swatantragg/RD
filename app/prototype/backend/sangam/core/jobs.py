"""Background jobs (architecture §17.4).

The production design runs Celery workers behind Redis; the prototype runs the same job
functions on an in-process thread pool and keeps the identical job contract:
`queued | running | succeeded | failed`, progress, message and a log tail, polled through
GET /api/jobs/{id}. A per-batch lock stands in for the advisory lock on batch_id.
"""
from __future__ import annotations

import threading
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import config, db

_executor: ThreadPoolExecutor | None = None
_batch_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def batch_lock(batch_id: int) -> threading.Lock:
    with _locks_guard:
        return _batch_locks[batch_id]


class JobContext:
    def __init__(self, job_id: int, conn):
        self.job_id = job_id
        self.conn = conn
        self._log: list[str] = []

    def log(self, msg: str) -> None:
        self._log.append(f"[{db.now()[11:]}] {msg}")
        tail = "\n".join(self._log[-200:])
        self.conn.execute("UPDATE job SET log = ?, message = ? WHERE id = ?", (tail, msg, self.job_id))

    def progress(self, p: float, msg: str | None = None) -> None:
        self.conn.execute("UPDATE job SET progress = ? WHERE id = ?", (max(0.0, min(1.0, p)), self.job_id))
        if msg:
            self.log(msg)


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=config.JOB_WORKERS, thread_name_prefix="sangam-job")
    return _executor


def create(conn, kind: str, *, batch_id=None, build_id=None, ref_id=None, user=None) -> int:
    with db.tx(conn):
        return db.insert(conn, "job", dict(kind=kind, batch_id=batch_id, build_id=build_id,
                                           ref_id=ref_id, status="queued", progress=0.0,
                                           message="queued", log="", created_at=db.now(),
                                           created_by=user))


def run(job_id: int, fn: Callable[[JobContext, object], dict | None]) -> dict:
    """Execute a job synchronously in the calling thread (used by the pool and the CLI)."""
    conn = db.connect()
    conn.execute("UPDATE job SET status='running', started_at=?, message='running' WHERE id=?",
                 (db.now(), job_id))
    ctx = JobContext(job_id, conn)
    try:
        result = fn(ctx, conn) or {}
        conn.execute("UPDATE job SET status='succeeded', progress=1, finished_at=?, "
                     "result_json=?, message=? WHERE id=?",
                     (db.now(), db.dumps(result), result.get("message", "done"), job_id))
        return result
    except Exception as e:                                   # noqa: BLE001 - surfaced to the UI
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        ctx.log(f"FAILED: {e}")
        conn.execute("UPDATE job SET status='failed', finished_at=?, error=?, message=? WHERE id=?",
                     (db.now(), traceback.format_exc(limit=8), str(e)[:500], job_id))
        raise
    finally:
        conn.close()


def submit(conn, kind: str, fn: Callable[[JobContext, object], dict | None], **kw) -> int:
    job_id = create(conn, kind, **kw)

    def _target():
        try:
            run(job_id, fn)
        except Exception:                                    # noqa: BLE001 - already recorded
            pass
    _get_executor().submit(_target)
    return job_id


def get(conn, job_id: int) -> dict | None:
    j = db.row(conn, "SELECT * FROM job WHERE id = ?", (job_id,))
    if j:
        j["result"] = db.loads(j.pop("result_json"), {})
    return j
