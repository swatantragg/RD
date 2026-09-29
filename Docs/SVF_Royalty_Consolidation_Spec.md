# SVF Royalty Distribution — Knowledge Base & Build Specification

**Purpose of this document.** This is a complete, cell-level description of a set of 46 royalty
spreadsheets, plus a precise specification for the Excel report you (Claude Code) must generate from
them. Read Part 1 to understand the data. Follow Part 2 to build the output. Part 3 is the exact
output layout. Part 4 lists parsing gotchas that will break the job if ignored. Appendix A is the
authoritative file-by-file catalog.

The end user wants: **(1) a consolidated master table of every royalty line across all sheets,
(2) analytical breakdowns — earnings per song, per source, per period, (3) a duplicate-songs
sheet, and (4) an overall summary that gives the best possible understanding of how the royalties
are distributed.** Output is a single `.xlsx`. Formatting must be plain (see §2.6).

---

## PART 1 — KNOWLEDGE BASE (what the data is)

### 1.1 The big picture

The 46 files are the **royalty book of a single music publisher** across roughly 20 distribution
runs. Concretely:

- **S-1 to S-43** are **royalty distribution statements**. 42 of them belong to one member —
  **SVF Entertainment Private Limited, Internal No `5154290`** (IPI Name No `00871526032`,
  IPI Base No `I-004791736-0`). Exactly **one file (S-32)** belongs to a *different* member,
  the composer **"SUSHANT", Internal No `8875288`**.
- **S-44 and S-45** are **royalty *re*distributions** — corrections/adjustments to earlier runs
  (filename says `Royalty_Redistribution`, run range `P2101 to P2550`). Same member (SVF). Same
  layout as the distribution statements.
- **S-46 is the master song catalog** — `SVF list of Song - April 2026`. This is the dimension
  table that resolves a work's ID to its track name and ISRC(s).

Each money file is a self-contained statement for one member, listing the works that earned, the
contributors on each work, and the amount that member collected — broken down by revenue
source (domestic files) or by usage type (overseas files).

The catalog is almost entirely **Bengali-language film music**; a few Hindi tracks appear
(e.g. the Sushant/T-Series work in S-32).

### 1.2 There are exactly TWO money-file schemas

Detect the schema **by inspecting the header row, not the sheet name** (the sheet name is
`overseasMemberDetail` for BOTH standard and overseas domestic exports — it is misleading; see §4.2).

#### Schema A — STANDARD (12 columns). Used for domestic, streaming, social, broadcast.

Header appears at **row index 3** (0-based). Exact column labels, in order:

| Col idx | Label | Meaning |
|---|---|---|
| 0 | `WORK INT NO` | Work internal number — the join key to the catalog (§1.4). Present only on the first row of each work block. |
| 1 | `TITLE` | Work title. First row of block only. |
| 2 | `AV` | Audio/Visual flag. Usually blank. |
| 3 | `LANGUAGE` | Language of the work. First row of block only. |
| 4 | `NAME` | Name of the contributor / rightsholder on this row. |
| 5 | `ROLE` | Role code (§1.3). |
| 6 | `SOCIETY` | Society affiliation of this contributor (e.g. `IPRS`, or numeric `036`, `099`, `000`). |
| 7 | `OWN` | Ownership share %. |
| 8 | `COLL` | Collectable share %. |
| 9 | `POOL` | Revenue pool this collection belongs to (e.g. `INTERNET WEBSITE`, `FRIENDS`). |
| 10 | `SOURCE` | Specific revenue source (a short code that ties to a description, e.g. `MUSERK JANUARY`, `KOLKATTA`, `APP10`, `FBI`). |
| 11 | `ROYALTY AMT` | The royalty amount for this line (and, on the subtotal line, the work total). |

#### Schema B — OVERSEAS (17 columns). Used for collections from foreign societies.

Header at **row index 3**. Sheet name is `MemberDetail`. The difference: columns 9–15 replace
POOL/SOURCE with a **usage-type split**, and column 16 is the total.

