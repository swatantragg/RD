"""Second, independent computation of the numbers before any workbook is written (Architecture V3 §14, I18).

The engine groups lines by work / recording and places each group once. This module walks every source line on its
own and finds the row(s) that may carry it by their codes, then compares. A number only one method produces fails
the build.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from . import names
from .engine import Result

ZERO = Decimal("0")


def master(res: Result) -> list[dict]:
    out = []
    by_work: dict[str, list] = defaultdict(list)
    by_isrc: dict[str, list] = defaultdict(list)
    for r in res.rows:
        for w in r.all_works:
            by_work[w].append(r)
        for i in r.all_isrcs:
            by_isrc[i].append(r)
    # royalty: every line -> the one row that carries a non-sibling cell for its statement and work
    got: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
    orphans, multi = [], []
    for st in res.statements:
        key = f"S:{st.file_id}"
        for ln in st.lines:
            if ln.work_no:
                cands = [r for r in by_work.get(ln.work_no, []) if key in r.cells and not r.cells[key].sibling]
            else:
                cands = [r for r in res.rows if r.origin == "hold" and key in r.cells and
                         r.key.startswith(f"hold:nocode:{st.file_id}:")]
                cands = [r for r in cands if r.key.endswith(":" + (ln.raw_work or "blank"))]
            if not cands:
                orphans.append(f"{st.label} row {ln.row_no}")
                continue
            if len(cands) > 1:
                multi.append(f"{st.label} work {ln.work_no}")
            got[(cands[0].key, key)] += ln.amount
    diff = [f"{rk} {ck}: {v} vs {res_row(res, rk).cells[ck].exact}" for (rk, ck), v in got.items()
            if res_row(res, rk).cells[ck].exact != v]
    out.append(dict(id="I18a", ok=not orphans and not multi and not diff,
                    text="every royalty line re-derived line by line lands on exactly one row with the same amount",
                    detail="; ".join((orphans + multi + diff)[:6])))
    # platform: every line -> its row by ISRC (or the held row)
    pgot: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
    porph = []
    for pr in res.platforms:
        for ln in pr.lines:
            if ln.amount is None or not ln.month:
                continue
            key = f"P:{pr.file_id}:{ln.month.isoformat()[:7]}"
            cands = [r for r in by_isrc.get(ln.isrc, []) if key in r.cells] if ln.isrc else \
                    [r for r in res.rows if r.origin == "hold" and key in r.cells and r.key.startswith("hold:noisrc")]
            if not cands:
                porph.append(f"{pr.label} row {ln.row_no}")
                continue
            held = [r for r in cands if r.origin == "hold"]
            assigned = [r for r in cands if ln.isrc in r.assigned_isrcs]
            owner = (held or assigned or sorted(cands, key=lambda r: r.order))[0]
            pgot[(owner.key, key)] += ln.amount
    pdiff = [f"{rk} {ck}" for (rk, ck), v in pgot.items() if res_row(res, rk).cells[ck].exact != v]
    out.append(dict(id="I18b", ok=not porph and not pdiff,
                    text="every platform line re-derived line by line lands on its row with the same amount",
                    detail="; ".join((porph + pdiff)[:6])))
    # printed totals
    tot_rows = sum((r.royalty for r in res.rows), ZERO)
    tot_cols = sum((c.shown_total for b in res.bands if b.kind == "ROYALTY" for c in b.cols), ZERO)
    out.append(dict(id="I23b", ok=tot_rows == tot_cols, text="Total Amount column = sum of the distribution columns",
                    detail=f"{tot_rows} vs {tot_cols}"))
    for b in res.bands:
        if b.kind != "PLATFORM":
            continue
        a = sum((r.platform.get(b.key, ZERO) for r in res.rows), ZERO)
        c = sum((x.shown_total for x in b.cols), ZERO)
        out.append(dict(id="I23c", ok=a == c, text=f"{b.total_header} = sum of its month columns", detail=f"{a} vs {c}"))
    fy = sum((v for r in res.rows for v in r.fy.values()), ZERO)
    out.append(dict(id="I6b", ok=fy == tot_rows, text="financial-year totals = Total Amount", detail=f"{fy} vs {tot_rows}"))
    return out


_cache: dict = {}


def res_row(res: Result, key: str):
    m = _cache.get(id(res))
    if m is None or m[0] is not res:
        m = (res, {r.key: r for r in res.rows})
        _cache.clear()
        _cache[id(res)] = m
    return m[1][key]


def companion(res: Result, groups: list[dict]) -> list[dict]:
    """Every companion amount re-derived straight from the source lines by the group's own codes (I18), and the
    population check that no listed code is in the base (I16)."""
    out = []
    stmt_by_work: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for st in res.statements:
        for ln in st.lines:
            if ln.work_no:
                stmt_by_work[ln.work_no] += ln.amount
    plat_by_isrc: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for pr in res.platforms:
        for ln in pr.lines:
            if ln.isrc and ln.amount is not None and ln.month:
                plat_by_isrc[ln.isrc] += ln.amount
    bad = []
    n_cols = sum(len(b.cols) for b in res.bands)
    budget = Decimal("0.01") * max(1, n_cols)
    for g in groups:
        roy = sum((stmt_by_work[w] for w in g["works"]), ZERO)
        plat = sum((plat_by_isrc[i] for i in g["isrcs"]), ZERO)
        if abs(roy - g["royalty"]) > budget or abs(plat - sum(g["platform"].values(), ZERO)) > budget:
            bad.append(f"{g['title']}: royalty {names.q2(roy)} vs {g['royalty']}, platform {names.q2(plat)} vs "
                       f"{sum(g['platform'].values(), ZERO)}")
    out.append(dict(id="I18c", ok=not bad, text="every companion amount re-derived from the source lines",
                    detail="; ".join(bad[:5])))
    base = {c for r in res.rows if r.in_base for c in r.all_isrcs + r.all_works}
    leak = [g["title"] for g in groups if any(c in base for c in g["isrcs"] + g["works"])]
    out.append(dict(id="I16b", ok=not leak, text="no listed song carries a code that is in the base",
                    detail="; ".join(leak[:5])))
    return out
