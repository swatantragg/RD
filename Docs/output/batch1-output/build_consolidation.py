"""SVF royalty consolidation -> single .xlsx per SVF_Royalty_Consolidation_Spec.md"""
import glob, os, re, sys, warnings, datetime as dt
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

IN_DIR = "/home/swatantra/RD/input/batch-1"
OUT_DIR = "/home/swatantra/RD/output"
OUT_XLSX = os.path.join(OUT_DIR, "SVF_Royalty_Consolidated_Report.xlsx")
TOL = 0.05

SOCIETIES = {
    "008": ("APRA", "Australia"), "021": ("BMI", "USA"), "023": ("BUMA", "Netherlands"),
    "026": ("CASH", "Hong Kong"), "058": ("SACEM", "France"), "080": ("SUISA", "Switzerland"),
    "101": ("SOCAN", "Canada"), "104": ("MACP", "Malaysia"), "106": ("COMPASS", "Singapore"),
    "126": ("MCT", "Thailand"), "128": ("IMRO", "Ireland"),
}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_LBL = {v: k.capitalize() for k, v in MONTHS.items()}


# ---------------------------------------------------------------- helpers
def s(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return str(v).strip()


def num(v):
    try:
        f = float(v)
        return 0.0 if np.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def month_end(y, m):
    return dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)


def parse_periods(fname):
    """Return (start_date, end_date, financial_year, period_source)."""
    fy = ""
    m = re.search(r"F\.?\s?Y\.?\s*(\d{4})\s*-\s*(\d{2,4})", fname, re.I)
    if m:
        a, b = m.group(1), m.group(2)
        fy = f"{a}-{b[-2:]}"
    hits = []
    for mm in re.finditer(r"([A-Za-z]{3,12})\.?\s+(\d{4})", fname):
        key = mm.group(1)[:3].lower()
        if key in MONTHS:
            hits.append((MONTHS[key], int(mm.group(2))))
    if hits:
        st = dt.date(hits[0][1], hits[0][0], 1)
        em, ey = hits[-1]
        return st, month_end(ey, em), fy, "filename period"
    if fy:                                     # Indian FY = Apr..Mar
        y = int(fy.split("-")[0])
        return dt.date(y, 4, 1), month_end(y + 1, 3), fy, "derived from financial year"
    return None, None, fy, ""


def parse_filename(path):
    fn = os.path.basename(path)
    stem = os.path.splitext(fn)[0]
    n = int(re.search(r"\(S-(\d+)\)", fn).group(1))
    low = stem.lower()

    redis = "redistribution" in low
    runs = re.findall(r"\b([PM]\d{4})\b", stem)
    sub_code = ""
    mcode = re.search(r"\b([PM]\d{4}[A-Z]\d{3})\b", stem)
    if mcode:
        sub_code = mcode.group(1)
    if re.search(r"P\d{4}\s+to\s+P\d{4}", stem, re.I) and len(runs) >= 2:
        run = f"{runs[0]}–{runs[1]}"
    else:
        run = runs[0] if runs else ""

    soc_code = soc_name = soc_country = ""
    ms = re.search(r"(\d{3})\s+([A-Z]{2,10})\s*$", stem.strip())
    if ms and ms.group(1) in SOCIETIES:
        soc_code = ms.group(1)
        soc_name, soc_country = SOCIETIES[soc_code]

    sub = ""
    if redis:
        cat = "Redistribution"
    elif "mechanical" in low:
        cat = "Mechanical"
    elif "apple music" in low:
        cat = "Apple Music"
    elif "spotify" in low:
        cat = "Spotify"
    elif "youtube" in low and "pre" in low:
        cat = "YouTube Pre-Claims"
    elif "youtube" in low and "post" in low:
        cat = "YouTube Post-Claims"
    elif "facebook" in low or "meta" in low:
        cat = "Facebook/Meta"
    elif "radio" in low:
        cat = "Radio"
    elif "zee television" in low:
        cat = "Zee TV Broadcast"
    elif "overseas" in low:
        cat = "Overseas"
    else:
        cat = "Other / Unclassified"
    if "final liquidation" in low:
        sub = "Final Liquidation"
    elif "movie channel" in low:
        sub = "Movie Channels"
    elif cat == "Other / Unclassified" and sub_code:
        sub = sub_code
    if cat == "Overseas" and soc_name:
        sub = soc_name

    st, en, fy, psrc = parse_periods(stem)
    return dict(s_no=n, sheet=f"S-{n}", file=fn, run=run, dist_type="Redistribution" if redis else "Distribution",
                category=cat, sub=sub, p_start=st, p_end=en, fy=fy, p_src=psrc,
                soc_code=soc_code, soc=soc_name, soc_country=soc_country)


def norm_lang(v):
    t = s(v).upper().replace(" ", "")
    if t.startswith("BENGALI"):
        return "Bengali"
    if not t:
        return "(blank)"
    return s(v).title()


def period_label(md):
    if md["p_start"] is None:
        return "Unspecified"
    a, b = md["p_start"], md["p_end"]
    return f"{MONTH_LBL[a.month]} {a.year} - {MONTH_LBL[b.month]} {b.year}"


