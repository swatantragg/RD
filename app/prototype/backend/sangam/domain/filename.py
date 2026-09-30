"""Statement metadata from the filename (architecture §6).

Statement metadata is not inside the file - it is parsed from the filename plus the
issue date hidden in the .xlsx zip. The category ladder and the society register are seed
rows in the database; the defaults below are only used to seed it.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
import zipfile

from .normalize import MONTHS, MONTH_LABEL, month_end, s

# (code, label, matcher regex on the lower-cased filename, ordinal) - order is significant
DEFAULT_CATEGORIES = [
    ("redistribution", "Redistribution", r"redistribution", 10),
    ("mechanical", "Mechanical (MUSERK)", r"mechanical", 20),
    ("apple_music", "Apple Music", r"apple music", 30),
    ("spotify", "Spotify", r"spotify", 40),
    ("youtube_pre", "YouTube Pre-Claims", r"(?=.*youtube)(?=.*pre)", 50),
    ("youtube_post", "YouTube Post-Claims", r"(?=.*youtube)(?=.*post)", 60),
    ("facebook_meta", "Facebook / Meta", r"facebook|meta", 70),
    ("radio", "Radio", r"radio", 80),
    ("zee_tv", "Zee TV Broadcast", r"zee television", 90),
    ("overseas", "Overseas", r"overseas", 100),
    ("other", "Other / Unclassified", r"", 999),
]

DEFAULT_SOCIETIES = [
    ("008", "APRA", "Australia"), ("021", "BMI", "USA"), ("023", "BUMA", "Netherlands"),
    ("026", "CASH", "Hong Kong"), ("058", "SACEM", "France"), ("080", "SUISA", "Switzerland"),
    ("101", "SOCAN", "Canada"), ("104", "MACP", "Malaysia"), ("106", "COMPASS", "Singapore"),
    ("126", "MCT", "Thailand"), ("128", "IMRO", "Ireland"),
]

SECTION_ORDER = ["YouTube Pre-Claims", "YouTube Post-Claims", "Facebook / Meta",
                 "Spotify", "Spotify MRM", "Apple Music", "Radio", "Zee TV Broadcast",
                 "Mechanical (MUSERK)", "Other / Unclassified", "Redistribution"]


def section_sort_key(section: str):
    if section in SECTION_ORDER:
        return (0, SECTION_ORDER.index(section), "")
    return (1, 0, section)


def zip_date(data: bytes) -> dt.date | None:
    """The statement's real issue date: max date_time over all members of the .xlsx zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            ts = max(i.date_time for i in z.infolist())
        return dt.date(ts[0], ts[1], ts[2])
    except Exception:
        return None


def parse_periods(stem: str):
    fy = ""
    m = re.search(r"F\.?\s?Y\.?\s*(\d{4})\s*-\s*(\d{2,4})", stem, re.I)
    if m:
        fy = f"{m.group(1)}-{m.group(2)[-2:]}"
    hits = []
    for mm in re.finditer(r"([A-Za-z]{3,12})\.?\s+(\d{4})", stem):
        k = mm.group(1)[:3].lower()
        if k in MONTHS:
            hits.append((MONTHS[k], int(mm.group(2))))
    if hits:
        return dt.date(hits[0][1], hits[0][0], 1), month_end(hits[-1][1], hits[-1][0]), fy
    if fy:
        y = int(fy.split("-")[0])
        return dt.date(y, 4, 1), month_end(y + 1, 3), fy
    return None, None, fy


def period_label(st: dt.date | None, en: dt.date | None, fy: str = "") -> str:
    if not st or not en:
        return "Not specified"
    lab = f"{MONTH_LABEL[st.month]} {st.year} - {MONTH_LABEL[en.month]} {en.year}"
    return lab + (f" (FY {fy})" if fy else "")


def classify_category(stem: str, categories=DEFAULT_CATEGORIES):
    low = stem.lower()
    for code, label, rx, _ord in sorted(categories, key=lambda c: c[3]):
        if rx and re.search(rx, low):
            return code, label
    other = [c for c in categories if not c[2]]
    return (other[0][0], other[0][1]) if other else ("other", "Other / Unclassified")


def parse_s_no(filename: str) -> int | None:
    m = re.search(r"\(S-(\d+)\)", filename)
    return int(m.group(1)) if m else None


def parse_filename(filename: str, data: bytes | None = None, categories=DEFAULT_CATEGORIES,
                   societies=DEFAULT_SOCIETIES) -> dict:
    stem = os.path.splitext(os.path.basename(filename))[0]
    low = stem.lower()
    sub = re.findall(r"\b([PM]\d{4}[A-Z]\d{3})\b", stem)
    runs = re.findall(r"\b([PM]\d{4})\b", stem)
    if sub:
        dist_no = sub[0]
    elif re.search(r"[PM]\d{4}\s+to\s+[PM]\d{4}", stem, re.I) and len(runs) > 1:
        dist_no = f"{runs[0]} to {runs[1]}"
    else:
        dist_no = runs[0] if runs else ""
    soc_map = {c: (n, k) for c, n, k in societies}
    soc_code = soc = country = ""
    ms = re.search(r"(\d{3})\s+([A-Z]{2,10})\s*$", stem.strip())
    if ms and ms.group(1) in soc_map:
        soc_code = ms.group(1)
        soc, country = soc_map[soc_code]
    cat_code, cat_label = classify_category(stem, categories)
    st, en, fy = parse_periods(stem)
    section = f"Overseas - {soc} ({country})" if (cat_code == "overseas" and soc) else cat_label
    return dict(
        s_no=parse_s_no(filename), dist_no=dist_no, redistribution="redistribution" in low,
        category_code=cat_code, category=cat_label, section=section,
        society_code=soc_code, society=soc, country=country,
        p_start=st, p_end=en, fy=fy, period=period_label(st, en, fy),
        stmt_date=zip_date(data) if data is not None else None,
    )


def dist_display(dist_no: str) -> str:
    return s(dist_no) or "Not specified"
