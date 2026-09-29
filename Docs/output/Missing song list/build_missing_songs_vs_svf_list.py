"""Songs missing from the SVF master song list.

Base            S1  (S-46)SVF list of Song -April 2026.xlsx      name + internal no + ISRC(s)
Tallied against S2  SVF-RD-SKV7.xlsx (batch3 output)             name + internal no + ISRC(s)
                S3  Spotify IPRS statement Oct'25-Mar'26         name + internal no          (no ISRC)
                S4  Raw Spotify MRM Oct'25-Mar'26                name + ISRC                 (no internal no)

Buckets (evaluated per source record against S1):
  A1  internal no absent from S1  +  ISRC absent from S1  +  song name absent from S1
      -> genuinely not in the SVF list
  A2  internal no absent  +  ISRC absent, but the song NAME exists in S1
      -> almost certainly the same song carrying different identifiers; the S1 internal
         no and the S1 possible ISRCs are printed next to it
  B   internal no matches S1 but the source row carries no ISRC
      -> song is in S1; S1 possible ISRCs printed so the ISRC can be filled in
  C   one ISRC pointing at more than one internal number
      -> "same ISRC, different internal no" list
Every sheet is de-duplicated; amounts of merged duplicates are added up.
"""
import re, warnings
from collections import defaultdict
warnings.filterwarnings("ignore")
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

R = "/home/swatantra/RD"
S1F = f"{R}/input/batch-1/(S-46)SVF list of Song -April 2026.xlsx"
S2F = f"{R}/output/batch3-output(Only Spotify RD)/SVF-RD-SKV7.xlsx"
S3F = f"{R}/input/batch-2/Spotify - for the Period October 2025 to March 2026.xlsx"
S4F = f"{R}/input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx"
DST = f"{R}/output/Songs-Not-In-SVF-Song-List.xlsx"

LBL = {"S2": "SVF-RD-SKV7 (consolidated RD)",
       "S3": "Spotify IPRS Statement Oct'25-Mar'26",
       "S4": "Raw Spotify MRM Oct'25-Mar'26"}
AMT = {"S2": "Total RD Amount", "S3": "IPRS Royalty Amount", "S4": "Spotify Revenue (MRM)"}


def s(v):
    return "" if v is None else str(v).strip()


def nk(v):                                    # name key: case / space / punctuation blind
    return re.sub(r"[^a-z0-9]", "", s(v).lower())


def ik(v):                                    # ISRC key
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())


def noi(v):                                   # 16026924.0 -> "16026924"
    t = s(v)
    if not t:
        return None
    try:
        return str(int(float(t)))
    except ValueError:
        return t


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return 0.0


