"""Normalisation primitives (architecture §7).

Implemented once and shared by the ingester, the build, the coverage engine, the merge
engine, the mismatch engine and the exporter, so no two layers can disagree about what
"the same ISRC" or "the same song name" means.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import Hashable, Mapping

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_LABEL = {v: k.capitalize() for k, v in MONTHS.items()}

JOIN = " | "                                  # the only place a pipe is ever produced (§16)


def s(v) -> str:
    """Safe string."""
    return "" if v is None else str(v).strip()


def num(v) -> float:
    """Safe float; NaN, blanks and junk become 0.0."""
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        return 0.0 if f != f else f
    try:
        f = float(str(v).replace(",", ""))
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


def noi(v) -> str | None:
    """Internal number: 16026924.0 -> '16026924'. Non-numeric text is kept verbatim
    ('NEED TO REGISTER') - an identifier is never dropped."""
    t = s(v)
    if not t:
        return None
    try:
        return str(int(float(t)))
    except (ValueError, OverflowError):
        return t


def is_work_no(v: str | None) -> bool:
    return bool(v) and v.isdigit()


def ik(v) -> str:
    """ISRC key."""
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


def norm(v) -> str:
    """Name key - case / space / punctuation blind."""
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


VER = re.compile(r"\b(lofi|lo fi|cover|reprise|sped up|slowed|version|male|female|remix|"
                 r"theme|instrumental|unplugged|acoustic|duet|original|mix|edit|radio|sad|"
                 r"vocals|title song|from)\b")


def norm2(v) -> str:
    """Name key with version words stripped - the fuzzy fallback."""
    return re.sub(r"[^a-z0-9]", "", VER.sub(" ", s(v).lower()))


def split_ids(v, pattern: str = r"[|,;/\n]+") -> list[str]:
    """One cell -> several identifiers ('a | b', 'a,b'), order preserved."""
    return [x.strip() for x in re.split(pattern, s(v)) if x.strip()]


def isrc_list(v) -> list[str]:
    out: list[str] = []
    for x in split_ids(v):
        k = ik(x)
        if k and k not in out:
            out.append(k)
    return out


# ------------------------------------------------------------------ dates / financial years
def fin_year(d: dt.date) -> int:
    """Indian financial year, 1 Apr - 31 Mar, keyed by its starting calendar year."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(y) -> str:
    if y == "NA":
        return "Period Not Stated"
    y = int(y)
    return f"FY {y}-{str(y + 1)[-2:]}"


def month_end(y: int, m: int) -> dt.date:
    return dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)


def month_key(v) -> str | None:
    """datetime / 'YYYY-MM...' / 'Mon YYYY' -> 'YYYY-MM'."""
    if isinstance(v, (dt.datetime, dt.date)):
        return f"{v.year:04d}-{v.month:02d}"
    t = s(v)
    m = re.match(r"^(\d{4})-(\d{1,2})", t)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.match(r"^([A-Za-z]{3,12})\.?\s+(\d{4})$", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{int(m.group(2)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}"
    return None


def month_label(mk: str) -> str:
    y, m = mk.split("-")
    return f"{MONTH_LABEL[int(m)]} {y}"


def month_end_of(mk: str) -> dt.date:
    y, m = mk.split("-")
    return month_end(int(y), int(m))


def fy_months(st: dt.date, en: dt.date) -> dict[int, int]:
    out: dict[int, int] = defaultdict(int)
    y, m = st.year, st.month
    while (y, m) <= (en.year, en.month):
        out[fin_year(dt.date(y, m, 1))] += 1
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return dict(out)


def fy_weights(st: dt.date | None, en: dt.date | None) -> dict[int, float]:
    """Share of a period falling in each Indian FY, month-weighted. {} = period not stated."""
    if not st or not en:
        return {}
    mm = fy_months(st, en)
    tot = sum(mm.values())
    return {y: k / tot for y, k in sorted(mm.items())} if tot else {}


def periods_overlap(a0, a1, b0, b1) -> bool:
    """Closed-interval overlap; an open bound (None) matches everything."""
    if a0 is None or a1 is None:
        return True
    lo = b0 or dt.date.min
    hi = b1 or dt.date.max
    return a0 <= hi and a1 >= lo


# ------------------------------------------------------------------ money
def r2(v: float) -> float:
    return round(v + 0.0, 2) + 0.0          # + 0.0 normalises -0.0


def penny_fix(parts: Mapping[Hashable, float], target: float) -> dict:
    """Round every part to 2 dp so that the rounded parts still add up to the target.

    The part that lost the most in rounding gets the first extra paisa; parts that are
    exactly zero only take a paisa when nothing else can. Deterministic: the same input
    (in the same order) always gives byte-identical output."""
    out = {k: r2(v) for k, v in parts.items()}
    gap = round(r2(target) - round(sum(out.values()), 2), 2)
    if gap and out:
        step = 0.01 if gap > 0 else -0.01
        keys = [k for k in out if parts[k] != 0] or list(out)
        pool = sorted(keys, key=lambda k: (parts[k] - out[k]), reverse=gap > 0)
        for i in range(int(round(abs(gap) / 0.01))):
            k = pool[i % len(pool)]
            out[k] = r2(out[k] + step)
    return out


def printed_total(parts) -> float:
    """Display rule (§7): a printed total is the sum of the printed parts."""
    return r2(sum(r2(p) for p in parts))