| Col idx | Label | Meaning |
|---|---|---|
| 0 | `WORK INT NO` | Same join key as above. |
| 1 | `TITLE` | Work title. |
| 2 | `AV` | Audio/Visual flag. |
| 3 | `LANGUAGE` | Language. |
| 4 | `NAME` | Contributor / rightsholder name. |
| 5 | `ROLE` | Role code. |
| 6 | `SOCIETY` | Society (usually `IPRS` for the member). |
| 7 | `OWN` | Ownership %. |
| 8 | `COLL` | Collectable %. |
| 9 | `RADIO` | Royalty from radio usage. |
| 10 | `TV` | Royalty from TV usage. |
| 11 | `CINEMAS` | Royalty from cinema usage. |
| 12 | `PERMITS` | Royalty from permits/licences. |
| 13 | `DEMAND` | Royalty from demand/on-request usage. |
| 14 | `GENERAL` | General/other performance royalty. |
| 15 | `OTHERS` | Other categories. |
| 16 | `ROYALTY AMT` | Total for the line (sum of cols 9–15). |

**Which society an overseas file is for is encoded in the filename**, not the header — e.g.
`058_SACEM`, `101_SOCAN`, `021_BMI`. See Appendix B for the full code→society map.

#### Schema C — MASTER CATALOG (S-46 only). 3 columns, sheet `Sheet1`.

Header at **row index 0**: `Track Name` | `Internal NO` | `ISRC`.
- `Internal NO` = the same value as `WORK INT NO` in the money files. **This is the join key.**
- `ISRC` may contain **multiple ISRCs pipe-delimited** (`|`) when a track has several recordings
  (e.g. `INS2X0700012|INE401001460|USQY52430516`).
- 2,762 song rows; **only ~2,570 are unique Internal NOs** — the catalog contains duplicates
  (versions/covers listed under different track names against the same or different IDs). See §1.6.

### 1.3 Field vocabulary

