"""Page 13 - 'Required demonstration before software acceptance'."""
from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from conftest import catalogue, revenue, statement
from flow import STMT_OCT, D, approve_identity, confirm_revenue, member, rule, run, upload
from mrm import cases, db, identity, intake, packs, rules
from mrm.security import Forbidden


def _base(people, client_id, works=(("Alpha", "20000001", "INBBB2500001", 1000, 40),)):
    upload(people, client_id, "catalogue.xlsx", catalogue([(t, w, i) for t, w, i, _, _ in works]))
    m, b = member(client_id)
    st = upload(people, client_id, STMT_OCT, statement(m, b, [(w, t.upper(), p) for t, w, _, _, p in works if p is not None]))
    rv = upload(people, client_id, "revenue.xlsx", revenue([("2025-10", i, t, r) for t, _, i, r, _ in works]))
    confirm_revenue(people, rv["id"])
    return st, rv


def test_reupload_does_not_inflate_totals(people, client_id):
    st, rv = _base(people, client_id)
    m, b = member(client_id)
    again = upload(people, client_id, "copy of statement.xlsx", statement(m, b, [("20000001", "ALPHA", 40)]))
    assert again["repeat"] is True and again["id"] == st["id"]                  # byte-identical: logged and skipped
    assert approve_identity(people, client_id)["ok"]
    rule(people, client_id)
    r = run(people, client_id)
    assert D(r["groups"]["20000001"]["p_amount"]) == Decimal("40")
    assert Decimal(r["summary"]["p_in_scope"]) == Decimal("40")


def test_corrected_statement_supersedes(people, client_id):
    st, _ = _base(people, client_id)
    m, b = member(client_id)
    v2 = upload(people, client_id, "Spotify - for the Period October 2025 to October 2025 (corrected).xlsx",
                statement(m, b, [("20000001", "ALPHA", 45)]))
    assert v2["status"] == "DUPLICATE_REVIEW"                                    # overlapping statement held
    with db.tx() as conn, pytest.raises(Forbidden):
        intake.decide_overlap(conn, people["swatantra"], v2["id"], st["id"], "SUPERSEDES", "uploader cannot approve")
    with db.tx() as conn:
        r = intake.decide_overlap(conn, people["accounts"], v2["id"], st["id"], "SUPERSEDES", "IPRS re-issued statement")
        assert r["status"] == "VALIDATED"
        assert db.scalar(conn, "SELECT status FROM source_file WHERE id = %s", (st["id"],)) == "SUPERSEDED"
    assert approve_identity(people, client_id)["ok"]
    rule(people, client_id)
    g = run(people, client_id)["groups"]["20000001"]
    assert D(g["p_amount"]) == Decimal("45")                                     # old and new never added


def test_all_money_reconciles(people, client_id):
    m, b = member(client_id)
    upload(people, client_id, "catalogue.xlsx", catalogue([("Beta", "20000002", "INBBB2500002")]))
    f = upload(people, client_id, STMT_OCT, statement(m, b, [("20000002", "BETA", 40)], total=41.5))
    assert f["status"] == "RECONCILIATION_HOLD"                                  # 40 lines vs 41.50 printed
    with db.tx() as conn:
        with pytest.raises(Exception):
            intake.approve_control(conn, people["accounts"], f["id"], None, "", [dict(label="fee", amount="1.5")])
    with db.tx() as conn:
        r = intake.approve_control(conn, people["accounts"], f["id"], None, "", [
            dict(label="administration fee withheld", amount="1.50", evidence="IPRS letter 12/2025")])
    assert r["status"] == "VALIDATED"                                            # evidenced bridge, no plug
    rv = upload(people, client_id, "revenue.xlsx", revenue([("2025-10", "INBBB2500002", "Beta", 1000),
                                                            ("2025-10", "INBBB2599999", "Unknown", 77)]))
    confirm_revenue(people, rv["id"])
    approve_identity(people, client_id)
    rule(people, client_id)
    r = run(people, client_id)
    assert all(c["result"] == "PASS" for c in r["checks"][:2])
    s = r["summary"]
    assert Decimal(s["r_in_scope"]) == Decimal(s["r_grouped"]) + Decimal(s["r_unmapped"]) == Decimal("1077")
    assert any(e["kind"] == "UNMAPPED_RECORDING" and D(e["amount"]) == 77 for e in r["exceptions"])


