"""Independent re-read of the produced workbook against the four sources."""
import re, warnings
from collections import defaultdict, Counter
warnings.filterwarnings("ignore")
import openpyxl
R="/home/swatantra/RD"
S1F=f"{R}/input/batch-1/(S-46)SVF list of Song -April 2026.xlsx"
DST=f"{R}/output/Songs-Not-In-SVF-Song-List.xlsx"
s=lambda v:"" if v is None else str(v).strip()
nk=lambda v:re.sub(r"[^a-z0-9]","",s(v).lower())
ik=lambda v:re.sub(r"[^A-Z0-9]","",s(v).upper())
def noi(v):
    t=s(v)
    if not t: return None
    try: return str(int(float(t)))
    except ValueError: return t
NOS=set(); ISR=set(); NAM=set(); BYNO=defaultdict(set)
wb=openpyxl.load_workbook(S1F,data_only=True,read_only=True)
for r in wb.active.iter_rows(min_row=2,values_only=True):
    n=noi(r[1])
    if n: NOS.add(n)
    NAM.add(nk(r[0]))
    for x in s(r[2]).split("|"):
        if ik(x):
            ISR.add(ik(x))
            if n: BYNO[n].add(ik(x))
wb.close()
wb=openpyxl.load_workbook(DST,data_only=True); bad=0
def rows(ws):
    hdr=[s(c.value) for c in ws[5]]
    for r in ws.iter_rows(min_row=6,values_only=True):
        if all(v is None for v in r): continue
        yield dict(zip(hdr,r))
for ws in wb.worksheets:
    if ws.title=="Summary": continue
    rs=list(rows(ws)); h=[s(c.value) for c in ws[5]]
    key=[]
    for d in rs:
        key.append((noi(d.get("Internal No (Source)") or d.get("Internal No")),
                    ik(d.get("ISRC (Source)") or d.get("ISRC In Source (Missing)")
                       or d.get("ISRC") or ""),
                    nk(d.get("Song Name (Source)") or d.get("Song Name") or "")))
    dup=[k for k,c in Counter(key).items() if c>1]
    print(f"{ws.title:32s} rows={len(rs):5d} dup={len(dup)}")
    if dup: bad+=1; print("   DUP:",dup[:3])
    for d in rs:
        t=ws.title
        no=noi(d.get("Internal No (Source)") or d.get("Internal No"))
        isr=[ik(x) for x in s(d.get("ISRC (Source)") or d.get("ISRC") or "").split("|") if ik(x)]
        nm=nk(d.get("Song Name (Source)") or d.get("Song Name") or "")
        if "Not In SVF" in t:
            if (no and no in NOS) or any(i in ISR for i in isr) or nm in NAM:
                bad+=1; print("   BAD not-missing:",t,no,isr,nm); break
        if "Same Name Diff ID" in t:
            if nm not in NAM or (no and no in NOS) or any(i in ISR for i in isr):
                bad+=1; print("   BAD name-diff:",t,no,isr,nm); break
        if "ISRC From SVF List" in t:
            if no not in NOS or isr:
                bad+=1; print("   BAD isrc-from:",t,no,isr); break
            got=[ik(x) for x in s(d["SVF Possible ISRC(s)"]).split("|") if ik(x)]
            if set(got)!=BYNO[no]:
                bad+=1; print("   BAD isrc-list:",no,got,BYNO[no]); break
        if t.startswith("Same ISRC"):
            i=ik(d["ISRC"]); nos={noi(x) for x in s(d["Internal Nos (SVF List)"]).split("|") if noi(x)}
            if len(nos)<2 or not all(i in BYNO[n] for n in nos):
                bad+=1; print("   BAD isrc-conf:",i,nos); break
print("\nVERDICT:", "OK - all checks passed" if bad==0 else f"{bad} FAILURES")
