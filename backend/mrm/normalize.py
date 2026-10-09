"""Normalisation primitives shared by every stage.

Money is Decimal end to end. A blank amount is None ("missing data is not zero"); only a written 0 is zero.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                           "nov", "dec"])}
MONTH_LABEL = {v: k.capitalize() for k, v in MONTHS.items()}


def s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, Decimal) and v.is_finite() and v == v.to_integral_value() and abs(v) < Decimal("1e15"):
        v = int(v)
    return str(v).strip()


def amount(v) -> Decimal | None:
    """Exact amount, or None when the cell is blank or not a number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        return v if v.is_finite() else None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return None if v != v or v in (float("inf"), float("-inf")) else Decimal(repr(v))
    t = str(v).strip().replace(",", "").replace("₹", "").replace(" ", "")
    if not t:
        return None
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        d = Decimal(t)
        return d if d.is_finite() else None
    except InvalidOperation:
        return None


def q2(v: Decimal | None) -> Decimal | None:
    if v is None:
        return None
    r = Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)
    return r + ZERO if r != 0 else ZERO


def q8(v: Decimal | None) -> Decimal | None:
    return None if v is None else Decimal(v).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def work_code(v) -> str | None:
    """16026924.0 -> '16026924'; non-numeric text kept verbatim."""
    t = s(v)
    if not t:
        return None
    try:
        d = Decimal(t.replace(",", ""))
        return str(int(d)) if d == d.to_integral_value() else t
    except InvalidOperation:
        return t


def isrc(v) -> str:
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


ISRC_RX = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")


def is_isrc(v: str | None) -> bool:
    return bool(ISRC_RX.match(v or ""))


def split_ids(v) -> list[str]:
    return [x.strip() for x in re.split(r"[|,;/\n]+", s(v)) if x.strip()]


def isrc_list(v) -> list[str]:
    out: list[str] = []
    for x in split_ids(v):
        k = isrc(x)
        if k and k not in out:
            out.append(k)
    return out


def work_list(v) -> list[str]:
    out: list[str] = []
    for x in split_ids(v):
        n = work_code(x)
        if n and n not in out:
            out.append(n)
    return out


# ------------------------------------------------------------------ titles (fuzzy candidates only - never auto-merged)
_PAREN = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_QUOTED = re.compile(r"[\"“”][^\"“”]*[\"“”]")
_VER = re.compile(r"\b(lofi|lo fi|cover|reprise|sped up|slowed|version|male|female|remix|theme|instrumental|"
                  r"unplugged|acoustic|duet|original|mix|edit|radio|sad|vocals|title song|title track|from)\b")
_FOLD = [("chh", "ch"), ("sh", "s"), ("ph", "f"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"),
         ("gh", "g"), ("jh", "j"), ("aa", "a"), ("ee", "i"), ("oo", "u"), ("ou", "o"), ("w", "v"), ("y", "i"),
         ("z", "j"), ("ea", "e"), ("ia", "a"), ("o", "a")]


def title_key(v) -> str:
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


def base_title(v) -> str:
    t = _QUOTED.sub(" ", _PAREN.sub(" ", s(v).lower()))
    k = re.sub(r"[^a-z0-9]", "", _VER.sub(" ", t))
    return k or title_key(v)


def fold(v) -> str:
    """Transliteration fold for Indian-language titles (chh->ch, sh->s, aa->a, o->a, doubled letters -> one)."""
    t = base_title(v)
    for a, b in _FOLD:
        t = t.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", t)


def similarity(a, b) -> float:
    """0..1 - how alike two titles are after folding."""
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    return round(max(difflib.SequenceMatcher(None, fa, fb, autojunk=False).ratio(),
                     difflib.SequenceMatcher(None, title_key(a), title_key(b), autojunk=False).ratio()), 3)


def is_version(title) -> bool:
    return base_title(title) != title_key(title) or bool(_VER.search(s(title).lower()))


# ------------------------------------------------------------------ dates
def month_end(y: int, m: int) -> dt.date:
    return dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)


def month_start(v) -> dt.date | None:
    """datetime / date / 'YYYY-MM...' / 'Oct 2025' / '10/2025' -> first day of that month."""
    if isinstance(v, dt.datetime):
        return dt.date(v.year, v.month, 1)
    if isinstance(v, dt.date):
        return dt.date(v.year, v.month, 1)
    t = s(v)
    m = re.match(r"^(\d{4})-(\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return dt.date(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r"^([A-Za-z]{3,12})\.?[\s'-]+(\d{2,4})$", t)
    if m and m.group(1)[:3].lower() in MONTHS:
        y = int(m.group(2))
        return dt.date(y + 2000 if y < 100 else y, MONTHS[m.group(1)[:3].lower()], 1)
    m = re.match(r"^(\d{1,2})[/-](\d{4})$", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return dt.date(int(m.group(2)), int(m.group(1)), 1)
    return None


PERIOD_RX = re.compile(r"([A-Za-z]{3,12})\.?[\s']+(\d{2,4})\s*(?:-|to|–|_)\s*([A-Za-z]{3,12})\.?[\s']+(\d{2,4})", re.I)


def period_from_text(t: str) -> tuple[dt.date | None, dt.date | None]:
    """'October 2025 to March 2026' / 'Oct25_Mar26' -> (2025-10-01, 2026-03-31)."""
    t = s(t)
    m = PERIOD_RX.search(t)
    if not m:
        m = re.search(r"([A-Za-z]{3})(\d{2})_([A-Za-z]{3})(\d{2})", t)
    if m and m.group(1)[:3].lower() in MONTHS and m.group(3)[:3].lower() in MONTHS:
        y1, y2 = int(m.group(2)), int(m.group(4))
        y1, y2 = (y1 + 2000 if y1 < 100 else y1), (y2 + 2000 if y2 < 100 else y2)
        return dt.date(y1, MONTHS[m.group(1)[:3].lower()], 1), month_end(y2, MONTHS[m.group(3)[:3].lower()])
    return None, None


def as_date(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(s(v)[:10])
    except ValueError:
        return None


def period_label(a: dt.date | None, b: dt.date | None) -> str:
    if not a or not b:
        return "period not stated"
    return f"{MONTH_LABEL[a.month]} {a.year} - {MONTH_LABEL[b.month]} {b.year}"


def months_between(a: dt.date, b: dt.date) -> list[dt.date]:
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(dt.date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
