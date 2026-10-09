"""Recording revenue, usage and catalogue tables (A4 recording record, A5 usage evidence, C1 catalogue).

Columns are found by header names (several suppliers, several spellings). A header row needs an identifier
column plus at least one more known column within the first 15 rows.
"""
from __future__ import annotations

from ..normalize import amount, isrc, isrc_list, is_isrc, month_start, s, work_list
from .scope import platform_of, use_type_of

SYNONYMS: dict[str, tuple[str, ...]] = {
    "month": ("month", "period", "reporting month", "sale month", "usage month", "date", "statement month"),
    "platform": ("client", "platform", "store", "dsp", "service", "retailer", "partner"),
    "territory": ("territory", "country", "region", "market"),
    "content_type": ("content type", "product type", "use type", "usage type", "offering"),
    "title": ("content name", "track name", "track title", "song name", "song title", "title", "song", "track"),
    "album": ("album name", "album", "release", "film", "movie", "album / film"),
    "isrc": ("isrc", "isrc code", "isrcs"),
    "upc": ("upc", "ean", "barcode"),
    "amount": ("revenue", "net revenue", "gross revenue", "amount", "earnings", "royalty", "payable", "net payable",
               "revenue (inr)", "amount (inr)"),
    "currency": ("currency", "ccy"),
    "streams": ("usage", "streams", "plays", "quantity", "units", "count", "views", "stream count"),
    "work_code": ("internal no", "internal number", "work no", "work int no", "work code", "iprs work no",
                  "iprs no", "tune code", "work id"),
    "iswc": ("iswc",),
    "composer": ("composer", "music director", "music"),
    "lyricist": ("lyricist", "lyrics", "writer"),
    "performer": ("singer", "artist", "performer", "artists"),
    "status": ("status", "remarks", "note", "notes", "comment"),
}
_LOOKUP = {name: field for field, names in SYNONYMS.items() for name in names}


def map_header(row: list) -> dict[str, int]:
    out: dict[str, int] = {}
    for j, v in enumerate(row):
        key = s(v).lower().replace("_", " ").strip()
        f = _LOOKUP.get(key)
        if f and f not in out:
            out[f] = j
    if "status" not in out:                                   # an unnamed column right after the ids is a note
        for j, v in enumerate(row):
            if v is None and j > max(out.values(), default=-1) and j > 0 and len(out) >= 2:
                out["status"] = j
                break
    return out


def find_header(grid: list[list]) -> tuple[int, dict[str, int]] | None:
    for i, r in enumerate(grid[:15]):
        m = map_header(r)
        if ("isrc" in m or "work_code" in m) and len(m) >= 2:
            return i, m
    return None


def kind_of(mapping: dict[str, int]) -> str:
    if "work_code" in mapping and "isrc" in mapping and "amount" not in mapping:
        return "IDENTITY"
    if "isrc" in mapping and "amount" in mapping:
        return "RECORDING"
    if "isrc" in mapping and "streams" in mapping:
        return "USAGE"
    return "OTHER"


def _get(r: list, m: dict, f: str):
    j = m.get(f)
    return r[j] if j is not None and j < len(r) else None


def recording_rows(sheet: dict, h: int, m: dict) -> list[dict]:
    out = []
    for i, r in enumerate(sheet["rows"][h + 1:], start=h + 2):
        if not r or all(v is None for v in r):
            continue
        code, a, mo = isrc(_get(r, m, "isrc")), amount(_get(r, m, "amount")), month_start(_get(r, m, "month"))
        reason = None
        if not is_isrc(code):
            reason = f"ISRC {s(_get(r, m, 'isrc')) or '(blank)'!r} is not a valid ISRC"
        elif a is None:
            reason = "revenue is blank or not a number (kept unknown, not zero)"
        elif "month" in m and mo is None:
            reason = f"month {s(_get(r, m, 'month'))!r} is not a date"
        ct = s(_get(r, m, "content_type")) or None
        plat = platform_of(_get(r, m, "platform"))
        out.append(dict(row_no=i, sheet=sheet["title"], isrc=code or None, title=s(_get(r, m, "title")) or None,
                        album=s(_get(r, m, "album")) or None, upc=s(_get(r, m, "upc")) or None, content_type=ct,
                        platform=plat, territory=s(_get(r, m, "territory")).upper() or None, month=mo,
                        amount=a, currency=s(_get(r, m, "currency")).upper() or None,
                        streams=_int(_get(r, m, "streams")), use_type=use_type_of(None, plat, ct),
                        is_valid=reason is None, invalid_reason=reason))
    return out


def usage_rows(sheet: dict, h: int, m: dict) -> list[dict]:
    out = []
    for i, r in enumerate(sheet["rows"][h + 1:], start=h + 2):
        if not r or all(v is None for v in r):
            continue
        code, n, mo = isrc(_get(r, m, "isrc")), _int(_get(r, m, "streams")), month_start(_get(r, m, "month"))
        reason = None
        if not is_isrc(code):
            reason = f"ISRC {s(_get(r, m, 'isrc')) or '(blank)'!r} is not a valid ISRC"
        elif n is None:
            reason = "stream count is blank or not a whole number (kept unknown, not zero)"
        elif "month" in m and mo is None:
            reason = f"month {s(_get(r, m, 'month'))!r} is not a date"
        plat = platform_of(_get(r, m, "platform"))
        out.append(dict(row_no=i, sheet=sheet["title"], isrc=code or None, title=s(_get(r, m, "title")) or None,
                        album=s(_get(r, m, "album")) or None, platform=plat,
                        territory=s(_get(r, m, "territory")).upper() or None, month=mo, streams=n,
                        metric="streams", use_type=use_type_of(None, plat, _get(r, m, "content_type")),
                        is_valid=reason is None, invalid_reason=reason))
    return out


def catalogue_rows(sheet: dict, h: int, m: dict) -> list[dict]:
    out = []
    for i, r in enumerate(sheet["rows"][h + 1:], start=h + 2):
        if not r or all(v is None for v in r):
            continue
        works, codes = work_list(_get(r, m, "work_code")), isrc_list(_get(r, m, "isrc"))
        bad = [c for c in codes if not is_isrc(c)]
        reason = None
        if not works:
            reason = "no work code on this row"
        elif not all(w.isdigit() for w in works):
            reason = f"work code {s(_get(r, m, 'work_code'))!r} is not a work number"
        elif bad:
            reason = f"not a valid ISRC: {', '.join(bad)} (an ISRC is never treated as a work code)"
        out.append(dict(row_no=i, title=s(_get(r, m, "title")) or None, work_codes=works,
                        isrcs=[c for c in codes if is_isrc(c)], raw_work=s(_get(r, m, "work_code")) or None,
                        film=s(_get(r, m, "album")) or None, composer=s(_get(r, m, "composer")) or None,
                        lyricist=s(_get(r, m, "lyricist")) or None, performer=s(_get(r, m, "performer")) or None,
                        status=s(_get(r, m, "status")) or None, is_valid=reason is None, invalid_reason=reason))
    return out


def _int(v) -> int | None:
    a = amount(v)
    if a is None or a != a.to_integral_value():
        return None
    return int(a)

