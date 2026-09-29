# SVF Entertainment — IPRS Royalty Intelligence Platform
## Complete build-from-scratch architecture — **V2**

| | |
|---|---|
| **Whose architecture** | **SVF Entertainment Private Limited** — IPRS member `5154290`, IPI name `00871526032`, IPI base `I-004791736-0` |
| **Domain** | Music publishing royalties: IPRS distribution statements + SVF's own song catalogue + Spotify's own revenue/usage reports |
| **What it builds** | `SVF-RD-SKV8` (master royalty matrix), the Catalogue Coverage Audit, the Same-Name/Different-ISRC merge review, the Song-ID-Mismatch reports and the gap lists — as a web application over a relational database, with byte-reproducible Excel exports |
| **Version** | **V2** — supersedes `SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V1.md` (previously `ARCHITECTURE.md`) |
| **Reference run** | April 2026 catalogue · statements to P2583 · Spotify Oct 2025 – Mar 2026 |
| **Status of the numbers** | Every figure in this document was re-measured from `input/` and `output/` while writing it. Nothing is quoted from memory. |

### What is new in V2

| # | Addition | Why it exists |
|---|---|---|
| N1 | **§11 Catalogue Coverage Audit** — a first-class, repeatable workflow: *"here is my song sheet; show me every song that is NOT in it but still earned money from a party (Spotify, YouTube, Meta, Apple, a foreign society …)"* | It was done three times by hand-written scripts with three different answers. It is now one engine with one exclusion ladder, two strictness modes and a stated accuracy contract. |
| N2 | **§12 Same-Name / Different-ISRC merge review** — the platform proposes candidate groups, the **user selects** which are really the same song, the selected ones are merged (revenue added, identifiers pipe-joined) into a new build, reversibly | One recording can reach SVF under two ISRCs or two internal numbers. Auto-merging is wrong; never merging is also wrong. The decision belongs to the user and must be recorded. |
| N3 | **§10 SVF-RD-SKV8** — the SKV7 matrix with those merges applied and the unregistered ISRCs written into column A | SKV7 quietly folded Spotify money onto a catalogue row by song name but printed only the registered ISRC, so the workbook could not be audited. |
| N4 | **§20 accuracy model** — 25 invariants, each with its measured reference value, plus the independent re-derivation rule | "Supreme accuracy" has to be a test, not a claim. |
| N5 | Input taxonomy extended with **TYPE F — any user-supplied song sheet** and a column-mapping contract | The coverage audit must accept a sheet the platform has never seen. |
| N6 | The **defect log** (§23) — every bug found in the hand-written generation of these reports, and the rule that prevents each one | Two of them silently changed money. |

---

## Table of contents

