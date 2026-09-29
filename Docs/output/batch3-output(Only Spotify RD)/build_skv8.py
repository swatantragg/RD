"""SVF-RD-SKV8 = SVF-RD-SKV7 with the same-song / different-identifier rows folded together.

Source 1  output/batch3-output(Only Spotify RD)/SVF-RD-SKV7.xlsx     the master RD matrix
Source 2  output/Missing song list/Songs-Missing-From-SVF-List.xlsx  songs earning on Spotify
                                                                     that are not in the catalogue
Source 3  input/batch-1/(S-46)SVF list of Song -April 2026.xlsx       the SVF catalogue

What SKV7 did with a source-2 song whose TITLE is in the catalogue but whose ISRC / internal
number is not: it folded the money into the catalogue row by name, but printed only the
catalogue identifiers in columns A and C - and in five cases it left a second, separate row
(a royalty statement had paid the work under another internal number).

SKV8 fixes both halves of that:
  * the unregistered ISRC is appended to column A, pipe separated, next to the catalogue ISRCs
  * separate rows carrying the same song name are merged into one row - amounts added,
    internal numbers pipe separated in column C, blank when no internal number exists,
    dates / periods / distribution numbers taken from the first row that carries one
  * column HO (Catalogue Status) records every change, so any merge can be undone

Nothing else in the 225-column layout changes; the TOTAL row is recomputed and re-checked
against SKV7 - merging rows must not move a single rupee.
"""
import re, shutil, warnings
from collections import defaultdict
warnings.filterwarnings("ignore")
import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

R = "/home/swatantra/RD"
SKV7 = f"{R}/output/batch3-output(Only Spotify RD)/SVF-RD-SKV7.xlsx"
MISS = f"{R}/output/Missing song list/Songs-Missing-From-SVF-List.xlsx"
CATF = f"{R}/input/batch-1/(S-46)SVF list of Song -April 2026.xlsx"
DST = f"{R}/output/batch3-output(Only Spotify RD)/SVF-RD-SKV8.xlsx"

HDR_ROWS = 2                     # row 1 = section bands, row 2 = column headers
FIRST = 3                        # first data row
GREY_R = "F2F2F2"                # alternating fill on the five identity columns


def s(v):
    return "" if v is None else str(v).strip()


def nk(v):
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


def ik(v):
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


def noi(v):
    t = s(v)
    if not t:
        return ""
    try:
        return str(int(float(t)))
    except ValueError:
        return t


def isrc_list(v):
    return [ik(x) for x in s(v).split("|") if ik(x)]


def no_list(v):
    return [noi(x) for x in s(v).split("|") if noi(x)]