# ---------------------------------------------------------------- discover
paths = sorted(glob.glob(os.path.join(IN_DIR, "*.xlsx")),
               key=lambda p: int(re.search(r"\(S-(\d+)\)", os.path.basename(p)).group(1)))
print(f"Discovered {len(paths)} workbooks in {IN_DIR}")

catalog_path, money_paths = None, []
for p in paths:
    head = pd.read_excel(p, header=None, nrows=1)
    if s(head.iloc[0, 0]).lower() == "track name":
        catalog_path = p
    else:
        money_paths.append(p)
print(f"Catalog: {os.path.basename(catalog_path)}  |  money files: {len(money_paths)}")

# ---------------------------------------------------------------- extract
rows, validation, file_meta = [], [], []
for p in money_paths:
    md = parse_filename(p)
    xl = pd.ExcelFile(p)
    sheet = xl.sheet_names[0]
    df = pd.read_excel(p, sheet_name=sheet, header=None)
    hdr = [s(x).upper() for x in df.iloc[3].tolist()]
    schema = "Overseas" if ("RADIO" in hdr and "TV" in hdr) else "Standard"
    amt_col = 16 if schema == "Overseas" else 11

    member_int = s(df.iloc[0, 1])
    member_int = int(float(member_int)) if re.fullmatch(r"\d+(\.0+)?", member_int) else member_int
    member_ipi = s(df.iloc[0, 3])
    member_name = s(df.iloc[1, 1]).rstrip(",")
    member_base = s(df.iloc[1, 3])

    mask = df.apply(lambda r: r.astype(str).str.strip().eq("TOTAL ROYALTIES").any(), axis=1)
    tr_idx = int(df.index[mask][0])
    file_total = num(df.iloc[tr_idx, amt_col])

    # source-code <-> description map from the pool/source summary block
    code2desc, desc2code, code2pool = {}, {}, {}
    if schema == "Standard":
        for i in range(tr_idx, len(df)):
            if s(df.iloc[i, 0]).upper() == "POOL" and s(df.iloc[i, 2]).upper() == "SOURCE DESCRIPTION":
                for j in range(i + 1, len(df)):
                    code, desc, pool = s(df.iloc[j, 1]), s(df.iloc[j, 2]), s(df.iloc[j, 0])
                    if not code and not desc:
                        break
                    if code:
                        code2desc.setdefault(code, desc)
                        code2pool.setdefault(code, pool)
                    if desc:
                        desc2code.setdefault(desc, code)
                break

    det = df.iloc[4:tr_idx].copy()
    det.columns = range(df.shape[1])
    for c in (0, 1, 2, 3):                       # forward-fill work attributes FIRST
        det[c] = det[c].ffill()

    if schema == "Standard":
        keep = det[10].map(lambda v: s(v) != "")
    else:
        keep = (det[4].map(lambda v: s(v) != "") & det[5].map(lambda v: s(v) != "")
                & det[amt_col].map(lambda v: s(v) != ""))
    money = det[keep]

    extracted, n_lines = 0.0, 0
    for _, r in money.iterrows():
        amount = num(r[amt_col])
        pool = src_code = src_desc = ""
        usage = {k: None for k in ("Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others")}
        if schema == "Standard":
            pool = s(r[9])
            raw = s(r[10])
            if raw in code2desc:
                src_code, src_desc = raw, code2desc[raw]
            elif raw in desc2code:
                src_code, src_desc = desc2code[raw], raw
            else:
                src_code, src_desc = raw, ""
        else:
            for k, c in zip(usage, range(9, 16)):
                usage[k] = num(r[c])
        wid = s(r[0])
        try:
            wid = int(float(wid)) if wid else None
        except ValueError:
            wid = None
        rows.append(dict(
            **{"Source Sheet": md["sheet"], "Source File": md["file"], "Distribution Run": md["run"],
               "Distribution Type": md["dist_type"], "Revenue Category": md["category"],
               "Revenue Sub-Type": md["sub"], "Period Start": md["p_start"], "Period End": md["p_end"],
               "Financial Year": md["fy"], "Schema": schema,
               "Member Internal No": member_int, "Member Name": member_name,
               "Work Int No": wid, "Language": s(r[3]), "Line Name": s(r[4]).rstrip(","),
               "Role": s(r[5]), "Society": s(r[6]),
               "Own %": pd.to_numeric(s(r[7]), errors="coerce"),
               "Coll %": pd.to_numeric(s(r[8]), errors="coerce"),
               "Pool": pool, "Source Code": src_code, "Source Description": src_desc,
               "Overseas Society Code": md["soc_code"], "Overseas Society": md["soc"],
               "Overseas Country": md["soc_country"],
               "Statement Title": s(r[1]), "Period Label": period_label(md),
               "Royalty Amount": amount},
            **usage))
        extracted += amount
        n_lines += 1

    diff = extracted - file_total
    validation.append(dict(**{"Source Sheet": md["sheet"], "Source File": md["file"], "Schema": schema,
                              "Rows in File": int(df.shape[0]), "Lines Extracted": n_lines,
                              "Extracted Sum": extracted, "File TOTAL ROYALTIES": file_total,
                              "Difference": diff, "Result": "PASS" if abs(diff) <= TOL else "FAIL"}))
    file_meta.append(dict(md, schema=schema, member_int=member_int, member_name=member_name,
                          member_ipi=member_ipi, member_base=member_base, total=file_total,
                          lines=n_lines, period=period_label(md)))
    print(f"  {md['sheet']:<5} {schema:<8} lines={n_lines:<6} extracted={extracted:>14.4f} "
          f"file={file_total:>14.4f} diff={diff:>+9.4f} "
          f"{'PASS' if abs(diff) <= TOL else 'FAIL'}   {md['category']}")

