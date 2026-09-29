"""Songs present in the Spotify sources but absent from the SVF master song list.

Source 1  input/batch-2/Spotify - for the Period October 2025 to March 2026.xlsx
          IPRS royalty distribution statement for Spotify, Oct'25-Mar'26.
          Carries WORK INT NO + TITLE + royalty amount.  No ISRC.
Source 2  input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx
          Raw Spotify MRM gross-revenue report, one row per month per ISRC.
          Carries ISRC + content name + revenue.  No internal number.
Source 3  input/batch-1/(S-46)SVF list of Song -April 2026.xlsx
          SVF master catalogue: Track Name + Internal NO + pipe-separated ISRCs.
Source 4  output/batch3-output(Only Spotify RD)/SVF-RD-SKV7.xlsx
          Used for LAYOUT AND COLOUR ONLY.  No amount is taken from it - every
          figure in the revenue workbook comes from source 1 and source 2.

A source-1 / source-2 record is dropped (= it IS in the catalogue) when
  - its own internal number is in source 3, or
  - its own ISRC is in source 3, or
  - the identifier it lacks, recovered through an exact title match in the other
    Spotify source, is in source 3.
What survives is merged by normalised title into one row per song.

Workbook 1  output/Missing song list/Songs-Missing-From-SVF-List.xlsx          song name + ISRC + internal number
Workbook 2  output/Missing song list/Songs-Missing-From-SVF-List-Revenue.xlsx  same songs, SVF-RD-SKV7 layout,
                                                      IPRS royalty + Spotify MRM gross
"""
import re, warnings
from datetime import datetime
from collections import defaultdict, Counter
warnings.filterwarnings("ignore")
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

R = "/home/swatantra/RD"
S1F = f"{R}/input/batch-2/Spotify - for the Period October 2025 to March 2026.xlsx"
S2F = f"{R}/input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx"
S3F = f"{R}/input/batch-1/(S-46)SVF list of Song -April 2026.xlsx"
DST1 = f"{R}/output/Missing song list/Songs-Missing-From-SVF-List.xlsx"
DST2 = f"{R}/output/Missing song list/Songs-Missing-From-SVF-List-Revenue.xlsx"

MONTHS = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
MONTH_LBL = ["Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026"]
MONTH_END = [datetime(2025, 10, 31), datetime(2025, 11, 30), datetime(2025, 12, 31),
             datetime(2026, 1, 31), datetime(2026, 2, 28), datetime(2026, 3, 31)]
MRM_DIST = "MRM Oct 2025 - Mar 2026"
IPRS_PERIOD = "Oct 2025 - Mar 2026"


def s(v):
    return "" if v is None else str(v).strip()


def nk(v):                                  # title key: case / space / punctuation blind
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


def ik(v):                                  # ISRC key
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


def noi(v):                                 # 16026924.0 -> "16026924"
    t = s(v)
    if not t:
        return ""
    try:
        return str(int(float(t)))
    except ValueError:
        return t


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return 0.0


# ------------------------------------------------------------ S1  IPRS statement
# Money lines only: column K (POOL/SOURCE) is non-blank exactly on the lines that carry
# money; the bare line after them repeats the figure as a block sub-total, and parsing
# must stop before the printed TOTAL ROYALTIES row or that grand total lands on the last
# work.  Money lines, sub-total lines and the printed total all read 113,848.57.
S1, cur = [], None
wb = openpyxl.load_workbook(S1F, data_only=True)
grid = list(wb.active.iter_rows(values_only=True))
wb.close()
stop = next(i for i, r in enumerate(grid)
            if any(s(c).upper() == "TOTAL ROYALTIES" for c in r))
file_total = num(grid[stop][11])                    # column L on a standard statement
for i, r in enumerate(grid[4:stop], 5):
    no = noi(r[0])
    if no and re.fullmatch(r"\d{4,}", no):
        cur = dict(row=i, no=no, name=s(r[1]), lang=s(r[3]), amt=0.0)
        S1.append(cur)
    if cur is not None and len(r) > 11 and s(r[10]):     # K non-blank = money line
        cur["amt"] = round(cur["amt"] + num(r[11]), 6)
booked = round(sum(x["amt"] for x in S1), 2)
assert abs(booked - file_total) <= 0.05, (booked, file_total)

