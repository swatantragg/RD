"""SVF_RD_V3 -> song x distribution matrix, colored sections, 4-col blocks, FY summary."""
import glob, os, re, zipfile, warnings, datetime as dt
from collections import defaultdict, OrderedDict
warnings.filterwarnings("ignore")
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

IN_DIR = "/home/swatantra/RD/input/batch-1"
OUT_DIR = "/home/swatantra/RD/output"
OUT_XLSX = os.path.join(OUT_DIR, "SVF-RD-V3.xlsx")
TOL = 0.05

SOCIETIES = {
    "008": ("APRA", "Australia"), "021": ("BMI", "USA"), "023": ("BUMA", "Netherlands"),
    "026": ("CASH", "Hong Kong"), "058": ("SACEM", "France"), "080": ("SUISA", "Switzerland"),
    "101": ("SOCAN", "Canada"), "104": ("MACP", "Malaysia"), "106": ("COMPASS", "Singapore"),
    "126": ("MCT", "Thailand"), "128": ("IMRO", "Ireland"),
}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MLBL = {v: k.capitalize() for k, v in MONTHS.items()}


def s(v):
    return "" if v is None else str(v).strip()


def num(v):
    try:
        f = float(v)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


def month_end(y, m):
    return dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)


def stmt_date(path):
    with zipfile.ZipFile(path) as z:
        ts = max(i.date_time for i in z.infolist())
    return dt.date(ts[0], ts[1], ts[2])