master = pd.DataFrame(rows)
val = pd.DataFrame(validation).sort_values("Source Sheet", key=lambda c: c.str[2:].astype(int))

# ---------------------------------------------------------------- catalog + join
cat_raw = pd.read_excel(catalog_path, header=None, skiprows=1, names=["Track Name", "Internal NO", "ISRC"])
cat_raw["Raw Internal NO"] = cat_raw["Internal NO"].map(s)
cat_raw["Internal NO"] = pd.to_numeric(cat_raw["Internal NO"], errors="coerce").astype("Int64")
cat_raw["Track Name"] = cat_raw["Track Name"].map(s)
cat_raw["ISRC"] = cat_raw["ISRC"].map(s)
cat_rows_total = len(cat_raw)
cat_bad = cat_raw[cat_raw["Internal NO"].isna()][["Track Name", "Raw Internal NO", "ISRC"]].rename(
    columns={"Raw Internal NO": "Internal NO (as written)"})
cat_raw = cat_raw[cat_raw["Internal NO"].notna()].reset_index(drop=True)
print(f"Catalog rows={cat_rows_total} usable={len(cat_raw)} unusable-id rows={len(cat_bad)}")


def isrc_union(series):
    out = []
    for v in series:
        for part in str(v).split("|"):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return "|".join(out)


cat_lu = (cat_raw.groupby("Internal NO", sort=False)
          .agg(**{"Track Name": ("Track Name", "first"), "ISRC": ("ISRC", isrc_union),
                  "Catalog Rows": ("Track Name", "size")})
          .reset_index())

master["Work Int No"] = master["Work Int No"].astype("Int64")
master = master.merge(cat_lu[["Internal NO", "Track Name", "ISRC"]],
                      left_on="Work Int No", right_on="Internal NO", how="left").drop(columns=["Internal NO"])
master["In Catalog"] = np.where(master["Track Name"].notna(), "Yes", "No")
master["Track Name"] = master["Track Name"].fillna("")
master["ISRC"] = master["ISRC"].fillna("")
master["Display Title"] = np.where(master["Track Name"] != "", master["Track Name"], master["Statement Title"])
master["Language (Normalized)"] = master["Language"].map(norm_lang)
master["Royalty Amount"] = master["Royalty Amount"].astype(float)
master["Domestic/Overseas"] = np.where(master["Schema"] == "Overseas", "Overseas", "Domestic")

GRAND = master["Royalty Amount"].sum()
print(f"\nGrand total extracted: {GRAND:,.2f}   lines: {len(master):,}   "
      f"distinct works: {master['Work Int No'].nunique():,}")
print(val.groupby("Result").size().to_dict())

# ---------------------------------------------------------------- sheet frames
MASTER_COLS = ["Source Sheet", "Source File", "Distribution Run", "Distribution Type", "Revenue Category",
               "Revenue Sub-Type", "Period Start", "Period End", "Financial Year", "Schema",
               "Member Internal No", "Member Name", "Work Int No", "Track Name", "ISRC", "In Catalog",
               "Language", "Line Name", "Role", "Society", "Own %", "Coll %",
               "Pool", "Source Code", "Source Description",
               "Overseas Society Code", "Overseas Society",
               "Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others", "Royalty Amount"]
sheet1 = (master.sort_values(["Revenue Category", "Royalty Amount"], ascending=[True, False])
          [MASTER_COLS].copy())
sheet1["Royalty Amount"] = sheet1["Royalty Amount"].round(4)
for c in ("Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others"):
    sheet1[c] = pd.to_numeric(sheet1[c], errors="coerce").round(4)

# --- Sheet 3: Earnings per Song
def first_period(g):
    v = g.dropna()
    return min(v) if len(v) else None


def last_period(g):
    v = g.dropna()
    return max(v) if len(v) else None


song = (master.groupby("Work Int No", dropna=False)
        .agg(**{"Track Name": ("Display Title", "first"), "ISRC": ("ISRC", "first"),
                "In Catalog": ("In Catalog", "first"), "Language": ("Language (Normalized)", "first"),
                "Total Royalty": ("Royalty Amount", "sum"), "# Transactions": ("Royalty Amount", "size"),
                "# Revenue Categories": ("Revenue Category", "nunique"),
                "# Distribution Runs": ("Distribution Run", "nunique"),
                "First Period": ("Period Start", first_period), "Last Period": ("Period End", last_period)})
        .reset_index().sort_values("Total Royalty", ascending=False))