**Role codes (`ROLE`):**
- `C` = Composer
- `A` = Author / Lyricist
- `CA` = Composer-Author (same person wrote both music and words)
- `E` = Original Publisher — **this is SVF's role on almost every line; the publisher is who
  collects the money.** (On the Sushant statement, the member's role is `C`, not `E`.)

**Key principle:** a statement is written *for* one member. The member is named in the header
(rows 0–1). Only the rows carrying **that member's own name** hold money that this member
collected. Other-contributor rows (the composers/authors on the same work) show shares but carry
**no royalty to this member** (their `ROYALTY AMT` / usage cells are blank or `0`). See §2.3 for
how to extract money lines reliably.

**Society (`SOCIETY`) values seen:** `IPRS` (Indian Performing Right Society — the member's home
society), and numeric society codes such as `036`, `099`, `000`, plus foreign societies in the
overseas files (mapped in Appendix B). Treat this as a free-text/categorical field.

**Pool (`POOL`) values seen:** `INTERNET WEBSITE`, `INT`, `FRIENDS`, `FRI`. (Codes and their
expanded forms both appear across files — treat as categorical.)

**Source (`SOURCE`) examples:** `MUSERK JANUARY/APRIL/JULY/OCTOBER` (mechanical feeds),
`APP10` (Apple), `FBI` (Facebook), `KO128`/`KOLKATTA`, `3511J`/`3512`/`3513` (SVF monthly YouTube
feeds), plus sub-label feeds like `SURINDER FILMS`, `GRASSROOT ENTERTAINMENT`, `VIRGIN RECORDS`,
`KAUZALA MUSIC`, `TSERIES MUSIC`. The `SOURCE DESCRIPTION` (a longer label) appears in the
pool/source summary block at the bottom of each standard file.

**Language (`LANGUAGE`) values:** predominantly `BENGALI(BANGLA)` and `BENGALI` (note: these two
strings are used inconsistently and should be treated as the same language for grouping — see §4.5);
a few `HINDI`.

### 1.4 The join: money files ↔ catalog

`money_file.WORK INT NO` == `catalog.Internal NO`. Join every extracted royalty line to S-46 on
this key to attach `Track Name` and `ISRC`. Because the catalog has duplicate Internal NOs,
**deduplicate the catalog before joining** (keep the first Track Name and concatenate distinct
ISRCs, or keep first — see §2.4). Every joined line must carry an **`In Catalog` = Yes/No** flag.

**Known coverage gap (important, surface it in the report):** across all money files there are
**2,117 distinct Work Int Nos**; only **1,787 (84.4%)** are found in the S-46 catalog. **330 works
that earned royalties are NOT in the April-2026 catalog.** Some are non-SVF works (e.g. the T-Series
work on the Sushant statement); others may be genuine catalog omissions. The report must list these
(see §3, Sheet "Unmatched Works").

### 1.5 Anatomy of a money file (row-by-row), with the block structure

Every money file has the same five-section vertical layout. Using row indices from a typical file:

```
Row 0:  INTERNAL NO | <id>        | IPI NAME NO | <ipi>          ...   <- member header line 1
Row 1:  NAME        | <member>    | IPI BASE NO | <base>         ...   <- member header line 2
Row 2:  (blank)
Row 3:  <COLUMN HEADER ROW>  (Schema A or B, see §1.2)
Row 4+: <WORK BLOCKS>  (detail — see below)
        ...
        <row where col 6 == "TOTAL ROYALTIES", with the grand total in the amount column>
        (blank)
        SUMMARY OF ROYALTY
        LANGUAGE | NO. OF WORKS | ROYALTY AMT   <- language summary block
        <one row per language> ... then a totals row
        (blank)
        POOL | SOURCE | SOURCE DESCRIPTION | ... | NO. OF WORKS | ... | ROYALTY AMT
        <one row per pool/source> ... then a totals row   <- (this block differs slightly in overseas files)
```

**A "work block" (the detail rows) looks like this (Schema A example):**

```
WORKNO | TITLE      |   | LANG | COMPOSER NAME  | C  | 036 | 25 | 25 |                  |               |          <- contributor, NO money
       |            |   |      | AUTHOR NAME    | A  | 036 | 25 | 25 |                  |               |          <- contributor, NO money
       |            |   |      | <MEMBER NAME>  | E  | 036 | 50 | 50 | INTERNET WEBSITE | MUSERK JANUARY | 2.5893   <- MEMBER money line
       |            |   |      | <MEMBER NAME>  | E  | 036 | 50 | 50 | INTERNET WEBSITE | MUSERK APRIL   | 26.8148  <- MEMBER money line (another source)
       |            |   |      |                |    |     |    |    |                  |               | 29.4041  <- WORK SUBTOTAL (only amount filled)
(blank row separates works)
```

Notes on the block:
- **`WORK INT NO`, `TITLE`, `AV`, `LANGUAGE` appear only on the first physical row of the block.**
  They must be **forward-filled down** to every row of that work before you can use them.
- The **money lines are the member's own rows.** In Schema A they are the rows that have a
  non-empty `SOURCE` (col 10) — one line per pool/source the member collected from. In Schema B
  they are the member's role line carrying the usage-type split.
- The **subtotal row** has the amount but **no `NAME` / `ROLE` / `SOURCE`** — it repeats the sum of
  the block's money lines. **Do not ingest subtotal rows as transactions** (that would double-count).
- A blank row separates consecutive works.

### 1.6 Duplicates & data quirks (the report must expose these)

1. **Catalog duplicates.** 2,762 catalog rows vs ~2,570 unique Internal NOs. Same track can appear
   multiple times (covers, reprises, versions, re-uploads). Sometimes the *same* Track Name maps to
   *different* Internal NOs, and sometimes the *same* Internal NO appears on multiple rows with
   different names. Both must be reported (Sheet "Duplicate Songs", §3).
2. **`BENGALI` vs `BENGALI(BANGLA)`** — two spellings for one language. Normalize for grouping.
3. **Language-summary count discrepancies.** At least one redistribution file (S-45) reports a work
   count in its summary block that doesn't match the number of works in its own detail. Treat the
   **detail rows as the source of truth**; do not trust the pre-computed summary blocks — recompute
   everything yourself and cross-check against `TOTAL ROYALTIES`.
4. **Societies repeat across runs.** SACEM, SOCAN, MACP each appear in 2–3 different distribution
   runs covering different periods. This is legitimate (different periods), **not** duplication.
   Key any run-level grouping on run + society + period so nothing is merged incorrectly.
5. **One non-SVF member (S-32).** Keep member identity as a column; do not assume all rows are SVF.
6. **Pool/Source codes vs expanded names** both occur (`INT` vs `INTERNET WEBSITE`, `FRI` vs
   `FRIENDS`, `KO128` vs `KOLKATTA`). Treat as categorical; do not attempt to force-merge unless
   obviously identical.

---

## PART 2 — WHAT TO BUILD (processing logic)

### 2.1 Input

A directory (path supplied at run time) containing the 46 `.xlsx` files. Filenames follow the
pattern `_S-<n>_<description>.xlsx`. **Parse `<n>` from the filename** to identify each sheet;
S-46 is the catalog, everything else is a money file (S-44/S-45 are redistributions).

Do **not** hard-code the list — glob `_S-*.xlsx`, sort numerically by the S-number, and classify
each by reading it (see §2.2). The logic must survive new files being added next cycle.

### 2.2 Per-file classification

For each money file:
1. Read with **pandas** (`pd.read_excel(path, header=None)`) — **not** openpyxl read-only (see §4.1).
2. Member header: `Internal No = iloc[0,1]`, `IPI Name No = iloc[0,3]`, `Member Name = iloc[1,1]`,
   `IPI Base No = iloc[1,3]`.
3. Schema: read row index 3; if it contains `RADIO` and `TV` → **Overseas (B)**; else → **Standard (A)**.
4. `TOTAL ROYALTIES`: find the row where any cell equals `TOTAL ROYALTIES`; the numeric value in
   that row is the file's grand total. **Use this as a validation control (see §2.5).**
5. From the **filename**, derive: Distribution Run code, Distribution Type, Revenue Category,
   Period, and (overseas only) Society code + name. See §2.7 and Appendices A/B.

### 2.3 Extracting transaction (money) lines — the core step

For each money file, isolate the **detail region**: rows strictly between the header row (idx 3)
and the `TOTAL ROYALTIES` row. Then:

1. **Forward-fill** `WORK INT NO`, `TITLE`, `AV`, `LANGUAGE` down the detail region so every row
   knows its parent work.
2. **Select money lines by schema:**
   - **Standard (A):** keep rows where `SOURCE` (col 10) is non-empty. These carry
     `POOL`, `SOURCE`, `ROYALTY AMT`, plus the member's `NAME/ROLE/SOCIETY/OWN/COLL`. This
     cleanly excludes contributor rows (empty SOURCE) and subtotal rows (empty SOURCE).
   - **Overseas (B):** keep rows where `ROYALTY AMT` (col 16) is non-empty **and** `NAME` (col 4)
     is non-empty **and** `ROLE` (col 5) is non-empty. This is the member's earning line and
     excludes the subtotal row (no NAME/ROLE). Capture the seven usage-type columns individually.
     *(Contributor lines that happen to carry 0 will net to zero and are harmless, but prefer to
     also require the member-name match if available.)*
3. **Discard subtotal rows and blank rows** (they have no NAME/ROLE and, in Schema A, no SOURCE).
4. Each surviving row becomes **one row in the consolidated master table**, tagged with all the
   file-level metadata from §2.2.

### 2.4 Join to catalog

1. Load S-46. Coerce `Internal NO` to integer.
2. Build a dedup lookup: for each `Internal NO`, keep one `Track Name` (first occurrence) and the
   set of distinct ISRCs joined by `|` (union across duplicate rows).
3. Left-join every transaction row on `WORK INT NO == Internal NO`. Populate `Track Name`,
   `ISRC`, and `In Catalog` = Yes if matched else No.
4. For unmatched works, `Track Name` = blank (or `NOT IN CATALOG`), `In Catalog` = No.

### 2.5 Validation (mandatory — do this and report the result)

The pre-computed totals in the files are the ground truth for reconciliation:
- For **each file**, `sum(extracted ROYALTY AMT) must equal that file's TOTAL ROYALTIES`
  (allow ±0.05 rounding tolerance).
- Optionally, per work: `sum(money lines) == subtotal row`.
- Record, per file: extracted sum, file total, difference, PASS/FAIL. Put this in a
  "Validation" section of the Summary sheet (or its own sheet). **If any file fails, the
  extraction rule for that schema is wrong — do not silently ship mismatched numbers.**

Expected grand totals to sanity-check against (currency assumed INR, unmarked):
- Member **5154290 (SVF)** across all its statement + redistribution files: **≈ 3,209,892.26**
- Member **8875288 (Sushant)**: **53.47**

### 2.6 Output formatting rules (strict)

- **Only the column-header row is bold.** Nothing else is bold.
- **No fill colors, no font colors, no cell shading, no conditional formatting, no banding.**
  Plain black text on default background throughout.
- Permitted (non-color) niceties: freeze the header row, enable an autofilter on header rows,
  auto-fit / sensible column widths, and number formatting (thousands separator + 2 decimals for
  display amounts). Keep it minimal.
- Amounts: preserve full numeric precision in the master data sheet (round to 4 dp); display 2 dp
  in the analytical/summary sheets. Do not convert currency.
- One workbook, multiple sheets (§3). Sheet order as listed. Use clear sheet names.

### 2.7 Deriving metadata from filenames

- **S-number:** regex `_S-(\d+)_`.
- **Distribution Run:** the `P####`/`M####` code (e.g. `P2550`, `M2506`). Redistributions carry a
  range (`P2101 to P2550`) — set Run = `P2101–P2550` and Distribution Type = `Redistribution`.
  All others: Distribution Type = `Distribution`.
- **Revenue Category** (classify from filename keywords; see Appendix A for the resolved value per file):
  - contains `Mechanical` → **Mechanical**
  - contains `Apple Music` → **Apple Music**
  - contains `Spotify` → **Spotify**
  - contains `YouTube` + `Pre` → **YouTube Pre-Claims**
  - contains `YouTube` + `Post` → **YouTube Post-Claims** (if also `Final Liquidation`, set
    Sub-Type = `Final Liquidation`)
  - contains `Facebook` or `Meta` → **Facebook/Meta**
  - contains `Radio` → **Radio**
  - contains `Zee Television` → **Zee TV Broadcast** (Sub-Type `Movie Channels` if present)
  - contains `Overseas` → **Overseas** (attach society from Appendix B)
  - **S-2/S-3/S-4/S-5** have coded names only (`P2107A008`, `P2109A008`, `P2527A001`, `P2530A001`)
    with no descriptive source → **Other / Unclassified**. Flag these for the user to identify;
    their pool/source values (`INTERNET WEBSITE`/`MUSERK…`, `FRIENDS`/`KOLKATTA`) hint at
    mechanical/domestic origin but do not assume.
- **Period:** parse `Month YYYY to Month YYYY` (or a single `Month YYYY`) into `Period Start` /
  `Period End` dates. Capture `Financial Year` when `F Y YYYY-YY` appears. Leave blank when the
  filename has no period. Derive `Year` and `Quarter` where a clean period exists (for the
  per-period sheet).

---

## PART 3 — OUTPUT WORKBOOK LAYOUT (exact sheets & columns)

Produce ONE `.xlsx` with the following sheets, in this order.

### Sheet 1 — `Master Data` (transaction level; the heart of the deliverable)
One row per extracted royalty line. Columns (header row bold; this order):

`Source Sheet` · `Source File` · `Distribution Run` · `Distribution Type` · `Revenue Category` ·
`Revenue Sub-Type` · `Period Start` · `Period End` · `Financial Year` · `Schema` ·
`Member Internal No` · `Member Name` · `Work Int No` · `Track Name` · `ISRC` · `In Catalog` ·
`Language` · `Line Name` · `Role` · `Society` · `Own %` · `Coll %` ·
`Pool` · `Source Code` · `Source Description` ·
`Overseas Society Code` · `Overseas Society` ·
`Radio` · `TV` · `Cinemas` · `Permits` · `Demand` · `General` · `Others` ·
`Royalty Amount`

- Standard-only columns (`Pool`, `Source Code`, `Source Description`) are blank for overseas rows.
- Overseas-only columns (`Overseas Society…` and the seven usage columns) are blank for standard rows.
- `Source Description` for standard rows can be looked up from that file's pool/source summary block,
  or left as the raw source value if the description is not readily resolvable.
- Sort by `Revenue Category`, then `Royalty Amount` descending (or by Member, then Work — your call;
  document the choice in the Summary).

### Sheet 2 — `Summary` (the overall picture / dashboard, text + small tables)
Include, clearly labelled:
- **Headline totals:** grand total royalty; total by member (SVF vs Sushant); number of files
  processed, distribution runs, distinct works, transaction lines.
- **By Revenue Category:** a table of Category → Total Amount, % of grand total, # distinct works,
  # transaction lines. Sort descending by amount. (Expected shape: YouTube ≈ 58%, Facebook/Meta
  ≈ 27%, then Spotify, Radio, Mechanical, Zee TV, Apple, Overseas ≈ <1%.)
