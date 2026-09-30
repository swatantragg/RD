"""REST routes (architecture §17.3)."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..build import engine as build_engine
from ..build.model import BASIS, STATUS, STATUS_ORDER
from ..core import config, db, jobs
from ..coverage import engine as coverage_engine
from ..domain import sniff
from ..domain.normalize import fy_label, ik, month_label, norm
from ..export import service as export_service
from ..export.style import STATUS_COLOURS
from ..ingest import pipeline
from ..merge import apply as merge_apply
from ..merge.candidates import SIGNALS
from ..mismatch import engine as mismatch_engine
from ..reference import REFERENCE_COVERAGE, REFERENCE_MISMATCH, compare

router = APIRouter()


# ------------------------------------------------------------------ dependencies
def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


class User(BaseModel):
    name: str
    role: str


def get_user(x_user: str | None = Header(None), x_role: str | None = Header(None)) -> User:
    role = (x_role or "analyst").lower()
    if role not in config.ROLES:
        role = "viewer"
    return User(name=(x_user or f"{role}@svf").strip()[:60], role=role)


def total(resp: Response, n: int) -> None:
    resp.headers["X-Total-Count"] = str(n)


def must(v, what: str):
    if v is None:
        raise KeyError(what)
    return v


# ------------------------------------------------------------------ meta
@router.get("/health")
def health(conn=Depends(get_conn)):
    return dict(ok=True, version=__version__, db=str(config.DB_PATH),
                batches=db.scalar(conn, "SELECT COUNT(*) FROM ingest_batch"))


@router.get("/meta")
def meta(conn=Depends(get_conn)):
    return dict(
        version=__version__, kinds=sniff.KIND_LABEL, categories=db.rows(conn, "SELECT * FROM category ORDER BY ordinal"),
        societies=db.rows(conn, "SELECT * FROM society ORDER BY name"),
        statuses=[dict(code=c, template=STATUS[c], colour=f"#{STATUS_COLOURS[c]}") for c in STATUS_ORDER],
        basis=BASIS, signals={k: dict(weight=v[0], label=v[1]) for k, v in SIGNALS.items()},
        artifacts=export_service.ARTIFACTS, roles=config.ROLES, decider_roles=config.DECIDER_ROLES,
        thresholds=dict(suggest=config.MERGE_SUGGEST_THRESHOLD, review=config.MERGE_REVIEW_THRESHOLD,
                        recon_tolerance=config.RECON_TOLERANCE),
        reference=dict(coverage=REFERENCE_COVERAGE, mismatch=REFERENCE_MISMATCH,
                       inputs_available=Path(config.REFERENCE_INPUT_DIR).is_dir()))


@router.get("/overview")
def overview(conn=Depends(get_conn)):
    batch = db.row(conn, "SELECT id FROM ingest_batch ORDER BY id DESC LIMIT 1")
    out: dict[str, Any] = dict(batch=None, build=None, builds=[], jobs=recent_jobs(10, conn))
    if not batch:
        return out
    out["batch"] = pipeline.batch_summary(conn, batch["id"])
    out["validation"] = pipeline.validation(conn, batch["id"])["summary"]
    builds = db.rows(conn, "SELECT id, label, generation, status, row_count, total_amount, total_mrm, created_at, "
                           "parent_build_id FROM build_run WHERE batch_id = ? ORDER BY id DESC", (batch["id"],))
    out["builds"] = builds
    if builds:
        b = build_engine.build_summary(conn, builds[0]["id"])
        by_section = []
        for sec in b["layout"]["sections"]:
            if sec["kind"] == "statement":
                by_section.append(dict(section=sec["section"], kind="royalty", colour=f"#{sec['band']}",
                                       total=round(sum(s["total"] for s in sec["statements"]), 2),
                                       count=len(sec["statements"])))
            else:
                by_section.append(dict(section=f"{b['layout']['client']} MRM (gross)", kind="gross",
                                       colour=f"#{sec['band']}", total=round(sum(m["total"] for m in sec["months"]), 2),
                                       count=len(sec["months"])))
        out["build"] = dict(id=b["id"], label=b["label"], status=b["status"], stats=b["stats"],
                            invariants=b["invariants"], row_count=b["row_count"], total_amount=b["total_amount"],
                            total_mrm=b["total_mrm"], by_section=by_section,
                            fy=[dict(fy=k, label=fy_label(k), total=v) for k, v in b["layout"]["fy_totals"].items()],
                            months=[dict(month=m["month"], label=m["label"], total=m["total"])
                                    for s in b["layout"]["sections"] if s["kind"] == "platform" for m in s["months"]])
    out["coverage"] = db.rows(conn, "SELECT cr.id, cr.build_id, cr.mode, cr.finding_count, cr.revenue_at_risk, "
                                    "cr.royalty_received, cr.status, cr.stats_json, cr.created_at FROM coverage_run cr "
                                    "JOIN build_run b ON b.id = cr.build_id WHERE b.batch_id = ? ORDER BY cr.id DESC "
                                    "LIMIT 5", (batch["id"],))
    for c in out["coverage"]:
        c["l3_policy"] = db.loads(c.pop("stats_json"), {}).get("l3_policy", "v2")
    return out


@router.get("/reference-check")
def reference_check(batch_id: int | None = None, conn=Depends(get_conn)):
    bid = batch_id or db.scalar(conn, "SELECT MAX(id) FROM ingest_batch")
    return dict(batch_id=bid, rows=compare(conn, bid) if bid else [])


class DemoIn(BaseModel):
    skip_exports: bool = True


@router.post("/demo/load")
def demo_load(body: DemoIn, user: User = Depends(get_user), conn=Depends(get_conn)):
    from ..cli import load_reference
    inputs = Path(config.REFERENCE_INPUT_DIR)
    if not inputs.is_dir():
        raise ValueError(f"reference inputs not found at {inputs}")

    def fn(ctx, c):
        res = load_reference(c, str(inputs), skip_exports=body.skip_exports, echo=ctx.log)
        return dict(message=f"reference run loaded: batch #{res['batch_id']}, builds #{res['base']} and "
                            f"#{res['merged']}", **res)
    return dict(job_id=jobs.submit(conn, "demo_load", fn, user=user.name))


# ------------------------------------------------------------------ jobs
def recent_jobs(limit: int, conn) -> list[dict]:
    out = db.rows(conn, "SELECT id, kind, batch_id, build_id, ref_id, status, progress, message, created_at, "
                        "finished_at, created_by FROM job ORDER BY id DESC LIMIT ?", (limit,))
    return out


@router.get("/jobs")
def list_jobs(limit: int = 30, conn=Depends(get_conn)):
    return recent_jobs(limit, conn)


@router.get("/jobs/{job_id}")
def get_job(job_id: int, conn=Depends(get_conn)):
    return must(jobs.get(conn, job_id), f"job {job_id}")


# ------------------------------------------------------------------ batches + files (S0/S1)
class BatchIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    note: str | None = None


@router.get("/batches")
def list_batches(resp: Response, conn=Depends(get_conn)):
    out = [pipeline.batch_summary(conn, b["id"]) for b in db.rows(conn, "SELECT id FROM ingest_batch ORDER BY id DESC")]
    total(resp, len(out))
    return out


@router.post("/batches")
def create_batch(body: BatchIn, user: User = Depends(get_user), conn=Depends(get_conn)):
    bid = pipeline.create_batch(conn, body.label.strip(), user.name, body.note)
    return pipeline.batch_summary(conn, bid)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, conn=Depends(get_conn)):
    return must(pipeline.batch_summary(conn, batch_id), f"batch {batch_id}")


@router.post("/batches/{batch_id}/files")
async def upload_files(batch_id: int, files: list[UploadFile] = File(...), user: User = Depends(get_user),
                       conn=Depends(get_conn)):
    must(db.row(conn, "SELECT id FROM ingest_batch WHERE id = ?", (batch_id,)), f"batch {batch_id}")
    out = []
    for f in files:
        data = await f.read()
        try:
            out.append(pipeline.add_file(conn, batch_id, f.filename or "upload.xlsx", data, user.name))
        except ValueError as e:
            out.append(dict(filename=f.filename, error=str(e)))
    return out


@router.get("/batches/{batch_id}/files")
def batch_files(batch_id: int, resp: Response, conn=Depends(get_conn)):
    out = pipeline.list_files(conn, batch_id)
    total(resp, len(out))
    return out


class FilePatch(BaseModel):
    kind: str | None = None
    category_code: str | None = None
    dist_no: str | None = None
    period_from: str | None = None
    period_to: str | None = None
    society_code: str | None = None
    s_no: int | None = None
    stmt_date: str | None = None


@router.patch("/files/{file_id}")
def patch_file(file_id: int, body: FilePatch, conn=Depends(get_conn)):
    return pipeline.patch_file(conn, file_id, body.model_dump(exclude_unset=True))


@router.delete("/files/{file_id}")
def delete_file(file_id: int, conn=Depends(get_conn)):
    pipeline.delete_file(conn, file_id)
    return dict(deleted=file_id)


@router.post("/batches/{batch_id}/extract")
def extract(batch_id: int, force: bool = False, user: User = Depends(get_user), conn=Depends(get_conn)):
    must(db.row(conn, "SELECT id FROM ingest_batch WHERE id = ?", (batch_id,)), f"batch {batch_id}")
    jid = jobs.submit(conn, "extract", lambda ctx, c: pipeline.extract_batch(ctx, c, batch_id, force),
                      batch_id=batch_id, user=user.name)
    return dict(job_id=jid)


@router.get("/batches/{batch_id}/validation")
def validation(batch_id: int, conn=Depends(get_conn)):
    return pipeline.validation(conn, batch_id)


@router.get("/statements/{statement_id}/blocks")
def statement_blocks(statement_id: int, resp: Response, q: str | None = None, offset: int = 0, limit: int = 200,
                     conn=Depends(get_conn)):
    where, args = "statement_id = ?", [statement_id]
    if q:
        where += " AND (title LIKE ? OR work_no LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    total(resp, db.scalar(conn, f"SELECT COUNT(*) FROM statement_block WHERE {where}", args))
    return db.rows(conn, f"SELECT id, ordinal, sheet_row, work_no, synthetic, title, language, amount, money_lines FROM "
                         f"statement_block WHERE {where} ORDER BY ordinal LIMIT ? OFFSET ?", args + [limit, offset])


# ------------------------------------------------------------------ song sheets (TYPE C / F)
def sheet_view(conn, s: dict, entries: int = 0) -> dict:
    s = dict(s)
    s["proposal"] = db.loads(s.pop("proposal_json"), {})
    s["header"] = db.loads(s.pop("header_json"), [])
    s["mapping"] = {m["field"]: m for m in db.rows(conn, "SELECT field, col_index, confidence, confirmed_by FROM "
                                                         "user_sheet_column_map WHERE sheet_id = ?", (s["id"],))}
    s["filename"] = db.scalar(conn, "SELECT filename FROM source_file WHERE id = ?", (s["source_file_id"],))
    s["coverage_runs"] = db.rows(conn, "SELECT id, build_id, mode, finding_count, created_at FROM coverage_run WHERE "
                                       "sheet_id = ? ORDER BY id DESC", (s["id"],))
    s["counts"] = dict(
        works=db.scalar(conn, "SELECT COUNT(DISTINCT w.work_no) FROM user_sheet_entry_work w JOIN user_sheet_entry e "
                              "ON e.id = w.entry_id WHERE e.sheet_id = ?", (s["id"],)),
        isrcs=db.scalar(conn, "SELECT COUNT(DISTINCT i.isrc) FROM user_sheet_entry_isrc i JOIN user_sheet_entry e "
                              "ON e.id = i.entry_id WHERE e.sheet_id = ?", (s["id"],)),
        names=db.scalar(conn, "SELECT COUNT(DISTINCT name_key) FROM user_sheet_entry WHERE sheet_id = ?", (s["id"],)))
    if entries:
        s["entries"] = entries_page(conn, s["id"], None, 0, entries)[1]
    return s


def entries_page(conn, sheet_id: int, q: str | None, offset: int, limit: int):
    where, args = "e.sheet_id = ?", [sheet_id]
    if q:
        where += (" AND (e.name LIKE ? OR e.raw_no LIKE ? OR e.id IN (SELECT entry_id FROM user_sheet_entry_isrc "
                  "WHERE isrc LIKE ?))")
        args += [f"%{q}%", f"%{q}%", f"%{q.upper()}%"]
    n = db.scalar(conn, f"SELECT COUNT(*) FROM user_sheet_entry e WHERE {where}", args)
    rows = db.rows(conn, f"SELECT e.id, e.ordinal, e.sheet_row, e.name, e.raw_no FROM user_sheet_entry e WHERE {where} "
                         f"ORDER BY e.ordinal LIMIT ? OFFSET ?", args + [limit, offset])
    for r in rows:
        r["isrcs"] = [x["isrc"] for x in db.rows(conn, "SELECT isrc FROM user_sheet_entry_isrc WHERE entry_id = ? "
                                                       "ORDER BY ordinal", (r["id"],))]
        r["work_nos"] = [x["work_no"] for x in db.rows(conn, "SELECT work_no FROM user_sheet_entry_work WHERE "
                                                             "entry_id = ? ORDER BY ordinal", (r["id"],))]
    return n, rows


@router.get("/sheets")
def list_sheets(resp: Response, batch_id: int | None = None, conn=Depends(get_conn)):
    q = "SELECT * FROM user_sheet" + (" WHERE batch_id = ?" if batch_id else "") + " ORDER BY is_catalogue DESC, id DESC"
    out = [sheet_view(conn, s) for s in db.rows(conn, q, (batch_id,) if batch_id else ())]
    total(resp, len(out))
    return out


@router.get("/sheets/{sheet_id}")
def get_sheet(sheet_id: int, conn=Depends(get_conn)):
    s = must(db.row(conn, "SELECT * FROM user_sheet WHERE id = ?", (sheet_id,)), f"sheet {sheet_id}")
    return sheet_view(conn, s, entries=25)


@router.get("/sheets/{sheet_id}/entries")
def sheet_entries(sheet_id: int, resp: Response, q: str | None = None, offset: int = 0, limit: int = 100,
                  conn=Depends(get_conn)):
    n, rows = entries_page(conn, sheet_id, q, offset, min(limit, 1000))
    total(resp, n)
    return rows


class MappingIn(BaseModel):
    mapping: dict[str, int | None]


@router.patch("/sheets/{sheet_id}/mapping")
def confirm_mapping(sheet_id: int, body: MappingIn, user: User = Depends(get_user), conn=Depends(get_conn)):
    pipeline.confirm_mapping(conn, sheet_id, body.mapping, user.name)
    return get_sheet(sheet_id, conn)


class SheetPatch(BaseModel):
    is_catalogue: bool


@router.patch("/sheets/{sheet_id}")
def patch_sheet(sheet_id: int, body: SheetPatch, conn=Depends(get_conn)):
    must(db.row(conn, "SELECT id FROM user_sheet WHERE id = ?", (sheet_id,)), f"sheet {sheet_id}")
    with db.tx(conn):
        conn.execute("UPDATE user_sheet SET is_catalogue = ? WHERE id = ?", (int(body.is_catalogue), sheet_id))
    return get_sheet(sheet_id, conn)


# ------------------------------------------------------------------ builds (S5-S8) + the RD viewer
class BuildIn(BaseModel):
    catalogue_sheet_id: int | None = None
    name_fallback: str = "exact"
    force: bool = False


@router.post("/batches/{batch_id}/builds")
def start_build(batch_id: int, body: BuildIn, user: User = Depends(get_user), conn=Depends(get_conn)):
    must(db.row(conn, "SELECT id FROM ingest_batch WHERE id = ?", (batch_id,)), f"batch {batch_id}")
    cfg = body.model_dump()
    jid = jobs.submit(conn, "build", lambda ctx, c: build_engine.run_build(ctx, c, batch_id, cfg, user.name),
                      batch_id=batch_id, user=user.name)
    return dict(job_id=jid)


@router.get("/builds")
def list_builds(resp: Response, batch_id: int | None = None, conn=Depends(get_conn)):
    q = ("SELECT id, batch_id, parent_build_id, root_build_id, generation, label, status, row_count, total_amount, "
         "total_mrm, created_at, created_by, decision_ids_json FROM build_run")
    out = db.rows(conn, q + (" WHERE batch_id = ?" if batch_id else "") + " ORDER BY id DESC",
                  (batch_id,) if batch_id else ())
    for b in out:
        b["decisions"] = len(db.loads(b.pop("decision_ids_json"), []))
    total(resp, len(out))
    return out


@router.get("/builds/{build_id}")
def get_build(build_id: int, conn=Depends(get_conn)):
    b = must(build_engine.build_summary(conn, build_id), f"build {build_id}")
    b["sheet"] = db.row(conn, "SELECT id, label, s_no FROM user_sheet WHERE id = ?", (b["catalogue_sheet_id"],)) \
        if b["catalogue_sheet_id"] else None
    b["lineage"] = db.rows(conn, "SELECT id, label, generation, parent_build_id, status, row_count, created_at FROM "
                                 "build_run WHERE root_build_id = ? ORDER BY id", (b["root_build_id"],))
    return b


def _children(conn, build_id: int):
    kids: dict[str, dict[int, list]] = {k: defaultdict(list) for k in ("isrc", "work", "amount", "mrm", "fy")}
    q = "SELECT x.* FROM {t} x JOIN rd_row r ON r.id = x.row_id WHERE r.build_id = ?{o}"
    for x in conn.execute(q.format(t="rd_row_isrc", o=" ORDER BY x.row_id, x.ordinal"), (build_id,)):
        kids["isrc"][x["row_id"]].append((x["isrc"], x["registered"], x["via"]))
    for x in conn.execute(q.format(t="rd_row_work", o=" ORDER BY x.row_id, x.ordinal"), (build_id,)):
        kids["work"][x["row_id"]].append((x["work_no"], x["registered"]))
    for x in conn.execute(q.format(t="rd_row_amount", o=""), (build_id,)):
        kids["amount"][x["row_id"]].append((x["statement_id"], x["amount"]))
    for x in conn.execute(q.format(t="rd_row_mrm", o=""), (build_id,)):
        kids["mrm"][x["row_id"]].append((x["month"], x["amount"]))
    for x in conn.execute(q.format(t="rd_row_fy", o=""), (build_id,)):
        kids["fy"][x["row_id"]].append((x["fy"], x["amount"]))
    return kids


@router.get("/builds/{build_id}/rows")
def build_rows(build_id: int, resp: Response, q: str | None = None, status: str | None = None,
               origin: str | None = None, basis: str | None = None, min_amount: float | None = None,
               merged: bool | None = None, sort: str = "ordinal", offset: int = 0, limit: int = 5000,
               conn=Depends(get_conn)):
    where, args = ["r.build_id = ?"], [build_id]
    if q:
        like = f"%{q.strip()}%"
        where.append("(r.name LIKE ? OR r.name_key LIKE ? OR r.id IN (SELECT row_id FROM rd_row_isrc WHERE isrc LIKE ?) "
                     "OR r.id IN (SELECT row_id FROM rd_row_work WHERE work_no LIKE ?))")
        args += [like, f"%{norm(q)}%", f"%{q.strip().upper()}%", like]
    if status:
        codes = status.split(",")
        where.append(f"r.status_code IN ({','.join('?' * len(codes))})")
        args += codes
    if origin:
        where.append("r.origin = ?")
        args.append(origin)
    if basis:
        where.append("r.basis_json LIKE ?")
        args.append(f'%"{basis}"%')
    if min_amount:
        where.append("(r.total_amount >= ? OR r.total_mrm >= ?)")
        args += [min_amount, min_amount]
    if merged is not None:
        where.append("r.merged_keys_json " + ("!=" if merged else "=") + " '[]'")
    order = {"ordinal": "r.ordinal", "amount": "r.total_amount DESC, r.ordinal", "mrm": "r.total_mrm DESC, r.ordinal",
             "name": "r.name_key, r.ordinal"}.get(sort, "r.ordinal")
    w = " AND ".join(where)
    n = db.scalar(conn, f"SELECT COUNT(*) FROM rd_row r WHERE {w}", args)
    rows = db.rows(conn, f"SELECT r.* FROM rd_row r WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?",
                   args + [min(limit, 10000), offset])
    kids = _children(conn, build_id)
    out = []
    for r in rows:
        isr = kids["isrc"].get(r["id"], [])
        wk = kids["work"].get(r["id"], [])
        out.append(dict(id=r["id"], o=r["ordinal"], key=r["row_key"], origin=r["origin"], name=r["name"],
                        isrcs=[i for i, reg, _v in isr], unreg=[i for i, reg, _v in isr if not reg],
                        works=[x for x, _reg in wk], works_unreg=[x for x, reg in wk if not reg],
                        d=r["total_amount"], e=r["total_mrm"], u=r["total_usage"], s=r["status_code"],
                        a={str(k): v for k, v in kids["amount"].get(r["id"], [])},
                        m={k: v for k, v in kids["mrm"].get(r["id"], [])},
                        f={k: v for k, v in kids["fy"].get(r["id"], [])},
                        b=db.loads(r["basis_json"], []), notes=len(db.loads(r["notes_json"], [])),
                        booked=bool(r["booked_note"]), bn=r["booked_note"],
                        merged=len(db.loads(r["merged_keys_json"], [])),
                        dec=r["merged_from_decision"]))
    total(resp, n)
    return out


@router.get("/builds/{build_id}/rows/{row_id}")
def build_row(build_id: int, row_id: int, conn=Depends(get_conn)):
    r = must(db.row(conn, "SELECT * FROM rd_row WHERE id = ? AND build_id = ?", (row_id, build_id)), f"row {row_id}")
    r["basis"] = [dict(code=b, label=BASIS[b]) for b in db.loads(r.pop("basis_json"), [])]
    r["notes"] = db.loads(r.pop("notes_json"), [])
    r["merged_keys"] = db.loads(r.pop("merged_keys_json"), [])
    r["isrcs"] = db.rows(conn, "SELECT isrc, registered, via FROM rd_row_isrc WHERE row_id = ? ORDER BY ordinal", (row_id,))
    r["works"] = db.rows(conn, "SELECT work_no, registered FROM rd_row_work WHERE row_id = ? ORDER BY ordinal", (row_id,))
    r["distributions"] = db.rows(conn, "SELECT a.statement_id, a.amount, a.raw, st.s_no, st.section, st.category, "
                                       "st.dist_no, st.period, st.stmt_date, sf.filename FROM rd_row_amount a JOIN "
                                       "statement st ON st.id = a.statement_id JOIN source_file sf ON sf.id = "
                                       "st.source_file_id WHERE a.row_id = ? ORDER BY st.stmt_date, st.s_no", (row_id,))
    # statement metadata as the build saw it (the layout snapshot), so a later override never
    # changes what an existing build shows
    layout = db.loads(db.scalar(conn, "SELECT layout_json FROM build_run WHERE id = ?", (build_id,)), {})
    snap = {st["id"]: dict(st, section=sec["section"]) for sec in layout.get("sections", [])
            if sec["kind"] == "statement" for st in sec["statements"]}
    for d in r["distributions"]:
        s = snap.get(d["statement_id"])
        if s:
            d.update(s_no=s["s_no"], section=s["section"], dist_no=s["dist_no"], period=s["period"], stmt_date=s["date"])
    r["distributions"].sort(key=lambda d: (d["stmt_date"] or "", d["s_no"]))
    r["months"] = [dict(m, label=month_label(m["month"])) for m in db.rows(
        conn, "SELECT month, amount, raw FROM rd_row_mrm WHERE row_id = ? ORDER BY month", (row_id,))]
    r["fy"] = [dict(f, label=fy_label(f["fy"])) for f in db.rows(
        conn, "SELECT fy, amount FROM rd_row_fy WHERE row_id = ? ORDER BY fy = 'NA', fy", (row_id,))]
    r["platform_isrcs"] = [dict(x, basis_label=BASIS.get(x["basis"], x["basis"])) for x in db.rows(
        conn, "SELECT isrc, basis, revenue, title, album FROM rd_row_mrm_isrc WHERE row_id = ? ORDER BY revenue DESC",
        (row_id,))]
    r["status_template"] = STATUS.get(r["status_code"])
    r["decision"] = None
    if r["merged_from_decision"]:
        d = db.row(conn, "SELECT * FROM merge_decision WHERE id = ?", (r["merged_from_decision"],))
        if d:
            d["evidence"] = db.loads(d.pop("evidence_json"), [])
            d["members"] = [x["row_key"] for x in db.rows(conn, "SELECT row_key FROM merge_decision_member WHERE "
                                                               "decision_id = ?", (d["id"],))]
            r["decision"] = d
    r["candidates"] = db.rows(conn, "SELECT c.id, c.kind, c.confidence, c.band, c.status FROM merge_candidate c JOIN "
                                    "merge_candidate_member m ON m.candidate_id = c.id WHERE m.rd_row_id = ?", (row_id,))
    return r


@router.get("/builds/{build_id}/statements")
def build_statements(build_id: int, conn=Depends(get_conn)):
    return db.rows(conn, "SELECT st.id, st.s_no, st.dist_no, st.category, st.section, st.schema, st.period, "
                         "st.stmt_date, st.work_count, st.line_count, st.extracted_total, st.file_total, st.reconciled, "
                         "sf.filename FROM statement st JOIN build_statement bs ON bs.statement_id = st.id JOIN "
                         "source_file sf ON sf.id = st.source_file_id WHERE bs.build_id = ? ORDER BY st.s_no",
                   (build_id,))


# ------------------------------------------------------------------ §11 coverage
class CoverageIn(BaseModel):
    sheet_id: int | None = None
    sources: list[str] | None = None
    period_from: str | None = None
    period_to: str | None = None
    mode: str = "RESOLVED"
    min_amount: float = 0
    l3_policy: str = "v2"


@router.get("/builds/{build_id}/coverage/sources")
def coverage_sources(build_id: int, conn=Depends(get_conn)):
    av = coverage_engine.available_sources(conn, build_id)
    return dict(sources=av["sources"])


@router.post("/builds/{build_id}/coverage")
def start_coverage(build_id: int, body: CoverageIn, user: User = Depends(get_user), conn=Depends(get_conn)):
    if body.mode not in ("RESOLVED", "STRICT"):
        raise ValueError("mode must be RESOLVED or STRICT")
    if body.l3_policy not in ("v2", "reference"):
        raise ValueError("l3_policy must be v2 or reference")
    cfg = body.model_dump()
    jid = jobs.submit(conn, "coverage", lambda ctx, c: coverage_engine.run_coverage(ctx, c, build_id, cfg, user.name),
                      build_id=build_id, user=user.name)
    return dict(job_id=jid)


def coverage_view(conn, r: dict) -> dict:
    r = dict(r)
    r["stats"] = db.loads(r.pop("stats_json"), {})
    r["invariants"] = db.loads(r.pop("invariants_json"), [])
    r["sources"] = db.loads(r.pop("sources_json"), [])
    r["sheet"] = db.row(conn, "SELECT id, label FROM user_sheet WHERE id = ?", (r["sheet_id"],))
    r["build_label"] = db.scalar(conn, "SELECT label FROM build_run WHERE id = ?", (r["build_id"],))
    r["exports"] = db.rows(conn, "SELECT id, filename, size, sha256, created_at FROM export_artifact WHERE kind = "
                                 "'coverage' AND ref_id = ? ORDER BY id DESC", (r["id"],))
    return r


def _run_scope(build_id: int | None, batch_id: int | None) -> tuple[str, tuple]:
    if build_id:
        return " WHERE build_id = ?", (build_id,)
    if batch_id:
        return " WHERE build_id IN (SELECT id FROM build_run WHERE batch_id = ?)", (batch_id,)
    return "", ()


@router.get("/coverage")
def list_coverage(resp: Response, build_id: int | None = None, batch_id: int | None = None, conn=Depends(get_conn)):
    w, a = _run_scope(build_id, batch_id)
    rows = db.rows(conn, "SELECT * FROM coverage_run" + w + " ORDER BY id DESC", a)
    total(resp, len(rows))
    return [coverage_view(conn, r) for r in rows]


@router.get("/coverage/{run_id}")
def get_coverage(run_id: int, conn=Depends(get_conn)):
    return coverage_view(conn, must(db.row(conn, "SELECT * FROM coverage_run WHERE id = ?", (run_id,)), f"run {run_id}"))


@router.get("/coverage/{run_id}/rows")
def coverage_rows(run_id: int, resp: Response, q: str | None = None, evidence: str | None = None,
                  present_in: str | None = None, conn=Depends(get_conn)):
    rows = db.rows(conn, "SELECT * FROM coverage_row WHERE run_id = ? ORDER BY ordinal", (run_id,))
    isr, wk = defaultdict(list), defaultdict(list)
    for x in conn.execute("SELECT i.* FROM coverage_row_isrc i JOIN coverage_row r ON r.id = i.row_id WHERE r.run_id = ? "
                          "ORDER BY i.row_id, i.ordinal", (run_id,)):
        isr[x["row_id"]].append(x["isrc"])
    for x in conn.execute("SELECT w.* FROM coverage_row_work w JOIN coverage_row r ON r.id = w.row_id WHERE r.run_id = ? "
                          "ORDER BY w.row_id, w.ordinal", (run_id,)):
        wk[x["row_id"]].append(x["work_no"])
    out = []
    for r in rows:
        d = db.loads(r.pop("detail_json"), {})
        r.update(isrcs=isr.get(r["id"], []), work_nos=wk.get(r["id"], []), statements=d.get("statements", {}),
                 months=d.get("months", {}), fy=d.get("fy", {}), spellings=d.get("spellings", []),
                 albums=d.get("albums", []))
        if q and q.lower() not in (r["song_name"].lower() + " " + " ".join(r["isrcs"]) + " " + " ".join(r["work_nos"])).lower():
            continue
        if evidence and r["evidence"] != evidence:
            continue
        if present_in and r["present_in"] != present_in:
            continue
        out.append(r)
    total(resp, len(out))
    return out


@router.get("/coverage/{run_id}/explain")
def coverage_explain(run_id: int, row_id: int | None = None, ref: str | None = None, conn=Depends(get_conn)):
    if row_id:
        r = must(db.row(conn, "SELECT * FROM coverage_row WHERE id = ? AND run_id = ?", (row_id, run_id)), f"row {row_id}")
        d = db.loads(r["detail_json"], {})
        return dict(kind="finding", song_name=r["song_name"], evidence=r["evidence"], present_in=r["present_in"],
                    trace=d.get("trace", []), name_in_sheet=d.get("name_in_sheet", []), spellings=d.get("spellings", []))
    if ref:
        key = ref.strip() if ref.strip().isdigit() else ik(ref)
        x = db.row(conn, "SELECT x.*, e.name entry_name, e.sheet_row FROM coverage_exclusion x LEFT JOIN user_sheet_entry e "
                         "ON e.id = x.matched_entry WHERE x.run_id = ? AND x.src_ref = ?", (run_id, key))
        if x:
            x["entry"] = dict(id=x["matched_entry"], name=x.pop("entry_name"), sheet_row=x.pop("sheet_row"))
            x["entry"]["isrcs"] = [i["isrc"] for i in db.rows(conn, "SELECT isrc FROM user_sheet_entry_isrc WHERE "
                                                                   "entry_id = ? ORDER BY ordinal", (x["matched_entry"],))]
            x["entry"]["work_nos"] = [w["work_no"] for w in db.rows(conn, "SELECT work_no FROM user_sheet_entry_work "
                                                                         "WHERE entry_id = ?", (x["matched_entry"],))]
            return dict(kind="excluded", **x)
        return dict(kind="unknown", ref=ref, detail="this identifier is neither a finding nor an excluded record of "
                                                    "the run - it earned nothing in the selected sources")
    raise ValueError("pass row_id or ref")


@router.get("/coverage/{run_id}/exclusions")
def coverage_exclusions(run_id: int, resp: Response, rung: str | None = None, q: str | None = None,
                        offset: int = 0, limit: int = 200, conn=Depends(get_conn)):
    where, args = ["x.run_id = ?"], [run_id]
    if rung:
        where.append("x.rung = ?")
        args.append(rung)
    if q:
        where.append("(x.src_ref LIKE ? OR x.src_name LIKE ?)")
        args += [f"%{q.upper()}%", f"%{q}%"]
    w = " AND ".join(where)
    total(resp, db.scalar(conn, f"SELECT COUNT(*) FROM coverage_exclusion x WHERE {w}", args))
    return db.rows(conn, f"SELECT x.*, e.name entry_name FROM coverage_exclusion x LEFT JOIN user_sheet_entry e ON "
                         f"e.id = x.matched_entry WHERE {w} ORDER BY x.amount DESC LIMIT ? OFFSET ?",
                   args + [limit, offset])


# ------------------------------------------------------------------ §12 merge review
@router.get("/builds/{build_id}/merge-candidates")
def merge_candidates(build_id: int, resp: Response, kind: str | None = None, band: str | None = None,
                     status: str | None = None, q: str | None = None, min_confidence: float | None = None,
                     offset: int = 0, limit: int = 100, conn=Depends(get_conn)):
    where, args = ["c.build_id = ?"], [build_id]
    if kind:
        ks = kind.split(",")
        where.append(f"c.kind IN ({','.join('?' * len(ks))})")
        args += ks
    if band:
        where.append("c.band = ?")
        args.append(band)
    if status:
        where.append("c.status = ?")
        args.append(status)
    if min_confidence is not None:
        where.append("c.confidence >= ?")
        args.append(min_confidence)
    if q:
        where.append("(c.display_name LIKE ? OR c.name_key LIKE ?)")
        args += [f"%{q}%", f"%{norm(q)}%"]
    w = " AND ".join(where)
    total(resp, db.scalar(conn, f"SELECT COUNT(*) FROM merge_candidate c WHERE {w}", args))
    cands = db.rows(conn, f"SELECT c.* FROM merge_candidate c WHERE {w} ORDER BY c.confidence DESC, "
                          f"CASE c.kind WHEN 'VERSION_VARIANT' THEN 1 ELSE 0 END, c.name_key LIMIT ? OFFSET ?",
                    args + [limit, offset])
    b = build_engine.build_summary(conn, build_id)
    section_of = {st["id"]: sec["section"] for sec in b["layout"]["sections"] if sec["kind"] == "statement"
                  for st in sec["statements"]}
    root = b["root_build_id"]
    for c in cands:
        c["signals"] = db.loads(c.pop("signals_json"), [])
        mem = db.rows(conn, "SELECT r.* FROM merge_candidate_member m JOIN rd_row r ON r.id = m.rd_row_id WHERE "
                            "m.candidate_id = ? ORDER BY r.origin != 'catalogue', r.total_amount DESC, r.ordinal", (c["id"],))
        c["members"] = []
        for r in mem:
            by_sec = defaultdict(float)
            for a in db.rows(conn, "SELECT statement_id, amount FROM rd_row_amount WHERE row_id = ?", (r["id"],)):
                by_sec[section_of.get(a["statement_id"], "?")] += a["amount"]
            c["members"].append(dict(
                id=r["id"], key=r["row_key"], name=r["name"], origin=r["origin"], status=r["status_code"],
                d=r["total_amount"], e=r["total_mrm"], u=r["total_usage"],
                isrcs=db.rows(conn, "SELECT isrc, registered, via FROM rd_row_isrc WHERE row_id = ? ORDER BY ordinal", (r["id"],)),
                works=db.rows(conn, "SELECT work_no, registered FROM rd_row_work WHERE row_id = ? ORDER BY ordinal", (r["id"],)),
                by_section={k: round(v, 2) for k, v in by_sec.items()},
                months={x["month"]: x["amount"] for x in db.rows(conn, "SELECT month, amount FROM rd_row_mrm WHERE row_id = ?", (r["id"],))},
                albums=sorted({x["album"] for x in db.rows(conn, "SELECT album FROM rd_row_mrm_isrc WHERE row_id = ? AND album IS NOT NULL", (r["id"],))}),
                titles=sorted({x["title"] for x in db.rows(conn, "SELECT title FROM rd_row_mrm_isrc WHERE row_id = ? AND title IS NOT NULL", (r["id"],))}),
                basis=db.loads(r["basis_json"], [])))
        d = db.row(conn, "SELECT id, verdict, decided_by, decided_at, survivor_key, note FROM merge_decision WHERE "
                         "root_build_id = ? AND kind = ? AND name_key = ? AND active = 1 ORDER BY id DESC LIMIT 1",
                   (root, c["kind"], c["name_key"]))
        c["decision"] = d
    return cands


class DecisionIn(BaseModel):
    candidate_id: int
    verdict: str
    survivor_row: int | None = None
    members: list[int] | None = None
    note: str | None = None


@router.post("/builds/{build_id}/merge-decisions")
def post_decisions(build_id: int, body: list[DecisionIn], user: User = Depends(get_user), conn=Depends(get_conn)):
    ids = merge_apply.record_decisions(conn, build_id, [d.model_dump() for d in body], user.name, user.role)
    return dict(decision_ids=ids)


@router.get("/builds/{build_id}/merge-decisions")
def get_decisions(build_id: int, conn=Depends(get_conn)):
    root = must(db.scalar(conn, "SELECT root_build_id FROM build_run WHERE id = ?", (build_id,)), f"build {build_id}")
    return merge_apply.decision_log(conn, root)


@router.delete("/merge-decisions/{decision_id}")
def revoke(decision_id: int, user: User = Depends(get_user), conn=Depends(get_conn)):
    return merge_apply.revoke_decision(conn, decision_id, user.name, user.role)


@router.post("/builds/{build_id}/apply-merges")
def apply_merges(build_id: int, user: User = Depends(get_user), conn=Depends(get_conn)):
    if user.role not in config.DECIDER_ROLES:
        raise merge_apply.Forbidden("only an analyst or admin may apply merges")
    must(db.row(conn, "SELECT id FROM build_run WHERE id = ?", (build_id,)), f"build {build_id}")
    jid = jobs.submit(conn, "apply_merges",
                      lambda ctx, c: merge_apply.apply_merges(ctx, c, build_id, user.name, user.role),
                      build_id=build_id, user=user.name)
    return dict(job_id=jid)


# ------------------------------------------------------------------ §13 mismatch
class MismatchIn(BaseModel):
    sheet_id: int | None = None
    sources: list[str] | None = None
    period_from: str | None = None
    period_to: str | None = None


@router.post("/builds/{build_id}/mismatch")
def start_mismatch(build_id: int, body: MismatchIn, user: User = Depends(get_user), conn=Depends(get_conn)):
    cfg = body.model_dump()
    jid = jobs.submit(conn, "mismatch", lambda ctx, c: mismatch_engine.run_mismatch(ctx, c, build_id, cfg, user.name),
                      build_id=build_id, user=user.name)
    return dict(job_id=jid)


def mismatch_view(conn, r: dict) -> dict:
    r = dict(r)
    for k in ("counts", "totals", "invariants", "sources"):
        r[k] = db.loads(r.pop(f"{k}_json"), {} if k != "invariants" else [])
    r["build_label"] = db.scalar(conn, "SELECT label FROM build_run WHERE id = ?", (r["build_id"],))
    r["exports"] = db.rows(conn, "SELECT id, filename, size, sha256, created_at FROM export_artifact WHERE kind = "
                                 "'mismatch' AND ref_id = ? ORDER BY id DESC", (r["id"],))
    return r


@router.get("/mismatch")
def list_mismatch(resp: Response, build_id: int | None = None, batch_id: int | None = None, conn=Depends(get_conn)):
    w, a = _run_scope(build_id, batch_id)
    rows = db.rows(conn, "SELECT * FROM mismatch_run" + w + " ORDER BY id DESC", a)
    total(resp, len(rows))
    return [mismatch_view(conn, r) for r in rows]


@router.get("/mismatch/{run_id}")
def get_mismatch(run_id: int, conn=Depends(get_conn)):
    return mismatch_view(conn, must(db.row(conn, "SELECT * FROM mismatch_run WHERE id = ?", (run_id,)), f"run {run_id}"))


@router.get("/mismatch/{run_id}/rows")
def mismatch_rows(run_id: int, resp: Response, kind: str | None = None, q: str | None = None, conn=Depends(get_conn)):
    from ..export.reports import load_mismatch
    run = load_mismatch(conn, run_id)
    out = []
    for d in run["rows"]:
        if kind and d["kind"] != kind:
            continue
        hay = f"{d['main_name']} {d['main_no']} {' '.join(d['isrcs'])} {' '.join(d['values'])}".lower()
        if q and q.lower() not in hay:
            continue
        out.append(d)
    total(resp, len(out))
    return out


# ------------------------------------------------------------------ exports
@router.get("/artifacts")
def artifacts():
    return export_service.ARTIFACTS


@router.post("/builds/{build_id}/exports/{kind}")
def start_export(build_id: int, kind: str, ref_id: int | None = None, user: User = Depends(get_user),
                 conn=Depends(get_conn)):
    if kind not in export_service.ARTIFACTS:
        raise ValueError(f"unknown artifact {kind!r}")
    jid = jobs.submit(conn, "export", lambda ctx, c: export_service.generate(ctx, c, kind, build_id, ref_id, user.name),
                      build_id=build_id, ref_id=ref_id, user=user.name)
    return dict(job_id=jid)


@router.get("/exports")
def list_exports(resp: Response, build_id: int | None = None, conn=Depends(get_conn)):
    out = export_service.list_artifacts(conn, build_id)
    total(resp, len(out))
    return out


@router.get("/exports/{artifact_id}/download")
def download(artifact_id: int, conn=Depends(get_conn)):
    a = must(db.row(conn, "SELECT * FROM export_artifact WHERE id = ?", (artifact_id,)), f"artifact {artifact_id}")
    p = Path(a["path"])
    if not p.exists():
        raise KeyError(f"file for artifact {artifact_id} is gone - generate it again")
    return FileResponse(p, filename=a["filename"],
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"X-SHA256": a["sha256"]})