song = song[["Work Int No", "Track Name", "ISRC", "In Catalog", "Language", "Total Royalty",
             "# Transactions", "# Revenue Categories", "# Distribution Runs", "First Period", "Last Period"]]

# --- Sheet 4a: by category
cat_tbl = (master.groupby(["Revenue Category", "Revenue Sub-Type"], dropna=False)
           .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                   "# Transactions": ("Royalty Amount", "size")}).reset_index())
cat_tbl["% of Total"] = cat_tbl["Total Royalty"] / GRAND * 100
cat_tbl = cat_tbl.sort_values("Total Royalty", ascending=False)[
    ["Revenue Category", "Revenue Sub-Type", "Total Royalty", "% of Total", "# Works", "# Transactions"]]

cat_roll = (master.groupby("Revenue Category")
            .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                    "# Transactions": ("Royalty Amount", "size")}).reset_index())
cat_roll["% of Total"] = cat_roll["Total Royalty"] / GRAND * 100
cat_roll = cat_roll.sort_values("Total Royalty", ascending=False)[
    ["Revenue Category", "Total Royalty", "% of Total", "# Works", "# Transactions"]]

# --- Sheet 4b: by file / run
byfile = (master.groupby(["Source Sheet", "Source File", "Distribution Run", "Distribution Type",
                          "Revenue Category", "Revenue Sub-Type", "Period Label", "Schema",
                          "Member Internal No", "Member Name"], dropna=False)
          .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                  "# Transactions": ("Royalty Amount", "size")}).reset_index())
byfile["_n"] = byfile["Source Sheet"].str[2:].astype(int)
byfile = byfile.sort_values("_n").drop(columns=["_n"]).rename(columns={"Period Label": "Period"})
byfile = byfile[["Source Sheet", "Distribution Run", "Distribution Type", "Revenue Category",
                 "Revenue Sub-Type", "Period", "Schema", "Member Internal No", "Member Name",
                 "Total Royalty", "# Works", "# Transactions", "Source File"]]

# --- Sheet 4c: overseas by society
ovs = master[master["Schema"] == "Overseas"].copy()
soc_tbl = (ovs.groupby(["Overseas Society Code", "Overseas Society"], dropna=False)
           .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                   "# Transactions": ("Royalty Amount", "size"),
                   "Radio": ("Radio", "sum"), "TV": ("TV", "sum"), "Cinemas": ("Cinemas", "sum"),
                   "Permits": ("Permits", "sum"), "Demand": ("Demand", "sum"),
                   "General": ("General", "sum"), "Others": ("Others", "sum")}).reset_index())
soc_tbl["Country"] = soc_tbl["Overseas Society Code"].map(lambda c: SOCIETIES.get(c, ("", ""))[1])
soc_tbl = soc_tbl.sort_values("Total Royalty", ascending=False)[
    ["Overseas Society Code", "Overseas Society", "Country", "Total Royalty", "# Works", "# Transactions",
     "Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others"]]

# --- Sheet 5: per period
per = (master.groupby("Period Label", dropna=False)
       .agg(**{"Period Start": ("Period Start", first_period), "Period End": ("Period End", last_period),
               "Total Royalty": ("Royalty Amount", "sum"), "# Transactions": ("Royalty Amount", "size"),
               "# Works": ("Work Int No", "nunique"), "# Source Sheets": ("Source Sheet", "nunique")})
       .reset_index().rename(columns={"Period Label": "Period"}))
per["_k"] = per["Period Start"].map(lambda d: d if d else dt.date(9999, 1, 1))
per = per.sort_values("_k").drop(columns=["_k"])[
    ["Period", "Period Start", "Period End", "Total Royalty", "# Transactions", "# Works", "# Source Sheets"]]

master["Year"] = master["Period Start"].map(lambda d: d.year if d else None)
master["Quarter"] = master["Period Start"].map(lambda d: f"{d.year} Q{(d.month - 1) // 3 + 1}" if d else "Unspecified")
year_tbl = (master.groupby(master["Year"].map(lambda y: int(y) if y == y and y else "Unspecified"))
            .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Transactions": ("Royalty Amount", "size"),
                    "# Works": ("Work Int No", "nunique")}).reset_index()
            .rename(columns={"Year": "Period Start Year"}))
year_tbl.columns = ["Period Start Year", "Total Royalty", "# Transactions", "# Works"]
qtr_tbl = (master.groupby("Quarter")
           .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Transactions": ("Royalty Amount", "size"),
                   "# Works": ("Work Int No", "nunique")}).reset_index()
           .rename(columns={"Quarter": "Period Start Quarter"}))
qtr_tbl = qtr_tbl.sort_values("Period Start Quarter")

pivot_order = list(per["Period"])
matrix = (master.pivot_table(index="Revenue Category", columns="Period Label", values="Royalty Amount",
                             aggfunc="sum", fill_value=0.0))
matrix = matrix.reindex(columns=[c for c in pivot_order if c in matrix.columns])
matrix["TOTAL"] = matrix.sum(axis=1)
matrix = matrix.sort_values("TOTAL", ascending=False).reset_index()

