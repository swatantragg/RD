"""The golden layer (§24): rebuild from Docs/input and hold every published number - or the
documented reason it differs - plus the accuracy invariants of §20."""
import hashlib
import json

import pytest

from sangam.build.engine import build_summary, load_rows
from sangam.core import db, jobs
from sangam.coverage.engine import run_coverage
from sangam.domain.normalize import norm
from sangam.export.service import generate
from sangam.merge.apply import apply_merges, content_sha, record_decisions, revoke_decision
from sangam.reference import REFERENCE_COVERAGE, compare

from .conftest import needs_reference

pytestmark = needs_reference


def _job(conn, fn):
    return jobs.run(jobs.create(conn, "test"), fn)


def test_every_statement_reconciles(conn, ref):
    v = db.row(conn, "SELECT COUNT(*) n, SUM(reconciled) ok, SUM(schema='Standard') std, SUM(ROUND(extracted_total,2)) t "
                     "FROM statement WHERE batch_id = ?", (ref["batch_id"],))
    assert (v["n"], v["ok"], v["std"]) == (46, 46, 28)
    assert round(v["t"], 2) == 3323794.31


def test_all_invariants_pass(conn, ref):
    for bid in (ref["base"], ref["merged"]):
        inv = build_summary(conn, bid)["invariants"]
        assert inv and all(i["passed"] for i in inv), [i for i in inv if not i["passed"]]
    for t in ("coverage_run", "mismatch_run"):
        for r in db.rows(conn, f"SELECT invariants_json FROM {t}"):
            assert all(i["passed"] for i in db.loads(r["invariants_json"], []))


def test_reference_numbers(conn, ref):
    rows = compare(conn, ref["batch_id"])
    bad = [r for r in rows if r["match"] is False]
    assert not bad, bad
    assert sum(1 for r in rows if r["match"] is True) >= 14


def test_base_build_totals_and_statuses(conn, ref):
    b = build_summary(conn, ref["base"])
    assert b["total_amount"] == 3323794.31 and b["total_mrm"] == 7889496.76
    by = b["stats"]["by_status"]
    assert (by["IN_RECEIVED"], by["NOT_PAID"], by["IN_ZERO"], by["NOT_ZERO"]) == (1795, 318, 18, 13)
    assert b["stats"]["catalogue_rows"] == 2762


def test_coverage_reference_result(conn, ref):
    r = db.row(conn, "SELECT * FROM coverage_run WHERE id = ?", (ref["coverage"]["reference"],))
    s = db.loads(r["stats_json"])
    assert (r["finding_count"], s["statement_only"], s["platform_only"], s["both"]) == (93, 13, 71, 9)
    assert (r["revenue_at_risk"], r["royalty_received"], r["name_present_count"]) == (250956.32, 1140.08, 18)
    assert (s["strict_works"], s["strict_isrcs"]) == (36, 129)
    assert s["exclusions"] == {"E1": 1343, "E2": 1630, "E3": 14, "E4": 48}


def test_coverage_v2_rule_is_stricter(conn, ref):
    a = db.row(conn, "SELECT finding_count FROM coverage_run WHERE id = ?", (ref["coverage"]["v2"],))["finding_count"]
    assert a > 93                                           # uniqueness on both sides resolves fewer titles


def test_coverage_leak_free_on_other_sheets(conn, ref):
    """I14/I15 on a different sheet - the batch-4 TYPE F list."""
    sheet = db.row(conn, "SELECT id FROM user_sheet WHERE batch_id = ? AND is_catalogue = 0", (ref["batch_id"],))
    res = _job(conn, lambda ctx, c: run_coverage(ctx, c, ref["base"], dict(REFERENCE_COVERAGE, sheet_id=sheet["id"],
                                                                          l3_policy="v2"), "test"))
    inv = db.loads(db.scalar(conn, "SELECT invariants_json FROM coverage_run WHERE id = ?", (res["run_id"],)))
    assert all(i["passed"] for i in inv)


