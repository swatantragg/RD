"""Independent re-read of the four new workbooks, checked against the raw sources."""
import datetime as dt
from collections import defaultdict
import openpyxl

ROOT = "/home/swatantra/RD"
B3 = f"{ROOT}/output/batch3-output(Only Spotify RD)"
B2 = f"{ROOT}/output/batch2-output"
ok = []


def grid(p):
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    g = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    wb.close()
    return g


def n(v):
    try:
        f = float(v)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


def s(v):
    return "" if v is None else str(v).strip()


def chk(label, a, b, tol=0.005):
    good = abs(a - b) <= tol if isinstance(a, float) or isinstance(b, float) else a == b
    ok.append(good)
    print(f"{'PASS' if good else 'FAIL'}  {label:<66} {a!r:>20} vs {b!r:>20}")


RAW = grid(f"{ROOT}/input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx")
L6M = grid(f"{ROOT}/input/batch-3(Only spotify RD)/Spotify L6M.xlsx")
V1 = grid(f"{B3}/Only-Spotify-RD-SKV1.xlsx")
V2 = grid(f"{B3}/Only-Spotify-RD-SKV2.xlsx")
ST2 = grid(f"{B3}/Only-Spotify-Statement-SKV2.xlsx")
K5 = grid(f"{B2}/SVF-RD-SKV5.xlsx")
K6 = grid(f"{B2}/SVF-RD-SKV6.xlsx")
SA = grid(f"{B2}/Statement-SKV2.xlsx")
SB = grid(f"{B2}/Statement-SKV3.xlsx")

raw_month = defaultdict(float)
for r in RAW[1:]:
    if r[0] is not None:
        raw_month[r[0].strftime("%Y-%m")] += n(r[7])
MONS = sorted(raw_month)
RAW_TOT = round(sum(raw_month.values()), 2)
L6_TOT = int(sum(n(r[6]) for r in L6M[1:] if r[0] is not None))
K5_body = [r for r in K5[2:] if r[1] and s(r[1]) != "TOTAL"]
IPRS_OCT = round(sum(n(r[61]) for r in K5_body), 2)     # SVF-RD-SKV5 col 62 = Oct25-Mar26 amount
IPRS_APR = round(sum(n(r[57]) for r in K5_body), 2)     # SVF-RD-SKV5 col 58 = P2567 amount
K5_D = round(sum(n(r[3]) for r in K5_body), 2)

print("\n=== 1. Only-Spotify-RD-SKV2  (period cut + Percentage) " + "=" * 20)
b2 = [r for r in V2[2:] if r[1] and s(r[1]) != "TOTAL"]
tot2 = next(r for r in V2[2:] if s(r[1]) == "TOTAL")
h1, h2 = V2[0], V2[1]
secs = [(i + 1, s(v)) for i, v in enumerate(h1) if v]
print("   banners:")
for c, v in secs:
    print(f"      col {c:>3}  {v}")
chk("column F is named 'Percentage'", s(h2[5]), "Percentage")
chk("fixed column names unchanged (A-E)",
    [s(x) for x in h2[:5]],
    ["ISRC", "Song Name", "Internal No", "Total Spotify-IPRS Amount",
     "Total Spotify Revenue (MRM)"])
periods = {s(r[c]) for r in b2 for c in range(len(r)) if s(h2[c]) == "Period" and r[c]}
chk("no Apr 2025 - Sep 2025 / P2567 left anywhere", "Apr 2025 - Sep 2025" in periods, False)
chk("no 'P2567' in any data cell (explanatory note excluded)",
    any("P2567" in s(v) for r in V2[:V2.index(tot2) + 1] for v in r), False)
chk("exactly one IPRS distribution block", sum(1 for _c, v in secs if "SECTION A" in v), 1)
chk("IPRS block total == SVF-RD-SKV5 Oct25-Mar26 column",
    round(sum(n(r[7]) for r in b2), 2), IPRS_OCT)
chk("col D total == IPRS block total", round(sum(n(r[3]) for r in b2), 2), IPRS_OCT)
chk("TOTAL row col D", n(tot2[3]), IPRS_OCT)
for i, m in enumerate(MONS):
    chk(f"Section B month {m} == raw MRM report",
        round(sum(n(r[11 + 4 * i]) for r in b2), 2), round(raw_month[m], 2), tol=0.02)