- **Domestic vs Overseas** split (amount + %).
- **Distribution vs Redistribution** split.
- **Catalog coverage:** distinct works earning, # and % found in catalog, # and amount from works
  NOT in catalog.
- **Top 15 earning songs** (Track Name / Work Int No / total / category count).
- **Period range** covered (earliest Period Start to latest Period End).
- **Validation results** (per §2.5): a compact table of file → extracted sum vs file total vs
  diff vs PASS/FAIL, and a single overall PASS/FAIL line.
- **Notes/assumptions:** currency assumed INR; `BENGALI`==`BENGALI(BANGLA)`; the 4 unclassified
  P-runs; summary blocks recomputed from detail; etc.

### Sheet 3 — `Earnings per Song`
One row per `Work Int No` (aggregated across ALL files):
`Work Int No` · `Track Name` · `ISRC` · `In Catalog` · `Language` · `Total Royalty` ·
`# Transactions` · `# Revenue Categories` · `# Distribution Runs` · `First Period` · `Last Period`
Sorted by `Total Royalty` descending. This is the primary analytical table.

### Sheet 4 — `Earnings per Source`
Two stacked tables (label each):
- **(a) By Revenue Category:** Category · Sub-Type · Total Royalty · % of total · # Works · # Transactions.
- **(b) By Distribution Run / Sheet:** Source Sheet · Distribution Run · Distribution Type ·
  Revenue Category · Period · Member · Total Royalty · # Works. (One row per money file — mirrors
  Appendix A, but computed from the data.)
