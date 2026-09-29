"""Song identity mismatch report.

Compares the three song-identity fields (ISRC, Song Name, Internal/IPRS Work No)
across
  S2  SVF catalogue      (S-46)SVF list of Song -April 2026.xlsx   -> name, no, ISRC list
  S3  Spotify IPRS stmt  Spotify - for the Period Oct 2025-Mar 2026 -> name, no      (no ISRC)
  S4  Spotify raw MRM    Raw_Spotify_MRM_Oct25_Mar26.xlsx          -> name, ISRC     (no no)

Rules (two fields agree -> the third one disagreeing is the issue):
  A  same Song Name + same ISRC  -> different Internal No
  B  same Song Name + same Internal No -> different ISRC
  C  same Internal No + same ISRC -> different Song Name
A field a sheet does not carry is a wildcard: it can never *disagree*, but it does not
block the match either, otherwise S3 (no ISRC) and S4 (no internal no) could never be
compared with anything.  Song names are compared case / space / punctuation insensitive.
The row shown in the identity columns is always the SVF catalogue (source 2) row when the
group contains one; every other value goes to the conflicting-value column.
"""
import re, warnings
from collections import defaultdict
warnings.filterwarnings("ignore")
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

R = "/home/swatantra/RD"
S2F = f"{R}/input/batch-1/(S-46)SVF list of Song -April 2026.xlsx"
S3F = f"{R}/input/batch-2/Spotify - for the Period October 2025 to March 2026.xlsx"
S4F = f"{R}/input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx"
DST = f"{R}/output/Song-ID-Mismatch-Report.xlsx"
DST2 = f"{R}/output/Song-ID-Mismatch-Report-V2-With-Revenue.xlsx"

LBL = {"S2": "SVF Song List (S-46)",
       "S3": "Spotify IPRS Statement (Oct'25-Mar'26)",
       "S4": "Spotify Raw MRM (Oct'25-Mar'26)"}
PRIO = {"S2": 0, "S4": 1, "S3": 2}


def s(v):
    return "" if v is None else str(v).strip()


def nk(v):                                   # name key: case / space / punctuation blind
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


def ik(v):                                   # ISRC key
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


def noi(v):                                  # internal no: 16026924.0 -> "16026924"
    t = s(v)
    if not t:
        return None
    try:
        return str(int(float(t)))
    except ValueError:
        return t


# ---------------------------------------------------------------- read the three sheets
recs = []
wb = openpyxl.load_workbook(S2F, data_only=True, read_only=True)
for i, r in enumerate(wb.active.iter_rows(min_row=2, values_only=True), 2):
    if r[0] is None and r[1] is None:
        continue
    recs.append(dict(src="S2", ord=i, name=s(r[0]), no=noi(r[1]),
                     isrcs=[ik(x) for x in s(r[2]).split("|") if ik(x)]))
wb.close()
n_s2 = len(recs)

wb = openpyxl.load_workbook(S3F, data_only=True)          # dimensions are unreliable here
ws = wb.active
n_s3 = 0
for r in ws.iter_rows(min_row=5, values_only=True):       # rows 1-4 are the letter head
    no = noi(r[0])
    if no:                                                # a work starts a block
        n_s3 += 1
        recs.append(dict(src="S3", ord=n_s3, name=s(r[1]), no=no, isrcs=[]))
wb.close()

wb = openpyxl.load_workbook(S4F, data_only=True, read_only=True)
seen = {}
for r in wb.active.iter_rows(min_row=2, values_only=True):
    if r[5] is None:
        continue
    k = (nk(r[3]), ik(r[5]))
    if k not in seen:
        seen[k] = len(seen)
        recs.append(dict(src="S4", ord=seen[k], name=s(r[3]), no=None, isrcs=[ik(r[5])]))
wb.close()
n_s4 = len(seen)
for x in recs:
    x["nk"] = nk(x["name"])
print(f"SVF catalogue rows        : {n_s2:,}")
print(f"IPRS statement works      : {n_s3:,}")
print(f"Spotify MRM name+ISRC     : {n_s4:,}")