chk("col E total == raw MRM grand total", round(sum(n(r[4]) for r in b2), 2), RAW_TOT)
chk("TOTAL row col E", n(tot2[4]), RAW_TOT)
chk("usage total == Spotify L6M report", int(sum(n(r[35]) for r in b2)), L6_TOT)
chk("TOTAL row usage", int(n(tot2[35])), L6_TOT)
badD = sum(1 for r in b2 if abs(n(r[3]) - n(r[7])) > 0.005)
badE = sum(1 for r in b2 if abs(round(sum(n(r[11 + 4 * i]) for i in range(6)), 2) - n(r[4])) > 0.005)
badP = sum(1 for r in b2 if r[4] and abs(n(r[5]) - n(r[3]) / n(r[4])) > 1e-9)
badPb = sum(1 for r in b2 if not n(r[4]) and r[5] is not None)
chk("rows where col D != the IPRS block amount", badD, 0)
chk("rows where col E != sum of the 6 month blocks", badE, 0)
chk("rows where Percentage != col D / col E", badP, 0)
chk("rows with no revenue that still show a Percentage", badPb, 0)
chk("TOTAL row Percentage == D/E", n(tot2[5]), IPRS_OCT / RAW_TOT, tol=1e-9)
FY = next(i for i, v in enumerate(h1) if s(v).startswith("SECTION D"))
nfy = sum(1 for j in range(FY, len(h2)) if h2[j] is not None and
          (j == FY or all(h2[k] is not None for k in range(FY, j + 1))))
badFY = sum(1 for r in b2 if abs(round(n(r[FY]) + n(r[FY + 1]), 2) - round(n(r[3]) + n(r[4]), 2)) > 0.005)
chk("rows where the FY split != col D + col E", badFY, 0)
chk("FY block Total Spotify-IPRS == col D", round(sum(n(r[FY + 2]) for r in b2), 2), IPRS_OCT)
chk("FY block Total Spotify (MRM) == col E", round(sum(n(r[FY + 3]) for r in b2), 2), RAW_TOT)
nos = [r[2] for r in b2 if r[2] not in (None, "")]
chk("duplicate Internal No", len(nos) - len(set(nos)), 0)
b1 = [r for r in V1[2:] if r[1] and s(r[1]) != "TOTAL"]
drop = sum(1 for r in b1 if r[10] is None and
           not any(r[14 + 4 * i] for i in range(6)) and not n(r[38]))
chk("rows dropped vs Only-Spotify-RD-SKV1 == rows that were P2567-only",
    len(b1) - len(b2), drop)

print("\n=== 2. Only-Spotify-Statement-SKV2 " + "=" * 40)
strow = next(r for r in ST2[2:] if s(r[0]).startswith("TOTAL"))
chk("statement IPRS total == RD sheet col D", round(n(strow[9]), 2), IPRS_OCT)
chk("statement MRM total == RD sheet col E", round(n(strow[10]), 2), RAW_TOT)
chk("statement usage total == RD sheet usage", int(n(strow[11])), L6_TOT)
chk("statement Percentage == IPRS / MRM", n(strow[14]), IPRS_OCT / RAW_TOT, tol=1e-9)
chk("statement lists 3 sources", sum(1 for r in ST2[2:] if s(r[0]).startswith("S-")), 3)
ST2d = ST2[:ST2.index(strow) + 1]
chk("no Apr 2025 - Sep 2025 in any data cell",
    any("Apr 2025 - Sep 2025" in s(v) for r in ST2d for v in r), False)
chk("no P2567 in any data cell", any("P2567" in s(v) for r in ST2d for v in r), False)

print("\n=== 3. SVF-RD-SKV6 " + "=" * 56)
SPOT_END, NEW = 64, 24


def cmap(c):
    return c if c <= 4 else (c + 1 if c <= SPOT_END else c + 1 + NEW)


LASTSONG = len(K5_body) + 2
diff = 0
for r in range(2, LASTSONG):
    for c in range(1, 198):
        a, b = K5[r][c - 1], K6[r][cmap(c) - 1]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) > 1e-9:
                diff += 1
        elif s(a) != s(b):
            diff += 1
chk("every SVF-RD-SKV5 cell survives unchanged (rows 3..last song)", diff, 0)
K6_body = [r for r in K6[2:] if r[1] and s(r[1]) != "TOTAL"]
K6_new = [r for r in K6_body if r[2] in (None, "")]
K6_old = [r for r in K6_body if r[2] not in (None, "")]
tot6 = next(r for r in K6[2:] if s(r[1]) == "TOTAL")
chk("original song rows all present", len(K6_old), len(K5_body))
chk("col D grand total unchanged", round(sum(n(r[3]) for r in K6_body), 2), K5_D)
chk("TOTAL row col D unchanged", n(tot6[3]), K5_D)
chk("new songs carry no royalty in col D", round(sum(n(r[3]) for r in K6_new), 2), 0.0)
chk("col E total == raw MRM grand total", round(sum(n(r[4]) for r in K6_body), 2), RAW_TOT)
chk("TOTAL row col E", n(tot6[4]), RAW_TOT)
M0 = 66
for i, m in enumerate(MONS):
    chk(f"MRM month {m} == raw report",
        round(sum(n(r[M0 + 4 * i]) for r in K6_body), 2), round(raw_month[m], 2), tol=0.02)
    chk(f"   TOTAL row month {m}", n(tot6[M0 + 4 * i]), round(raw_month[m], 2), tol=0.02)
