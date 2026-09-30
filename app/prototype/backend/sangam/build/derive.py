"""S7 derived values: penny-exact cells, totals, the FY split, the status enum, row order.

Rounding happens exactly once, through penny_fix:
  * each statement column is rounded so its cells add up to the statement's own total;
  * the platform month totals are rounded so they add up to the report total, then each
    month column is rounded so its cells add up to that month total;
  * each row's FY split is rounded so it adds up to the row's Total Amount.
A printed total therefore always equals the sum of its printed parts (I24).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..domain.normalize import fy_weights, norm, penny_fix, printed_total, r2
from .model import STATUS, Row


def round_statement_cells(rows: list[Row], statements: list[dict]) -> None:
    by_key = {r.key: r for r in rows}
    for st in statements:
        parts = {r.key: r.raw_amounts[st["id"]] for r in rows if st["id"] in r.raw_amounts}
        if not parts:
            continue
        for k, v in penny_fix(parts, r2(st["extracted_total"])).items():
            by_key[k].amounts[st["id"]] = v


def round_month_cells(rows: list[Row], month_raw: dict[str, float], grand: float) -> dict[str, float]:
    targets = penny_fix(dict(sorted(month_raw.items())), grand)
    by_key = {r.key: r for r in rows}
    for m, t in targets.items():
        parts = {r.key: r.mrm_raw[m] for r in rows if m in r.mrm_raw}
        if parts:
            for k, v in penny_fix(parts, t).items():
                by_key[k].mrm[m] = v
    return targets


def totals_and_fy(rows: list[Row], statements: list[dict]) -> None:
    weights = {}
    for st in statements:
        p0 = dt.date.fromisoformat(st["p_start"]) if st["p_start"] else None
        p1 = dt.date.fromisoformat(st["p_end"]) if st["p_end"] else None
        weights[st["id"]] = fy_weights(p0, p1)
    for r in rows:
        r.total_amount = printed_total(r.amounts.values())
        r.total_mrm = printed_total(r.mrm.values())
        raw: dict[str, float] = defaultdict(float)
        for sid, a in r.amounts.items():
            w = weights[sid]
            if not w:
                raw["NA"] += a
            else:
                for y, f in w.items():
                    raw[str(y)] += a * f
        keys = sorted(k for k in raw if k != "NA") + (["NA"] if "NA" in raw else [])
        r.fy = penny_fix({k: raw[k] for k in keys}, r.total_amount) if raw else {}


def assign_status(rows: list[Row], cat_label: str, n_statements: int, client: str) -> None:
    for r in rows:
        if r.origin == "catalogue":
            if r.owned_works and r.total_amount != 0:
                code = "IN_RECEIVED"
            elif r.owned_works:
                code = "IN_ZERO"
            elif r.sibling_of:
                code = "IN_SIBLING"
            else:
                code = "IN_NONE"
        elif r.origin == "statement":
            code = "NOT_PAID" if r.total_amount != 0 else "NOT_ZERO"
        elif r.origin == "platform":
            code = "NOT_PLATFORM"
        else:
            code = "NOT_USAGE"
        r.status_code = code
        r.status = STATUS[code].format(cat=cat_label, n=n_statements, client=client)


def sort_rows(rows: list[Row]) -> list[Row]:
    """-Total Amount, then -Total platform revenue, then norm(Song Name) (architecture §10.4)."""
    return sorted(rows, key=lambda r: (-r.total_amount, -r.total_mrm, norm(r.name), r.seq))
