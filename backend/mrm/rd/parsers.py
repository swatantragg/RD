"""Readers for every file kind. Input: sheets of cached cell values (parsing/reader.py). Output: model objects.

Rules proven on the reference files (Architecture V3 §2.3, checked again on S-1 and S-16):
  * standard layout (12 columns, money in ROYALTY AMT = column L): a line carries money only when SOURCE is filled;
    the bare line after a block repeats the block sub-total and is never counted again;
  * overseas layout (17 columns, usage split RADIO..OTHERS, money in column Q): a line is kept when NAME, ROLE and
    ROYALTY AMT are all filled; 0.0 is a real line ("named, 0.00 paid");
  * reading stops before the row containing TOTAL ROYALTIES (its label sits in column H, not A);
  * work number, title, AV and language appear only on a block's first line and are carried forward;
  * footer tables (SUMMARY OF ROYALTY by language, POOL / SOURCE) are independent totals printed by IPRS;
    their 'NO. OF WORKS' column is not a work count and is never checked;
  * the overseas sub-total row's OTHERS cell is unreliable (S-16 prints 10.2588 for 0.4832); only column Q is used.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from decimal import Decimal

from ..normalize import amount, isrc as ik, s, work_code
from .model import (PLATFORM_REVENUE, PLATFORM_USAGE, REVIEW_LIST, SONG_LIST, Footer, PlatformData, PlatformLine,
                    PriorColumn, PriorOutputData, PriorRow, RoyaltyLine, SongEntry, SongListData, StatementData)
from .names import parse_period_label
from .rules import status_is_recognised

ZERO = Decimal("0")
ISRC_RX = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
USAGE_COLS = ("RADIO", "TV", "CINEMAS", "PERMITS", "DEMAND", "GENERAL", "OTHERS")


def _cell(r: list, j: int | None):
    return r[j] if j is not None and 0 <= j < len(r) else None


def _up(v) -> str:
    return s(v).upper()


# ================================================================== IPRS statements (kinds A and B)
def statement_header(rows: list[list]) -> int | None:
    for i, r in enumerate(rows[:40]):
        if any(_up(c) == "WORK INT NO" for c in r[:4]):
            return i
    return None


def _letterhead(rows: list[list], h: int) -> dict:
    out = dict(holder_member=None, holder_name=None, ipi_name_no=None, ipi_base_no=None)
    for r in rows[:h]:
        if not r:
            continue
        for j, c in enumerate(r):
            u = _up(c)
            nxt = s(_cell(r, j + 1))
            if u == "INTERNAL NO" and nxt:
                out["holder_member"] = work_code(_cell(r, j + 1))
            elif u == "NAME" and nxt:
                out["holder_name"] = re.sub(r"[,\s]+$", "", nxt).strip() or None
            elif u == "IPI NAME NO" and nxt:
                out["ipi_name_no"] = nxt
            elif u == "IPI BASE NO" and nxt:
                out["ipi_base_no"] = nxt
    return out


def _footers(rows: list[list], start: int) -> list[Footer]:
    out: list[Footer] = []
    i = start
    while i < len(rows):
        r = rows[i]
        first = _up(_cell(r, 0))
        if first in ("LANGUAGE", "POOL"):
            hdr = [_up(x) for x in r]
            if "ROYALTY AMT" not in hdr:
                i += 1
                continue
            amt_j = hdr.index("ROYALTY AMT")
            name = "SUMMARY OF ROYALTY" if first == "LANGUAGE" else "POOL"
            items, tot, j = [], ZERO, i + 1
            while j < len(rows) and rows[j] and any(v is not None for v in rows[j]) and s(_cell(rows[j], 0)):
                rr = rows[j]
                a = amount(_cell(rr, amt_j)) or ZERO
                label = " / ".join(s(x) for k, x in enumerate(rr[:amt_j]) if s(x) and not isinstance(x, (int, float, Decimal)))
                items.append(dict(label=label, amount=a))
                tot += a
                j += 1
            grand = None
            k = j
            while k < len(rows) and (not rows[k] or all(v is None for v in rows[k])):
                k += 1
            if k < len(rows) and not s(_cell(rows[k], 0)) and amount(_cell(rows[k], amt_j)) is not None:
                grand = amount(_cell(rows[k], amt_j))
                j = k + 1
            out.append(Footer(name=name, rows=items, rows_total=tot, grand_total=grand))
            i = j
            continue
        i += 1
    return out


def parse_statement(rows: list[list], sheet: str) -> StatementData:
    h = statement_header(rows)
    if h is None:
        raise ValueError("no 'WORK INT NO' header row")
    hdr = [_up(x) for x in rows[h]]
    col = {name: j for j, name in enumerate(hdr) if name}
    overseas = "RADIO" in col and "TV" in col
    c_amt = col.get("ROYALTY AMT", 16 if overseas else 11)
    c_title, c_lang = col.get("TITLE", 1), col.get("LANGUAGE", 3)
    c_name, c_role = col.get("NAME", 4), col.get("ROLE", 5)
    c_own, c_coll = col.get("OWN", 7), col.get("COLL", 8)
    c_pool, c_src = col.get("POOL"), col.get("SOURCE")
    stop = next((i for i in range(h + 1, len(rows)) if any(_up(c) == "TOTAL ROYALTIES" for c in rows[i])), None)
    end = stop if stop is not None else len(rows)
    printed = amount(_cell(rows[stop], c_amt)) if stop is not None else None

    lines: list[RoyaltyLine] = []
    blank_amount_rows: list[int] = []
    subtotal = ZERO
    carry = {"work": None, "title": "", "lang": ""}
    for i in range(h + 1, end):
        r = rows[i]
        if not r or all(v is None for v in r):
            continue
        if s(_cell(r, 0)):
            carry["work"] = _cell(r, 0)
        if s(_cell(r, c_title)):
            carry["title"] = s(_cell(r, c_title))
        if s(_cell(r, c_lang)):
            carry["lang"] = s(_cell(r, c_lang))
        name, role = s(_cell(r, c_name)), s(_cell(r, c_role))
        a_raw = _cell(r, c_amt)
        if overseas:
            is_money = bool(name) and bool(role) and s(a_raw) != ""
            is_sub = not name and not role and s(a_raw) != ""
        else:
            is_money = bool(s(_cell(r, c_src)))
            is_sub = not is_money and not name and s(a_raw) != ""
        if is_sub:
            subtotal += amount(a_raw) or ZERO
            continue
        if not is_money:
            continue
        a = amount(a_raw)
        if a is None:                         # a money line with no amount stays unknown - never zero
            blank_amount_rows.append(i + 1)
            continue
        raw = s(carry["work"])
        wn = work_code(carry["work"]) if raw else None
        if wn is not None and not wn.isdigit():
            wn = None
        usage = None
        if overseas:
            usage = {u: amount(_cell(r, col[u])) for u in USAGE_COLS if u in col}
        lines.append(RoyaltyLine(
            line_no=len(lines) + 1, row_no=i + 1, work_no=wn, raw_work=raw, title=carry["title"], amount=a,
            party=re.sub(r"[,\s]+$", "", name), role=role, language=carry["lang"],
            own_pct=amount(_cell(r, c_own)), coll_pct=amount(_cell(r, c_coll)),
            pool=s(_cell(r, c_pool)), source=s(_cell(r, c_src)), usage=usage))
    footers = _footers(rows, (stop + 1) if stop is not None else len(rows))
    pool_sources = [x["label"] for f in footers if f.name == "POOL" for x in f.rows]
    lh = _letterhead(rows, h)
    return StatementData(layout="IPRS_OVERSEAS" if overseas else "IPRS_STANDARD", sheet=sheet, header_row=h + 1,
                         lines=lines, printed_total=printed, lines_total=sum((x.amount for x in lines), ZERO),
                         subtotal_total=subtotal, footers=footers, blank_amount_rows=blank_amount_rows,
                         pool_sources=pool_sources, **lh)


# ================================================================== tabular files: headers
TITLE_H = ("track name", "song name", "song title", "track title", "title", "content name", "song", "track",
           "work title", "name of the song")
WORK_H = ("internal no", "internal number", "work int no", "work no", "work number", "iprs work no",
          "iprs work number", "work code", "work id", "internal no.")
ISRC_H = ("isrc", "isrc code", "isrcs")
MONTH_H = ("month", "reporting month", "sales month", "period", "usage month", "statement month")
REV_H = ("revenue", "gross revenue", "net revenue", "earnings", "amount", "royalty", "net amount", "gross amount",
         "revenue (inr)", "income", "net payable")
USE_H = ("usage", "plays", "streams", "stream count", "quantity", "units", "views")
ALBUM_H = ("album name", "album", "release title", "release")
UPC_H = ("upc", "upc code", "ean")
PLAT_H = ("client", "platform", "store", "dsp", "service", "retailer")
CUR_H = ("currency", "currency code")
STATUS_H = ("status given in review", "status given in source 1", "status", "remarks", "remark", "comment", "comments", "review status", "svf status", "action")
NOTE_H = ("note", "notes", "link", "url")


def _norm_h(v) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.()]+", " ", s(v).lower())).strip()


def _find(hdr: list[str], names: tuple) -> int | None:
    for n in names:
        if n in hdr:
            return hdr.index(n)
    return None


def _numbered(h: str) -> str:
    """'isrc 1', 'isrc-2', 'isrc (3)', 'iprs song code 1' -> the heading without its number."""
    return re.sub(r"(\s*(no\.?|#)?\s*\(?\d{1,2}\)?)+$", "", h).strip()


_CODEISH = re.compile(r"\b(code|codes|no|no\.|nos|number|numbers|num|id|int)\b")


def _is_isrc_h(h: str) -> bool:
    return bool(re.search(r"\bisrcs?\b", h) or re.match(r"isrcs?\d", h)) and "upc" not in h


def _is_work_h(h: str) -> bool:
    """IPRS work numbers go by many names: 'Internal No', 'Work No', 'IPRS Song Code 1', 'IPRS Work Code',
    'Tune Code' … A serial number ('S.No', 'Sr No') is not one."""
    if _is_isrc_h(h) or any(w in h for w in ("upc", "album", "isrc", "date", "language")):
        return False
    b = _numbered(h)
    if b in WORK_H or b == "iprs":
        return True
    if re.match(r"^(s|sr|sl|serial|row|sno|s no)\b", b):
        return False
    return bool((re.search(r"\b(iprs|work|internal|tune)\b", b) and _CODEISH.search(b))
                or re.search(r"\b(song|track) codes?\b", b))


def _is_album_h(h: str) -> bool:
    return h in ALBUM_H or bool(re.search(r"\b(album|movie|film|web series|serial name|release)\b", h)
                                   and "date" not in h and "code" not in h)


def _title_col(hdr: list[str], skip: set) -> int | None:
    """The song title: an exact heading first, then a heading that speaks of the song or track name."""
    for n in TITLE_H:
        for j, h in enumerate(hdr):
            if j not in skip and h == n:
                return j
    for word in ("song name", "track name", "song title", "track title", "name of the song", "song", "track", "title"):
        for j, h in enumerate(hdr):
            if j in skip or word not in h or _CODEISH.search(h) or _is_isrc_h(h) or _is_album_h(h):
                continue
            return j
    return None


def map_header(row: list) -> dict:
    hdr = [_norm_h(x) for x in row]
    isrc_cols = [j for j, h in enumerate(hdr) if h and _is_isrc_h(h)]
    work_cols = [j for j, h in enumerate(hdr) if h and _is_work_h(h)]
    album = _find(hdr, ALBUM_H)
    if album is None:
        album = next((j for j, h in enumerate(hdr) if h and _is_album_h(h) and j not in isrc_cols + work_cols), None)
    m = dict(title=_title_col(hdr, set(isrc_cols + work_cols) | ({album} if album is not None else set())),
             work=work_cols[0] if work_cols else None, isrc=isrc_cols[0] if isrc_cols else None,
             month=_find(hdr, MONTH_H),
             revenue=_find(hdr, REV_H), usage=_find(hdr, USE_H), album=album, upc=_find(hdr, UPC_H),
             platform=_find(hdr, PLAT_H), currency=_find(hdr, CUR_H), status=_find(hdr, STATUS_H),
             note=_find(hdr, NOTE_H), language=_find(hdr, ("language", "lang", "song language")))
    m["isrc_cols"], m["work_cols"] = isrc_cols, work_cols
    if m["revenue"] is None:
        for j, h in enumerate(hdr):
            if "revenue" in h or "royalt" in h or "earning" in h:
                m["revenue"] = j
                break
    m["headers"] = [s(x) for x in row]
    m["basis_hint"] = None
    if m["revenue"] is not None:
        h = hdr[m["revenue"]]
        m["basis_hint"] = "NET" if "net" in h else ("GROSS" if "gross" in h else None)
    return m


def find_table(rows: list[list], limit: int = 15) -> tuple[int, dict] | None:
    """The first row (within the first rows) that names at least two identity / data columns."""
    best = None
    for i, r in enumerate(rows[:limit]):
        if not r:
            continue
        m = map_header(r)
        ident = sum(1 for k in ("title", "work", "isrc") if m[k] is not None)
        data = sum(1 for k in ("month", "revenue", "usage") if m[k] is not None)
        if ident >= 2 or (m["isrc"] is not None and data >= 1):
            score = ident + data
            if best is None or score > best[0]:
                best = (score, i, m)
            if score >= 3:
                break
    return (best[1], best[2]) if best else None


def table_kind(m: dict) -> str | None:
    if m["isrc"] is not None and m["month"] is not None and m["revenue"] is not None:
        return PLATFORM_REVENUE
    if m["isrc"] is not None and m["month"] is not None and m["usage"] is not None:
        return PLATFORM_USAGE
    if m["title"] is not None and (m["work"] is not None or m["isrc"] is not None):
        return SONG_LIST
    return None


# ================================================================== song lists and review lists (kind C)
def split_codes(v) -> list[str]:
    return [x.strip() for x in re.split(r"[|,;/\n]+", s(v)) if x.strip()]


def isrcs_of(v) -> tuple[list[str], list[str]]:
    good, bad = [], []
    for x in split_codes(v):
        k = ik(x)
        if not k:
            continue
        (good if ISRC_RX.match(k) else bad).append(k)
    return list(dict.fromkeys(good)), bad


def works_of(v) -> tuple[list[str], list[str]]:
    nums, other = [], []
    if isinstance(v, (int, Decimal, float)) and not isinstance(v, bool):
        w = work_code(v)
        return ([w], []) if w and w.isdigit() else ([], [s(v)])
    for x in split_codes(v):
        w = work_code(x)
        if w and w.isdigit():
            nums.append(w)
        elif w:
            other.append(s(x))
    return list(dict.fromkeys(nums)), other


def _status_column(rows: list[list], h: int, m: dict) -> tuple[int | None, int | None]:
    """A review list carries a status column - headed ('Status', 'Remarks' ...) or, as in SVF's reviewed list,
    an unheaded column to the right whose values read as review statuses."""
    if m["status"] is not None:
        return m["status"], m["note"]
    width = max((j + 1 for j, x in enumerate(rows[h]) if s(x)), default=0)
    used = {v for k, v in m.items() if isinstance(v, int)}
    for j in range(width, width + 4):
        if j in used:
            continue
        vals = [s(_cell(r, j)) for r in rows[h + 1:] if r and s(_cell(r, j))]
        if len(vals) >= 3 and sum(1 for v in vals if status_is_recognised(v)) >= 0.6 * len(vals):
            note = j + 1 if any(s(_cell(r, j + 1)) for r in rows[h + 1:] if r) else None
            return j, note
    return None, None


def codes_in(r: list, cols: list[int], read) -> tuple[list[str], list[str]]:
    """The codes of every column of one kind (ISRC 1 … ISRC 16, IPRS Song Code 1 …), in column order, once each."""
    good, bad = [], []
    for j in cols:
        a, b = read(_cell(r, j))
        good += a
        bad += b
    return list(dict.fromkeys(good)), list(dict.fromkeys(bad))


def parse_song_list(rows: list[list], sheet: str, h: int, m: dict) -> SongListData:
    st_col, note_col = _status_column(rows, h, m)
    entries: list[SongEntry] = []
    wcols = m.get("work_cols") or ([m["work"]] if m["work"] is not None else [])
    icols = m.get("isrc_cols") or ([m["isrc"]] if m["isrc"] is not None else [])
    for i in range(h + 1, len(rows)):
        r = rows[i]
        if not r or all(v is None for v in r):
            continue
        title = s(_cell(r, m["title"])) if m["title"] is not None else ""
        works, other = codes_in(r, wcols, works_of)
        isrcs, bad = codes_in(r, icols, isrcs_of)
        if not title and not works and not isrcs:
            continue
        if re.match(r"^total\b", title.lower()) and not works and not isrcs:
            continue                          # a TOTAL line under the list, not a song
        entries.append(SongEntry(entry_no=len(entries) + 1, row_no=i + 1, title=title, work_nos=works, isrcs=isrcs,
                                 other_codes=other + bad,
                                 status_text=s(_cell(r, st_col)) if st_col is not None else "",
                                 note=s(_cell(r, note_col)) if note_col is not None else ""))
    mapping = {k: v for k, v in m.items() if k in ("title", "work", "isrc") and v is not None}
    if st_col is not None:
        mapping["status"] = st_col
    if note_col is not None:
        mapping["note"] = note_col
    return SongListData(kind=REVIEW_LIST if st_col is not None else SONG_LIST, sheet=sheet, header_row=h + 1,
                        mapping=mapping, entries=entries)


# ================================================================== platform reports (kinds D and E)
def _month(v) -> dt.date | None:
    from ..normalize import month_start
    return month_start(v)


def parse_platform(rows: list[list], sheet: str, h: int, m: dict, kind: str) -> PlatformData:
    lines: list[PlatformLine] = []
    plats, curs = Counter(), Counter()
    for i in range(h + 1, len(rows)):
        r = rows[i]
        if not r or all(v is None for v in r):
            continue
        isrc_v = ik(_cell(r, m["isrc"]))
        mon = _month(_cell(r, m["month"]))
        if not isrc_v and mon is None and not s(_cell(r, m["title"])):
            continue
        if m["platform"] is not None and s(_cell(r, m["platform"])):
            plats[s(_cell(r, m["platform"]))] += 1
        if m["currency"] is not None and s(_cell(r, m["currency"])):
            curs[s(_cell(r, m["currency"])).upper()] += 1
        lines.append(PlatformLine(
            line_no=len(lines) + 1, row_no=i + 1, month=mon, isrc=isrc_v,
            title=s(_cell(r, m["title"])) if m["title"] is not None else "",
            album=s(_cell(r, m["album"])) if m["album"] is not None else "",
            upc=s(_cell(r, m["upc"])) if m["upc"] is not None else "",
            amount=amount(_cell(r, m["revenue"])) if kind == PLATFORM_REVENUE else None,
            plays=amount(_cell(r, m["usage"])) if kind == PLATFORM_USAGE else None))
    mapping = {k: v for k, v in m.items() if isinstance(v, int)}
    return PlatformData(kind=kind, sheet=sheet, header_row=h + 1, mapping=mapping, lines=lines,
                        platform_values=[k for k, _ in plats.most_common()],
                        currency_values=[k for k, _ in curs.most_common()], basis_hint=m.get("basis_hint"))


# ================================================================== previous master output (kind F, SKV layout)
SKV_ID = ("isrc", "song name", "internal no", "total amount")
BLOCK = ("date", "amount", "period", "distribution number")


def looks_like_companion(rows: list[list]) -> bool:
    """Our own Missing Songs / out-of-scope report, edited in Excel and uploaded back as a review list."""
    return len(rows) > 2 and tuple(_norm_h(x) for x in rows[1][:4]) == ("isrc", "song name", "internal no",
                                                                        "total royalty from iprs")


def looks_like_skv(rows: list[list]) -> bool:
    if len(rows) < 3:
        return False
    hdr = [_norm_h(x) for x in rows[1][:4]]
    return tuple(hdr) == SKV_ID and any(s(x) for x in rows[0])


def _band_section(label: str) -> tuple[str, str, str | None, str | None]:
    """Row-1 band text -> (band name, kind, platform, distributor)."""
    name = re.sub(r"\s{2,}\(\d+\s+distributions?.*$", "", label).strip()
    name = re.sub(r"\s{2,}\(.*\)$", "", name).strip()
    up = name.upper()
    m = re.match(r"^(.+?)\s*-\s*(GROSS|NET)?\s*REVENUE REPORTED BY\s+(.+?)(?:\s*\((.+?)\s+report\))?$", name, re.I)
    if m or "GROSS REVENUE" in up or "REVENUE REPORTED BY" in up:
        plat = name.split(" - ")[0].strip().title()
        dist = None
        dm = re.search(r"\(([^()]+?)\s+report\)", name, re.I)
        if dm:
            dist = dm.group(1).strip()
        return name, "PLATFORM", plat, dist
    if " - ROYALTY DISTRIBUTED BY" in up:
        name = name.split(" - ROYALTY DISTRIBUTED BY")[0]
    return _section_from_band(name), "ROYALTY", None, None


def _section_from_band(name: str) -> str:
    from .rules import SECTION_ORDER
    up = name.strip().upper()
    for sec in SECTION_ORDER:
        if sec.upper() == up:
            return sec
    m = re.match(r"^OVERSEAS\s*-\s*([A-Z0-9]+)\s*(?:\((.+)\))?$", up)
    if m:
        soc = m.group(1)
        country = (m.group(2) or "").title()
        return f"Overseas - {soc}" + (f" ({country})" if country else "")
    return name.strip().title()


def parse_skv(rows: list[list], sheet: str, generation: str) -> PriorOutputData:
    hdr = [_norm_h(x) for x in rows[1]]
    total_row = next((i for i in range(2, len(rows)) if _up(_cell(rows[i], 1)) == "TOTAL"), None)
    last = total_row if total_row is not None else len(rows)
    # identity + totals block: A..D, then 'Total <platform> Revenue (...)' columns
    plat_tot = {}
    j = 4
    while j < len(hdr) and hdr[j] != "date":
        if hdr[j].startswith("total") and "revenue" in hdr[j]:
            plat_tot[j] = s(rows[1][j])
        j += 1
    # bands
    bands: list[tuple[int, str]] = [(k, s(v)) for k, v in enumerate(rows[0]) if s(v)]

    def band_at(k: int) -> str:
        lab = ""
        for start, text in bands:
            if start <= k:
                lab = text
        return lab

    columns: list[PriorColumn] = []
    k = j
    while k + 3 < len(hdr) and tuple(hdr[k:k + 4]) == BLOCK:
        label = band_at(k)
        band, kind, plat, dist = _band_section(label)
        vals = [r for r in rows[2:last] if r and amount(_cell(r, k + 1)) is not None]
        per = Counter(s(_cell(r, k + 2)) for r in vals if s(_cell(r, k + 2)))
        dno = Counter(s(_cell(r, k + 3)) for r in vals if s(_cell(r, k + 3)))
        dts = Counter(_cell(r, k) for r in vals if isinstance(_cell(r, k), (dt.date, dt.datetime)))
        tot = amount(_cell(rows[total_row], k + 1)) if total_row is not None else None
        period = per.most_common(1)[0][0] if per else "Not specified"
        d = dts.most_common(1)[0][0] if dts else None
        if isinstance(d, dt.datetime):
            d = d.date()
        dist_no = (s(_cell(rows[total_row], k + 3)) if total_row is not None else "") or \
                  (dno.most_common(1)[0][0] if dno else "")
        col = PriorColumn(index=k, band=band, kind=kind, section=band if kind == "PLATFORM" else band,
                          dist_no=dist_no, period_label=period, date=d,
                          total=tot if tot is not None else sum((amount(_cell(r, k + 1)) for r in vals), ZERO),
                          platform=plat, distributor=dist)
        if kind == "PLATFORM":
            a, _ = parse_period_label(period)
            col.month = a
        columns.append(col)
        k += 4
    # audit columns
    def find_h(prefix: str) -> int | None:
        return next((x for x in range(k, len(hdr)) if hdr[x].startswith(prefix)), None)
    c_status, c_booked = find_h("catalogue status"), find_h("royalty booked on")
    c_basis = next((x for x in range(k, len(hdr)) if hdr[x].endswith("match basis")), None)

    out_rows: list[PriorRow] = []
    for i in range(2, last):
        r = rows[i]
        if not r or all(v is None for v in r):
            continue
        if not s(_cell(r, 1)) and not s(_cell(r, 0)) and not s(_cell(r, 2)):
            continue
        isrcs, _bad = isrcs_of(_cell(r, 0))
        works, _other = works_of(_cell(r, 2))
        cells = {}
        for c in columns:
            a = amount(_cell(r, c.index + 1))
            if a is not None:
                cells[c.index] = a
        out_rows.append(PriorRow(
            row_no=i + 1, isrcs=isrcs, title=s(_cell(r, 1)), work_nos=works,
            total=amount(_cell(r, 3)) or ZERO,
            platform_totals={plat_tot[x]: (amount(_cell(r, x)) or ZERO) for x in plat_tot},
            cells=cells, status_text=s(_cell(r, c_status)), booked_on=s(_cell(r, c_booked)),
            basis=s(_cell(r, c_basis))))
    grand = amount(_cell(rows[total_row], 3)) if total_row is not None else None
    pgrand = {plat_tot[x]: amount(_cell(rows[total_row], x)) for x in plat_tot} if total_row is not None else {}
    integrity = _skv_integrity(out_rows, columns, grand, pgrand, plat_tot)
    return PriorOutputData(sheet=sheet, generation=generation, native=False, columns=columns, rows=out_rows,
                           grand_total=grand if grand is not None else sum((x.total for x in out_rows), ZERO),
                           platform_grand={k: v for k, v in pgrand.items() if v is not None}, integrity=integrity)


def _skv_integrity(rows: list[PriorRow], columns: list[PriorColumn], grand, pgrand: dict, plat_tot: dict) -> list[str]:
    """Edited after export?  Row totals = their royalty cells; TOTAL row = the rows (V3 §11.1 step 3)."""
    from .names import q2
    issues = []
    roy = [c.index for c in columns if c.kind == "ROYALTY"]
    for r in rows:
        t = q2(sum((r.cells.get(c, ZERO) for c in roy), ZERO))
        if t != q2(r.total):
            issues.append(f"row {r.row_no} '{r.title}': Total Amount {q2(r.total)} but its distribution amounts add "
                          f"to {t}")
    if grand is not None:
        t = q2(sum((r.total for r in rows), ZERO))
        if t != q2(grand):
            issues.append(f"TOTAL row says {q2(grand)} but the song rows add to {t}")
    for c in columns:
        t = q2(sum((r.cells.get(c.index, ZERO) for r in rows), ZERO))
        if t != q2(c.total):
            issues.append(f"column {c.band} {c.dist_no} {c.period_label}: TOTAL row {q2(c.total)}, rows add to {t}")
    return issues[:50]
