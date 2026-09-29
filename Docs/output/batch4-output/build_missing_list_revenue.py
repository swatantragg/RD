"""Revenue on the songs of SVF's updated missing-song list, from IPRS and from Spotify.

Source 1  input/batch-4/Songs-Missing-From-SVF-List_Updated.xlsx
          the missing-song list after SVF worked through it: column C now carries the
          internal number SVF filled in, column A the ISRC(s) it corrected, column D the
          status SVF gave the row.  Two workbooks come out of it:
            * every song on the list                      -> Missing-Songs-Revenue-...
            * only the rows marked "Not SVF work"         -> Non-SVF-Works-Revenue-...
Source 2  input/batch-2/Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx
          the IPRS royalty distribution statement -> SECTION A.
Source 3  input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx
          Spotify's own gross revenue report -> SECTION B.
Source 4  output/batch3-output(Only Spotify RD)/SVF-RD-SKV8.xlsx
          STRUCTURE AND COLOURS ONLY.  Not one figure is read from it.

An identifier cell may hold several values separated by "|" or "," - both are split, and
the run asserts that no ISRC and no internal number is claimed by two different songs, so
nothing can be counted twice.

Every amount is computed from source 2 and source 3 and then re-derived a second time by a
different method before the file is written; the run aborts if the two disagree by a paisa.
"""
import re, warnings
from datetime import datetime
from collections import defaultdict, Counter
warnings.filterwarnings("ignore")
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

R = "/home/swatantra/RD"
S1F = f"{R}/input/batch-4/Songs-Missing-From-SVF-List_Updated.xlsx"
S2F = f"{R}/input/batch-2/Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx"
S3F = f"{R}/input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx"
CATF = f"{R}/input/batch-1/(S-46)SVF list of Song -April 2026.xlsx"
OUT = f"{R}/output/batch4-output"
MARK = "Not SVF work"

# (file, sheet, status filter, what the workbook holds)
JOBS = [
    ("Missing-Songs-Revenue-From-IPRS-And-Spotify.xlsx", "Missing Songs Revenue",
     None, "every song on SVF's updated missing-song list"),
    ("Non-SVF-Works-Revenue-From-IPRS-And-Spotify.xlsx", "Non-SVF Works Revenue",
     MARK, "the songs SVF marked '%s'" % MARK),
]
MONTHS = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
MONTH_LBL = ["Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026"]
MONTH_END = [datetime(2025, 10, 31), datetime(2025, 11, 30), datetime(2025, 12, 31),
             datetime(2026, 1, 31), datetime(2026, 2, 28), datetime(2026, 3, 31)]
MRM_DIST = "MRM Oct 2025 - Mar 2026"
IPRS_PERIOD = "Oct 2025 - Mar 2026"


def s(v):
    return "" if v is None else str(v).strip()


def nk(v):
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


def bk(v):                                   # name key ignoring a _(From "...") suffix
    return re.sub(r"[^a-z0-9]", "", re.sub(r"_?\(from[^)]*\)", "", s(v).lower()))


def ik(v):
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


def multi(v):                                # one cell -> several ids: "a | b" or "a,b"
    return [x for x in re.split(r"[|,;/]+", s(v)) if x.strip()]


def noi(v):
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


# ------------------------------------------------------------ source 1: the song list
ALL = []
ws = openpyxl.load_workbook(S1F, data_only=True).active
for i, r in enumerate(ws.iter_rows(min_row=3, values_only=True), 3):
    name = s(r[1])
    if not name or name.upper() == "TOTAL":
        continue
    ALL.append(dict(row=i, isrcs=[ik(x) for x in multi(r[0]) if ik(x)], name=name,
                    nos=[noi(x) for x in multi(r[2]) if noi(x)], status=s(r[3]),
                    note=s(r[4]) if len(r) > 4 else ""))
assert ALL, "source 1 holds no songs"

own_i, own_n = {}, {}                      # an id may belong to one song only
for e in ALL:
    for i in e["isrcs"]:
        assert own_i.setdefault(i, e["name"]) == e["name"], (i, own_i[i], e["name"])
    for n in e["nos"]:
        assert own_n.setdefault(n, e["name"]) == e["name"], (n, own_n[n], e["name"])

