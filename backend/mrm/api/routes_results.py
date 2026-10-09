"""E-H: rules, comparison runs, report packs, enquiry cases."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response

from .. import cases, compare, db, packs, rules, storage
from ..normalize import s
from .deps import J, actor, need, page

router = APIRouter()


# ------------------------------------------------------------------ rules
@router.get("/rules")
def rule_list(client_id: int | None = None, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT r.*, c.name AS created_by_name, a.name AS approved_by_name, o.name AS owner_name, "
                              "cl.code AS client_code FROM rule_version r JOIN app_user c ON c.id = r.created_by LEFT "
                              "JOIN app_user a ON a.id = r.approved_by LEFT JOIN app_user o ON o.id = r.owner_id LEFT "
                              "JOIN client cl ON cl.id = r.client_id WHERE %s::BIGINT IS NULL OR r.client_id IS NULL OR "
                              "r.client_id = %s ORDER BY r.rule_key, r.version_no DESC", (client_id, client_id)))


@router.post("/rules")
def rule_draft(body: dict = Body(...), a: dict = Depends(need("rule_draft"))):
    with db.tx() as conn:
        rid = rules.draft(conn, a, body.get("client_id") or None, s(body.get("rule_key")) or "RULE",
                          body.get("values") or {}, body.get("reason"))
        return J(db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (rid,)))


@router.patch("/rules/{rid}")
def rule_revise(rid: int, body: dict = Body(...), a: dict = Depends(need("rule_draft"))):
    with db.tx() as conn:
        nid = rules.revise(conn, a, rid, body.get("values") or {}, body.get("reason"))
        return J(db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (nid,)))


@router.post("/rules/{rid}/approve")
def rule_approve(rid: int, a: dict = Depends(need("rule_approve"))):
    with db.tx() as conn:
        return J(rules.approve(conn, a, rid))


@router.post("/rules/{rid}/retire")
def rule_retire(rid: int, body: dict = Body(...), a: dict = Depends(need("rule_approve"))):
    with db.tx() as conn:
        rules.retire(conn, a, rid, body.get("reason"))
    return J({"ok": True})


@router.delete("/rules/{rid}")
def rule_discard(rid: int, a: dict = Depends(need("rule_draft"))):
    with db.tx() as conn:
        rules.delete_draft(conn, a, rid)
    return J({"ok": True})


@router.get("/rules/{rid}/check")
def rule_check(rid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        r = db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (rid,))
    return J(dict(problems=rules.completeness(r)))


# ------------------------------------------------------------------ comparison runs
@router.get("/runs")
def run_list(client_id: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT r.id, r.version_no, r.platform, r.territory, r.use_type, r.right_scope, "
                              "r.period_from, r.period_to, r.cutoff, r.status, r.summary, r.created_at, u.name AS "
                              "created_by_name, (SELECT version_no FROM identity_version WHERE id = "
                              "r.identity_version_id) AS identity_version FROM comparison_run r JOIN app_user u ON "
                              "u.id = r.created_by WHERE r.client_id = %s ORDER BY r.id DESC", (client_id,)))


@router.get("/runs/scopes")
def scopes(client_id: int, _: dict = Depends(actor)):
    """Scope suggestions from validated files."""
    with db.tx() as conn:
        return J(db.all(conn, "SELECT id, filename, income_type, meta->>'platform' AS platform, meta->>'territory' AS "
                              "territory, meta->>'use_type' AS use_type, meta->>'period_from' AS period_from, "
                              "meta->>'period_to' AS period_to FROM source_file WHERE client_id = %s AND status = "
                              "'VALIDATED' AND income_type IN ('PUBLISHING', 'RECORDING', 'USAGE') ORDER BY id",
                        (client_id,)))


@router.post("/runs")
def run_start(body: dict = Body(...), a: dict = Depends(need("run"))):
    with db.tx() as conn:
        r = compare.run(conn, a, int(body["client_id"]), s(body.get("platform")), s(body.get("territory")),
                        s(body.get("use_type")), s(body.get("right_scope")), body.get("period_from"),
                        body.get("period_to"), body.get("cutoff"), int(body.get("distribution_lag_months") or 6))
    return J(r)


@router.get("/runs/{rid}")
def run_detail(rid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        r = db.one(conn, "SELECT r.*, u.name AS created_by_name, v.version_no AS identity_version, c.name AS client_name, "
                         "c.code AS client_code FROM comparison_run r JOIN app_user u ON u.id = r.created_by JOIN "
                         "identity_version v ON v.id = r.identity_version_id JOIN client c ON c.id = r.client_id WHERE "
                         "r.id = %s", (rid,))
        r["files"] = db.all(conn, "SELECT id, filename, income_type, status FROM source_file WHERE id = ANY(%s)",
                            (r["file_ids"],))
        r["packs"] = db.all(conn, "SELECT p.id, p.version_no, p.status, p.built_at, u.name AS built_by_name FROM "
                                  "report_pack p JOIN app_user u ON u.id = p.built_by WHERE p.run_id = %s ORDER BY "
                                  "p.version_no DESC", (rid,))
        r["exception_counts"] = db.all(conn, "SELECT kind, count(*) AS n, sum(amount) AS amount FROM run_exception "
                                             "WHERE run_id = %s GROUP BY 1 ORDER BY 2 DESC", (rid,))
    return J(r)


SORTS = {"gap": "positive_gap DESC NULLS LAST, r_amount DESC NULLS LAST", "r": "r_amount DESC NULLS LAST",
         "p": "p_amount DESC NULLS LAST", "title": "title", "work": "work_code", "default": "id"}


@router.get("/runs/{rid}/groups")
def groups(rid: int, outcome: str | None = None, reason: str | None = None, q: str | None = None,
           sort: str = "default", limit: int | None = None, offset: int | None = None, _: dict = Depends(actor)):
    n, o = page(limit, offset)
    qq = f"%{s(q)}%" if s(q) else None
    where = ("run_id = %(r)s AND (%(o)s::TEXT IS NULL OR outcome = %(o)s) AND (%(h)s::TEXT IS NULL OR hold_reason = "
             "%(h)s) AND (%(q)s::TEXT IS NULL OR title ILIKE %(q)s OR work_code ILIKE %(q)s OR case_code ILIKE %(q)s "
             "OR array_to_string(isrcs, ' ') ILIKE %(q)s)")
    p = dict(r=rid, o=outcome or None, h=reason or None, q=qq, n=n, off=o)
    with db.tx() as conn:
        total = db.scalar(conn, f"SELECT count(*) FROM comparison_group WHERE {where}", p)
        rows = db.all(conn, f"SELECT id, case_code, work_code, title, film, isrcs, r_amount, n_streams, p_amount, "
                            f"p_status, b_amount, b_stream, variance, positive_gap, provisional, outcome, hold_reason, "
                            f"method, route, currency, limitations FROM comparison_group WHERE {where} ORDER BY "
                            f"{SORTS.get(sort, 'id')}, id LIMIT %(n)s OFFSET %(off)s", p)
    return J(dict(rows=rows, total=total))


@router.get("/groups/{gid}")
def group(gid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        g = db.one(conn, "SELECT g.*, r.rule_key, r.version_no AS rule_version, r.rate, r.share_treatment, "
                         "r.denominator, r.revenue_basis FROM comparison_group g LEFT JOIN rule_version r ON r.id = "
                         "g.rule_version_id WHERE g.id = %s", (gid,))
        ids = {x["file_id"] for k in ("r_rows", "n_rows", "p_rows") for x in g["evidence"][k]}
        g["files"] = {str(f["id"]): f["filename"] for f in db.all(conn, "SELECT id, filename FROM source_file WHERE "
                                                                        "id = ANY(%s)", (list(ids),))}
        g["case"] = db.one(conn, "SELECT id, case_code, status FROM enquiry_case WHERE group_key = %s",
                           (g["group_key"],))
    return J(g)


@router.get("/runs/{rid}/exceptions")
def exceptions(rid: int, kind: str | None = None, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT * FROM run_exception WHERE run_id = %s AND (%s::TEXT IS NULL OR kind = %s) "
                              "ORDER BY amount DESC NULLS LAST, id LIMIT 1000", (rid, kind, kind)))


# ------------------------------------------------------------------ packs
PACK_SQL = ("SELECT p.*, b.name AS built_by_name, a.name AS approved_by_name, sd.name AS sent_by_name, r.version_no "
            "AS run_version, r.platform, r.period_from, r.period_to FROM report_pack p JOIN app_user b ON b.id = "
            "p.built_by LEFT JOIN app_user a ON a.id = p.approved_by LEFT JOIN app_user sd ON sd.id = p.sent_by JOIN "
            "comparison_run r ON r.id = p.run_id")


@router.get("/packs")
def pack_list(client_id: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, PACK_SQL + " WHERE p.client_id = %s ORDER BY p.id DESC", (client_id,)))


@router.post("/runs/{rid}/packs")
def pack_build(rid: int, body: dict = Body(default={}), a: dict = Depends(need("pack_build"))):
    with db.tx() as conn:
        p = packs.build(conn, a, rid, s(body.get("note")) or None)
        return J(db.one(conn, PACK_SQL + " WHERE p.id = %s", (p["id"],)))


@router.get("/packs/{pid}")
def pack_detail(pid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.one(conn, PACK_SQL + " WHERE p.id = %s", (pid,)))


@router.get("/packs/{pid}/download")
def pack_download(pid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        p = db.one(conn, PACK_SQL + " WHERE p.id = %s", (pid,))
        c = db.one(conn, "SELECT code FROM client WHERE id = %s", (p["client_id"],))
    data = storage.get("packs", p["object_key"])
    name = f"MRM-{c['code']}-{p['platform']}-run{p['run_version']}-pack-v{p['version_no']}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/packs/{pid}/approve")
def pack_approve(pid: int, body: dict = Body(default={}), a: dict = Depends(need("pack_approve"))):
    with db.tx() as conn:
        packs.approve(conn, a, pid, s(body.get("note")) or None)
        return J(db.one(conn, PACK_SQL + " WHERE p.id = %s", (pid,)))


@router.post("/packs/{pid}/revise")
def pack_revise(pid: int, body: dict = Body(...), a: dict = Depends(need("pack_approve"))):
    with db.tx() as conn:
        packs.request_revision(conn, a, pid, body.get("note"))
        return J(db.one(conn, PACK_SQL + " WHERE p.id = %s", (pid,)))


@router.post("/packs/{pid}/sent")
def pack_sent(pid: int, body: dict = Body(...), a: dict = Depends(need("send"))):
    with db.tx() as conn:
        packs.mark_sent(conn, a, pid, body.get("reference"), body.get("follow_up"), body.get("sent_on"))
        return J(db.one(conn, PACK_SQL + " WHERE p.id = %s", (pid,)))


# ------------------------------------------------------------------ cases
@router.get("/cases")
def case_list(client_id: int, status: str | None = None, q: str | None = None, due: bool = False,
              limit: int | None = None, offset: int | None = None, _: dict = Depends(actor)):
    n, o = page(limit, offset)
    qq = f"%{s(q)}%" if s(q) else None
    where = ("e.client_id = %(c)s AND (%(s)s::TEXT IS NULL OR e.status = %(s)s) AND (%(q)s::TEXT IS NULL OR e.title "
             "ILIKE %(q)s OR e.case_code ILIKE %(q)s OR e.work_code ILIKE %(q)s) AND (NOT %(d)s OR (e.follow_up_date "
             "<= current_date AND e.status NOT LIKE 'CLOSED%%'))")
    p = dict(c=client_id, s=status or None, q=qq, d=due, n=n, o=o)
    with db.tx() as conn:
        total = db.scalar(conn, f"SELECT count(*) FROM enquiry_case e WHERE {where}", p)
        rows = db.all(conn, f"SELECT e.*, g.outcome, g.r_amount, g.b_amount, g.p_amount, g.variance, g.p_status, "
                            f"u.name AS owner_name FROM enquiry_case e LEFT JOIN comparison_group g ON g.id = "
                            f"e.latest_group_id LEFT JOIN app_user u ON u.id = e.owner_id WHERE {where} ORDER BY "
                            f"g.positive_gap DESC NULLS LAST, e.id LIMIT %(n)s OFFSET %(o)s", p)
        counts = db.all(conn, "SELECT status, count(*) AS n FROM enquiry_case WHERE client_id = %s GROUP BY 1",
                        (client_id,))
    return J(dict(rows=rows, total=total, counts=counts))


@router.get("/cases/{cid}")
def case_detail(cid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        c = db.one(conn, "SELECT e.*, u.name AS owner_name FROM enquiry_case e LEFT JOIN app_user u ON u.id = "
                         "e.owner_id WHERE e.id = %s", (cid,))
        c["history"] = cases.history(conn, cid)
        c["group"] = db.one(conn, "SELECT id, run_id, outcome, hold_reason, r_amount, n_streams, b_amount, p_amount, "
                                  "variance, positive_gap, p_status, question, limitations, method FROM "
                                  "comparison_group WHERE id = %s", (c["latest_group_id"],))
        c["runs"] = db.all(conn, "SELECT g.id, r.version_no, g.outcome, g.r_amount, g.b_amount, g.p_amount, g.variance "
                                 "FROM comparison_group g JOIN comparison_run r ON r.id = g.run_id WHERE g.group_key = "
                                 "%s AND r.client_id = %s ORDER BY r.id", (c["group_key"], c["client_id"]))
    return J(c)


def _case_act(fn, cid: int, a: dict, *args):
    with db.tx() as conn:
        fn(conn, a, cid, *args)
    return case_detail(cid, a)


@router.post("/cases/{cid}/reply")
def case_reply(cid: int, body: dict = Body(...), a: dict = Depends(need("send"))):
    return _case_act(cases.log_reply, cid, a, body)


@router.post("/cases/{cid}/keep-open")
def case_keep_open(cid: int, body: dict = Body(...), a: dict = Depends(need("case_update"))):
    return _case_act(cases.keep_open, cid, a, body.get("reason"), body.get("requested"),
                     int(body["owner_id"]) if s(body.get("owner_id")) else None, body.get("follow_up"))


@router.post("/cases/{cid}/payment")
def case_payment(cid: int, body: dict = Body(...), a: dict = Depends(need("payment"))):
    return _case_act(cases.payment, cid, a, body.get("status"), body.get("amount"), body.get("reference") or "",
                     int(body["file_id"]) if s(body.get("file_id")) else None)


@router.post("/cases/{cid}/close")
def case_close(cid: int, body: dict = Body(...), a: dict = Depends(need("case_update"))):
    return _case_act(cases.close, cid, a, body.get("outcome"), body.get("reason"), body.get("evidence"))