# --- Sheet 6: duplicate songs
earn_by_id = master.groupby("Work Int No")["Royalty Amount"].sum()
dup_id = cat_raw.groupby("Internal NO").agg(
    **{"Track Name Variants": ("Track Name", lambda x: " | ".join(dict.fromkeys([v for v in x if v]))),
       "Distinct Track Names": ("Track Name", lambda x: len(set(v for v in x if v))),
       "Combined ISRCs": ("ISRC", isrc_union), "# Catalog Rows": ("Track Name", "size")}).reset_index()
dup_id = dup_id[dup_id["# Catalog Rows"] > 1].copy()
dup_id["Total Royalty"] = dup_id["Internal NO"].map(earn_by_id).fillna(0.0)
dup_id = dup_id.sort_values("Total Royalty", ascending=False).rename(columns={"Internal NO": "Internal No"})[
    ["Internal No", "Track Name Variants", "Distinct Track Names", "Combined ISRCs", "# Catalog Rows",
     "Total Royalty"]]

cat_raw["_tn"] = cat_raw["Track Name"].str.upper().str.strip()
dup_name = cat_raw[cat_raw["_tn"] != ""].groupby("_tn").agg(
    **{"Track Name": ("Track Name", "first"),
       "Internal Nos": ("Internal NO", lambda x: " | ".join(str(v) for v in dict.fromkeys(x))),
       "# Distinct Internal Nos": ("Internal NO", "nunique"), "# Catalog Rows": ("Internal NO", "size")}).reset_index()
dup_name = dup_name[dup_name["# Distinct Internal Nos"] > 1].copy()


def per_id_royalty(ids):
    parts, tot = [], 0.0
    for i in [int(x) for x in ids.split(" | ")]:
        amt = float(earn_by_id.get(i, 0.0))
        tot += amt
        parts.append(f"{i}={amt:,.2f}")
    return " | ".join(parts), tot


_pid = [per_id_royalty(v) for v in dup_name["Internal Nos"]]
dup_name["Royalty per Internal No"] = [a for a, _ in _pid]
dup_name["Combined Royalty"] = [b for _, b in _pid]
dup_name = dup_name.sort_values("Combined Royalty", ascending=False)[
    ["Track Name", "Internal Nos", "# Distinct Internal Nos", "# Catalog Rows",
     "Royalty per Internal No", "Combined Royalty"]]

# --- Sheet 7: unmatched works + dormant catalog
unm = master[master["In Catalog"] == "No"]
unmatched = (unm.groupby("Work Int No")
             .agg(**{"Title (as in statements)": ("Statement Title", "first"),
                     "Total Royalty": ("Royalty Amount", "sum"), "# Transactions": ("Royalty Amount", "size"),
                     "Revenue Categories": ("Revenue Category", lambda x: ", ".join(sorted(set(x)))),
                     "Source Sheets": ("Source Sheet", lambda x: ", ".join(sorted(set(x), key=lambda v: int(v[2:])))),
                     "Member": ("Member Name", lambda x: ", ".join(sorted(set(x)))),
                     "Language (as seen in statements)": ("Language", lambda x: ", ".join(sorted(set(v for v in x if v))))})
             .reset_index().sort_values("Total Royalty", ascending=False))
unmatched = unmatched[["Work Int No", "Title (as in statements)", "Total Royalty", "# Transactions",
                       "Revenue Categories", "Source Sheets", "Member", "Language (as seen in statements)"]]

earned_ids = set(master["Work Int No"].dropna().astype(int))
dormant = cat_lu[~cat_lu["Internal NO"].astype(int).isin(earned_ids)][
    ["Internal NO", "Track Name", "ISRC"]].rename(columns={"Internal NO": "Internal No"})
dormant = dormant.sort_values("Track Name")

# --- Sheet 8: overseas detail
ovs_det = ovs.copy()
ovs_det["Country"] = ovs_det["Overseas Society Code"].map(lambda c: SOCIETIES.get(c, ("", ""))[1])
ovs_det = ovs_det.sort_values(["Overseas Society", "Royalty Amount"], ascending=[True, False])[
    ["Source Sheet", "Distribution Run", "Overseas Society Code", "Overseas Society", "Country",
     "Period Label", "Work Int No", "Display Title", "In Catalog", "Language",
     "Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others", "Royalty Amount"]]
ovs_det = ovs_det.rename(columns={"Display Title": "Track Name", "Period Label": "Period"})

# ---------------------------------------------------------------- summary numbers
by_member = (master.groupby(["Member Internal No", "Member Name"])
             .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                     "# Transactions": ("Royalty Amount", "size"),
                     "# Source Sheets": ("Source Sheet", "nunique")}).reset_index()
             .sort_values("Total Royalty", ascending=False))
dom_ovs = (master.groupby("Domestic/Overseas")
           .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                   "# Transactions": ("Royalty Amount", "size")}).reset_index()
           .sort_values("Total Royalty", ascending=False))
dom_ovs["% of Total"] = dom_ovs["Total Royalty"] / GRAND * 100
dist_redis = (master.groupby("Distribution Type")
              .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                      "# Transactions": ("Royalty Amount", "size")}).reset_index()
              .sort_values("Total Royalty", ascending=False))
