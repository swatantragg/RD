"""Shape detection (architecture §5.7) and TYPE F auto-mapping (§5.6).

The shape is detected from header TEXT - never from a folder name, a sheet name or a
column position.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from .normalize import MONTHS, ik, norm, s, split_ids

STATEMENT_STANDARD = "STATEMENT_STANDARD"      # TYPE A
STATEMENT_OVERSEAS = "STATEMENT_OVERSEAS"      # TYPE B
CATALOGUE = "CATALOGUE"                        # TYPE C
PLATFORM_REVENUE = "PLATFORM_REVENUE"          # TYPE D - Spotify MRM
PLATFORM_USAGE = "PLATFORM_USAGE"              # TYPE E - Spotify usage
USER_SHEET = "USER_SHEET"                      # TYPE F - any song sheet
UNKNOWN = "UNKNOWN"

KIND_LABEL = {
    STATEMENT_STANDARD: "TYPE A · IPRS statement (standard)",
    STATEMENT_OVERSEAS: "TYPE B · IPRS statement (overseas society)",
    CATALOGUE: "TYPE C · SVF catalogue",
    PLATFORM_REVENUE: "TYPE D · Spotify MRM revenue",
    PLATFORM_USAGE: "TYPE E · Spotify usage",
    USER_SHEET: "TYPE F · song sheet",
    UNKNOWN: "Unknown - quarantined",
}
STATEMENT_KINDS = (STATEMENT_STANDARD, STATEMENT_OVERSEAS)
SHEET_KINDS = (CATALOGUE, USER_SHEET)
PLATFORM_KINDS = (PLATFORM_REVENUE, PLATFORM_USAGE)
ALL_KINDS = tuple(KIND_LABEL)

FIELDS = ("song_name", "internal_no", "isrc", "amount", "period")
IDENTITY_FIELDS = ("song_name", "internal_no", "isrc")
FIELD_RX = {
    "song_name": re.compile(r"track|song|title|content name|work title", re.I),
    "internal_no": re.compile(r"internal|work int|work no|iprs|work id", re.I),
    "isrc": re.compile(r"isrc|recording code", re.I),
    "amount": re.compile(r"royalty|revenue|amount|earning", re.I),
    "period": re.compile(r"period|month|year|quarter", re.I),
}
ASSIGN_ORDER = ("isrc", "internal_no", "song_name", "amount", "period")
ISRC_RX = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
MAP_THRESHOLD = 0.5
HEADER_WEIGHT, VALUE_WEIGHT = 0.6, 0.4


def statement_header_row(grid, limit: int = 15) -> int | None:
    for i, r in enumerate(grid[:limit]):
        if "WORK INT NO" in [s(x).upper() for x in r]:
            return i
    return None


def detect(grid) -> str:
    if not grid:
        return UNKNOWN
    row1 = [s(x).lower() for x in grid[0]]
    if row1 and row1[0] == "track name":
        return CATALOGUE
    if "revenue" in row1 and "isrc" in row1:
        return PLATFORM_REVENUE
    if "usage" in row1 and "isrc" in row1:
        return PLATFORM_USAGE
    h = statement_header_row(grid)
    if h is not None:
        hdr = [s(x).upper() for x in grid[h]]
        return STATEMENT_OVERSEAS if ("RADIO" in hdr and "TV" in hdr) else STATEMENT_STANDARD
    m = propose_mapping(grid)
    if m and any(f in m["mapping"] for f in IDENTITY_FIELDS):
        return USER_SHEET
    return UNKNOWN


def header_fingerprint(header_cells) -> str:
    return hashlib.sha256("|".join(norm(x) for x in header_cells).encode()).hexdigest()


def _is_int(v) -> bool:
    try:
        f = float(str(v).replace(",", ""))
        return f == f and float(int(f)) == f
    except (TypeError, ValueError, OverflowError):
        return False


def _is_num(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        float(str(v).replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def _is_period(v) -> bool:
    if isinstance(v, (dt.date, dt.datetime)):
        return True
    t = s(v)
    if re.match(r"^\d{4}-\d{1,2}", t):
        return True
    m = re.match(r"^([A-Za-z]{3,12})\.?\s+(\d{4})", t)
    return bool(m and m.group(1)[:3].lower() in MONTHS)


def _value_ratio(field: str, values: list) -> float:
    vals = [v for v in values if s(v)]
    if not vals:
        return 0.0
    if field == "song_name":
        texts = [s(v) for v in vals if not _is_num(v)]
        if len(texts) < 0.8 * len(vals):
            return 0.0
        return 1.0 if sum(1 for t in texts if " " in t) >= 0.4 * len(texts) else 0.0
    if field == "internal_no":
        ok = sum(1 for v in vals if split_ids(v) and _is_int(split_ids(v)[0]))
        return ok / len(vals)
    if field == "isrc":
        ok = 0
        for v in vals:
            parts = [ik(p) for p in split_ids(v)]
            if parts and all(ISRC_RX.match(p) for p in parts):
                ok += 1
        return ok / len(vals)
    if field == "amount":
        return sum(1 for v in vals if _is_num(v)) / len(vals)
    if field == "period":
        return sum(1 for v in vals if _is_period(v)) / len(vals)
    return 0.0


VALUE_THRESHOLD = {"song_name": 1.0, "internal_no": 0.8, "isrc": 0.6, "amount": 0.8, "period": 0.6}


def propose_mapping(grid, scan_rows: int = 15, sample: int = 200) -> dict | None:
    """Score every column's header text, then its values. The header row is the first row
    where >= 2 columns score. A field below the threshold stays unmapped - never guessed."""
    header_row = None
    for i, r in enumerate(grid[:scan_rows]):
        hits = sum(1 for x in r if s(x) and any(rx.search(s(x)) for rx in FIELD_RX.values()))
        if hits >= 2:
            header_row = i
            break
    if header_row is None:
        for i, r in enumerate(grid[:scan_rows]):
            if any(s(x) and any(FIELD_RX[f].search(s(x)) for f in IDENTITY_FIELDS) for x in r):
                header_row = i
                break
    if header_row is None:
        return None
    hdr = grid[header_row]
    body = grid[header_row + 1: header_row + 1 + sample]
    columns = []
    scores: dict[tuple[str, int], float] = {}
    for c, h in enumerate(hdr):
        col_vals = [r[c] if c < len(r) else None for r in body]
        cand = {}
        for f in FIELDS:
            hh = bool(s(h)) and bool(FIELD_RX[f].search(s(h)))
            ratio = _value_ratio(f, col_vals)
            vok = ratio >= VALUE_THRESHOLD[f]
            conf = round(HEADER_WEIGHT * hh + VALUE_WEIGHT * vok, 3)
            if conf > 0:
                cand[f] = dict(confidence=conf, header_hit=hh, value_ratio=round(ratio, 3))
                scores[(f, c)] = conf
        columns.append(dict(index=c, header=s(h), candidates=cand))
    mapping: dict[str, dict] = {}
    used: set[int] = set()
    for f in ASSIGN_ORDER:
        best = sorted(((conf, -c) for (ff, c), conf in scores.items()
                       if ff == f and c not in used), reverse=True)
        if best and best[0][0] >= MAP_THRESHOLD:
            conf, negc = best[0]
            c = -negc
            mapping[f] = dict(col_index=c, header=s(hdr[c]), confidence=conf,
                              value_ratio=columns[c]["candidates"][f]["value_ratio"])
            used.add(c)
    return dict(header_row=header_row, header=[s(x) for x in hdr], columns=columns,
                mapping=mapping, fingerprint=header_fingerprint(hdr),
                identity_ok=any(f in mapping for f in IDENTITY_FIELDS))