# ---------------------------------------------------------------- indexes for the wildcards
name_only = defaultdict(list)        # name key -> records that carry no ISRC       (S3)
no_only = defaultdict(list)          # internal -> records that carry no ISRC       (S3)
isrc_only = defaultdict(list)        # ISRC     -> records that carry no internal   (S4)
noint_by_name = defaultdict(list)    # name key -> records that carry no internal   (S4)
for x in recs:
    if not x["isrcs"]:
        name_only[x["nk"]].append(x)
        if x["no"]:
            no_only[x["no"]].append(x)
    if not x["no"]:
        noint_by_name[x["nk"]].append(x)
        for i in x["isrcs"]:
            isrc_only[i].append(x)

merged = {}                      # (main record, issue kind) -> one report row
KLBL = {"no": "Different Internal Number", "isrc": "Different ISRC",
        "name": "Different Song Name"}


def has(rec, kind):
    return bool(rec["no"] if kind == "no" else rec["isrcs"] if kind == "isrc" else rec["name"])


def pick(kind, core, grp):
    """Identity row: SVF catalogue first, a record that actually carries the disputed
    field first, and a record that matched on both key fields (core) before a wildcard."""
    cid = {id(y) for y in core}
    cand = sorted(grp, key=lambda y: (0 if has(y, kind) else 1,
                                      0 if y["src"] == "S2" else 1,
                                      0 if id(y) in cid else 1,
                                      PRIO[y["src"]], y["ord"]))
    return cand[0]


def emit(kind, main, values, holders):
    """One row per (identity, kind).  A second group that hits the same identity with the
    same kind of clash merges into that row instead of starting a duplicate one."""
    values = {v for v in values if v}
    if not values:
        return
    e = merged.setdefault((main["src"], main["ord"], kind),
                          dict(main=main, kind=kind, vals={}, sheets=set()))
    for v in values:
        e["vals"].setdefault(nk(v) if kind == "name" else v, v)
    e["sheets"] |= holders


# ---------------------------------------------------------------- A  name + ISRC -> internal no
gA = defaultdict(list)
for x in recs:
    for i in x["isrcs"]:
        gA[(x["nk"], i)].append(x)
for (n, _i), core in gA.items():
    grp = core + name_only.get(n, [])
    if len({y["no"] for y in grp if y["no"]}) < 2:
        continue
    main = pick("no", core, grp)
    other = {y["no"] for y in grp if y["no"] and y["no"] != main["no"]}
    emit("no", main, other, {y["src"] for y in grp if y["no"] in other})

# names that carry no ISRC anywhere (works known only to the statement): the ISRC
# condition of rule A is vacuous, so the name alone decides the match
by_name_all = defaultdict(list)
for x in recs:
    by_name_all[x["nk"]].append(x)
for n, grp in by_name_all.items():
    if any(y["isrcs"] for y in grp):
        continue
    if len({y["no"] for y in grp if y["no"]}) < 2:
        continue
    main = pick("no", grp, grp)
    other = {y["no"] for y in grp if y["no"] and y["no"] != main["no"]}
    emit("no", main, other, {y["src"] for y in grp if y["no"] in other})

# ---------------------------------------------------------------- B  name + internal no -> ISRC
gB = defaultdict(list)
for x in recs:
    if x["no"]:
        gB[(x["nk"], x["no"])].append(x)
for (n, _no), core in gB.items():
    if not any(y["isrcs"] for y in core):
        continue                     # no catalogued ISRC for this work -> nothing to differ from
    grp = core + noint_by_name.get(n, [])
    main = pick("isrc", core, grp)
    ref = set(main["isrcs"])
    extra = {i for y in grp for i in y["isrcs"] if i not in ref}
    emit("isrc", main, extra, {y["src"] for y in grp if set(y["isrcs"]) & extra})

# ---------------------------------------------------------------- C  internal no + ISRC -> name
gC = defaultdict(list)
for x in recs:
    if x["no"]:
        for i in x["isrcs"]:
            gC[(x["no"], i)].append(x)