dist_redis["% of Total"] = dist_redis["Total Royalty"] / GRAND * 100
lang_tbl = (master.groupby("Language (Normalized)")
            .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                    "# Transactions": ("Royalty Amount", "size")}).reset_index()
            .sort_values("Total Royalty", ascending=False))
lang_tbl["% of Total"] = lang_tbl["Total Royalty"] / GRAND * 100
pool_tbl = (master[master["Schema"] == "Standard"].groupby(["Pool", "Source Code", "Source Description"])
            .agg(**{"Total Royalty": ("Royalty Amount", "sum"), "# Works": ("Work Int No", "nunique"),
                    "# Transactions": ("Royalty Amount", "size")}).reset_index()
            .sort_values("Total Royalty", ascending=False))
top15 = song.head(15)[["Work Int No", "Track Name", "In Catalog", "Total Royalty", "# Transactions",
                       "# Revenue Categories", "# Distribution Runs"]]

n_distinct_works = master["Work Int No"].nunique()
n_in_cat = master[master["In Catalog"] == "Yes"]["Work Int No"].nunique()
n_not_cat = master[master["In Catalog"] == "No"]["Work Int No"].nunique()
amt_not_cat = master[master["In Catalog"] == "No"]["Royalty Amount"].sum()
p_starts = [d for d in master["Period Start"] if d]
p_ends = [d for d in master["Period End"] if d]
overall_pass = (val["Result"] == "PASS").all()

# ---------------------------------------------------------------- write workbook
wb = Workbook()
BOLD = Font(bold=True)
FMT4, FMT2, FMTPCT, FMTINT, FMTDATE, FMTID = '#,##0.0000', '#,##0.00', '#,##0.00"%"', '#,##0', 'yyyy-mm-dd', '0'


def widths(ws, df, extra=2, cap=52):
    for i, col in enumerate(df.columns, start=1):
        vals = df[col].astype(str)
        w = max(len(str(col)), int(vals.str.len().quantile(0.95)) if len(vals) else 0,
                min(int(vals.str.len().max()) if len(vals) else 0, cap))
        ws.column_dimensions[get_column_letter(i)].width = min(max(w + extra, 9), cap)


def write_table(ws, df, start_row=1, money_cols=(), pct_cols=(), int_cols=(), date_cols=(), autofilter=True):
    for j, c in enumerate(df.columns, start=1):
        cell = ws.cell(row=start_row, column=j, value=str(c))
        cell.font = BOLD
    r = start_row + 1
    for _, row in df.iterrows():
        for j, c in enumerate(df.columns, start=1):
            v = row[c]
            if isinstance(v, (pd.Timestamp,)):
                v = v.date()
            if v is pd.NA or (isinstance(v, float) and np.isnan(v)):
                v = None
            if isinstance(v, np.integer):
                v = int(v)
            elif isinstance(v, np.floating):
                v = float(v)
            cell = ws.cell(row=r, column=j, value=v)
            if c in money_cols:
                cell.number_format = FMT2
            elif c in pct_cols:
                cell.number_format = FMTPCT
            elif c in ID_COLS:
                cell.number_format = FMTID
            elif c in int_cols:
                cell.number_format = FMTINT
            elif c in date_cols:
                cell.number_format = FMTDATE
        r += 1
    if autofilter and len(df):
        ws.auto_filter.ref = (f"A{start_row}:{get_column_letter(len(df.columns))}{r - 1}")
    return r


ID_COLS = {"Work Int No", "Internal No", "Member Internal No"}
MONEY = {"Total Royalty", "Royalty Amount", "Extracted Sum", "File TOTAL ROYALTIES", "Difference",
         "Combined Royalty", "Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others", "TOTAL"}
PCT = {"% of Total"}
INTS = {"# Transactions", "# Works", "# Revenue Categories", "# Distribution Runs", "# Catalog Rows",
        "# Distinct Internal Nos", "Distinct Track Names", "# Source Sheets", "Lines Extracted",
        "Rows in File", "Work Int No", "Internal No"}
DATES = {"Period Start", "Period End", "First Period", "Last Period"}

# Sheet 1
ws = wb.active
ws.title = "Master Data"
write_table(ws, sheet1,
            money_cols={"Royalty Amount", "Radio", "TV", "Cinemas", "Permits", "Demand", "General", "Others",
                        "Own %", "Coll %"},
            date_cols=DATES)
for j, c in enumerate(sheet1.columns, start=1):
    if c == "Royalty Amount":
        for row in ws.iter_rows(min_row=2, min_col=j, max_col=j):
            row[0].number_format = FMT4
widths(ws, sheet1, cap=40)
ws.freeze_panes = "A2"

# Sheet 2 - Summary
ws = wb.create_sheet("Summary")
r = 1


def put(text, row=None, col=1):
    global r
    rr = row or r
    ws.cell(row=rr, column=col, value=text)
    if row is None:
        r += 1
    return rr


def kv(k, v, fmt=None):
    global r
    ws.cell(row=r, column=1, value=k)
    c = ws.cell(row=r, column=2, value=v)
    if fmt:
        c.number_format = fmt
    r += 1


