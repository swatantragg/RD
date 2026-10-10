"""Background work in a PostgreSQL job table (claimed with SKIP LOCKED), so processing survives the browser closing
and a worker that dies leaves a visible, retryable failure - never a half-made report.

Two kinds of job, told apart by the build's state:
  QUEUED build             -> process: load the run's files, build, check, write the draft reports
  SUBMITTED + approved_by  -> publish (asked for by the preparer; approved_by holds who published): build again from
                              the same inputs, prove the numbers are identical, write the final reports under the
                              next generation name (e.g. SVF-RD-SKV9)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading
import traceback
from decimal import Decimal

from .. import audit, db, storage
from . import access, assemble, engine, excel, rules, verify
from .model import PLATFORM_REVENUE, PLATFORM_USAGE, PREVIOUS_OUTPUT, SONG_LIST, STATEMENT
from .service import SOFTWARE, _client, _run_files, run_checks
from .store import load_data

log = logging.getLogger("mrm.rd.jobs")
ZERO = Decimal("0")
_wake = threading.Event()
_started = False
STALE_MINUTES = 20


def wake() -> None:
    _wake.set()


def start_worker() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="rd-worker", daemon=True).start()


def run_forever() -> None:
    _loop()


def _loop() -> None:
    while True:
        try:
            while run_one():
                pass
            sweep()
        except Exception:                                        # noqa: BLE001
            log.exception("worker loop")
        _wake.wait(timeout=5)
        _wake.clear()


def sweep() -> None:
    """A job whose worker stopped answering is marked failed, with a message the user can act on."""
    with db.tx() as conn:
        stale = db.all(conn, "SELECT id, build_id, client_id FROM rd_job WHERE state = 'RUNNING' AND heartbeat_at < "
                             "now() - make_interval(mins => %s)", (STALE_MINUTES,))
        for j in stale:
            access.set_scope(conn, [j["client_id"]])
            conn.execute("UPDATE rd_job SET state = 'FAILED', finished_at = now() WHERE id = %s", (j["id"],))
            b = db.one(conn, "SELECT state FROM rd_build WHERE id = %s", (j["build_id"],))
            if b and b["state"] in ("QUEUED", "RUNNING"):
                conn.execute("UPDATE rd_build SET state = 'FAILED', error = %s, finished_at = now() WHERE id = %s",
                             ("Processing stopped unexpectedly. No reports were produced. Please process the files "
                              "again.", j["build_id"]))


def run_one() -> bool:
    with db.tx() as conn:
        j = db.one(conn, "SELECT * FROM rd_job WHERE state = 'QUEUED' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1")
        if not j:
            return False
        conn.execute("UPDATE rd_job SET state = 'RUNNING', attempts = attempts + 1, started_at = now(), "
                     "heartbeat_at = now() WHERE id = %s", (j["id"],))
    ok = False
    try:
        with access.tx(None, j["client_id"]) as conn:
            b = db.one(conn, "SELECT state, approved_by FROM rd_build WHERE id = %s", (j["build_id"],))
        if b["state"] == "QUEUED":
            ok = process(j["build_id"], j["client_id"], j["id"])
        elif b["state"] == "SUBMITTED" and b["approved_by"]:
            ok = publish(j["build_id"], j["client_id"], j["id"])
    except Exception:                                            # noqa: BLE001
        log.exception("job %s", j["id"])
    with db.tx() as conn:
        conn.execute("UPDATE rd_job SET state = %s, finished_at = now() WHERE id = %s",
                     ("DONE" if ok else "FAILED", j["id"]))
    return True


def run_pending() -> int:
    n = 0
    while run_one():
        n += 1
    return n


# ================================================================== processing
def _stage(build_id: int, client_id: int, job_id: int, idx: int, state: str, extra: dict | None = None) -> None:
    with access.tx(None, client_id) as conn:
        b = db.one(conn, "SELECT stages FROM rd_build WHERE id = %s", (build_id,))
        stages = b["stages"]
        stages[idx]["state"] = state
        vals = dict(stages=db.J(stages), heartbeat_at=dt.datetime.now(dt.timezone.utc))
        if extra:
            vals.update({k: db.J(v) if isinstance(v, (list, dict)) else v for k, v in extra.items()})
        db.update(conn, "rd_build", build_id, vals)
    with db.tx() as conn:
        conn.execute("UPDATE rd_job SET heartbeat_at = now() WHERE id = %s", (job_id,))


def _fail(build_id: int, client_id: int, stage: int | None, user_msg: str, detail: str) -> None:
    with access.tx(None, client_id) as conn:
        b = db.one(conn, "SELECT stages FROM rd_build WHERE id = %s", (build_id,))
        stages = b["stages"]
        if stage is not None:
            stages[stage]["state"] = "FAILED"
        db.update(conn, "rd_build", build_id, dict(state="FAILED", stages=db.J(stages), error=user_msg,
                                                   error_detail=detail[:20000],
                                                   finished_at=dt.datetime.now(dt.timezone.utc)))
        audit.record(conn, "build.failed", None, "rd_build", build_id, dict(error=user_msg))


def load_inputs(conn, build: dict) -> tuple[engine.RunInput, list[dict], list[dict], dict]:
    run = db.one(conn, "SELECT * FROM rd_run WHERE id = %s", (build["run_id"],))
    c = _client(conn, run["client_id"])
    files = _run_files(conn, run["id"])
    chk = run_checks(conn, run, files)
    inp = engine.RunInput(client_code=c["code"], client_name=c["name"], ruleset=rules.RULESET_V1)
    inputs = []
    for f in chk["used"]:
        if f["status"] != "READY":
            continue
        data = load_data(conn, f["id"], f["kind"], f["facts"])
        m = dict(f["meta"])
        if f["kind"] == STATEMENT:
            src = assemble.statement_src(f["id"], f["filename"], data, m)
            if (f["choice"] or {}).get("relation") == "SUPPLEMENTARY":
                src.relation = "SUPPLEMENTARY"
                src.identity_key += f"#supplementary:{f['id']}"
            inp.statements.append(src)
        elif f["kind"] == PLATFORM_REVENUE:
            inp.platforms.append(assemble.platform_src(f["id"], f["filename"], data, m))
        elif f["kind"] == PLATFORM_USAGE:
            inp.usages.append(assemble.usage_src(f["id"], f["filename"], data, m))
        elif f["kind"] == SONG_LIST:
            inp.song_list = assemble.list_src(f["id"], f["filename"], data, m)
        elif f["kind"] == PREVIOUS_OUTPUT:
            inp.prior = assemble.prior_src(f["id"], f["filename"], data, m)
        inputs.append(dict(file_id=f["id"], filename=f["filename"], kind=f["kind"], label=f["label"],
                           sha256=f["sha256"], total=(f["summary"] or {}).get("total"),
                           check="PASS" if f["status"] == "READY" else f["status"], included="yes"))
    people = {r["id"]: r["name"] for r in db.all(conn, "SELECT id, name FROM app_user")}
    decisions = []
    for d in db.all(conn, "SELECT * FROM rd_decision WHERE client_id = %s AND state = 'ACTIVE' ORDER BY id",
                    (run["client_id"],)):
        if d["kind"] == "SONG_STATUS":
            s, v = d["subject"], d["value"]
            inp.reviews.append(engine.ReviewMark(isrcs=s.get("isrcs") or [], work_nos=s.get("work_nos") or [],
                                                 status=v["status"], original=v.get("original") or "",
                                                 note=v.get("note") or "", source=d["source"] or "", ref=d["id"]))
        else:
            inp.decisions.append(engine.Decision(id=d["id"], kind=d["kind"], subject=d["subject"], value=d["value"],
                                                 approved_by=people.get(d["made_by"], "")))
            from .service import _decision_text
            decisions.append(dict(id=d["id"], text=_decision_text(d), made_by=people.get(d["made_by"]),
                                  reason=d["reason"]))
    return inp, inputs, decisions, dict(client=c, run=run, left_out=chk["left_out"], people=people)


def _draft_name(c: dict, build: dict) -> tuple[str, str]:
    s = c.get("settings") or {}
    prefix = s.get("output_prefix") or f"{c['code']}-RD-SKV"
    nxt = int(s.get("next_generation") or 1)
    return f"{prefix}{nxt}", prefix


def process(build_id: int, client_id: int, job_id: int) -> bool:
    stage = 0
    try:
        with access.tx(None, client_id) as conn:
            db.update(conn, "rd_build", build_id, dict(state="RUNNING", started_at=dt.datetime.now(dt.timezone.utc),
                                                       heartbeat_at=dt.datetime.now(dt.timezone.utc)))
            build = db.one(conn, "SELECT * FROM rd_build WHERE id = %s", (build_id,))
        _stage(build_id, client_id, job_id, 0, "RUNNING")
        with access.tx(None, client_id) as conn:
            inp, inputs, decisions, ctx = load_inputs(conn, build)
        _stage(build_id, client_id, job_id, 0, "DONE")
        stage = 1
        _stage(build_id, client_id, job_id, 1, "RUNNING")
        n_lines = sum(len(s.lines) for s in inp.statements)
        _stage(build_id, client_id, job_id, 1, "DONE")
        stage = 2
        _stage(build_id, client_id, job_id, 2, "RUNNING")
        gen, _prefix = _draft_name(ctx["client"], build)
        inp.generation = gen
        res = engine.build(inp)
        checks = res.checks + verify.master(res)
        failed = [c for c in checks if not c["ok"] and c.get("blocking", True)]
        if failed:
            _fail(build_id, client_id, 2, "The financial checks did not pass, so no reports were produced: "
                  + "; ".join(c["text"] for c in failed[:3]) + ". Please contact your administrator with this run.",
                  "\n".join(f"{c['id']} {c['text']}: {c.get('detail')}" for c in failed))
            return False
        _stage(build_id, client_id, job_id, 2, "DONE", dict(checks=checks))
        stage = 3
        _stage(build_id, client_id, job_id, 3, "RUNNING")
        _save_review(build_id, client_id, res)
        _stage(build_id, client_id, job_id, 3, "DONE")
        stage = 4
        _stage(build_id, client_id, job_id, 4, "RUNNING")
        summary = _summary(res, inp, n_lines)
        reports = write_reports(res, ctx, build, gen, "DRAFT", inputs, decisions, final=False)
        _save_reports(build_id, client_id, reports, final=False)
        with access.tx(None, client_id) as conn:
            b = db.one(conn, "SELECT stages FROM rd_build WHERE id = %s", (build_id,))
            stages = b["stages"]
            stages[4]["state"] = "DONE"
            db.update(conn, "rd_build", build_id, dict(
                state="CHECKED", stages=db.J(stages), summary=db.J(_jsonable(summary)),
                checks=db.J(checks + reports["checks"]), notices=db.J(res.notices), inputs=db.J(inputs),
                decisions_sha256=hashlib.sha256(
                    ",".join(str(d.id) for d in inp.decisions).encode()).hexdigest(),
                finished_at=dt.datetime.now(dt.timezone.utc)))
            audit.record(conn, "build.checked", None, "rd_build", build_id, dict(royalty=summary["royalty"]))
        return True
    except Exception as e:                                       # noqa: BLE001
        _fail(build_id, client_id, stage, "Something went wrong while processing, so no reports were produced. "
              "Please try again; if it happens again, contact your administrator.",
              f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return False


def _summary(res: engine.Result, inp: engine.RunInput, n_lines: int) -> dict:
    t = res.totals
    by_status: dict = {}
    for r in res.findings:
        k = r.review.status if r.review else rules.NEW
        by_status[k] = by_status.get(k, 0) + 1
    recon = [dict(label=s.label, section=s.section, total=str(s.printed_total), ok=True) for s in res.statements]
    return dict(royalty=str(t["royalty"]), platform={b.total_header: str(t["platform"].get(b.key, ZERO))
                                                     for b in res.bands if b.kind == "PLATFORM"},
                statements=len(res.statements), platform_reports=len(res.platforms), lines=n_lines,
                rows=t["rows"], matched_rows=t["matched_rows"], held_rows=t["held_rows"],
                held_royalty=str(t["held_royalty"]), held_platform=str(t["held_platform"]),
                missing=t["missing"], not_ours=t["not_ours"], unreviewed=t["unreviewed"], findings_by_status=by_status,
                distributions=t["distributions"], platform_months=t["platform_months"], base=res.base_label,
                grain=res.grain, reconciliation=recon,
                review_items=sum(1 for i in res.issues if i["severity"] in ("REVIEW", "BLOCKING")),
                money_items=sum(1 for i in res.issues if i["category"] == "MONEY"),
                matching_items=sum(1 for i in res.issues if i["category"] == "MATCHING"))


def _save_review(build_id: int, client_id: int, res: engine.Result) -> None:
    with access.tx(None, client_id) as conn:
        for n, i in enumerate(res.issues, 1):
            db.insert(conn, "rd_issue", dict(build_id=build_id, client_id=client_id, issue_no=n, kind=i["kind"],
                                             severity=i["severity"], category=i["category"], title=i["title"],
                                             message=i["message"], subject=_jsonable(i["subject"]),
                                             actions=db.J(i["actions"])), returning=None)
        rows = []
        for n, r in enumerate(res.findings, 1):
            p = r.proposals[0] if r.proposals and r.proposals[0]["band"] != "unlikely" else None
            src = "IPRS statement" if r.origin == "work" else "platform report"
            rows.append((build_id, client_id, n, r.key, r.title, r.all_isrcs, r.all_works, r.royalty,
                         sum(r.platform.values(), ZERO), r.review.status if r.review else rules.NEW,
                         r.review.original if r.review else None, src, p))
        db.insert_many(conn, "rd_finding", ("build_id", "client_id", "finding_no", "row_key", "title", "isrcs",
                                            "work_nos", "royalty", "platform", "status", "status_original", "sources",
                                            "proposal"), rows)


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


def write_reports(res: engine.Result, ctx: dict, build: dict, generation: str, state: str, inputs: list[dict],
                  decisions: list[dict], final: bool) -> dict:
    c = ctx["client"]
    ref = f"run {build['run_id']} v{build['version']}"
    suffix = "" if final else f"-DRAFT-{build['run_id']}.{build['version']}"
    names_ = ctx.get("people") or {}
    data, meta = excel.master(res, client_code=c["code"], generation=generation, state=state, build_ref=ref,
                              ruleset=rules.RULESET_V1, software=SOFTWARE, inputs=inputs, left_out=ctx["left_out"],
                              decisions=decisions,
                              people={"prepared_by": names_.get(build.get("created_by")),
                                      "approved_by": names_.get(build.get("approved_by"))})
    out = dict(checks=[], files=[], meta=meta)
    out["files"].append(dict(kind="MASTER", filename=f"{generation}{suffix}.xlsx", data=data, rows=len(res.rows),
                             available=True, reason=None,
                             totals=dict(royalty=str(res.totals["royalty"]),
                                         platform={k: str(v) for k, v in res.totals["platform"].items()})))
    combined = bool(rules.RULESET_V1.get("companion_combined_total", True))
    has_base = bool(res.base_label)
    for kind, status, fname, empty_reason in (
            ("MISSING", None, f"Missing-Songs-Revenue-{generation}{suffix}.xlsx",
             "No song list or previous report was included in this run, so we cannot tell which paid songs are "
             "missing from it. Add the client's song list and process again."),
            ("NON_CLIENT", rules.NOT_OURS, f"Non-{c['code']}-Works-Revenue-{generation}{suffix}.xlsx",
             "No song has been marked 'Not ours' yet, so there is nothing for this report. Review the missing songs "
             "first, then process again.")):
        if not has_base:
            out["files"].append(dict(kind=kind, filename=fname, data=None, rows=0, available=False,
                                     reason=empty_reason if kind == "MISSING" else
                                     "This report needs a song list (to find missing songs) and reviewed statuses.",
                                     totals={}))
            continue
        groups = excel.companion_groups(res, status)
        out["checks"] += verify.companion(res, groups)
        bad = [x for x in out["checks"] if not x["ok"]]
        if bad:
            raise RuntimeError("companion check failed: " + "; ".join(f"{x['id']} {x['detail']}" for x in bad))
        if kind == "NON_CLIENT" and not groups:
            out["files"].append(dict(kind=kind, filename=fname, data=None, rows=0, available=False,
                                     reason=empty_reason, totals={}))
            continue
        d = excel.companion(res, groups, kind=kind, client_code=c["code"], client_name=c["name"],
                            generation=generation, state=state, combined_total=combined)
        out["files"].append(dict(kind=kind, filename=fname, data=d, rows=len(groups), available=True, reason=None,
                                 totals=dict(royalty=str(sum((g["royalty"] for g in groups), ZERO)),
                                             platform=str(sum((sum(g["platform"].values(), ZERO) for g in groups),
                                                              ZERO)))))
    return out


def _save_reports(build_id: int, client_id: int, reports: dict, final: bool) -> None:
    with access.tx(None, client_id) as conn:
        code = db.scalar(conn, "SELECT code FROM client WHERE id = %s", (client_id,))
        for f in reports["files"]:
            key = sha = None
            if f["data"] is not None:
                sha = hashlib.sha256(f["data"]).hexdigest()
                key = f"{code}/{build_id}/{'final' if final else 'draft'}/{sha}.xlsx"
                storage.put("reports", key, f["data"])
            db.insert(conn, "rd_report", dict(build_id=build_id, client_id=client_id, kind=f["kind"], final=final,
                                              filename=f["filename"], object_key=key, sha256=sha,
                                              bytes=len(f["data"]) if f["data"] else None, rows=f["rows"],
                                              available=f["available"], reason=f["reason"],
                                              totals=db.J(_jsonable(f["totals"]))),
                      returning=None)


# ================================================================== publishing
def publish(build_id: int, client_id: int, job_id: int) -> bool:
    """Rebuild from the same inputs, prove the numbers are unchanged, write the final reports."""
    try:
        with access.tx(None, client_id) as conn:
            build = db.one(conn, "SELECT * FROM rd_build WHERE id = %s", (build_id,))
            inp, inputs, decisions, ctx = load_inputs(conn, build)
            from .service import _inputs_sha
            used = run_checks(conn, ctx["run"], _run_files(conn, build["run_id"]))["used"]
            if _inputs_sha(conn, ctx["run"], used) != build["inputs_sha256"]:
                raise PublishRefused("Files, answers or review decisions changed after this version was processed. "
                                     "Process the files again, then publish the new version.")
            c = ctx["client"]
            s = c.get("settings") or {}
            prefix = s.get("output_prefix") or f"{c['code']}-RD-SKV"
            last = db.scalar(conn, "SELECT max(generation_no) FROM rd_build WHERE client_id = %s", (client_id,))
            gen_no = max(int(s.get("next_generation") or 1), (last or 0) + 1)
        generation = f"{prefix}{gen_no}"
        inp.generation = generation
        res = engine.build(inp)
        checks = res.checks + verify.master(res)
        if not all(c["ok"] for c in checks if c.get("blocking", True)):
            raise PublishRefused("The financial checks did not pass when the final reports were prepared.")
        if str(res.totals["royalty"]) != str(build["summary"].get("royalty")):
            raise PublishRefused("The numbers changed since this version was checked. Process the files again.")
        reports = write_reports(res, ctx, build, generation, "PUBLISHED", inputs, decisions, final=True)
        _save_reports(build_id, client_id, reports, final=True)
        with access.tx(None, client_id) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(84726101, %s)", (client_id,))
            for prev in db.all(conn, "SELECT id FROM rd_build WHERE client_id = %s AND state = 'PUBLISHED'",
                               (client_id,)):
                conn.execute("UPDATE rd_build SET state = 'SUPERSEDED' WHERE id = %s", (prev["id"],))
            db.update(conn, "rd_build", build_id, dict(state="PUBLISHED", generation=generation, generation_no=gen_no,
                                                       published_at=dt.datetime.now(dt.timezone.utc)))
            s = dict(c.get("settings") or {})
            s["next_generation"] = gen_no + 1
            db.update(conn, "client", client_id, dict(settings=s))
            audit.record(conn, "build.published", None, "rd_build", build_id, dict(
                generation=generation, master_sha256=[hashlib.sha256(f["data"]).hexdigest()
                                                      for f in reports["files"] if f["kind"] == "MASTER"][0],
                values_sha256=reports["meta"]["values_sha256"]))
        return True
    except PublishRefused as e:
        with access.tx(None, client_id) as conn:
            conn.execute("UPDATE rd_build SET approved_by = NULL, approved_at = NULL, returned_reason = %s, "
                         "state = 'CHECKED' WHERE id = %s", (str(e), build_id))
            audit.record(conn, "build.publish_refused", None, "rd_build", build_id, dict(reason=str(e)))
        return False
    except Exception as e:                                       # noqa: BLE001
        log.exception("publish %s", build_id)
        with access.tx(None, client_id) as conn:
            conn.execute("UPDATE rd_build SET approved_by = NULL, approved_at = NULL, returned_reason = %s, "
                         "state = 'CHECKED' WHERE id = %s",
                         ("Publishing failed - nothing was published. Please try again; if it happens again, "
                          "contact your administrator.", build_id))
            audit.record(conn, "build.publish_failed", None, "rd_build", build_id, dict(error=f"{type(e).__name__}: {e}"))
        return False


class PublishRefused(Exception):
    pass
