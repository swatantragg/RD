"""C: registers, link table, identity review, duplicate decisions, approved versions."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from .. import db, identity
from ..normalize import s
from .deps import J, actor, need, page

router = APIRouter()


@router.get("/identity/{cid}/summary")
def summary(cid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        out = identity.summary(conn, cid)
        out["issues_by_kind"] = db.all(conn, "SELECT kind, status, count(*) AS n, sum(amount) AS amount FROM "
                                             "identity_issue WHERE client_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (cid,))
        out["candidates_by_status"] = db.all(conn, "SELECT status, count(*) AS n FROM duplicate_candidate WHERE "
                                                   "client_id = %s GROUP BY 1", (cid,))
        out["files_since_version"] = db.scalar(conn, "SELECT count(*) FROM source_file WHERE client_id = %s AND "
                                                     "status = 'VALIDATED' AND uploaded_at > coalesce((SELECT max("
                                                     "approved_at) FROM identity_version WHERE client_id = %s), "
                                                     "'-infinity')", (cid, cid))
    return J(out)


@router.post("/identity/{cid}/refresh")
def refresh(cid: int, a: dict = Depends(need("identity"))):
    with db.tx() as conn:
        return J(identity.refresh(conn, cid, a))


@router.get("/identity/{cid}/issues")
def issues(cid: int, kind: str | None = None, status: str | None = "OPEN", q: str | None = None,
           limit: int | None = None, offset: int | None = None, _: dict = Depends(actor)):
    n, o = page(limit, offset)
    qq = f"%{s(q)}%" if s(q) else None
    with db.tx() as conn:
        where = ("client_id = %(c)s AND (%(k)s::TEXT IS NULL OR kind = %(k)s) AND (%(s)s::TEXT IS NULL OR status = %(s)s) "
                 "AND (%(q)s::TEXT IS NULL OR title ILIKE %(q)s OR subject_key ILIKE %(q)s)")
        p = dict(c=cid, k=kind or None, s=status or None, q=qq, n=n, o=o)
        total = db.scalar(conn, f"SELECT count(*) FROM identity_issue WHERE {where}", p)
        rows = db.all(conn, f"SELECT i.*, u.name AS resolved_by_name FROM identity_issue i LEFT JOIN app_user u ON "
                            f"u.id = i.resolved_by WHERE {where} ORDER BY amount DESC NULLS LAST, id LIMIT %(n)s "
                            f"OFFSET %(o)s", p)
    return J(dict(rows=rows, total=total))


@router.post("/identity/issues/{iid}/link")
def link_issue(iid: int, body: dict = Body(...), a: dict = Depends(need("identity"))):
    """UNMAPPED_RECORDING: link its ISRC to a work. WORK_* issues: link a recording (ISRC) to the work."""
    with db.tx() as conn:
        i = db.one(conn, "SELECT * FROM identity_issue WHERE id = %s", (iid,))
        if not i:
            raise ValueError("unknown issue")
        if i["kind"] == "UNMAPPED_RECORDING":
            rec = db.scalar(conn, "SELECT id FROM recording WHERE client_id = %s AND isrc = %s",
                            (i["client_id"], i["subject_key"]))
            comp = int(body["composition_id"])
        else:
            comp = db.scalar(conn, "SELECT id FROM composition WHERE client_id = %s AND work_code = %s",
                             (i["client_id"], i["subject_key"]))
            rec = db.scalar(conn, "SELECT id FROM recording WHERE client_id = %s AND isrc = %s",
                            (i["client_id"], s(body.get("isrc")).upper()))
            if not rec:
                raise ValueError("that ISRC is not in the recording register")
        identity.link(conn, a, i["client_id"], comp, rec, body.get("reason"), body.get("allocation"), iid)
        identity.resolve_issue(conn, a, iid, f"linked: {s(body.get('reason'))}")
    return J({"ok": True})


@router.post("/identity/issues/{iid}/resolve")
def resolve(iid: int, body: dict = Body(...), a: dict = Depends(need("identity"))):
    with db.tx() as conn:
        identity.resolve_issue(conn, a, iid, body.get("resolution"), body.get("status") or "RESOLVED")
    return J({"ok": True})


@router.post("/identity/issues/{iid}/conflict")
def conflict(iid: int, body: dict = Body(...), a: dict = Depends(need("identity"))):
    with db.tx() as conn:
        identity.resolve_conflict(conn, a, iid, body.get("choices") or [], body.get("reason"))
    return J({"ok": True})


@router.get("/identity/{cid}/candidates")
def candidates(cid: int, status: str | None = "PENDING", limit: int | None = None, offset: int | None = None,
               _: dict = Depends(actor)):
    n, o = page(limit, offset)
    with db.tx() as conn:
        p = dict(c=cid, s=status or None, n=n, o=o)
        total = db.scalar(conn, "SELECT count(*) FROM duplicate_candidate WHERE client_id = %(c)s AND (%(s)s::TEXT IS "
                                "NULL OR status = %(s)s)", p)
        rows = db.all(conn, "SELECT d.*, u.name AS decided_by_name FROM duplicate_candidate d LEFT JOIN app_user u ON "
                            "u.id = d.decided_by WHERE d.client_id = %(c)s AND (%(s)s::TEXT IS NULL OR d.status = %(s)s) "
                            "ORDER BY d.score DESC, d.id LIMIT %(n)s OFFSET %(o)s", p)
    return J(dict(rows=rows, total=total))


@router.post("/identity/candidates/{did}")
def decide(did: int, body: dict = Body(...), a: dict = Depends(need("identity"))):
    with db.tx() as conn:
        identity.decide_candidate(conn, a, did, body.get("decision"), body.get("reason"))
    return J({"ok": True})


@router.get("/identity/{cid}/links")
def links(cid: int, q: str | None = None, status: str | None = None, limit: int | None = None,
          offset: int | None = None, _: dict = Depends(actor)):
    n, o = page(limit, offset)
    qq = f"%{s(q)}%" if s(q) else None
    with db.tx() as conn:
        where = ("w.client_id = %(c)s AND (%(s)s::TEXT IS NULL OR w.status = %(s)s) AND (%(q)s::TEXT IS NULL OR "
                 "c.title ILIKE %(q)s OR c.work_code ILIKE %(q)s OR r.isrc ILIKE %(q)s OR r.title ILIKE %(q)s)")
        p = dict(c=cid, s=status or None, q=qq, n=n, o=o)
        total = db.scalar(conn, f"SELECT count(*) FROM work_link w JOIN composition c ON c.id = w.composition_id JOIN "
                                f"recording r ON r.id = w.recording_id WHERE {where}", p)
        rows = db.all(conn, f"SELECT w.id, w.basis, w.status, w.allocation, w.reason, w.evidence, w.decided_at, "
                            f"c.work_code, c.title AS work_title, c.id AS composition_id, r.isrc, r.title AS "
                            f"recording_title, u.name AS decided_by_name FROM work_link w JOIN composition c ON c.id = "
                            f"w.composition_id JOIN recording r ON r.id = w.recording_id LEFT JOIN app_user u ON u.id = "
                            f"w.decided_by WHERE {where} ORDER BY c.title, r.isrc LIMIT %(n)s OFFSET %(o)s", p)
    return J(dict(rows=rows, total=total))


@router.post("/identity/links/{lid}")
def decide_link(lid: int, body: dict = Body(...), a: dict = Depends(need("identity"))):
    with db.tx() as conn:
        identity.decide_link(conn, a, lid, body.get("decision"), body.get("reason"), body.get("allocation"))
    return J({"ok": True})


@router.get("/identity/{cid}/works")
def works(cid: int, q: str = "", _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT id, work_code, title, film, source FROM composition WHERE client_id = %s AND "
                              "canonical_id IS NULL AND (title ILIKE %s OR work_code = %s) ORDER BY title LIMIT 25",
                        (cid, f"%{s(q)}%", s(q))))


@router.get("/identity/{cid}/versions")
def versions(cid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT v.*, u.name AS approved_by_name FROM identity_version v JOIN app_user u ON u.id = "
                              "v.approved_by WHERE v.client_id = %s ORDER BY v.version_no DESC", (cid,)))


@router.get("/identity/{cid}/version-check")
def version_check(cid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        checks, counts = identity.version_checks(conn, cid)
    return J(dict(checks=checks, counts=counts))


@router.post("/identity/{cid}/versions")
def approve_version(cid: int, body: dict = Body(default={}), a: dict = Depends(need("identity_approve"))):
    with db.tx() as conn:
        return J(identity.approve_version(conn, a, cid, s(body.get("note")) or None))