def test_fuzzy_candidates_require_human_decision(people, client_id):
    _base(people, client_id, works=(("Jani Na", "20000003", "INBBB2500003", 300, 10),
                                    ("Jani Naa", "20000004", "INBBB2500004", 200, 5)))
    with db.tx() as conn:
        identity.refresh(conn, client_id, people["devi"])
        cands = db.all(conn, "SELECT * FROM duplicate_candidate WHERE client_id = %s", (client_id,))
        assert len(cands) == 1 and cands[0]["status"] == "PENDING"
        assert db.scalar(conn, "SELECT count(*) FROM composition WHERE client_id = %s AND canonical_id IS NOT NULL",
                         (client_id,)) == 0                                       # never merged automatically
        v = identity.approve_version(conn, people["devi"], client_id)
        assert v["ok"] is False and any(c["gate"] == "C4" and c["result"] == "HOLD" for c in v["checks"])
    with db.tx() as conn:
        identity.decide_candidate(conn, people["devi"], cands[0]["id"], "SAME", "same IPRS work registered twice")
        assert identity.approve_version(conn, people["devi"], client_id)["ok"]
    rule(people, client_id)
    r = run(people, client_id)
    assert len(r["groups"]) == 1                                                 # resolved by decision, not by title
    g = next(iter(r["groups"].values()))
    assert D(g["r_amount"]) == Decimal("500") and D(g["p_amount"]) == Decimal("15")


def test_covers_are_not_proposed_as_duplicates(people, client_id):
    _base(people, client_id, works=(("Mon Bojhe Na", "20000005", "INBBB2500005", 300, 10),
                                    ("Mon Bojhe Na - Cover", "20000006", "INBBB2500006", 50, 1)))
    with db.tx() as conn:
        identity.refresh(conn, client_id, people["devi"])
        assert db.scalar(conn, "SELECT count(*) FROM duplicate_candidate WHERE client_id = %s", (client_id,)) == 0


def test_mixed_rights_stay_separate(people, client_id):
    m, b = member(client_id)
    upload(people, client_id, "catalogue.xlsx", catalogue([("Gamma", "20000007", "INBBB2500007")]))
    upload(people, client_id, STMT_OCT, statement(m, b, [("20000007", "GAMMA", 40, "INTERNET WEBSITE"),
                                                         ("20000007", "GAMMA", 25, "MECHANICAL DIGITAL")]))
    rv = upload(people, client_id, "revenue.xlsx", revenue([("2025-10", "INBBB2500007", "Gamma", 1000)]))
    confirm_revenue(people, rv["id"])
    approve_identity(people, client_id)
    rule(people, client_id)
    r = run(people, client_id)
    assert D(r["groups"]["20000007"]["p_amount"]) == Decimal("40")                # mechanical not added in
    assert any(e["kind"] == "OTHER_RIGHT_SCOPE" and D(e["amount"]) == 25 for e in r["exceptions"])


def test_wrong_period_share_currency_are_held(people, client_id):
    m, b = member(client_id)
    upload(people, client_id, "catalogue.xlsx", catalogue([("Delta", "20000008", "INBBB2500008")]))
    upload(people, client_id, STMT_OCT, statement(m, b, [("20000008", "DELTA", 40)]))
    rv = upload(people, client_id, "revenue.xlsx", revenue([("2025-10", "INBBB2500008", "Delta", 1000),
                                                            ("2025-12", "INBBB2500008", "Delta", 999)]))
    assert rv["status"] == "DATA_EXCEPTION"                                      # basis / share / currency not stated
    with db.tx() as conn:
        f = intake.set_meta(conn, people["swatantra"], rv["id"], dict(territory="IN", currency="USD", basis="NET",
                                                                      share="1", period_from="2025-10-01",
                                                                      period_to="2025-10-31"))
        assert f["status"] == "DATA_EXCEPTION"                                   # December row: wrong period
        bad = db.all(conn, "SELECT invalid_reason FROM recording_line WHERE file_id = %s AND NOT is_valid", (rv["id"],))
        assert len(bad) == 1 and "wrong period" in bad[0]["invalid_reason"]
        with pytest.raises(Exception):
            intake.set_meta(conn, people["swatantra"], rv["id"], dict(share="1.5"))
    with db.tx() as conn:
        intake.accept_row_exceptions(conn, people["accounts"], rv["id"], "December belongs to another period")
    confirm_revenue(people, rv["id"], currency="USD")
    approve_identity(people, client_id)
    rule(people, client_id)
    g = run(people, client_id)["groups"]["20000008"]
    assert g["outcome"] == "HOLD" and g["hold_reason"] == "BASIS"                # USD revenue vs INR statement
    assert g["b_amount"] is None and g["variance"] is None
    assert D(g["r_amount"]) == Decimal("1000")                                   # the held December row is not in R