Optionally **(c) Overseas by Society:** Society Code · Society · Country · Total Royalty ·
# Works · and the usage-type totals (Radio/TV/Cinemas/Permits/Demand/General/Others).

### Sheet 5 — `Earnings per Period`
Group by normalized period. Provide:
- Period (or Year, and Year×Quarter where derivable) · Total Royalty · # Transactions · # Works.
- Plus a **Category × Period** matrix if feasible (categories as rows, periods as columns, amounts
  in cells) — this shows how each revenue stream moves over time. Where periods can't be parsed
  from a filename, bucket as `Unspecified`.

### Sheet 6 — `Duplicate Songs`
Expose catalog duplication (from S-46, cross-referenced with earnings). Include both kinds:
- **Same Internal NO, multiple catalog rows:** `Internal No` · list of distinct `Track Name`
  variants · combined distinct `ISRC`s · `# Catalog Rows` · `Total Royalty` (from Master Data).
- **Same Track Name, multiple Internal NOs:** `Track Name` · list of `Internal No`s · per-ID
  royalty · combined royalty.
Sort by combined royalty descending, so the highest-value consolidation candidates are on top.

### Sheet 7 — `Unmatched Works` (catalog reconciliation)
The works that earned royalties but are **not** in the S-46 catalog:
`Work Int No` · `Total Royalty` · `# Transactions` · `Revenue Categories (list)` ·
`Member` · `Language (as seen in statements)`.
Sorted by `Total Royalty` descending. (Optionally add a second table: catalog songs that earned
**nothing** this cycle — dormant catalog — `Internal No` · `Track Name` · `ISRC`.)