# ------------------------------------------------------------------ source 3
CAT_NO, CAT_ISRC, CAT_NAME = set(), set(), defaultdict(list)
wb = openpyxl.load_workbook(CATF, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    name, no, iss = s(r[0]), noi(r[1]), isrc_list(r[2])
    if not name and not no:
        continue
    if no:
        CAT_NO.add(no)
    CAT_ISRC.update(iss)
    CAT_NAME[nk(name)].append(dict(name=name, no=no, isrcs=iss))
wb.close()

# ------------------------------------------------------------------ source 2
MISSING = []
wb = openpyxl.load_workbook(MISS, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=FIRST, values_only=True):
    name = s(r[1])
    if not name or name.upper() == "TOTAL":
        continue
    MISSING.append(dict(name=name, isrcs=isrc_list(r[0]), nos=no_list(r[2])))
wb.close()

# songs the user asked about: title already in the catalogue, identifiers not
TARGET = defaultdict(lambda: dict(isrcs=[], nos=[], names=[]))
for m in MISSING:
    k = nk(m["name"])
    if k not in CAT_NAME:
        continue
    t = TARGET[k]
    t["names"].append(m["name"])
    for i in m["isrcs"]:
        if i not in t["isrcs"]:
            t["isrcs"].append(i)
    for n in m["nos"]:
        if n not in t["nos"]:
            t["nos"].append(n)

# ------------------------------------------------------------------ source 1
shutil.copyfile(SKV7, DST)
wb = openpyxl.load_workbook(DST)
ws = wb.active
NCOL = ws.max_column

total_row = next(r for r in range(FIRST, ws.max_row + 1)
                 if s(ws.cell(r, 2).value).upper() == "TOTAL")
note_row = next(r for r in range(total_row, ws.max_row + 1)
                if s(ws.cell(r, 1).value).startswith("SVF-RD-SKV"))
last = max(r for r in range(FIRST, total_row) if s(ws.cell(r, 2).value))
data_rows = list(range(FIRST, last + 1))

# column roles, read off the two header rows
band, BANDS = "", []
for c in range(1, NCOL + 1):
    v = s(ws.cell(1, c).value)
    if v:
        band = v
    BANDS.append((band, s(ws.cell(2, c).value)))
AMOUNT_C = [c for c in range(4, NCOL + 1) if BANDS[c - 1][1] in ("Amount",)]
FY_C = [c for c in range(1, NCOL + 1) if BANDS[c - 1][0].upper().startswith("TOTAL REVENUE")]
NUM_C = sorted(set([4, 5] + AMOUNT_C + FY_C))
TEXT_C = [c for c in range(6, NCOL + 1) if c not in NUM_C]
AUDIT_C = {BANDS[c - 1][1]: c for c in range(1, NCOL + 1)
           if BANDS[c - 1][0].upper().startswith("AUDIT")}
STATUS_C = AUDIT_C.get("Catalogue Status")

by_name = defaultdict(list)
for r in data_rows:
    by_name[nk(ws.cell(r, 2).value)].append(r)


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return 0.0


before = {c: round(sum(num(ws.cell(r, c).value) for r in data_rows), 2) for c in NUM_C}

# ------------------------------------------------------------------ the two edits
merge_log, isrc_log, kill = [], [], []
for key, t in sorted(TARGET.items()):
    rows = by_name.get(key, [])
    if not rows:
        continue
    # the surviving row: catalogue identifiers first, then the biggest Total Amount
    def rank(r):
        iss, no = isrc_list(ws.cell(r, 1).value), noi(ws.cell(r, 3).value)
        in_cat = bool((no and no in CAT_NO) or (set(iss) & CAT_ISRC))
        return (0 if in_cat else 1, -num(ws.cell(r, 4).value), -num(ws.cell(r, 5).value), r)
    rows = sorted(rows, key=rank)
    keep, drop = rows[0], rows[1:]

    isrcs = isrc_list(ws.cell(keep, 1).value)
    nos = no_list(ws.cell(keep, 3).value)
    for r in drop:
        for i in isrc_list(ws.cell(r, 1).value):
            if i not in isrcs:
                isrcs.append(i)
        for n in no_list(ws.cell(r, 3).value):
            if n not in nos:
                nos.append(n)
        for c in NUM_C:                                   # money adds up
            ws.cell(keep, c).value = round(num(ws.cell(keep, c).value) + num(ws.cell(r, c).value), 2)
        for c in TEXT_C:                                  # first statement detail wins
            if not s(ws.cell(keep, c).value) and s(ws.cell(r, c).value):
                ws.cell(keep, c).value = ws.cell(r, c).value
        kill.append(r)

    added = [i for i in t["isrcs"] if i not in isrcs]      # the unregistered ISRC(s)
    isrcs += added
    added_no = [n for n in t["nos"] if n not in nos]
    nos += added_no

    ws.cell(keep, 1).value = " | ".join(isrcs)
    ws.cell(keep, 3).value = " | ".join(nos)               # blank when nothing is known

    note = []
    if drop:
        note.append("SKV8: merged %d row(s) with the same song name (internal no %s)"
                    % (len(drop), ", ".join(no_list(ws.cell(r, 3).value) or ["none"]) or "none"))
        merge_log.append((ws.cell(keep, 2).value, keep, drop, nos, isrcs))
    if added:
        note.append("SKV8: ISRC %s reported by Spotify but NOT registered in S-46"
                    % ", ".join(added))
        isrc_log.append((ws.cell(keep, 2).value, added))
    if added_no:
        note.append("SKV8: internal no %s paid by a statement but NOT in S-46" % ", ".join(added_no))
    if note and STATUS_C:
        ws.cell(keep, STATUS_C).value = " ; ".join([s(ws.cell(keep, STATUS_C).value)] + note).strip(" ;")

for r in sorted(kill, reverse=True):
    ws.delete_rows(r)

# ------------------------------------------------------------------ tidy up
last -= len(kill)
total_row -= len(kill)
note_row -= len(kill)
data_rows = list(range(FIRST, last + 1))
grey = PatternFill("solid", fgColor=GREY_R)
blank = PatternFill(fill_type=None)
for n, r in enumerate(data_rows):                          # re-stripe after the deletions
    for c in range(1, 6):
        ws.cell(r, c).fill = grey if n % 2 == 0 else blank

for c in NUM_C:                                            # recompute the TOTAL row
    ws.cell(total_row, c).value = round(sum(num(ws.cell(r, c).value) for r in data_rows), 2)

ws.title = "SVF-RD-SKV8"
ws.auto_filter.ref = f"A2:{get_column_letter(NCOL)}{last}"
ws.cell(note_row, 1).value = (
    "SVF-RD-SKV8 = SVF-RD-SKV7 with the same-song / different-identifier rows folded together.  "
    "SKV7 matched a Spotify-reported recording to the catalogue by song name when its ISRC was not "
    "registered, so the money landed on the right row but column A showed only the registered ISRCs, "
    "and where a royalty statement had also paid the work under a second internal number the workbook "
    "carried two rows for one song.  In SKV8 every such song is one row: column A lists the registered "
    "ISRCs followed by the unregistered ISRC Spotify reported, column C lists every internal number "
    "involved (pipe separated, blank when no internal number exists anywhere in the three sources), "
    "and every amount of the merged rows is added into the survivor.  Column HO (Catalogue Status) "
    "names each change - 'SKV8: merged ...' and 'SKV8: ISRC ... NOT registered in S-46' - so a merge "
    "can be traced or reversed.  %d row(s) were merged away and %d unregistered ISRC(s) were written "
    "into column A across %d songs; grand totals are unchanged from SKV7, rupee for rupee."
    % (len(kill), sum(len(a) for _, a in isrc_log), len(TARGET)))

wb.save(DST)

# ------------------------------------------------------------------ verification
wb = openpyxl.load_workbook(DST, data_only=True)
w = wb.active
after = {c: round(sum(num(w.cell(r, c).value) for r in range(FIRST, last + 1)), 2) for c in NUM_C}
drift = {get_column_letter(c): (before[c], after[c]) for c in NUM_C if abs(before[c] - after[c]) > 0.011}
print(f"written : {DST}")
print(f"sheet   : {w.title}   rows {FIRST}..{last} ({len(data_rows)} songs, was {len(data_rows) + len(kill)})")
print(f"merged  : {len(kill)} row(s) folded into {len(merge_log)} song(s)")
for nm, keep, drop, nos, iss in merge_log:
    print(f"          {nm[:42]:44s} keep r{keep}  dropped {drop}  ->  no [{' | '.join(nos)}]  isrc [{' | '.join(iss)}]")
print(f"ISRCs   : {sum(len(a) for _, a in isrc_log)} unregistered ISRC(s) written into column A, {len(isrc_log)} song(s)")
for nm, a in isrc_log:
    print(f"          {nm[:42]:44s} + {', '.join(a)}")
print(f"VERIFY money drift vs SKV7 on {len(NUM_C)} numeric columns: {drift if drift else 'none - totals identical'}")
print(f"VERIFY TOTAL row D / E : {w.cell(total_row, 4).value} / {w.cell(total_row, 5).value}")
dups = sum(1 for k, v in defaultdict(list, {k: [r for r in range(FIRST, last + 1)
           if nk(w.cell(r, 2).value) == k] for k in TARGET}).items() if len(v) > 1)
print(f"VERIFY target songs still holding more than one row: {dups}")