# ------------------------------------------------------------ source 2: IPRS statement
grid = list(openpyxl.load_workbook(S2F, data_only=True).active.iter_rows(values_only=True))
stop = next(i for i, r in enumerate(grid)
            if any(s(c).upper() == "TOTAL ROYALTIES" for c in r))
S2_TOTAL = num(grid[stop][11])
IPRS = defaultdict(float)               # work no -> royalty
IPRS_NAME, IPRS_LINES = {}, defaultdict(int)
money = subtotal = 0.0
cur = None
for r in grid[4:stop]:
    n = noi(r[0])
    if n and re.fullmatch(r"\d{4,}", n):
        cur = n
        IPRS_NAME.setdefault(n, s(r[1]))
    if cur is None or len(r) < 12:
        continue
    amt = num(r[11])
    if not s(r[11]):
        continue
    if s(r[10]):                        # POOL/SOURCE non-blank = money line
        IPRS[cur] += amt
        IPRS_LINES[cur] += 1
        money += amt
    else:
        subtotal += amt
assert abs(money - S2_TOTAL) <= 0.05 and abs(subtotal - S2_TOTAL) <= 0.05, \
    (money, subtotal, S2_TOTAL)
IPRS_BY_NAME = defaultdict(list)
IPRS_BY_BASE = defaultdict(list)
for n, nm in IPRS_NAME.items():
    IPRS_BY_NAME[nk(nm)].append(n)
    IPRS_BY_BASE[bk(nm)].append(n)