### Sheet 8 — `Overseas Detail` (optional but recommended)
Every overseas transaction with its full usage split, for auditing the 17-column data:
`Source Sheet` · `Society Code` · `Society` · `Country` · `Work Int No` · `Track Name` ·
`Language` · `Radio` · `TV` · `Cinemas` · `Permits` · `Demand` · `General` · `Others` ·
`Royalty Amount`.

---

## PART 4 — PARSING GOTCHAS (read before coding; these will bite)

### 4.1 openpyxl read-only reports wrong dimensions
These files were exported by a non-Excel system and omit/mis-set the dimension record. openpyxl in
`read_only=True` mode reports **1×1** for every sheet and `iter_rows` yields nothing useful. **Use
pandas `read_excel` (header=None)** for reading, or openpyxl with `read_only=False`. For *writing*
the output, openpyxl (or pandas + xlsxwriter/openpyxl engine) is fine.

### 4.2 The sheet name lies about the schema
Standard domestic files use sheet name `overseasMemberDetail` (yes, "overseas" even though they're
domestic). Overseas files use `MemberDetail`. The master uses `Sheet1`. **Never** infer schema from
the sheet name — infer it from the header row (presence of `RADIO`/`TV`) or the column count
(12 vs 17).

### 4.3 Header is on row index 3, not row 0
Rows 0–1 are the member header; row 2 is blank; row 3 is the column header; data starts at row 4.
Read with `header=None` and slice by position.

### 4.4 Forward-fill work attributes before filtering
`WORK INT NO`/`TITLE`/`LANGUAGE` are only on the first row of each work block. If you filter to
money lines *before* forward-filling, most rows lose their work identity. Fill first, filter second.