# ------------------------------------------------------------ S2  raw Spotify MRM
mrm_month = defaultdict(lambda: defaultdict(float))   # isrc -> month -> revenue
mrm_name = defaultdict(Counter)
wb = openpyxl.load_workbook(S2F, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    isr = ik(r[5])
    if not isr:
        continue
    mrm_month[isr][str(r[0])[:7]] += num(r[7])
    mrm_name[isr][s(r[3])] += 1
wb.close()
mrm_total = {i: sum(m.values()) for i, m in mrm_month.items()}

# ------------------------------------------------------------ S3  SVF catalogue
S3 = []
wb = openpyxl.load_workbook(S3F, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    name, no = s(r[0]), noi(r[1])
    if not name and not no:
        continue
    S3.append(dict(name=name, no=no, isrcs=[ik(x) for x in s(r[2]).split("|") if ik(x)]))
wb.close()
S3_NO = {x["no"] for x in S3 if x["no"]}
S3_ISRC = {i for x in S3 for i in x["isrcs"]}
S3_NAME = defaultdict(list)
for x in S3:
    S3_NAME[nk(x["name"])].append(x)

# ------------------------------------------------------------ title indexes
S1_BY_NAME = defaultdict(list)
for x in S1:
    S1_BY_NAME[nk(x["name"])].append(x)
S2_BY_NAME = defaultdict(list)
for i in mrm_total:
    S2_BY_NAME[nk(mrm_name[i].most_common(1)[0][0])].append(i)

# ------------------------------------------------------------ what is missing
dropped = Counter()
miss1 = []
for x in S1:
    if x["no"] in S3_NO:
        dropped["S1 internal no in catalogue"] += 1
        continue
    linked = S2_BY_NAME.get(nk(x["name"]), [])
    if any(i in S3_ISRC for i in linked):
        dropped["S1 title-linked ISRC in catalogue"] += 1
        continue
    miss1.append(x)

miss2 = []
for i in mrm_total:
    if i in S3_ISRC:
        dropped["S2 ISRC in catalogue"] += 1
        continue
    cand = S1_BY_NAME.get(nk(mrm_name[i].most_common(1)[0][0]), [])
    if len(cand) == 1 and cand[0]["no"] in S3_NO:
        dropped["S2 title-linked internal no in catalogue"] += 1
        continue
    miss2.append(i)

songs = {}
for x in miss1:
    songs.setdefault(nk(x["name"]), dict(name=x["name"], s1=[], s2=[]))["s1"].append(x)
for i in miss2:
    key = nk(mrm_name[i].most_common(1)[0][0])
    songs.setdefault(key, dict(name=mrm_name[i].most_common(1)[0][0], s1=[], s2=[]))["s2"].append(i)

for e in songs.values():
    e["nos"] = sorted({x["no"] for x in e["s1"] if x["no"]})
    e["isrcs"] = sorted(set(e["s2"]))
    e["iprs"] = round(sum(x["amt"] for x in e["s1"]), 2)
    e["mrm_m"] = [round(sum(mrm_month[i].get(m, 0.0) for i in e["s2"]), 2) for m in MONTHS]
    e["mrm"] = round(sum(e["mrm_m"]), 2)      # total equals the months shown
    if e["s1"] and e["s2"]:
        e["origin"] = "Source 1 (IPRS statement) + Source 2 (Spotify MRM)"
    elif e["s1"]:
        e["origin"] = "Source 1 (IPRS statement)"
    else:
        e["origin"] = "Source 2 (Spotify MRM)"
    e["namehit"] = "Yes - identifiers differ" if nk(e["name"]) in S3_NAME else "No"

rows = sorted(songs.values(), key=lambda e: (-(e["mrm"] + e["iprs"]), e["name"].upper()))

# ============================================================ shared SKV7 styling
GREY_H = "D9D9D9"                    # identity header fill
GREY_R = "F2F2F2"                    # alternating identity row fill
C_IPRS, T_IPRS = "BFD9BF", "E8F2E8"  # Spotify royalty distributed by IPRS
C_MRM, T_MRM = "B7CBE4", "E6EDF7"    # Spotify gross revenue (MRM)
C_TOT, H_TOT, T_TOT = "C9B99B", "D8CBB3", "E8F2E8"
C_AUD, T_AUD = "D8CBB7", "F0E9DC"

BAND_F = Font(bold=True, size=12, color="1F1F1F")
HEAD_F = Font(bold=True)
BOLD = Font(bold=True)
NOTE_F = Font(size=10, color="404040")
THIN = Side(style="thin", color="BFBFBF")
MED = Side(style="medium", color="808080")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CEN = Alignment(horizontal="center", vertical="center", wrap_text=True)
NUMF = '#,##0.00'
DATEF = 'DD-MMM-YYYY'

# ============================================================ WORKBOOK 1  song list
out = openpyxl.Workbook()
ws = out.active
ws.title = "Songs Not In SVF List"
ws.merge_cells("A1:C1")
c = ws["A1"]
c.value = ("SONGS NOT AVAILABLE IN THE SVF SONG LIST  -  (S-46) SVF list of Song, April 2026  |  "
           "sourced from the Spotify IPRS statement Oct'25-Mar'26 and the raw Spotify MRM report Oct'25-Mar'26  |  "
           "every row verified absent from the SVF list on BOTH internal number and ISRC")
c.font = BAND_F
c.fill = PatternFill("solid", fgColor=C_MRM)
c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
ws.row_dimensions[1].height = 40

for i, h in enumerate(["ISRC", "Song Name", "Internal No"], 1):
    c = ws.cell(row=2, column=i, value=h)
    c.font = HEAD_F
    c.fill = PatternFill("solid", fgColor=GREY_H)
    c.alignment = CEN
    c.border = BOX
ws.row_dimensions[2].height = 30

for n, e in enumerate(rows):
    r = 3 + n
    for i, v in enumerate([" | ".join(e["isrcs"]), e["name"], " | ".join(e["nos"])], 1):
        c = ws.cell(row=r, column=i, value=v)
        if n % 2 == 0:
            c.fill = PatternFill("solid", fgColor=GREY_R)
last = 2 + len(rows)
c = ws.cell(row=last + 2, column=2, value="TOTAL")
c.font = BOLD
for i in range(1, 4):
    cc = ws.cell(row=last + 2, column=i)
    cc.fill = PatternFill("solid", fgColor=GREY_H)
    cc.border = Border(top=MED)
    cc.font = BOLD
ws.cell(row=last + 2, column=3, value=f"{len(rows)} songs")
for col, w in zip("ABC", (34, 46, 16)):
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"
ws.auto_filter.ref = f"A2:C{last}"
out.save(DST1)

# ============================================================ WORKBOOK 2  revenue
out2 = openpyxl.Workbook()
w2 = out2.active
w2.title = "Missing Songs Revenue"

# band, header fill, tint, [(header, width)]
BANDS = [
    (None, GREY_H, None,
     [("ISRC", 34), ("Song Name", 42), ("Internal No", 13),
      ("Total Amount", 15), ("Total Spotify Revenue (MRM)", 21)]),
    ("SPOTIFY - ROYALTY DISTRIBUTED BY IPRS  (1 distribution: Oct 2025 - Mar 2026)",
     C_IPRS, T_IPRS,
     [("Date", 13), ("Amount", 12), ("Period", 22), ("Distribution Number", 17)]),
    ("SPOTIFY - GROSS REVENUE REPORTED BY SPOTIFY (MRM report)  (Oct 2025 - Mar 2026, 6 monthly figures)",
     C_MRM, T_MRM,
     [x for m in MONTH_LBL for x in [("Date", 13), ("Amount", 12), ("Period", 13),
                                     ("Distribution Number", 24)]]),
    ("TOTAL REVENUE  (Indian Financial Year, 1 Apr - 31 Mar)", C_TOT, T_TOT,
     [("FY 2025-26", 16), ("Total Revenue", 16)], H_TOT),
    ("AUDIT / TRACEABILITY", C_AUD, T_AUD,
     [("Present In", 46), ("Song Name Exists In SVF List", 24)]),
]

MONEY_COLS = [4, 5, 7] + [11 + 4 * k for k in range(6)] + [34, 35]   # Total Amount, MRM total,
DATE_COLS = [6] + [10 + 4 * k for k in range(6)]                     # IPRS amount, 6 MRM amounts, FY, total

col = 1
layout = []                                  # (start, end, band fill, tint)
for b in BANDS:
    name, fill, tint, heads = b[0], b[1], b[2], b[3]
    hfill = b[4] if len(b) > 4 else fill
    a, z = col, col + len(heads) - 1
    if name:
        w2.merge_cells(start_row=1, start_column=a, end_row=1, end_column=z)
        c = w2.cell(row=1, column=a, value=name)
        c.font = BAND_F
        c.alignment = Alignment(horizontal="center", vertical="center")
        for k in range(a, z + 1):
            w2.cell(row=1, column=k).fill = PatternFill("solid", fgColor=fill)
        w2.cell(row=1, column=a).border = Border(left=MED)
    for k, (h, wd) in enumerate(heads):
        c = w2.cell(row=2, column=a + k, value=h)
        c.font = HEAD_F
        c.fill = PatternFill("solid", fgColor=hfill)
        c.alignment = CEN
        c.border = BOX
        w2.column_dimensions[get_column_letter(a + k)].width = wd
    layout.append((a, z, fill, tint))
    col = z + 1
NCOL = col - 1
w2.row_dimensions[1].height = 22
w2.row_dimensions[2].height = 30

for n, e in enumerate(rows):
    r = 3 + n
    v = [" | ".join(e["isrcs"]), e["name"], " | ".join(e["nos"]), e["iprs"], e["mrm"]]
    v += [None, e["iprs"] if e["s1"] else None, IPRS_PERIOD if e["s1"] else "",
          "Not specified" if e["s1"] else ""]
    for k in range(6):
        amt = e["mrm_m"][k]
        v += [MONTH_END[k] if amt else None, amt if amt else None,
              MONTH_LBL[k] if amt else "", MRM_DIST if amt else ""]
    v += [e["iprs"], e["iprs"]]
    v += [e["origin"], e["namehit"]]
    for i, val in enumerate(v, 1):
        c = w2.cell(row=r, column=i, value=val)
        if i in MONEY_COLS:
            c.number_format = NUMF
        elif i in DATE_COLS:
            c.number_format = DATEF
    for a, z, fill, tint in layout:
        for i in range(a, z + 1):
            c = w2.cell(row=r, column=i)
            if tint:
                c.fill = PatternFill("solid", fgColor=tint)
            elif n % 2 == 0:
                c.fill = PatternFill("solid", fgColor=GREY_R)
        if tint:
            w2.cell(row=r, column=a).border = Border(left=MED)
    for i in (4, 5):
        w2.cell(row=r, column=i).font = BOLD

lastd = 2 + len(rows)
tr = lastd + 1
SUM_COLS = MONEY_COLS
w2.cell(row=tr, column=2, value="TOTAL")
for a, z, fill, tint in layout:
    for i in range(a, z + 1):
        c = w2.cell(row=tr, column=i)
        c.fill = PatternFill("solid", fgColor=fill)
        c.font = BOLD
        c.border = Border(top=MED, left=MED if (i == a and tint) else None)
for i in SUM_COLS:
    cl = get_column_letter(i)
    c = w2.cell(row=tr, column=i, value=f"=SUM({cl}3:{cl}{lastd})")
    c.number_format = NUMF
    c.font = BOLD

note = ("Songs earning on Spotify that are NOT in the SVF song list (S-46) April 2026.  "
        "Layout and colours follow SVF-RD-SKV7; no figure is taken from SVF-RD-SKV7 - every amount here is "
        "recomputed from source 1 and source 2.  "
        "Total Amount = royalty actually distributed to SVF by IPRS for the Spotify statement Oct 2025 - Mar 2026 "
        "(source 1, block total per work).  "
        "Total Spotify Revenue (MRM) = gross revenue Spotify reported for the ISRC, Oct 2025 - Mar 2026 "
        "(source 2, sum of the six monthly figures) - it is gross, not a distribution, so it is deliberately "
        "excluded from Total Amount and from Total Revenue, exactly as in SVF-RD-SKV7.  "
        "The IPRS statement carries no distribution date or number, so those two cells are left blank / "
        "'Not specified'.  Both periods fall inside Indian FY 2025-26, so FY 2025-26 = Total Revenue.  "
        "A blank Internal No means the song reached us only through the MRM report (ISRC only); a blank ISRC "
        "means it reached us only through the IPRS statement (internal number only).  "
        "'Song Name Exists In SVF List = Yes - identifiers differ' flags a title that does appear in S-46 while "
        "its internal number and ISRC do not - typically a cover, a male/female version or a re-recording that "
        "still needs registering.")
w2.merge_cells(start_row=tr + 2, start_column=1, end_row=tr + 2, end_column=NCOL)
c = w2.cell(row=tr + 2, column=1, value=note)
c.font = NOTE_F
c.alignment = Alignment(vertical="top", wrap_text=True)
w2.row_dimensions[tr + 2].height = 96

w2.freeze_panes = "F3"
w2.auto_filter.ref = f"A2:{get_column_letter(NCOL)}{lastd}"
out2.save(DST2)

# ------------------------------------------------------------ verification
bad_no = [e for e in rows if any(n in S3_NO for n in e["nos"])]
bad_is = [e for e in rows if any(i in S3_ISRC for i in e["isrcs"])]
print(f"written : {DST1}")
print(f"written : {DST2}   ({NCOL} columns, {len(rows)} songs)")
print(f"songs   : {len(rows)}   (source 1 only: {sum(1 for e in rows if e['s1'] and not e['s2'])}, "
      f"source 2 only: {sum(1 for e in rows if e['s2'] and not e['s1'])}, "
      f"both: {sum(1 for e in rows if e['s1'] and e['s2'])})")
print(f"revenue : Spotify MRM gross {sum(e['mrm'] for e in rows):,.2f}   IPRS royalty {sum(e['iprs'] for e in rows):,.2f}")
print(f"RECON   : IPRS statement money lines {booked:,.2f} == printed TOTAL ROYALTIES {file_total:,.2f}")
print(f"name also in SVF list (identifiers differ): {sum(1 for e in rows if e['namehit'].startswith('Yes'))}")
for k, v in dropped.most_common():
    print(f"excluded: {k}: {v}")
print(f"VERIFY internal number leak: {len(bad_no)}")
print(f"VERIFY ISRC leak           : {len(bad_is)}")
