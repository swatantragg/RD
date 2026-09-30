"""Command line: load the reference run, verify it, or serve the web app.

    python -m sangam.cli demo [--fresh] [--inputs DIR] [--skip-exports]
    python -m sangam.cli verify
    python -m sangam.cli serve [--host 127.0.0.1] [--port 8765]
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import time

from .core import config, db, jobs


def _run(conn, kind, fn, **kw):
    j = jobs.create(conn, kind, **kw)
    return jobs.run(j, fn)


def load_reference(conn, inputs, *, skip_exports=False, echo=print) -> dict:
    from .coverage.engine import run_coverage
    from .domain.normalize import norm
    from .build.engine import run_build
    from .export.service import generate
    from .ingest import pipeline
    from .merge.apply import apply_merges, record_decisions
    from .mismatch.engine import run_mismatch
    from .reference import REFERENCE_COVERAGE, REFERENCE_MERGES, REFERENCE_MISMATCH
    t0 = time.time()
    bid = pipeline.create_batch(conn, "April 2026 reference run", "demo", note="input/batch-1..4 of the architecture")
    files = []
    for sub in ("batch-1", "batch-2", "batch-3(Only spotify RD)", "batch-4"):
        files += sorted(glob.glob(os.path.join(inputs, sub, "*.xlsx")))
    if not files:
        raise SystemExit(f"no .xlsx files under {inputs}")
    for p in files:
        pipeline.add_file(conn, bid, os.path.basename(p), open(p, "rb").read(), "demo")
    echo(f"  uploaded {len(files)} files into batch #{bid}")
    r = _run(conn, "extract", lambda ctx, c: pipeline.extract_batch(ctx, c, bid), batch_id=bid)
    echo(f"  extract   {r['message']}")
    r = _run(conn, "build", lambda ctx, c: run_build(ctx, c, bid, {"name_fallback": "exact"}, "demo"), batch_id=bid)
    base = r["build_id"]
    echo(f"  build     {r['message']}")
    cat = db.scalar(conn, "SELECT catalogue_sheet_id FROM build_run WHERE id = ?", (base,))
    cov = {}
    for pol in ("reference", "v2"):
        cfg = dict(REFERENCE_COVERAGE, sheet_id=cat, l3_policy=pol)
        r = _run(conn, "coverage", lambda ctx, c, cfg=cfg: run_coverage(ctx, c, base, cfg, "demo"), build_id=base)
        cov[pol] = r["run_id"]
        echo(f"  coverage  [{pol}] {r['message']}")
    r = _run(conn, "mismatch", lambda ctx, c: run_mismatch(ctx, c, base, dict(REFERENCE_MISMATCH, sheet_id=cat), "demo"),
             build_id=base)
    mm = r["run_id"]
    echo(f"  mismatch  {r['message']}")
    decs = []
    for name in REFERENCE_MERGES:
        c = db.row(conn, "SELECT id FROM merge_candidate WHERE build_id = ? AND name_key = ? AND kind != "
                         "'VERSION_VARIANT'", (base, norm(name)))
        if c:
            decs.append(dict(candidate_id=c["id"], verdict="MERGE", note="reference SKV8 merge"))
    record_decisions(conn, base, decs, "demo-analyst", "analyst")
    r = _run(conn, "apply_merges", lambda ctx, c: apply_merges(ctx, c, base, "demo-analyst", "analyst"), build_id=base)
    merged = r["build_id"]
    echo(f"  merge     {r['message']}")
    if not skip_exports:
        for kind, b_, ref in (("skv", base, None), ("skv", merged, None), ("coverage", base, cov["v2"]),
                              ("coverage", base, cov["reference"]), ("mismatch", base, mm),
                              ("merge_list", merged, None), ("register", merged, None), ("gap_works", merged, None),
                              ("gap_platform", merged, None), ("gap_usage", merged, None)):
            r = _run(conn, "export", lambda ctx, c, k=kind, b=b_, ref=ref: generate(ctx, c, k, b, ref, "demo"), build_id=b_)
            echo(f"  export    {r['message'][:150]}")
    echo(f"  done in {time.time() - t0:.1f}s")
    return dict(batch_id=bid, base=base, merged=merged, coverage=cov, mismatch=mm)


def verify(conn, echo=print) -> bool:
    from .reference import compare
    ok = True
    bid = db.scalar(conn, "SELECT MAX(id) FROM ingest_batch")
    if not bid:
        echo("no batch loaded - run `demo` first")
        return False
    echo(f"\nInvariants (architecture §20) - batch #{bid}")
    for b in db.rows(conn, "SELECT id, label, status, invariants_json FROM build_run WHERE batch_id = ? ORDER BY id", (bid,)):
        inv = db.loads(b["invariants_json"], [])
        echo(f"  build #{b['id']} {b['label']}: {sum(i['passed'] for i in inv)}/{len(inv)} PASS  [{b['status']}]")
        for i in inv:
            if not i["passed"]:
                ok = False
                echo(f"     FAIL {i['id']} {i['label']}: expected {i['expected']} got {i['actual']} {i['detail']}")
    for t, lbl in (("coverage_run", "coverage"), ("mismatch_run", "mismatch")):
        for r in db.rows(conn, f"SELECT id, status, invariants_json FROM {t} ORDER BY id"):
            inv = db.loads(r["invariants_json"], [])
            echo(f"  {lbl} run #{r['id']}: {sum(i['passed'] for i in inv)}/{len(inv)} PASS "
                 f"({', '.join(i['id'] for i in inv)})")
            ok = ok and all(i["passed"] for i in inv)
    echo("\nReference numbers (architecture Appendix C)")
    for c in compare(conn, bid):
        mark = {True: "MATCH", False: "DIFF ", None: "NOTE "}[c["match"]]
        echo(f"  {mark} {c['item']}\n         expected {c['expected']}\n         actual   {c['actual']}")
        if c["note"]:
            echo(f"         why      {c['note']}")
        if c["match"] is False:
            ok = False
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sangam")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="load the architecture's reference inputs end to end")
    d.add_argument("--fresh", action="store_true", help="delete the existing database and exports first")
    d.add_argument("--inputs", default=str(config.REFERENCE_INPUT_DIR))
    d.add_argument("--skip-exports", action="store_true")
    sub.add_parser("verify", help="print invariants and the reference-number comparison")
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if a.cmd == "demo":
        if a.fresh:
            for p in (config.DB_PATH, config.DB_PATH.with_suffix(".db-wal"), config.DB_PATH.with_suffix(".db-shm")):
                if p.exists():
                    p.unlink()
            shutil.rmtree(config.EXPORT_DIR, ignore_errors=True)
        config.ensure_dirs()
        conn = db.connect()
        print(f"Sangam - loading the reference run from {a.inputs}")
        load_reference(conn, a.inputs, skip_exports=a.skip_exports)
        ok = verify(conn)
        sys.exit(0 if ok else 1)
    if a.cmd == "verify":
        sys.exit(0 if verify(db.connect()) else 1)
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("sangam.api.app:app", host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
