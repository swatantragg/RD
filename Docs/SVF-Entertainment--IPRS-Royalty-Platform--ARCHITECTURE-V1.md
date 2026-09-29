# SVF Royalty Distribution Platform — Complete Architecture

> Build-from-scratch specification for the system that turns raw IPRS royalty statements,
> a song catalogue and Spotify's own reports into **SVF-RD-SKV7** (the master royalty
> distribution workbook), the **Song-ID-Mismatch-Report** (V1 + V2 with revenue) and the
> gap lists — served through a web application with a relational database, an Excel
> download and zero data duplication.
>
> Everything in this document is derived from the working pipeline in
> `output/batch1-output/`, `output/batch2-output/`, `output/batch3-output(Only Spotify RD)/`
> and `output/build_song_id_mismatch.py`. Numbers quoted are the real, reconciled numbers
> of the April-2026 run.

---

## Table of contents

1. [System purpose and scope](#1-system-purpose-and-scope)
2. [Domain glossary](#2-domain-glossary)
3. [Why the three identity fields never mix — the wildcard rule](#3-why-the-three-identity-fields-never-mix--the-wildcard-rule)
4. [Input taxonomy — every file, every sheet, every cell](#4-input-taxonomy--every-file-every-sheet-every-cell)
5. [File classification and metadata extraction](#5-file-classification-and-metadata-extraction)
6. [Normalisation primitives](#6-normalisation-primitives)
7. [Processing pipeline — stage by stage](#7-processing-pipeline--stage-by-stage)
8. [SVF-RD-SKV7 — full 225-column specification](#8-svf-rd-skv7--full-225-column-specification)
9. [Song-ID-Mismatch-Report — V1 and V2 specification](#9-song-id-mismatch-report--v1-and-v2-specification)
10. [Gap lists and the statement register](#10-gap-lists-and-the-statement-register)
11. [Database design](#11-database-design)
12. [The "|" rule — pipes live in the export, never in the database](#12-the--rule--pipes-live-in-the-export-never-in-the-database)
13. [Backend architecture](#13-backend-architecture)
14. [Frontend architecture](#14-frontend-architecture)
15. [Excel export engine](#15-excel-export-engine)
16. [Validation, reconciliation and invariants](#16-validation-reconciliation-and-invariants)
17. [Handling new / unknown input shapes](#17-handling-new--unknown-input-shapes)
18. [Deployment, configuration and operations](#18-deployment-configuration-and-operations)
19. [Test plan](#19-test-plan)
20. [Build order for an implementer](#20-build-order-for-an-implementer)

---

## 1. System purpose and scope

SVF Entertainment Private Limited (IPRS member `5154290`, IPI name `00871526032`, IPI base
`I-004791736-0`) receives royalty money from IPRS in the form of **distribution statements**
— one Excel file per distribution run per revenue source. Separately it holds a **catalogue**
of its own recordings, and Spotify sends its **own** revenue and usage reports which do not
agree with what IPRS paid.

The platform must:

| # | Capability |
|---|---|
| C1 | Accept an arbitrary set of statement files, a catalogue file, and Spotify report files |
| C2 | Auto-detect each file's shape and classify it (category, distribution number, period, society) |
| C3 | Extract every royalty line without double counting and reconcile to the file's own printed total |
| C4 | Store everything atomically in a relational database — one fact, one row, no duplication |
| C5 | Produce **SVF-RD-SKV7**: one row per catalogue recording + everything paid or reported that is not in the catalogue, with a Date/Amount/Period/Distribution-Number block per statement |
| C6 | Produce the **Song-ID-Mismatch-Report** V1 (identity clashes) and V2 (same + revenue per source file) |
| C7 | Produce the gap lists (paid but not catalogued, Spotify revenue but not catalogued, streams only) |
| C8 | Let the user download any of these as a formatted `.xlsx`, byte-for-byte reproducible |
| C9 | Never lose a rupee: every total must tie back to the source file's own total |

**Scale of the reference run**

| Metric | Value |
|---|---|
| Statement files | 46 (45 in `input/batch-1`, 1 in `input/batch-2`) |
| Catalogue recordings | 2,762 |
| Distinct IPRS works in the catalogue | ~2,600 |
| SKV7 output rows | 3,149 songs + TOTAL row |
| SKV7 columns | 225 |
| Total royalty distributed (col D) | 33,23,794.31 |
| Spotify gross revenue MRM (col E) | 78,89,496.76 |
| Spotify MRM lines / distinct ISRCs | 10,960 / 1,759 |
| Spotify usage rows | 11,222 |
| Mismatch rows | 781 |

---

## 2. Domain glossary

| Term | Meaning |
|---|---|
| **IPRS** | Indian Performing Right Society — the collecting society that distributes the money |
| **WORK INT NO** / **Internal No** | IPRS's internal identifier for a musical *work* (composition). Integer, e.g. `15628816`. This is the key money is paid against. |
| **ISRC** | International Standard Recording Code — identifies a *recording*, e.g. `INS2X0900009`. One work can have many recordings. |
| **Distribution** | One payout run, identified by a distribution number such as `P2550`, `M2506`, or a sub-run `P2107A008`. |
| **Pool / Source** | IPRS's usage pool (`INTERNET WEBSITE`, `FRI`) and the licensee (`SPOTIFY AB`, `KOLKATTA 1`). Present only on lines that actually carry money. |
| **Role** | `C` composer, `A` author/lyricist, `E` publisher. SVF is the `E`. |
| **OWN / COLL** | Ownership % and collection % for that party. |
| **MRM** | Spotify's "Music Reporting & Money" gross revenue report — revenue per ISRC per month. |
| **Usage report** | Spotify's stream-count report — streams per ISRC per month. |
| **Catalogue (S-46)** | `(S-46)SVF list of Song -April 2026.xlsx` — SVF's own list: Track Name, Internal NO, ISRC (pipe-separated). |
| **SKV\<n\>** | Successive generations of the master workbook. SKV7 is current. |
| **Recording grain** | One row per ISRC/recording. The catalogue is at this grain. |
| **Work grain** | One row per IPRS work. Statements pay at this grain. |

---

## 3. Why the three identity fields never mix — the wildcard rule

This is the single most misunderstood part of the system, so it is specified first.

**Field coverage per source**

| Source | Song Name | Internal No | ISRC |
|---|---|---|---|
| Catalogue `(S-46)` | ✅ `Track Name` | ✅ `Internal NO` | ✅ `ISRC` (pipe list) |
| IPRS statement (any) | ✅ `TITLE` | ✅ `WORK INT NO` | ❌ **absent** |
| Spotify MRM | ✅ `Content Name` | ❌ **absent** | ✅ `ISRC` |
| Spotify usage | ✅ `Content Name` | ❌ **absent** | ✅ `ISRC` |

**The rule.** When two records are compared, a field that a source *does not carry* is a
**wildcard**:

* it can **never** be reported as "different" — a value that does not exist cannot disagree;
* it does **not** block the match either — otherwise the statement (no ISRC) and Spotify
  (no internal number) could never be compared with anything, and the whole report would
  collapse to catalogue-vs-catalogue.

**Consequence, measured on the real run:**

| Mismatch type | Catalogue only | Statement | Spotify MRM | Total |
|---|---|---|---|---|
| Different Internal Number | 0 | **121** | **0 — impossible** | 121 |
| Different ISRC | 25 | **0 — impossible** | 185 (+35 both) | 245 |
| Different Song Name | 21 | 123 (+9 +8 both) | 153 (+17 +84 both) | 415 |

So an internal number in the report is always a real `WORK INT NO` read out of the
catalogue or a statement; an ISRC is always a real ISRC read out of the catalogue or
Spotify. Nothing is inferred, guessed or back-filled.

---

## 4. Input taxonomy — every file, every sheet, every cell

Five physical shapes exist. The ingester detects the shape; it never trusts the folder name.

### 4.1 TYPE A — Standard IPRS distribution statement (27 files in batch-1, 1 in batch-2)

Single worksheet. Sheet name varies (`overseasMemberDetail`, `Sheet1`, …) — **ignore it**.
`ws.max_row`/`max_column` from `openpyxl` **cannot be trusted** on these files (the
dimension record is wrong on the batch-2 file); load with `read_only=False` or call
`ws.calculate_dimension()`.

**Rows 1–3 — letterhead**

| Cell | Content | Use |
|---|---|---|
| `A1` | literal `INTERNAL NO` | shape marker |
| `B1` | `5154290.0` | member internal number → `statement.member_no` (cast float→int) |
| `C1` | literal `IPI NAME NO` | — |
| `D1` | `00871526032` | member IPI name number (keep as text, leading zero) |
| `A2` | literal `NAME` | — |
| `B2` | `SVF ENTERTAINMENT PRIVATE LIMITED` | member name (strip trailing comma) |
| `C2` | literal `IPI BASE NO` | — |
| `D2` | `I-004791736-0` | member IPI base number |
| row 3 | blank | separator |

**Row 4 — column header (12 columns)**

| Col | 1-based | Header | Type | Meaning / rule |
|---|---|---|---|---|
| A | 1 | `WORK INT NO` | float-as-text | IPRS work id. **Present only on the first line of a block**, blank on continuation lines → must be *carried forward*. `int(float(x))`. |
| B | 2 | `TITLE` | text | Work title as IPRS holds it, usually UPPER CASE. Carried forward. |
| C | 3 | `AV` | text | Audio-visual flag. Usually blank. Carried forward. |
| D | 4 | `LANGUAGE` | text | e.g. `BENGALI(BANGLA)`. Carried forward. |
| E | 5 | `NAME` | text | Interested party name (`JEET, GANNGULI`). Per line. |
| F | 6 | `ROLE` | text | `C`, `A`, `E`, `AR`, `SA`… |
| G | 7 | `SOCIETY` | text | `IPRS`, `NS` (non-society) … |
| H | 8 | `OWN` | float | ownership % |
| I | 9 | `COLL` | float | collection % |
| J | 10 | `POOL` | text | usage pool — **non-blank only on money lines** |
| K | 11 | `SOURCE` | text | licensee code — **non-blank only on money lines** |
| L | 12 | `ROYALTY AMT` | float | the money |

**Body, rows 5 … (TOTAL ROYALTIES row − 1)** — block structure:

```
row 5   15617483.0  AAJ AMAYE  ''  BENGALI  JEET, GANNGULI        C  IPRS 25 25  ''   ''      ''        <- party line
row 6   ''          ''         ''  ''       PRASENJIT, MUKHERJEE  A  IPRS 25 25  ''   ''      ''        <- party line
row 7   ''          ''         ''  ''       SVF ENTERTAINMENT     E  IPRS 50 50  FRI  lgGgN   25.2509   <- MONEY line
row 8   ''          ''         ''  ''       ''                    '' ''   '' ''  ''   ''      25.2509   <- block SUB-TOTAL
row 9   blank separator
```

> **Extraction rule (critical, prevents 2× double count):**
> keep a row **iff column K `SOURCE` is non-blank**. That selects money lines only.
> The bare row after them repeats the same figure as a block sub-total and must be skipped.
> Cross-check: Σ(money lines) must equal Σ(sub-total lines) must equal the printed
> `TOTAL ROYALTIES`. On the batch-2 Spotify file all three are `113,848.57`.

**Footer**

| Row | Content |
|---|---|
| a row whose any cell = `TOTAL ROYALTIES` | file grand total at column L (`amt_col`) — parsing stops **before** this row |
| blank rows | — |
| `POOL / SOURCE / SOURCE DESCRIPTION / … / NO. OF WORKS / … / ROYALTY AMT` | pool summary header |
| one row per pool+source | e.g. `FRI · lgGgN · KOLKATTA 1 · 252 works · 40,792.99` |
| final row | works count + grand total repeated |

The pool summary is stored as `statement_pool_summary` and is an independent reconciliation
source.

### 4.2 TYPE B — Overseas society statement (18 files)

Identical letterhead and block/carry-forward mechanics. **17 columns**, header row 4:

| Col | 1-based | Header | Notes |
|---|---|---|---|
| A–I | 1–9 | `WORK INT NO`, `TITLE`, `AV`, `LANGUAGE`, `NAME`, `ROLE`, `SOCIETY`, `OWN`, `COLL` | same as Type A |
| J | 10 | `RADIO` | usage-category split |
| K | 11 | `TV` | |
| L | 12 | `CINEMAS` | |
| M | 13 | `PERMITS` | |
| N | 14 | `DEMAND` | |
| O | 15 | `GENERAL` | |
| P | 16 | `OTHERS` | |
| Q | 17 | `ROYALTY AMT` | the money — **column 17, not 12** |

> **Shape test:** `"RADIO" in header and "TV" in header` → Overseas schema, `amt_col = 17`;
> otherwise Standard, `amt_col = 12`.
>
> **Extraction rule for Type B:** there is no POOL/SOURCE column, so keep a row **iff**
> `NAME` (E) **and** `ROLE` (F) **and** `ROYALTY AMT` (Q) are all non-blank. Rows with a
> `0.0` amount are kept (they are real zero-value lines) — blank is what excludes.

Footer here is a per-usage-category summary (`OTHERS · 227 works · 1018.1984`) ending in a
grand-total row.

The society is **not** in the file — it is parsed from the filename suffix
(`… - 021 BMI.xlsx` → code `021`, society `BMI`, country `USA`).

### 4.3 TYPE C — Catalogue `(S-46)SVF list of Song -April 2026.xlsx`

Header on **row 1**, data from row 2. 2,762 data rows.

| Col | Header | Type | Rule |
|---|---|---|---|
| A | `Track Name` | text | recording name as SVF spells it, mixed case, may contain `(From "…")`, `- Cover`, `-Lofi`, `(Male)`, `(Female)`, `Pt. 1` … |
| B | `Internal NO` | int-as-text | the IPRS work number this recording belongs to. **Never blank in the reference file.** Several recordings legitimately share one number (148 numbers are shared). |
| C | `ISRC` | text | **one or more ISRCs separated by `\|`**, e.g. `INS2X0700012\|INE401001460\|USQY52430516`. Order matters: element 0 is the *primary* ISRC of the recording. Never blank in the reference file. |

Shape test: `A1` lower-cased == `track name`.

### 4.4 TYPE D — Spotify MRM revenue report `Raw_Spotify_MRM_Oct25_Mar26.xlsx`

Header row 1, data from row 2, 10,960 data lines, 1,759 distinct ISRCs, one line per
(month × ISRC × content).

| Col | 1-based | Header | Type | Rule |
|---|---|---|---|---|
| A | 1 | `Month` | datetime | first day of the month; key on `(year, month)` |
| B | 2 | `Client` | text | always `Spotify` |
| C | 3 | `Content Type` | text | `App_Music`, … |
| D | 4 | `Content Name` | text | Spotify's own title — often carries `(From "…")`, `- Cover`, casing differs |
| E | 5 | `Album name` | text | |
| F | 6 | `ISRC` | text | **the join key.** Skip the line if blank. Upper-case, strip non-alphanumerics. |
| G | 7 | `UPC` | text | keep as text, it is a long numeric |
| H | 8 | `Revenue` | float | gross revenue, full precision — do **not** round before aggregating |

Total = `7,889,496.76`. 6 month blocks: Oct 2025 … Mar 2026.

### 4.5 TYPE E — Spotify usage report `Spotify L6M.xlsx`

Header row 1, 11,222 data rows.

| Col | 1-based | Header | Rule |
|---|---|---|---|
| A | 1 | `Month` | datetime |
| B | 2 | `Client` | `Spotify` |
| C | 3 | `Content Name` | title |
| D | 4 | `Album name` | |
| E | 5 | `ISRC` | join key — skip if blank |
| F | 6 | `UPC` | text |
| G | 7 | `Usage` | integer stream count |

> Note the **column order differs from Type D** (no `Content Type` column, so ISRC is at
> index 5 not 6). Detect by header text, never by position.

### 4.6 Shape-detection decision table

```
row1[0].lower() == "track name"                        -> TYPE C  catalogue
"Revenue" in row1 and "ISRC" in row1                    -> TYPE D  Spotify MRM
"Usage"   in row1 and "ISRC" in row1                    -> TYPE E  Spotify usage
row4 contains "WORK INT NO" and "RADIO" and "TV"        -> TYPE B  overseas statement
row4 contains "WORK INT NO"                             -> TYPE A  standard statement
otherwise                                               -> UNKNOWN -> quarantine + operator review
```

---

## 5. File classification and metadata extraction

Statement metadata is **not inside the file** — it is parsed from the filename plus the
zip timestamp. `parse_filename()` is the contract.

### 5.1 Filename grammar

```
(S-<n>)<free text describing the run>.xlsx
```

| Field | Rule | Example |
|---|---|---|
| `s_no` | `\(S-(\d+)\)` → int | `(S-13)…` → 13 |
| `dist_no` | 1st `[PM]\d{4}[A-Z]\d{3}` (sub-run); else if the stem matches `[PM]\d{4}\s+to\s+[PM]\d{4}` use `"<first> to <second>"`; else the 1st `[PM]\d{4}`; else `""` | `P2107A008`, `P2101 to P2540`, `P2550` |
| `redis` | `"redistribution" in stem.lower()` | S-44, S-45 |
| `soc_code` | trailing `(\d{3})\s+([A-Z]{2,10})$` where the code is in `SOCIETIES` | `021 BMI` |
| `p_start`,`p_end` | all `([A-Za-z]{3,12})\.?\s+(\d{4})` month-year hits: first → month start, last → month end. If none but an `F.Y. 2025-26` is present → 1 Apr … 31 Mar. | `Jul 2025 - Sep 2025` |
| `fy` | `F\.?\s?Y\.?\s*(\d{4})\s*-\s*(\d{2,4})` | `2025-26` |
| `period` | `"<Mon> <yyyy> - <Mon> <yyyy>"` (+ ` (FY <fy>)` when known); else `"Not specified"` | |
| `date` | **max `date_time` of all members inside the .xlsx zip** — the statement's real issue date | `2025-11-21` |
| `category` | first match, in order, over the lower-cased stem (see below) | |
| `section` | `"Overseas - <SOC> (<COUNTRY>)"` when category is Overseas and the society resolved, else the category | |

### 5.2 Category ladder (order is significant)

```
redistribution        -> "Redistribution"
"mechanical"          -> "Mechanical (MUSERK)"
"apple music"         -> "Apple Music"
"spotify"             -> "Spotify"
"youtube" & "pre"     -> "YouTube Pre-Claims"
"youtube" & "post"    -> "YouTube Post-Claims"
"facebook" | "meta"   -> "Facebook / Meta"
"radio"               -> "Radio"
"zee television"      -> "Zee TV Broadcast"
"overseas"            -> "Overseas"
else                  -> "Other / Unclassified"
```

### 5.3 Society register

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

Stored as a seeded lookup table so new societies are added without a code change.

### 5.4 Section ordering in the output

```
SECTION_ORDER = ["YouTube Pre-Claims", "YouTube Post-Claims", "Facebook / Meta",
                 "Spotify", "Spotify MRM", "Apple Music", "Radio", "Zee TV Broadcast",
                 "Mechanical (MUSERK)", "Other / Unclassified", "Redistribution"]
```
then every `Overseas - …` section, alphabetically. Inside a section, distributions are
ordered by **statement date**, then by section name.

---

## 6. Normalisation primitives

Every comparison in the system uses these and only these. Implement once, share between
ingester, matcher, mismatch engine and exporter. They are also the definition of the
generated key columns in the database.

```python
def s(v):                       # safe string
    return "" if v is None else str(v).strip()

def num(v):                     # safe float, NaN -> 0
    try:
        f = float(v)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0

def noi(v):                     # internal number:  "16026924.0" -> "16026924"
    t = s(v)
    if not t:
        return None
    try:
        return str(int(float(t)))
    except ValueError:
        return t                # keep unparseable ids verbatim, never drop them

def ik(v):                      # ISRC key
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())

def norm(v):                    # name key  — case / space / punctuation blind
    return re.sub(r"[^a-z0-9]", "", s(v).lower())

VER = re.compile(r"\b(lofi|lo fi|cover|reprise|sped up|slowed|version|male|female|remix|"
                 r"theme|instrumental|unplugged|acoustic|duet|original|mix|edit|radio|sad)\b")

def norm2(v):                   # name key with version words stripped — fuzzy fallback
    return re.sub(r"[^a-z0-9]", "", VER.sub(" ", s(v).lower()))
```

Financial-year helpers:

```python
fin_year(d)  = d.year if d.month >= 4 else d.year - 1      # Indian FY, 1 Apr - 31 Mar
fy_label(y)  = f"FY {y}-{str(y+1)[-2:]}"                   # 2025 -> "FY 2025-26"
month_end(y, m)                                            # last calendar day
```

**Penny reconciliation** — used whenever a total is split across cells that are then
rounded to 2 dp, so the rounded cells still add up to the unrounded total:

```python
def penny_fix(parts: dict, target: float) -> dict:
    out = {k: round(v, 2) for k, v in parts.items()}
    gap = round(target - round(sum(out.values()), 2), 2)
    if gap and out:
        step = 0.01 if gap > 0 else -0.01
        pool = sorted(out, key=lambda k: (parts[k] - out[k]), reverse=gap > 0)
        for i in range(int(round(abs(gap) / 0.01))):
            k = pool[i % len(pool)]
            out[k] = round(out[k] + step, 2)
    return out
```
The cell that lost the most in rounding gets the first extra paisa. Deterministic, so two
runs of the same input produce byte-identical output.

---

## 7. Processing pipeline — stage by stage

```
        upload
          │
   ┌──────▼───────┐  S0  intake        sha256, dedupe, quarantine
   │ source_file  │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S1  classify      TYPE A-E, filename metadata
   │  statement   │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S2  extract       carry-forward blocks -> royalty_line
   │ royalty_line │                    reconcile to TOTAL ROYALTIES
   └──────┬───────┘
          │
   ┌──────▼───────┐  S3  catalogue     TYPE C -> catalogue_entry + recording + work
   │  catalogue   │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S4  spotify       TYPE D -> spotify_revenue,  TYPE E -> spotify_usage
   │   spotify    │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S5  row universe  catalogue backbone + statement-only + spotify-only
   │    rd_row    │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S6  attach money  royalty by WORK INT NO (booked once)
   │  rd_row_cell │                    MRM by ISRC cascade B1..B7
   └──────┬───────┘
          │
   ┌──────▼───────┐  S7  derive        FY split, totals, audit columns
   │   rd_row.*   │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S8  mismatch      rules A / B / C with wildcards -> mismatch + values
   │   mismatch   │
   └──────┬───────┘
          │
   ┌──────▼───────┐  S9  export        SKV7.xlsx, mismatch V1/V2.xlsx, gap lists
   │   export     │
   └──────────────┘
```

### S0 — Intake

* store the raw bytes in object storage under `sha256`;
* `sha256` is unique — re-uploading the same file is a no-op that returns the existing
  `source_file.id` (idempotency, requirement C4);
* the original filename is kept verbatim: **the metadata parser depends on it**;
* files that fail shape detection go to `status = 'quarantined'` with the sniffed header
  row attached, for operator mapping (see §17).

### S1 — Classify

Run the decision table of §4.6 and `parse_filename()` of §5. Produce one `statement` row
for TYPE A/B, one `catalogue_version` for TYPE C, one `spotify_report` for TYPE D/E.

### S2 — Extract royalty lines

```python
schema  = "Overseas" if ("RADIO" in hdr and "TV" in hdr) else "Standard"
amt_col = 17 if schema == "Overseas" else 12          # 1-based
tr      = first row index where any cell == "TOTAL ROYALTIES"
file_total = num(row[tr][amt_col])

carry = [None]*4                                       # WORK INT NO, TITLE, AV, LANGUAGE
for r in rows[4:tr]:                                   # 0-based slice = from sheet row 5
    for c in (0,1,2,3):
        if s(r[c]): carry[c] = r[c]
    keep = s(r[10]) != ""                     if schema == "Standard" else \
           (s(r[4]) and s(r[5]) and s(r[16]))          # NAME & ROLE & AMT
    if not keep: continue
    work_no = noi(carry[0])                            # may be None -> "?S-13:BLANK"
    emit RoyaltyLine(work_no, title=s(carry[1]), language=s(carry[3]),
                     party=s(r[4]), role=s(r[5]), society=s(r[6]),
                     own=num(r[7]), coll=num(r[8]),
                     pool=s(r[9]),  source=s(r[10]),   # Standard only
                     buckets={RADIO:…, TV:…, …},       # Overseas only
                     amount=num(r[amt_col]))
```

* **Unparseable work id** → synthesise `?S-<n>:<raw or BLANK>` and record it in
  `ingest_anomaly`. Never drop the money.
* **Reconciliation:** `abs(Σ amounts − file_total) ≤ 0.05` → `PASS`, else `FAIL` and the
  statement is not promoted to the build.
* Second, independent check: `Σ(money lines) == Σ(sub-total lines)`.

### S3 — Catalogue load

```python
for row in rows[1:]:
    name  = s(row[0]); raw = s(row[1])
    no    = noi(raw)
    isrcs = [ik(x) for x in s(row[2]).split("|") if ik(x)]     # ORDER PRESERVED
    -> catalogue_entry(name, work_no=no, raw_no=raw, position=i)
    -> recording(isrc) for each,  catalogue_entry_isrc(entry, recording, ordinal)
```
`ordinal = 0` is the **primary** ISRC — the MRM cascade depends on it.

### S4 — Spotify load

```python
# TYPE D
mrm[(isrc, (year, month))] += num(Revenue)
mrm_name[isrc][Content Name] += num(Revenue)     # weighted, most_common() picks the title
# TYPE E
usage[isrc] = (first non-empty Content Name, Σ Usage)
```

### S5 — Row universe (the SKV7 backbone)

The rule that makes SKV7 different from SKV6:

1. **one row per catalogue recording** — all 2,762, whether or not anyone paid for it;
2. plus every **work that a statement paid for but the catalogue does not list** (372 in
   the reference run);
3. plus every **ISRC that only Spotify's revenue report knows** (7);
4. plus every **ISRC that only Spotify's usage report knows** (8);
5. → 3,149 rows.

Catalogue → statement linking:

```python
by_no      = {work_no: row for statement-derived rows having a work number}
isrc_blank = {isrc: [rows without a work number that carry this isrc]}

for entry in catalogue:
    if entry.work_no in by_no:            target = by_no[entry.work_no]     # AUTHORITATIVE
    else:                                 target = first isrc_blank hit     # fallback only
```
> The IPRS work number is the only authoritative link for money. ISRC is used **only** to
> rescue rows that carry no work number at all. Song name is never used to attach money.

### S6a — Booking royalty once per work

Several catalogue recordings share one IPRS work (168 in the reference run). The money was
paid once, so it is booked once:

```python
for target_row, entries in link.items():
    cand = [e for e in entries if norm(e.name)  == norm(target_row.title)] \
        or [e for e in entries if norm2(e.name) == norm2(target_row.title)] \
        or entries
    owner[target_row] = cand[0]            # this catalogue row carries the money
```
The siblings get `Amount = 0.00` and an audit note in column 224:
`"IPRS work 15628861 - royalty booked once, on 'Tomake Chai' (INS2X1600134)"`.

**Invariant:** `Σ col D over all rows == Σ file_total over all statements == 33,23,794.31`.

### S6b — Attaching Spotify MRM revenue (ISRC-first cascade)

For every ISRC in the MRM report, in this order — first hit wins:

| Basis | Test | Reference count |
|---|---|---|
| B1 `ISRC - catalogue (primary ISRC of the recording)` | ISRC == some entry's ordinal-0 ISRC | 1,269 (+116 with B2) |
| B2 `ISRC - catalogue (secondary ISRC of the recording)` | ISRC in any entry's ISRC list | 65 |
| B3 `ISRC - royalty statement work (not in the SVF list)` | ISRC sits on a statement-only row | 38 |
| B4 `Song name - catalogue` | `norm(title)` matches a catalogue name | 19 (+30 with B1) |
| B5 `Song name - royalty statement work` | `norm(title)` matches a statement-only row | 18 |
| B6 `Song name, version words stripped - catalogue` | `norm2(title)` matches | — |
| B7 `No match - song is only in Spotify's report` | new row of its own | 7 |

When several catalogue rows are candidates, `pick()` disambiguates by `norm` then `norm2`
against the MRM title, else takes the first.

Month rounding then uses `penny_fix` twice — once so each month column adds to the month
total, once so the month totals add to the report total.

**Invariant:** `Σ col E == 78,89,496.76 == Σ Revenue in the raw MRM file`.

### S7 — Derived values

* `Total Amount` (col D) = Σ of every statement Amount cell on that row.
* `Total Spotify Revenue (MRM)` (col E) = Σ of the 6 month cells.
* **FY split (cols 217–221):** each distribution's amount is spread across Indian financial
  years **in proportion to how many months of its period fall in each FY**
  (`split_period`), then `penny_fix`-ed back to the exact row total. A distribution with no
  parseable period lands entirely in `Period Not Stated`.
* `Total Revenue` (col 222) must equal col D exactly.
* **Catalogue Status (col 223)** — one of exactly eight values:

| Value | Reference count |
|---|---|
| `In SVF list (S-46) - royalty received` | 1,795 |
| `In SVF list (S-46) - no royalty distributed in any of the 47 statements` | 780 |
| `NOT in SVF list (S-46) - work paid by a royalty statement` | 318 |
| `In SVF list (S-46) - separate recording of an IPRS work paid on another row` | 168 |
| `NOT in SVF list (S-46) - appears only in Spotify's revenue report` | 48 |
| `In SVF list (S-46) - named in a statement, but the amount distributed was 0.00` | 18 |
| `NOT in SVF list (S-46) - named in a statement, but the amount distributed was 0.00` | 13 |
| `NOT in SVF list (S-46) - appears only in Spotify's usage report (streams, but no revenue and no royalty in this period)` | 8 |

* **Royalty Booked On (col 224)** — sibling note, blank on 2,980 rows.
* **Spotify (MRM) Match Basis (col 225)** — the B1…B7 label(s), `" ; "`-joined when a row
  absorbed several ISRCs matched on different bases.

### S8 — Mismatch engine → §9. S9 — Export → §15.

---

## 8. SVF-RD-SKV7 — full 225-column specification

One worksheet named `SVF-RD-SKV7`. Row 1 = merged section bands, row 2 = column headers,
rows 3…N = songs, then a blank row, a `TOTAL` row, a blank row, and a full-width note row.
Freeze panes at `A3`; `ISRC`/`Song Name`/`Internal No` frozen horizontally.

### 8.1 Identity + totals (columns 1–5)

| Col | Header | Source | Format |
|---|---|---|---|
| 1 | `ISRC` | catalogue ISRC list joined `" \| "`, in catalogue order; for non-catalogue rows the ISRCs Spotify/the statement supplied | text |
| 2 | `Song Name` | catalogue `Track Name`; else statement `TITLE`; else Spotify `Content Name` | text |
| 3 | `Internal No` | catalogue `Internal NO`; else statement `WORK INT NO`; blank for Spotify-only rows | text/int |
| 4 | `Total Amount` | Σ all statement Amount cells on the row | `#,##0.00` |
| 5 | `Total Spotify Revenue (MRM)` | Σ the 6 MRM month cells | `#,##0.00` |

### 8.2 Distribution sections (columns 6–213)

Every section is **`4 × number_of_distributions`** columns wide, and every distribution is
the same 4-column block:

| Offset | Header | Value |
|---|---|---|
| +0 | `Date` | `statement.date` — `DD-MMM-YYYY` |
| +1 | `Amount` | this row's money in that distribution — `#,##0.00`, blank when zero *and* the row is not in that statement |
| +2 | `Period` | `statement.period` label |
| +3 | `Distribution Number` | `statement.dist_no` (or `Not specified`) |

Reference layout (row 1 merged label → column range):

| Range | Section | Distributions |
|---|---|---|
| 6–17 | `YOUTUBE PRE-CLAIMS` | 3 |
| 18–45 | `YOUTUBE POST-CLAIMS` | 7 |
| 46–57 | `FACEBOOK / META` | 3 |
| 58–65 | `SPOTIFY - ROYALTY DISTRIBUTED BY IPRS  (2 distributions: Apr 2025 - Sep 2025 and Oct 2025 - Mar 2026)` | 2 |
| 66–89 | `SPOTIFY - GROSS REVENUE REPORTED BY SPOTIFY (MRM report)  (Oct 2025 - Mar 2026, 6 months)` | 6 month-blocks |
| 90–97 | `APPLE MUSIC` | 2 |
| 98–101 | `RADIO` | 1 |
| 102–113 | `ZEE TV BROADCAST` | 3 |
| 114–117 | `MECHANICAL (MUSERK)` | 1 |
| 118–133 | `OTHER / UNCLASSIFIED` | 4 |
| 134–141 | `REDISTRIBUTION` | 2 |
| 142–145 | `OVERSEAS - APRA (AUSTRALIA)` | 1 |
| 146–149 | `OVERSEAS - BMI (USA)` | 1 |
| 150–153 | `OVERSEAS - BUMA (NETHERLANDS)` | 1 |
| 154–157 | `OVERSEAS - CASH (HONG KONG)` | 1 |
| 158–161 | `OVERSEAS - COMPASS (SINGAPORE)` | 1 |
| 162–169 | `OVERSEAS - IMRO (IRELAND)` | 2 |
| 170–181 | `OVERSEAS - MACP (MALAYSIA)` | 3 |
| 182–185 | `OVERSEAS - MCT (THAILAND)` | 1 |
| 186–197 | `OVERSEAS - SACEM (FRANCE)` | 3 |
| 198–209 | `OVERSEAS - SOCAN (CANADA)` | 3 |
| 210–213 | `OVERSEAS - SUISA (SWITZERLAND)` | 1 |
| 214–216 | *(blank spacer columns)* | — |

> The MRM section is **not** a statement — its 4-column blocks carry the month-end date,
> the month's revenue, `"<Mon> <yyyy>"` and `"Spotify MRM report"` respectively.
>
> **The layout is data-driven.** With a different set of uploaded files the section list,
> their order and their widths change automatically. Never hard-code column 58.

### 8.3 Financial-year block (columns 217–222)

| Col | Header |
|---|---|
| 217 | `FY 2022-23` |
| 218 | `FY 2023-24` |
| 219 | `FY 2024-25` |
| 220 | `FY 2025-26` |
| 221 | `Period Not Stated` |
| 222 | `Total Revenue` |

Row-1 band: `TOTAL REVENUE  (by Indian Financial Year, 1 Apr - 31 Mar, of the period the
royalty was earned in)`. FY columns are generated from the data — a statement for FY
2026-27 adds a column.

### 8.4 Audit block (columns 223–225)

Row-1 band `AUDIT / TRACEABILITY  (new in SVF-RD-SKV7)`.

| Col | Header | Content |
|---|---|---|
| 223 | `Catalogue Status` | the eight-value enum of §S7 |
| 224 | `Royalty Booked On` | sibling note or blank |
| 225 | `Spotify (MRM) Match Basis` | B1…B7 label(s), `" ; "`-joined |

### 8.5 Sorting, totals, note

* Rows sorted by `-Total Amount`, then `-Total Spotify Revenue`, then `norm(Song Name)`.
* `TOTAL` row: label in col 2, sums for col 4, col 5, every Amount column and the FY block.
* Final note row: a full-width merged paragraph explaining what changed from SKV6 and how
  the row universe was built. Stored in `report_note` so the exporter is not the source of
  prose.

---

## 9. Song-ID-Mismatch-Report — V1 and V2 specification

### 9.1 Inputs

| Alias | File | Fields it contributes |
|---|---|---|
| S2 | `(S-46)SVF list of Song -April 2026.xlsx` | name + internal no + ISRC list |
| S3 | `Spotify - for the Period October 2025 to March 2026.xlsx` | name + internal no |
| S4 | `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | name + ISRC (deduped to 1,792 distinct `(norm(name), isrc)` pairs) |

Record counts: 2,762 + 1,389 + 1,792.

### 9.2 The three rules

Two fields agree → the third disagreeing is the issue. A field the source does not carry
is a wildcard (§3).

| Rule | Match on | Report | Rows |
|---|---|---|---|
| **A** | Song Name + ISRC | `Different Internal Number` | 121 |
| **B** | Song Name + Internal No | `Different ISRC` | 245 |
| **C** | Internal No + ISRC | `Different Song Name` | 415 |

**Grouping indexes**

```python
gA[(norm(name), isrc)]  += records that carry that name and that ISRC
gB[(norm(name), no)]    += records that carry that name and that internal number
gC[(no, isrc)]          += records that carry both

name_only[norm(name)]   = records with NO ISRC              (statement)   -> wildcard into gA
noint_by_name[norm(nm)] = records with NO internal number   (Spotify)     -> wildcard into gB
no_only[no]             = records with no ISRC              (statement)   -> wildcard into gC
isrc_only[isrc]         = records with no internal number   (Spotify)     -> wildcard into gC
```

Two extra passes handle the all-wildcard case — a name (or a work) for which **no** record
anywhere carries an ISRC. There the ISRC condition is vacuous, so the name alone (rule A) or
the number alone (rule C) decides. Without these passes, titles that exist only in the
statement would never be compared.

Rule B additionally **skips a group where no record carries an ISRC** — with nothing to
compare against, "different ISRC" would be meaningless.

### 9.3 Identity row selection (`pick`)

For each group the row printed in the identity columns is chosen by this sort:

```
0. a record that actually carries the disputed field   (before one that does not)
1. a record from the SVF catalogue (S2)                (before any other source)
2. a record that matched on BOTH key fields (core)     (before a wildcard joiner)
3. source priority  S2 < S4 < S3
4. original row order
```

This is what guarantees the "main" values come from source 2 whenever source 2 is in the
group — and prevents the earlier defect where a wildcard record without the disputed field
was printed as the main row and its own value then appeared as its own conflict.

### 9.4 Value merging — the rule that fixed the duplicate rows

**One output row per `(identity record, mismatch type)`.**

A catalogue row with several ISRCs forms several `(no, isrc)` groups; each can surface a
different conflicting name. Those must land in **one** row with the values pipe-joined —
not in one row per ISRC.

```python
key = (main.source, main.row_ordinal, kind)
bucket = merged.setdefault(key, {vals: {}, sheets: set()})
for v in conflicting_values:
    bucket.vals.setdefault(norm(v) if kind == "name" else v, v)   # de-dupe, keep 1st spelling
bucket.sheets |= sources_that_supplied_those_values
```

* de-duplication key for names is `norm()` — `AMARE TUMI` and `Amare Tumi` are one value;
* for ISRC and internal number the normalised value is itself the key;
* the main record's own value can never enter its own conflict list;
* result: 844 raw groups → **781 rows**.

### 9.5 V1 column layout — `Song-ID-Mismatch-Report.xlsx`

Sheet `Song ID Mismatches`, header on row 1, freeze `A2`, autofilter `A1:G782`.

| Col | Header | Width | Content |
|---|---|---|---|
| A | `S. No` | 7 | 1…781 |
| B | `ISRC (as per SVF Song List)` | 34 | main record's ISRC list, `" \| "`-joined, `-` if none |
| C | `Song Name (as per SVF Song List)` | 34 | main record's name |
| D | `Internal No. (as per SVF Song List)` | 17 | main record's work number, `-` if none |
| E | `Type of Mismatch` | 24 | `Different ISRC` / `Different Internal Number` / `Different Song Name` |
| F | `Conflicting Value(s) Found` | 46 | every other value, sorted, `" \| "`-joined |
| G | `Sheet(s) Where the Conflict Was Found` | 42 | `SVF Song List (S-46)` / `Spotify IPRS Statement (Oct'25-Mar'26)` / `Spotify Raw MRM (Oct'25-Mar'26)`, `" \| "`-joined in S2,S3,S4 order |

Sort: mismatch type (`Different ISRC`, `Different Internal Number`, `Different Song Name`),
then `norm(Song Name)`, then internal number.

Styling: header bold `#1F3864` on pastel blue `#DCE9F7`, wrapped, centred, row height 34;
thin `#B7C9DC` borders everywhere; body wraps on B, F, G; A and D centred.

### 9.6 V2 column layout — `Song-ID-Mismatch-Report-V2-With-Revenue.xlsx`

Rows 1 = section bands, row 2 = headers, freeze `A3`, autofilter `A2:J783`, TOTAL row at
the bottom.

| Range | Row-1 band | Fill |
|---|---|---|
| A1:G1 (merged) | `SONG IDENTITY MISMATCHES BETWEEN THE SVF SONG LIST, THE IPRS SPOTIFY STATEMENT AND SPOTIFY'S OWN REPORT   -   781 rows` | `#DCE9F7` |
| H1 | `SPOTIFY - ROYALTY DISTRIBUTED BY IPRS` / `Spotify - for the Period October 2025 to March 2026.xlsx` / `Total royalty in this file : 113,848.57` | `#FCE4D6` |
| I1 | `SPOTIFY - GROSS REVENUE REPORTED BY SPOTIFY (MRM)` / `Raw_Spotify_MRM_Oct25_Mar26.xlsx` / `Total revenue in this file : 7,889,496.76` | `#FCE4D6` |
| J1 | `BOTH FILES TOGETHER` / `booked once per IPRS work / per ISRC` | `#FCE4D6` |

Columns A–G identical to V1. Then:

| Col | Header | Rule |
|---|---|---|
| H | `Royalty Paid on This Song` | the IPRS statement royalty of the row's work number |
| I | `Gross Revenue on This Song` | Σ MRM revenue of the row's ISRCs |
| J | `Total (Both Files)` | H + I |

**Booking rule (identical in spirit to SKV7 col D):** a work number is booked to the **first
row that carries it**, an ISRC to the **first row that lists it**; later rows show `0.00`.
Without this, the 148 shared work numbers would multiply the money.

TOTAL row (pastel green `#E2EFDA`, bold): `TOTAL  (booked once per IPRS work / per ISRC)`
merged A:G, then `61,206.05`, `3,722,218.78`, `3,783,424.83`.

**Invariants:** column H sum ≤ file total; column I sum ≤ file total; TOTAL row == column
sums; V1 and V2 have identical A–G content and the same row count.

### 9.7 Source-file royalty totals used by V2

* IPRS statement: sum the **money lines** (POOL/SOURCE non-blank) per work — cross-checked
  against the sub-total lines and against the printed `TOTAL ROYALTIES` (all three =
  `113,848.57`).
* Spotify MRM: sum `Revenue` per ISRC (`7,889,496.76`, equal to SKV7 column E's total).

---

## 10. Gap lists and the statement register

Four companion workbooks, all derived from the same tables — never recomputed by hand.

| File | Sheet | Rows | Columns |
|---|---|---|---|
| `Works-Paid-But-Missing-From-SVF-Song-List.xlsx` | `Missing-From-SVF-List` | 336 | `S. No`, `IPRS Work Int No`, `Song Name`, `ISRC`, `Where the ISRC comes from`, `Total Royalty Received`, `Spotify Revenue (MRM)`, then one column per category (`YouTube Pre-Claims`, `YouTube Post-Claims`, `Facebook / Meta`, `Spotify (IPRS royalty)`, `Apple Music`, `Radio`, `Zee TV Broadcast`, …) |
| `Spotify-Revenue-But-Missing-From-SVF-Song-List.xlsx` | `Spotify-Revenue-Only` | 53 | `S. No`, `Song Name`, `ISRC`, `Album (as Spotify reports it)`, `Total Spotify Revenue (MRM)`, `Revenue Oct 2025` … `Revenue Mar 2026`, `Total Streams`, `IPRS Royalty Received`, `How Spotify's revenue was matched` |
| `Spotify-Streams-Only-Missing-From-SVF-Song-List.xlsx` | `Spotify-Streams-Only` | 13 | `S. No`, `Song Name`, `ISRC`, `Album`, `Total Streams`, `Streams Jan 2026` … `Streams Jun 2026`, `Spotify Revenue`, `IPRS Royalty Received` |
| `Statement-SKV4.xlsx` | `Statement-SKV4` | 46 + summary blocks | `S. No`, `Statement File`, `Distribution Number`, `Source / Category`, `Period Covered`, `Financial Year(s) Covered`, `Statement Date`, `Works`, `Royalty Lines`, `Total Amount`, `Spotify Revenue (MRM)`, `% of Grand Total` |

`Where the ISRC comes from` is a provenance string, e.g.
`SVF list (S-46) - same name ignoring version words`,
`Spotify report - recording of this work`, or `-` when no ISRC could be established.

---

## 11. Database design

**Engine:** PostgreSQL 16. Rationale: exact `NUMERIC` money, generated columns for the
normalisation keys, `citext`/expression indexes for name matching, partial unique indexes
for the "one primary ISRC" rule, and window functions for the book-once logic.

**Money type:** `NUMERIC(18,6)` for stored raw amounts (Spotify sends 12+ decimals),
`NUMERIC(18,2)` for anything presented. Never `float`.

### 11.1 Entity–relationship overview

```
ingest_batch ──< source_file ──┬─< statement ──< royalty_line >── work
                               │                 │
                               │                 └──< statement_pool_summary
                               ├─< catalogue_version ──< catalogue_entry >── work
                               │                              │
                               │                              └──< catalogue_entry_isrc >── recording
                               └─< spotify_report ──┬─< spotify_revenue >── recording
                                                    └─< spotify_usage   >── recording

build_run ──┬─< rd_row ──┬─< rd_row_isrc >── recording
            │            ├─< rd_row_amount >── statement
            │            ├─< rd_row_mrm  (month, amount)
            │            └──< rd_row_fy   (fy, amount)
            ├─< mismatch ──┬─< mismatch_value
            │              └─< mismatch_source
            └─< export_artifact
```

### 11.2 DDL

```sql
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------- reference data
CREATE TABLE society (
    code        CHAR(3) PRIMARY KEY,           -- '021'
    name        TEXT NOT NULL,                 -- 'BMI'
    country     TEXT NOT NULL                  -- 'USA'
);

CREATE TABLE category (
    code        TEXT PRIMARY KEY,              -- 'youtube_pre'
    label       TEXT NOT NULL,                 -- 'YouTube Pre-Claims'
    sort_order  INT  NOT NULL,
    matcher     TEXT NOT NULL                  -- the filename rule, editable by an admin
);

-- ---------------------------------------------------------------- intake
CREATE TABLE ingest_batch (
    id          BIGSERIAL PRIMARY KEY,
    label       TEXT NOT NULL,                 -- 'batch-1', 'April 2026 run'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  BIGINT REFERENCES app_user(id)
);

CREATE TABLE source_file (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
    original_name TEXT   NOT NULL,             -- MUST be preserved: metadata is parsed from it
    sha256        CHAR(64) NOT NULL,
    byte_size     BIGINT NOT NULL,
    storage_key   TEXT   NOT NULL,             -- object-store path
    file_kind     TEXT   NOT NULL              -- 'statement_std'|'statement_overseas'
                                               -- |'catalogue'|'spotify_mrm'|'spotify_usage'|'unknown'
                  CHECK (file_kind IN ('statement_std','statement_overseas','catalogue',
                                       'spotify_mrm','spotify_usage','unknown')),
    sheet_name    TEXT,
    header_row    INT,
    status        TEXT NOT NULL DEFAULT 'received'
                  CHECK (status IN ('received','classified','extracted','failed','quarantined')),
    error_text    TEXT,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sha256)                            -- re-upload of the same bytes is a no-op
);

-- ---------------------------------------------------------------- canonical identities
CREATE TABLE work (                            -- one row per IPRS WORK INT NO, ever seen
    id          BIGSERIAL PRIMARY KEY,
    work_no     TEXT NOT NULL,                 -- normalised by noi(): '16026924'
    is_synthetic BOOLEAN NOT NULL DEFAULT false, -- true for '?S-13:BLANK' placeholders
    UNIQUE (work_no)
);

CREATE TABLE recording (                       -- one row per ISRC, ever seen
    id          BIGSERIAL PRIMARY KEY,
    isrc        TEXT NOT NULL,                 -- normalised by ik(): 'INS2X0900009'
    UNIQUE (isrc)
);

-- ---------------------------------------------------------------- catalogue (TYPE C)
CREATE TABLE catalogue_version (
    id             BIGSERIAL PRIMARY KEY,
    source_file_id BIGINT NOT NULL UNIQUE REFERENCES source_file(id) ON DELETE CASCADE,
    as_of_label    TEXT,                       -- 'April 2026'
    row_count      INT  NOT NULL
);

CREATE TABLE catalogue_entry (                 -- one row per catalogue LINE (recording grain)
    id           BIGSERIAL PRIMARY KEY,
    version_id   BIGINT NOT NULL REFERENCES catalogue_version(id) ON DELETE CASCADE,
    row_ordinal  INT    NOT NULL,              -- sheet row order; the tie-breaker everywhere
    track_name   TEXT   NOT NULL,
    raw_work_no  TEXT,                         -- exactly as printed
    work_id      BIGINT REFERENCES work(id),
    name_key     TEXT GENERATED ALWAYS AS
                 (regexp_replace(lower(track_name), '[^a-z0-9]', '', 'g')) STORED,
    UNIQUE (version_id, row_ordinal)
);
CREATE INDEX ON catalogue_entry (name_key);
CREATE INDEX ON catalogue_entry (work_id);

CREATE TABLE catalogue_entry_isrc (            -- the "|" list, exploded — NEVER a pipe string
    entry_id     BIGINT NOT NULL REFERENCES catalogue_entry(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    ordinal      SMALLINT NOT NULL,            -- 0 = primary ISRC of the recording
    PRIMARY KEY (entry_id, recording_id)
);
CREATE UNIQUE INDEX ON catalogue_entry_isrc (entry_id, ordinal);

-- ---------------------------------------------------------------- statements (TYPE A/B)
CREATE TABLE statement (
    id             BIGSERIAL PRIMARY KEY,
    source_file_id BIGINT NOT NULL UNIQUE REFERENCES source_file(id) ON DELETE CASCADE,
    s_no           INT,                        -- from "(S-13)"
    schema_type    TEXT NOT NULL CHECK (schema_type IN ('standard','overseas')),
    dist_no        TEXT,                       -- 'P2550' | 'P2107A008' | 'P2101 to P2540'
    category_code  TEXT NOT NULL REFERENCES category(code),
    society_code   CHAR(3) REFERENCES society(code),
    section_label  TEXT NOT NULL,              -- 'Overseas - BMI (USA)' or the category label
    period_start   DATE,
    period_end     DATE,
    period_label   TEXT NOT NULL DEFAULT 'Not specified',
    fy_label       TEXT,
    statement_date DATE NOT NULL,              -- max mtime inside the .xlsx zip
    member_no      TEXT NOT NULL,              -- '5154290'
    member_name    TEXT NOT NULL,
    ipi_name_no    TEXT,
    ipi_base_no    TEXT,
    file_total     NUMERIC(18,6) NOT NULL,     -- printed TOTAL ROYALTIES
    extracted_total NUMERIC(18,6) NOT NULL,    -- Σ royalty_line.amount
    line_count     INT NOT NULL,
    work_count     INT NOT NULL,
    reconciled     BOOLEAN NOT NULL,           -- abs(diff) <= 0.05
    is_redistribution BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX ON statement (category_code, statement_date);

CREATE TABLE royalty_line (                    -- immutable raw extraction, one per money line
    id            BIGSERIAL PRIMARY KEY,
    statement_id  BIGINT NOT NULL REFERENCES statement(id) ON DELETE CASCADE,
    sheet_row     INT    NOT NULL,             -- provenance back to the cell
    work_id       BIGINT NOT NULL REFERENCES work(id),
    title         TEXT   NOT NULL,             -- TITLE as printed (carried forward)
    language      TEXT,
    av_flag       TEXT,
    party_name    TEXT,
    role          TEXT,
    society       TEXT,
    own_pct       NUMERIC(9,4),
    coll_pct      NUMERIC(9,4),
    pool          TEXT,                        -- standard schema only
    source_code   TEXT,                        -- standard schema only
    amt_radio     NUMERIC(18,6),               -- overseas schema only
    amt_tv        NUMERIC(18,6),
    amt_cinemas   NUMERIC(18,6),
    amt_permits   NUMERIC(18,6),
    amt_demand    NUMERIC(18,6),
    amt_general   NUMERIC(18,6),
    amt_others    NUMERIC(18,6),
    amount        NUMERIC(18,6) NOT NULL,
    title_key     TEXT GENERATED ALWAYS AS
                  (regexp_replace(lower(title), '[^a-z0-9]', '', 'g')) STORED,
    UNIQUE (statement_id, sheet_row)           -- idempotent re-extraction
);
CREATE INDEX ON royalty_line (work_id);
CREATE INDEX ON royalty_line (title_key);

CREATE TABLE statement_pool_summary (          -- the printed footer, an independent check
    id           BIGSERIAL PRIMARY KEY,
    statement_id BIGINT NOT NULL REFERENCES statement(id) ON DELETE CASCADE,
    pool         TEXT, source_code TEXT, source_description TEXT,
    work_count   INT, amount NUMERIC(18,6)
);

-- ---------------------------------------------------------------- Spotify (TYPE D/E)
CREATE TABLE spotify_report (
    id             BIGSERIAL PRIMARY KEY,
    source_file_id BIGINT NOT NULL UNIQUE REFERENCES source_file(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('revenue','usage')),
    period_start   DATE NOT NULL,
    period_end     DATE NOT NULL,
    line_count     INT  NOT NULL,
    total_value    NUMERIC(18,6) NOT NULL      -- Σ revenue, or Σ streams
);

CREATE TABLE spotify_revenue (
    id           BIGSERIAL PRIMARY KEY,
    report_id    BIGINT NOT NULL REFERENCES spotify_report(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    month        DATE   NOT NULL,              -- first day of month
    content_name TEXT   NOT NULL,
    album_name   TEXT,
    upc          TEXT,
    content_type TEXT,
    revenue      NUMERIC(18,6) NOT NULL,
    name_key     TEXT GENERATED ALWAYS AS
                 (regexp_replace(lower(content_name), '[^a-z0-9]', '', 'g')) STORED,
    UNIQUE (report_id, recording_id, month, name_key)   -- collapses repeated lines
);
CREATE INDEX ON spotify_revenue (recording_id);
CREATE INDEX ON spotify_revenue (name_key);

CREATE TABLE spotify_usage (
    id           BIGSERIAL PRIMARY KEY,
    report_id    BIGINT NOT NULL REFERENCES spotify_report(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    month        DATE   NOT NULL,
    content_name TEXT   NOT NULL,
    album_name   TEXT, upc TEXT,
    streams      BIGINT NOT NULL,
    UNIQUE (report_id, recording_id, month)
);

-- ---------------------------------------------------------------- build output
CREATE TABLE build_run (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT NOT NULL REFERENCES ingest_batch(id),
    version_label TEXT   NOT NULL,             -- 'SKV7'
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','succeeded','failed')),
    row_count     INT,
    total_royalty NUMERIC(18,2),
    total_mrm     NUMERIC(18,2),
    config        JSONB NOT NULL DEFAULT '{}'  -- section order, tolerances, labels
);

CREATE TABLE rd_row (
    id             BIGSERIAL PRIMARY KEY,
    build_id       BIGINT NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    row_ordinal    INT    NOT NULL,            -- final sorted position, 1-based
    origin         TEXT   NOT NULL CHECK (origin IN ('catalogue','statement','spotify_revenue',
                                                     'spotify_usage')),
    catalogue_entry_id BIGINT REFERENCES catalogue_entry(id),
    work_id        BIGINT REFERENCES work(id),
    song_name      TEXT   NOT NULL,
    total_amount   NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_mrm      NUMERIC(18,2) NOT NULL DEFAULT 0,
    catalogue_status TEXT NOT NULL,            -- the 8-value enum
    booked_note    TEXT,                       -- col 224
    mrm_basis      TEXT,                       -- col 225
    UNIQUE (build_id, row_ordinal)
);
CREATE INDEX ON rd_row (build_id, work_id);

CREATE TABLE rd_row_isrc (                     -- the "|" of column A, exploded
    rd_row_id    BIGINT NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    ordinal      SMALLINT NOT NULL,
    PRIMARY KEY (rd_row_id, recording_id)
);

CREATE TABLE rd_row_amount (                   -- one cell of one distribution block
    rd_row_id    BIGINT NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    statement_id BIGINT NOT NULL REFERENCES statement(id),
    amount       NUMERIC(18,2) NOT NULL,
    PRIMARY KEY (rd_row_id, statement_id)
);

CREATE TABLE rd_row_mrm (
    rd_row_id    BIGINT NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    month        DATE   NOT NULL,
    amount       NUMERIC(18,2) NOT NULL,
    PRIMARY KEY (rd_row_id, month)
);

CREATE TABLE rd_row_fy (
    rd_row_id    BIGINT NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    fy_start     INT,                          -- NULL = 'Period Not Stated'
    amount       NUMERIC(18,2) NOT NULL,
    PRIMARY KEY (rd_row_id, COALESCE(fy_start, -1))
);

-- ---------------------------------------------------------------- mismatch report
CREATE TABLE mismatch (
    id            BIGSERIAL PRIMARY KEY,
    build_id      BIGINT NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    row_ordinal   INT    NOT NULL,
    kind          TEXT   NOT NULL CHECK (kind IN ('internal_no','isrc','song_name')),
    main_source   TEXT   NOT NULL CHECK (main_source IN ('catalogue','statement','spotify')),
    main_ref_id   BIGINT NOT NULL,             -- catalogue_entry.id | royalty_line.id | spotify_revenue.id
    main_name     TEXT   NOT NULL,
    main_work_id  BIGINT REFERENCES work(id),
    iprs_amount   NUMERIC(18,2) NOT NULL DEFAULT 0,   -- V2 col H, booked once
    mrm_amount    NUMERIC(18,2) NOT NULL DEFAULT 0,   -- V2 col I, booked once
    UNIQUE (build_id, main_source, main_ref_id, kind)  -- ENFORCES the merge rule
);

CREATE TABLE mismatch_main_isrc (
    mismatch_id  BIGINT NOT NULL REFERENCES mismatch(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    ordinal      SMALLINT NOT NULL,
    PRIMARY KEY (mismatch_id, recording_id)
);

CREATE TABLE mismatch_value (                  -- one conflicting value = one row
    id           BIGSERIAL PRIMARY KEY,
    mismatch_id  BIGINT NOT NULL REFERENCES mismatch(id) ON DELETE CASCADE,
    value_text   TEXT   NOT NULL,              -- the value as printed
    value_key    TEXT   NOT NULL,              -- norm()/ik()/noi() of it
    UNIQUE (mismatch_id, value_key)            -- ENFORCES no duplicate inside one cell
);

CREATE TABLE mismatch_source (
    mismatch_id  BIGINT NOT NULL REFERENCES mismatch(id) ON DELETE CASCADE,
    source_kind  TEXT   NOT NULL CHECK (source_kind IN ('catalogue','statement','spotify')),
    source_file_id BIGINT NOT NULL REFERENCES source_file(id),
    PRIMARY KEY (mismatch_id, source_file_id)
);

-- ---------------------------------------------------------------- exports & audit
CREATE TABLE export_artifact (
    id           BIGSERIAL PRIMARY KEY,
    build_id     BIGINT NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    artifact     TEXT   NOT NULL,              -- 'skv7'|'mismatch_v1'|'mismatch_v2'|'gap_works'|…
    file_name    TEXT   NOT NULL,
    storage_key  TEXT   NOT NULL,
    sha256       CHAR(64) NOT NULL,
    byte_size    BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (build_id, artifact)
);

CREATE TABLE ingest_anomaly (
    id             BIGSERIAL PRIMARY KEY,
    source_file_id BIGINT NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    sheet_row      INT,
    kind           TEXT NOT NULL,              -- 'unparseable_work_no'|'total_mismatch'|…
    detail         JSONB NOT NULL
);
```

### 11.3 Why this shape has no duplication

| Risk | Guard |
|---|---|
| Same file uploaded twice | `source_file.sha256` UNIQUE |
| Same line extracted twice | `royalty_line (statement_id, sheet_row)` UNIQUE |
| Money counted twice (money line + sub-total line) | extraction keeps `SOURCE`-bearing lines only, verified against both other totals |
| One work paid once but shown on several catalogue recordings | money lives in `rd_row_amount` keyed by `(rd_row_id, statement_id)`; the owner row is chosen once by the `norm/norm2` rule; siblings carry `0.00` and `booked_note` |
| Same ISRC on two catalogue rows | `recording.isrc` UNIQUE, referenced from both — the *string* exists once |
| Same conflicting value listed twice in one cell | `mismatch_value (mismatch_id, value_key)` UNIQUE |
| Two report rows for the same identity + issue | `mismatch (build_id, main_source, main_ref_id, kind)` UNIQUE |
| Spotify repeating a line for the same ISRC/month | `spotify_revenue (report_id, recording_id, month, name_key)` UNIQUE |

---

## 12. The "|" rule — pipes live in the export, never in the database

The `|` character appears in three places in the deliverables:

1. catalogue column C — the input's own multi-ISRC list;
2. SKV7 column A — the row's ISRC list;
3. mismatch report columns B, F, G — ISRC list, conflicting values, source sheets.

**In the database none of these is ever stored as a pipe-joined string.** Each is a child
table with one row per element (`catalogue_entry_isrc`, `rd_row_isrc`, `mismatch_value`,
`mismatch_source`). Reasons: a pipe string cannot be indexed, joined, de-duplicated or
counted; and "the same ISRC written twice with different spacing" becomes undetectable.

**Join is a presentation function, applied only in the export/serialiser layer:**

```python
JOIN = " | "

def join_isrcs(rows):        # rd_row_isrc / catalogue_entry_isrc, ordered by ordinal
    return JOIN.join(r.isrc for r in sorted(rows, key=lambda r: r.ordinal)) or "-"

def join_values(vals):       # mismatch_value — sorted, already unique by value_key
    return JOIN.join(v.value_text for v in sorted(vals, key=lambda v: v.value_text))

def join_sheets(srcs):       # mismatch_source — fixed order S2, S3, S4
    return JOIN.join(LABEL[k] for k in ("catalogue", "statement", "spotify")
                     if k in {s.source_kind for s in srcs})
```

Splitting on input is the mirror image: `[ik(x) for x in cell.split("|") if ik(x)]`,
preserving order so `ordinal = 0` stays the primary ISRC. A `|` inside a song *name* is
never produced — names are stored and exported verbatim, and only ISRC/number/sheet lists
are ever joined.

---

## 13. Backend architecture

### 13.1 Stack

| Concern | Choice | Why |
|---|---|---|
| API | **FastAPI** (Python 3.12), Pydantic v2 | the entire extraction/matching logic is already Python + `openpyxl`; no language boundary |
| ORM / migrations | SQLAlchemy 2 + Alembic | |
| Async jobs | Celery + Redis (or RQ) | a 46-file build takes minutes; HTTP must not hold it |
| Excel | `openpyxl` (write), `openpyxl` read-only + `calculate_dimension()` fallback | identical to the proven scripts |
| Object storage | S3 / MinIO | raw uploads + generated artifacts |
| Auth | OIDC or session + RBAC (`viewer`, `analyst`, `admin`) | |

### 13.2 Module layout

```
app/
  core/          config, logging, security, errors
  domain/
    normalize.py       s, num, noi, ik, norm, norm2, penny_fix, fin_year, fy_label
    filename.py        parse_filename, SOCIETIES, category ladder
    sniff.py           shape detection (§4.6)
  ingest/
    reader.py          workbook -> grid, dimension repair
    statement.py       TYPE A/B extractor + reconciliation
    catalogue.py       TYPE C
    spotify.py         TYPE D/E
  build/
    universe.py        S5 row universe
    linker.py          catalogue <-> statement linking, owner selection
    mrm.py             B1..B7 cascade, penny_fix month rounding
    fy.py              split_period, FY allocation
    status.py          catalogue_status / booked_note / mrm_basis
  mismatch/
    engine.py          rules A/B/C, wildcard passes, pick(), merge
    revenue.py         book-once attribution for V2
  export/
    skv7.py            225-column writer
    mismatch_xlsx.py   V1 + V2 writers
    gaps.py            the four companion workbooks
    style.py           fills, fonts, borders, number formats — single source of truth
  api/                 routers
  jobs/                celery tasks
  tests/
```

### 13.3 REST API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/batches` | create a batch (`label`) |
| `POST` | `/api/batches/{id}/files` | multipart upload, N files; returns per-file `{id, sha256, duplicate:bool}` |
| `GET` | `/api/batches/{id}/files` | listing with `file_kind`, `status`, sniffed header |
| `PATCH` | `/api/files/{id}` | operator override of `file_kind`, `category_code`, `dist_no`, `period`, `society_code` |
| `POST` | `/api/batches/{id}/classify` | run S1 → job |
| `POST` | `/api/batches/{id}/extract` | run S2–S4 → job |
| `GET` | `/api/batches/{id}/validation` | per-statement `extracted vs file_total`, PASS/FAIL, anomalies |
| `POST` | `/api/batches/{id}/builds` | run S5–S8 → `build_run` |
| `GET` | `/api/builds/{id}` | status, row count, totals |
| `GET` | `/api/builds/{id}/rows` | paginated SKV7 rows; `?q=&status=&min_amount=&sort=` |
| `GET` | `/api/builds/{id}/rows/{rowId}` | one row with every amount cell + provenance |
| `GET` | `/api/builds/{id}/mismatches` | paginated, `?kind=&source=&q=` |
| `GET` | `/api/builds/{id}/gaps/{which}` | the three gap lists |
| `GET` | `/api/builds/{id}/statements` | the statement register (Statement-SKV4 content) |
| `POST` | `/api/builds/{id}/exports/{artifact}` | generate the .xlsx → job |
| `GET` | `/api/builds/{id}/exports/{artifact}` | 302 to a signed URL, or stream the bytes |
| `GET` | `/api/jobs/{id}` | `queued\|running\|succeeded\|failed`, progress %, log tail |

Every list endpoint: cursor pagination, `X-Total-Count`, deterministic ordering.

### 13.4 Job orchestration

```
classify_batch -> extract_files (fan-out, one task per file) -> chord ->
build_universe -> attach_money -> attach_mrm -> derive_fy_status ->
run_mismatch -> [export_skv7, export_mismatch_v1, export_mismatch_v2, export_gaps]
```

Rules: every task is idempotent and keyed by `(batch_id, file_id)`; a failed file marks
itself `failed` without aborting the batch; the build refuses to start while any statement
has `reconciled = false` unless the caller passes `?force=true`, which is recorded in
`build_run.config`.

### 13.5 Concurrency and integrity

* Extraction of one file = one transaction. Partial extraction is never visible.
* A build takes an advisory lock on `batch_id` — one build at a time per batch.
* `build_run` rows are immutable once `succeeded`; a re-run makes a new build, so an
  exported workbook can always be traced to the exact input set.

---

## 14. Frontend architecture

### 14.1 Stack

React 18 + TypeScript + Vite · TanStack Query (server state) · TanStack Table +
`react-virtual` (225 columns × 3,149 rows demands virtualisation) · Tailwind + shadcn/ui ·
Recharts for the summary charts.

### 14.2 Screens

| Screen | Contents |
|---|---|
| **Batches** | list, create, per-batch counts, last build status |
| **Upload** | drag-and-drop; per-file card showing detected `file_kind`, parsed distribution number / category / period / society / statement date; duplicate badge for a repeated `sha256`; inline override form; "Classify" and "Extract" buttons |
| **Validation** | one row per statement: file, category, distribution, schema, lines, extracted, printed total, difference, PASS/FAIL; anomaly drawer listing unparseable work numbers; a build is blocked while any FAIL is unresolved |
| **RD Viewer (SKV7)** | virtualised grid, sticky first 3 columns, sticky 2-row header with the merged section bands, section collapse/expand, column-group filters, full-text search over ISRC/name/work no, filters on catalogue status and amount range; row click → drawer with every non-zero distribution, its statement file, period and distribution number, the FY split and the three audit fields |
| **Mismatch Report** | tabs `All / Different ISRC / Different Internal Number / Different Song Name`; each conflicting value is a chip (never a pipe string in the UI); a chip click opens the record that supplied it; source-sheet filter; V2 toggle adds the revenue columns and the sticky total bar |
| **Gap lists** | the three lists with the same filtering |
| **Statements** | the register, with per-category totals and a share-of-total bar |
| **Exports** | one card per artifact: generate, progress, size, sha256, download; history of previous builds |

### 14.3 UI rules that mirror the data rules

* Pipe-joined strings are **never** rendered as strings — the API returns arrays
  (`isrcs: string[]`, `conflicting_values: string[]`, `sources: string[]`) and the UI renders
  chips. The pipe only ever appears inside the downloaded `.xlsx`.
* Money is right-aligned, `#,##0.00`, always 2 dp, and a `0.00` from the book-once rule is
  shown greyed with a tooltip naming the row that carries the money.
* The eight catalogue-status values get eight fixed colours, used identically everywhere.

---

## 15. Excel export engine

A single `style.py` holds every visual constant so the workbooks stay consistent:

| Token | Value | Used for |
|---|---|---|
| `HDR_FILL` | `#DCE9F7` pastel blue | column-name row |
| `SEC_FILL` | `#FCE4D6` pastel peach | file/section bands |
| `TOT_FILL` | `#E2EFDA` pastel green | total rows |
| `HDR_FONT` | bold 11, `#1F3864` | column names |
| `SEC_FONT` | bold 9, `#833C0C` | section bands |
| `BORDER` | thin `#B7C9DC`, all four sides | every cell |
| `MONEY` | `#,##0.00` | every amount |
| `DATEF` | `DD-MMM-YYYY` | every statement date |

Writer contract:

1. build the section plan from the database (`statement` ordered by section then date) —
   never from a constant;
2. write row 1 bands + merges, row 2 headers, set column widths and row heights;
3. stream rows in `rd_row.row_ordinal` order;
4. write the `TOTAL` row and the note row;
5. `freeze_panes`, `auto_filter`;
6. save to a temp file, `sha256` it, upload, insert `export_artifact`.

Determinism requirement: same `build_run` → identical `sha256`. That means no timestamps
inside the sheet, sorted iteration everywhere, and `penny_fix` as the only rounding path.

Download: `GET /api/builds/{id}/exports/{artifact}` streams with
`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and
`Content-Disposition: attachment; filename="SVF-RD-SKV7.xlsx"`.

---

## 16. Validation, reconciliation and invariants

Every build asserts these. A failure aborts the build and is surfaced on the Validation
screen with the offending rows.

| # | Invariant | Reference value |
|---|---|---|
| I1 | per statement: `abs(Σ royalty_line.amount − file_total) ≤ 0.05` | 46/46 PASS |
| I2 | per statement: `Σ money lines == Σ sub-total lines == printed TOTAL ROYALTIES` | `113,848.57` on the Spotify statement |
| I3 | `Σ rd_row.total_amount == Σ statement.file_total` | `3,323,794.31` |
| I4 | `Σ rd_row.total_mrm == Σ spotify_revenue.revenue` | `7,889,496.76` |
| I5 | `Σ rd_row_fy.amount == Σ rd_row.total_amount` | `3,323,794.31` |
| I6 | every catalogue entry has exactly one `rd_row` | 2,762 |
| I7 | every IPRS work with money is booked on exactly one row | 168 siblings at 0.00 |
| I8 | every month column of the MRM block sums to that month's reported total | `penny_fix` |
| I9 | no `mismatch_value` equals its own row's main value | 0 violations |
| I10 | no two `mismatch` rows share `(main_ref, kind)` | 844 groups → 781 rows |
| I11 | mismatch V1 and V2 have identical A–G content and row count | 781 = 781 |
| I12 | V2 column H sum ≤ IPRS file total, column I sum ≤ MRM file total | 61,206.05 ≤ 113,848.57 · 3,722,218.78 ≤ 7,889,496.76 |
| I13 | V2 TOTAL row == the column sums | 3,783,424.83 |

**Independent re-derivation.** The test suite recomputes I9–I13 from the *raw input files*
with a second, deliberately different implementation (pairwise comparison instead of
grouping) and compares. The reference run gives: 0 precision problems; rule A 0 missing
pairs, rule C 0 missing pairs, rule B 0 missing except 76 Spotify↔Spotify pairs whose two
ISRCs are both already catalogued under the same work (no discrepancy exists to report).

---

## 17. Handling new / unknown input shapes

The system must not break when SVF sends a file nobody has seen.

1. **Sniff** — header text, not position. Store the first 8 rows of the sheet as JSON on
   `source_file` for the operator.
2. **Quarantine** — `status = 'quarantined'`, excluded from the build, visible on the Upload
   screen with a red badge.
3. **Column mapping UI** — the operator maps sheet columns onto the canonical fields
   (`work_no`, `title`, `party`, `role`, `own`, `coll`, `pool`, `source`, `amount`, …). The
   mapping is stored in `file_kind_profile(header_fingerprint, mapping JSONB)` and is applied
   automatically the next time the same fingerprint arrives.
4. **New category** — insert a `category` row with a `matcher` regex; no code change.
5. **New society** — insert a `society` row.
6. **New FY** — FY columns are generated from the data.
7. **Missing period in the filename** — the money lands in `Period Not Stated`; the operator
   can set `period_start`/`period_end` on the statement and rebuild.
8. **Catalogue without ISRCs, or with a blank internal number** — allowed. Those entries
   simply cannot participate in the rules that need the missing field (§3), and their
   `catalogue_status` records the gap.

---

## 18. Deployment, configuration and operations

```
                 ┌────────────┐
   browser ─────▶│  nginx/CDN │─────▶ React static bundle
                 └─────┬──────┘
                       │ /api
                 ┌─────▼──────┐      ┌──────────┐
                 │  FastAPI   │─────▶│ Postgres │
                 │  (uvicorn) │      └──────────┘
                 └─────┬──────┘
                       │ enqueue          ┌──────────┐
                 ┌─────▼──────┐           │  MinIO   │
                 │   Redis    │◀──────────│   / S3   │
                 └─────┬──────┘           └──────────┘
                 ┌─────▼──────┐
                 │  Celery    │  extraction / build / export workers
                 └────────────┘
```

Configuration (`.env`): `DATABASE_URL`, `REDIS_URL`, `S3_*`, `MAX_UPLOAD_MB` (default 64),
`RECON_TOLERANCE` (default `0.05`), `MONEY_ROUNDING` (`penny_fix`), `EXPORT_TIMEOUT_S`.

Operational notes: `openpyxl` on a 10,000-row sheet is memory-hungry — use `read_only=True`
where the dimension record is sound, and repair it with `calculate_dimension()` where it is
not (the batch-2 Spotify statement reports `1×1`). Workers get 2 GB. Keep every uploaded
file forever; keep exports for 90 days and regenerate on demand — the build is deterministic.

Backups: nightly `pg_dump` + object-store versioning. Restore drill quarterly.

---

## 19. Test plan

| Layer | Tests |
|---|---|
| Unit | `noi("16026924.0") == "16026924"`; `norm("Aaj  Amaye!") == "aajamaye"`; `norm2("Abar Phire Ele-Lofi") == norm2("Abar Phire Ele")`; `penny_fix` restores the target to the paisa; `parse_filename` on all 46 real names |
| Fixture | a 40-row synthetic Type A file, a 40-row Type B file, a 10-row catalogue, a 50-line MRM file — with hand-computed expected totals |
| Extraction | money lines vs sub-total lines vs printed total, on every real file |
| Golden | rebuild from `input/batch-1..3` and diff cell-by-cell against the committed `SVF-RD-SKV7.xlsx`, `Song-ID-Mismatch-Report.xlsx`, `Song-ID-Mismatch-Report-V2-With-Revenue.xlsx` |
| Property | shuffling the input file order must not change any output byte |
| Mismatch | the independent pairwise re-derivation of §16 |
| API | upload → classify → extract → build → export happy path; duplicate upload returns the same id; build blocked on a FAIL statement |
| UI | virtualised grid renders 3,149 × 225 without layout shift; chips render one per value |

---

## 20. Build order for an implementer

1. `domain/normalize.py` + `domain/filename.py` + unit tests. Everything depends on these.
2. Postgres schema + Alembic migration + the `society` / `category` seeds.
3. `ingest/reader.py` and `sniff.py`; prove shape detection on all 49 real files.
4. `ingest/statement.py` with the carry-forward + `SOURCE`-line rule; assert I1 and I2.
5. `ingest/catalogue.py` and `ingest/spotify.py`; assert row counts 2,762 / 10,960 / 11,222.
6. `build/universe.py` + `linker.py`; assert I3, I6, I7.
7. `build/mrm.py` with the B1–B7 cascade and `penny_fix`; assert I4 and I8.
8. `build/fy.py` + `build/status.py`; assert I5 and the eight-value status distribution.
9. `export/skv7.py`; golden-diff against the committed workbook.
10. `mismatch/engine.py` + `revenue.py`; assert I9–I13 and the independent re-derivation.
11. `export/mismatch_xlsx.py` (V1 + V2) and `export/gaps.py`; golden-diff.
12. FastAPI routers + Celery tasks + job status.
13. React app: Upload → Validation → RD Viewer → Mismatch → Exports.
14. Hardening: RBAC, audit log, retention, backup/restore drill.

---

### Appendix A — reference file inventory

| Folder | Files | Shape |
|---|---|---|
| `input/batch-1` | 27 | TYPE A standard statement |
| `input/batch-1` | 18 | TYPE B overseas statement |
| `input/batch-1` | 1 (`S-46`) | TYPE C catalogue |
| `input/batch-2` | 1 | TYPE A standard statement (Spotify Oct 25 – Mar 26) |
| `input/batch-3(Only spotify RD)` | 1 | TYPE D Spotify MRM revenue |
| `input/batch-3(Only spotify RD)` | 1 | TYPE E Spotify usage (L6M) |

### Appendix B — output lineage

| Generation | Workbook | Built by | Notes |
|---|---|---|---|
| V1 | `SVF_Royalty_Consolidated_Report_SK.xlsx` | `build_consolidation.py` | first consolidation |
| V2 | `SVF_RD_V2.xlsx` | `build_song_matrix.py` | song × distribution matrix |
| V3 | `SVF-RD-V3.xlsx` | `build_rd_v3.py` | sections, 4-column blocks, FY summary — **the metadata parser lives here** |
| V4 | `SVF-RD-SKV4.xlsx` | `build_rd_v4.py` | + statement register |
| V5 | `SVF-RD-SKV5.xlsx` | `build_rd_v5.py` | batch-2 Spotify statement folded in |
| V6 | `SVF-RD-SKV6.xlsx` | `build_v2.py` | + Spotify MRM revenue |
| **V7** | **`SVF-RD-SKV7.xlsx`** | `build_skv7.py` | **catalogue as the backbone, ISRC-first MRM, audit columns** |
| — | `Song-ID-Mismatch-Report.xlsx` (+ V2) | `build_song_id_mismatch.py` | identity clashes, with revenue |
| — | `Works-Paid-But-Missing-…`, `Spotify-Revenue-…`, `Spotify-Streams-Only-…` | `build_gap_list.py`, `build_spotify_gap_lists.py` | gap lists |
| — | `Statement-SKV4.xlsx` | `build_stmt4.py` | statement register |
