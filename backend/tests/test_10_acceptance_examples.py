"""Page 12 - 'Examples for Swatantra's acceptance check'."""
from __future__ import annotations

from decimal import Decimal

from conftest import catalogue, revenue, statement, usage
from flow import STMT_OCT, D, approve_identity, confirm_revenue, member, rule, run, upload


def _setup(people, client_id, cat, stmt_works, rev_lines=None, use_lines=None, stmt=True):
    upload(people, client_id, "catalogue.xlsx", catalogue(cat))
    if stmt:
        m, b = member(client_id)
        upload(people, client_id, STMT_OCT, statement(m, b, stmt_works))
    if rev_lines:
        f = upload(people, client_id, "revenue.xlsx", revenue(rev_lines))
        assert confirm_revenue(people, f["id"])["status"] == "VALIDATED"
    if use_lines:
        f = upload(people, client_id, "streams.xlsx", usage(use_lines))
        assert confirm_revenue(people, f["id"], currency=None, basis=None, share=None)["status"] == "VALIDATED"
    assert approve_identity(people, client_id)["ok"]
    rule(people, client_id)
    return run(people, client_id)


def test_1000_recording_40_publishing(people, client_id):
    r = _setup(people, client_id, [("Song One", "10000001", "INAAA2500001")], [("10000001", "SONG ONE", 40)],
               [("2025-10", "INAAA2500001", "Song One", 1000)])
    g = r["groups"]["10000001"]
    assert D(g["r_amount"]) == Decimal("1000") and D(g["p_amount"]) == Decimal("40")
    assert D(g["b_amount"]) == Decimal("60") and D(g["variance"]) == Decimal("20")
    assert g["outcome"] == "BELOW_COMPARISON" and g["method"] == "MRM_BENCHMARK"
    assert "indicative benchmark" in g["limitations"] and "not" in g["limitations"]      # not a debt


def test_50_recording_1_publishing(people, client_id):
    r = _setup(people, client_id, [("Song Two", "10000002", "INAAA2500002")], [("10000002", "SONG TWO", 1)],
               [("2025-10", "INAAA2500002", "Song Two", 50)])
    g = r["groups"]["10000002"]
    assert (D(g["b_amount"]), D(g["variance"])) == (Decimal("3"), Decimal("2"))
    assert D(g["r_amount"]) == Decimal("50") and D(g["p_amount"]) == Decimal("1")       # both originals reported
    assert g["outcome"] == "BELOW_COMPARISON"


def test_10000_streams_revenue_unknown(people, client_id):
    r = _setup(people, client_id, [("Song Three", "10000003", "INAAA2500003")], [("10000003", "SONG THREE", 2)],
               use_lines=[("2025-10", "INAAA2500003", "Song Three", 10000)])
    g = r["groups"]["10000003"]
    assert g["n_streams"] == 10000 and g["r_amount"] is None
    assert g["b_amount"] is None and g["variance"] is None                             # no universal per-stream rate
    assert g["outcome"] == "COVERAGE_ONLY" and g["route"] == "COVERAGE"


def test_two_masters_one_work(people, client_id):
    r = _setup(people, client_id, [("Song Four", "10000004", "INAAA2500004|INAAA2500005")],
               [("10000004", "SONG FOUR", 40)],
               [("2025-10", "INAAA2500004", "Song Four", 400), ("2025-10", "INAAA2500005", "Song Four (Reprise)", 600)])
    assert len(r["groups"]) == 1
    g = r["groups"]["10000004"]
    assert D(g["r_amount"]) == Decimal("1000") and D(g["p_amount"]) == Decimal("40")      # P once, never twice
    assert len(g["evidence"]["p_rows"]) == 1 and len(g["recordings"]) == 2
    assert (D(g["b_amount"]), D(g["variance"])) == (Decimal("60"), Decimal("20"))
    assert all(c["result"] == "PASS" for c in r["checks"][:2])


def test_statement_missing_is_unknown_not_unpaid(people, client_id):
    r = _setup(people, client_id, [("Song Five", "10000006", "INAAA2500006")], [], stmt=False,
               rev_lines=[("2025-10", "INAAA2500006", "Song Five", 500)])
    g = r["groups"]["10000006"]
    assert g["p_amount"] is None and g["variance"] is None and g["positive_gap"] is None
    assert g["outcome"] == "STATUS_ENQUIRY" and g["p_status"] in ("MISSING_STATEMENT", "PENDING_CYCLE")
    tot = r["summary"]["by_currency"][0]
    assert Decimal(tot["positive_gaps"]) == 0 and tot["comparable_groups"] == 0      # not added to differences
