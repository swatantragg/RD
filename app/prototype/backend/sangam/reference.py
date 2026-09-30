"""Appendix C of the architecture - "the numbers a rebuild must reproduce" - checked against
the live database, with the reason for every known difference stated next to it."""
from __future__ import annotations

from .core import db
from .domain.normalize import r2

REFERENCE_COVERAGE = dict(sources=["spotify", "spotify_mrm"], period_from="2025-10", period_to="2026-03",
                          mode="RESOLVED")
REFERENCE_MISMATCH = dict(sources=["spotify", "spotify_mrm"], period_from="2025-10", period_to="2026-03")
REFERENCE_MERGES = ["Cinderella Mon", "Ei Je Tomar Prem", "Leelabali", "Mathura Nagarpati", "Roder Nishana"]


def _row(item, expected, actual, note="", exact=True):
    ok = (expected == actual) if exact else None
    return dict(item=item, expected=expected, actual=actual, match=ok, note=note)


def compare(conn, batch_id: int) -> list[dict]:
    out = []
    v = db.row(conn, "SELECT COUNT(*) n, SUM(schema='Standard') std, SUM(schema='Overseas') ovs, "
                     "SUM(ROUND(extracted_total, 2)) tot, SUM(reconciled) ok FROM statement WHERE batch_id = ?",
               (batch_id,))
    out.append(_row("statements (standard + overseas)", "46 (28 + 18)", f"{v['n']} ({v['std']} + {v['ovs']})"))
    out.append(_row("statements reconciled (I1)", "46/46", f"{v['ok']}/{v['n']}"))
    out.append(_row("total royalty distributed", "3,323,794.31", f"{r2(v['tot'] or 0):,.2f}"))
    cat = db.row(conn, "SELECT id FROM user_sheet WHERE batch_id = ? AND is_catalogue = 1 ORDER BY id DESC LIMIT 1",
                 (batch_id,))
    if cat:
        c = db.row(conn, "SELECT COUNT(*) n, COUNT(DISTINCT name_key) k FROM user_sheet_entry WHERE sheet_id = ?", (cat["id"],))
        nos = db.scalar(conn, "SELECT COUNT(DISTINCT w.work_no) FROM user_sheet_entry_work w JOIN user_sheet_entry e ON "
                              "e.id = w.entry_id WHERE e.sheet_id = ?", (cat["id"],))
        isr = db.scalar(conn, "SELECT COUNT(DISTINCT i.isrc) FROM user_sheet_entry_isrc i JOIN user_sheet_entry e ON "
                              "e.id = i.entry_id WHERE e.sheet_id = ?", (cat["id"],))
        out.append(_row("catalogue rows · internal nos · ISRCs · name keys", "2,762 · 2,571 · 4,278 · 2,570",
                        f"{c['n']:,} · {nos:,} · {isr:,} · {c['k']:,}"))
    s = db.row(conn, "SELECT COUNT(*) n, SUM(ROUND(extracted_total, 2)) t, SUM(work_count) w FROM statement WHERE "
                     "batch_id = ? AND category_code = 'spotify' AND period LIKE 'Oct 2025%'", (batch_id,))
    out.append(_row("IPRS Spotify Oct25-Mar26 total · works", "113,848.57 · 1,379", f"{r2(s['t'] or 0):,.2f} · {s['w'] or 0:,}"))
    for kind, lbl, exp in (("REVENUE", "Spotify MRM lines · ISRCs · total", "10,960 · 1,759 · 7,889,496.76"),
                           ("USAGE", "Spotify usage rows", "11,222")):
        p = db.row(conn, "SELECT SUM(line_count) l, SUM(isrc_count) i, SUM(total) t FROM platform_report WHERE "
                         "batch_id = ? AND kind = ?", (batch_id, kind))
        act = (f"{p['l'] or 0:,} · {p['i'] or 0:,} · {r2(p['t'] or 0):,.2f}" if kind == "REVENUE" else f"{p['l'] or 0:,}")
        out.append(_row(lbl, exp, act))
    base = db.row(conn, "SELECT * FROM build_run WHERE batch_id = ? AND generation = 0 ORDER BY id DESC LIMIT 1", (batch_id,))
    if base:
        st = db.loads(base["stats_json"], {})
        out.append(_row("base build (SKV7) rows", "3,149", f"{base['row_count']:,}",
                        "SKV7's universe inherited SKV6 history: 41 rows appended by name in SKV6 plus 7 + 8 "
                        "platform-only rows. The clean-room build gives 2,762 catalogue + 331 statement-only + "
                        f"{st.get('platform_rows', 0)} revenue-only + {st.get('usage_rows', 0)} usage-only rows.",
                        exact=False))
        by = st.get("by_status", {})
        out.append(_row("status: royalty received · paid NOT in list · 0.00 in list · 0.00 NOT in list",
                        "1,795 · 318 · 18 · 13",
                        f"{by.get('IN_RECEIVED', 0):,} · {by.get('NOT_PAID', 0):,} · {by.get('IN_ZERO', 0):,} · "
                        f"{by.get('NOT_ZERO', 0):,}"))
        out.append(_row("status: siblings (booked on another row)", "168", f"{by.get('IN_SIBLING', 0):,}",
                        "SKV7 booked each shared work on the FIRST catalogue entry; V2 §9 S6a books it on the entry "
                        "whose name matches the statement title (e.g. 'Bojhena Shey Bojhena (Female Version)'), and "
                        "SKV7 also marked 2 never-paid shared works as siblings.", exact=False))
        out.append(_row("col D total · col E total (base build)", "3,323,794.31 · 7,889,496.76",
                        f"{base['total_amount']:,.2f} · {base['total_mrm']:,.2f}"))
    merged = db.row(conn, "SELECT * FROM build_run WHERE batch_id = ? AND generation >= 1 ORDER BY id DESC LIMIT 1",
                    (batch_id,))
    if merged and base:
        out.append(_row("merge apply: rows folded away · totals unchanged", "5 · yes",
                        f"{base['row_count'] - merged['row_count']} · "
                        f"{'yes' if abs(merged['total_amount'] - base['total_amount']) < 0.005 and abs(merged['total_mrm'] - base['total_mrm']) < 0.005 else 'NO'}"))
    for pol, label in (("reference", "reference-run title link"), ("v2", "V2 rule: unique on both sides")):
        runs = db.rows(conn, "SELECT cr.* FROM coverage_run cr JOIN build_run b ON b.id = cr.build_id WHERE "
                             "b.batch_id = ? AND cr.mode = 'RESOLVED' AND cr.sheet_id = ? AND cr.period_from = ? "
                             "AND cr.period_to = ? ORDER BY cr.id DESC",
                       (batch_id, cat["id"] if cat else -1, REFERENCE_COVERAGE["period_from"],
                        REFERENCE_COVERAGE["period_to"]))
        run = next((r for r in runs if db.loads(r["stats_json"], {}).get("l3_policy") == pol
                    and db.loads(r["sources_json"], []) == sorted(REFERENCE_COVERAGE["sources"])), None)
        if not run:
            continue
        s2 = db.loads(run["stats_json"], {})
        act = (f"{run['finding_count']} ({s2['statement_only']} · {s2['platform_only']} · {s2['both']}) · "
               f"{run['revenue_at_risk']:,.2f} · {run['royalty_received']:,.2f} · {run['name_present_count']}")
        exp = "93 (13 · 71 · 9) · 250,956.32 · 1,140.08 · 18"
        out.append(_row(f"coverage RESOLVED [{label}]: songs · at stake · royalty · name present", exp, act,
                        "" if pol == "reference" else
                        "The spec's text requires L3 title links to be unique on BOTH sides (§8, §11.2); its "
                        "published 93 was produced by scripts that did not. Stricter rule -> more findings.",
                        exact=pol == "reference"))
        out.append(_row(f"coverage STRICT count [{label}]", "36 works + 129 ISRCs",
                        f"{s2['strict_works']} works + {s2['strict_isrcs']} ISRCs"))
    mm = db.row(conn, "SELECT mr.* FROM mismatch_run mr JOIN build_run b ON b.id = mr.build_id WHERE b.batch_id = ? "
                      "AND mr.sheet_id = ? AND mr.period_from = ? AND mr.period_to = ? ORDER BY mr.id DESC LIMIT 1",
                (batch_id, cat["id"] if cat else -1, REFERENCE_MISMATCH["period_from"], REFERENCE_MISMATCH["period_to"]))
    if mm:
        c = db.loads(mm["counts_json"], {})["by_kind"]
        t = db.loads(mm["totals_json"], {})
        out.append(_row("mismatch rows (ISRC · internal no · name)", "781 (245 · 121 · 415)",
                        f"{mm['row_count']} ({c['Different ISRC']} · {c['Different Internal Number']} · "
                        f"{c['Different Song Name']})",
                        "The published report contains 3 junk rows built from the statement's footer (the "
                        "SUMMARY OF ROYALTY language table read as works: internal no 'BENGALI', 'SANSKRIT', "
                        "names '1.0' / '54.0'). Without them: 245 · 120 · 413 = 778.", exact=False))
        out.append(_row("mismatch V2 totals (royalty · gross · both)", "61,206.05 · 3,722,218.78 · 3,783,424.83",
                        f"{t['royalty']:,.2f} · {t['gross']:,.2f} · {t['both']:,.2f}"))
    return out