badE6 = sum(1 for r in K6_body
            if abs(round(sum(n(r[M0 + 4 * i]) for i in range(6)), 2) - n(r[4])) > 0.005)
chk("rows where col E != sum of the 6 month blocks", badE6, 0)
FY6 = next(i for i, v in enumerate(K6[1]) if s(v) == "FY 2022-23")
chk("FY block still totals col D",
    round(sum(n(r[FY6 + k]) for r in K6_body for k in range(5)), 2), K5_D)
badfy6 = sum(1 for r in K6_body
             if abs(round(sum(n(r[FY6 + k]) for k in range(5)), 2) - n(r[3])) > 0.005)
chk("rows where the FY split != col D", badfy6, 0)
chk("Spotify IPRS Apr25-Sep25 column preserved", round(sum(n(r[58]) for r in K6_body), 2), IPRS_APR)
chk("Spotify IPRS Oct25-Mar26 column preserved", round(sum(n(r[62]) for r in K6_body), 2), IPRS_OCT)
nos6 = [r[2] for r in K6_body if r[2] not in (None, "")]
chk("duplicate Internal No", len(nos6) - len(set(nos6)), 0)
chk("no usage column on SVF-RD-SKV6",
    any("usage" in s(v).lower() for v in K6[0] + K6[1]), False)
chk("no percentage column on SVF-RD-SKV6",
    any(s(v).lower() == "percentage" for v in K6[1]), False)
# per-song Spotify revenue must equal Only-Spotify-RD-SKV1
v1_by_no, v1_extra = {}, defaultdict(float)
for r in b1:
    tot = round(sum(n(r[14 + 4 * i]) for i in range(6)), 2)
    if r[2] not in (None, ""):
        v1_by_no[r[2]] = tot
    else:
        v1_extra[s(r[1]).lower()] += tot
badmap = sum(1 for r in K6_old if abs(n(r[4]) - v1_by_no.get(r[2], 0.0)) > 0.005)
chk("every matched song's Spotify revenue == Only-Spotify-RD-SKV1", badmap, 0)
newmap = defaultdict(float)
for r in K6_new:
    newmap[s(r[1]).lower()] += n(r[4])
chk("appended songs' revenue == the extra songs of Only-Spotify-RD-SKV1",
    round(sum(newmap.values()), 2), round(sum(v1_extra.values()), 2))
chk("appended song count == extra songs that actually earned revenue",
    len(K6_new), sum(1 for k, v in v1_extra.items() if v > 0))

print("\n=== 4. Statement-SKV3 " + "=" * 53)
sa = [r for r in SA[2:] if s(r[0]).startswith("S-")]
sb = [r for r in SB[2:] if s(r[0]).startswith("S-")]
chk("one source added", len(sb) - len(sa), 1)
same = all(s(a[0]) == s(b[0]) and s(a[1]) == s(b[1]) and s(a[2]) == s(b[2]) and
           s(a[3]) == s(b[3]) and s(a[4]) == s(b[4]) and s(a[5]) == s(b[5]) and
           a[6] == b[6] and n(a[7]) == n(b[7]) and n(a[8]) == n(b[8]) and
           abs(n(a[9]) - n(b[9])) < 1e-9 for a, b in zip(sa, sb))
chk("the 46 existing statement rows are byte-identical", same, True)
tb = next(r for r in SB[2:] if s(r[0]).startswith("TOTAL"))
ta = next(r for r in SA[2:] if s(r[0]).startswith("TOTAL"))
chk("royalty grand total unchanged", round(n(tb[9]), 2), round(n(ta[9]), 2))
chk("royalty grand total == SVF-RD-SKV6 col D", round(n(tb[9]), 2), K5_D)
chk("Spotify MRM total == raw report", round(n(tb[10]), 2), RAW_TOT)
chk("Spotify MRM total == SVF-RD-SKV6 col E",
    round(n(tb[10]), 2), round(sum(n(r[4]) for r in K6_body), 2))
chk("new row carries 0.00 royalty", round(n(sb[-1][9]), 2), 0.0)
chk("new row carries the MRM revenue", round(n(sb[-1][10]), 2), RAW_TOT)
rec = [r for r in SB if s(r[0]).startswith("Difference")]
chk("reconciliation differences are zero", round(sum(n(r[2]) for r in rec), 2), 0.0)
chk("no usage column on Statement-SKV3",
    any("usage" in s(v).lower() for v in SB[1]), False)

print(f"\n{sum(ok)}/{len(ok)} checks PASS" + ("" if all(ok) else "   <-- FAILURES PRESENT"))
