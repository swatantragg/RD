"""A + B: upload, classify, confirm metadata, reconcile, decide duplicates."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import Response

from .. import config, db, intake, storage
from ..parsing import reader, safety
from .deps import J, actor, need, page

router = APIRouter()


@router.get("/files")
def files(client_id: int, status: str | None = None, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT f.id, f.filename, f.income_type, f.format, f.status, f.gate, f.hold_reason, "
                              "f.meta, f.printed_total, f.lines_total, f.control_total, f.rows_total, f.rows_invalid, "
                              "f.uploaded_at, f.supersedes_id, b.code AS batch, u.name AS uploaded_by_name, f.bytes "
                              "FROM source_file f JOIN batch b ON b.id = f.batch_id LEFT JOIN app_user u ON u.id = "
                              "f.uploaded_by WHERE f.client_id = %s AND (%s::TEXT IS NULL OR f.status = %s) "
                              "ORDER BY f.id DESC", (client_id, status, status)))


@router.post("/files")
async def upload(client_id: int = Form(...), batch: str | None = Form(None), declared_type: str | None = Form(None),
                 platform: str | None = Form(None), territory: str | None = Form(None),
                 currency: str | None = Form(None), period_from: str | None = Form(None),
                 period_to: str | None = Form(None), basis: str | None = Form(None), share: str | None = Form(None),
                 sender: str | None = Form(None), files: list[UploadFile] = File(...), a: dict = Depends(need("upload"))):
    limit = config.settings.max_upload_mb * 1024 * 1024
    meta = dict(platform=platform, territory=territory, currency=currency, period_from=period_from,
                period_to=period_to, basis=basis, share=share, sender=sender)
    out = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            out.append(dict(filename=f.filename, status="FILE_EXCEPTION",
                            hold_reason=f"over the {config.settings.max_upload_mb} MB limit"))
            continue
        with db.tx() as conn:
            r = intake.upload(conn, a, client_id, f.filename or "upload.xlsx", data, batch, declared_type or None, meta)
        out.append(dict(r, filename=f.filename))
    return J(out)


def _detail(conn, fid: int) -> dict:
    f = db.one(conn, "SELECT f.*, b.code AS batch, u.name AS uploaded_by_name, c.name AS control_by_name FROM "
                     "source_file f JOIN batch b ON b.id = f.batch_id LEFT JOIN app_user u ON u.id = f.uploaded_by "
                     "LEFT JOIN app_user c ON c.id = f.control_by WHERE f.id = %s", (fid,))
    if not f:
        raise ValueError("unknown file")
    f["overlaps"] = intake._overlaps(conn, f) if f["status"] in intake.ACTIVE else []
    if f["income_type"] in intake.LINE_TABLE:
        t = intake.LINE_TABLE[f["income_type"]]
        dup = "duplicate_state" if t != "catalogue_line" else "'NONE'"
        f["row_counts"] = db.one(conn, f"SELECT count(*) AS rows, count(*) FILTER (WHERE NOT is_valid) AS invalid, "
                                       f"count(*) FILTER (WHERE {dup} = 'CANDIDATE') AS duplicate_candidates, "
                                       f"count(*) FILTER (WHERE {dup} = 'SUPPRESSED') AS suppressed "
                                       f"FROM {t} WHERE file_id = %s", (fid,))
        if t in ("recording_line", "usage_line"):
            f["months"] = db.all(conn, "SELECT month, count(*) AS rows, " +
                                 ("sum(amount)" if t == "recording_line" else "sum(streams)") +
                                 f" AS total FROM {t} WHERE file_id = %s AND is_valid GROUP BY month ORDER BY month",
                                 (fid,))
        f["invalid_reasons"] = db.all(conn, f"SELECT invalid_reason, count(*) AS n FROM {t} WHERE file_id = %s AND NOT "
                                            f"is_valid GROUP BY 1 ORDER BY 2 DESC", (fid,))
    f["superseded_by"] = db.one(conn, "SELECT id, filename FROM source_file WHERE supersedes_id = %s", (fid,))
    return f


@router.get("/files/{fid}")
def file_detail(fid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        return J(_detail(conn, fid))


@router.get("/files/{fid}/rows")
def file_rows(fid: int, only: str = "all", limit: int | None = None, offset: int | None = None,
              _: dict = Depends(actor)):
    n, o = page(limit, offset)
    with db.tx() as conn:
        return J(intake.file_rows(conn, fid, only if only in ("all", "invalid", "duplicates") else "all", n, o))


@router.get("/files/{fid}/preview")
def preview(fid: int, _: dict = Depends(actor)):
    """The first rows of each sheet, for classifying a file or mapping an unknown layout."""
    with db.tx() as conn:
        f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,))
    data = storage.get("originals", f["object_key"])
    rep = safety.Report()
    try:
        safety.check_bytes(data, f["filename"], rep)
        sheets = reader.parse(data, rep)
    except Exception as e:                                      # noqa: BLE001
        return J(dict(error=str(e), sheets=[]))
    return J(dict(sheets=[dict(title=sh["title"], rows=sh["rows"][:20]) for sh in sheets[:4]],
                  mapping=f["mapping"]))


@router.get("/files/{fid}/original")
def original(fid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        f = db.one(conn, "SELECT filename, object_key FROM source_file WHERE id = %s", (fid,))
    data = storage.get("originals", f["object_key"])
    safe = "".join(c for c in f["filename"] if c.isalnum() or c in " ._-()")[:150]
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})


def _act(fn, fid: int, a: dict, *args):
    with db.tx() as conn:
        fn(conn, a, fid, *args)
        return J(_detail(conn, fid))


@router.post("/files/{fid}/classify")
def classify(fid: int, body: dict = Body(...), a: dict = Depends(need("upload"))):
    return _act(intake.reclassify, fid, a, body.get("income_type"), body.get("header_row"), body.get("columns"))


@router.post("/files/{fid}/meta")
def set_meta(fid: int, body: dict = Body(...), a: dict = Depends(need("upload"))):
    return _act(intake.set_meta, fid, a, body)


@router.post("/files/{fid}/accept-rows")
def accept_rows(fid: int, body: dict = Body(...), a: dict = Depends(need("intake_review"))):
    return _act(intake.accept_row_exceptions, fid, a, body.get("note"))


@router.post("/files/{fid}/control")
def control(fid: int, body: dict = Body(...), a: dict = Depends(need("intake_review"))):
    return _act(intake.approve_control, fid, a, body.get("control_total"), body.get("reference") or "",
                body.get("bridge") or [])


@router.post("/files/{fid}/overlap")
def overlap(fid: int, body: dict = Body(...), a: dict = Depends(need("intake_review"))):
    return _act(intake.decide_overlap, fid, a, int(body.get("other_id")), body.get("decision"), body.get("note"))


@router.post("/files/{fid}/row-duplicates")
def row_duplicates(fid: int, body: dict = Body(...), a: dict = Depends(need("intake_review"))):
    return _act(intake.decide_row_duplicates, fid, a, body.get("decision"), body.get("note"))


@router.post("/files/{fid}/exclude")
def exclude(fid: int, body: dict = Body(...), a: dict = Depends(need("intake_review"))):
    return _act(intake.exclude, fid, a, body.get("note"))


@router.post("/files/{fid}/recheck")
def recheck(fid: int, a: dict = Depends(need("upload"))):
    with db.tx() as conn:
        intake.evaluate(conn, fid, a)
        return J(_detail(conn, fid))
