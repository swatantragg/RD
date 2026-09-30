"""Unit tests for the normalisation primitives, the filename grammar, shape detection and the
statement extractor (architecture §24 'Unit' and 'Fixture' layers)."""
import datetime as dt
import glob
import os
import random

import pytest

from sangam.domain import sniff
from sangam.domain.filename import parse_filename
from sangam.domain.link import NameIndex, l3_recover
from sangam.domain.normalize import fin_year, fy_label, fy_weights, ik, noi, norm, norm2, penny_fix, printed_total
from sangam.ingest.sheets import load_entries
from sangam.ingest.statement import extract_statement

from .conftest import REF_INPUT, needs_reference


# ------------------------------------------------------------------ §7 primitives
def test_noi():
    assert noi("16026924.0") == "16026924"
    assert noi(16026924.0) == "16026924"
    assert noi("NEED TO REGISTER") == "NEED TO REGISTER"          # never drop an identifier
    assert noi("") is None and noi(None) is None


def test_keys():
    assert norm("Aaj  Amaye!") == "aajamaye"
    assert norm2("Abar Phire Ele-Lofi") == norm2("Abar Phire Ele")
    assert norm2("Bhalobashar Morshum (Male version)") == norm2("Bhalobashar Morshum (Female Version)")
    assert ik(" ins2x-09-00009 ") == "INS2X0900009"


def test_fy():
    assert fin_year(dt.date(2025, 3, 31)) == 2024 and fin_year(dt.date(2025, 4, 1)) == 2025
    assert fy_label(2025) == "FY 2025-26" and fy_label("NA") == "Period Not Stated"
    w = fy_weights(dt.date(2025, 1, 1), dt.date(2025, 6, 30))            # Jan-Mar in FY24, Apr-Jun in FY25
    assert w == {2024: 0.5, 2025: 0.5}
    assert fy_weights(None, None) == {}


@pytest.mark.parametrize("seed", range(25))
def test_penny_fix_restores_the_target(seed):
    rnd = random.Random(seed)
    parts = {i: rnd.uniform(0, 5000) / 7 for i in range(rnd.randint(1, 60))}
    target = round(sum(parts.values()), 2)
    out = penny_fix(parts, target)
    assert round(sum(out.values()), 2) == target                       # rounded parts add up to the total
    assert all(abs(out[k] - parts[k]) < 0.0101 for k in parts)          # no part moves by more than a paisa
    assert out == penny_fix(parts, target)                              # deterministic


def test_printed_total_display_rule():
    months = [2217.955, 2217.955, 2217.955, 2217.955, 2217.955, 2217.955]
    assert printed_total(months) == round(sum(round(m, 2) for m in months), 2)   # defect D3


# ------------------------------------------------------------------ §8 L3 uniqueness
def test_l3_requires_uniqueness_on_both_sides():
    stmt = NameIndex([dict(name="AAJ JYOTSNA RAATEY", no="15628816"), dict(name="AAJ JYOTSNA RAATEY", no="29764517")],
                     lambda r: r["name"])
    plat = NameIndex([dict(name="Aaj Jyotsna Raatey", isrc="INS2X1800201")], lambda r: r["name"])
    assert l3_recover("Aaj Jyotsna Raatey", plat, stmt) is None         # two works share the title (D6)
    plat2 = NameIndex([dict(name="Tomake Chai", isrc="X")], lambda r: r["name"])
    one = NameIndex([dict(name="TOMAKE CHAI", no="1")], lambda r: r["name"])
    assert l3_recover("Tomake Chai", plat2, one)["no"] == "1"               # unique on both sides -> link


# ------------------------------------------------------------------ §6 filename grammar
def test_parse_filename_cases():
    m = parse_filename("(S-13)Royalty Distribution - P2550 YouTube Pre Claims - July 2025 to September 2025 "
                       "Including Non-Identified GE Music on Basis.xlsx")
    assert (m["s_no"], m["dist_no"], m["category"], m["period"]) == (13, "P2550", "YouTube Pre-Claims", "Jul 2025 - Sep 2025")
    m = parse_filename("(S-2)Royalty Distribution - P2101 to P2540 - P2107A008~5154290.xlsx")
    assert m["dist_no"] == "P2107A008" and m["period"] == "Not specified"
    m = parse_filename("(S-44)Royalty Redistribution - for P2101 to P2550 - SVF ENTERTAINMENT PRIVATE LIMITED.xlsx")
    assert m["dist_no"] == "P2101 to P2550" and m["category"] == "Redistribution"
    m = parse_filename("(S-17)Royalty Distribution - P2555 Collections from Overseas Societies - April 2024 to March 2025 - 101 SOCAN.xlsx")
    assert m["section"] == "Overseas - SOCAN (Canada)" and m["society_code"] == "101"
    m = parse_filename("(S-1)Royalty Distribution - M2506 For MUSREK - Collectiones during F.Y. 2025-26 - Mechanical.xlsx")
    assert m["dist_no"] == "M2506" and m["period"] == "Apr 2025 - Mar 2026 (FY 2025-26)" and m["category"] == "Mechanical (MUSERK)"
    m = parse_filename("Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx")
    assert m["s_no"] is None and m["category"] == "Spotify" and m["period"] == "Oct 2025 - Mar 2026"