def test_mismatch_totals(conn, ref):
    m = db.row(conn, "SELECT * FROM mismatch_run WHERE id = ?", (ref["mismatch"],))
    t = db.loads(m["totals_json"])
    assert (t["royalty"], t["gross"], t["both"]) == (61206.05, 3722218.78, 3783424.83)
    c = db.loads(m["counts_json"])["by_kind"]
    assert (c["Different ISRC"], c["Different Internal Number"], c["Different Song Name"]) == (245, 120, 413)


def test_reference_merges_reproduce_skv8(conn, ref):
    rows = {r.name: r for r in load_rows(conn, ref["merged"])}
    expect = {
        "Cinderella Mon": (["28964597", "26297314"], ["INS2X2210002", "USQY52429704", "USQY52431173", "INS2X2209002"]),
        "Ei Je Tomar Prem": (["29764577", "25809088"], ["INS2X2001114", "USQY52437614", "INS2X2001113"]),
        "Leelabali": (["31627630", "30677046"], ["INS2X2400163", "INS2X2500102", "INS2X2403601"]),
        "Mathura Nagarpati": (["31627589", "5846855"], ["INS2X1900406", "INS2X2306001", "INS2X2401301"]),
        "Roder Nishana": (["28964618", "26297316"], ["INS2X2210004", "INS2X2209004"]),
    }
    for name, (nos, isrcs) in expect.items():
        assert rows[name].ordered_works() == nos, name
        assert rows[name].ordered_isrcs() == isrcs, name
    base = build_summary(conn, ref["base"])
    merged = build_summary(conn, ref["merged"])
    assert base["row_count"] - merged["row_count"] == 5
    assert (merged["total_amount"], merged["total_mrm"]) == (base["total_amount"], base["total_mrm"])


def test_leelabali_is_not_suggested(conn, ref):
    c = db.row(conn, "SELECT confidence, band FROM merge_candidate WHERE build_id = ? AND name_key = ? AND kind != "
                     "'VERSION_VARIANT'", (ref["base"], norm("Leelabali")))
    assert c["band"] != "suggested"                        # both numbers separately registered (§12.2)


def test_merge_is_reversible_and_deterministic(conn, ref):
    root = ref["base"]
    base_sha = content_sha(load_rows(conn, root))
    merged_sha = content_sha(load_rows(conn, ref["merged"]))
    # re-applying the same decisions gives the identical build (I25)
    again = _job(conn, lambda ctx, c: apply_merges(ctx, c, ref["merged"], "t", "analyst"))
    assert content_sha(load_rows(conn, again["build_id"])) == merged_sha
    # revoking every decision and applying restores the parent exactly
    active = db.rows(conn, "SELECT id FROM merge_decision WHERE root_build_id = ? AND active = 1", (root,))
    for d in active:
        revoke_decision(conn, d["id"], "t", "analyst")
    undone = _job(conn, lambda ctx, c: apply_merges(ctx, c, again["build_id"], "t", "analyst"))
    assert content_sha(load_rows(conn, undone["build_id"])) == base_sha
    # restore the reference decisions for the other tests
    for d in active:
        conn.execute("UPDATE merge_decision SET active = 1, revoked_at = NULL, revoked_by = NULL WHERE id = ?", (d["id"],))


def test_not_the_same_suppresses_the_group(conn, ref):
    c = db.row(conn, "SELECT * FROM merge_candidate WHERE build_id = ? AND kind = 'SAME_NAME_DIFF_ISRC' ORDER BY id LIMIT 1",
               (ref["base"],))
    [did] = record_decisions(conn, ref["base"], [dict(candidate_id=c["id"], verdict="NOT_THE_SAME")], "t", "analyst")
    new = _job(conn, lambda ctx, cn: apply_merges(ctx, cn, ref["base"], "t", "analyst"))
    status = db.scalar(conn, "SELECT status FROM merge_candidate WHERE build_id = ? AND name_key = ? AND kind = ?",
                       (new["build_id"], c["name_key"], c["kind"]))
    assert status == "not_same"                            # the same question is never asked twice
    revoke_decision(conn, did, "t", "analyst")


def test_viewer_cannot_decide(conn, ref):
    from sangam.merge.apply import Forbidden
    c = db.scalar(conn, "SELECT id FROM merge_candidate WHERE build_id = ? LIMIT 1", (ref["base"],))
    with pytest.raises(Forbidden):
        record_decisions(conn, ref["base"], [dict(candidate_id=c, verdict="MERGE")], "v", "viewer")


