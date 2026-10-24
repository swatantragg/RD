"""Reconciliation platform: catalogue, statement library, master view, reconciliation, enquiries and follow-up.
Thin: every route calls one service function, which checks the role, scopes the transaction and audits."""
from __future__ import annotations

import datetime as dt
import urllib.parse

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .. import config
from ..rd import access, catalogue, enquiries, library, master, recon
from ..rd.service import RDError
from .deps import J, actor

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attachment(name: str, data: bytes, media: str = XLSX) -> Response:
    return Response(data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"{name.encode('ascii', 'replace').decode()}\"; "
                               f"filename*=UTF-8''{urllib.parse.quote(name)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


async def _read(f: UploadFile) -> tuple[str, bytes]:
    limit = config.settings.max_upload_mb * 1024 * 1024
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise RDError(f"This file is larger than {config.settings.max_upload_mb} MB.")
    return f.filename or "upload.xlsx", data


def _d(v: str | None) -> dt.date | None:
    return dt.date.fromisoformat(v[:10]) if v else None


# ------------------------------------------------------------------ catalogue
@router.get("/catalogue/works")
def works(client_id: int, q: str | None = None, status: str | None = None, mapping: str | None = None,
          offset: int = 0, import_id: int | None = None, a: dict = Depends(actor)):
    return J(catalogue.works(a, client_id, q or None, status or None, mapping or None, offset,
                             import_id=import_id))


@router.post("/catalogue/works")
def create_work(body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.create_work(a, int(body["client_id"]), body))


@router.post("/catalogue/link-isrc")
def link_isrc(body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.link_by_number(a, int(body["client_id"]), body))


@router.get("/catalogue/works/search")
def find_works(client_id: int, q: str, a: dict = Depends(actor)):
    return J(catalogue.find_works(a, client_id, q))


@router.get("/catalogue/works/{wid}")
def work(wid: int, a: dict = Depends(actor)):
    return J(catalogue.work_detail(a, wid))


@router.patch("/catalogue/works/{wid}")
def update_work(wid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.update_work(a, wid, body))


@router.post("/catalogue/works/{wid}/links")
def add_link(wid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.add_link(a, wid, body))


@router.post("/catalogue/links/{mid}/status")
def link_status(mid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.set_link_status(a, mid, body.get("status") or "", body.get("note")))


@router.post("/catalogue/links/{mid}/move")
def move_link(mid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.move_link(a, mid, body.get("to_work") or "", body.get("note")))


@router.get("/catalogue/conflicts")
def conflicts(client_id: int, a: dict = Depends(actor)):
    return J(catalogue.conflicts(a, client_id))


@router.get("/catalogue/export")
def export_catalogue(client_id: int, a: dict = Depends(actor)):
    return _attachment(*catalogue.export(a, client_id))


@router.get("/catalogue/song-lists")
def song_lists(client_id: int, a: dict = Depends(actor)):
    return J(catalogue.stored_song_lists(a, client_id))


@router.get("/catalogue/imports")
def imports(client_id: int, a: dict = Depends(actor)):
    return J(catalogue.imports(a, client_id))


@router.post("/catalogue/imports")
async def start_import(client_id: int = Form(...), file: UploadFile = File(...), a: dict = Depends(actor)):
    access.require(a, "prepare")
    name, data = await _read(file)
    return J(await run_in_threadpool(catalogue.start_import, a, client_id, name, data))


@router.post("/catalogue/imports/from-file")
def import_stored(body: dict = Body(...), a: dict = Depends(actor)):
    return J(catalogue.import_stored(a, int(body["client_id"]), int(body["file_id"])))


@router.get("/catalogue/imports/{iid}")
def import_view(iid: int, status: str | None = None, action: str | None = None, q: str | None = None,
                offset: int = 0, a: dict = Depends(actor)):
    return J(catalogue.import_view(a, iid, status or None, action or None, offset, q or None))


@router.post("/catalogue/imports/{iid}/apply")
def apply_import(iid: int, body: dict = Body(default={}), a: dict = Depends(actor)):
    return J(catalogue.apply_import(a, iid, verify=bool(body.get("verify_mappings", True))))


@router.post("/catalogue/imports/{iid}/discard")
def discard_import(iid: int, a: dict = Depends(actor)):
    return J(catalogue.discard_import(a, iid))


@router.get("/catalogue/imports/{iid}/report")
def import_report(iid: int, a: dict = Depends(actor)):
    return _attachment(*catalogue.import_report(a, iid))


# ------------------------------------------------------------------ statement library
@router.get("/statements")
def statements(client_id: int, record_type: str | None = None, platform_id: int | None = None,
               status: str | None = None, q: str | None = None, offset: int = 0, source: str | None = None,
               a: dict = Depends(actor)):
    return J(library.listing(a, client_id, record_type or None, platform_id, status or None, q or None, offset,
                             source or None))


@router.get("/statement-batches")
def statement_batches(client_id: int, source: str, platform_id: int | None = None, status: str | None = None,
                      q: str | None = None, offset: int = 0, a: dict = Depends(actor)):
    return J(library.batches(a, client_id, source, platform_id, status or None, q or None, offset))


@router.get("/statement-batches/{bid}")
def statement_batch(bid: int, a: dict = Depends(actor)):
    return J(library.batch(a, bid))


@router.post("/statements")
async def upload_statements(client_id: int = Form(...), source: str | None = Form(None),
                            batch_key: str | None = Form(None), files: list[UploadFile] = File(...),
                            a: dict = Depends(actor)):
    access.require(a, "prepare")
    out = []
    for f in files:
        try:
            name, data = await _read(f)
            out.append(await run_in_threadpool(library.upload, a, client_id, name, data, source or None,
                                               batch_key or None))
        except RDError as e:
            out.append(dict(filename=f.filename, error=str(e)))
    return J(out)


@router.get("/statements/{sid}")
def statement(sid: int, a: dict = Depends(actor)):
    return J(library.detail(a, sid))


@router.post("/statements/{sid}/answer")
def answer(sid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(library.answer(a, sid, body.get("answers") or {}))


@router.patch("/statements/{sid}")
def update_statement(sid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(library.update(a, sid, body))


@router.get("/statements/{sid}/records")
def records(sid: int, q: str | None = None, mapping: str | None = None, offset: int = 0, a: dict = Depends(actor)):
    return J(library.records(a, sid, q or None, mapping or None, offset))


@router.get("/statements/{sid}/error-report")
def statement_errors(sid: int, a: dict = Depends(actor)):
    return _attachment(*library.error_report(a, sid))


@router.get("/statements/{sid}/original")
def statement_original(sid: int, a: dict = Depends(actor)):
    name, data = library.original(a, sid)
    return _attachment(name, data, XLSX if not name.lower().endswith(".csv") else "text/csv")


@router.get("/platform-data")
def platform_data(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                  period_to: str | None = None, q: str | None = None, only: str | None = None, offset: int = 0,
                  limit: int = 100, a: dict = Depends(actor)):
    return J(library.combined(a, client_id, platform_id, period_from, period_to, q or None, only or None, offset,
                              limit))


@router.get("/platform-data/export")
def platform_data_export(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                         period_to: str | None = None, q: str | None = None, only: str | None = None,
                         a: dict = Depends(actor)):
    return _attachment(*library.export_combined(a, client_id, platform_id, period_from, period_to, q or None,
                                                only or None))


@router.get("/records/export")
def export_records(client_id: int, record_type: str, platform_id: int | None = None, period_from: str | None = None,
                   period_to: str | None = None, statement_id: int | None = None, mapping: str | None = None,
                   q: str | None = None, source: str | None = None, a: dict = Depends(actor)):
    return _attachment(*library.export_records(a, client_id, record_type, platform_id, _d(period_from), _d(period_to),
                                               statement_id, mapping or None, q or None, source or None))


# ------------------------------------------------------------------ master view and exports
def _mf(platform_id, period_from, period_to, statement_id, q, status, mapping, money, sort, side=None) -> dict:
    return dict(platform_id=platform_id, period_from=period_from, period_to=period_to, statement_id=statement_id, q=q,
                status=status, mapping=mapping, money=money, sort=sort, side=side)


@router.get("/master")
def master_view(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                period_to: str | None = None, statement_id: int | None = None, q: str | None = None,
                status: str | None = None, mapping: str | None = None, money: str | None = None,
                sort: str | None = None, offset: int = 0, a: dict = Depends(actor)):
    return J(master.view(a, client_id, _mf(platform_id, period_from, period_to, statement_id, q, status, mapping, money,
                                           sort), offset))


@router.get("/master/works/{wid}/sources")
def master_sources(wid: int, platform_id: int | None = None, period_from: str | None = None,
                   period_to: str | None = None, statement_id: int | None = None, a: dict = Depends(actor)):
    return J(master.sources(a, wid, _mf(platform_id, period_from, period_to, statement_id, None, None, None, None,
                                        None)))


@router.get("/master/unmatched")
def master_unmatched(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                     period_to: str | None = None, statement_id: int | None = None, a: dict = Depends(actor)):
    return J(master.unmatched(a, client_id, _mf(platform_id, period_from, period_to, statement_id, None, None, None,
                                                None, None)))


@router.get("/master/export")
def master_export(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                  period_to: str | None = None, statement_id: int | None = None, q: str | None = None,
                  status: str | None = None, mapping: str | None = None, money: str | None = None,
                  sort: str | None = None, a: dict = Depends(actor)):
    return _attachment(*master.export_view(a, client_id, _mf(platform_id, period_from, period_to, statement_id, q,
                                                             status, mapping, money, sort)))


@router.get("/master/sheet")
async def master_sheet(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                       period_to: str | None = None, statement_id: int | None = None, q: str | None = None,
                       side: str | None = None, sort: str | None = None, offset: int = 0, limit: int = 100,
                       a: dict = Depends(actor)):
    return J(await run_in_threadpool(master.sheet, a, client_id, _mf(
        platform_id, period_from, period_to, statement_id, q, None, None, None, sort, side), offset, limit))


@router.get("/master/export-statement")
async def master_statement(client_id: int, platform_id: int | None = None, period_from: str | None = None,
                           period_to: str | None = None, statement_id: int | None = None, side: str | None = None,
                           sort: str | None = None, a: dict = Depends(actor)):
    name, data = await run_in_threadpool(master.export_skv, a, client_id, _mf(
        platform_id, period_from, period_to, statement_id, None, None, None, None, sort, side))
    return _attachment(name, data)


# ------------------------------------------------------------------ reconciliation
@router.get("/reconciliation/options")
def recon_options(client_id: int, a: dict = Depends(actor)):
    return J(recon.options(a, client_id))


@router.get("/reconciliation/settings")
def recon_settings(client_id: int, a: dict = Depends(actor)):
    return J(recon.settings_view(a, client_id))


@router.post("/reconciliation/settings")
def save_recon_settings(body: dict = Body(...), a: dict = Depends(actor)):
    return J(recon.save_settings(a, int(body["client_id"]), body))


@router.post("/reconciliation/settings/platforms")
def save_recon_platform_settings(body: dict = Body(...), a: dict = Depends(actor)):
    return J(recon.save_platform_settings(a, int(body["client_id"]), body))


@router.get("/reconciliation/runs")
def recon_runs(client_id: int, a: dict = Depends(actor)):
    return J(recon.runs(a, client_id))


@router.post("/reconciliation/runs")
async def start_recon(body: dict = Body(...), a: dict = Depends(actor)):
    return J(await run_in_threadpool(recon.start_run, a, int(body["client_id"]), int(body.get("platform_id") or 0),
                                     body.get("period_from"), body.get("period_to"),
                                     "YEAR" if body.get("mode") == "YEAR" else "PERIOD", body.get("fy")))


@router.get("/reconciliation/runs/{rid}")
def recon_run(rid: int, a: dict = Depends(actor)):
    return J(recon.run_view(a, rid))


def _rf(kind, calc, mapping, review, exception, q, sort, open_, variance) -> dict:
    return dict(kind=kind, calc=calc, mapping=mapping, review=review, exception=exception, q=q, sort=sort, open=open_,
                variance=variance)


@router.get("/reconciliation/runs/{rid}/item-ids")
def recon_item_ids(rid: int, kind: str | None = None, calc: str | None = None, mapping: str | None = None,
                   review: str | None = None, exception: str | None = None, q: str | None = None,
                   open: bool = False, variance: str | None = None, a: dict = Depends(actor)):  # noqa: A002
    return J(recon.item_ids(a, rid, _rf(kind, calc, mapping, review, exception, q, None, open, variance)))


@router.get("/reconciliation/runs/{rid}/items")
def recon_items(rid: int, kind: str | None = None, calc: str | None = None, mapping: str | None = None,
                review: str | None = None, exception: str | None = None, q: str | None = None,
                sort: str | None = None, open: bool = False, variance: str | None = None, offset: int = 0,  # noqa: A002
                a: dict = Depends(actor)):
    return J(recon.items(a, rid, _rf(kind, calc, mapping, review, exception, q, sort, open, variance), offset))


@router.get("/reconciliation/runs/{rid}/report")
def recon_report(rid: int, kind: str | None = None, calc: str | None = None, mapping: str | None = None,
                 review: str | None = None, exception: str | None = None, q: str | None = None,
                 open: bool = False, variance: str | None = None, sort: str | None = None,
                 a: dict = Depends(actor)):  # noqa: A002
    return _attachment(*recon.report(a, rid, _rf(kind, calc, mapping, review, exception, q, sort, open, variance)))


@router.get("/reconciliation/items/{iid}")
def recon_item(iid: int, a: dict = Depends(actor)):
    return J(recon.item_detail(a, iid))


@router.post("/reconciliation/runs/{rid}/review")
def review_items(rid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(recon.review_items(a, rid, body.get("item_ids") or [], body.get("status") or "", body.get("note")))


@router.post("/reconciliation/items/{iid}/review")
def review_item(iid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(recon.review_item(a, iid, body.get("status") or "", body.get("note")))


@router.post("/reconciliation/items/{iid}/addressed")
def item_addressed(iid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(recon.mark_addressed(a, iid, body))


@router.post("/reconciliation/exceptions/{eid}")
def update_exception(eid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(recon.update_exception(a, eid, body))


# ------------------------------------------------------------------ enquiries and follow-up
@router.get("/enquiries/dashboard")
def enquiry_dashboard(client_id: int, a: dict = Depends(actor)):
    return J(enquiries.dashboard(a, client_id))


@router.get("/enquiries")
def enquiry_list(client_id: int, status: str | None = None, q: str | None = None, mine: bool = False,
                 queue: str | None = Query(None), a: dict = Depends(actor)):
    if queue and queue not in enquiries.QUEUES:
        raise RDError("Unknown list.")
    return J(enquiries.listing(a, client_id, status or None, q or None, mine, queue or None))


@router.post("/enquiries")
def create_enquiry(body: dict = Body(...), a: dict = Depends(actor)):
    return J(enquiries.create(a, int(body["client_id"]), int(body["run_id"]), [int(x) for x in body.get("item_ids") or []],
                              bool(body.get("later_reviewed")), body.get("assigned_to")))


@router.get("/enquiries/{eid}")
def enquiry(eid: int, a: dict = Depends(actor)):
    return J(enquiries.detail(a, eid))


@router.patch("/enquiries/{eid}")
def update_enquiry(eid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(enquiries.update_draft(a, eid, body))


@router.post("/enquiries/{eid}/act")
def enquiry_act(eid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(enquiries.act(a, eid, body.get("action") or "", body))


@router.post("/enquiries/{eid}/actions")
def add_follow_up(eid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(enquiries.add_action(a, eid, body))


@router.patch("/enquiry-actions/{aid}")
def update_follow_up(aid: int, body: dict = Body(...), a: dict = Depends(actor)):
    return J(enquiries.update_action(a, aid, body))


@router.get("/enquiries/{eid}/attachment")
def enquiry_attachment(eid: int, usage: bool = False, a: dict = Depends(actor)):
    return _attachment(*enquiries.attachment(a, eid, usage))


@router.get("/enquiries/{eid}/annex")
def enquiry_annex(eid: int, a: dict = Depends(actor)):
    return _attachment(*enquiries.annex(a, eid))


# ------------------------------------------------------------------ home dashboard
@router.get("/overview")
def overview(client_id: int, a: dict = Depends(actor)):
    from ..rd.overview import overview as ov
    return J(ov(a, client_id))