# ------------------------------------------------------------------ S1 base catalogue
s1_rows = []
wb = openpyxl.load_workbook(S1F, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    name, no, isr = s(r[0]), noi(r[1]), s(r[2])
    if not name and not no:
        continue
    s1_rows.append(dict(name=name, no=no, isrcs=[ik(x) for x in isr.split("|") if ik(x)]))
wb.close()

S1_BY_NO = {}                       # internal no -> names / isrcs as listed in S1
S1_ISRC = defaultdict(list)         # ISRC        -> internal nos
S1_ISRC_NAME = defaultdict(list)    # ISRC        -> song names
S1_BY_NAME = defaultdict(list)      # name key    -> S1 rows
for x in s1_rows:
    if x["no"]:
        e = S1_BY_NO.setdefault(x["no"], dict(names=[], isrcs=[]))
        if x["name"] and x["name"] not in e["names"]:
            e["names"].append(x["name"])
        for i in x["isrcs"]:
            if i not in e["isrcs"]:
                e["isrcs"].append(i)
    for i in x["isrcs"]:
        if x["no"] and x["no"] not in S1_ISRC[i]:
            S1_ISRC[i].append(x["no"])
        if x["name"] not in S1_ISRC_NAME[i]:
            S1_ISRC_NAME[i].append(x["name"])
    S1_BY_NAME[nk(x["name"])].append(x)

# ------------------------------------------------------------------ S2  SVF-RD-SKV7
S2 = []
wb = openpyxl.load_workbook(S2F, data_only=True, read_only=True)
for i, r in enumerate(wb.active.iter_rows(min_row=3, values_only=True), 3):
    isr, name, no = s(r[0]), s(r[1]), noi(r[2])
    if name.upper() == "TOTAL" or (not name and not no):
        continue
    S2.append(dict(src="S2", row=i, name=name, no=no,
                   isrcs=[ik(x) for x in isr.split("|") if ik(x)], amt=num(r[3])))
wb.close()

# ------------------------------------------------------------------ S3  IPRS statement
S3, cur = [], None
wb = openpyxl.load_workbook(S3F, data_only=True)
for i, r in enumerate(wb.active.iter_rows(min_row=5, values_only=True), 5):
    no = noi(r[0])
    if no and re.fullmatch(r"\d{4,}", no):
        cur = dict(src="S3", row=i, name=s(r[1]), no=no, isrcs=[], amt=0.0)
        S3.append(cur)
    if cur is not None and len(r) > 11 and s(r[11]):
        cur["amt"] = num(r[11])            # block total is the last value of the block
wb.close()

# ------------------------------------------------------------------ S4  raw Spotify MRM
agg = {}
wb = openpyxl.load_workbook(S4F, data_only=True, read_only=True)
for r in wb.active.iter_rows(min_row=2, values_only=True):
    i = ik(r[5])
    if not i:
        continue
    k = (i, nk(r[3]))
    e = agg.setdefault(k, dict(src="S4", row=0, name=s(r[3]), no=None, isrcs=[i],
                               amt=0.0, album=s(r[4])))
    e["amt"] += num(r[7])
wb.close()
S4 = sorted(agg.values(), key=lambda x: -x["amt"])
for n, x in enumerate(S4, 2):
    x["row"] = n

print(f"S1 SVF song list rows     : {len(s1_rows):,}  ({len(S1_BY_NO):,} internal nos, "
      f"{len(S1_ISRC_NAME):,} ISRCs)")
print(f"S2 SVF-RD-SKV7 songs      : {len(S2):,}")
print(f"S3 IPRS statement works   : {len(S3):,}")
print(f"S4 Spotify MRM name+ISRC  : {len(S4):,}")


# ------------------------------------------------------------------ classification
def classify(rec):
    no, isr = rec["no"], rec["isrcs"]
    no_hit = bool(no and no in S1_BY_NO)
    s1_isrcs = S1_BY_NO[no]["isrcs"] if no_hit else []
    hit_isrcs = [i for i in isr if i in S1_ISRC_NAME]
    name_rows = S1_BY_NAME.get(nk(rec["name"]), [])
    if not no_hit and not hit_isrcs:
        kind = "A2" if name_rows else "A1"
    elif no_hit and not isr:
        kind = "B"
    elif no_hit and [i for i in isr if i not in s1_isrcs]:
        kind = "B2"
    elif hit_isrcs and no and no not in {o for i in hit_isrcs for o in S1_ISRC[i]}:
        kind = "C"
    else:
        kind = "OK"
    return dict(kind=kind, no_hit=no_hit, s1_isrcs=s1_isrcs, hit_isrcs=hit_isrcs,
                new_isrcs=[i for i in isr if i not in S1_ISRC_NAME], name_rows=name_rows)


buckets = defaultdict(list)
for data in (S2, S3, S4):
    for x in data:
        c = classify(x)
        x["c"] = c
        buckets[(x["src"], c["kind"])].append(x)


def dedup(rows):
    """One row per (internal no, ISRC set, song name); merged rows add their amounts."""
    out, seen = [], {}
    for x in rows:
        k = (x["no"] or "", "|".join(sorted(x["isrcs"])), nk(x["name"]))
        if k in seen:
            seen[k]["amt"] += x["amt"]
            continue
        y = dict(x)
        seen[k] = y
        out.append(y)
    return out


# ------------------------------------------------------------------ workbook helpers
HFILL = PatternFill("solid", fgColor="1F3864")
HFONT = Font(bold=True, color="FFFFFF", size=10)
TFONT = Font(bold=True, size=14, color="1F3864")
NFILL = PatternFill("solid", fgColor="FFF2CC")
BORD = Border(*[Side(style="thin", color="BFBFBF")] * 4)
MONEY = '#,##0.00'

wbo = openpyxl.Workbook()
wbo.remove(wbo.active)


def sheet(title, note, headers, rows, widths, money_cols=()):
    ws = wbo.create_sheet(title[:31])
    ws["A1"] = title
    ws["A1"].font = TFONT
    ws["A2"] = note
    ws["A2"].font = Font(italic=True, size=9, color="595959")
    ws["A3"] = f"Rows: {len(rows):,}   (de-duplicated)"
    ws["A3"].font = Font(bold=True, size=9, color="C00000")
    for c, h in enumerate(headers, 1):
        cell = ws.cell(5, c, h)
        cell.fill, cell.font, cell.border = HFILL, HFONT, BORD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for ri, row in enumerate(rows, 6):
        for ci, v in enumerate(row, 1):
            cell = ws.cell(ri, ci, v)
            cell.border = BORD
            cell.alignment = Alignment(vertical="top", wrap_text=(ci in (2, 3)))
            if ci in money_cols:
                cell.number_format = MONEY
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[5].height = 30
    ws.freeze_panes = "A6"
    if rows:
        ws.auto_filter.ref = f"A5:{get_column_letter(len(headers))}{5 + len(rows)}"
    return ws


def s1_ref(name_rows):
    nos = []
    names = []
    isrcs = []
    for y in name_rows:
        if y["no"] and y["no"] not in nos:
            nos.append(y["no"])
        if y["name"] not in names:
            names.append(y["name"])
        for i in y["isrcs"]:
            if i not in isrcs:
                isrcs.append(i)
    return " | ".join(nos), " | ".join(names), " | ".join(isrcs)


# ------------------------------------------------------------------ A1 / A2 / B sheets
SHEETS = [
    ("S2", "A1", "SKV7 - Not In SVF Song List",
     "Songs paid in SVF-RD-SKV7 whose internal number, ISRC and song name are all absent "
     "from the SVF master song list (S-46). These are true additions."),
    ("S2", "A2", "SKV7 - Same Name Diff ID",
     "Internal number and ISRC are absent from the SVF song list, but the song NAME is present "
     "there - most likely the same song under a different internal number / ISRC. The SVF "
     "internal number and the possible ISRCs of that name are given for verification."),
    ("S3", "A1", "IPRS Stmt - Not In SVF List",
     "Works paid in the Spotify IPRS statement (Oct'25-Mar'26) whose internal number and song "
     "name are both absent from the SVF master song list. The statement carries no ISRC."),
    ("S3", "A2", "IPRS Stmt - Same Name Diff ID",
     "Internal number absent from the SVF song list but the song NAME is present there - likely "
     "the same song under a different internal number. SVF internal number and possible ISRCs given."),
    ("S4", "A1", "Spotify MRM - Not In SVF List",
     "Spotify raw MRM tracks whose ISRC and song name are both absent from the SVF master song "
     "list. The MRM file carries no internal number."),
]
counts = {}
for src, kind, title, note in SHEETS:
    rows_in = dedup(sorted(buckets[(src, kind)], key=lambda x: -x["amt"]))
    counts[(src, kind)] = len(rows_in)
    if kind == "A1":
        head = ["S.No", "Song Name (Source)", "Album (Source)" if src == "S4" else "Internal No (Source)",
                "ISRC (Source)", "In SVF Song List?", AMT[src], "Source Row"]
        wid = [7, 42, 30, 34, 20, 18, 11]
        body = [[n, x["name"],
                 (x.get("album", "") if src == "S4" else (x["no"] or "")),
                 " | ".join(x["isrcs"]),
                 "No - internal no, ISRC and name all absent", round(x["amt"], 2), x["row"]]
                for n, x in enumerate(rows_in, 1)]
        money = (6,)
    elif kind == "A2":
        head = ["S.No", "Song Name (Source)", "Internal No (Source)", "ISRC (Source)",
                "Matching Song Name In SVF List", "SVF Internal No (Possible)",
                "SVF ISRC (Possible)", "Source Internal No Found Anywhere In SVF List?",
                "Source ISRC Found Anywhere In SVF List?", "Remark", AMT[src], "Source Row"]
        wid = [7, 38, 20, 32, 38, 24, 46, 26, 26, 46, 18, 11]
        body = []
        for n, x in enumerate(rows_in, 1):
            nos, names, isrcs = s1_ref(x["c"]["name_rows"])
            found_no = ("Yes - internal no " + x["no"] if x["no"] and x["no"] in S1_BY_NO
                        else "No - absent from the whole SVF list" if x["no"] else "-")
            hit = [i for i in x["isrcs"] if i in S1_ISRC_NAME]
            found_i = ("Source row carries no ISRC" if not x["isrcs"]
                       else "Yes - " + " | ".join(hit) if hit
                       else "No - absent from the whole SVF list")
            rem = ("Song name is the same (case / spacing / punctuation ignored). "
                   + ("Only the internal number differs - the source internal number exists "
                      "nowhere in the SVF list." if not x["isrcs"] else
                      "Internal number and ISRC both differ."))
            body.append([n, x["name"], x["no"] or "", " | ".join(x["isrcs"]), names, nos, isrcs,
                         found_no, found_i, rem, round(x["amt"], 2), x["row"]])
        money = (11,)
    sheet(title, note, head, body, wid, money)

# ---- B : internal number matches, source row has no ISRC
for src in ("S2", "S3"):
    rows_in = dedup(sorted(buckets[(src, "B")], key=lambda x: -x["amt"]))
    counts[(src, "B")] = len(rows_in)
    body = []
    for n, x in enumerate(rows_in, 1):
        e = S1_BY_NO[x["no"]]
        same = nk(x["name"]) in {nk(v) for v in e["names"]}
        body.append([n, x["name"], x["no"], " | ".join(e["names"]), " | ".join(e["isrcs"]),
                     "Same song - ISRC can be taken from SVF list" if same else
                     "Internal no matches but SVF name differs - verify",
                     round(x["amt"], 2), x["row"]])
    title = ("SKV7 - ISRC From SVF List" if src == "S2" else "IPRS Stmt - ISRC From SVF List")
    sheet(title,
          "Source row carries NO ISRC but its internal number is present in the SVF song list, so "
          "the song is the same one. The internal number and every possible ISRC held against it in "
          "the SVF list are printed here.",
          ["S.No", "Song Name (Source)", "Internal No", "Song Name In SVF List",
           "SVF Possible ISRC(s)", "Remark", AMT[src], "Source Row"],
          body, [7, 38, 16, 38, 52, 42, 18, 11], (7,))

# ------------------------------------------------------------------ song in the list, ISRC not
def name_isrcs(nkey):
    out = []
    for y in S1_BY_NAME.get(nkey, []):
        for i in y["isrcs"]:
            if i not in out:
                out.append(i)
    return out


irows, iseen = [], set()
for data in (S2, S3, S4):
    for x in sorted(data, key=lambda y: -y["amt"]):
        if not x["isrcs"]:
            continue
        c, nkey = x["c"], nk(x["name"])
        if c["no_hit"]:
            by, ref = "Internal number", c["s1_isrcs"]
            s1nos, s1names = x["no"], " | ".join(S1_BY_NO[x["no"]]["names"])
        elif nkey in S1_BY_NAME:
            by = "Song name"
            ref = name_isrcs(nkey)
            s1nos, s1names, _u = s1_ref(S1_BY_NAME[nkey])
        else:
            continue                       # song itself is not in the SVF list -> other sheets
        for i in x["isrcs"]:
            if i in ref or (i, nkey) in iseen:
                continue
            iseen.add((i, nkey))
            if i in S1_ISRC_NAME:
                status = ("Present in the SVF list but against internal no "
                          + (" | ".join(S1_ISRC[i]) or "-") + "  (song: "
                          + " / ".join(S1_ISRC_NAME[i]) + ")")
            else:
                status = "New ISRC - not present anywhere in the SVF song list"
            irows.append([0, LBL[x["src"]], x["name"], x.get("album", ""), i, by, s1names,
                          s1nos, " | ".join(ref), len(ref), status, round(x["amt"], 2), x["row"]])
for n, r in enumerate(irows, 1):
    r[0] = n
sheet("Song In List - ISRC Missing",
      "The song itself IS in the SVF master song list (matched on internal number, else on song "
      "name with case / spacing / punctuation ignored) but the ISRC quoted by the source is NOT "
      "one of the ISRCs held against that song in the SVF list. The ISRCs already listed for the "
      "song are printed so the new one can be added. Source 2 (SVF-RD-SKV7) contributes nothing "
      "here because its ISRC column is itself copied from the SVF song list.",
      ["S.No", "Source", "Song Name (Source)", "Album (Source)", "ISRC In Source (Missing)",
       "Matched With SVF Song By", "Song Name In SVF List", "SVF Internal No",
       "ISRC(s) Already In SVF List For This Song", "No. Of SVF ISRCs", "ISRC Status",
       "Amount (INR)", "Source Row"],
      irows, [7, 30, 34, 30, 22, 16, 34, 20, 46, 11, 60, 16, 11], (12,))

# ------------------------------------------------------------------ C : one ISRC, many internal nos
conf = {i: nos for i, nos in S1_ISRC.items() if len(nos) > 1}
s2_isrc = defaultdict(list)
for x in S2:
    for i in x["isrcs"]:
        if x["name"] not in s2_isrc[i]:
            s2_isrc[i].append(x["name"])
crows = []
for n, (i, nos) in enumerate(sorted(conf.items(), key=lambda kv: (-len(kv[1]), kv[0])), 1):
    crows.append([n, i, len(nos), " | ".join(sorted(nos)),
                  " | ".join(" / ".join(S1_BY_NO[o]["names"]) for o in sorted(nos)),
                  "Yes" if i in s2_isrc else "No", " | ".join(s2_isrc.get(i, []))])
sheet("Same ISRC Diff Internal No",
      "The same ISRC is held against more than one internal number. Every source that quotes this "
      "ISRC therefore resolves to two different works - the internal number has to be corrected in "
      "the SVF song list before the song can be tallied.",
      ["S.No", "ISRC", "No. Of Internal Nos", "Internal Nos (SVF List)",
       "Song Names (SVF List)", "Paid In SKV7?", "Song Name In SKV7"],
      crows, [7, 18, 12, 30, 56, 13, 40])

# ------------------------------------------------------------------ master unique list
master, seen = [], {}
for src in ("S2", "S3", "S4"):
    for kind in ("A1", "A2"):
        for x in sorted(buckets[(src, kind)], key=lambda y: -y["amt"]):
            k = x["no"] or (x["isrcs"][0] if x["isrcs"] else nk(x["name"]))
            if k in seen:
                e = seen[k]
                if LBL[src] not in e["srcs"]:
                    e["srcs"].append(LBL[src])
                for i in x["isrcs"]:
                    if i not in e["isrcs"]:
                        e["isrcs"].append(i)
                e["amt"] += x["amt"]
                continue
            nos, names, isrcs = s1_ref(x["c"]["name_rows"])
            e = dict(name=x["name"], no=x["no"] or "", isrcs=list(x["isrcs"]),
                     srcs=[LBL[src]], amt=x["amt"],
                     kind=("Not in SVF song list" if kind == "A1"
                           else "Song in SVF list - ISRC not in SVF list" if src == "S4"
                           else "Song name in SVF list - internal number differs"),
                     s1no=nos, s1name=names, s1isrc=isrcs)
            seen[k] = e
            master.append(e)
mrows = [[n, e["name"], e["no"], " | ".join(e["isrcs"]), e["kind"], " ; ".join(e["srcs"]),
          e["s1name"], e["s1no"], e["s1isrc"], round(e["amt"], 2)]
         for n, e in enumerate(sorted(master, key=lambda y: -y["amt"]), 1)]
sheet("All Sources - Missing Unique",
      "Every song of sources 2, 3 and 4 that the SVF master song list does not carry, merged into "
      "one de-duplicated list (key = internal number, else ISRC, else song name). Amounts of the "
      "merged rows are added up.",
      ["S.No", "Song Name", "Internal No (Source)", "ISRC (Source)", "Category", "Found In Source",
       "Matching Name In SVF List", "SVF Internal No (Possible)", "SVF ISRC (Possible)",
       "Amount (INR)"],
      mrows, [7, 40, 20, 34, 40, 44, 36, 24, 44, 16], (10,))

# ------------------------------------------------------------------ summary (first sheet)
ws = wbo.create_sheet("Summary", 0)
ws["A1"] = "Songs Not Available In The SVF Master Song List"
ws["A1"].font = Font(bold=True, size=16, color="1F3864")
ws["A2"] = "Base: (S-46)SVF list of Song -April 2026.xlsx   |   built 2026-09-08"
ws["A2"].font = Font(italic=True, size=10, color="595959")
line = 4
ws.cell(line, 1, "Source inventory").font = Font(bold=True, size=12)
line += 1
for h, c in zip(["Source", "File", "Rows Read", "Carries Internal No", "Carries ISRC"], range(1, 6)):
    cell = ws.cell(line, c, h)
    cell.fill, cell.font, cell.border = HFILL, HFONT, BORD
inv = [("S1 - base", "(S-46)SVF list of Song -April 2026.xlsx", len(s1_rows), "Yes", "Yes"),
       ("S2", "SVF-RD-SKV7.xlsx", len(S2), "Yes", "Yes"),
       ("S3", "Spotify - for the Period October 2025 to March 2026.xlsx", len(S3), "Yes", "No"),
       ("S4", "Raw_Spotify_MRM_Oct25_Mar26.xlsx", len(S4), "No", "Yes")]
for r in inv:
    line += 1
    for c, v in enumerate(r, 1):
        cell = ws.cell(line, c, v)
        cell.border = BORD
line += 2
ws.cell(line, 1, "Sheets in this workbook").font = Font(bold=True, size=12)
line += 1
for h, c in zip(["Sheet", "What it holds", "Rows"], range(1, 4)):
    cell = ws.cell(line, c, h)
    cell.fill, cell.font, cell.border = HFILL, HFONT, BORD
note = {t: n for _s, _k, t, n in SHEETS}
tbl = [("SKV7 - Not In SVF Song List", note["SKV7 - Not In SVF Song List"], counts[("S2", "A1")]),
       ("SKV7 - Same Name Diff ID", note["SKV7 - Same Name Diff ID"], counts[("S2", "A2")]),
       ("IPRS Stmt - Not In SVF List", note["IPRS Stmt - Not In SVF List"], counts[("S3", "A1")]),
       ("IPRS Stmt - Same Name Diff ID", note["IPRS Stmt - Same Name Diff ID"], counts[("S3", "A2")]),
       ("Spotify MRM - Not In SVF List", note["Spotify MRM - Not In SVF List"], counts[("S4", "A1")]),
       ("SKV7 - ISRC From SVF List",
        "Internal number found in the SVF list, source row carries no ISRC - SVF possible ISRCs printed",
        counts[("S2", "B")]),
       ("IPRS Stmt - ISRC From SVF List",
        "Internal number found in the SVF list, statement carries no ISRC - SVF possible ISRCs printed",
        counts[("S3", "B")]),
       ("Song In List - ISRC Missing",
        "Song is in the SVF list but the ISRC quoted by the source is not one of the ISRCs held "
        "against that song", len(irows)),
       ("Same ISRC Diff Internal No",
        "One ISRC held against more than one internal number in the SVF song list", len(crows)),
       ("All Sources - Missing Unique",
        "All songs missing from the SVF song list, de-duplicated across the three sources", len(mrows))]
for t, n, cnt in tbl:
    line += 1
    ws.cell(line, 1, t).border = BORD
    ws.cell(line, 1).font = Font(bold=True)
    c2 = ws.cell(line, 2, n)
    c2.border, c2.alignment = BORD, Alignment(wrap_text=True, vertical="top")
    c3 = ws.cell(line, 3, cnt)
    c3.border, c3.fill, c3.font = BORD, NFILL, Font(bold=True)
    ws.row_dimensions[line].height = 30
line += 2
for txt in ["Matching rules applied against the base list:",
            "1.  Internal number match = exact match on the SVF 'Internal NO' column.",
            "2.  ISRC match = exact match on any ISRC of the pipe-separated SVF 'ISRC' column.",
            "3.  Song name match = case / space / punctuation insensitive.",
            "4.  Internal no absent + ISRC absent + name absent  ->  'Not In SVF Song List'.",
            "5.  Internal no absent + ISRC absent + name present ->  'Same Name Diff ID', SVF "
            "internal no and possible ISRCs printed for verification.",
            "6.  Internal no present + source row has no ISRC   ->  song is the same, SVF possible "
            "ISRCs printed ('ISRC From SVF List').",
            "7.  Song found in the SVF list (by internal no, else by name) but the ISRC quoted by "
            "the source is not one of the ISRCs held against it -> 'Song In List - ISRC Missing'.",
            "8.  One ISRC pointing at more than one internal number -> 'Same ISRC Diff Internal No'.",
            "9.  Every sheet is de-duplicated on (internal no, ISRC set, song name); amounts of "
            "merged rows are added up."]:
    ws.cell(line, 1, txt).font = Font(bold=txt.endswith(":"), size=10)
    line += 1
for c, w in zip("ABCDE", (34, 78, 14, 22, 16)):
    ws.column_dimensions[c].width = w

wbo.save(DST)
print("\nwrote", DST)
for t, n, cnt in tbl:
    print(f"  {t:34s} {cnt:6,}")