### 4.5 Normalize `BENGALI` / `BENGALI(BANGLA)`
Map both to a single `Bengali` label for all grouping/aggregation. Preserve the raw value in the
Master Data `Language` column if you like, but group on the normalized one.

### 4.6 Recompute everything; don't trust in-file summary blocks
Each file contains its own language and pool/source summary blocks at the bottom. At least one file
(S-45) has an internally inconsistent count. Ignore these blocks for computation — **derive all
aggregates from the detail rows** and reconcile only against `TOTAL ROYALTIES`.

### 4.7 Numeric coercion
`WORK INT NO` / `Internal NO` should be coerced to a nullable integer for a clean join (values are
large integers). Royalty amounts are floats with varying precision (some are exact 4-dp, some are
long division results). Do not round during aggregation; round only for display.

### 4.8 Don't ingest subtotal or blank rows
Subtotal rows carry an amount but no NAME/ROLE (and, in Schema A, no SOURCE). Ingesting them
double-counts. The §2.3 selection rules already exclude them — just don't loosen those rules.

---

## APPENDIX A — Authoritative file catalog (verified)

`Schema`: STD = standard 12-col, OVS = overseas 17-col, CAT = catalog.
`Total` is that file's `TOTAL ROYALTIES` (INR assumed). All members are `5154290` (SVF) except S-32.

| Sheet | Run | Revenue Category | Society (overseas) | Schema | Rows | Member | Total |
|---|---|---|---|---|---:|---|---:|
| S-1 | M2506 | Mechanical | — | STD | 3765 | 5154290 | 82,769.64 |
| S-2 | P2101→P2540 (P2107A008) | Other / Unclassified | — | STD | 22 | 5154290 | 11.60 |
| S-3 | P2101→P2540 (P2109A008) | Other / Unclassified | — | STD | 57 | 5154290 | 16.29 |
| S-4 | P2101→P2540 (P2527A001) | Other / Unclassified | — | STD | 100 | 5154290 | 590.45 |
| S-5 | P2101→P2540 (P2530A001) | Other / Unclassified | — | STD | 80 | 5154290 | 26,160.35 |
| S-6 | P2533 | Apple Music | — | STD | 3615 | 5154290 | 9,685.91 |
| S-7 | P2535 | Overseas | 058 SACEM (France) | OVS | 502 | 5154290 | 54.77 |
| S-8 | P2536 | YouTube Post-Claims | — | STD | 321 | 5154290 | 48,709.34 |
| S-9 | P2540 | Radio | — | STD | 1371 | 5154290 | 120,935.11 |
| S-10 | P2543 | Facebook/Meta | — | STD | 8168 | 5154290 | 262,315.02 |
| S-11 | P2546 | Zee TV Broadcast | — | STD | 219 | 5154290 | 36,956.25 |
| S-12 | P2549 | YouTube Post-Claims | — | STD | 174 | 5154290 | 8,818.87 |
| S-13 | P2550 | YouTube Pre-Claims | — | STD | 3802 | 5154290 | 766,455.06 |
| S-14 | P2552 | YouTube Pre-Claims | — | STD | 197 | 5154290 | 13,510.35 |
| S-15 | P2554 | YouTube Post-Claims | — | STD | 177 | 5154290 | 96,982.31 |
| S-16 | P2555 | Overseas | 026 CASH (Hong Kong) | OVS | 46 | 5154290 | 10.26 |
| S-17 | P2555 | Overseas | 101 SOCAN (Canada) | OVS | 194 | 5154290 | 236.24 |
| S-18 | P2555 | Overseas | 104 MACP (Malaysia) | OVS | 22 | 5154290 | 22.86 |
| S-19 | P2555 | Overseas | 128 IMRO (Ireland) | OVS | 230 | 5154290 | 25.46 |
| S-20 | P2558 | YouTube Post-Claims | — | STD | 33 | 5154290 | 567.06 |
| S-21 | P2559 | Apple Music | — | STD | 4980 | 5154290 | 12,319.94 |
| S-22 | P2565 | Zee TV Broadcast (Movie Channels) | — | STD | 111 | 5154290 | 3,626.65 |
| S-23 | P2566 | Zee TV Broadcast | — | STD | 209 | 5154290 | 23,729.82 |
| S-24 | P2567 | Spotify | — | STD | 4560 | 5154290 | 140,883.01 |
| S-25 | P2570 | Overseas | 021 BMI (USA) | OVS | 1450 | 5154290 | 1,912.18 |
| S-26 | P2570 | Overseas | 058 SACEM (France) | OVS | 1489 | 5154290 | 627.26 |
| S-27 | P2570 | Overseas | 101 SOCAN (Canada) | OVS | 205 | 5154290 | 2.29 |
| S-28 | P2570 | Overseas | 104 MACP (Malaysia) | OVS | 58 | 5154290 | 55.31 |
| S-29 | P2570 | Overseas | 106 COMPASS (Singapore) | OVS | 132 | 5154290 | 0.27 |
| S-30 | P2571 | YouTube Pre-Claims | — | STD | 3931 | 5154290 | 862,273.04 |
| S-31 | P2577 | YouTube Post-Claims | — | STD | 122 | 5154290 | 77,322.51 |
| S-32 | P2577 | YouTube Post-Claims | — | STD | 22 | **8875288** | 53.47 |
| S-33 | P2578 | Facebook/Meta | — | STD | 10268 | 5154290 | 278,686.48 |
| S-34 | P2580 | Overseas | 058 SACEM (France) | OVS | 1318 | 5154290 | 211.20 |
| S-35 | P2580 | Overseas | 104 MACP (Malaysia) | OVS | 61 | 5154290 | 148.63 |
| S-36 | P2580 | Overseas | 008 APRA (Australia) | OVS | 38 | 5154290 | 121.63 |
| S-37 | P2580 | Overseas | 023 BUMA (Netherlands) | OVS | 369 | 5154290 | 0.41 |
| S-38 | P2580 | Overseas | 080 SUISA (Switzerland) | OVS | 206 | 5154290 | 1.23 |
| S-39 | P2580 | Overseas | 101 SOCAN (Canada) | OVS | 182 | 5154290 | 4.53 |
| S-40 | P2580 | Overseas | 126 MCT (Thailand) | OVS | 383 | 5154290 | 0.32 |
| S-41 | P2580 | Overseas | 128 IMRO (Ireland) | OVS | 241 | 5154290 | 27.02 |
| S-42 | P2582 | YouTube Post-Claims (Final Liquidation) | — | STD | 26 | 5154290 | 1,724.54 |
| S-43 | P2583 | Facebook/Meta | — | STD | 10960 | 5154290 | 328,884.15 |
| S-44 | P2101→P2550 | Redistribution | — | STD | 24 | 5154290 | 60.73 |
| S-45 | P2101→P2550 | Redistribution | — | STD | 28 | 5154290 | 2,435.92 |
| S-46 | — | **Master Catalog** (2,762 songs) | — | CAT | 2763 | — | — |

