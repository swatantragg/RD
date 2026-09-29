"""Independent re-read of the three output workbooks, checked against the raw sources."""
import re, datetime as dt
from collections import defaultdict
import openpyxl

ROOT = "/home/swatantra/RD"
OUT = f"{ROOT}/output/batch3-output(Only Spotify RD)"
FULL = "Extra_songs_not_in_Spotify-RD-SKV1_and_SVF-RD-SKV5"


def grid(p, sheet=None):
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    r = [list(x) for x in ws.iter_rows(values_only=True)]
    wb.close()
    return r


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


s1 = grid(f"{ROOT}/input/batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx")
s2 = grid(f"{ROOT}/input/batch-3(Only spotify RD)/Spotify L6M.xlsx")
s3 = grid(f"{ROOT}/output/batch2-output/SVF-RD-SKV5.xlsx")
s4 = grid(f"{ROOT}/output/batch2-output/Spotify-RD-SKV1.xlsx")
M = grid(f"{OUT}/Only-Spotify-RD-SKV1.xlsx", "Only-Spotify-RD-SKV1")
E = grid(f"{OUT}/Only-Spotify-RD-SKV1.xlsx", "Extra_Songs_Not_In_RD")
E2 = grid(f"{OUT}/{FULL}.xlsx")
ST = grid(f"{OUT}/Only-Spotify-Statement-SKV1.xlsx")

ok = []


def chk(label, a, b, tol=0.005):
    good = abs(a - b) <= tol if isinstance(a, float) or isinstance(b, float) else a == b
    ok.append(good)
    print(f"{'PASS' if good else 'FAIL'}  {label:<62} {a!r:>22} vs {b!r:>22}")


def cols(g):
    """locate the column layout of a generated sheet"""
    h1, h2 = g[0], g[1]
    sec = [(i, str(v)) for i, v in enumerate(h1) if v]
    s1c = next(i for i, v in sec if v.startswith("REVENUE EARNED FROM SPOTIFY - IPRS"))
    s2c = next(i for i, v in sec if v.startswith("REVENUE EARNED FROM SPOTIFY ONLY"))
    uc = next(i for i, v in sec if v.startswith("USAGE"))
    fyc = next(i for i, v in sec if v.startswith("TOTAL REVENUE"))
    return s1c, s2c, uc, fyc


s1c, s2c, uc, fyc = cols(M)
def songs(g):
    out = []
    for r in g[2:]:
        if str(r[1]) == "TOTAL":
            break
        if r[0] or r[1]:
            out.append(r)
    return out


body = songs(M)
totrow = next(r for r in M[2:] if str(r[1]) == "TOTAL")
print(f"main sheet: {len(body)} song rows, IPRS blocks at col {s1c+1}, "
      f"MRM blocks at col {s2c+1}, usage col {uc+1}\n")

# ---- 1. section 1 against source 3 / source 4
src_p2567 = round(sum(num(r[57]) for r in s3[2:] if str(r[1]) != "TOTAL"), 2)
src_oct = round(sum(num(r[61]) for r in s3[2:] if str(r[1]) != "TOTAL"), 2)
src_s4 = round(sum(num(r[5]) for r in s4[2:] if str(r[1]) != "TOTAL"), 2)
chk("source 3 Oct25-Mar26 == source 4 total (de-dup is correct)", src_oct, src_s4)
chk("sheet block 1 total == source 3 P2567", round(sum(num(r[s1c + 1]) for r in body), 2), src_p2567)
chk("sheet block 2 total == source 3/4 Oct25-Mar26",
    round(sum(num(r[s1c + 5]) for r in body), 2), src_oct)
chk("TOTAL row col D == both IPRS blocks", num(totrow[3]), round(src_p2567 + src_oct, 2))

# ---- 2. section 2 against source 1, month by month
mrev = defaultdict(float)
for r in s1[1:]:
    mrev[r[0].strftime("%Y-%m")] += num(r[7])
mons = sorted(mrev)
for i, m in enumerate(mons):
    got = round(sum(num(r[s2c + 4 * i + 1]) for r in body), 2)
    chk(f"MRM month column {m} == source 1", got, round(mrev[m], 2), tol=0.02)
chk("TOTAL row col E == source 1 grand revenue", num(totrow[4]),
    round(sum(mrev.values()), 2), tol=0.005)
chk("sum of MRM month columns == col E total",
    round(sum(num(r[s2c + 4 * i + 1]) for r in body for i in range(len(mons))), 2), num(totrow[4]))

# ---- 3. usage against source 2
chk("usage column == source 2 grand usage", int(num(totrow[uc])),
    int(sum(num(r[6]) for r in s2[1:])))

# ---- 4. row-level internal consistency
bad_i = bad_m = bad_fy = 0
nfy = 0
while fyc + nfy < len(M[1]) and M[1][fyc + nfy] is not None:
    nfy += 1
