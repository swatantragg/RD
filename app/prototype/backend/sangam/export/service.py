"""Export orchestration (§19.2 step 6): write -> sha256 -> store -> export_artifact row.
Paired deliverables are generated together so their cross-checks (I12, I16) run on the
files a user actually downloads."""
from __future__ import annotations

from ..core import config, db
from . import coverage_xlsx, reports, skv

ARTIFACTS = {
    "skv": dict(label="SVF-RD-SKV master matrix", scope="build", section="§10"),
    "coverage": dict(label="Coverage audit - finding list + revenue workbook", scope="coverage", section="§11"),
    "merge_list": dict(label="Same-Name / Different-ISRC list", scope="build", section="§12.5"),
    "mismatch": dict(label="Song-ID-Mismatch report V1 + V2", scope="mismatch", section="§13"),
    "register": dict(label="Statement register", scope="build", section="§14"),
    "gap_works": dict(label="Works paid but missing from the catalogue", scope="build", section="§14"),
    "gap_platform": dict(label="Platform revenue but missing from the catalogue", scope="build", section="§14"),
    "gap_usage": dict(label="Streams only, missing from the catalogue", scope="build", section="§14"),
}


def _dir(build_id: int, kind: str, ref_id):
    return config.EXPORT_DIR / f"build-{build_id}" / f"{kind}-{ref_id or 0}"


def _record(conn, build_id, kind, ref_id, filename, path, info, user) -> dict:
    prev = db.row(conn, "SELECT sha256 FROM export_artifact WHERE build_id = ? AND kind = ? AND "
                        "COALESCE(ref_id, 0) = ? AND filename = ? ORDER BY id DESC LIMIT 1",
                  (build_id, kind, ref_id or 0, filename))
    with db.tx(conn):
        aid = db.insert(conn, "export_artifact", dict(build_id=build_id, kind=kind, ref_id=ref_id, filename=filename,
                                                      path=str(path), size=info["size"], sha256=info["sha256"],
                                                      rows=info.get("rows"), created_at=db.now(), created_by=user))
    return dict(id=aid, filename=filename, size=info["size"], sha256=info["sha256"], rows=info.get("rows"),
                deterministic=None if not prev else prev["sha256"] == info["sha256"])


def _upsert_invariant(conn, table: str, run_id: int, inv: dict) -> None:
    cur = db.loads(db.scalar(conn, f"SELECT invariants_json FROM {table} WHERE id = ?", (run_id,)), [])
    cur = [i for i in cur if i["id"] != inv["id"]] + [inv]
    ok = all(i["passed"] for i in cur)
    conn.execute(f"UPDATE {table} SET invariants_json = ?, status = ? WHERE id = ?",
                 (db.dumps(sorted(cur, key=lambda i: int(i["id"][1:]))), "ready" if ok else "invariant_failed", run_id))


def generate(ctx, conn, kind: str, build_id: int, ref_id: int | None = None, user: str | None = None) -> dict:
    from ..build.engine import _inv, build_summary
    if kind not in ARTIFACTS:
        raise ValueError(f"unknown artifact {kind!r}")
    b = build_summary(conn, build_id)
    if not b:
        raise ValueError(f"build {build_id} not found")
    d = _dir(build_id, kind, ref_id)
    out = []
    ctx.progress(0.1, f"writing {ARTIFACTS[kind]['label']}")
    if kind == "skv":
        fn = f"{b['label']}.xlsx"
        out.append(_record(conn, build_id, kind, None, fn, d / fn, skv.write_skv(conn, build_id, d / fn), user))
    elif kind == "coverage":
        if not ref_id:
            raise ValueError("coverage export needs a coverage run id")
        run = coverage_xlsx.load_run(conn, ref_id)
        client = b["layout"].get("client", "Spotify")
        f1, f2 = "Songs-Missing-From-SVF-List.xlsx", "Songs-Missing-From-SVF-List-Revenue.xlsx"
        out.append(_record(conn, build_id, kind, ref_id, f1, d / f1, coverage_xlsx.write_list(run, d / f1), user))
        ctx.progress(0.5, "writing the revenue workbook")
        out.append(_record(conn, build_id, kind, ref_id, f2, d / f2, coverage_xlsx.write_revenue(run, d / f2, client), user))
        chk = coverage_xlsx.check_population_identity(d / f1, d / f2)
        _upsert_invariant(conn, "coverage_run", ref_id, _inv(
            "I16", "the finding list and the revenue workbook hold the same songs in the same order",
            f"{len(run['rows'])} == {len(run['rows'])}", f"{chk['list_rows']} == {chk['revenue_rows']}",
            chk["identical"] and chk["list_rows"] == len(run["rows"])))
    elif kind == "mismatch":
        if not ref_id:
            raise ValueError("mismatch export needs a mismatch run id")
        run = reports.load_mismatch(conn, ref_id)
        f1, f2 = "Song-ID-Mismatch-Report.xlsx", "Song-ID-Mismatch-Report-V2-With-Revenue.xlsx"
        out.append(_record(conn, build_id, kind, ref_id, f1, d / f1, reports.write_mismatch(run, d / f1, False), user))
        out.append(_record(conn, build_id, kind, ref_id, f2, d / f2, reports.write_mismatch(run, d / f2, True), user))
        chk = reports.check_v1_v2(d / f1, d / f2)
        _upsert_invariant(conn, "mismatch_run", ref_id, _inv(
            "I12", "mismatch V1 and V2 carry identical A-G content and row count", f"{len(run['rows'])} == {len(run['rows'])}",
            f"{chk['v1_rows']} == {chk['v2_rows']}", chk["identical"] and chk["v1_rows"] == len(run["rows"])))
    elif kind == "merge_list":
        fn = "Same-Name-Different-ISRC.xlsx"
        out.append(_record(conn, build_id, kind, None, fn, d / fn, reports.write_merge_list(conn, build_id, d / fn), user))
    elif kind == "register":
        fn = "Statement-Register.xlsx"
        out.append(_record(conn, build_id, kind, None, fn, d / fn, reports.write_register(conn, build_id, d / fn), user))
    else:
        which = kind.split("_", 1)[1]
        fn = {"works": "Works-Paid-But-Missing-From-SVF-Song-List.xlsx",
              "platform": "Spotify-Revenue-But-Missing-From-SVF-Song-List.xlsx",
              "usage": "Spotify-Streams-Only-Missing-From-SVF-Song-List.xlsx"}[which]
        out.append(_record(conn, build_id, kind, None, fn, d / fn, reports.write_gap(conn, build_id, which, d / fn), user))
    msg = "; ".join(f"{a['filename']} ({a['size']:,} bytes, sha256 {a['sha256'][:12]}…)" for a in out)
    ctx.log(msg)
    return dict(message=msg, artifacts=out)


def list_artifacts(conn, build_id: int | None = None) -> list[dict]:
    q = "SELECT id, build_id, kind, ref_id, filename, size, sha256, rows, created_at, created_by FROM export_artifact"
    if build_id:
        return db.rows(conn, q + " WHERE build_id = ? ORDER BY id DESC", (build_id,))
    return db.rows(conn, q + " ORDER BY id DESC LIMIT 200")