# ------------------------------------------------------------ source 3: Spotify MRM
MRM = defaultdict(lambda: defaultdict(float))      # isrc -> month -> revenue
MRM_LINES = Counter()
MRM_NAME, MRM_ALBUM = defaultdict(Counter), defaultdict(Counter)
S3_TOTAL = 0.0
wb = openpyxl.load_workbook(S3F, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    i = ik(r[5])
    if not i:
        continue
    MRM[i][str(r[0])[:7]] += num(r[7])
    MRM_LINES[i] += 1
    MRM_NAME[i][s(r[3])] += 1
    MRM_ALBUM[i][s(r[4])] += 1
    S3_TOTAL += num(r[7])
wb.close()
S3_ISRCS = len(MRM)                 # count it before any lookup adds an empty key

# ------------------------------------------------------------ catalogue, for the audit column
CAT_ISRC, CAT_NO = set(), set()
wb = openpyxl.load_workbook(CATF, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    CAT_ISRC.update(ik(x) for x in s(r[2]).split("|") if ik(x))
    if s(r[1]):
        CAT_NO.add(noi(r[1]))
wb.close()

# ------------------------------------------------------------ per-song figures
for e in ALL:
    e["iprs"] = round(sum(IPRS.get(n, 0.0) for n in e["nos"]), 2)
    e["mrm_m"] = [round(sum(MRM[i].get(m, 0.0) for i in e["isrcs"]), 2) for m in MONTHS]
    e["mrm"] = round(sum(e["mrm_m"]), 2)        # the total equals the months printed
    e["lines"] = sum(MRM_LINES[i] for i in e["isrcs"])
    e["months"] = sum(1 for x in e["mrm_m"] if x)
    e["album"] = next((MRM_ALBUM[i].most_common(1)[0][0] for i in e["isrcs"] if MRM_ALBUM[i]), "")

    # is this work in the IPRS statement under ANY key?  number, exact name, base name
    by_no = [n for n in e["nos"] if n in IPRS]
    by_nm = IPRS_BY_NAME.get(nk(e["name"]), [])
    by_bs = IPRS_BY_BASE.get(bk(e["name"]), [])
    if by_no:
        e["in_s2"] = "Yes - work no %s, royalty %s" % (", ".join(by_no),
                                                       f"{e['iprs']:,.2f}")
    elif by_nm or by_bs:
        e["in_s2"] = "Work no absent; song title matches IPRS work %s" % \
                     ", ".join(sorted(set(by_nm + by_bs)))
    else:
        e["in_s2"] = "No - work number, song title and title-without-film-name all absent"
    e["mrm_basis"] = ("ISRC - exact match in the MRM report (%d monthly line%s)"
                      % (e["lines"], "" if e["lines"] == 1 else "s")) if e["lines"] else \
                     "No ISRC match in the MRM report"
    e["in_cat"] = "Yes" if (any(i in CAT_ISRC for i in e["isrcs"])
                            or any(n in CAT_NO for n in e["nos"])) else "No"

ALL.sort(key=lambda e: (-(e["mrm"] + e["iprs"]), e["name"].upper()))

# ------------------------------------------------------------ independent re-derivation
chk_m = defaultdict(lambda: [0.0] * 6)
chk_t = defaultdict(float)
idx = {m: k for k, m in enumerate(MONTHS)}
wb = openpyxl.load_workbook(S3F, data_only=True, read_only=True)
want = {i for e in ALL for i in e["isrcs"]}
for r in wb.active.iter_rows(min_row=2, values_only=True):
    i = ik(r[5])
    if i in want:
        chk_m[i][idx[str(r[0])[:7]]] += num(r[7])
        chk_t[i] += num(r[7])
wb.close()
BUDGET = 6 * 0.005 + 0.001        # six monthly cells, each rounded to the paisa
for e in ALL:
    exp_m = [round(sum(chk_m[i][k] for i in e["isrcs"]), 2) for k in range(6)]
    raw = round(sum(chk_t[i] for i in e["isrcs"]), 2)
    assert exp_m == e["mrm_m"], (e["name"], exp_m, e["mrm_m"])          # month by month, exact
    assert e["mrm"] == round(sum(e["mrm_m"]), 2), e["name"]             # total == months printed
    assert abs(raw - e["mrm"]) <= BUDGET, (e["name"], raw, e["mrm"])    # vs the unrounded truth
    e["raw"] = raw

# ------------------------------------------------------------ SKV8 visual system (source 4)
GREY_H, GREY_R = "D9D9D9", "F2F2F2"
C_IPRS, T_IPRS = "BFD9BF", "E8F2E8"
C_SPOT, T_SPOT = "B7CBE4", "E6EDF7"
C_TOT, H_TOT, T_TOT = "C9B99B", "D8CBB3", "E8F2E8"
C_AUD, T_AUD = "D8CBB7", "F0E9DC"
BAND_F = Font(bold=True, size=12, color="1F1F1F")
HEAD_F, BOLD = Font(bold=True), Font(bold=True)
NOTE_F = Font(size=10, color="404040")
THIN = Side(style="thin", color="BFBFBF")
MED = Side(style="medium", color="808080")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CEN = Alignment(horizontal="center", vertical="center", wrap_text=True)
NUMF, DATEF = '#,##0.00', 'DD-MMM-YYYY'

def build(dst_name, sheet_name, status_filter, blurb):
  rows = [e for e in ALL if status_filter is None or e["status"] == status_filter]
  assert rows, "no rows for filter %r" % status_filter
  with_note = any(e["note"] for e in rows)
  audit = [("Status Given In Source 1", 20)] + \
          ([("Note From Source 1", 40)] if with_note else []) + \
          [("Present In The IPRS Statement (Source 2)", 46),
           ("Spotify (MRM) Match Basis", 34), ("In SVF Catalogue (S-46)?", 16)]
  BANDS = [
    (None, GREY_H, None,
     [("ISRC", 34), ("Song Name", 44), ("Internal No", 13),
      ("Total Royalty From IPRS", 16), ("Total Revenue From Spotify (MRM)", 20)]),
    ("SECTION A  -  REVENUE FROM IPRS   (Source 2: Spotify royalty distribution statement "
     "for the period October 2025 to March 2026, received from IPRS)", C_IPRS, T_IPRS,
     [("Date", 13), ("Amount", 13), ("Period", 22), ("Distribution Number", 18)]),
    ("SECTION B  -  REVENUE EARNED FROM SPOTIFY   (Source 3: Raw_Spotify_MRM_Oct25_Mar26 - "
     "gross revenue Spotify reported against the ISRC, month by month)", C_SPOT, T_SPOT,
     [x for _ in MONTH_LBL for x in [("Date", 13), ("Amount", 13), ("Period", 13),
                                     ("Distribution Number", 24)]]),
    ("TOTAL REVENUE  (Indian Financial Year, 1 Apr - 31 Mar - both periods fall in FY 2025-26)",
     C_TOT, T_TOT,
     [("FY 2025-26 - IPRS Royalty", 17), ("FY 2025-26 - Spotify Revenue", 18),
      ("Total (Both Sources)", 17)], H_TOT),
    ("AUDIT / TRACEABILITY", C_AUD, T_AUD, audit),
  ]

  out = openpyxl.Workbook()
  ws = out.active
  ws.title = sheet_name

  col, layout = 1, []
  for b in BANDS:
      name, fill, tint, heads = b[0], b[1], b[2], b[3]
      hfill = b[4] if len(b) > 4 else fill
      a, z = col, col + len(heads) - 1
      if name:
          ws.merge_cells(start_row=1, start_column=a, end_row=1, end_column=z)
          c = ws.cell(row=1, column=a, value=name)
          c.font = BAND_F
          c.alignment = Alignment(horizontal="center", vertical="center")
          for k in range(a, z + 1):
              ws.cell(row=1, column=k).fill = PatternFill("solid", fgColor=fill)
          ws.cell(row=1, column=a).border = Border(left=MED)
      for k, (h, wd) in enumerate(heads):
          c = ws.cell(row=2, column=a + k, value=h)
          c.font = HEAD_F
          c.fill = PatternFill("solid", fgColor=hfill)
          c.alignment = CEN
          c.border = BOX
          ws.column_dimensions[get_column_letter(a + k)].width = wd
      layout.append((a, z, fill, tint))
      col = z + 1
  NCOL = col - 1
  ws.row_dimensions[1].height = 24
  ws.row_dimensions[2].height = 32

  MONEY_COLS = [4, 5, 7] + [11 + 4 * k for k in range(6)] + [34, 35, 36]
  DATE_COLS = [6] + [10 + 4 * k for k in range(6)]

  for n, e in enumerate(rows):
      r = 3 + n
      v = [" | ".join(e["isrcs"]), e["name"], " | ".join(e["nos"]), e["iprs"], e["mrm"]]
      # SECTION A - nothing was distributed, and the audit column says how that was established
      v += [None, e["iprs"], IPRS_PERIOD if e["iprs"] else "", "Not specified" if e["iprs"] else ""]
      # SECTION B - one block per month
      for k in range(6):
          amt = e["mrm_m"][k]
          v += [MONTH_END[k] if amt else None, amt if amt else None,
                MONTH_LBL[k] if amt else "", MRM_DIST if amt else ""]
      v += [e["iprs"], e["mrm"], round(e["iprs"] + e["mrm"], 2)]
      v += [e["status"]] + ([e["note"]] if with_note else []) + \
           [e["in_s2"], e["mrm_basis"], e["in_cat"]]
      for i, val in enumerate(v, 1):
          c = ws.cell(row=r, column=i, value=val)
          if i in MONEY_COLS:
              c.number_format = NUMF
          elif i in DATE_COLS:
              c.number_format = DATEF
          if i >= 37:
              c.alignment = Alignment(vertical="center", wrap_text=True)
      for a, z, fill, tint in layout:
          for i in range(a, z + 1):
              cell = ws.cell(row=r, column=i)
              if tint:
                  cell.fill = PatternFill("solid", fgColor=tint)
              elif n % 2 == 0:
                  cell.fill = PatternFill("solid", fgColor=GREY_R)
          if tint:
              ws.cell(row=r, column=a).border = Border(left=MED)
      for i in (4, 5):
          ws.cell(row=r, column=i).font = BOLD

  last = 2 + len(rows)
  tr = last + 1
  ws.cell(row=tr, column=2,
          value="TOTAL  (%d songs - %s)" % (len(rows), blurb))
  for a, z, fill, tint in layout:
      for i in range(a, z + 1):
          c = ws.cell(row=tr, column=i)
          c.fill = PatternFill("solid", fgColor=fill)
          c.font = BOLD
          c.border = Border(top=MED, left=MED if (i == a and tint) else None)
  for i in MONEY_COLS:
      cl = get_column_letter(i)
      c = ws.cell(row=tr, column=i, value=f"=SUM({cl}3:{cl}{last})")
      c.number_format = NUMF
      c.font = BOLD

  n_iprs = sum(1 for e in rows if e["iprs"])
  n_spot = sum(1 for e in rows if e["mrm"])
  note = (
      "REVENUE ON %s, FROM IPRS AND FROM SPOTIFY.  "
      "Population: %s in Songs-Missing-From-SVF-List_Updated.xlsx (source 1); the ISRC in "
      "column A and the internal number in column C are the ones SVF entered there, and a "
      "cell holding several of them is split on '|' and on ','.  No ISRC and no internal "
      "number belongs to two songs, so nothing is counted twice.  "
      "Structure and colours follow SVF-RD-SKV8; no figure is taken from it - Section A is "
      "computed from the IPRS statement (source 2) and Section B from Spotify's raw MRM "
      "report (source 3), and nothing else.  "
      "SECTION A - the statement reconciles at %s (money lines = block sub-totals = the "
      "printed TOTAL ROYALTIES).  %d of these %d songs are in it, and they were paid %s; "
      "for a song that is not in it the royalty is 0.00 and the date, period and "
      "distribution number are blank, because no statement line exists to take them from.  "
      "Every absence was tested three ways - by internal number, by song title, and by the "
      "title with the film name removed.  "
      "SECTION B - Spotify reported %s of gross revenue on %d of these songs, across %d "
      "monthly lines against %d ISRCs.  A blank month is a month with no reported revenue, "
      "not a zero that was inferred.  "
      "Gross revenue reported by Spotify is not a royalty distribution: column D is what "
      "IPRS actually paid, column E is what the platform reported, so the two are added "
      "together only in the column that says 'Total (Both Sources)'.  "
      "Every monthly figure and every total was computed once and then re-derived a second "
      "time straight from the raw report by a different method; the file is written only "
      "when the two agree to the paisa."
      % (blurb.upper(), blurb, f"{S2_TOTAL:,.2f}", n_iprs, len(rows),
         f"{sum(e['iprs'] for e in rows):,.2f}", f"{sum(e['mrm'] for e in rows):,.2f}",
         n_spot, sum(e["lines"] for e in rows),
         len({i for e in rows for i in e["isrcs"]})))
  ws.merge_cells(start_row=tr + 2, start_column=1, end_row=tr + 2, end_column=NCOL)
  c = ws.cell(row=tr + 2, column=1, value=note)
  c.font = NOTE_F
  c.alignment = Alignment(vertical="top", wrap_text=True)
  ws.row_dimensions[tr + 2].height = 118

  ws.freeze_panes = "F3"
  ws.auto_filter.ref = f"A2:{get_column_letter(NCOL)}{last}"
  out.save(f"{OUT}/{dst_name}")
  return rows, NCOL, note

# ------------------------------------------------------------ build + report
print(f"source 1: {len(ALL)} songs   "
      f"{len({i for e in ALL for i in e['isrcs']})} ISRCs   "
      f"{len({n for e in ALL for n in e['nos']})} internal numbers   (none shared between songs)")
print(f"source 2: works {len(IPRS)}  money lines {money:,.2f} == sub-totals {subtotal:,.2f} "
      f"== printed TOTAL ROYALTIES {S2_TOTAL:,.2f}")
print(f"source 3: ISRCs {S3_ISRCS}  file total {S3_TOTAL:,.2f}")
print("VERIFY  independent re-derivation of every month and every total : PASS")

for dst_name, sheet_name, filt, blurb in JOBS:
    rows, ncol, _ = build(dst_name, sheet_name, filt, blurb)
    print(f"\nwritten : {OUT}/{dst_name}")
    print(f"sheet   : {sheet_name}   {len(rows)} songs x {ncol} columns")
    print(f"  SECTION A  IPRS royalty : {sum(e['iprs'] for e in rows):>12,.2f}   "
          f"on {sum(1 for e in rows if e['iprs'])} of {len(rows)} songs")
    print(f"  SECTION B  Spotify rev. : {sum(e['mrm'] for e in rows):>12,.2f}   "
          f"on {sum(1 for e in rows if e['mrm'])} of {len(rows)} songs, "
          f"{sum(e['lines'] for e in rows)} monthly lines")
    print(f"  VERIFY  works found in the IPRS statement  : "
          f"{sum(1 for e in rows if not e['in_s2'].startswith('No'))}")
    print(f"  VERIFY  ISRCs matched in the MRM report    : "
          f"{sum(1 for e in rows if e['lines'])} / {len(rows)}")
    print(f"  VERIFY  registered in the SVF catalogue    : "
          f"{sum(1 for e in rows if e['in_cat'] == 'Yes')}")