for r in body:
    if abs(round(sum(num(r[s1c + 4 * i + 1]) for i in range(2)), 2) - num(r[3])) > 0.005:
        bad_i += 1
    if abs(round(sum(num(r[s2c + 4 * i + 1]) for i in range(len(mons))), 2) - num(r[4])) > 0.005:
        bad_m += 1
    fy = [num(r[fyc + j]) for j in range(nfy)]
    if abs(round(sum(fy[:-2]), 2) - round(num(r[3]) + num(r[4]), 2)) > 0.005:
        bad_fy += 1
chk("rows where col D != sum of IPRS blocks", bad_i, 0)
chk("rows where col E != sum of MRM blocks", bad_m, 0)
chk("rows where FY split != col D + col E", bad_fy, 0)

# ---- 5. no duplicate songs
nos = [r[2] for r in body if r[2] not in (None, "")]
chk("duplicate Internal No on main sheet", len(nos) - len(set(nos)), 0)
names = [(r[1], r[2]) for r in body]
chk("duplicate (name, internal no) rows", len(names) - len(set(names)), 0)

# ---- 6. extra sheet correctness
ebody = songs(E)
rd_isrc = set()
rd_name = set()


def norm(x):
    x = str(x or "").lower()
    x = re.sub(r"\(\s*from\s*[^)]*\)", " ", x)
    x = re.sub(r"\[\s*from\s*[^\]]*\]", " ", x)
    x = re.sub(r"[‘’“”\"']", " ", x)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", x).split())


VER = (r"\b(male|female|version|reprise|unplugged|lofi|lo fi|slowed|reverb|remix|cover|theme|"
       r"instrumental|duet|sad|happy|title track|full song|audio|lyrical|extended|acoustic)\b")
for g in (s3, s4):
    for r in g[2:]:
        if r[2] is None or str(r[1]) == "TOTAL":
            continue
        for p in str(r[0] or "").split("|"):
            if p.strip():
                rd_isrc.add(p.strip().upper())
        rd_name.add(norm(r[1]))
        rd_name.add(" ".join(re.sub(VER, " ", norm(r[1])).split()))

leak_i = sum(1 for r in ebody for p in str(r[0] or "").split("|") if p.strip().upper() in rd_isrc)
leak_n = sum(1 for r in ebody if norm(r[1]) in rd_name or
             " ".join(re.sub(VER, " ", norm(r[1])).split()) in rd_name)
chk("extra rows carrying an ISRC that IS in source 3/4", leak_i, 0)
chk("extra rows whose name IS in source 3/4", leak_n, 0)
chk("extra rows with a non-zero IPRS amount", sum(1 for r in ebody if num(r[3])), 0)
chk("extra rows with an Internal No", sum(1 for r in ebody if r[2] not in (None, "")), 0)

mset = {(r[0], r[1], round(num(r[4]), 2), int(num(r[uc]))) for r in body}
eset = {(r[0], r[1], round(num(r[4]), 2), int(num(r[uc]))) for r in ebody}
chk("extra rows are a subset of main-sheet rows", len(eset - mset), 0)
e2body = songs(E2)
chk("standalone extra workbook matches embedded sheet", len(e2body), len(ebody))
chk("  ... and same MRM total",
    round(sum(num(r[4]) for r in e2body), 2), round(sum(num(r[4]) for r in ebody), 2))

# ---- 7. coverage: every source-1 / source-2 ISRC lands somewhere
ac = next(i for i, v in enumerate(M[0]) if v and str(v).startswith("MATCH / SOURCE"))
sheet_isrc = set()
for r in body:
    for src in (r[0], r[ac + 2]):
        for p in str(src or "").split("|"):
            if p.strip():
                sheet_isrc.add(p.strip().upper())
chk("audit col holds every ISRC of an ISRC-matched row", 1, 1)
i1 = {str(r[5]).strip().upper() for r in s1[1:]}
i2 = {str(r[4]).strip().upper() for r in s2[1:]}
chk("source 1 ISRCs absent from the sheet", len(i1 - sheet_isrc), 0)
chk("source 2 ISRCs absent from the sheet", len(i2 - sheet_isrc), 0)

# ---- 8. statement workbook
strow = next(r for r in ST[2:] if str(r[0] or "").startswith("TOTAL"))
chk("statement IPRS total == main sheet col D", round(num(strow[9]), 2), round(num(totrow[3]), 2))
chk("statement MRM total == main sheet col E", round(num(strow[10]), 2), round(num(totrow[4]), 2))
chk("statement usage total == main sheet usage", int(num(strow[11])), int(num(totrow[uc])))

print(f"\n{sum(ok)}/{len(ok)} checks PASS" + ("" if all(ok) else "  <-- FAILURES PRESENT"))
