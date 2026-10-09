"""A1-A5: decide what each file represents, from its content (never from the platform or sender name alone),
and read whatever metadata the file itself states. Anything not stated stays blank for the operator (B3)."""
from __future__ import annotations

import re

from ..normalize import month_end, period_from_text, s
from . import iprs, tabular

REQUIRED_META = {
    "PUBLISHING": ("territory", "period_from", "period_to", "currency", "member_id"),
    "RECORDING": ("platform", "territory", "period_from", "period_to", "currency", "basis", "share"),
    "USAGE": ("platform", "territory", "period_from", "period_to", "metric"),
    "IDENTITY": (),
    "OTHER": (),
}
META_FIELDS = ("sender", "payer", "platform", "territory", "period_from", "period_to", "currency", "basis", "share",
               "metric", "member_id", "beneficiary", "use_type", "distribution_ref", "statement_version")


def classify(sheets: list[dict]) -> dict:
    """-> {income_type, sheet, header_row, mapping, why}"""
    for sh in sheets:
        if iprs.header_row(sh["rows"]) is not None:
            return dict(income_type="PUBLISHING", sheet=sh["title"], header_row=iprs.header_row(sh["rows"]),
                        mapping=None, why="IPRS statement layout (WORK INT NO / ROYALTY AMT) - composition income")
    for sh in sheets:
        if sh.get("state", "visible") != "visible":
            continue
        found = tabular.find_header(sh["rows"])
        if not found:
            continue
        h, m = found
        k = tabular.kind_of(m)
        why = {"RECORDING": "ISRC + revenue columns - sound recording / master income",
               "USAGE": "ISRC + usage count, no money column - usage-only evidence (money stays unknown)",
               "IDENTITY": "work code + ISRC columns - catalogue / link table (feeds page 4)",
               "OTHER": "identifier column found but no revenue, usage or work-code column"}[k]
        if k != "OTHER":
            return dict(income_type=k, sheet=sh["title"], header_row=h, mapping=m, why=why)
    return dict(income_type="OTHER", sheet=None, header_row=None, mapping=None,
                why="no recognised layout: the right being paid for is not clear (classification hold)")


def meta_from_filename(name: str) -> dict:
    out: dict = {}
    a, b = period_from_text(name)
    if a:
        out["period_from"], out["period_to"] = a.isoformat(), b.isoformat()
    low = name.lower()
    if "iprs" in low or "royalty distribution" in low or "royalty redistribution" in low:
        out["sender"] = "IPRS"
    m = re.search(r"\b([PM]\d{4})\b", name)
    if m:
        out["distribution_ref"] = m.group(1)
    return out


def meta_from_content(kind: str, extracted: dict, lines: list[dict]) -> dict:
    out: dict = {}
    if kind == "PUBLISHING":
        lh = extracted["letterhead"]
        if lh.get("member_id"):
            out["member_id"] = lh["member_id"]
        if lh.get("beneficiary"):
            out["beneficiary"] = lh["beneficiary"]
        out["sender"] = out["payer"] = "IPRS"
        plats = {x["platform"] for x in lines if x.get("platform")}
        if len(plats) == 1:
            out["platform"] = plats.pop()
        uses = {x["use_type"] for x in lines if x.get("use_type")}
        if len(uses) == 1:
            out["use_type"] = uses.pop()
        return out
    if kind in ("RECORDING", "USAGE"):
        plats = {x["platform"] for x in lines if x.get("platform")}
        if len(plats) == 1:
            out["platform"] = next(iter(plats))
        terr = {x["territory"] for x in lines if x.get("territory")}
        if len(terr) == 1:
            out["territory"] = next(iter(terr))
        months = sorted({x["month"] for x in lines if x.get("month")})
        if months:
            out["period_from"] = months[0].isoformat()
            out["period_to"] = month_end(months[-1].year, months[-1].month).isoformat()
        if kind == "RECORDING":
            cur = {x["currency"] for x in lines if x.get("currency")}
            if len(cur) == 1:
                out["currency"] = next(iter(cur))
        if kind == "USAGE":
            out["metric"] = "streams"
        uses = {x["use_type"] for x in lines if x.get("use_type")}
        if len(uses) == 1:
            out["use_type"] = next(iter(uses))
    return out


def missing(kind: str, meta: dict) -> list[str]:
    return [f for f in REQUIRED_META.get(kind, ()) if not s(meta.get(f))]