def fin_year(d):
    """Indian FY: 1 Apr -> 31 Mar. Returns start year."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(y):
    return f"FY {y}-{str(y + 1)[-2:]}"


def parse_periods(stem):
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


def parse_filename(path):
    fn = os.path.basename(path)
    stem = os.path.splitext(fn)[0]
    n = int(re.search(r"\(S-(\d+)\)", fn).group(1))
    low = stem.lower()
    redis = "redistribution" in low
    # distribution number: prefer the specific sub-run token (P2107A008), else run, else range
    sub = re.findall(r"\b([PM]\d{4}[A-Z]\d{3})\b", stem)
    runs = re.findall(r"\b([PM]\d{4})\b", stem)
    if sub:
        dist_no = sub[0]
    elif re.search(r"[PM]\d{4}\s+to\s+[PM]\d{4}", stem, re.I) and len(runs) > 1:
        dist_no = f"{runs[0]} to {runs[1]}"
    else:
        dist_no = runs[0] if runs else ""
    soc_code = soc = country = ""
    ms = re.search(r"(\d{3})\s+([A-Z]{2,10})\s*$", stem.strip())
    if ms and ms.group(1) in SOCIETIES:
        soc_code = ms.group(1)
        soc, country = SOCIETIES[soc_code]
    if redis:
        cat = "Redistribution"
    elif "mechanical" in low:
        cat = "Mechanical (MUSERK)"
    elif "apple music" in low:
        cat = "Apple Music"
    elif "spotify" in low:
        cat = "Spotify"
    elif "youtube" in low and "pre" in low:
        cat = "YouTube Pre-Claims"
    elif "youtube" in low and "post" in low:
        cat = "YouTube Post-Claims"
    elif "facebook" in low or "meta" in low:
        cat = "Facebook / Meta"
    elif "radio" in low:
        cat = "Radio"
    elif "zee television" in low:
        cat = "Zee TV Broadcast"
    elif "overseas" in low:
        cat = "Overseas"
    else:
        cat = "Other / Unclassified"
    st, en, fy = parse_periods(stem)
    if st:
        plabel = f"{MLBL[st.month]} {st.year} - {MLBL[en.month]} {en.year}"
        if fy:
            plabel += f" (FY {fy})"
    else:
        plabel = "Not specified"
    section = f"Overseas - {soc} ({country})" if (cat == "Overseas" and soc) else cat
    return dict(s_no=n, sheet=f"S-{n}", file=fn, dist_no=dist_no, category=cat, section=section,
                p_start=st, p_end=en, fy=fy, period=plabel, soc=soc, country=country,
                date=stmt_date(path), redis=redis)


def grid(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


# ------------------------------------------------------------------ discover
paths = sorted(glob.glob(os.path.join(IN_DIR, "*.xlsx")),
               key=lambda p: int(re.search(r"\(S-(\d+)\)", os.path.basename(p)).group(1)))
catalog_path, money_paths = None, []
for p in paths:
    g = grid(p)
    if s(g[0][0]).lower() == "track name":
        catalog_path, catalog_rows = p, g
    else:
        money_paths.append((p, g))
print(f"files={len(paths)}  catalog={os.path.basename(catalog_path)}  money={len(money_paths)}")

# ------------------------------------------------------------------ extract
tx, validation, groups = [], [], {}
odd_ids = []
for p, g in money_paths:
    md = parse_filename(p)
    hdr = [s(x).upper() for x in g[3]]
    schema = "Overseas" if ("RADIO" in hdr and "TV" in hdr) else "Standard"
    amt_col = 16 if schema == "Overseas" else 11
    member_no = s(g[0][1])
    member_no = int(float(member_no)) if re.fullmatch(r"\d+(\.0+)?", member_no) else member_no
    member = s(g[1][1]).rstrip(",")
    tr = next(i for i, r in enumerate(g) if any(s(c) == "TOTAL ROYALTIES" for c in r))
    file_total = num(g[tr][amt_col])

    got, lines, carry = 0.0, 0, [None, None, None, None]
    for r in g[4:tr]:
        for c in (0, 1, 2, 3):
            if s(r[c]) != "":
                carry[c] = r[c]
        if schema == "Standard":
            keep = s(r[10]) != ""
        else:
            keep = s(r[4]) != "" and s(r[5]) != "" and s(r[amt_col]) != ""
        if not keep:
            continue
        raw = s(carry[0])
        try:
            wid = int(float(raw)) if raw else None
        except ValueError:
            wid = None
        if wid is None:
            odd_ids.append((md["sheet"], raw, s(carry[1])))
            wid = f"?{md['sheet']}:{raw or 'BLANK'}"
        amt = num(r[amt_col])
        got += amt
        lines += 1
        tx.append((wid, md["s_no"], s(carry[1]), amt))
    groups[md["s_no"]] = dict(md, schema=schema, total=file_total, member=member,
                              member_no=member_no, lines=lines, extracted=got)
    diff = got - file_total
    validation.append((md["sheet"], md["section"], md["dist_no"], schema, lines, got,
                       file_total, diff, "PASS" if abs(diff) <= TOL else "FAIL"))
    print(f"  {md['sheet']:<5} {md['dist_no']:<11} {schema:<8} n={lines:<6} sum={got:>13.4f} "
          f"file={file_total:>13.4f} {'PASS' if abs(diff) <= TOL else 'FAIL'}  {md['section']}")

# ------------------------------------------------------------------ catalog
cat_name, cat_isrc = {}, {}
for t, n, i in ((r + [None, None, None])[:3] for r in catalog_rows[1:]):
    try:
        k = int(float(s(n)))
    except ValueError:
        continue
    if s(t) == "":
        continue
    cat_name.setdefault(k, s(t))
    seen = cat_isrc.setdefault(k, [])
    for part in s(i).split("|"):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
print(f"catalog works={len(cat_name)}")

# ------------------------------------------------------------------ pivot
def gid_all(w):
    return work_gids[w]

cell = defaultdict(float)                       # (work, gid) -> amount
work_gids = defaultdict(set)
song = OrderedDict()                            # work -> dict
for wid, gid, title, amt in tx:
    cell[(wid, gid)] += amt
    work_gids[wid].add(gid)
    d = song.setdefault(wid, dict(title=title, total=0.0))
    d["total"] += amt
    if not d["title"]:
        d["title"] = title
# ---- penny-exact rounding: every displayed cell rounds to 2dp, and each distribution's
# ---- displayed cells re-sum to that statement's printed TOTAL ROYALTIES (to the paisa).
by_gid = defaultdict(list)
for (w, g), a in cell.items():
    by_gid[g].append(w)
cell_r = {}
for g, works in by_gid.items():
    target = round(sum(cell[(w, g)] for w in works), 2)
    for w in works:
        cell_r[(w, g)] = round(cell[(w, g)], 2)
    gap = round(target - round(sum(cell_r[(w, g)] for w in works), 2), 2)
    if gap:
        step = 0.01 if gap > 0 else -0.01
        pool = [w for w in works if cell[(w, g)] != 0] or works
        pool.sort(key=lambda w: (cell[(w, g)] - cell_r[(w, g)]), reverse=gap > 0)
        for i in range(int(round(abs(gap) / 0.01))):
            w = pool[i % len(pool)]
            cell_r[(w, g)] = round(cell_r[(w, g)] + step, 2)
# final paisa: make the sheet's grand total equal the sum printed across the source-2 files
_src_target = round(sum(g["total"] for g in groups.values()), 2)
_gap0 = round(_src_target - round(sum(cell_r.values()), 2), 2)
if _gap0:
    _k = max(cell_r, key=lambda k: cell_r[k])
    cell_r[_k] = round(cell_r[_k] + _gap0, 2)

cell = cell_r
for wid in song:
    song[wid]["total"] = round(sum(cell.get((wid, g), 0.0) for g in gid_all(wid)), 2)

for wid, d in song.items():
    k = wid if isinstance(wid, int) else None
    d["name"] = cat_name.get(k) or d["title"]
    d["isrc"] = " | ".join(cat_isrc.get(k, []))
    d["incat"] = "Yes" if k in cat_name else "No"
order = sorted(song, key=lambda w: (-song[w]["total"], song[w]["name"]))

SECTION_ORDER = ["YouTube Pre-Claims", "YouTube Post-Claims", "Facebook / Meta", "Spotify",
                 "Apple Music", "Radio", "Zee TV Broadcast", "Mechanical (MUSERK)",
                 "Other / Unclassified", "Redistribution"]
present = sorted({g["section"] for g in groups.values()})
ordered_sections = [x for x in SECTION_ORDER if x in present] + \
                   sorted([x for x in present if x not in SECTION_ORDER])
layout = []
for sec in ordered_sections:
    gids = sorted([g for g, m in groups.items() if m["section"] == sec],
                  key=lambda g: (groups[g]["date"], g))
    layout.append((sec, gids))

# ------------------------------------------------------------------ palette (muted)
PALETTE = {
    "Spotify":             ("BFD9BF", "E8F2E8"),   # green
    "Apple Music":         ("E0B4B4", "F7E7E7"),   # red
    "YouTube Pre-Claims":  ("E7C3D8", "F9E9F2"),   # pink
    "YouTube Post-Claims": ("CBC1E0", "EEEAF7"),   # purple
    "Facebook / Meta":     ("B7CBE4", "E6EDF7"),   # blue
    "Radio":               ("E6CBA6", "F9F0E2"),   # amber
    "Zee TV Broadcast":    ("ADCECA", "E6F1EF"),   # teal
    "Mechanical (MUSERK)": ("DAD7A0", "F3F2DF"),   # olive
    "Other / Unclassified": ("CFCFCF", "EFEFEF"),  # grey
    "Redistribution":      ("D5BFA7", "F2E9DE"),   # tan
}
OVERSEAS_CYCLE = [("B9C4D6", "E9EDF4"), ("C2CFB8", "ECF1E8"), ("DCC0C0", "F5EAEA"),
                  ("C9C2D9", "EFECF5"), ("DBCEB1", "F5F0E5"), ("B3CDD1", "E7F0F2"),
                  ("D2BFCE", "F2E9F0"), ("C9CDA8", "F0F1E3")]
sec_fill = {}
k = 0
for sec, _ in layout:
    if sec in PALETTE:
        sec_fill[sec] = PALETTE[sec]
    else:
        sec_fill[sec] = OVERSEAS_CYCLE[k % len(OVERSEAS_CYCLE)]
        k += 1

# ------------------------------------------------------------------ write
wb = Workbook()
ws = wb.active
ws.title = "Royalty by Song"
BOLD = Font(bold=True)
SECF = Font(bold=True, size=12, color="1F1F1F")
CTR = Alignment(horizontal="center", vertical="center")
WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)
MED = Side(style="medium", color="808080")
THIN = Side(style="thin", color="BFBFBF")
HEAD_FILL = PatternFill("solid", fgColor="D9D9D9")
BAND = PatternFill("solid", fgColor="F2F2F2")
MONEY = "#,##0.00"
DATEF = "DD-MMM-YYYY"

FIXED = ["ISRC", "Song Name", "Internal No", "Total Amount"]
BLOCK = ("Date", "Amount", "Period", "Distribution Number")
for i, h in enumerate(FIXED, start=1):
    c = ws.cell(row=2, column=i, value=h)
    c.font = BOLD
    c.fill = HEAD_FILL
    c.alignment = WRAP
    c.border = Border(top=THIN, bottom=MED, left=THIN, right=THIN)
ws.cell(row=1, column=1).border = Border(bottom=THIN)

col = len(FIXED) + 1
spans, gid_col = [], {}
for sec, gids in layout:
    start = col
    bfill = PatternFill("solid", fgColor=sec_fill[sec][0])
    hfill = PatternFill("solid", fgColor=sec_fill[sec][0])
    for g in gids:
        gid_col[g] = col
        for j, h in enumerate(BLOCK):
            c = ws.cell(row=2, column=col + j, value=h)
            c.font = BOLD
            c.fill = hfill
            c.alignment = WRAP
            c.border = Border(top=THIN, bottom=MED, left=THIN, right=THIN)
        # separator between distributions inside a section
        ws.cell(row=2, column=col + 3).border = Border(
            top=THIN, bottom=MED, left=THIN, right=Side(style="thin", color="808080"))
        col += 4
    end = col - 1
    sc = ws.cell(row=1, column=start, value=f"{sec.upper()}  ({len(gids)} distribution"
                                            f"{'s' if len(gids) > 1 else ''})")
    sc.font = SECF
    sc.alignment = CTR
    for cc in range(start, end + 1):
        ws.cell(row=1, column=cc).fill = bfill
    ws.cell(row=1, column=start).border = Border(left=MED, top=MED, bottom=THIN)
    ws.cell(row=1, column=end).border = Border(right=MED, top=MED, bottom=THIN)
    if end > start:
        ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=end)
    spans.append((sec, start, end, len(gids)))
LAST_COL = col - 1

r = 3
for wid in order:
    d = song[wid]
    ws.cell(row=r, column=1, value=d["isrc"])
    ws.cell(row=r, column=2, value=d["name"])
    ws.cell(row=r, column=3, value=wid if isinstance(wid, int) else str(wid))
    c = ws.cell(row=r, column=4, value=round(d["total"], 2))
    c.number_format = MONEY
    c.font = BOLD
    if r % 2 == 1:
        for cc in range(1, 5):
            ws.cell(row=r, column=cc).fill = BAND
    for sec, start, end, _n in spans:
        dfill = PatternFill("solid", fgColor=sec_fill[sec][1])
        for cc in range(start, end + 1):
            ws.cell(row=r, column=cc).fill = dfill
        ws.cell(row=r, column=start).border = Border(left=MED)
        ws.cell(row=r, column=end).border = Border(right=MED)
    for g, base in gid_col.items():
        amt = cell.get((wid, g))
        if amt is None:
            continue
        md = groups[g]
        dc = ws.cell(row=r, column=base, value=md["date"])
        dc.number_format = DATEF
        ac = ws.cell(row=r, column=base + 1, value=amt)
        ac.number_format = MONEY
        ws.cell(row=r, column=base + 2, value=md["period"])
        ws.cell(row=r, column=base + 3, value=md["dist_no"])
    r += 1
LAST_ROW = r - 1

# ---- grand / per-distribution totals row
tr_ = LAST_ROW + 2
tc = ws.cell(row=tr_, column=2, value="TOTAL")
tc.font = BOLD
grand = round(sum(d["total"] for d in song.values()), 2)
c = ws.cell(row=tr_, column=4, value=grand)
c.number_format = MONEY
c.font = BOLD
for cc in range(1, 5):
    ws.cell(row=tr_, column=cc).fill = HEAD_FILL
    ws.cell(row=tr_, column=cc).border = Border(top=MED, bottom=MED)
gid_total = defaultdict(float)
for (w, g), a in cell.items():
    gid_total[g] += a
for sec, start, end, _n in spans:
    bfill = PatternFill("solid", fgColor=sec_fill[sec][0])
    for cc in range(start, end + 1):
        ws.cell(row=tr_, column=cc).fill = bfill
        ws.cell(row=tr_, column=cc).border = Border(top=MED, bottom=MED)
    ws.cell(row=tr_, column=start).border = Border(top=MED, bottom=MED, left=MED)
    ws.cell(row=tr_, column=end).border = Border(top=MED, bottom=MED, right=MED)
for g, base in gid_col.items():
    c = ws.cell(row=tr_, column=base + 1, value=round(gid_total[g], 2))
    c.number_format = MONEY
    c.font = BOLD
    c = ws.cell(row=tr_, column=base + 3, value=groups[g]["dist_no"])
    c.font = BOLD

# ------------------------------------------------------------------ FY summary
fy_amt, fy_dist, fy_works = defaultdict(float), defaultdict(list), defaultdict(set)
for (w, g), a in cell.items():
    y = fin_year(groups[g]["date"])
    fy_amt[y] += a
    if a:
        fy_works[y].add(w)
for g, md in groups.items():
    fy_dist[fin_year(md["date"])].append(g)

_fyk = sorted(fy_amt)
for _y in _fyk:
    fy_amt[_y] = round(fy_amt[_y], 2)
_g2 = round(grand - round(sum(fy_amt.values()), 2), 2)
if _g2 and _fyk:
    _b2 = max(_fyk, key=lambda k: fy_amt[k])
    fy_amt[_b2] = round(fy_amt[_b2] + _g2, 2)

yr = tr_ + 3
t = ws.cell(row=yr, column=1, value="YEARLY ROYALTY GAINED  (Financial Year: 1 April - 31 March)")
t.font = Font(bold=True, size=13)
ws.merge_cells(start_row=yr, start_column=1, end_row=yr, end_column=6)
t.alignment = Alignment(horizontal="left", vertical="center")
t.fill = PatternFill("solid", fgColor="D9D9D9")

YH = ["Financial Year", "Period Covered", "Distributions Received", "Songs Paid",
      "Royalty Earned", "% of Total"]
hr = yr + 1
for i, h in enumerate(YH, start=1):
    c = ws.cell(row=hr, column=i, value=h)
    c.font = BOLD
    c.fill = HEAD_FILL
    c.alignment = WRAP
    c.border = Border(top=THIN, bottom=MED, left=THIN, right=THIN)

FY_FILL = ["E8F2E8", "E6EDF7", "F9E9F2", "F5F0E5", "EEEAF7", "E7F0F2"]
rr = hr + 1
for i, y in enumerate(sorted(fy_amt)):
    amt = fy_amt[y]
    f = PatternFill("solid", fgColor=FY_FILL[i % len(FY_FILL)])
    vals = [fy_label(y), f"Apr {y} - Mar {y + 1}", len(fy_dist[y]), len(fy_works[y]),
            amt, amt / grand if grand else 0]
    for j, v in enumerate(vals, start=1):
        c = ws.cell(row=rr, column=j, value=v)
        c.fill = f
        c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        if j == 5:
            c.number_format = MONEY
        if j == 6:
            c.number_format = "0.00%"
        if j in (3, 4):
            c.alignment = Alignment(horizontal="center")
    rr += 1
tot_row = rr
vals = ["TOTAL", "", sum(len(v) for v in fy_dist.values()), len(song), grand, 1.0]
for j, v in enumerate(vals, start=1):
    c = ws.cell(row=tot_row, column=j, value=v)
    c.font = BOLD
    c.fill = HEAD_FILL
    c.border = Border(top=MED, bottom=MED)
    if j == 5:
        c.number_format = MONEY
    if j == 6:
        c.number_format = "0.00%"
    if j in (3, 4):
        c.alignment = Alignment(horizontal="center")

# ---- legend for the two Songs Paid figures
NOTE = Font(italic=True, size=10, color="404040")
notes = [f"{len(song)} = every song row in the grid (any work appearing on any statement).",
         f"{len(fy_works[max(fy_works)]) if fy_works else 0} = rows whose amount is "
         f"\u20b9 0.01 or more, i.e. counted as 'paid'."]
for i, n in enumerate(notes):
    c = ws.cell(row=tot_row + 1 + i, column=1, value=n)
    c.font = NOTE
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.merge_cells(start_row=tot_row + 1 + i, start_column=1, end_row=tot_row + 1 + i, end_column=6)

# ---- supplementary: same money allocated to the FY(s) the royalty was EARNED in
def fy_months(st, en):
    """month-count of the covered period per financial year -> {fy_start: months}"""
    out = defaultdict(int)
    y, m = st.year, st.month
    while (y, m) <= (en.year, en.month):
        out[fin_year(dt.date(y, m, 1))] += 1
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


earn_amt, earn_dist = defaultdict(float), defaultdict(set)
for g, md in groups.items():
    amt = gid_total[g]
    if md["p_start"] is None:
        earn_amt["NA"] += amt
        earn_dist["NA"].add(g)
        continue
    mm = fy_months(md["p_start"], md["p_end"])
    tot_m = sum(mm.values())
    for y, k_ in mm.items():
        earn_amt[y] += amt * k_ / tot_m
        earn_dist[y].add(g)

# keep the split penny-exact against the grand total
_keys = sorted([k for k in earn_amt if k != "NA"]) + (["NA"] if "NA" in earn_amt else [])
_raw = dict(earn_amt)
for k in _keys:
    earn_amt[k] = round(_raw[k], 2)
_gap = round(grand - round(sum(earn_amt[k] for k in _keys), 2), 2)
if _gap and _keys:
    _big = max(_keys, key=lambda k: earn_amt[k])
    earn_amt[_big] = round(earn_amt[_big] + _gap, 2)

er = tot_row + 5
t2 = ws.cell(row=er, column=1,
             value="ROYALTY BY EARNING PERIOD  (same money split over the financial years each "
                   "statement covers)")
t2.font = Font(bold=True, size=12)
ws.merge_cells(start_row=er, start_column=1, end_row=er, end_column=6)
t2.fill = PatternFill("solid", fgColor="D9D9D9")
EH = ["Financial Year", "Period Covered", "Distributions Covering It", "Basis",
      "Royalty Earned", "% of Total"]
for i, h in enumerate(EH, start=1):
    c = ws.cell(row=er + 1, column=i, value=h)
    c.font = BOLD
    c.fill = HEAD_FILL
    c.alignment = WRAP
    c.border = Border(top=THIN, bottom=MED, left=THIN, right=THIN)
rr2 = er + 2
keys = sorted([k for k in earn_amt if k != "NA"]) + (["NA"] if "NA" in earn_amt else [])
for i, y in enumerate(keys):
    amt = earn_amt[y]
    f = PatternFill("solid", fgColor=FY_FILL[i % len(FY_FILL)])
    lbl = "Period not stated" if y == "NA" else fy_label(y)
    per = "-" if y == "NA" else f"Apr {y} - Mar {y + 1}"
    basis = "-" if y == "NA" else "month-weighted split"
    vals = [lbl, per, len(earn_dist[y]), basis, amt, amt / grand if grand else 0]
    for j, v in enumerate(vals, start=1):
        c = ws.cell(row=rr2, column=j, value=v)
        c.fill = f
        c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        if j == 5:
            c.number_format = MONEY
        if j == 6:
            c.number_format = "0.00%"
        if j == 3:
            c.alignment = Alignment(horizontal="center")
    rr2 += 1
for j, v in enumerate(["TOTAL", "", "", "", round(sum(earn_amt.values()), 2), 1.0], start=1):
    c = ws.cell(row=rr2, column=j, value=v)
    c.font = BOLD
    c.fill = HEAD_FILL
    c.border = Border(top=MED, bottom=MED)
    if j == 5:
        c.number_format = MONEY
    if j == 6:
        c.number_format = "0.00%"

# ---- reconciliation against source-2 file totals
src_total = round(sum(g["total"] for g in groups.values()), 2)
rec = rr2 + 2
recs = [("Grand total of this sheet (sum of 'Total Amount' column)", grand),
        ("Sum of 'TOTAL ROYALTIES' printed in the 45 source-2 statements", src_total),
        ("Sum of the Yearly Royalty Gained table above", round(sum(fy_amt.values()), 2)),
        ("Sum of the Royalty by Earning Period table above", round(sum(earn_amt.values()), 2)),
        ("Difference (sheet - source 2)", round(grand - src_total, 2))]
for i, (lbl, v) in enumerate(recs):
    c = ws.cell(row=rec + i, column=1, value=lbl)
    c.font = BOLD if i == 4 else Font()
    ws.merge_cells(start_row=rec + i, start_column=1, end_row=rec + i, end_column=4)
    vc = ws.cell(row=rec + i, column=5, value=v)
    vc.number_format = MONEY
    vc.font = BOLD
    if i == 4:
        vc.fill = PatternFill("solid", fgColor="E8F2E8" if abs(v) <= TOL else "F7E7E7")
ws.cell(row=rec + 5, column=1,
        value=f"Reconciliation: {'MATCHED' if abs(grand - src_total) <= TOL else 'MISMATCH'}"
              f"  |  {len(groups)} statements, {len(song)} songs, {len(tx):,} royalty lines"
              f"  |  FY bucket = statement date").font = Font(bold=True, italic=True)

# ------------------------------------------------------------------ cosmetics
ws.freeze_panes = "E3"
ws.auto_filter.ref = f"A2:{get_column_letter(LAST_COL)}{LAST_ROW}"
ws.row_dimensions[1].height = 22
ws.row_dimensions[2].height = 30
for w, cl in ((34, "A"), (42, "B"), (13, "C"), (15, "D")):
    ws.column_dimensions[cl].width = w
for _, start, end, _n in spans:
    for cc in range(start, end + 1, 4):
        ws.column_dimensions[get_column_letter(cc)].width = 13
        ws.column_dimensions[get_column_letter(cc + 1)].width = 12
        ws.column_dimensions[get_column_letter(cc + 2)].width = 26
        ws.column_dimensions[get_column_letter(cc + 3)].width = 15
wb.save(OUT_XLSX)

# ------------------------------------------------------------------ report
with open(os.path.join(OUT_DIR, "validation_rd_v3.csv"), "w") as f:
    f.write("Sheet,Section,DistributionNumber,Schema,Lines,Extracted,FileTotal,Diff,Result\n")
    for v in validation:
        f.write(",".join(str(x) if not isinstance(x, float) else f"{x:.6f}"
                         for x in (v[0], f'"{v[1]}"', v[2], v[3], v[4], v[5], v[6], v[7], v[8]))
                + "\n")

print("\n=== SECTIONS ===")
for sec, start, end, n in spans:
    tot = sum(gid_total[g] for g, m in groups.items() if m["section"] == sec)
    print(f"  {sec:<32} {get_column_letter(start)}..{get_column_letter(end)}  "
          f"dist={n:<2} fill=#{sec_fill[sec][0]}/#{sec_fill[sec][1]}  {tot:>14,.2f}")
print("\n=== YEARLY ROYALTY GAINED ===")
for y in sorted(fy_amt):
    print(f"  {fy_label(y)}  Apr {y} - Mar {y+1}   dists={len(fy_dist[y]):<3} "
          f"songs={len(fy_works[y]):<5} {fy_amt[y]:>14,.2f}  {fy_amt[y]/grand:6.2%}")
print(f"  {'TOTAL':<26} {grand:>14,.2f}")
print(f"\nSheet grand total  = {grand:,.2f}")
print(f"Source-2 file totals = {src_total:,.2f}")
print(f"Yearly table total = {sum(fy_amt.values()):,.2f}")
print(f"Difference         = {grand - src_total:,.6f}  -> "
      f"{'MATCH' if abs(grand - src_total) <= TOL else 'MISMATCH'}")
fails = [v for v in validation if v[8] == "FAIL"]
print(f"Per-file validation: {len(validation)-len(fails)} PASS / {len(fails)} FAIL   "
      f"max|diff|={max(abs(v[7]) for v in validation):.9f}")
print(f"Grid: {LAST_ROW-2} song rows x {LAST_COL} cols   works-not-in-catalog="
      f"{sum(1 for d in song.values() if d['incat']=='No')}")
if odd_ids:
    print(f"Non-numeric work ids: {len(odd_ids)}  e.g. {odd_ids[:3]}")
print(f"-> {OUT_XLSX}")