def test_missing_data_is_not_zero(people, client_id):
    m, b = member(client_id)
    upload(people, client_id, "catalogue.xlsx", catalogue([("Eps", "20000009", "INBBB2500009"),
                                                           ("Zeta", "20000010", "INBBB2500010"),
                                                           ("Eta", "20000011", "INBBB2500011")]))
    upload(people, client_id, STMT_OCT, statement(m, b, [("20000009", "EPS", 40), ("20000010", "ZETA", 0)]))
    rv = upload(people, client_id, "revenue.xlsx", revenue([("2025-10", "INBBB2500009", "Eps", 1000),
                                                            ("2025-10", "INBBB2500010", "Zeta", 1000),
                                                            ("2025-10", "INBBB2500011", "Eta", 1000)]))
    confirm_revenue(people, rv["id"])
    approve_identity(people, client_id)
    rule(people, client_id)
    gs = run(people, client_id)["groups"]
    assert gs["20000010"]["p_status"] == "EXPLICIT_ZERO" and D(gs["20000010"]["p_amount"]) == 0
    assert gs["20000011"]["p_status"] == "NOT_FOUND" and gs["20000011"]["p_amount"] is None
    assert gs["20000011"]["outcome"] == "NO_MATCHING_ENTRY" and gs["20000011"]["provisional"]
    assert gs["20000011"]["variance"] is None                                    # B - 0 never computed as observed


def test_rule_changes_create_new_versions(people, client_id):
    rid = rule(people, client_id)
    with db.tx() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE rule_version SET rate = 0.07 WHERE id = %s", (rid,))
    with db.tx() as conn:
        nid = rules.revise(conn, people["accounts"], rid, dict(rate="0.07", effective_from="2026-04-01"),
                           "society confirmation")
        assert nid != rid
        with pytest.raises(Forbidden):
            rules.approve(conn, people["accounts"], nid)                         # maker is not checker
    with db.tx() as conn:
        rules.approve(conn, people["sherley"], nid)
        rows = {r["version_no"]: r for r in db.all(conn, "SELECT * FROM rule_version WHERE client_id = %s", (client_id,))}
    assert rows[1]["status"] == "RETIRED" and rows[2]["status"] == "APPROVED"
    assert rows[1]["rate"] == Decimal("0.06") and str(rows[1]["effective_to"]) == "2026-03-31"


def test_figures_trace_to_source_rows(people, client_id):
    _base(people, client_id, works=(("Theta", "20000012", "INBBB2500012", 700, 30),))
    approve_identity(people, client_id)
    rule(people, client_id)
    g = run(people, client_id)["groups"]["20000012"]
    with db.tx() as conn:
        for x in g["evidence"]["r_rows"]:
            row = db.one(conn, "SELECT * FROM recording_line WHERE file_id = %s AND row_no = %s", (x["file_id"], x["row"]))
            assert row["isrc"] == x["isrc"] and row["amount"] == D(x["amount"])
        for x in g["evidence"]["p_rows"]:
            row = db.one(conn, "SELECT * FROM publishing_line WHERE file_id = %s AND row_no = %s", (x["file_id"], x["row"]))
            assert row["work_code"] == "20000012" and row["amount"] == D(x["amount"])
    assert sum(D(x["amount"]) for x in g["evidence"]["r_rows"]) == D(g["r_amount"])
    assert sum(D(x["amount"]) for x in g["evidence"]["p_rows"]) == D(g["p_amount"])


def test_resolving_a_case_retains_history(people, client_id):
    _base(people, client_id, works=(("Iota", "20000013", "INBBB2500013", 1000, 40),))
    approve_identity(people, client_id)
    rule(people, client_id)
    r = run(people, client_id)
    with db.tx() as conn:
        p = packs.build(conn, people["swatantra"], r["run_id"])
        with pytest.raises(Forbidden):
            packs.approve(conn, people["swatantra"], p["id"])                     # builder cannot approve
    with db.tx() as conn:
        packs.approve(conn, people["sherley"], p["id"])
        packs.mark_sent(conn, people["sherley"], p["id"], "email 2026-10-08", "2026-10-22")
        case = db.one(conn, "SELECT * FROM enquiry_case WHERE client_id = %s", (client_id,))
        assert case["status"] == "AWAITING_REPLY"
        cases.log_reply(conn, people["sherley"], case["id"], dict(society_status="under review", reason="allocation "
                        "pending", expected_distribution="P2610", reference="IPRS reply 101"))
        with pytest.raises(cases.CaseError):
            cases.close(conn, people["devi"], case["id"], "CLOSED_CORRECTED", "corrected", "x")   # promised: stays open
        cases.payment(conn, people["accounts"], case["id"], "RECEIVED", "20", "statement P2610 row 4")
        cases.close(conn, people["devi"], case["id"], "CLOSED_CORRECTED", "adjustment received", "P2610 statement")
        kinds = [e["kind"] for e in cases.history(conn, case["id"])]
    assert kinds == ["opened", "sent", "reply_logged", "payment_received", "closed"]
    with db.tx() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM case_event WHERE case_id = %s", (case["id"],))
    with db.tx() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE comparison_group SET p_amount = 0 WHERE run_id = %s", (r["run_id"],))