for (no, i), core in gC.items():
    grp = core + no_only.get(no, []) + isrc_only.get(i, [])
    if len({y["nk"] for y in grp}) < 2:
        continue
    main = pick("name", core, grp)
    other = {}
    for y in grp:
        if y["nk"] != main["nk"]:
            other.setdefault(y["nk"], y["name"])
    emit("name", main, set(other.values()),
         {y["src"] for y in grp if y["nk"] in other})

# internal numbers that carry no ISRC anywhere: rule C's ISRC condition is vacuous
by_no_all = defaultdict(list)
for x in recs:
    if x["no"]:
        by_no_all[x["no"]].append(x)
for no, grp in by_no_all.items():
    if any(y["isrcs"] for y in grp):
        continue
    if len({y["nk"] for y in grp}) < 2:
        continue
    main = pick("name", grp, grp)
    other = {}
    for y in grp:
        if y["nk"] != main["nk"]:
            other.setdefault(y["nk"], y["name"])
    emit("name", main, set(other.values()),
         {y["src"] for y in grp if y["nk"] in other})

ORDER = {"Different ISRC": 0, "Different Internal Number": 1, "Different Song Name": 2}
out = []
for e in merged.values():
    m = e["main"]
    out.append(dict(isrc=" | ".join(m["isrcs"]) or "-", name=m["name"] or "-",
                    no=m["no"] or "-", issue=KLBL[e["kind"]],
                    val=" | ".join(sorted(e["vals"].values())),
                    sheets=" | ".join(LBL[t] for t in ("S2", "S3", "S4") if t in e["sheets"]),
                    isrc_list=m["isrcs"], no_key=m["no"]))
out.sort(key=lambda d: (ORDER[d["issue"]], nk(d["name"]), d["no"]))
print(f"\nmismatch rows             : {len(out):,}")
for k in ORDER:
    print(f"   {k:<26}: {sum(1 for d in out if d['issue'] == k):,}")

# ---------------------------------------------------------------- revenue per source file
def numf(v):
    try:
        f = float(v)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


iprs = defaultdict(float)                    # IPRS work no -> royalty paid by the statement
wb = openpyxl.load_workbook(S3F, data_only=True)
cur = None
for r in wb.active.iter_rows(min_row=5, values_only=True):
    no = noi(r[0])
    if no:
        cur = no
    if cur and (s(r[9]) or s(r[10])):        # a POOL / SOURCE line is a payment line;
        iprs[cur] += numf(r[11])             # the bare line after it is only the sub-total
wb.close()
IPRS_TOT = round(sum(iprs.values()), 2)