**Period notes:** most filenames carry an explicit period (e.g. S-9 = Apr 2023–Mar 2025,
S-10 = Oct 2024–Mar 2025, S-13 = Jul 2025–Sep 2025, S-30 = Oct 2025–Dec 2025, S-33/S-43 =
Apr–Jun / Jul–Sep 2025). S-1 references FY 2025-26. S-2 to S-5 have no period in the filename.

## APPENDIX B — Overseas society code → society → country (seen in this set)

| Code | Society | Country |
|---|---|---|
| 008 | APRA | Australia |
| 021 | BMI | USA |
| 023 | BUMA | Netherlands |
| 026 | CASH | Hong Kong |
| 058 | SACEM | France |
| 080 | SUISA | Switzerland |
| 101 | SOCAN | Canada |
| 104 | MACP | Malaysia |
| 106 | COMPASS | Singapore |
| 126 | MCT | Thailand |
| 128 | IMRO | Ireland |

(If a new society code appears next cycle, map it from the standard CISAC society-code list and add
it here.)

## APPENDIX C — Expected top earners (sanity check for the finished report)

Per-file, the largest statements are: S-30 YouTube Pre-Claims (862K), S-13 YouTube Pre-Claims
(766K), S-43 Meta (329K), S-33 Facebook (279K), S-10 Facebook (262K), S-24 Spotify (141K),
S-9 Radio (121K), S-15 YouTube Post (97K), S-1 Mechanical (83K), S-31 YouTube Post (77K).
If the finished `Earnings per Source` sheet doesn't broadly reflect this, the extraction is off.

---

*End of specification. Build the workbook exactly as laid out in Part 3, following the logic in
Part 2 and the cautions in Part 4. When done, print the validation table (§2.5) so the user can
confirm every file reconciled.*
