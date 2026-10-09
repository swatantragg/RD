"""Statement metadata from the file name, then from the content (V3 §2.6). Every value records where it came from.

File-name grammar of the reference set, e.g.
  (S-13)Royalty Distribution - P2550 YouTube Pre Claims - July 2025 to September 2025 ...
  (S-1)Royalty Distribution - M2506 For MUSREK - Collectiones during F.Y. 2025-26 - Mechanical
  (S-16)Royalty Distribution - P2555 Collections from Overseas Societies - April 2024 to March 2025 - 026 CASH
  (S-2)Royalty Distribution - P2101 to P2540 - P2107A008~5154290
  Spotify - for the Period October 2025 to March 2026(from IPRS)
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from ..normalize import MONTH_LABEL, MONTHS, month_end
from .rules import OVERSEAS_SOCIETIES

CENT = Decimal("0.01")


def q2(v: Decimal) -> Decimal:
    r = Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)
    return r + 0 if r != 0 else Decimal("0.00")


def stem(filename: str) -> str:
    return re.sub(r"\.(xlsx|csv|xlsm|xls)$", "", filename.strip(), flags=re.I)


def short_label(filename: str) -> str:
    """'(S-46)SVF list of Song -April 2026.xlsx' -> 'S-46'; otherwise a shortened file name."""
    m = re.match(r"^\s*\((S-\d+)\)", filename)
    if m:
        return m.group(1)
    t = stem(filename)
    return t if len(t) <= 40 else t[:38] + "…"


# ------------------------------------------------------------------ periods
_MY = re.compile(r"([A-Za-z]{3,12})\.?\s*'?(\d{4}|\d{2})\b")
_FY = re.compile(r"F\.?\s?Y\.?\s*(\d{4})\s*-\s*(\d{2,4})", re.I)


def _month_hits(text: str) -> list[tuple[int, int]]:
    """Month-year pairs in order. A word counts when its first three letters name a month, so a misspelt
    'Septmber 2025' (S-24) still reads as September, as the SKV scripts did."""
    hits = []
    for mm in _MY.finditer(text):
        k = mm.group(1)[:3].lower()
        if k in MONTHS:
            y = int(mm.group(2))
            hits.append((MONTHS[k], y + 2000 if y < 100 else y))
    return hits


def period_from_name(text: str) -> tuple[dt.date | None, dt.date | None, str]:
    """-> (start, end, fy) where fy is '2025-26' when the name states a financial year."""
    fy = ""
    m = _FY.search(text)
    if m:
        fy = f"{m.group(1)}-{m.group(2)[-2:]}"
    hits = _month_hits(_FY.sub(" ", text))
    if hits:
        a, b = hits[0], hits[-1]
        return dt.date(a[1], a[0], 1), month_end(b[1], b[0]), fy
    if fy:
        y = int(fy.split("-")[0])
        return dt.date(y, 4, 1), month_end(y + 1, 3), fy
    return None, None, fy


def period_label(start: dt.date | None, end: dt.date | None, fy: str = "") -> str:
    if not start or not end:
        return "Not specified"
    lbl = f"{MONTH_LABEL[start.month]} {start.year} - {MONTH_LABEL[end.month]} {end.year}"
    return lbl + (f" (FY {fy})" if fy else "")


def parse_period_label(label: str | None) -> tuple[dt.date | None, dt.date | None]:
    """'Apr 2025 - Mar 2026 (FY 2025-26)' / 'Oct 2025' -> (first day, last day); 'Not specified' -> (None, None)."""
    t = re.sub(r"\(.*?\)", "", label or "")
    hits = _month_hits(t)
    if not hits:
        return None, None
    a, b = hits[0], hits[-1]
    return dt.date(a[1], a[0], 1), month_end(b[1], b[0])


def fin_year(d: dt.date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fy_label(y: int) -> str:
    return f"FY {y}-{str(y + 1)[-2:]}"


def fy_weights(start: dt.date | None, end: dt.date | None) -> dict[int, Decimal]:
    """Month-weighted share of a period per Indian FY; {} when the period is not stated."""
    if not start or not end:
        return {}
    months: dict[int, int] = defaultdict(int)
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months[fin_year(dt.date(y, m, 1))] += 1
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    total = sum(months.values())
    return {k: Decimal(v) / Decimal(total) for k, v in months.items()}


def penny_fix(parts: dict, target: Decimal) -> dict:
    """Round each part to the paisa so the printed parts add up exactly to the printed target (largest remainder)."""
    if not parts:
        return {}
    out = {k: q2(v) for k, v in parts.items()}
    gap = q2(target) - sum(out.values(), Decimal("0"))
    if gap:
        step = CENT if gap > 0 else -CENT
        order = sorted(parts, key=lambda k: ((parts[k] - out[k]) if gap > 0 else (out[k] - parts[k]), str(k)),
                       reverse=True)
        n = int(abs(gap) / CENT)
        for i in range(n):
            k = order[i % len(order)]
            out[k] += step
    return out


# ------------------------------------------------------------------ statement file names
def _category_from_text(low: str) -> str | None:
    if "redistribution" in low:
        return "Redistribution"
    if "mechanical" in low or "muserk" in low or "musrek" in low:
        return "Mechanical (MUSERK)" if ("muserk" in low or "musrek" in low) else "Mechanical"
    if "apple music" in low:
        return "Apple Music"
    if "spotify" in low:
        return "Spotify"
    if "youtube" in low and "pre" in low:
        return "YouTube Pre-Claims"
    if "youtube" in low and "post" in low:
        return "YouTube Post-Claims"
    if "facebook" in low or re.search(r"\bmeta\b", low):
        return "Facebook / Meta"
    if re.search(r"\bradio\b", low):
        return "Radio"
    if "zee television" in low or "zee tv" in low:
        return "Zee TV Broadcast"
    if "overseas" in low:
        return "Overseas"
    return None


def statement_meta_from_name(filename: str) -> dict:
    """-> dict(field -> value) for the fields the name states. Missing fields are simply absent."""
    st = stem(filename)
    low = st.lower()
    out: dict = {}
    m = re.match(r"^\s*\((S-\d+)\)", filename)
    if m:
        out["label"] = m.group(1)
    sub = re.findall(r"\b([PM]\d{4}[A-Z]\d{3})\b", st)
    runs = re.findall(r"\b([PM]\d{4})\b", st)
    if "redistribution" in low and re.search(r"[PM]\d{4}\s+to\s+[PM]\d{4}", st, re.I) and len(runs) > 1:
        out["dist_no"] = f"{runs[0]} to {runs[1]}"
    elif sub:
        out["dist_no"] = sub[0]
    elif re.search(r"[PM]\d{4}\s+to\s+[PM]\d{4}", st, re.I) and len(runs) > 1 and not sub:
        out["dist_no"] = f"{runs[0]} to {runs[1]}"
    elif runs:
        out["dist_no"] = runs[0]
    ms = re.search(r"(\d{3})\s+([A-Z][A-Z0-9]{1,11})\s*$", st.strip())
    if ms:
        code, name = ms.group(1), ms.group(2)
        soc, country = OVERSEAS_SOCIETIES.get(code, (name, ""))
        out["overseas_society"] = soc
        if country:
            out["overseas_country"] = country
    cat = _category_from_text(low)
    looks_like_statement = bool(re.search(r"royalty\s+(re)?distribution", low)) or bool(runs) or "iprs" in low
    if cat:
        out["category"] = cat
    elif looks_like_statement:
        out["category"] = "Other / Unclassified"
    a, b, fy = period_from_name(st)
    if a:
        out["period_start"], out["period_end"] = a, b
        if fy:
            out["fy"] = fy
    return out


def category_from_footer(pool_sources: list[str], overseas_layout: bool) -> str | None:
    """Content fallback when the file name gives no category (e.g. a statement renamed to 'statement.xlsx')."""
    if overseas_layout:
        return "Overseas"
    text = " ".join(pool_sources).lower()
    for key, cat in (("spotify", "Spotify"), ("apple", "Apple Music"), ("muserk", "Mechanical (MUSERK)"),
                     ("facebook", "Facebook / Meta"), ("whatsapp", "Facebook / Meta"), ("zee", "Zee TV Broadcast")):
        if key in text:
            return cat
    return None


def section_of(category: str | None, overseas_society: str | None, overseas_country: str | None) -> str | None:
    if not category:
        return None
    if category == "Overseas":
        if not overseas_society:
            return None
        return f"Overseas - {overseas_society}" + (f" ({overseas_country})" if overseas_country else "")
    return category


# ------------------------------------------------------------------ platform report file names
PLATFORM_WORDS = {"spotify": "Spotify", "apple": "Apple Music", "youtube": "YouTube", "amazon": "Amazon Music",
                  "jiosaavn": "JioSaavn", "saavn": "JioSaavn", "gaana": "Gaana", "wynk": "Wynk", "meta": "Meta",
                  "facebook": "Facebook", "instagram": "Instagram", "deezer": "Deezer", "tidal": "Tidal"}


def platform_from_text(text: str) -> str | None:
    low = (text or "").lower()
    for k, v in PLATFORM_WORDS.items():
        if re.search(rf"\b{k}", low):
            return v
    return None


def distributor_from_name(filename: str, known: list[str]) -> str | None:
    tokens = re.split(r"[^A-Za-z0-9]+", stem(filename))
    for k in known:
        if any(t.lower() == k.lower() for t in tokens):
            return k
    return None


def month_end_of(d: dt.date) -> dt.date:
    return month_end(d.year, d.month)
