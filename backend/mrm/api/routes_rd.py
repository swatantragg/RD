"""The royalty processing platform: home, clients, processing runs, files, results, review, publishing, downloads."""
from __future__ import annotations


from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .. import config
from ..normalize import s
from ..rd import access, service
from .deps import J, actor, attachment, id_list, json_body, need_id

router = APIRouter()


# ------------------------------------------------------------------ home and history
@router.get("/home")
def home(a: dict = Depends(actor)):
    return J(service.home(a))


@router.get("/past-reports")
def past_reports(client_id: int | None = None, a: dict = Depends(actor)):
    return J(service.past_reports(a, client_id))


# ------------------------------------------------------------------ clients
@router.get("/clients")
def clients(a: dict = Depends(actor)):
    return J(service.list_clients(a))


@router.post("/clients")
def create_client(body: dict = Depends(json_body), a: dict = Depends(actor)):
    return J(service.save_client(a, body))


@router.patch("/clients/{cid}")
def update_client(cid: int, body: dict = Depends(json_body), a: dict = Depends(actor)):
    return J(service.save_client(a, body, cid))


# ------------------------------------------------------------------ runs and files
@router.get("/runs")
def runs(client_id: int | None = None, a: dict = Depends(actor)):
    return J(service.list_runs(a, client_id, limit=50))


@router.post("/runs")
def create_run(body: dict = Depends(json_body), a: dict = Depends(actor)):
    return J(service.create_run(a, need_id(body, "client_id", "client"), body.get("title")))


@router.get("/runs/{rid}")
def run(rid: int, a: dict = Depends(actor)):
    return J(service.run_view(a, rid))


@router.post("/runs/{rid}/close")
def close_run(rid: int, a: dict = Depends(actor)):
    service.close_run(a, rid)
    return J({"ok": True})


@router.delete("/runs/{rid}")
def delete_run(rid: int, a: dict = Depends(actor)):
    return J(service.delete_run(a, rid))


@router.post("/runs/{rid}/files")
async def upload(rid: int, files: list[UploadFile] = File(...), a: dict = Depends(actor)):
    access.require(a, "prepare")
    limit = config.settings.max_upload_mb * 1024 * 1024
    out = []
    for f in files:
        data = await f.read(limit + 1)
        name = f.filename or "upload.xlsx"
        if len(data) > limit:
            out.append(dict(filename=name, error=f"This file is larger than {config.settings.max_upload_mb} MB."))
            continue
        try:
            out.append(await run_in_threadpool(service.add_file, a, rid, name, data))
        except service.RDError as e:
            out.append(dict(filename=name, error=str(e)))
    return J(out)


@router.post("/runs/{rid}/files/{fid}/answer")
def answer(rid: int, fid: int, body: dict = Depends(json_body), a: dict = Depends(actor)):
    return J(service.answer(a, rid, fid, body.get("answers") or {}))


@router.post("/runs/{rid}/files/{fid}/choice")
def choice(rid: int, fid: int, body: dict = Depends(json_body), a: dict = Depends(actor)):
    service.choose(a, rid, fid, s(body.get("choice")))
    return J(service.run_view(a, rid))


@router.delete("/runs/{rid}/files/{fid}")
def remove(rid: int, fid: int, a: dict = Depends(actor)):
    service.remove_file(a, rid, fid)
    return J(service.run_view(a, rid))


@router.get("/files/{fid}/details")
def file_details(fid: int, a: dict = Depends(actor)):
    return J(service.file_details(a, fid))


@router.post("/runs/{rid}/process")
def process(rid: int, a: dict = Depends(actor)):
    return J(service.start_build(a, rid))


# ------------------------------------------------------------------ results and review
@router.get("/builds/{bid}")
def build(bid: int, a: dict = Depends(actor)):
    return J(service.build_view(a, bid))


@router.get("/builds/{bid}/findings")
def findings(bid: int, status: str | None = None, q: str | None = None, offset: int = 0, a: dict = Depends(actor)):
    return J(service.findings(a, bid, status or None, q or None, offset=offset))


@router.post("/builds/{bid}/issues/{no}/act")
def act(bid: int, no: int, body: dict = Depends(json_body), a: dict = Depends(actor)):
    return J(service.act(a, bid, no, s(body.get("action")), body))


@router.post("/builds/{bid}/findings/status")
def set_status(bid: int, body: dict = Depends(json_body), a: dict = Depends(actor)):
    return J(service.set_status(a, bid, id_list(body, "findings", "findings"), s(body.get("status")),
                                body.get("note")))


@router.post("/builds/{bid}/publish")
def publish(bid: int, a: dict = Depends(actor)):
    return J(service.publish(a, bid))


def _attachment(name: str, data: bytes, media: str) -> Response:
    return attachment(name, data, media)


@router.get("/reports/{rid}/download")
def download(rid: int, a: dict = Depends(actor)):
    name, data = service.report_file(a, rid)
    return _attachment(name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/reports/{rid}/preview")
def preview(rid: int, sheet: int = 0, a: dict = Depends(actor)):
    return J(service.report_preview(a, rid, sheet))


@router.get("/builds/{bid}/download-all")
def download_all(bid: int, a: dict = Depends(actor)):
    name, data = service.report_bundle(a, bid)
    return _attachment(name, data, "application/zip")


# ------------------------------------------------------------------ diagnostics
@router.get("/diagnostics")
def diagnostics(a: dict = Depends(actor)):
    return J(service.diagnostics(a))