@needs_reference
def test_parse_filename_over_every_real_statement():
    names = [os.path.basename(p) for p in glob.glob(str(REF_INPUT / "batch-*" / "*.xlsx"))]
    stmts = [n for n in names if "Royalty" in n or "Spotify - for" in n]
    assert len(stmts) == 46
    for n in stmts:
        m = parse_filename(n)
        assert m["category"] != "Other / Unclassified" or "P2101 to P2540" in n, n
        if m["category"] == "Overseas":
            assert m["section"].startswith("Overseas - "), n


# ------------------------------------------------------------------ §5 shapes + the extractor on fixtures
def _type_a(last_amount=0.37, total_override=None):
    g = [["INTERNAL NO", 5154290.0, "IPI NAME NO", "00871526032"] + [None] * 8,
         ["NAME", "SVF ENTERTAINMENT PRIVATE LIMITED,  ", "IPI BASE NO", "I-004791736-0"] + [None] * 8,
         [None] * 12,
         ["WORK INT NO", "TITLE", "AV", "LANGUAGE", "NAME", "ROLE", "SOCIETY", "OWN", "COLL", "POOL", "SOURCE", "ROYALTY AMT"]]
    amts = [119.2258, 3.5, last_amount]
    for i, a in enumerate(amts):
        g += [[15617483.0 + i, f"SONG {i}", None, "BENGALI", "COMPOSER", "C", "IPRS", 25.0, 25.0, None, None, None],
              [None, None, None, None, "SVF ENTERTAINMENT", "E", "IPRS", 50.0, 50.0, "INTERNET", "SPOTIFY AB", a],
              [None] * 11 + [a], [None] * 12]
    total = round(sum(amts), 6) if total_override is None else total_override
    g += [[None] * 7 + ["TOTAL ROYALTIES", None, None, None, total], [None] * 12,
          ["SUMMARY OF ROYALTY"] + [None] * 11, ["LANGUAGE", "NO. OF WORKS", "ROYALTY AMT"] + [None] * 9,
          ["BENGALI", 3.0, total] + [None] * 9]
    return g


def test_type_a_extraction_rules():
    x = extract_statement(_type_a(), "S-99")
    assert x["schema"] == "Standard" and len(x["lines"]) == 3 and len(x["blocks"]) == 3
    assert abs(x["extracted_total"] - (119.2258 + 3.5 + 0.37)) < 1e-9          # sub-total lines not double counted
    assert x["reconciled"] and x["checks"]["money_vs_subtotal"] and x["checks"]["stopped_before_total"]
    assert x["blocks"][-1]["amount"] == pytest.approx(0.37)                   # D1: the total never lands on the last work
    assert x["letterhead"]["member_no"] == "5154290" and x["letterhead"]["member_name"] == "SVF ENTERTAINMENT PRIVATE LIMITED"
    assert x["footer"]["languages"][0]["language"] == "BENGALI"


def test_type_a_reconciliation_failure_is_detected():
    x = extract_statement(_type_a(total_override=999.0), "S-99")
    assert not x["reconciled"] and x["checks"]["money_vs_printed"] is False


def test_type_b_extraction_keeps_zero_lines():
    g = [["INTERNAL NO", 5154290.0, "IPI NAME NO", "00871526032"] + [None] * 13,
         ["NAME", "SVF", "IPI BASE NO", "I-004791736-0"] + [None] * 13, [None] * 17,
         ["WORK INT NO", "TITLE", "AV", "LANGUAGE", "NAME", "ROLE", "SOCIETY", "OWN", "COLL", "RADIO", "TV", "CINEMAS",
          "PERMITS", "DEMAND", "GENERAL", "OTHERS", "ROYALTY AMT"],
         [5846855.0, "MATHURA NAGAR PATI", None, "HINDI", "A, B", "C", "IPRS", 25.0, 0.0] + [0.0] * 8,
         [None, None, None, None, "SVF", "E", "IPRS", 50.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.5, 1.5],
         [None] * 9 + [0.0] * 6 + [1.5, 1.5], [None] * 17,
         [None] * 7 + ["TOTAL ROYALTIES", None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.5, 1.5]]
    assert sniff.detect(g) == sniff.STATEMENT_OVERSEAS
    x = extract_statement(g, "S-98")
    assert x["schema"] == "Overseas" and len(x["lines"]) == 2                 # the 0.0 line is a real line
    assert x["lines"][1]["buckets"]["OTHERS"] == 1.5 and x["reconciled"]


def test_type_f_ugly_sheet_mapping():
    g = [["My songs - exported from somewhere", None, None, None],
         ["Title of Work", "IPRS Work No", "Recording Code(s)", "Remarks"],
         ["Aaj Amaye", 15617483, "INS2X0900009, INE400901947", "ok"],
         ["Tumi Amar", None, "INS2X1000002", ""],
         ["Ekakitwo - The Poem", "NEED TO REGISTER", "", "register"],
         ["Mon Kharap", 15587400.0, "INS2X2207003|INS2X2207004", None]]
    p = sniff.propose_mapping(g)
    assert p["header_row"] == 1
    assert {f: m["col_index"] for f, m in p["mapping"].items()} == {"song_name": 0, "internal_no": 1, "isrc": 2}
    entries = load_entries(g, p["header_row"], p["mapping"])
    assert [e["isrcs"] for e in entries][0] == ["INS2X0900009", "INE400901947"]         # comma list exploded
    assert entries[2]["work_nos"] == ["NEED TO REGISTER"] and entries[1]["work_nos"] == []
    assert sniff.detect(g) == sniff.USER_SHEET


def test_sheet_without_identity_column_is_rejected():
    g = [["Colour", "Weight"], ["red", 1], ["blue", 2]]
    assert sniff.detect(g) == sniff.UNKNOWN