def block(title, df, money_cols=MONEY, pct_cols=PCT, int_cols=INTS, date_cols=DATES):
    global r
    put(title)
    r = write_table(ws, df, start_row=r, money_cols=money_cols, pct_cols=pct_cols,
                    int_cols=int_cols, date_cols=date_cols, autofilter=False)
    r += 1


put("SVF ROYALTY DISTRIBUTION - CONSOLIDATED SUMMARY")
kv("Generated", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
kv("Source folder", IN_DIR)
kv("Currency", "INR (assumed; not marked in source files)")
r += 1
put("HEADLINE TOTALS")
kv("Grand total royalty", float(GRAND), FMT2)
kv("Money files processed", len(money_paths))
kv("Catalog files processed", 1)
kv("Distribution runs", int(master["Distribution Run"].nunique()))
kv("Distinct works earning", int(n_distinct_works))
kv("Transaction lines", int(len(master)))
kv("Members", int(master["Member Internal No"].nunique()))
kv("Period coverage", f"{min(p_starts):%b %Y} to {max(p_ends):%b %Y}" if p_starts else "n/a")
kv("Overall validation", "PASS - every file reconciles to its TOTAL ROYALTIES" if overall_pass else "FAIL")
r += 1
block("BY MEMBER", by_member)
block("BY REVENUE CATEGORY", cat_roll)
block("BY REVENUE CATEGORY AND SUB-TYPE", cat_tbl)
block("DOMESTIC vs OVERSEAS", dom_ovs)
block("DISTRIBUTION vs REDISTRIBUTION", dist_redis)
block("BY LANGUAGE (normalized)", lang_tbl)

put("CATALOG COVERAGE (works that earned vs the S-46 April-2026 catalog)")
kv("Distinct works earning royalties", int(n_distinct_works))
kv("Found in catalog", int(n_in_cat))
kv("% found in catalog", round(n_in_cat / n_distinct_works * 100, 2), FMTPCT)
kv("NOT in catalog", int(n_not_cat))
kv("Royalty from works not in catalog", float(amt_not_cat), FMT2)
kv("% of grand total from works not in catalog", round(amt_not_cat / GRAND * 100, 4), FMTPCT)
kv("Catalog rows (S-46)", int(cat_rows_total))
kv("Catalog rows with an unusable Internal NO", int(len(cat_bad)))
kv("Distinct Internal Nos in catalog", int(cat_raw['Internal NO'].nunique()))
kv("Catalog Internal Nos with no earnings (dormant)", int(len(dormant)))
r += 1
block("TOP 15 EARNING SONGS", top15)
block("TOP 15 POOL / SOURCE (standard schema)", pool_tbl.head(15))
block("VALIDATION - per file (tolerance +/- 0.05)", val)
kv("OVERALL", "PASS" if overall_pass else "FAIL")
r += 1
put("NOTES AND ASSUMPTIONS")
for n_ in [
    "1. Currency assumed INR; no currency marker exists in the source files. No conversion applied.",
    "2. BENGALI and BENGALI(BANGLA) are the same language; both are grouped as 'Bengali'. Raw value kept in Master Data 'Language'.",
    "3. All aggregates are recomputed from detail rows. The in-file SUMMARY OF ROYALTY blocks are ignored for computation (S-45's block is internally inconsistent) and used only via TOTAL ROYALTIES for reconciliation.",
    "4. Money lines: Standard schema = rows with a non-empty SOURCE; Overseas schema = rows with NAME, ROLE and ROYALTY AMT all present. Work subtotal rows and blank rows are excluded, so no double counting.",
    "5. WORK INT NO / TITLE / AV / LANGUAGE are forward-filled down each work block before money lines are selected.",
    "6. S-2, S-3, S-4 and S-5 carry coded filenames only (P2107A008, P2109A008, P2527A001, P2530A001) with no revenue source in the name -> Revenue Category 'Other / Unclassified', code kept in Revenue Sub-Type. Their pools/sources (FRIENDS/KOLKATTA, INTERNET WEBSITE/MUSERK) suggest domestic mechanical origin; NOT assumed. USER ACTION: identify these four runs.",
    "7. S-44 and S-45 are redistributions (corrections) for runs P2101-P2550, tagged Distribution Type = Redistribution.",
    "8. S-32 belongs to a different member (SUSHANT, 8875288, role C) and includes a T-Series work. Member identity is a column; totals are given per member.",
    "9. S-1 has no month range in the filename, only F.Y. 2025-26; Period Start/End were derived as Apr 2025 - Mar 2026 (Indian financial year) so it can be placed on the period sheets.",
    "10. Source Code / Source Description are cross-mapped from each standard file's POOL/SOURCE/SOURCE DESCRIPTION block; detail rows carry sometimes the code and sometimes the description (e.g. KO128 vs KOLKATTA).",
    "11. Overseas society is taken from the filename code (Appendix B of the spec), not from the sheet; sheet names are unreliable (domestic files use the sheet name 'overseasMemberDetail').",
    "12. Master Data sort order: Revenue Category ascending, then Royalty Amount descending.",
    "13. Amounts are stored at full precision (displayed to 4 dp on Master Data, 2 dp elsewhere).",
    "14. One catalog row ('Ekakitwo - The Poem') carries the text 'NEED TO REGISTER' instead of an Internal NO, so it cannot be joined to earnings; it is listed in Unmatched Works table (c). USER ACTION: register that work and issue an Internal NO.",
    "15. Languages beyond the expected Bengali/Hindi appear in the statements (Marathi, Sanskrit, Santhali, Awadhi); they are carried through as-is.",
]:
    put(n_)
widths(ws, pd.DataFrame({0: ["x" * 62]}), extra=0)
ws.column_dimensions["A"].width = 62
for col in "BCDEFGHIJKLM":
    ws.column_dimensions[col].width = 18

# Sheets 3-8
def add(name, df, freeze="A2", start=1, cap=44):
    w = wb.create_sheet(name)
    write_table(w, df, start_row=start, money_cols=MONEY, pct_cols=PCT, int_cols=INTS, date_cols=DATES)
    widths(w, df, cap=cap)
    w.freeze_panes = freeze
    return w


add("Earnings per Song", song)

ws = wb.create_sheet("Earnings per Source")
ws.cell(row=1, column=1, value="(a) BY REVENUE CATEGORY AND SUB-TYPE")
r2 = write_table(ws, cat_tbl, start_row=2, money_cols=MONEY, pct_cols=PCT, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(b) BY DISTRIBUTION RUN / SOURCE SHEET (one row per money file)")
r2 = write_table(ws, byfile, start_row=r2 + 1, money_cols=MONEY, pct_cols=PCT, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(c) OVERSEAS BY SOCIETY (usage-type split)")
write_table(ws, soc_tbl, start_row=r2 + 1, money_cols=MONEY, pct_cols=PCT, int_cols=INTS, autofilter=False)
widths(ws, byfile, cap=46)

ws = wb.create_sheet("Earnings per Period")
ws.cell(row=1, column=1, value="(a) BY PERIOD")
r2 = write_table(ws, per, start_row=2, money_cols=MONEY, int_cols=INTS, date_cols=DATES, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(b) BY PERIOD-START YEAR")
r2 = write_table(ws, year_tbl, start_row=r2 + 1, money_cols=MONEY, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(c) BY PERIOD-START QUARTER")
r2 = write_table(ws, qtr_tbl, start_row=r2 + 1, money_cols=MONEY, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(d) REVENUE CATEGORY x PERIOD MATRIX")
write_table(ws, matrix, start_row=r2 + 1,
            money_cols=set(matrix.columns) - {"Revenue Category"}, autofilter=False)
widths(ws, per, cap=40)
for i in range(1, matrix.shape[1] + 1):
    ws.column_dimensions[get_column_letter(i)].width = max(
        ws.column_dimensions[get_column_letter(i)].width or 10, 22)

ws = wb.create_sheet("Duplicate Songs")
ws.cell(row=1, column=1, value="(a) SAME INTERNAL NO APPEARING ON MULTIPLE CATALOG ROWS")
r2 = write_table(ws, dup_id, start_row=2, money_cols=MONEY, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(b) SAME TRACK NAME MAPPED TO MULTIPLE INTERNAL NOS")
write_table(ws, dup_name, start_row=r2 + 1, money_cols=MONEY, int_cols=INTS, autofilter=False)
widths(ws, dup_name, cap=46)

ws = wb.create_sheet("Unmatched Works")
ws.cell(row=1, column=1, value="(a) WORKS THAT EARNED ROYALTIES BUT ARE NOT IN THE S-46 CATALOG")
r2 = write_table(ws, unmatched, start_row=2, money_cols=MONEY, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(b) DORMANT CATALOG - CATALOG WORKS WITH NO EARNINGS IN THIS CYCLE")
r2 = write_table(ws, dormant, start_row=r2 + 1, int_cols=INTS, autofilter=False) + 1
ws.cell(row=r2, column=1, value="(c) CATALOG ROWS THAT CANNOT BE JOINED - INTERNAL NO IS NOT A NUMBER")
write_table(ws, cat_bad, start_row=r2 + 1, autofilter=False)
widths(ws, unmatched, cap=46)

add("Overseas Detail", ovs_det)

os.makedirs(OUT_DIR, exist_ok=True)
wb.save(OUT_XLSX)
print(f"\nWrote {OUT_XLSX}")

val.to_csv(os.path.join(OUT_DIR, "validation_report.csv"), index=False)
print(val.to_string(index=False))
print("\nBy category:")
print(cat_roll.to_string(index=False))
print("\nBy member:")
print(by_member.to_string(index=False))
print(f"\nCatalog coverage: {n_in_cat}/{n_distinct_works} = {n_in_cat / n_distinct_works * 100:.1f}%  "
      f"not-in-catalog works={n_not_cat} amount={amt_not_cat:,.2f}")
print(f"Catalog rows={len(cat_raw)} distinct ids={cat_raw['Internal NO'].nunique()} dormant={len(dormant)}")
print("\nTop 10 songs:")
print(song.head(10).to_string(index=False))
