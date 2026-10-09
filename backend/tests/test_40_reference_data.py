"""The supplied SVF files (Docs/input) run end to end: every control holds on real data."""
from __future__ import annotations

from decimal import Decimal

import pytest

from mrm import config, db

pytestmark = pytest.mark.skipif(not (config.REPO_ROOT / "Docs" / "input" / "batch-2").exists(),
                                reason="reference files not present")


def test_demo_walkthrough_on_reference_files():
    import legacy_walkthrough
    out = legacy_walkthrough.run_demo(echo=lambda *_: None)
    with db.tx() as conn:
        run = db.one(conn, "SELECT * FROM comparison_run WHERE id = %s", (out["run_id"],))
        files = {f["id"]: f for f in db.all(conn, "SELECT f.* FROM source_file f JOIN client c ON c.id = f.client_id "
                                                   "WHERE c.code = 'SVF'")}
        pack = db.one(conn, "SELECT * FROM report_pack WHERE id = %s", (out["pack_id"],))
    assert all(f["status"] == "VALIDATED" for f in files.values())
    stmt = next(f for f in files.values() if f["income_type"] == "PUBLISHING")
    assert abs(stmt["lines_total"] - Decimal("113848.57")) < Decimal("0.01")       # IPRS printed TOTAL ROYALTIES
    assert abs(stmt["printed_total"] - stmt["lines_total"]) < Decimal("0.01")
    assert all(c["result"] == "PASS" for c in run["checks"]), run["checks"]
    s = run["summary"]
    assert abs(Decimal(s["p_in_scope"]) - Decimal("113848.57")) < Decimal("0.01")
    assert abs(Decimal(s["r_in_scope"]) - Decimal("7889496.76")) < Decimal("0.01")   # MRM Spotify Oct-25..Mar-26
    t = s["by_currency"][0]
    assert t["currency"] == "INR" and t["comparable_groups"] > 1000
    assert Decimal(t["positive_gaps"]) > 0 and Decimal(t["above_benchmark"]) >= 0
    assert pack["status"] == "DRAFT" and pack["sha256"]