mrm = defaultdict(float)                     # ISRC -> gross revenue reported by Spotify
wb = openpyxl.load_workbook(S4F, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    if r[5] is None:
        continue
    mrm[ik(r[5])] += numf(r[7])
wb.close()
MRM_TOT = round(sum(mrm.values()), 2)
print(f"\nIPRS statement total      : {IPRS_TOT:,.2f}")
print(f"Spotify MRM report total  : {MRM_TOT:,.2f}")

# book each work / each ISRC to the first row that carries it, so the columns still add up
seen_no, seen_i = set(), set()
for d in out:
    v = 0.0
    if d["no_key"] and d["no_key"] not in seen_no:
        seen_no.add(d["no_key"])
        v = iprs.get(d["no_key"], 0.0)
    d["iprs"] = round(v, 2)
    v = 0.0
    for i in d["isrc_list"]:
        if i not in seen_i:
            seen_i.add(i)
            v += mrm.get(i, 0.0)
    d["mrm"] = round(v, 2)
    d["tot"] = round(d["iprs"] + d["mrm"], 2)
SUM_I = round(sum(d["iprs"] for d in out), 2)
SUM_M = round(sum(d["mrm"] for d in out), 2)
print(f"   of which on these songs: {SUM_I:,.2f} (IPRS)   {SUM_M:,.2f} (MRM)")

# ---------------------------------------------------------------- write
HDR = ["S. No", "ISRC (as per SVF Song List)", "Song Name (as per SVF Song List)",
       "Internal No. (as per SVF Song List)", "Type of Mismatch",
       "Conflicting Value(s) Found", "Sheet(s) Where the Conflict Was Found"]
WID = [7, 34, 34, 17, 24, 46, 42]
RHDR = ["Royalty Paid on This Song", "Gross Revenue on This Song", "Total (Both Files)"]
RWID = [18, 19, 17]
SEC = [f"SPOTIFY - ROYALTY DISTRIBUTED BY IPRS\n{S3F.split('/')[-1]}\n"
       f"Total royalty in this file : {IPRS_TOT:,.2f}",
       f"SPOTIFY - GROSS REVENUE REPORTED BY SPOTIFY (MRM)\n{S4F.split('/')[-1]}\n"
       f"Total revenue in this file : {MRM_TOT:,.2f}",
       "BOTH FILES TOGETHER\nbooked once per IPRS work / per ISRC"]

HFILL = PatternFill("solid", fgColor="DCE9F7")          # light pastel blue - column names
SFILL = PatternFill("solid", fgColor="FCE4D6")          # light pastel peach - file sections
TFILL = PatternFill("solid", fgColor="E2EFDA")          # light pastel green - total row
THIN = Side(style="thin", color="B7C9DC")
BD = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY = "#,##0.00"


def build(path, revenue):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Song ID Mismatches"
    nc = len(HDR) + (len(RHDR) if revenue else 0)
    top = 2 if revenue else 1                            # header row for the column names

    if revenue:                                          # row 1 = the file sections
        t = ws.cell(1, 1, value=f"SONG IDENTITY MISMATCHES BETWEEN THE SVF SONG LIST, THE "
                               f"IPRS SPOTIFY STATEMENT AND SPOTIFY'S OWN REPORT   -   "
                               f"{len(out):,} rows")
        t.font = Font(bold=True, size=11, color="1F3864")
        t.fill = HFILL
        t.alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HDR))
        for j, lab in enumerate(SEC):
            c = ws.cell(1, len(HDR) + 1 + j, value=lab)
            c.font = Font(bold=True, size=9, color="833C0C")
            c.fill = SFILL
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 58
        for c in range(1, nc + 1):
            ws.cell(1, c).border = BD

    for c, h in enumerate(HDR + (RHDR if revenue else []), 1):
        cell = ws.cell(top, c, value=h)
        cell.font = Font(bold=True, size=11, color="1F3864")
        cell.fill = HFILL
        cell.border = BD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = (WID + RWID)[c - 1]
    ws.row_dimensions[top].height = 34

    for i, d in enumerate(out, 1):
        r = top + i
        vals = [i, d["isrc"], d["name"], d["no"], d["issue"], d["val"], d["sheets"]]
        if revenue:
            vals += [d["iprs"], d["mrm"], d["tot"]]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, value=v)
            cell.border = BD
            cell.alignment = Alignment(vertical="top",
                                       horizontal="center" if c in (1, 4) else "left",
                                       wrap_text=c in (2, 6, 7))
            if c > len(HDR):
                cell.number_format = MONEY
                cell.alignment = Alignment(vertical="top", horizontal="right")

    if revenue:                                          # total line
        r = top + len(out) + 1
        c = ws.cell(r, 1, value="TOTAL  (booked once per IPRS work / per ISRC)")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(HDR))
        c.font = Font(bold=True, size=11, color="1F3864")
        c.alignment = Alignment(horizontal="right", vertical="center")
        for j, v in enumerate([SUM_I, SUM_M, round(SUM_I + SUM_M, 2)]):
            cell = ws.cell(r, len(HDR) + 1 + j, value=v)
            cell.font = Font(bold=True)
            cell.number_format = MONEY
            cell.alignment = Alignment(horizontal="right")
        for cc in range(1, nc + 1):
            ws.cell(r, cc).fill = TFILL
            ws.cell(r, cc).border = BD

    ws.freeze_panes = f"A{top + 1}"
    ws.auto_filter.ref = f"A{top}:{get_column_letter(nc)}{top + len(out)}"
    wb.save(path)
    print(f"written -> {path}")


print()
build(DST, False)
build(DST2, True)