1. [System purpose and scope](#1-system-purpose-and-scope)
2. [Reference-run facts](#2-reference-run-facts)
3. [Domain glossary](#3-domain-glossary)
4. [The identity model and the wildcard rule](#4-the-identity-model-and-the-wildcard-rule)
5. [Input taxonomy — every file, every sheet, every cell](#5-input-taxonomy--every-file-every-sheet-every-cell)
6. [File classification and metadata extraction](#6-file-classification-and-metadata-extraction)
7. [Normalisation primitives](#7-normalisation-primitives)
8. [Identity resolution — the link ladder](#8-identity-resolution--the-link-ladder)
9. [Processing pipeline — stage by stage](#9-processing-pipeline--stage-by-stage)
10. [SVF-RD-SKV7 / SKV8 — full 225-column specification](#10-svf-rd-skv7--skv8--full-225-column-specification)
11. [Catalogue Coverage Audit — "not in my sheet but still earning"](#11-catalogue-coverage-audit--not-in-my-sheet-but-still-earning)
12. [Same-Name / Different-ISRC merge review](#12-same-name--different-isrc-merge-review)
13. [Song-ID-Mismatch report — V1 and V2](#13-song-id-mismatch-report--v1-and-v2)
14. [Gap lists and the statement register](#14-gap-lists-and-the-statement-register)
15. [Database design](#15-database-design)
16. [The "|" rule — pipes live in the export, never in the database](#16-the--rule--pipes-live-in-the-export-never-in-the-database)
17. [Backend architecture](#17-backend-architecture)
18. [Frontend architecture — the tabs](#18-frontend-architecture--the-tabs)
19. [Excel export engine and the SKV visual system](#19-excel-export-engine-and-the-skv-visual-system)
20. [Accuracy model — invariants and reconciliation](#20-accuracy-model--invariants-and-reconciliation)
21. [Handling new / unknown input shapes](#21-handling-new--unknown-input-shapes)
22. [Deployment, configuration and operations](#22-deployment-configuration-and-operations)
23. [Defect log — what went wrong and the rule that prevents it](#23-defect-log--what-went-wrong-and-the-rule-that-prevents-it)
24. [Test plan](#24-test-plan)
25. [Build order for an implementer](#25-build-order-for-an-implementer)
26. [Appendices](#26-appendices)

---

## 1. System purpose and scope

SVF receives royalty money from IPRS as **distribution statements** — one Excel file per
distribution run per revenue source. It separately maintains a **catalogue** of its own
recordings, and Spotify sends **its own** revenue and usage reports, which do not agree
with what IPRS paid.

The platform must:

| # | Capability | Section |
|---|---|---|
| C1 | Accept an arbitrary set of statement files, a catalogue file, platform reports, and any user-supplied song sheet | §5, §21 |
| C2 | Auto-detect each file's shape and classify it (category, distribution number, period, society) | §6 |
| C3 | Extract every royalty line without double counting and reconcile to the file's own printed total | §9 S2, §20 |
| C4 | Store everything atomically — one fact, one row, no duplication, no pipe strings | §15, §16 |
| C5 | Produce **SVF-RD-SKV8**: one row per catalogue recording plus everything paid or reported that the catalogue does not list, with a Date/Amount/Period/Distribution-Number block per statement | §10 |
| C6 | Answer *"which songs are NOT in this sheet and still earned money?"* for **any** sheet the user uploads, at a stated confidence level | §11 |
| C7 | Propose same-song/different-identifier groups, let the **user** decide, apply the chosen merges into a new build, and keep the decision reversible | §12 |
| C8 | Produce the Song-ID-Mismatch report (V1 identity clashes, V2 with revenue) | §13 |
| C9 | Produce the gap lists and the statement register | §14 |
| C10 | Export every deliverable as a formatted `.xlsx`, byte-for-byte reproducible from the same build | §19 |
| C11 | Never lose a rupee, never invent one: every total ties back to a source file's own printed total, and every merge is money-neutral | §20 |
| C12 | Never mutate a delivered build — corrections create a new build with a lineage pointer | §15, §17 |

**Out of scope:** payment execution, contracts/splits administration, licensing, and any
write-back to IPRS.

---

## 2. Reference-run facts

Measured from the files in `input/` and `output/` on the April-2026 run.

### 2.1 Inputs

| Input | Count / value |
|---|---|
| Statement files | **46** (45 in `input/batch-1`, 1 in `input/batch-2`) |
| — Standard schema (12 columns, `ROYALTY AMT` in column L) | **28** |
| — Overseas schema (17 columns, `ROYALTY AMT` in column Q) | **18** |
| Catalogue `(S-46)SVF list of Song -April 2026.xlsx` rows | **2,762** |
| — distinct internal numbers | **2,571** (one of them is the literal text `NEED TO REGISTER`, on *Ekakitwo - The Poem*) |
| — distinct ISRCs | **4,278** |
| — distinct name keys | **2,570** |
| IPRS Spotify statement Oct'25–Mar'26 — works | **1,379** |
| IPRS Spotify statement Oct'25–Mar'26 — total | **113,848.57** (money lines = sub-total lines = printed `TOTAL ROYALTIES`) |
| Spotify MRM `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | **10,960** lines · **1,759** ISRCs · 6 months |
| Spotify MRM gross revenue | **7,889,496.76** |
| Spotify usage `Spotify L6M.xlsx` | **11,222** rows |

### 2.2 Outputs

| Output | Count / value |
|---|---|
| `SVF-RD-SKV7.xlsx` rows × columns | 3,149 × 225 |
| `SVF-RD-SKV8.xlsx` rows × columns | **3,144 × 225** (5 rows merged away) |
| Total royalty distributed (column D) | **3,323,794.31** — identical in SKV7 and SKV8 |
| Spotify gross revenue (column E) | **7,889,496.76** — identical in SKV7 and SKV8 |
| Coverage audit — songs earning but absent from the catalogue | **93** |
| — reached us only through the IPRS statement | 13 |
| — reached us only through the Spotify MRM report | 71 |
| — both | 9 |
| — Spotify gross revenue at stake | **250,956.32** (sum of the rounded monthly cells; the unrounded raw sum is 250,956.39 — see the display rule in §7) |
| — IPRS royalty already received on them | **1,140.08** |
| — title exists in the catalogue, identifiers do not | **18** |
| Merge candidates in SKV8 (name on more than one row) | **168 groups over 402 rows** |
| Song-ID-Mismatch rows | 781 |

---

## 3. Domain glossary

| Term | Meaning |
|---|---|
| **IPRS** | Indian Performing Right Society — the collecting society that distributes the money |
| **WORK INT NO** / **Internal No** | IPRS's identifier for a musical *work* (composition). Integer, e.g. `15628816`. **Money is paid against this.** |
| **ISRC** | International Standard Recording Code — identifies a *recording*, e.g. `INS2X0900009`. One work has many recordings. **Platform revenue is reported against this.** |
| **Distribution** | One payout run: `P2550`, `M2506`, or a sub-run `P2107A008` |
| **Statement** | One Excel file for one distribution run for one revenue source |
| **Pool / Source** | IPRS's usage pool (`INTERNET WEBSITE`, `FRI`) and the licensee (`SPOTIFY AB`). Non-blank **only on lines that carry money** |
| **Role** | `C` composer, `A` author, `E` publisher. SVF is the `E` |
| **MRM** | Spotify's gross revenue report — revenue per ISRC per month. Gross, *not* a distribution |
| **Catalogue / the sheet (S-46)** | `(S-46)SVF list of Song -April 2026.xlsx`: Track Name · Internal NO · ISRC (pipe list) |
| **SKV\<n\>** | Successive generations of the master workbook. **SKV8 is current** |
| **Work grain** | One row per IPRS work — statements pay at this grain |
| **Recording grain** | One row per ISRC — the catalogue and the platform reports live at this grain |
| **Coverage audit** | The "not in my sheet but still earning" report (§11) |
| **Merge decision** | A user's recorded judgement that two identifiers are the same song (§12) |
| **Booked once** | The rule that money paid once against a work appears on exactly one row (§9 S6a) |

---

## 4. The identity model and the wildcard rule

Three identity fields exist and **no source carries all three**.

| Source | Song Name | Internal No | ISRC |
|---|---|---|---|
| Catalogue (S-46) / any user sheet | ✅ | ✅ | ✅ (pipe list) |
| IPRS statement (any type) | ✅ `TITLE` | ✅ `WORK INT NO` | ❌ **absent** |
| Spotify MRM (revenue) | ✅ `Content Name` | ❌ **absent** | ✅ |
| Spotify usage (streams) | ✅ `Content Name` | ❌ **absent** | ✅ |

**The wildcard rule.** When two records are compared, a field a source *does not carry* is a
wildcard:

* it can **never** be reported as "different" — a value that does not exist cannot disagree;
* it does **not** block the match either — otherwise a statement (no ISRC) could never be
  compared with a Spotify report (no internal number).

**The authority rule.** Each field has exactly one job, and they are never interchanged:

| Field | Authoritative for | Never used for |
|---|---|---|
| Internal No | attaching **royalty money** from a statement | attaching platform revenue |
| ISRC | attaching **platform revenue** (Spotify MRM/usage) | attaching statement money, unless the row has no work number at all |
| Song Name | **linking identity across sources** when one side lacks the other's identifier, and generating merge candidates | attaching money on its own — a name match alone never books a rupee without the audit column saying so |

Every place where a song name *did* decide money — SKV7's B4/B5 MRM fallback — is stamped in
column 225 (`Spotify (MRM) Match Basis`) and surfaced in the UI, because that is exactly the
population the merge review (§12) exists to confirm.

---

## 5. Input taxonomy — every file, every sheet, every cell

Six physical shapes. The ingester detects the shape from **header text**; it never trusts a
folder name, a sheet name or a column position.

### 5.1 TYPE A — Standard IPRS distribution statement (28 files)

Single worksheet; the sheet name varies (`overseasMemberDetail`, `MemberDetail`, `Sheet1`) —
**ignore it**. `ws.max_row` / `max_column` **cannot be trusted**: several of these files
carry a `1×1` dimension record. Load with `read_only=False`, or repair with
`ws.calculate_dimension()`.

**Rows 1–3 — letterhead**

| Cell | Content | Use |
|---|---|---|
| `A1` | literal `INTERNAL NO` | shape marker |
| `B1` | `5154290.0` | member internal number → `statement.member_no` (`int(float(x))`) |
| `C1` / `D1` | `IPI NAME NO` / `00871526032` | keep as text — leading zero is significant |
| `A2` / `B2` | `NAME` / `SVF ENTERTAINMENT PRIVATE LIMITED,` | member name (strip the trailing comma) |
| `C2` / `D2` | `IPI BASE NO` / `I-004791736-0` | |
| row 3 | blank | separator |

**Row 4 — column header (12 columns)**

| Col | Header | Rule |
|---|---|---|
| A | `WORK INT NO` | present **only on the first line of a block** → carry forward. `int(float(x))` |
| B | `TITLE` | carried forward, usually UPPER CASE |
| C | `AV` | carried forward |
| D | `LANGUAGE` | carried forward, e.g. `BENGALI(BANGLA)` |
| E | `NAME` | interested party, per line |
| F | `ROLE` | `C`, `A`, `E`, `CA`, `AR`, `SA` … |
| G | `SOCIETY` | `IPRS`, `NS`, `DP` … |
| H / I | `OWN` / `COLL` | ownership % / collection % |
| J | `POOL` | usage pool — **non-blank only on money lines** |
| K | `SOURCE` | licensee — **non-blank only on money lines** |
| L | `ROYALTY AMT` | the money |

**Block structure**

```
row 5   15617483.0  AAJ AMAYE  ''  BENGALI  JEET, GANNGULI        C  IPRS 25 25  ''   ''     ''        <- party line
row 6   ''          ''         ''  ''       PRASENJIT, MUKHERJEE  A  IPRS 25 25  ''   ''     ''        <- party line
row 7   ''          ''         ''  ''       SVF ENTERTAINMENT     E  IPRS 50 50  INTERNET  SPOTIFY AB  119.2258   <- MONEY line
row 8   ''          ''         ''  ''       ''                    '' ''   '' ''  ''   ''     119.2258  <- block SUB-TOTAL
row 9   blank separator
```

> **Extraction rule (prevents a 2× double count):** keep a line **iff column K `SOURCE` is
> non-blank**. The bare line after it repeats the figure as a block sub-total.
>
> **Stop rule (prevents a grand-total leak):** parsing stops **before** the row whose any
> cell equals `TOTAL ROYALTIES`. That row's amount sits in the same amount column, so a
> parser that runs past it silently books the whole file onto the last work. On the Spotify
> Oct'25–Mar'26 file that is the difference between `113,848.57` and `227,696.78`
> (see §23 D1).
>
> **Three-way check:** Σ(money lines) == Σ(sub-total lines) == printed `TOTAL ROYALTIES`
> == `113,848.57` on that file.

**Footer** — after `TOTAL ROYALTIES`: a `SUMMARY OF ROYALTY` block by language, then a
pool/source summary (`POOL · SOURCE · SOURCE DESCRIPTION · NO. OF WORKS · ROYALTY AMT`).
Both are stored (`statement_pool_summary`, `statement_language_summary`) as independent
reconciliation sources — they are never the primary extraction.

### 5.2 TYPE B — Overseas society statement (18 files)

Identical letterhead and carry-forward mechanics. **17 columns**; columns A–I as Type A, then:

| Col | Header |
|---|---|
| J–P | `RADIO`, `TV`, `CINEMAS`, `PERMITS`, `DEMAND`, `GENERAL`, `OTHERS` — usage-category split |
| Q | `ROYALTY AMT` — the money, **column 17, not 12** |

> **Shape test:** `"RADIO" in header and "TV" in header` → Overseas, `amt_col = 17`; else
> Standard, `amt_col = 12`.
>
> **Extraction rule:** there is no POOL/SOURCE column, so keep a line **iff** `NAME` **and**
> `ROLE` **and** `ROYALTY AMT` are all non-blank. A `0.0` amount is a real line and is kept;
> blank is what excludes.

The society is **not inside the file** — it comes from the filename suffix
(`… - 021 BMI.xlsx` → code `021`, society `BMI`, country `USA`).

### 5.3 TYPE C — The SVF catalogue `(S-46)SVF list of Song -April 2026.xlsx`

Header row 1, data from row 2, 2,762 rows.

| Col | Header | Rule |
|---|---|---|
| A | `Track Name` | recording name as SVF spells it; may carry `(From "…")`, `- Cover`, `- Lofi`, `(Male)`, `(Female Version)`, `Pt. 1` |
| B | `Internal NO` | the IPRS work number. **May be non-numeric** — the reference file contains the literal `NEED TO REGISTER`. Keep such a value verbatim (`noi()` does), never coerce it to null |
| C | `ISRC` | one or more ISRCs separated by `\|`. **Order matters** — element 0 is the *primary* ISRC |

Shape test: `A1.lower() == "track name"`.

### 5.4 TYPE D — Spotify MRM revenue `Raw_Spotify_MRM_Oct25_Mar26.xlsx`

Header row 1; 10,960 data lines; one line per (month × ISRC).

| Col | Header | Rule |
|---|---|---|
| A | `Month` | datetime, first day of the month → key on `(year, month)` |
| B | `Client` | always `Spotify` |
| C | `Content Type` | `App_Music` |
| D | `Content Name` | Spotify's own title — casing and version suffixes differ from the catalogue |
| E | `Album name` | used as a merge-review signal (§12) |
| F | `ISRC` | **the join key**; skip the line if blank |
| G | `UPC` | keep as text |
| H | `Revenue` | gross, full precision — **do not round before aggregating** |

Total `7,889,496.76`; months Oct 2025 … Mar 2026.

### 5.5 TYPE E — Spotify usage `Spotify L6M.xlsx`

Header row 1; 11,222 rows; `Month`, `Client`, `Content Name`, `Album name`, `ISRC`, `UPC`,
`Usage`.

> The column order **differs from Type D** (no `Content Type`, so ISRC is at index 5, not 6).
> Detect by header text, never by position.

### 5.6 TYPE F — Any user-supplied song sheet (new in V2)

The coverage audit (§11) must run against a sheet nobody has seen. A TYPE F sheet is any
workbook that is not A–E and that carries at least one identity column.

**Auto-mapping** — for each column, score the header text and then the cell values:

| Canonical field | Header regex (case-insensitive) | Value fingerprint |
|---|---|---|
| `song_name` | `track\|song\|title\|content name\|work title` | mostly text, ≥ 40 % contain a space |
| `internal_no` | `internal\|work int\|work no\|iprs\|work id` | ≥ 80 % parse as an integer after `float()` |
| `isrc` | `isrc\|recording code` | ≥ 60 % match `^[A-Z]{2}[A-Z0-9]{3}\d{7}$` after `ik()` |
| `amount` | `royalty\|revenue\|amount\|earning` | numeric |
| `period` | `period\|month\|year\|quarter` | date or `Mon YYYY` text |

Rules:

* the header row is the first row where ≥ 2 columns score;
* a score below the threshold leaves the field **unmapped — never guessed**;
* the operator confirms or overrides the mapping in the UI before the run;
* the confirmed mapping is stored against the sheet's `header_fingerprint`
  (`sha256` of the normalised header row) and reused automatically next time;
* a sheet with **no** identity column is rejected with a specific error, not a silent
  empty result.

A TYPE F sheet may carry ISRC lists pipe-separated, comma-separated or one-per-row; all three
are exploded to `user_sheet_entry_isrc` rows (§16).

### 5.7 Shape-detection decision table

```
row1[0].lower() == "track name"                     -> TYPE C  catalogue
"Revenue" in row1 and "ISRC" in row1                 -> TYPE D  Spotify MRM
"Usage"   in row1 and "ISRC" in row1                 -> TYPE E  Spotify usage
row4 has "WORK INT NO" and "RADIO" and "TV"          -> TYPE B  overseas statement
row4 has "WORK INT NO"                               -> TYPE A  standard statement
any row scores >= 1 identity column (§5.6)           -> TYPE F  user sheet  (operator confirms)
otherwise                                            -> UNKNOWN -> quarantine (§21)
```

---

## 6. File classification and metadata extraction

Statement metadata is **not inside the file** — it is parsed from the filename plus the zip
timestamp. `parse_filename()` is the contract.

### 6.1 Filename grammar

```
(S-<n>)<free text describing the run>.xlsx
```

| Field | Rule | Example |
|---|---|---|
| `s_no` | `\(S-(\d+)\)` → int | `(S-13)…` → 13 |
| `dist_no` | first `[PM]\d{4}[A-Z]\d{3}` (sub-run); else `[PM]\d{4}\s+to\s+[PM]\d{4}` → `"<a> to <b>"`; else first `[PM]\d{4}`; else `""` | `P2107A008`, `P2101 to P2540`, `P2550` |
| `redis` | `"redistribution" in stem.lower()` | S-44, S-45 |
| `soc_code` | trailing `(\d{3})\s+([A-Z]{2,10})$`, code must exist in `society` | `021 BMI` |
| `p_start`, `p_end` | every `([A-Za-z]{3,12})\.?\s+(\d{4})` hit: first → period start, last → period end; if none but `F.Y. 2025-26` → 1 Apr … 31 Mar | `Jul 2025 - Sep 2025` |
| `fy` | `F\.?\s?Y\.?\s*(\d{4})\s*-\s*(\d{2,4})` | `2025-26` |
| `period` | `"<Mon> <yyyy> - <Mon> <yyyy>"` (+ ` (FY <fy>)`), else `"Not specified"` | |
| `date` | **max `date_time` over all members of the .xlsx zip** — the statement's real issue date | `2025-11-21` |
| `category` | first hit of the ladder below | |
| `section` | `"Overseas - <SOC> (<COUNTRY>)"` when Overseas and the society resolved, else the category | |

### 6.2 Category ladder (order is significant)

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

Each rung is a row in `category(code, label, matcher_regex, ordinal)` — a new revenue source
is a seed row, never a code change.

### 6.3 Society register

| Code | Society | Country |  | Code | Society | Country |
|---|---|---|---|---|---|---|
| 008 | APRA | Australia | | 101 | SOCAN | Canada |
| 021 | BMI | USA | | 104 | MACP | Malaysia |
| 023 | BUMA | Netherlands | | 106 | COMPASS | Singapore |
| 026 | CASH | Hong Kong | | 126 | MCT | Thailand |
| 058 | SACEM | France | | 128 | IMRO | Ireland |
| 080 | SUISA | Switzerland | | | | |

### 6.4 Section ordering in every output

```
SECTION_ORDER = ["YouTube Pre-Claims", "YouTube Post-Claims", "Facebook / Meta",
                 "Spotify", "Spotify MRM", "Apple Music", "Radio", "Zee TV Broadcast",
                 "Mechanical (MUSERK)", "Other / Unclassified", "Redistribution"]
```
then every `Overseas - …` section alphabetically. Inside a section, distributions are ordered
by statement date, then by section name. **The layout is data-driven** — a new upload changes
the column plan automatically. Never hard-code a column index.

---

## 7. Normalisation primitives

Implemented once in `domain/normalize.py`, shared by ingester, matcher, coverage engine,
merge engine and exporter. They are also the definitions of the generated key columns in the
database, so Python and SQL can never drift.

```python
def s(v):                       # safe string
    return "" if v is None else str(v).strip()

def num(v):                     # safe float, NaN -> 0.0
    try:
        f = float(str(v).replace(",", ""))
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0

def noi(v):                     # internal number: "16026924.0" -> "16026924"
    t = s(v)
    if not t:
        return None
    try:
        return str(int(float(t)))
    except ValueError:
        return t                # keep 'NEED TO REGISTER' verbatim - never drop an id

def ik(v):                      # ISRC key
    return re.sub(r"[^A-Z0-9]", "", s(v).upper())

def norm(v):                    # name key - case / space / punctuation blind
    return re.sub(r"[^a-z0-9]", "", s(v).lower())

VER = re.compile(r"\b(lofi|lo fi|cover|reprise|sped up|slowed|version|male|female|remix|"
                 r"theme|instrumental|unplugged|acoustic|duet|original|mix|edit|radio|sad|"
                 r"vocals|title song|from)\b")

def norm2(v):                   # name key with version words stripped - fuzzy fallback
    return re.sub(r"[^a-z0-9]", "", VER.sub(" ", s(v).lower()))
```

Financial-year helpers:

```python
fin_year(d) = d.year if d.month >= 4 else d.year - 1     # Indian FY, 1 Apr - 31 Mar
fy_label(y) = f"FY {y}-{str(y + 1)[-2:]}"                # 2025 -> 'FY 2025-26'
month_end(y, m)                                          # last calendar day of the month
```

**Penny reconciliation** — whenever one total is split into cells that are then rounded to
2 dp, the rounded cells must still add up to the unrounded total:

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
runs of the same input give byte-identical output.

> **Display rule that follows from this:** a printed total must equal the sum of the printed
> parts, not a separately rounded total. `Total Spotify MRM Revenue` in the coverage revenue
> workbook is `round(Σ round(month, 2), 2)`, not `round(Σ month, 2)` — otherwise a row shows
> six months adding to 13,307.74 beside a total of 13,307.76 (§23 D3).

---

## 8. Identity resolution — the link ladder

Everything in §11 and §12 is built on one ordered ladder. It is implemented **once**, in
`domain/link.py`, and every caller states which rungs it is allowed to use.

| Rung | Evidence | Strength | Money may be attached? |
|---|---|---|---|
| **L1** | same internal number | **certain** | yes — this is how statements pay |
| **L2** | same ISRC | **certain** | yes — this is how platforms report |
| **L3** | one side's missing identifier recovered through an **exact** `norm(name)` match that is **unique on both sides**, and that recovered identifier then matches L1/L2 | **strong** | yes, but the row is stamped with the basis |
| **L4** | exact `norm(name)` match, identifiers known on both sides and **different** | **candidate only** | **no** — this is a merge candidate (§12) |
| **L5** | `norm2(name)` match (version words stripped) | **weak candidate** | no |
| **L6** | album / UPC / period / registrant-prefix agreement | **corroborating signal only** | no |

Two hard rules:

1. **L4 and L5 never move money on their own.** They generate proposals; a human accepts
   them (§12) and the acceptance is stored. The only exception already in the data is SKV7's
   MRM name fallback (B4/B5), which is explicitly labelled in column 225 and is precisely the
   population the merge review asks the user to confirm.
2. **L3 requires uniqueness on both sides.** If a title appears twice in either source, the
   rung does not fire — because `AAJ JYOTSNA RAATEY` is two different works
   (`15628816` and `29764517`) with the same title, and a non-unique title match would have
   merged them.

---

## 9. Processing pipeline — stage by stage

```
        upload
          │
   ┌──────▼───────┐  S0  intake          sha256, dedupe, quarantine
   │ source_file  │
   └──────┬───────┘
   ┌──────▼───────┐  S1  classify        TYPE A-F, filename metadata
   │  statement   │
   └──────┬───────┘
   ┌──────▼───────┐  S2  extract         carry-forward blocks -> royalty_line
   │ royalty_line │                      three-way reconciliation
   └──────┬───────┘
   ┌──────▼───────┐  S3  catalogue       TYPE C -> catalogue_entry + recording + work
   │  catalogue   │  S3b user sheet      TYPE F -> user_sheet_entry (+ column map)
   └──────┬───────┘
   ┌──────▼───────┐  S4  platform        TYPE D -> spotify_revenue, TYPE E -> spotify_usage
   │   spotify    │
   └──────┬───────┘
   ┌──────▼───────┐  S5  row universe    catalogue backbone + statement-only + platform-only
   │    rd_row    │
   └──────┬───────┘
   ┌──────▼───────┐  S6  attach money    royalty by work no (booked once) · MRM by ISRC cascade
   │  rd_row_cell │
   └──────┬───────┘
   ┌──────▼───────┐  S7  derive          FY split, totals, audit columns
   │   rd_row.*   │
   └──────┬───────┘
   ┌──────▼───────┐  S8  mismatch        rules A/B/C with wildcards
   │   mismatch   │
   └──────┬───────┘
   ┌──────▼───────┐  S9  coverage        §11 - "not in this sheet but earning"
   │ coverage_row │
   └──────┬───────┘
   ┌──────▼───────┐  S10 merge candidates §12 - propose, user selects
   │merge_candidate│
   └──────┬───────┘
   ┌──────▼───────┐  S11 apply merges    new build, money-neutral, reversible
   │  build_run'  │
   └──────┬───────┘
   ┌──────▼───────┐  S12 export          SKV8.xlsx, coverage pair, merge list, mismatch, gaps
   │   export     │
   └──────────────┘
```

### S0 — Intake

* raw bytes to object storage keyed by `sha256`; re-uploading the same file is a no-op that
  returns the existing `source_file.id`;
* the original filename is kept verbatim — **the metadata parser depends on it**;
* shape-detection failures go to `status='quarantined'` with the first 8 rows stored as JSON.

### S1 — Classify

Decision table §5.7 + `parse_filename()` §6. One `statement` row per TYPE A/B, one
`catalogue_version` per TYPE C, one `spotify_report` per TYPE D/E, one `user_sheet` per
TYPE F.

### S2 — Extract royalty lines

```python
schema  = "Overseas" if ("RADIO" in hdr and "TV" in hdr) else "Standard"
amt_col = 17 if schema == "Overseas" else 12                 # 1-based
stop    = first row index where any cell == "TOTAL ROYALTIES"    # HARD STOP
file_total = num(grid[stop][amt_col - 1])

carry = [None] * 4                                           # WORK INT NO, TITLE, AV, LANGUAGE
for r in grid[4:stop]:                                       # sheet row 5 .. stop-1
    for c in (0, 1, 2, 3):
        if s(r[c]):
            carry[c] = r[c]
    keep = bool(s(r[10])) if schema == "Standard" else \
           bool(s(r[4]) and s(r[5]) and s(r[16]))
    if not keep:
        continue
    emit RoyaltyLine(work_no=noi(carry[0]), title=s(carry[1]), language=s(carry[3]),
                     party=s(r[4]), role=s(r[5]), society=s(r[6]),
                     own=num(r[7]), coll=num(r[8]),
                     pool=s(r[9]), source=s(r[10]),
                     buckets={...} if schema == "Overseas" else None,
                     amount=num(r[amt_col - 1]))
```

* **unparseable work id** → synthesise `?S-<n>:<raw or BLANK>` and log `ingest_anomaly`;
  never drop the money;
* **reconciliation:** `abs(Σ amount − file_total) ≤ 0.05` → PASS, else FAIL and the statement
  is not promoted into a build;
* **second, independent check:** Σ(money lines) == Σ(sub-total lines).

### S3 — Catalogue load · S3b — User sheet load

```python
for i, row in enumerate(rows[1:]):
    name, raw = s(row[0]), s(row[1])
    isrcs = [ik(x) for x in s(row[2]).split("|") if ik(x)]   # ORDER PRESERVED
    -> catalogue_entry(name, work_no=noi(raw), raw_no=raw, position=i)
    -> recording(isrc), catalogue_entry_isrc(entry, recording, ordinal)
```

`ordinal = 0` is the **primary** ISRC — the MRM cascade depends on it. A user sheet (TYPE F)
loads identically through its confirmed column map into `user_sheet_entry` /
`user_sheet_entry_isrc`; the catalogue is simply the user sheet the platform knows by name.

### S4 — Platform load

```python
mrm[(isrc, (year, month))] += num(Revenue)
mrm_name[isrc][Content Name] += num(Revenue)      # revenue-weighted; most_common() picks the title
usage[isrc] = (first non-empty Content Name, Σ Usage)
```

### S5 — Row universe

1. one row per catalogue recording — all 2,762, paid or not;
2. plus every work a statement paid that the catalogue does not list (372);
3. plus every ISRC only Spotify's revenue report knows (7);
4. plus every ISRC only Spotify's usage report knows (8);
5. → 3,149 rows (SKV7). After the §12 merges → 3,144 rows (SKV8).

Catalogue → statement linking uses **L1 only**, with L2 as a rescue for statement rows that
carry no work number at all. A song name never attaches statement money.

### S6a — Booking royalty once per work

168 catalogue recordings share one IPRS work. The money was paid once, so it is booked once:

```python
cand = [e for e in entries if norm(e.name)  == norm(target.title)] \
    or [e for e in entries if norm2(e.name) == norm2(target.title)] \
    or entries
owner[target] = cand[0]
```

Siblings get `Amount = 0.00` and column 224 explains:
`"IPRS work 15628861 - royalty booked once, on 'Tomake Chai' (INS2X1600134)"`.

### S6b — Attaching Spotify MRM revenue (ISRC-first cascade)

| Basis | Test | Reference |
|---|---|---|
| B1 `ISRC - catalogue (primary ISRC of the recording)` | ISRC == some entry's ordinal-0 ISRC | 1,269 (+116 with B2) |
| B2 `ISRC - catalogue (secondary ISRC of the recording)` | ISRC anywhere in an entry's list | 65 |
| B3 `ISRC - royalty statement work (not in the SVF list)` | ISRC sits on a statement-only row | 38 |
| B4 `Song name - catalogue` | `norm(title)` matches a catalogue name | 19 (+30 with B1) |
| B5 `Song name - royalty statement work` | `norm(title)` matches a statement-only row | 18 |
| B6 `Song name, version words stripped - catalogue` | `norm2(title)` matches | — |
| B7 `No match - song is only in Spotify's report` | its own new row | 7 |

Month rounding uses `penny_fix` twice: months → month total, month totals → report total.

> **B4/B5 are the debt this platform now repays.** They move money on a name match. SKV7
> printed the result without saying which ISRC produced it; SKV8 writes that ISRC into column
> A and the merge review (§12) asks the user to confirm the pairing.

### S7 — Derived values

* `Total Amount` (col D) = Σ every statement Amount cell on the row;
* `Total Spotify Revenue (MRM)` (col E) = Σ the 6 month cells;
* **FY split (217–221):** each distribution's amount is spread across Indian FYs in
  proportion to the months of its period falling in each FY, then `penny_fix`-ed back to the
  row total; an unparseable period lands entirely in `Period Not Stated`;
* `Total Revenue` (222) must equal col D exactly;
* **Catalogue Status (223)** — the eight-value enum:

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

* **Royalty Booked On (224)** — the sibling note, blank on 2,980 rows;
* **Spotify (MRM) Match Basis (225)** — the B1…B7 labels, `" ; "`-joined.

In SKV8 column 223 additionally carries the merge/ISRC provenance sentences of §10.3.

---

## 10. SVF-RD-SKV7 / SKV8 — full 225-column specification

One worksheet, named for its generation (`SVF-RD-SKV8`). Row 1 = merged section bands,
row 2 = column headers, rows 3…N = songs, blank row, `TOTAL` row, an FY-basis note, then a
full-width provenance note. `freeze_panes = "F3"`; autofilter `A2:HQ<last>`.

### 10.1 Identity + totals (columns 1–5)

| Col | Header | Source | Format |
|---|---|---|---|
| 1 | `ISRC` | the row's ISRCs, `" \| "`-joined in catalogue order; in SKV8, followed by any unregistered ISRC that reported revenue on this row | text |
| 2 | `Song Name` | catalogue `Track Name`; else statement `TITLE`; else Spotify `Content Name` | text |
| 3 | `Internal No` | catalogue `Internal NO`; else statement `WORK INT NO`; in SKV8 every internal number involved, `" \| "`-joined; **blank when no source carries one** | text |
| 4 | `Total Amount` | Σ all statement Amount cells on the row — royalty **distributions** only | `#,##0.00` |
| 5 | `Total Spotify Revenue (MRM)` | Σ the 6 month cells — Spotify **gross**, deliberately **not** part of col D or col 222 | `#,##0.00` |

> Column D and column E are different kinds of money and must never be added together in a
> headline total. D is what IPRS actually distributed to SVF; E is what Spotify reported as
> gross revenue on the recording. The workbook states this in its footer note.

### 10.2 Distribution sections (columns 6–216)

Every section is `4 × number_of_distributions` columns; every distribution is the same block:

| Offset | Header | Value |
|---|---|---|
| +0 | `Date` | `statement.date`, `DD-MMM-YYYY` |
| +1 | `Amount` | this row's money in that distribution, `#,##0.00` |
| +2 | `Period` | `statement.period` |
| +3 | `Distribution Number` | `statement.dist_no` or `Not specified` |

Reference column plan:

| Range | Section | Distributions |
|---|---|---|
| 6–17 | `YOUTUBE PRE-CLAIMS` | 3 |
| 18–45 | `YOUTUBE POST-CLAIMS` | 7 |
| 46–57 | `FACEBOOK / META` | 3 |
| 58–65 | `SPOTIFY - ROYALTY DISTRIBUTED BY IPRS` | 2 |
| 66–89 | `SPOTIFY - GROSS REVENUE REPORTED BY SPOTIFY (MRM report)` | 6 month blocks |
| 90–97 | `APPLE MUSIC` | 2 |
| 98–101 | `RADIO` | 1 |
| 102–113 | `ZEE TV BROADCAST` | 3 |
| 114–117 | `MECHANICAL (MUSERK)` | 1 |
| 118–133 | `OTHER / UNCLASSIFIED` | 4 |
| 134–141 | `REDISTRIBUTION` | 2 |
| 142–216 | `OVERSEAS - …` APRA · BMI · BUMA · CASH · COMPASS · IMRO(2) · MACP(3) · MCT · SACEM(3) · SOCAN(3) · SUISA | 1–3 each |
| 217–222 | `TOTAL REVENUE` — `FY 2022-23` … `FY 2025-26`, `Period Not Stated`, `Total Revenue` | |
| 223–225 | `AUDIT / TRACEABILITY` — `Catalogue Status`, `Royalty Booked On`, `Spotify (MRM) Match Basis` | |

The MRM section is **not** a statement: its blocks carry the month-end date, that month's
revenue, `"<Mon> <yyyy>"` and the report label.

### 10.3 What SKV8 changes (and what it must not)

SKV7 matched a Spotify-reported recording to a catalogue row **by song name** when its ISRC
was not registered. The money landed on the right row, but column A showed only the
registered ISRCs — and where a royalty statement had also paid the same song under a second
internal number, the workbook carried **two rows for one song**.

SKV8 applies exactly three edits, scoped to songs the coverage audit (§11) flagged as
"title in the catalogue, identifiers not":

| # | Edit | Rule |
|---|---|---|
| E1 | **Unregistered ISRC written into column A** | the ISRC Spotify reported is appended after the registered ones, `" \| "`-separated. 18 ISRCs across 18 songs |
| E2 | **Same-name rows merged** | the survivor is the row with catalogue identifiers, then the largest `Total Amount`; every numeric cell of the merged rows is **added**; each empty Date/Period/Distribution cell takes the first non-empty value from a merged row; internal numbers are `" \| "`-joined, blank when none exists anywhere. 5 rows folded into 5 songs |
| E3 | **Provenance written into column 223** | `"SKV8: merged N row(s) with the same song name (internal no …)"`, `"SKV8: ISRC … reported by Spotify but NOT registered in S-46"`, `"SKV8: internal no … paid by a statement but NOT in S-46"` |

The five merges in the reference run:

| Song | Survivor | Merged internal numbers | Column A after the merge |
|---|---|---|---|
| Cinderella Mon | r501 | `28964597 \| 26297314` | `INS2X2210002 \| USQY52429704 \| USQY52431173 \| INS2X2209002` |
| Ei Je Tomar Prem | r2418 | `29764577 \| 25809088` | `INS2X2001114 \| USQY52437614 \| INS2X2001113` |
| Leelabali | r998 | `31627630 \| 30677046` | `INS2X2400163 \| INS2X2500102 \| INS2X2403601` |
| Mathura Nagarpati | r2150 | `31627589 \| 5846855` | `INS2X1900406 \| INS2X2306001 \| INS2X2401301` |
| Roder Nishana | r583 | `28964618 \| 26297316` | `INS2X2210004 \| INS2X2209004` |

> `Leelabali` is the case that proves the merge must be a **user decision**: both internal
> numbers are registered in the catalogue as separate works. The rule as specified merges
> them and says so in column 223; the merge review (§12) is where that judgement is confirmed
> or reversed.

**Money neutrality is the acceptance test.** Measured across all 60 numeric columns of the
reference build: SKV7 column sums == SKV8 column sums, to the paisa; `TOTAL` row
`3,323,794.31` / `7,889,496.76` unchanged; 2,571 catalogue internal numbers all still
present; 0 ISRCs lost, 18 gained.

### 10.4 Sorting, totals, notes

* rows sorted by `-Total Amount`, then `-Total Spotify Revenue`, then `norm(Song Name)`;
* `TOTAL` row: label in column 2, sums for col 4, col 5, every `Amount` column, and the FY
  block — **recomputed from the visible rows, never carried over from the previous
  generation**, and asserted equal to the previous generation's totals;
* the FY-basis note sits under the FY block; the generation note is a full-width merged
  paragraph stored in `report_note`, so prose never lives in the exporter.

---

## 11. Catalogue Coverage Audit — "not in my sheet but still earning"

> **The user story.** *"Here is my song sheet. Tell me every song that is not in it and is
> still earning money from a party — Spotify, YouTube, Meta, Apple, a foreign society — and
> tell me how much, so I can register it."*

This is a first-class product surface (tab **Coverage Audit**, §18), not a script. It runs
against **any** sheet (TYPE F, §5.6) and **any** subset of ingested revenue sources.

### 11.1 Inputs and configuration

| Parameter | Meaning | Default |
|---|---|---|
| `sheet_id` | the user's song sheet (TYPE F or the catalogue) | the current `catalogue_version` |
| `sources[]` | which revenue sources count: statement categories (`spotify`, `youtube_pre`, `youtube_post`, `facebook_meta`, `apple_music`, `overseas:*`, …) and/or platform reports (`spotify_mrm`, `spotify_usage`) | all |
| `period_from` / `period_to` | restrict to money earned in a period | none |
| `mode` | `RESOLVED` (default) or `STRICT` — §11.3 | `RESOLVED` |
| `min_amount` | hide rows below a threshold | 0 |

### 11.2 The exclusion ladder

A source record (a statement work, or a platform ISRC) is **excluded** — it *is* in the
user's sheet — when any rung fires. Rungs are evaluated in order and the one that fired is
recorded on `coverage_exclusion`, so every excluded song can be explained.

| Rung | Test | Ladder rung (§8) | Reference count |
|---|---|---|---|
| **E1** | the record's own internal number is in the sheet | L1 | 1,343 statement works |
| **E2** | the record's own ISRC is in the sheet | L2 | 1,630 MRM ISRCs |
| **E3** | the record has no ISRC; an **exact, unique** title match in the platform report supplies one; that ISRC is in the sheet | L3 | 14 statement works |
| **E4** | the record has no internal number; an **exact, unique** title match in the statement supplies one; that number is in the sheet | L3 | 48 MRM ISRCs |

Everything that survives all four rungs is a **finding**.

Survivors are then merged into one row per song by `norm(name)`, so a work that reached the
platform twice (once through the statement, once through the MRM report) is one finding with
both identifiers. Reference result: **93 songs** — 13 from the statement only, 71 from the
MRM report only, 9 from both.

### 11.3 STRICT vs RESOLVED — and why both exist

| Mode | Rungs applied | Answers | Reference result |
|---|---|---|---|
| `STRICT` | E1, E2 only | *"which identifiers are absent from my sheet?"* — every unregistered ISRC is a finding even when the title is registered under another ISRC | 36 statement works + 129 MRM ISRCs |
| `RESOLVED` | E1–E4 | *"which songs are absent from my sheet?"* — a song whose identity can be resolved to a sheet entry through a unique title link is treated as present | **93 songs** |

Both are correct answers to different questions, so the mode is a switch on the run and is
printed in the workbook header. `STRICT` is the registration backlog; `RESOLVED` is the
catalogue gap. A run stores both counts so the UI can show the delta without a second pass.

### 11.4 Evidence flag on every finding

| Flag | Meaning | Reference count |
|---|---|---|
| `IDENTIFIERS ABSENT` | neither the name nor any identifier appears in the sheet | 75 |
| `NAME PRESENT, IDENTIFIERS DIFFER` | the title is in the sheet but the internal number and ISRC are not — a cover, a male/female version, a re-recording, or an unregistered recording of a registered work | **18** |

The second flag is the feed into the merge review (§12): those 18 are precisely the songs a
human must classify as *"same song, register the ISRC"* versus *"different recording"*.

### 11.5 Output 1 — the finding list

`Songs-Missing-From-SVF-List.xlsx`, sheet `Songs Not In SVF List`. **Three columns only** —
this sheet is the hand-off to whoever registers the works, and carries nothing else:

| Col | Header | Rule |
|---|---|---|
| A | `ISRC` | every ISRC the platform reported for this song, `" \| "`-joined; blank when the song reached us only through a statement |
| B | `Song Name` | the name as the source spells it |
| C | `Internal No` | every internal number a statement paid it under, `" \| "`-joined; **blank when no source carries one** |

Row 1 is a merged banner naming the sheet audited, the sources, the period and the mode.
Sorted by revenue at stake, descending. A `TOTAL` row states the finding count.

### 11.6 Output 2 — the revenue workbook

`Songs-Missing-From-SVF-List-Revenue.xlsx`, sheet `Missing Songs Revenue`, **37 columns in
the SKV band layout and the SKV colour system** (§19), so it reads like the master workbook:

| Range | Band | Columns |
|---|---|---|
| A–E | *(identity)* | `ISRC`, `Song Name`, `Internal No`, `Total Amount`, `Total Spotify Revenue (MRM)` |
| F–I | `SPOTIFY - ROYALTY DISTRIBUTED BY IPRS  (1 distribution: Oct 2025 - Mar 2026)` | `Date`, `Amount`, `Period`, `Distribution Number` |
| J–AG | `SPOTIFY - GROSS REVENUE REPORTED BY SPOTIFY (MRM report)` | 6 × (`Date`, `Amount`, `Period`, `Distribution Number`) |
| AH–AI | `TOTAL REVENUE  (Indian Financial Year, 1 Apr - 31 Mar)` | `FY 2025-26`, `Total Revenue` |
| AJ–AK | `AUDIT / TRACEABILITY` | `Present In`, `Song Name Exists In SVF List` |

Rules that make this workbook trustworthy:

1. **No figure is copied from the master workbook.** Every amount is recomputed from the
   source files. The master supplies *layout and colour only*. (This is a user requirement
   and an accuracy property: a coverage audit that quotes the artefact it is auditing cannot
   detect that artefact's errors.)
2. `Total Amount` = royalty actually distributed (statement money). `Total Spotify Revenue
   (MRM)` = gross reported revenue. Gross is **excluded** from `Total Amount` and from
   `Total Revenue`, exactly as in SKV7/SKV8.
3. A cell that the source cannot supply stays **blank** — the IPRS statement carries no
   distribution date or number, so those two cells are blank / `Not specified`. Blank is a
   fact; zero is a claim.
4. The `TOTAL` row is a live `=SUM()` over the visible rows for all 12 money columns.
5. A full-width footer note states every rule above in prose, including what blank means.

Reference totals: Spotify gross at stake **250,956.32**, IPRS royalty already received
**1,140.08**.

### 11.7 Accuracy contract

Every coverage run asserts these before the export is offered (they are invariants I14–I19,
§20):

| Check | Statement |
|---|---|
| **Leak test** | no finding's internal number appears in the user's sheet; no finding's ISRC appears in the user's sheet. Measured: 0 and 0 |
| **Population identity** | the finding list and the revenue workbook contain exactly the same songs, in the same order. Measured: 93 == 93 |
| **Recompute test** | every month cell, every total and every IPRS amount is re-derived from the raw source files by a second, independent pass and compared. Measured: 0 mismatches |
| **Conservation** | Σ(revenue of findings) + Σ(revenue of excluded records) == the source file's own total, per source |
| **Source reconciliation** | each statement's money lines == its sub-total lines == its printed `TOTAL ROYALTIES` before it may contribute |
| **Explainability** | every excluded record carries the rung that excluded it and the sheet entry it matched |
| **Determinism** | the same sheet + same sources + same mode ⇒ byte-identical workbooks |

### 11.8 Generalisation beyond Spotify

Nothing in §11 is Spotify-specific. `sources[]` selects any ingested category, and the
revenue workbook's band plan is generated the same way as SKV8's (§6.4): one band per
contributing source, four columns per distribution, the platform-report bands carrying
month blocks. A YouTube-only coverage run produces the same two workbooks with
`YOUTUBE PRE-CLAIMS` / `YOUTUBE POST-CLAIMS` bands. The only per-source knowledge the engine
needs is already in `category` and `statement`.

---

## 12. Same-Name / Different-ISRC merge review

> **The user story.** *"Show me the songs that look like the same song under different
> ISRCs or different internal numbers. Let me tick the ones that really are the same, merge
> their revenue, and give me the list."*

Auto-merging is unsafe (`AAJ JYOTSNA RAATEY` is two different works; `Leelabali` is two
catalogue registrations). Never merging is also wrong (`Bhalobashar Morshum (Male version)`
is one recording that reached SVF under two ISRCs). So the platform **proposes**, the user
**decides**, and the decision is **stored, applied to a new build, and reversible**.

### 12.1 Candidate generation

Over the rows of a build (and, for a coverage run, over its findings):

```python
group_exact = defaultdict(list)     # norm(name)  -> rows
group_fuzzy = defaultdict(list)     # norm2(name) -> rows      (version words stripped)
```

A group becomes a **candidate** when it holds more than one row **and** the rows disagree on
at least one identifier. Candidate kinds:

| Kind | Definition | Reference count |
|---|---|---|
| `SAME_NAME_DIFF_ISRC` | same `norm(name)`, different ISRC sets | the dominant kind |
| `SAME_NAME_DIFF_INTERNAL_NO` | same `norm(name)`, different internal numbers | e.g. `Ei Je Tomar Prem` |
| `SAME_NAME_NO_IDENTIFIER` | same `norm(name)`, one side has no identifier at all | the statement-only rows |
| `VERSION_VARIANT` | same `norm2(name)`, different `norm(name)` — `(Male version)` vs `(Female Version)` | proposal only, **never** auto-suggested |

Measured on SKV8: **168 name groups covering 402 rows**.

### 12.2 Signals and the confidence score

Each candidate group is scored from evidence the platform already holds. The score is
advisory — it orders the queue and sets the default tick — and every component is shown.

| Signal | Weight | Source |
|---|---|---|
| identical `norm(name)` | +0.30 | required for the exact kinds |
| same album name / UPC in the platform report | +0.25 | TYPE D/E |
| same IPRS work number on one side and no conflicting number on the other | +0.20 | statements |
| ISRC registrant prefix identical (`INS2X…` first 5) | +0.10 | ISRC structure |
| revenue periods disjoint (looks like a re-registration, not two live recordings) | +0.10 | MRM months |
| both identifiers registered in the user's sheet as **separate** entries | **−0.40** | the sheet |
| version words differ (`Male` vs `Female`, `Cover`, `Lofi`) | **−0.50** | `norm` vs `norm2` |

Bands: `≥ 0.70` **suggested**, `0.40–0.69` **review**, `< 0.40` **unlikely** (shown, never
pre-ticked). `Leelabali` scores below the suggestion band because both numbers are separately
registered — which is exactly the outcome that forces a human to look.

### 12.3 The review surface

For every candidate the UI shows, side by side: each row's ISRC list, internal number, song
name as each source spells it, album, the revenue each row carries per source and per month,
and the audit basis that attached it (B1…B7). The user then:

* ticks the rows that are the same song (partial selection inside a group is allowed);
* chooses the **surviving identity** — which name, which internal number leads, which ISRC is
  primary (default: the sheet-registered row, then the largest `Total Amount`);
* or marks the group **`NOT THE SAME`**, which suppresses it permanently and is itself a
  stored decision, so the same question is never asked twice.

### 12.4 Applying the decisions

Applying never edits a delivered build. It creates a **new build** whose `parent_build_id`
points at the reviewed one, and writes `merge_decision` / `merge_decision_member` rows. The
merge itself is exactly the SKV8 E2 rule (§10.3):

* numeric cells **added**;
* Date / Period / Distribution Number: first non-empty wins;
* ISRCs `" \| "`-joined, catalogue-registered first, then the unregistered ones;
* internal numbers `" \| "`-joined, blank when none exists;
* column 223 records the merge in prose.

**Money neutrality is asserted, not assumed:** every numeric column of the new build must sum
to the same value as the parent build, to the paisa (invariant I20). A merge that changes a
total is a bug and aborts the apply.

**Reversibility:** because decisions are data and builds are immutable, un-ticking a group
and re-applying produces a build identical to the one before that decision existed. The UI
shows the decision log with who decided, when, and on what evidence.

### 12.5 Output — the merge list

`Same-Name-Different-ISRC.xlsx`, sheet `Same Name Diff ISRC`:

| Col | Header | Content |
|---|---|---|
| A | `Group` | group number |
| B | `Song Name` | the surviving name |
| C | `Name As Each Source Spells It` | `" \| "`-joined distinct spellings |
| D | `ISRCs In This Group` | `" \| "`-joined |
| E | `Internal Numbers In This Group` | `" \| "`-joined, blank when none |
| F | `Kind` | the candidate kind |
| G | `Confidence` | score + the signals that produced it |
| H | `Decision` | `MERGED` / `NOT THE SAME` / `PENDING`, with who and when |
| I | `Royalty Before` / J `Royalty After` | per-row and merged `Total Amount` |
| K | `Spotify Revenue Before` / L `After` | same for column E |
| M | `In The User's Sheet?` | which identifiers are registered and which are not |

This is the workbook that answers *"give me the list of songs that have the same name and
just a different ISRC"* — whether or not the user chooses to merge them.

---

## 13. Song-ID-Mismatch report — V1 and V2

Where §11 asks *"what is missing from the sheet?"* and §12 asks *"what is the same song?"*,
§13 asks *"where do the three sources disagree about a song they all know?"*

### 13.1 Inputs

| Alias | File | Fields contributed | Records |
|---|---|---|---|
| S2 | `(S-46)SVF list of Song -April 2026.xlsx` | name + internal no + ISRC list | 2,762 |
| S3 | `Spotify - for the Period October 2025 to March 2026.xlsx` | name + internal no | 1,389 |
| S4 | `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | name + ISRC | 1,792 distinct `(norm(name), isrc)` |

### 13.2 The three rules

Two fields agree → the third disagreeing is the finding. A field a source does not carry is a
wildcard (§4).

| Rule | Match on | Reports | Rows |
|---|---|---|---|
| **A** | Song Name + ISRC | `Different Internal Number` | 121 |
| **B** | Song Name + Internal No | `Different ISRC` | 245 |
| **C** | Internal No + ISRC | `Different Song Name` | 415 |

```python
gA[(norm(name), isrc)]   += records carrying that name and that ISRC
gB[(norm(name), no)]     += records carrying that name and that internal number
gC[(no, isrc)]           += records carrying both
name_only[norm(name)]    = records with NO ISRC            (statement)  -> wildcard into gA
noint_by_name[norm(nm)]  = records with NO internal number (Spotify)    -> wildcard into gB
no_only[no]              = records with NO ISRC                          -> wildcard into gC
isrc_only[isrc]          = records with NO internal number               -> wildcard into gC
```

Two extra passes handle the all-wildcard case — a title (or a work) for which no record
anywhere carries an ISRC; there the ISRC condition is vacuous, so the name alone (rule A) or
the number alone (rule C) decides. Rule B skips any group where no record carries an ISRC:
"different ISRC" is meaningless with nothing to compare.

### 13.3 Identity row selection (`pick`)

```
0. a record that actually carries the disputed field      (before one that does not)
1. a record from the user's sheet / catalogue (S2)        (before any other source)
2. a record that matched on BOTH key fields               (before a wildcard joiner)
3. source priority  S2 < S4 < S3
4. original row order
```

### 13.4 Value merging — one row per `(identity record, mismatch kind)`

```python
key = (main.source, main.row_ordinal, kind)
bucket = merged.setdefault(key, {"vals": {}, "sheets": set()})
for v in conflicting_values:
    bucket["vals"].setdefault(norm(v) if kind == "name" else v, v)   # de-dupe, keep 1st spelling
bucket["sheets"] |= sources_that_supplied_those_values
```

* names de-duplicate on `norm()` — `AMARE TUMI` and `Amare Tumi` are one value;
* a record's own value can never enter its own conflict list;
* 844 raw groups → **781 rows**.

### 13.5 Column layouts

**V1 `Song-ID-Mismatch-Report.xlsx`**, sheet `Song ID Mismatches`, freeze `A2`:
`S. No` · `ISRC (as per SVF Song List)` · `Song Name (as per SVF Song List)` ·
`Internal No. (as per SVF Song List)` · `Type of Mismatch` · `Conflicting Value(s) Found` ·
`Sheet(s) Where the Conflict Was Found`. Sorted by kind, then `norm(name)`, then number.

**V2 `Song-ID-Mismatch-Report-V2-With-Revenue.xlsx`** adds three columns under peach bands
naming the file and its total:

| Col | Header | Rule |
|---|---|---|
| H | `Royalty Paid on This Song` | the statement royalty of the row's work number |
| I | `Gross Revenue on This Song` | Σ MRM revenue of the row's ISRCs |
| J | `Total (Both Files)` | H + I |

**Booking rule:** a work number is booked to the first row that carries it, an ISRC to the
first row that lists it; later rows show `0.00`. Without it the 148 shared work numbers
multiply the money. TOTAL row: `61,206.05`, `3,722,218.78`, `3,783,424.83`.

---

## 14. Gap lists and the statement register

Companion workbooks, all derived from the same tables — never recomputed by hand.

| File | Sheet | Rows | Shape |
|---|---|---|---|
| `Works-Paid-But-Missing-From-SVF-Song-List.xlsx` | `Missing-From-SVF-List` | 336 | work no · name · ISRC · ISRC provenance · total royalty · Spotify revenue · one column per category |
| `Spotify-Revenue-But-Missing-From-SVF-Song-List.xlsx` | `Spotify-Revenue-Only` | 53 | name · ISRC · album · total + 6 monthly revenues · streams · IPRS royalty · match basis |
| `Spotify-Streams-Only-Missing-From-SVF-Song-List.xlsx` | `Spotify-Streams-Only` | 13 | name · ISRC · album · total + monthly streams · revenue · royalty |
| `Statement-SKV4.xlsx` | `Statement-SKV4` | 46 + summaries | file · distribution number · category · period · FY · date · works · lines · total · % of grand total |

These are **views of the coverage engine** (§11) with a fixed configuration, and V2 keeps
them only for continuity: new work should use a coverage run, which carries the mode, the
evidence flag and the accuracy contract that these older workbooks predate.

---

## 15. Database design

**Engine:** PostgreSQL 16 — exact `NUMERIC` money, generated columns for the normalisation
keys, expression indexes for name matching, partial unique indexes for the primary-ISRC rule,
window functions for book-once.

**Money:** `NUMERIC(18,6)` stored (Spotify sends 12+ decimals), `NUMERIC(18,2)` presented.
Never `float`.

### 15.1 Entity overview

```
ingest_batch ──< source_file ──┬─< statement ──< royalty_line >── work
                               │                └─< statement_pool_summary
                               │                └─< statement_language_summary
                               ├─< catalogue_version ──< catalogue_entry >── work
                               │                            └─< catalogue_entry_isrc >── recording
                               ├─< user_sheet ──┬─< user_sheet_column_map
                               │                └─< user_sheet_entry >── work
                               │                      └─< user_sheet_entry_isrc >── recording
                               └─< spotify_report ──┬─< spotify_revenue >── recording
                                                    └─< spotify_usage   >── recording

build_run ──┬─< rd_row ──┬─< rd_row_isrc >── recording
            │            ├─< rd_row_amount >── statement
            │            ├─< rd_row_mrm (month, amount)
            │            └─< rd_row_fy  (fy, amount)
            ├─< mismatch ──┬─< mismatch_value
            │              └─< mismatch_source
            ├─< merge_candidate ──< merge_candidate_member
            ├─< merge_decision  ──< merge_decision_member
            ├─< coverage_run ──┬─< coverage_row ──< coverage_row_isrc
            │                  └─< coverage_exclusion
            └─< export_artifact
```

### 15.2 DDL — the V2 additions

The V1 schema (`society`, `category`, `ingest_batch`, `source_file`, `work`, `recording`,
`catalogue_version`, `catalogue_entry`, `catalogue_entry_isrc`, `statement`, `royalty_line`,
`statement_pool_summary`, `spotify_report`, `spotify_revenue`, `spotify_usage`, `build_run`,
`rd_row`, `rd_row_isrc`, `rd_row_amount`, `rd_row_mrm`, `rd_row_fy`, `mismatch`,
`mismatch_main_isrc`, `mismatch_value`, `mismatch_source`, `export_artifact`,
`ingest_anomaly`) is carried forward unchanged. V2 adds:

```sql
-- ------------------------------------------------ TYPE F: any sheet the user uploads
CREATE TABLE user_sheet (
    id              BIGSERIAL PRIMARY KEY,
    source_file_id  BIGINT NOT NULL REFERENCES source_file(id),
    label           TEXT   NOT NULL,              -- 'SVF list of Song - April 2026'
    header_fp       TEXT   NOT NULL,              -- sha256 of the normalised header row
    row_count       INT    NOT NULL,
    is_catalogue    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON user_sheet (header_fp);

CREATE TABLE user_sheet_column_map (                -- confirmed, reused by fingerprint
    sheet_id    BIGINT NOT NULL REFERENCES user_sheet(id) ON DELETE CASCADE,
    field       TEXT   NOT NULL CHECK (field IN
                ('song_name','internal_no','isrc','amount','period')),
    col_index   INT    NOT NULL,
    confidence  NUMERIC(4,3) NOT NULL,
    confirmed_by TEXT,
    PRIMARY KEY (sheet_id, field)
);

CREATE TABLE user_sheet_entry (
    id          BIGSERIAL PRIMARY KEY,
    sheet_id    BIGINT NOT NULL REFERENCES user_sheet(id) ON DELETE CASCADE,
    ordinal     INT    NOT NULL,
    name        TEXT   NOT NULL,
    name_key    TEXT   GENERATED ALWAYS AS (regexp_replace(lower(name),'[^a-z0-9]','','g')) STORED,
    raw_no      TEXT,                               -- 'NEED TO REGISTER' survives here
    work_id     BIGINT REFERENCES work(id),
    UNIQUE (sheet_id, ordinal)
);
CREATE INDEX ON user_sheet_entry (sheet_id, name_key);
CREATE INDEX ON user_sheet_entry (work_id);

CREATE TABLE user_sheet_entry_isrc (                -- the '|' list, exploded
    entry_id     BIGINT NOT NULL REFERENCES user_sheet_entry(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    ordinal      INT    NOT NULL,                   -- 0 = primary
    PRIMARY KEY (entry_id, recording_id)
);
CREATE UNIQUE INDEX ON user_sheet_entry_isrc (entry_id, ordinal);

-- ------------------------------------------------ §11 coverage audit
CREATE TABLE coverage_run (
    id              BIGSERIAL PRIMARY KEY,
    build_id        BIGINT NOT NULL REFERENCES build_run(id),
    sheet_id        BIGINT NOT NULL REFERENCES user_sheet(id),
    mode            TEXT   NOT NULL CHECK (mode IN ('STRICT','RESOLVED')),
    sources         JSONB  NOT NULL,                -- category codes + report kinds
    period_from     DATE, period_to DATE,
    min_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,
    finding_count   INT, strict_count INT, resolved_count INT,
    revenue_at_risk NUMERIC(18,2), royalty_received NUMERIC(18,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (build_id, sheet_id, mode, sources, period_from, period_to, min_amount)
);

CREATE TABLE coverage_row (
    id            BIGSERIAL PRIMARY KEY,
    run_id        BIGINT NOT NULL REFERENCES coverage_run(id) ON DELETE CASCADE,
    ordinal       INT    NOT NULL,
    song_name     TEXT   NOT NULL,
    name_key      TEXT   NOT NULL,
    work_ids      BIGINT[] NOT NULL DEFAULT '{}',   -- pipe-joined only at export time
    evidence      TEXT   NOT NULL CHECK (evidence IN
                  ('IDENTIFIERS ABSENT','NAME PRESENT, IDENTIFIERS DIFFER')),
    present_in    TEXT   NOT NULL,                  -- 'statement' | 'platform' | 'both'
    royalty       NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_rev  NUMERIC(18,2) NOT NULL DEFAULT 0,
    UNIQUE (run_id, ordinal)
);

CREATE TABLE coverage_row_isrc (
    row_id       BIGINT NOT NULL REFERENCES coverage_row(id) ON DELETE CASCADE,
    recording_id BIGINT NOT NULL REFERENCES recording(id),
    ordinal      INT    NOT NULL,
    PRIMARY KEY (row_id, recording_id)
);

CREATE TABLE coverage_exclusion (                   -- why a record is NOT a finding
    run_id       BIGINT NOT NULL REFERENCES coverage_run(id) ON DELETE CASCADE,
    src_kind     TEXT   NOT NULL,                   -- 'statement_work' | 'platform_isrc'
    src_ref      TEXT   NOT NULL,                   -- work no or ISRC
    rung         TEXT   NOT NULL CHECK (rung IN ('E1','E2','E3','E4')),
    matched_entry BIGINT REFERENCES user_sheet_entry(id),
    PRIMARY KEY (run_id, src_kind, src_ref)
);

-- ------------------------------------------------ §12 merge review
CREATE TABLE merge_candidate (
    id          BIGSERIAL PRIMARY KEY,
    build_id    BIGINT NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    kind        TEXT   NOT NULL CHECK (kind IN ('SAME_NAME_DIFF_ISRC',
                'SAME_NAME_DIFF_INTERNAL_NO','SAME_NAME_NO_IDENTIFIER','VERSION_VARIANT')),
    name_key    TEXT   NOT NULL,
    confidence  NUMERIC(4,3) NOT NULL,
    signals     JSONB  NOT NULL,                    -- every component of the score
    UNIQUE (build_id, kind, name_key)
);

CREATE TABLE merge_candidate_member (
    candidate_id BIGINT NOT NULL REFERENCES merge_candidate(id) ON DELETE CASCADE,
    rd_row_id    BIGINT NOT NULL REFERENCES rd_row(id),
    PRIMARY KEY (candidate_id, rd_row_id)
);

CREATE TABLE merge_decision (
    id            BIGSERIAL PRIMARY KEY,
    candidate_id  BIGINT NOT NULL REFERENCES merge_candidate(id),
    verdict       TEXT   NOT NULL CHECK (verdict IN ('MERGE','NOT_THE_SAME')),
    survivor_row  BIGINT REFERENCES rd_row(id),
    decided_by    TEXT   NOT NULL,
    decided_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    note          TEXT,
    UNIQUE (candidate_id)
);

CREATE TABLE merge_decision_member (                -- partial selection inside a group
    decision_id BIGINT NOT NULL REFERENCES merge_decision(id) ON DELETE CASCADE,
    rd_row_id   BIGINT NOT NULL REFERENCES rd_row(id),
    PRIMARY KEY (decision_id, rd_row_id)
);

ALTER TABLE build_run  ADD COLUMN parent_build_id BIGINT REFERENCES build_run(id);
ALTER TABLE rd_row     ADD COLUMN merged_from_decision BIGINT REFERENCES merge_decision(id);
```

### 15.3 Why this shape has no duplication

* **one fact, one row** — an amount lives once in `royalty_line`; every report reads it;
* **identifiers are entities** — `work` and `recording` are referenced, never re-typed, so
  "the same ISRC written twice with different spacing" cannot exist;
* **decisions are data** — a merge is a `merge_decision`, not an edited cell, so it can be
  listed, audited and reversed;
* **builds are immutable** — a correction is a new `build_run` with `parent_build_id`, so an
  exported workbook always maps to an exact input set and decision set;
* **the user's sheet is a first-class input** — the catalogue is simply the `user_sheet` with
  `is_catalogue = true`, which is what makes §11 work for any sheet.

---

## 16. The "|" rule — pipes live in the export, never in the database

The `|` appears in the deliverables in five places: catalogue column C, SKV column A, SKV
column C (new in SKV8), the mismatch report's value/source columns, and the coverage
workbooks' ISRC/internal-number columns.

**None of them is ever stored as a pipe-joined string.** Each is a child table with one row
per element (`catalogue_entry_isrc`, `user_sheet_entry_isrc`, `rd_row_isrc`,
`coverage_row_isrc`, `mismatch_value`, `mismatch_source`, `rd_row.work_ids`). A pipe string
cannot be indexed, joined, de-duplicated or counted.

Joining is a **presentation function**, applied only in the export/serialiser layer:

```python
JOIN = " | "

def join_isrcs(rows):    # ordered by ordinal - the primary ISRC stays first
    return JOIN.join(r.isrc for r in sorted(rows, key=lambda r: r.ordinal)) or ""

def join_nos(nos):       # registered numbers first, then the unregistered ones
    return JOIN.join(nos)                       # "" when the song has none anywhere

def join_values(vals):   # mismatch values - sorted, unique by value_key
    return JOIN.join(v.value_text for v in sorted(vals, key=lambda v: v.value_text))
```

Splitting on input is the mirror image: `[ik(x) for x in cell.split("|") if ik(x)]`,
preserving order so `ordinal = 0` stays primary. A `|` is never produced inside a song
*name*; names are stored and exported verbatim.

**Empty is empty.** When a song has no internal number in any source, column C is blank — not
`-`, not `0`, not `N/A`. The coverage list and SKV8 both depend on this: a blank cell means
"no source carries one", and that is actionable information.

---

## 17. Backend architecture

### 17.1 Stack

| Concern | Choice | Why |
|---|---|---|
| API | FastAPI (Python 3.12) + Pydantic v2 | the extraction/matching logic is already Python + `openpyxl` |
| ORM / migrations | SQLAlchemy 2 + Alembic | |
| Async jobs | Celery + Redis | a 46-file build takes minutes |
| Excel | `openpyxl` (write), read-only + `calculate_dimension()` repair (read) | identical to the proven scripts |
| Object storage | S3 / MinIO | raw uploads + generated artefacts |
| Auth | OIDC or session + RBAC (`viewer`, `analyst`, `admin`) | only `analyst`+ may record a merge decision |

### 17.2 Module layout

```
app/
  core/            config, logging, security, errors
  domain/
    normalize.py     s, num, noi, ik, norm, norm2, penny_fix, fin_year, fy_label
    filename.py      parse_filename, category ladder, society register
    sniff.py         shape detection (§5.7) + TYPE F auto-mapping (§5.6)
    link.py          the L1..L6 ladder (§8) - the ONLY place identity is decided
  ingest/
    reader.py        workbook -> grid, dimension repair
    statement.py     TYPE A/B extractor, hard stop at TOTAL ROYALTIES, 3-way reconciliation
    catalogue.py     TYPE C
    usersheet.py     TYPE F
    spotify.py       TYPE D/E
  build/
    universe.py      S5 row universe
    linker.py        catalogue <-> statement linking, book-once owner selection
    mrm.py           B1..B7 cascade, penny_fix month rounding
    fy.py            split_period, FY allocation
    status.py        catalogue_status / booked_note / mrm_basis
  coverage/
    engine.py        E1..E4 exclusion ladder, STRICT/RESOLVED, evidence flags
    revenue.py       per-finding revenue recomputed from source files
  merge/
    candidates.py    grouping, signals, confidence
    apply.py         new build from decisions, money-neutrality assertion
  mismatch/
    engine.py        rules A/B/C, wildcard passes, pick(), merge
    revenue.py       book-once attribution for V2
  export/
    skv.py           the 225-column writer (SKV7/SKV8/next)
    coverage_xlsx.py the finding list + the revenue workbook
    merge_xlsx.py    the same-name/different-ISRC list
    mismatch_xlsx.py V1 + V2
    gaps.py          the companion workbooks
    style.py         every fill, font, border, width and number format (§19)
  api/ jobs/ tests/
```

### 17.3 REST API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/batches` | create a batch |
| `POST` | `/api/batches/{id}/files` | multipart upload; returns `{id, sha256, duplicate, detected_kind}` |
| `PATCH` | `/api/files/{id}` | operator override of kind / category / dist_no / period / society |
| `POST` | `/api/sheets` | register an uploaded file as a TYPE F song sheet |
| `GET` / `PATCH` | `/api/sheets/{id}/mapping` | proposed column map / confirm-override |
| `POST` | `/api/batches/{id}/classify` · `/extract` | S1 · S2–S4 → jobs |
| `GET` | `/api/batches/{id}/validation` | per statement: extracted vs printed total, PASS/FAIL, anomalies |
| `POST` | `/api/batches/{id}/builds` | S5–S8 → `build_run` |
| `GET` | `/api/builds/{id}` · `/rows` · `/rows/{rowId}` | status/totals · paginated SKV rows · one row with full provenance |
| `POST` | `/api/builds/{id}/coverage` | body: `{sheet_id, sources[], period, mode, min_amount}` → `coverage_run` |
| `GET` | `/api/coverage/{id}` · `/rows` · `/exclusions?src_ref=` | summary · findings · why a song was excluded |
| `GET` | `/api/builds/{id}/merge-candidates?kind=&min_confidence=` | the review queue |
| `POST` | `/api/builds/{id}/merge-decisions` | body: `[{candidate_id, verdict, survivor_row, members[]}]` |
| `POST` | `/api/builds/{id}/apply-merges` | → **new** `build_run` with `parent_build_id` |
| `GET` | `/api/builds/{id}/mismatches` · `/gaps/{which}` · `/statements` | |
| `POST` / `GET` | `/api/builds/{id}/exports/{artifact}` | generate → job · stream/302 signed URL |
| `GET` | `/api/jobs/{id}` | `queued\|running\|succeeded\|failed`, progress, log tail |

Every list endpoint: cursor pagination, `X-Total-Count`, deterministic ordering. Every
response that represents a pipe column returns an **array**, never a joined string.

### 17.4 Job orchestration

```
classify_batch -> extract_files (fan-out per file) -> chord ->
build_universe -> attach_money -> attach_mrm -> derive_fy_status ->
run_mismatch -> build_merge_candidates ->
[export_skv, export_mismatch_v1, export_mismatch_v2, export_gaps]

coverage_run      -> export_coverage_list + export_coverage_revenue
apply_merges      -> new build_run -> the whole build chain again
```

Rules: every task is idempotent and keyed by `(batch_id, file_id)`; a failed file marks
itself failed without aborting the batch; a build refuses to start while any statement has
`reconciled = false` unless `?force=true`, which is recorded in `build_run.config`; a build
takes an advisory lock on `batch_id`.

---

## 18. Frontend architecture — the tabs

React 18 + TypeScript + Vite · TanStack Query · TanStack Table + `react-virtual`
(225 columns × 3,144 rows demands virtualisation) · Tailwind + shadcn/ui · Recharts.

| Tab | Contents |
|---|---|
| **Batches** | list, create, per-batch counts, last build status |
| **Upload** | drag-and-drop; per-file card with detected kind, parsed distribution number / category / period / society / statement date; duplicate badge on a repeated `sha256`; inline override; Classify and Extract |
| **My Sheets** | every TYPE F sheet the user has uploaded, its column map (proposed vs confirmed), row count, and which coverage runs used it. The catalogue appears here as the sheet flagged *catalogue* |
| **Validation** | one row per statement: file, category, distribution, schema, lines, extracted, printed total, difference, PASS/FAIL; anomaly drawer; a build is blocked while a FAIL is unresolved |
| **RD Viewer (SKV8)** | virtualised grid, sticky identity columns, sticky 2-row header with the merged bands, section collapse/expand, search over ISRC/name/work no, filters on catalogue status and amount; row click → drawer with every non-zero distribution, its statement file, period, distribution number, the FY split, the three audit fields, and — new in V2 — the merge decision that produced the row, with an **Undo this merge** action |
| **Coverage Audit** *(new, §11)* | **1.** pick the sheet · **2.** tick the revenue sources (Spotify, YouTube Pre/Post, Meta, Apple, Zee, Mechanical, each overseas society, plus the platform reports) · **3.** period and mode (`RESOLVED` / `STRICT`, with both counts shown live) · **4.** Run. Result: a summary strip (findings · revenue at stake · royalty already received · how many have a name in the sheet), a findings table (ISRC · Song Name · Internal No · revenue by source), an **Explain** drawer on any song showing which rung would have excluded it and against which sheet entry, and two downloads — the 3-column list and the SKV-styled revenue workbook |
| **Merge Review** *(new, §12)* | the candidate queue ordered by confidence. Each card shows every row side by side — ISRC list, internal number, each source's spelling, album, revenue by source and month, the MRM match basis — with the signal chips that produced the score. Actions: tick rows, choose the surviving identity, **Merge**, or **Not the same**. A decision log lists who decided what and when, each entry reversible. "Apply merges" creates the next build and shows the money-neutrality assertion result before the new build is published |
| **Mismatch Report** | tabs `All / Different ISRC / Different Internal Number / Different Song Name`; conflicting values as chips, never pipe strings; a chip opens the record that supplied it; V2 toggle adds the revenue columns and a sticky total bar |
| **Gap lists · Statements** | the companion lists and the statement register with per-category totals |
| **Exports** | one card per artefact: generate, progress, size, `sha256`, download; history per build |

### 18.1 UI rules that mirror the data rules

* pipe-joined strings are **never** rendered — the API returns arrays and the UI renders
  chips; the pipe exists only inside the downloaded `.xlsx`;
* money is right-aligned `#,##0.00`; a `0.00` produced by the book-once rule is greyed with a
  tooltip naming the row that carries the money;
* a **blank** identifier renders as an empty cell with a muted "not in any source" tooltip —
  never as `0` or `-`;
* the eight catalogue-status values have eight fixed colours used identically everywhere;
* anything decided by a song name — an MRM B4/B5 match, an L3 link, a merge — carries a
  visible basis chip. The user can always see when a name moved money.

---

## 19. Excel export engine and the SKV visual system

### 19.1 The SKV colour system (measured from `SVF-RD-SKV7.xlsx`, reproduced exactly in every V2 workbook)

| Element | Band / header fill | Data-row tint |
|---|---|---|
| Identity columns (ISRC · Song Name · Internal No · totals) | `D9D9D9` | alternating `F2F2F2` / none |
| `YOUTUBE PRE-CLAIMS` | `E7C3D8` | `F9E9F2` |
| `YOUTUBE POST-CLAIMS` | `CBC1E0` | `EEEAF7` |
| `FACEBOOK / META` · `SPOTIFY - GROSS REVENUE (MRM)` | `B7CBE4` | `E6EDF7` |
| `SPOTIFY - ROYALTY DISTRIBUTED BY IPRS` | `BFD9BF` | `E8F2E8` |
| `APPLE MUSIC` | `E0B4B4` | `F7E7E7` |
| `RADIO` | `E6CBA6` | `F9F0E2` |
| `ZEE TV BROADCAST` | `ADCECA` | `E6F1EF` |
| `MECHANICAL (MUSERK)` | `DAD7A0` | `F3F2DF` |
| `OTHER / UNCLASSIFIED` | `CFCFCF` | `EFEFEF` |
| `REDISTRIBUTION` | `D5BFA7` | `F2E9DE` |
| Overseas — APRA/SACEM `B9C4D6`·`E9EDF4` · BMI/SOCAN `C2CFB8`·`ECF1E8` · BUMA/SUISA `DCC0C0`·`F5EAEA` · CASH `C9C2D9`·`EFECF5` · COMPASS `DBCEB1`·`F5F0E5` · IMRO `B3CDD1`·`E7F0F2` · MACP `D2BFCE`·`F2E9F0` · MCT `C9CDA8`·`F0F1E3` | | |
| `TOTAL REVENUE` | band `C9B99B`, header `D8CBB3` | `E8F2E8` |
| `AUDIT / TRACEABILITY` | `D8CBB7` | `F0E9DC` |

Typography and geometry: band row bold 12 pt `1F1F1F`, centred, height 22; header row bold,
centred, wrapped, height 30, thin `BFBFBF` borders; a **medium `808080` left border** marks
every band boundary on the header rows and on every data row; money `#,##0.00`; dates
`DD-MMM-YYYY`; widths ISRC 34, Song Name 42, Internal No 13, totals 15/21, then Date 13,
Amount 12, Period 22–26, Distribution Number 15–24; `freeze_panes` after the identity block;
autofilter over the header row to the last data row.

Every colour lives in `export/style.py` as a named token. A new section gets a token, not a
hard-coded hex.

### 19.2 Writer contract

1. build the band plan from the database (`statement` ordered by section then date) — never
   from a constant;
2. write row 1 bands + merges, row 2 headers, widths, heights;
3. stream rows in `rd_row.row_ordinal` order;
4. write the `TOTAL` row (recomputed from the rows just written), the basis note and the
   provenance note;
5. `freeze_panes`, `auto_filter`;
6. save to a temp file, `sha256`, upload, insert `export_artifact`.

**Determinism:** same build ⇒ identical `sha256`. No timestamps inside the sheet, sorted
iteration everywhere, `penny_fix` the only rounding path.

**Editing an existing workbook** (how SKV8 is produced from SKV7): copy the file, mutate
cells in place, then — because deleting rows shifts everything below — recompute the
alternating identity stripe, re-derive the `TOTAL` row position, and re-point the footer
note rows. Row bookkeeping after a delete is the single easiest thing to get wrong here
(§23 D2); the writer therefore locates the `TOTAL` row and the note rows **by content**,
never by arithmetic on the original row numbers.

---

## 20. Accuracy model — invariants and reconciliation

Every build, coverage run and merge apply asserts these. A failure aborts and surfaces the
offending rows.

| # | Invariant | Reference value |
|---|---|---|
| I1 | per statement `abs(Σ royalty_line.amount − file_total) ≤ 0.05` | 46/46 PASS |
| I2 | per statement Σ money lines == Σ sub-total lines == printed `TOTAL ROYALTIES` | `113,848.57` on the Spotify statement |
| I3 | extraction stops before the `TOTAL ROYALTIES` row | last work = `0.37`, not `113,848.57` |
| I4 | `Σ rd_row.total_amount == Σ statement.file_total` | `3,323,794.31` |
| I5 | `Σ rd_row.total_mrm == Σ spotify_revenue.revenue` | `7,889,496.76` |
| I6 | `Σ rd_row_fy.amount == Σ rd_row.total_amount` | `3,323,794.31` |
| I7 | every catalogue entry has exactly one `rd_row` | 2,762 |
| I8 | every IPRS work with money is booked on exactly one row | 168 siblings at `0.00` |
| I9 | every MRM month column sums to that month's reported total | `penny_fix` |
| I10 | no `mismatch_value` equals its own row's main value | 0 violations |
| I11 | no two `mismatch` rows share `(main_ref, kind)` | 844 groups → 781 rows |
| I12 | mismatch V1 and V2 have identical A–G content and row count | 781 == 781 |
| I13 | V2 column H ≤ IPRS file total, column I ≤ MRM file total, TOTAL == column sums | `61,206.05` · `3,722,218.78` · `3,783,424.83` |
| **I14** | **coverage leak test — no finding's internal number is in the audited sheet** | **0** |
| **I15** | **coverage leak test — no finding's ISRC is in the audited sheet** | **0** |
| **I16** | **coverage list and coverage revenue workbook hold the same songs in the same order** | **93 == 93** |
| **I17** | **every coverage amount re-derived from the raw source files by an independent pass** | **0 mismatches** |
| **I18** | **Σ(finding revenue) + Σ(excluded revenue) == the source's own total, per source** | MRM `7,889,496.76` |
| **I19** | **every excluded record carries the rung (E1–E4) and the sheet entry that excluded it** | 3,035 exclusions |
| **I20** | **a merge apply changes no column total** | 60/60 numeric columns identical SKV7 → SKV8 |
| **I21** | **a merge loses no identifier** | internal numbers 2,902 → 2,902; ISRCs 4,332 → 4,350 (+18 by design) |
| **I22** | **every catalogue internal number still resolves to a row after a merge** | 2,571 / 2,571 |
| **I23** | **after apply, no candidate group still spans more than one row unless the user said `NOT_THE_SAME`** | 0 |
| **I24** | **a printed total equals the sum of the printed parts (monthly cells vs their total)** | 93/93 rows |
| **I25** | **same inputs + same decisions ⇒ byte-identical exports** | `sha256` equality |

**Independent re-derivation.** The test suite recomputes I14–I18 and I10–I13 from the raw
input files with a deliberately different implementation (pairwise comparison instead of
grouping; per-ISRC accumulation instead of per-song) and compares. A number that only one
implementation produces is not trusted.

**The two-parser rule.** Any figure that reaches a deliverable must be produced by the
ingestion path *and* checked against the file's own printed totals. Both silent-money bugs in
§23 were caught by exactly this rule, and both would have been invisible to a single-parser
test suite.

---

## 21. Handling new / unknown input shapes

1. **Sniff** — header text, never position. Store the first 8 rows as JSON on `source_file`.
2. **Quarantine** — `status='quarantined'`, excluded from the build, red badge on Upload.
3. **Column mapping UI** — the operator maps sheet columns to canonical fields; the mapping
   is stored against `header_fingerprint` and applied automatically next time (this is the
   same machinery TYPE F uses, §5.6).
4. **New category / new society** — a seed row with a matcher regex; no code change.
5. **New FY** — FY columns are generated from the data.
6. **Missing period in the filename** — the money lands in `Period Not Stated`; the operator
   can set the period on the statement and rebuild.
7. **A sheet with no ISRCs, or a non-numeric internal number** — allowed. Such entries simply
   cannot participate in the rules that need the missing field (§4), and the coverage engine
   records that as the reason, not as an error. The reference catalogue contains exactly one:
   `Ekakitwo - The Poem`, internal number `NEED TO REGISTER`.
8. **A platform that is not Spotify** — a new `spotify_report`-shaped table is *not* created;
   the report kind is a column (`platform_report.kind`) and the month/ISRC/amount grain is
   identical for YouTube, Apple and Meta raw reports.

---

## 22. Deployment, configuration and operations

```
   browser ──▶ nginx/CDN ──▶ React bundle
                  │ /api
             ┌────▼─────┐      ┌──────────┐
             │ FastAPI  │─────▶│ Postgres │
             └────┬─────┘      └──────────┘
                  │ enqueue          ┌────────┐
             ┌────▼─────┐            │ MinIO  │
             │  Redis   │◀───────────│  / S3  │
             └────┬─────┘            └────────┘
             ┌────▼─────┐
             │  Celery  │ extraction · build · coverage · merge · export workers
             └──────────┘
```

`.env`: `DATABASE_URL`, `REDIS_URL`, `S3_*`, `MAX_UPLOAD_MB` (64), `RECON_TOLERANCE` (0.05),
`MONEY_ROUNDING` (`penny_fix`), `EXPORT_TIMEOUT_S`, `COVERAGE_DEFAULT_MODE` (`RESOLVED`),
`MERGE_SUGGEST_THRESHOLD` (0.70).

Operational notes: `openpyxl` on a 10,000-row sheet is memory-hungry — use `read_only=True`
where the dimension record is sound and repair it with `calculate_dimension()` where it is
not (several statements report `1×1`). Workers get 2 GB. Keep every uploaded file forever;
keep exports 90 days and regenerate on demand — builds are deterministic. Nightly `pg_dump` +
object-store versioning; quarterly restore drill.

---

## 23. Defect log — what went wrong and the rule that prevents it

Every one of these was found in the hand-written generation of these reports. They are in the
architecture because a rebuild that does not encode them will reproduce them.

| # | Defect | Effect | The rule now |
|---|---|---|---|
| **D1** | The statement parser iterated to the end of the sheet instead of stopping at `TOTAL ROYALTIES`, so the printed grand total landed on the **last work** of the file | `YUDDHA THEME` showed `113,848.57` instead of `0.37`; the file total read `227,696.78` instead of `113,848.57` — a silent 2× | §5.1 hard stop + I2 + I3: money lines, sub-total lines and the printed total must all agree before the file may contribute |
| **D2** | Deleting merged rows shifted everything below, and the `TOTAL` row was then located by arithmetic — the recomputed totals were written one row **below** the real `TOTAL` row | two total rows in the workbook, one stale | §19.2: find the `TOTAL` row and the note rows **by content**, never by arithmetic |
| **D3** | Six monthly cells were rounded individually while their total was rounded from the unrounded sum | a row showed months adding to `13,307.74` beside a total of `13,307.76` | §7: a printed total is `round(Σ round(part))`; I24 asserts it |
| **D4** | A `TOTAL` row summed the **Date** columns because the money columns were computed as `10 + 4k` instead of `11 + 4k` | totals over dates | §19.2: column roles are read from the header row, never from arithmetic on band offsets |
| **D5** | `round(sum([]))` returns `int 0`, so an all-zero money column silently lost its `#,##0.00` format | `0` instead of `0.00` | number formats are applied **by column role**, never by inspecting the Python type of a value |
| **D6** | A title match was allowed to back-fill an internal number without checking uniqueness | `AAJ JYOTSNA RAATEY` (two works, `15628816` and `29764517`) would have merged | §8 L3 requires the title to be unique **on both sides**; anything else is a §12 candidate, not a link |
| **D7** | A coverage report quoted revenue from the master workbook it was auditing | an error in the master would have been invisible | §11.6 rule 1: the coverage workbook recomputes every figure from the source files; the master supplies layout and colour only |

---

## 24. Test plan

| Layer | Tests |
|---|---|
| Unit | `noi("16026924.0") == "16026924"`; `noi("NEED TO REGISTER") == "NEED TO REGISTER"`; `norm("Aaj  Amaye!") == "aajamaye"`; `norm2("Abar Phire Ele-Lofi") == norm2("Abar Phire Ele")`; `penny_fix` restores the target to the paisa; `parse_filename` over all 46 real names |
| Fixture | a 40-row Type A file, a 40-row Type B file, a 10-row catalogue, a 50-line MRM file, and a deliberately ugly TYPE F sheet (merged header, ISRCs comma-separated, one blank internal number) with hand-computed expectations |
| Extraction | money lines vs sub-total lines vs printed total on every real file; a regression file whose last work is non-zero (D1) |
| Coverage | leak tests I14/I15 on three different sheets; STRICT vs RESOLVED counts; conservation I18; explainability I19; a sheet containing only ISRCs and a sheet containing only internal numbers |
| Merge | money neutrality I20 on a synthetic 3-row group; identifier preservation I21/I22; `NOT_THE_SAME` suppression; undo restores the parent build exactly |
| Golden | rebuild from `input/batch-1..3` and diff cell-by-cell against the committed `SVF-RD-SKV8.xlsx`, both coverage workbooks and both mismatch reports |
| Property | shuffling input file order changes no output byte; running a coverage audit twice gives the same `sha256` |
| API | upload → classify → extract → build → coverage → merge → export happy path; duplicate upload returns the same id; a build is blocked on a FAIL statement |
| UI | 3,144 × 225 virtualised grid without layout shift; chips render one per value; blank identifier renders blank |

---

## 25. Build order for an implementer

1. `domain/normalize.py`, `domain/filename.py`, `domain/link.py` + unit tests. Everything
   depends on these, and `link.py` is the only place identity may be decided.
2. Postgres schema + Alembic + `society` / `category` seeds.
3. `ingest/reader.py`, `sniff.py`; prove shape detection on all 50 real files.
4. `ingest/statement.py` with carry-forward, the `SOURCE`-line rule and the hard stop;
   assert I1, I2, I3.
5. `ingest/catalogue.py`, `ingest/usersheet.py`, `ingest/spotify.py`; assert 2,762 / 10,960 /
   11,222.
6. `build/universe.py` + `linker.py`; assert I4, I7, I8.
7. `build/mrm.py` (B1–B7 + `penny_fix`); assert I5, I9.
8. `build/fy.py`, `build/status.py`; assert I6 and the eight-value status distribution.
9. `export/style.py` + `export/skv.py`; golden-diff against `SVF-RD-SKV8.xlsx`.
10. `coverage/engine.py` + `coverage/revenue.py` + `export/coverage_xlsx.py`; assert
    I14–I19 and reproduce the 93-song reference result.
11. `merge/candidates.py` + `merge/apply.py` + `export/merge_xlsx.py`; assert I20–I23 and
    reproduce the five reference merges.
12. `mismatch/` + its exports; assert I10–I13.
13. FastAPI routers + Celery tasks + job status.
14. React: Upload → My Sheets → Validation → RD Viewer → **Coverage Audit** → **Merge
    Review** → Mismatch → Exports.
15. Hardening: RBAC (only `analyst`+ may decide a merge), audit log, retention, restore drill.

---

## 26. Appendices

### Appendix A — current file inventory

| Location | Files | Shape |
|---|---|---|
| `input/batch-1` | 27 | TYPE A standard statement |
| `input/batch-1` | 18 | TYPE B overseas statement |
| `input/batch-1` | 1 — `(S-46)SVF list of Song -April 2026.xlsx` | TYPE C catalogue (2,762 rows) |
| `input/batch-2` | 1 — `Spotify - for the Period October 2025 to March 2026.xlsx` | TYPE A (1,379 works, `113,848.57`) |
| `input/batch-3(Only spotify RD)` | 1 — `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | TYPE D (10,960 lines, `7,889,496.76`) |
| `input/batch-3(Only spotify RD)` | 1 — `Spotify L6M.xlsx` | TYPE E (11,222 rows) |

### Appendix B — output lineage

| Generation | Workbook | Built by | What it added |
|---|---|---|---|
| V1 | `output/batch1-output/SVF_Royalty_Consolidated_Report_SK.xlsx` | `build_consolidation.py` | first consolidation, 23,242 master rows |
| V2 | `output/batch1-output/SVF_RD_V2.xlsx` | `build_song_matrix.py` | song × distribution matrix |
| V3 | `output/batch1-output/SVF-RD-V3.xlsx` | `build_rd_v3.py` | sections, 4-column blocks, FY summary — the metadata parser |
| V4 | `output/batch1-output/SVF-RD-SKV4.xlsx` | `build_rd_v4.py` | statement register |
| V5 | `output/batch2-output/SVF-RD-SKV5.xlsx` | `build_rd_v5.py` | batch-2 Spotify statement folded in |
| V6 | `output/batch3-output(Only Spotify RD)/SVF-RD-SKV6.xlsx` | — | Spotify MRM revenue |
| V7 | `output/batch3-output(Only Spotify RD)/SVF-RD-SKV7.xlsx` | — | catalogue as the backbone, ISRC-first MRM cascade, audit columns (3,149 × 225) |
| **V8** | **`output/batch3-output(Only Spotify RD)/SVF-RD-SKV8.xlsx`** | **`build_skv8.py`** | **same-song rows merged, unregistered ISRCs written into column A, merge provenance in column 223 (3,144 × 225)** |
| — | `output/Missing song list/Songs-Missing-From-SVF-List.xlsx` | `build_missing_songs_with_revenue.py` | coverage finding list (93 songs, 3 columns) |
| — | `output/Missing song list/Songs-Missing-From-SVF-List-Revenue.xlsx` | same script | coverage revenue workbook (37 columns, SKV layout and colours) |
| — | `output/Missing song list/Song-ID-Mismatch-Report.xlsx` (+ `-V2-With-Revenue`) | `build_song_id_mismatch.py` | identity clashes, with revenue |
| — | `output/batch3-output(Only Spotify RD)/Works-Paid-…`, `Spotify-Revenue-…`, `Spotify-Streams-Only-…` | gap-list scripts | superseded by coverage runs (§14) |
| — | `output/batch3-output(Only Spotify RD)/Statement-SKV4.xlsx` | `build_stmt4.py` | statement register |

### Appendix C — the numbers a rebuild must reproduce

```
statements                     46        (28 standard + 18 overseas)
catalogue rows                 2,762     2,571 internal numbers · 4,278 ISRCs · 2,570 name keys
IPRS Spotify Oct25-Mar26       113,848.57  over 1,379 works
Spotify MRM                    7,889,496.76 over 10,960 lines / 1,759 ISRCs
Spotify usage                  11,222 rows
SKV7                           3,149 rows × 225 cols
SKV8                           3,144 rows × 225 cols   (5 merged, 18 ISRCs added)
total royalty distributed      3,323,794.31            (identical SKV7 -> SKV8)
Spotify gross revenue          7,889,496.76            (identical SKV7 -> SKV8)
coverage findings (RESOLVED)   93        13 statement-only · 71 MRM-only · 9 both
coverage findings (STRICT)     36 works + 129 ISRCs
revenue at stake               250,956.32   (rounded monthly cells; raw sum 250,956.39)
royalty already received       1,140.08
name-in-sheet, ids differ      18
merge candidate pool (SKV8)    168 name groups over 402 rows
mismatch rows                  781       (121 + 245 + 415 raw -> 844 groups -> 781)
```

### Appendix D — glossary of the deliverables

| Question the user asks | Deliverable | Section |
|---|---|---|
| "What did every song earn, from every source, ever?" | `SVF-RD-SKV8.xlsx` | §10 |
| "Which songs are not in my sheet but still earned money?" | Coverage Audit — list + revenue workbook | §11 |
| "Which songs are the same, just a different ISRC?" | Merge Review — candidate list, and the merged build if accepted | §12 |
| "Where do my sheet, IPRS and Spotify disagree about a song?" | Song-ID-Mismatch V1 / V2 | §13 |
| "What did each statement pay in total?" | Statement register | §14 |

---

*End of `SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V2.md`. The V1 document is
kept as `SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V1.md`; where the two
disagree, V2 is authoritative.*