def test_exports_are_byte_identical(conn, ref, tmp_path):
    a = _job(conn, lambda ctx, c: generate(ctx, c, "register", ref["merged"], None, "t"))["artifacts"][0]
    b = _job(conn, lambda ctx, c: generate(ctx, c, "register", ref["merged"], None, "t"))["artifacts"][0]
    assert a["sha256"] == b["sha256"] and b["deterministic"] is True
    cov = _job(conn, lambda ctx, c: generate(ctx, c, "coverage", ref["base"], ref["coverage"]["reference"], "t"))
    assert len(cov["artifacts"]) == 2
    inv = db.loads(db.scalar(conn, "SELECT invariants_json FROM coverage_run WHERE id = ?", (ref["coverage"]["reference"],)))
    assert any(i["id"] == "I16" and i["passed"] for i in inv)            # list == revenue workbook, same order


def test_builds_and_runs_stay_immutable(conn, ref):
    """A file a build (or a coverage run) used can no longer be re-extracted, re-typed or re-mapped."""
    from sangam.ingest import pipeline
    st_file = db.scalar(conn, "SELECT source_file_id FROM statement WHERE batch_id = ? LIMIT 1", (ref["batch_id"],))
    with pytest.raises(ValueError, match="immutable"):
        pipeline.patch_file(conn, st_file, {"kind": "UNKNOWN"})
    res = _job(conn, lambda ctx, c: pipeline.extract_batch(ctx, c, ref["batch_id"], force=True))
    assert res["extracted"] < 50                                 # files used by builds were kept, not rebuilt
    cat = db.row(conn, "SELECT id FROM user_sheet WHERE batch_id = ? AND is_catalogue = 1", (ref["batch_id"],))
    same = {f: m["col_index"] for f, m in {r["field"]: r for r in db.rows(
        conn, "SELECT field, col_index FROM user_sheet_column_map WHERE sheet_id = ?", (cat["id"],))}.items()}
    assert pipeline.confirm_mapping(conn, cat["id"], same, "t")["entries"] == 2762     # same map is fine
    with pytest.raises(ValueError, match="catalogue of build"):
        pipeline.confirm_mapping(conn, cat["id"], {"song_name": 0, "isrc": 2}, "t")
    assert db.scalar(conn, "SELECT COUNT(*) FROM build_statement WHERE build_id = ?", (ref["base"],)) == 46


def test_pipes_live_only_in_exports(conn, ref):
    """§16: no identifier column in the database holds a '|'."""
    for table, col in (("user_sheet_entry_isrc", "isrc"), ("rd_row_isrc", "isrc"), ("rd_row_work", "work_no"),
                       ("coverage_row_isrc", "isrc"), ("mismatch_value", "value_text")):
        if col == "value_text":
            continue                                        # values are song names, stored verbatim
        assert db.scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE '%|%'") == 0, table


def test_shuffled_input_order_changes_no_output_byte(conn, ref):
    """§24 property: a second batch uploaded in reverse order builds a byte-identical SKV workbook."""
    import glob
    import os
    from sangam.build.engine import run_build
    from sangam.ingest import pipeline
    from .conftest import REF_INPUT
    files = []
    for sub in ("batch-1", "batch-2", "batch-3(Only spotify RD)", "batch-4"):
        files += sorted(glob.glob(os.path.join(str(REF_INPUT), sub, "*.xlsx")))
    bid = pipeline.create_batch(conn, "shuffled", "t")
    for p in reversed(files):
        pipeline.add_file(conn, bid, os.path.basename(p), open(p, "rb").read(), "t")
    _job(conn, lambda ctx, c: pipeline.extract_batch(ctx, c, bid))
    other = _job(conn, lambda ctx, c: run_build(ctx, c, bid, {"name_fallback": "exact"}, "t"))["build_id"]
    a = _job(conn, lambda ctx, c: generate(ctx, c, "skv", ref["base"], None, "t"))["artifacts"][0]
    b = _job(conn, lambda ctx, c: generate(ctx, c, "skv", other, None, "t"))["artifacts"][0]
    assert a["sha256"] == b["sha256"] and a["size"] == b["size"]
