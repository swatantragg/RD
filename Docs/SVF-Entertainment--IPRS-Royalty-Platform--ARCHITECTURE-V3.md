# SVF Entertainment — IPRS Royalty Intelligence Platform
## Complete build-from-scratch architecture — **V3**

| | |
|---|---|
| **Platform** | A royalty consolidation platform for music rights holders. **SVF Entertainment Private Limited** (IPRS member `5154290`) is the first client; the design does not depend on SVF |
| **Domain** | Collecting-society royalty statements (IPRS today) + streaming-platform reports (Spotify today) + optional song lists + optional previously exported outputs |
| **What it builds** | The master royalty matrix in the **SVF-RD-SKV8 layout**, the "paid but not in the base" lists, the same-name / different-code flags, the mismatch report, the held-money report and the statement register — as a web application with versioned, reproducible Excel exports |
| **Version** | **V3** — supersedes `…ARCHITECTURE-V2.md`. V2 assumed the SVF song list is always present and that every file belongs to SVF. Neither is true |
| **Reference data** | `Docs/input/batch-1..4` and every workbook in `Docs/output/` up to `SVF-RD-SKV8.xlsx` |
| **Status of the numbers** | Every figure below was measured from those files while writing V3 |

### What is new in V3

| # | Change | Why |
|---|---|---|
| N1 | **The song list is optional.** A run is built from four input roles: royalty statements, platform reports, a song list, a previous output. Any combination is valid (§3) | Most runs start from IPRS statements alone. The song list arrives only sometimes |
| N2 | **A previous output is an input.** A workbook the platform exported earlier can be uploaded back; new money is merged into its rows and everything paid but not in it is listed (§11) | This is the real "Spotify statement + last month's output" workflow (SKV4 → SKV5 → SKV6, and the 148-song extra list) |
| N3 | **Many clients, many rights holders, many distributors.** Every statement carries its rights holder in its letterhead; every platform report is tagged with its distributor and platform. A run is scoped to chosen holders (§4) | Statements come from several distributors and members, not only SVF. One statement in the reference set already belongs to another member |
| N4 | **Identity model rebuilt:** works, recordings and the links between them are separate; an output row is a grouping of them (§5) | One work has many recordings (remixes, covers, versions); one recording can sit under several works |
| N5 | **Automatic links are guarded.** Exact-code links stay automatic, but guards hold the money for a person when something looks wrong (§6.3) | Most money moves through code links, and a wrong code moves it silently |
| N6 | **A person's decision always wins**, and a title never moves money without an accepted decision (§6.4, §6.5) | Titles are unreliable; the human judgement must survive later uploads |
| N7 | **Statement identity, re-issues, negatives and rights-holder checks** (§8) | A distribution number is not unique; clawbacks and re-issues must not double-count |
| N8 | **Rule sets are versioned** — tolerances, weights, thresholds, layouts, FY method (§12.1) | Same inputs must give the same report on any day |
| N9 | **Build lifecycle with maker-checker approval** (§12) | No single person can move money and approve it |
| N10 | **Two financial-year views and an explicit currency model** (§9) | Usage period and payment date answer different questions |
| N11 | **Money kinds are never added** — society royalty (holder's share) vs platform gross (§9.1) | Publishing share and recording gross are different kinds of money |
| N12 | **Findings keep their status** across runs; title differences are classed (§7) | Otherwise the same items are raised forever |
| N13 | **Long storage, bounded wide export** (§13.2) | The SKV layout grows by 4 columns per distribution |
| N14 | **Quality metrics** measured on every build (§15) | Pipeline checks prove the process ran, not that the answer is right |
| N15 | **Security architecture with trust zones** — quarantined intake, write-once originals, a separate audit store, SSO + server-side permissions (§18, §19) | The results and the record of changing them must not share one trust boundary |
| N16 | **Statement metadata resolved from file name, then content, then a person** (§2.6) | Other holders and senders name their files differently |
| N17 | **ISRC families flagged, never merged** (§6.2) | Remixes and versions get nearby ISRCs from the same registrant; they are related, not identical |
| N18 | **Build series, concurrency rules and a legacy rule set v0** (§12.1, §12.3) | Two people must never see two "version 9"s; old outputs must stay reproducible while new rules are adopted |

---

## Table of contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Inputs — four roles, six file kinds](#2-inputs--four-roles-six-file-kinds)
3. [Run modes — what can be combined](#3-run-modes--what-can-be-combined)
4. [Parties — clients, rights holders, distributors, platforms](#4-parties--clients-rights-holders-distributors-platforms)
5. [Identity model](#5-identity-model)
6. [Matching and linking](#6-matching-and-linking)
7. [Flags and findings](#7-flags-and-findings)
8. [Statements — identity, duplicates, re-issues, negatives](#8-statements--identity-duplicates-re-issues-negatives)
9. [Money rules](#9-money-rules)
10. [Processing pipeline](#10-processing-pipeline)
11. [Incremental merge with a previous output](#11-incremental-merge-with-a-previous-output)
12. [Rule sets, decisions and builds](#12-rule-sets-decisions-and-builds)
13. [Outputs](#13-outputs)
14. [Accuracy model — invariants](#14-accuracy-model--invariants)
15. [Quality metrics](#15-quality-metrics)
16. [Data model](#16-data-model)
17. [Roles and permissions](#17-roles-and-permissions)
18. [System architecture](#18-system-architecture)
19. [Security design](#19-security-design)
20. [Operations](#20-operations)
21. [API](#21-api)
22. [Workspace (frontend)](#22-workspace-frontend)
23. [Test plan](#23-test-plan)
24. [Migration from V2 and the prototype](#24-migration-from-v2-and-the-prototype)
25. [Build order](#25-build-order)
26. [Items needing business sign-off](#26-items-needing-business-sign-off)
27. [Appendices](#27-appendices)

---

## 1. Purpose and scope

Rights holders receive royalty money from a collecting society (IPRS) as **distribution
statements**, and platform revenue reports from their **distributors**. Each source uses its
own format and its own identifiers. The platform turns any mix of these files into one
reconciled, explainable master matrix and a set of exception lists.

| # | Capability | Section |
|---|---|---|
| C1 | Accept any mix of statements, platform reports, song lists and previous outputs | §2, §3 |
| C2 | Detect each file's kind and layout from its content; hold anything unfamiliar or changed | §2.4, §2.5 |
| C3 | Identify the rights holder of every statement and the distributor/platform of every report | §4 |
| C4 | Extract every money line exactly once and reconcile it to the file's own totals | §8, §9.5 |
| C5 | Link songs across sources by code; propose, never impose, links by title | §5, §6 |
| C6 | Build the master matrix in the SKV8 layout, with or without a song list | §13.1 |
| C7 | Merge new sources into a previous output and list everything paid but not in it | §11 |
| C8 | Flag same name / different ISRC, same name / different work number, same code / different name | §7 |
| C9 | Keep every decision, rule and build versioned, reproducible and reversible | §12 |
| C10 | Never add different kinds of money; never lose or invent a rupee | §9, §14 |
| C11 | Enforce roles and two-person approval on the server | §17 |
| C12 | Keep originals write-once and the audit record outside the results' trust boundary | §18, §19 |

**Out of scope:** payments, contract and split administration, licensing, and sending data
back to IPRS or to a distributor. The platform can *export* correction lists; people send them.

---

## 2. Inputs — four roles, six file kinds

### 2.1 The four roles

| Role | What it is | Required? | Carries |
|---|---|---|---|
| **Royalty statement** | One payout run from a collecting society (IPRS) for one rights holder and one revenue source | At least one statement **or** one platform report | Title · **work number** · holder's share of money |
| **Platform report** | A distributor's report of what a platform (Spotify today) earned per recording, or how often it was played | Optional | Title · **ISRC** · album/UPC · gross revenue or play count, per month |
| **Song list** | Any sheet listing a holder's songs — SVF's April 2026 list is one example | Optional | Title · work number(s) · ISRC(s) |
| **Previous output** | A master matrix this platform (or the SKV scripts) exported earlier | Optional | Rows with ISRC(s), title, work number(s) and the money already consolidated |

A **source** brings new money. A **base** (song list, previous output, or both) supplies the
rows the new money is matched into. A run with no base builds its rows from the sources.

### 2.2 The six file kinds

| Kind | File | Reference example |
|---|---|---|
| **A** | Standard IPRS statement — 12 columns, money in column L | 28 files, e.g. `(S-13) … P2550 YouTube Pre Claims …` |
| **B** | Overseas IPRS statement — 17 columns, money in column Q, society from the file name | 18 files, e.g. `(S-25) … P2570 … 021 BMI` |
| **C** | Song list — any layout, columns mapped (V2's TYPE C and TYPE F are one kind now) | `(S-46)SVF list of Song -April 2026.xlsx`, 2,762 rows |
| **D** | Platform revenue report — month, title, album, ISRC, UPC, revenue | `Raw_Spotify_MRM_Oct25_Mar26.xlsx`, 10,960 lines |
| **E** | Platform usage report — month, title, album, ISRC, UPC, plays | `Spotify L6M.xlsx`, 11,222 rows |
| **F** | Previous output — a master matrix in the SKV layout | `SVF-RD-SKV4.xlsx` … `SVF-RD-SKV8.xlsx` |

### 2.3 Kind details

**A — standard statement.** Rows 1–2 are the letterhead: `A1 = INTERNAL NO`, `B1` = the
rights holder's society member number, `D1` = IPI name number (text, keep leading zeros),
`B2` = holder name, `D2` = IPI base number. Row 4 is the header
(`WORK INT NO · TITLE · AV · LANGUAGE · NAME · ROLE · SOCIETY · OWN · COLL · POOL · SOURCE · ROYALTY AMT`).
Work number, title, AV and language appear only on the first line of a block and are carried
forward. Rules proven on the reference files:

* **Money-line rule:** a line carries money only when `SOURCE` is filled. The bare line after
  it repeats the figure as a block sub-total and must not be counted again.
* **Hard stop:** stop reading before the row containing `TOTAL ROYALTIES`. Reading past it books
  the file's grand total onto its last work (the reference Spotify file would read
  `227,696.78` instead of `113,848.57`).
* **Three-way check:** Σ money lines = Σ sub-total lines = printed `TOTAL ROYALTIES`.
* **Footer check:** the `SUMMARY OF ROYALTY` table (by language) and the pool/source table
  must both agree with the lines. They are independent totals printed by IPRS.
* The sheet name varies and several files carry a wrong `1×1` dimension record — never trust
  sheet names or `max_row`.

**B — overseas statement.** Same letterhead and carry-forward. Columns J–P split usage
(`RADIO · TV · CINEMAS · PERMITS · DEMAND · GENERAL · OTHERS`); money is column Q. A line is
kept when `NAME`, `ROLE` and `ROYALTY AMT` are all filled; `0.0` is a real line. The society
comes from the file name (`… - 021 BMI` → BMI, USA). Amounts are already in rupees.

**C — song list.** Any sheet with at least one identity column. Columns are mapped to
`song_name · work_no · isrc` (and optionally `amount · period`) by header text and value
fingerprints; the operator confirms the mapping. ISRC and work-number cells may hold several
values separated by `|`, `,` or new lines; order is kept and element 0 is the primary. A
non-numeric work number such as `NEED TO REGISTER` is kept verbatim.

**D — platform revenue.** One line per month × recording. Canonical fields: `month · platform
· content_name · album · isrc · upc · amount · currency`. At upload the operator confirms
four facts the file may not state:

* **distributor** and **platform** (the reference file's `Client` column says only `Spotify`);
* **rights holder** the report belongs to — the scope rule (§4) applies to reports as to statements;
* **currency** — required; the reference file has no currency column;
* **revenue basis** — `GROSS` (before the distributor's fee) or `NET` (after it). Distributors
  differ. `GROSS` and `NET` are different money kinds (§9.1) and are never added.

**E — platform usage.** Same grain as D with `plays` instead of amount. Never money.

**F — previous output.** Row 1 = section bands, row 2 = headers starting
`ISRC · Song Name · Internal No · Total Amount`, then one row per song, a `TOTAL` row and notes.
Each band holds repeating `Date · Amount · Period · Distribution Number` blocks. A V3 export
also carries a hidden `_rd_meta` sheet (§13.4) that makes re-import exact. Full parsing rules
are in §11.

### 2.4 Kind detection

Detection reads header text, never file names, folder names, sheet names or column positions.

```
hidden sheet "_rd_meta" present                                   -> F (V3-native)
row 2 starts "ISRC", "Song Name", "Internal No", "Total Amount"
  and row 1 holds section bands                                   -> F (legacy SKV)
header row has "WORK INT NO" and "RADIO" and "TV"                  -> B
header row has "WORK INT NO"                                       -> A
header has an ISRC column and a revenue/amount column
  and a month column                                               -> D
header has an ISRC column and a usage/plays/streams column         -> E
any row maps >= 1 identity column (song_name / work_no / isrc)     -> C (operator confirms)
otherwise                                                          -> UNKNOWN -> held for review
```

### 2.5 Layout registry and drift

Every accepted layout is stored as a **layout**: kind, the exact normalised header signature
(column names in order), the column mapping, and the rule-set version it belongs to.

* A file is read with a saved layout **only if its header signature matches exactly**.
* Any difference — a column added, removed, renamed or moved — sends the file to review with the
  difference shown (for example: *new column `TAX` after `ROYALTY AMT`*).
* A new or changed layout is a rule-set change (§12.1): it needs a second person's approval,
  and the first file read with it is checked by a person before it can count.
* Extra plausibility checks run on every statement: holder identity (§4), line count against
  earlier files of the same source, share percentages in the usual range, and a work number
  on every money line.

### 2.6 Statement metadata — file name, content, then a person

The letterhead gives the rights holder, but **not** the revenue category, distribution number,
usage period or overseas society. In the reference set those come from the file name, e.g.
`(S-13)Royalty Distribution - P2550 YouTube Pre Claims - July 2025 to September 2025 …`.
Files from other holders or senders may be named differently, so metadata is resolved in
this order and every field records where it came from:

| Order | Source | Gives |
|---|---|---|
| 1 | file-name grammar (V2 §6.1: `(S-n)`, `[PM]dddd`, sub-run `[PM]ddddAddd`, `Mon YYYY … Mon YYYY`, `F.Y. 2025-26`, trailing `ddd SOCIETY`) | category, distribution number, sub-run, period, overseas society |
| 2 | file content: the pool/source footer (`SOURCE DESCRIPTION` such as `SPOTIFY AB`, `TSERIES MUSIC`) and the overseas usage columns | category when the name has none; confirms the name's category |
| 3 | the operator at upload | anything still missing or contradictory. The upload card shows every field, its source, and a warning where name and content disagree |

Category is matched with the ordered category ladder (redistribution → mechanical → Apple
Music → Spotify → YouTube pre/post → Facebook/Meta → radio → Zee TV → overseas → other),
held in the rule set. A statement cannot enter a run with an unresolved category; a missing
period is allowed and lands in `Period Not Stated`.

---

## 3. Run modes — what can be combined

A **run** = zero or more bases + one or more sources + a rights-holder scope + a rule set +
the decisions in force. The platform works out the mode from what is present.

| Base | Sources | Output rows | Extra outputs | Reference in the files |
|---|---|---|---|---|
| none | IPRS statements | one row per **work** (work number is unique within a society) | statement register | `SVF-RD-SKV4` — 45 statements, ~2,120 rows, ₹32,09,945.73 |
| none | platform reports | one row per **recording** (ISRC) | — | Spotify-only views |
| none | statements + platform reports | work rows + recording rows; title-based **proposals** to join them | proposals list | `Only-Spotify-RD-SKV1/2` |
| song list | any | one row per **song-list entry**, plus rows for anything paid that the list lacks | paid-but-not-in-list; same name / different ISRC; same name / different work | `SVF-RD-SKV7`, `SVF-RD-SKV8` |
| previous output | any | the previous rows kept in order, new money added into them, new rows appended | paid-but-not-in-previous-output; change log | `SKV4 → SKV5` (+ IPRS Spotify statement), `SKV5 → SKV6` (+ Spotify MRM); `Extra_songs…` (148 songs) |
| previous output + song list | any | previous rows first; list entries that match no previous row by code are appended as `In list - not in previous output`; list codes that a previous row lacks are **proposed** as links, never added silently | all of the above | — |

### 3.1 Statements only (no song list)

The 45–46 IPRS statements are the most common input. Every money line carries a work
number, so rows are keyed by `(issuing society, work number)` — overseas statements use the
same IPRS work numbers, so a work paid by YouTube and by BMI is one row. Every distribution is a
block of columns. The ISRC column stays blank unless another input (a previous output or a song
list) links an ISRC to that work. Works named in a statement with `0.00` (common in overseas
files) still get a row, marked `named, 0.00 paid`. Two different work numbers with the same
title (e.g. `AAJ JYOTSNA RAATEY`, works `15628816` and `29764517`) stay two rows, with an
information flag.

### 3.2 Statements (+ platform reports) with a song list

Each song-list entry becomes a row; money attaches by work number (statements) and by ISRC
(platform reports). Anything paid that no entry claims becomes its own row and appears on the
paid-but-not-in-list output. Where a paid title equals a list title but the code differs, the
row is flagged **same name, different ISRC** (or **different work number**) and a link is
*proposed* (§6.5) — it is not applied until accepted. The flag appears in three places: the
row's `Held / Flags` column in the master, the same-name workbook (§13.3), and the review queue.

**A song list with titles only** (no code column) is accepted but cannot exclude anything by
code. The run is marked `TITLE-ONLY BASE — low confidence` on the cover and on every list;
every paid song becomes `NOT_IN_BASE`, and title matches (M4/M5) against the list are attached
to each finding as *possible match*, never as proof.

### 3.3 A previous output + a new statement or platform report

The earlier export is the base. New money is matched into its rows by work number (column C)
and by ISRC (column A). Its distribution columns are kept; the new distribution gets new
columns; totals and FY columns are recomputed. Songs the new source paid that match no row are
appended **and** listed in a separate paid-but-not-in-previous-output workbook. Full algorithm:
§11.

### 3.4 Platform reports only

Rows are keyed by ISRC. The same ISRC across months or reports is one row. Different ISRCs are
never joined automatically, even with equal titles — remixes and versions are legitimately
different recordings. Equal titles produce an information flag only.

### 3.5 Mixed rights holders or distributors

A run is scoped to one or more rights holders. Files for a holder outside the scope are
excluded with a notice on the cover sheet. Including several holders in one run is an explicit
choice. The same work can then be paid to two holders — for example a publisher and a
composer each receive a statement for it — and their shares must not be added as if they were
one payment. So in a multi-holder run the row key becomes `(holder, song)`: the output carries
a `Rights Holder` column, each holder's money sits on its own rows, and totals are shown per
holder first and overall second, labelled `all chosen holders`.

---

## 4. Parties — clients, rights holders, distributors, platforms

| Party | What it is | Where it comes from |
|---|---|---|
| **Client (workspace)** | The organisation using the platform. All data, users and outputs belong to exactly one workspace | Set up by an admin. SVF is the first |
| **Rights holder** | The society member a statement pays — publisher, composer or author | Statement letterhead: member number (`B1`), name (`B2`), IPI name number (`D1`), IPI base number (`D2`) |
| **Society** | The collecting society issuing statements (IPRS) and, for overseas money, the foreign society it collected from | Seed data; the overseas society from the file name |
| **Distributor** | The company that delivers a platform report | Declared at upload, or read from the file when present |
| **Platform** | Spotify, YouTube, Apple Music, Meta … | The report's `Client`/platform column, or declared at upload |

Rules:

* Each workspace declares its **own rights holders** (e.g. SVF = member `5154290`, IPI
  `00871526032`). A statement whose letterhead names another holder is labelled
  **other holder** and excluded from the run unless the scope includes that holder.
  Reference: `(S-32) … P2577 …` is member `8875288` (a composer), not SVF; its `₹53.47` sits
  inside `SVF-RD-SKV8`'s total today.
* Society, category and platform lists are seed data inside the rule set (§12.1). A new source
  is a new row, never a code change.
* Output naming is per workspace: `<CLIENT_CODE>-RD-SKV<generation>` (SVF's next is
  `SVF-RD-SKV9`). The layout is the SKV8 layout for every client.

---

## 5. Identity model

### 5.1 Entities

```
          work  (society + work number)          recording  (ISRC)
            |  \                                   /  |
            |   \___ work_recording_link _________/   |
            |        many-to-many, each link has      |
            |        a source and a version           |
   royalty lines (statements)              platform lines (reports)
            \                                         /
             \______________ song row ______________ /
                  a grouping of works + recordings;
                  one row of the master matrix
```

| Entity | Key | Notes |
|---|---|---|
| **Work** | `(society, work_no)` | The composition. IPRS pays against it. Titles are attributes, not keys |
| **Recording** | `isrc` (normalised: upper case, `A–Z0–9` only) | One recorded version. Platforms pay against it |
| **Work–recording link** | `(work, recording, source)` | Many-to-many. Sources: song list, previous output, accepted decision. Never created by a title alone |
| **Song row** | a stable `row_key` | What the output shows as one line. Built from a base entry, or from one work / one recording when no base claims it |

The reference song list shows why links must be many-to-many: **1,037** work numbers have
more than one ISRC (up to 15), and **263** ISRCs are listed under two or more different work
numbers (e.g. `INS231421096` under *Mon Bojhe Naa* `15675703` and *Eka Ekela Mon*
`15675713`). Some are medleys; some are list errors.

### 5.2 Where money lands

| Money | Attaches to | Never attaches through |
|---|---|---|
| Statement royalty line | its **work** (by work number) | a title, or an ISRC — unless the line has no work number at all, in which case it is held |
| Platform revenue line | its **recording** (by ISRC) | a title, or a work number |
| Platform usage line | its **recording** | — (not money) |

A song row's amount is the sum of the money on the works and recordings it groups. Money is
stored once, on the work or recording; a row only points at it.

### 5.3 Output grain and the book-once rule

| Grain | Used when | One row per |
|---|---|---|
| `per_entry` | a song list or previous output is the base (default) | base entry — exactly like SKV7/SKV8 |
| `per_work` | statements only, no base | work |
| `per_recording` | platform reports only, no base | recording |

When several base rows claim the same work (the reference list has 148 work numbers on more
than one row, e.g. *Tomake Chai* and its versions), the work's statement money is shown **once**:
on the owner row (the entry whose title matches the statement title, else the version-stripped
match, else the first entry). The other rows show `0.00` with the note
`IPRS work 15628861 - royalty booked once, on 'Tomake Chai' (INS2X1600134)`. The grand total
never double-counts.

### 5.4 Shared codes

A code claimed by two or more base rows that are **not** the same song is a **shared code**:

* a work shared by several rows of one song (versions of one composition) → book-once (§5.3);
* a recording listed under two different works (medley or list error) → its platform money is
  **held** as `SHARED RECORDING — needs decision` on its own row, until a person assigns it to
  one row or confirms it stays shared. It still counts in every total.

---

## 6. Matching and linking

### 6.1 Normalisation

Implemented once (`domain/normalize.py`) and shared by every stage. Money uses `Decimal`
everywhere — never binary floating point.

```python
def s(v):     return "" if v is None else str(v).strip()
def dec(v):   # exact money: Decimal(str(v)) after removing thousands separators; blank -> Decimal(0)
def noi(v):   # work number: "16026924.0" -> "16026924"; non-numeric text kept verbatim
def ik(v):    return re.sub(r"[^A-Z0-9]", "", s(v).upper())          # ISRC key
def norm(v):  return re.sub(r"[^a-z0-9]", "", s(v).lower())           # title key
VER = r"\b(lofi|lo fi|cover|reprise|sped up|slowed|version|male|female|remix|theme|" \
      r"instrumental|unplugged|acoustic|duet|original|mix|edit|radio|sad|vocals|title song|from)\b"
def norm2(v): # title key with version words and "(From "Film")" removed
def fold(v):  # transliteration fold for Indian-language titles: aa->a, ee->i, oo->u, w->v,
              # sh->s, chh->ch, ph->f, th->t, dh->d, double letters -> single; then norm()
```

### 6.2 The link ladder

| Rung | Evidence | Strength | Action |
|---|---|---|---|
| **M1** | same `(society, work_no)` | certain | automatic, then guarded (§6.3) |
| **M2** | same ISRC | certain | automatic, then guarded |
| **M3** | a work–recording link supplied by a base (song list or previous output row carrying both codes) | known | automatic, then guarded |
| **M4** | exact `norm(title)`, unique on both sides, no conflicting code | proposal | a person accepts (§6.5) |
| **M5** | `norm2(title)` or `fold(title)` match | weak proposal | a person accepts; never bulk-accepted |
| **M6** | album / UPC, **ISRC family**, language, disjoint earning periods | signal only | changes a proposal's score |

**ISRC family.** Versions of one song (remix, lofi, male/female, cover) usually get new ISRCs
from the same registrant in the same year, with nearby serial numbers — for example
*Bhalobashar Morshum* `INS2X2209006` (male) and `INS2X2209001` (female). An ISRC is
`CC-XXX-YY-NNNNN` (country, registrant, year, designation). Two ISRCs are one **family** when
country + registrant + year match (first 7 characters) and the designations are within
`isrc_family_gap` (rule set, default 50). A family is a signal and a flag
(`POSSIBLE_VERSIONS`), never a merge: remixes are real, separate recordings and keep their own
rows unless a person joins them.

Every link and every attachment of money records the rung, the evidence and the rule-set
version, so any figure can be traced to how it got there.

### 6.3 Guards on automatic links

M1–M3 are automatic, but the money is **held** — shown in every total as *not yet assigned*,
listed on the held-money report, and never silently placed — when any guard fires:

| Guard | Fires when |
|---|---|
| G1 other holder | the file's rights holder (statement letterhead, or the holder confirmed for a platform report) is outside the run's scope |
| G2 shared code | the code maps to more than one base row that is not the same song (§5.4) |
| G3 title far apart | the source title and the row title fall in the "different words" class (§7.2) |
| G4 amount spike | a code earns more than `k ×` its median over earlier builds (k in the rule set) |
| G5 human veto | a stored `NOT_SAME` decision separates the two codes being joined |
| G6 no code | a statement money line has no parseable work number (kept as `?S-<n>:<raw>`) |

### 6.4 Precedence

```
approved human decision  >  base link (song list / previous output)  >  automatic code link  >  proposal
```

Decisions are stored against **codes** (work numbers, ISRCs, statement identities), never
against row numbers, so they survive new uploads. If a new file would join two things a person
marked `NOT_SAME`, the join is not made; a **conflict** is raised and the money waits as held.

### 6.5 Title-based proposals

A title never moves money on its own. M4/M5 create a **proposal**: *attach ISRC X to row Y* or
*join row P and row Q*. The analyst accepts or rejects each one; accepted proposals become
decisions (§12.2).

The rule set carries one policy switch, `name_link_policy`:

| Value | Behaviour |
|---|---|
| `suggest` (default) | every M4/M5 match is a proposal; money stays on separate rows until accepted |
| `bulk_exact` | the analyst may accept **all M4** proposals of a run in one action; the approver signs it off; every row it touched carries the basis `title (exact, unique) — bulk accepted` in its audit column |

### 6.6 Proposal score

The score orders the review queue and sets the default tick. Every component is shown.

| Signal | Weight |
|---|---|
| identical `norm(title)` | +0.30 |
| same album name or UPC in a platform report | +0.25 |
| same work number on one side, no conflicting number on the other | +0.20 |
| same ISRC family (country + registrant + year, nearby serials) | +0.15 |
| same ISRC registrant only (first 5 characters), different year | +0.05 |
| earning months do not overlap (looks like a re-registration) | +0.10 |
| both codes are separate entries in the base | −0.40 |
| version words differ (`Male`/`Female`, `Cover`, `Lofi` …) | −0.50 |

Bands: `≥ 0.70` suggested · `0.40–0.69` review · `< 0.40` unlikely (shown, never pre-ticked).
Weights and bands live in the rule set (§12.1); every proposal stores the rule-set version that
scored it. The weights are a starting point and are re-fitted against analyst decisions (§15).

---

## 7. Flags and findings

### 7.1 Finding kinds

| Kind | Raised when | Needs a base? |
|---|---|---|
| `NOT_IN_BASE` | money was paid on a work or recording that no base row claims | yes |
| `SAME_NAME_DIFF_ISRC` | a paid recording's title equals a base row's title, but its ISRC is not on that row | song list or previous output with ISRCs |
| `SAME_NAME_DIFF_WORK` | a paid work's title equals a base row's title, but its work number is not on that row | base with work numbers |
| `SAME_CODE_DIFF_NAME` | a code matches, but the titles fall in the "different words" class | any |
| `SHARED_CODE` | one code is claimed by rows that are not the same song | base |
| `OTHER_HOLDER` | a file belongs to a rights holder outside the scope | no |
| `IN_BASE_NOT_PAID` | a base row earned nothing in this run (information) | yes |
| `HELD_MONEY` | a guard held money (§6.3) | no |
| `ALREADY_IN_BASE` | a new statement's distribution is already a column of the previous output (§11) | previous output |
| `POSSIBLE_VERSIONS` | two or more rows carry ISRCs of one ISRC family (§6.2) and similar titles | no |
| `SAME_TITLE_DIFF_WORK` | two different work numbers carry the same title (information; never merged) | no |
| `TITLE_PLACED_IN_BASE` | money in a previous output was placed by a title match (legacy basis `Song name …`); listed for confirmation (§11.1) | previous output |
| `EDITED_BASE` | a previous output fails its integrity check or its `_rd_meta` hash (§11.1) | previous output |

Each finding carries the evidence: which codes, which titles as each source spells them,
which rung or guard, and the money involved by money kind.

### 7.2 Title comparison classes

| Class | Test | Example from the files | Shown by default? |
|---|---|---|---|
| **same** | equal after `norm` | `AMARE TUMI` / `Amare Tumi` | no — not a difference |
| **version** | equal after `norm2` | `Aaj Amaye` / `Aaj Amaye - Cover` | no — counted as variant |
| **spelling** | equal after `fold`, or edit similarity ≥ `title_similarity` (rule set) | `YUDDHA THEME` / `Yuddho Theme` | no — counted, can be accepted in bulk |
| **different** | none of the above | `Zaheree Neeli - Female` / `BISHE BISHE (FEMALE VOCALS)` | **yes** |

Every report states how many rows each class hid. Today's mismatch report treats everything
beyond `norm` as different: 415 of its 781 rows are "different song name".

### 7.3 Finding status

A finding's identity is a fingerprint of `(kind, codes, conflicting values)`. Its status is
stored per workspace and carried into every later run:

```
NEW -> ACKNOWLEDGED (reason) -> SENT_FOR_CORRECTION (to whom, date) -> FIXED (sources now agree)
                             \-> ACCEPTED_AS_IS (e.g. a known spelling)
```

Coverage findings use the review labels SVF's team already uses: `CONFIRMED_MISSING`,
`ALREADY_IN_LIST`, `NOT_OURS`, `NEEDS_CHECK`. A finding whose values change becomes `NEW`
again. Reports open on `NEW` and `SENT_FOR_CORRECTION` and show counts for the rest.

---

## 8. Statements — identity, duplicates, re-issues, negatives

### 8.1 Statement identity

A distribution number is **not** unique. In the reference set `P2580` covers 8 files (one per
overseas society), `P2570` 5, `P2555` 4, `P2577` 2 (one of them for another member), and the
two `P2101 to P2550` redistribution files carry different money (`₹60.73` and `₹2,435.92`).

```
statement_identity = (society, holder_member_no, category, dist_no, sub_run, overseas_society, period)
content_fingerprint = sha256 of the normalised money lines (work_no, source, amount) in order
file_fingerprint    = sha256 of the uploaded bytes
```

### 8.2 Duplicates and re-issues

| Situation | Result |
|---|---|
| same file bytes again | ignored; the upload points at the existing file |
| same identity, same content fingerprint | duplicate; ignored |
| same identity, different content | **held**; an analyst marks it `REPLACES` (the earlier statement stops counting but is kept) or `SUPPLEMENTARY` (both count); the approver signs off |
| a redistribution file | its own statement, in the `Redistribution` section, as today |
| a new statement whose distribution is already a column of the previous output | `ALREADY_IN_BASE`; same total → skipped; different total → held as a possible re-issue (§11) |

### 8.3 Negative lines and clawbacks

None of the 46 reference statements contains a negative line; the path is tested with fixtures.

* Negative lines are kept as they are, flagged `NEGATIVE`, and shown in the song's history.
  A song's total may go down.
* If a statement names the distribution it corrects, the negative line is linked to it.
* The three-way check and every invariant apply unchanged.

---

## 9. Money rules

### 9.1 Money kinds

| Kind | Meaning | Source | Master column |
|---|---|---|---|
| `SOCIETY_ROYALTY` | what the society actually distributed to the rights holder — the holder's share, as paid | kinds A, B | `Total Amount` (D), every statement `Amount` cell, the FY block, `Total Revenue` |
| `PLATFORM_GROSS` | what a platform reported as gross revenue on a recording, before any split | kind D, basis `GROSS` | one `Total <Platform> Revenue (<report>)` column per platform (E, …) and its month blocks |
| `PLATFORM_NET` | a distributor's report after its own fee | kind D, basis `NET` | its own total column and month blocks, labelled `net` |
| `USAGE` | play counts | kind E | usage columns only; never money |

* **Kinds are never added together** — not in a row, a total, a headline or any companion
  report. A ratio between them (IPRS royalty as a % of platform gross, as in
  `Only-Spotify-RD-SKV2`) is allowed and labelled as a ratio.
* Statement amounts are the holder's share. In the reference set every money line sits on the
  holder's own publisher line (role `E`): 20,766 lines, ₹33,23,740.84; the only other money
  line is the `₹53.47` of the other-holder file. `OWN` and `COLL` percentages are stored on
  every line and shown in the row detail.
* Two companion reports produced before V3 add the kinds together — `Song-ID-Mismatch-Report-V2`
  ("Total (Both Files)", ₹37,83,424.83) and the batch-4 workbooks ("Total (Both Sources)").
  V3 does not produce such columns.

### 9.2 Exact arithmetic and rounding

* Stored: `NUMERIC(20,8)` (platform reports send 12+ decimals). Presented: 2 decimals.
* Python uses `Decimal` end to end. A test fails the build if a binary float reaches money code.
* Whenever one total is split into rounded cells (months, FY buckets), `penny_fix` makes the
  rounded cells add up to the rounded total; the cell that lost most in rounding gets the first
  paisa. A printed total always equals the sum of the printed parts.

### 9.3 Currency and exchange rates

* Every money line stores `currency`. IPRS statements are INR — IPRS converts overseas money
  before distributing it, and the overseas files show rupees only, with no foreign amount or rate.
* A platform report must have a currency, mapped from a column or declared at upload.
* Non-INR money is stored in its own currency. Conversion happens only when a report is built,
  using an `fx_rate` row: `(currency, rate, rate_date, rate_source)`, e.g. the RBI reference
  rate on the statement date. The FX table is part of the rule set, so a re-run gives the same
  rupee figure.

### 9.4 Financial year — two views

| View | Basis | Use |
|---|---|---|
| **Earned in FY** | the usage period printed in the statement's file name; a period crossing 31 March is split month-weighted (e.g. Radio, April 2023 – March 2025 → half in FY 2023-24, half in FY 2024-25) | analysis: when the music earned |
| **Received in FY** | the payment date (from the IPRS payment advice, entered or uploaded with the statement); if absent, the file's internal date, flagged `date estimated` | accounts: when the money arrived |

Money whose period cannot be read goes to `Period Not Stated` (₹29,275.34 in SKV8). The
rule set names the headline view; the other is always available. FY columns are generated
from the data, never hard-coded.

Platform money has an exact month on every line, so its FY is exact. It gets its **own** FY
block per money kind (`Spotify gross — FY 2025-26` …), next to the society-royalty FY block and
never summed with it.

Legacy previous outputs used different FY bases: `SVF-RD-SKV4` bucketed by statement date
("FY bucket = statement date" in its footer), `SKV5` onwards by usage period. On import the FY
block of a previous output is **never carried**; it is recomputed from each prior distribution's
`Period` and `Date` cells under the current rule set.

### 9.5 Reconciliation

| Level | Check | On failure |
|---|---|---|
| File | Σ money lines = Σ sub-totals = printed total, within `recon_tolerance` (rule set; ₹0.05 today) | the file is **excluded** from the run |
| File | footer tables (by language, by pool/source) agree with the lines | excluded |
| File | holder in scope, layout signature exact, plausibility checks (§2.5) | held for review |
| Build | Σ society royalty in the output = Σ included statements' printed totals | build fails |
| Build | Σ platform gross per platform = Σ included reports' totals | build fails |
| Incremental | new grand total = previous output's total + Σ new sources included (§11) | build fails |
| Merge | every numeric column total is unchanged by a merge decision | the apply is refused |

* There is **no force option**. A failed file never enters a build; the cover sheet of every
  output lists excluded files and the money they print.
* One failed file never blocks the others: the run continues without it.
* A file may be **accepted with a difference** only by a two-person decision (§12.2) with a
  written reason; the difference then appears as its own line, `Unexplained difference`,
  so every rupee stays visible.

---

## 10. Processing pipeline

```
 upload ──► S0 INTAKE (quarantine zone)        type check, limits, virus scan, sha256,
              │                                  original stored write-once
              ▼
            S1 CLASSIFY                          kind A–F, layout signature, holder / distributor
              │                                  unknown or changed layout -> review
              ▼
            S2 EXTRACT                           lines, carry-forward, hard stop, footers;
              │                                  song-list entries; previous-output rows + cells
              ▼
            S3 VALIDATE                          three-way + footer checks, statement identity,
              │                                  duplicates / re-issues, currency, periods
              ▼
            S4 SCOPE                             base(s) + sources + holders + rule set
              │                                  = run manifest (fingerprinted)
              ▼
            S5 RESOLVE IDENTITY                  seed rows from base, M1–M3 links, guards -> holds,
              │                                  decisions applied, M4–M5 -> proposals
              ▼
            S6 PLACE MONEY                       royalty -> work -> row (book-once),
              │                                  platform gross -> recording -> row
              ▼
            S7 DERIVE                            totals per kind, FY earned + received,
              │                                  penny_fix, audit columns
              ▼
            S8 ANALYSE                           findings (§7) with carried statuses, proposals
              │                                  with scores, change log vs previous output
              ▼
            S9 CHECK                             every invariant (§14); any failure -> build FAILED
              ▼
            S10 PUBLISH                          draft -> checked -> published (approver for FINAL)
              ▼
            S11 EXPORT                           master (SKV layout), lists, register, cover, _rd_meta
```

Each stage is a job keyed by its input fingerprints. Re-running a stage replaces its own
output; it never appends to it. S5–S9 write into a build in state `building`; only S10 makes
it visible.

---

## 11. Incremental merge with a previous output

The workflow this section encodes: *"here is the file I exported last time, and here is a new
Spotify statement — add its money to the songs already there, and give me the songs it paid
that are not in my file."*

### 11.1 Reading the previous output (kind F)

1. **V3-native file:** read `_rd_meta` (§13.4) — build id, workspace, rule set, row keys,
   column signatures, source fingerprints, grand totals. Rows and columns are matched by key.
2. **Legacy SKV file** (`SVF-RD-SKV4` … `SKV8`): parse row 1 bands and row 2 headers.
   * Identity: column A (ISRCs, split on `|` and `,`), B (title), C (work numbers).
   * Each band = a section; inside it every `Date · Amount · Period · Distribution Number`
     group is one **prior distribution** with signature `(section, dist_no, period, date)`.
     Platform bands hold month blocks with signature `(platform, report label, month)`.
   * `Total Amount`, platform totals, the FY block and the audit columns are read for checking.
   * Row key: `legacy:<file sha256>:<row number>`, plus an identity fingerprint of its codes.
3. **Integrity check on import:** every row's `Total Amount` = Σ its royalty `Amount` cells;
   the `TOTAL` row = Σ the rows; for V3 files, the visible values hash to the `_rd_meta` hash.
   A mismatch means the file was edited after export: finding `EDITED_BASE`, and the import is
   held until a person acknowledges it (`ACCEPT_EDITED_BASE`, §12.2). If a user deleted the
   hidden `_rd_meta` sheet, the file is read as legacy.
4. **Rights holder of a legacy file** is not written in it. The operator confirms it at upload;
   it then takes part in the scope rule (§4) like any other input.
5. **Book-once owners.** A legacy row whose `Royalty Booked On` column names another row is a
   sibling: new royalty for that work goes to the named owner row, not to the sibling.
6. **Money placed by title in the old process.** Rows whose `Spotify (MRM) Match Basis` starts
   with `Song name` (81 rows in SKV8) carry money a title placed. The cells are carried as they
   are, and each row gets a `TITLE_PLACED_IN_BASE` finding so a person can confirm or move it.
7. The prior row's status text (`In SVF list (S-46) - …`) is kept in the change log but
   recomputed for the new build against the current base.

### 11.2 Matching new money into it

```
for each new source line:
    statement line   -> key = work_no  ; candidate rows = prior rows whose column C holds it     (M1)
    platform line    -> key = isrc     ; candidate rows = prior rows whose column A holds it     (M2)
    either           -> links a prior row carries (both codes on one row) apply                  (M3)
    guards (§6.3) run on every candidate; decisions (§6.4) take precedence
    exactly one candidate  -> money placed on that row, in the new distribution's columns
    several candidates     -> book-once owner (same song) or SHARED_CODE hold (different songs)
    no candidate           -> a new row is appended; finding NOT_IN_BASE; title proposals (M4/M5)
                              against prior rows are attached to the finding
```

### 11.3 Guarding against double counting

* A new statement whose distribution signature already exists in the prior output is flagged
  `ALREADY_IN_BASE`. Equal totals → skipped. Different totals → held as a possible re-issue (§8.2).
* A new platform report whose months are already present for that platform → the same test
  per month.

### 11.4 What is carried and what is recomputed

| Item | Rule |
|---|---|
| Prior money cells | carried as they are, tagged `source = previous output <sha256>` |
| Prior rows | keep their row keys; merged rows keep the first row's key. Output order follows §13.1 (default SKV sort), or `keep previous order, new rows at the end` if chosen for the run |
| New distribution columns | inserted in section order, then by statement date (§13.1) |
| Row totals, FY blocks, `TOTAL` row | **recomputed from the cells**, never copied |
| Audit column | appended: `SKV9: +₹x from P2583 (work 31627630)` style provenance |

**Conservation:** new grand total per money kind = prior grand total + Σ new included sources.
A build that breaks this fails.

### 11.5 Outputs of an incremental run

1. The next master generation (`<CLIENT>-RD-SKV<n+1>`).
2. **Paid but not in previous output** — the 3-column hand-off list (`ISRC · Song Name ·
   Work No`) and the revenue workbook in the SKV layout (§13.3). Reference:
   `Extra_songs_not_in_Spotify-RD-SKV1_and_SVF-RD-SKV5.xlsx` — 148 recordings, ₹62,729.83
   platform gross, none of them tied to a prior row by code.
3. **Change log** — every row whose money changed, before → after, per money kind.

---

## 12. Rule sets, decisions and builds

### 12.1 Rule sets

Everything that can change a number lives in a numbered, read-only **rule set**:

| Group | Contents |
|---|---|
| Recognition | layouts (header signatures + mappings), kind-detection thresholds |
| Parties | the workspace's rights holders, societies, overseas society register, platforms, categories and their ordering |
| Money | `recon_tolerance`, rounding method, FX rates, FY headline view |
| Matching | `name_link_policy`, proposal weights and bands, `title_similarity` (default 0.90), `isrc_family_gap` (default 50), amount-spike factor `k` (default 5 × median) |
| Metadata | file-name grammar, category ladder (§2.6) |
| Output | section order, output name pattern, sort order, wide-export soft limit (default 80 distribution blocks ≈ 330 columns; Excel's hard limit is 16,384 columns) |

A change creates rule set `n+1` with author, reason and approver; the previous set is never
edited. A build may only use an **approved** rule set. Every build names the rule set it used.

**Rule set v0 — legacy.** A special, read-only rule set reproduces the behaviour of the scripts
that made `SVF-RD-SKV4` … `SKV8`: no holder scope, first-row-wins on shared ISRCs, title
fallback allowed to place platform money (V2 basis B4/B5). It exists only so golden tests can
reproduce the old outputs exactly (§23) and so the difference between v0 and v1 can be shown,
line by line, before v1 is adopted. It can never be used for a published build.

### 12.2 Decisions

| Decision | Moves money? | Maker | Checker |
|---|---|---|---|
| `LINK` — attach an ISRC / work to a row (accept a proposal) | yes | analyst | approver |
| `BULK_LINK_EXACT` — accept all M4 proposals of a run | yes | analyst | approver |
| `MERGE_ROWS` — two rows are one song | yes (between rows) | analyst | approver |
| `NOT_SAME` — two rows / codes are different songs | no | analyst | — (logged) |
| `ASSIGN_HELD` — place held money on a row | yes | analyst | approver |
| `CODE_OVERRIDE` — a statement line's code is wrong; move it | yes | analyst | approver |
| `STATEMENT_RELATION` — replaces / supplementary | yes | analyst | approver |
| `ACCEPT_DIFFERENCE` — accept a file outside tolerance | yes | operator | approver |
| `SCOPE_HOLDER` — include another rights holder | yes | analyst | approver |
| `CONFIRM_HOLDER` — the rights holder of a platform report or legacy output | yes | operator | approver |
| `ACCEPT_EDITED_BASE` — use a previous output that was edited after export | yes | analyst | approver |
| `FINDING_STATUS` — acknowledge / sent / accepted | no | analyst | — (logged) |
| `RULE_SET_CHANGE` | yes | admin or operator | a different approver |

* The maker can never be the checker. A decision waiting for its checker has no effect.
* **Small teams.** A workspace must have at least two people who can act as checker before it
  can publish a `FINAL` build or approve money-moving decisions; the platform checks this at
  set-up and whenever a role changes. A one-person team names an outside approver (for example
  the finance lead) with the approver role only. Self-approval is never possible, even for admins.
* Decisions are keyed by codes and statement identities, so they carry across runs and uploads.
* Every decision records who, when, why, the evidence shown, and the rule-set version.

### 12.3 Builds

A **build** is fixed by five things, and only these:

```
build = (input fingerprints, base fingerprints, approved decision set, rule-set version, software version)
```

Anything that changes one of them makes a new build: a new file, a file excluded or replaced,
a decision, a rule-set change, a software release.

```
DRAFT ──► BUILDING ──► CHECKED ──► PUBLISHED ──► SUPERSEDED
             │             │
             └──► FAILED   └──► (FINAL requires an approver's sign-off)
```

* `BUILDING` and `FAILED` builds are never shown in the workspace or exported.
* A `PUBLISHED` build is read-only in the database (§19.4). "Version 9" means the same numbers
  for everyone, and the version, rule set and date print on every screen and export.
* Same five inputs ⇒ byte-identical exports.

**Series.** Builds belong to a **series** — one line of versions with one purpose, e.g.
`SVF master` or `SVF Spotify-only`. Generation numbers (`SKV9`, `SKV10` …) count within a
series, and each series has exactly one *current* published build. Every screen shows the
series, generation and publish date, so two people can never mean different things by
"version 9".

**Concurrency.** One build at a time per series (a database lock). Decisions carry the
generation they were made against; a build can only be published on top of the series' current
build — if another build was published meanwhile, the draft is rebuilt on the new parent
first, and any decision that no longer applies is listed for the analyst.

### 12.4 Undo

Undoing a decision creates a **new** build from the same inputs with that decision revoked.
It equals "what the build would be if the decision had never been made" — not a copy of an
earlier build unless it was the latest change. Before applying, the platform lists every later
decision that depends on the one being revoked (e.g. a merge into a row the revoked merge
created) and asks the analyst to revoke or re-point each. Earlier builds never change.

---

## 13. Outputs

### 13.1 The master matrix — SKV8 layout

One worksheet named for its generation. Row 1 = section bands, row 2 = headers, rows 3…N =
songs, blank row, `TOTAL`, the FY-basis note, the provenance note. Freeze after the identity
block; autofilter over the header row.

| Columns | Content |
|---|---|
| Identity | `ISRC` (all ISRCs, primary first, then unregistered ones, `" \| "`-joined) · `Song Name` · `Internal No` (all work numbers, blank when no source has one) · `Rights Holder` (only in multi-holder runs) |
| Totals | `Total Amount` (society royalty) · one `Total <Platform> Revenue` per platform present · optional ratio column |
| Distribution sections | one band per section, `4 × distributions` columns: `Date · Amount · Period · Distribution Number` |
| Platform sections | one band per platform report, one 4-column block per month |
| Usage (optional) | plays per month |
| Total revenue | `FY …` columns (headline view), `Period Not Stated`, `Total Revenue` (= Total Amount) |
| Audit / traceability | `Catalogue Status` (row origin + changes), `Royalty Booked On`, `Match Basis`, `Held / Flags` |

**Song Name** shown on a row: the base title (song list or previous output) → else the most
recent statement title for the work → else the platform title carrying the most revenue.
Every other spelling is kept and shown in the row detail and the mismatch report.

**Row order:** `Total Amount` descending, then platform totals descending, then `norm(Song Name)`
(the SKV rule), unless the run chose `keep previous order`. Row keys never depend on order.

Section order: `YouTube Pre-Claims · YouTube Post-Claims · Facebook / Meta · Spotify ·
<platform reports> · Apple Music · Radio · Zee TV Broadcast · Mechanical · Other /
Unclassified · Redistribution`, then `Overseas - <society>` alphabetically; inside a section,
by statement date. The plan is generated from the data; no column index is hard-coded.
Colours, widths and number formats are the measured SKV system (V2 §19), held as named tokens.

Row origins (the `Catalogue Status` column):

| Origin | Meaning |
|---|---|
| `In base - paid` / `In base - not paid in this run` | a song-list or previous-output row |
| `In base - separate recording of a work paid on another row` | book-once sibling |
| `Not in base - paid by a statement` / `Not in base - platform revenue only` / `Not in base - platform usage only` | appended rows |
| `No base - work` / `No base - recording` | statements-only or platform-only runs |

### 13.2 Size and the long format

The master grows by 4 columns per distribution (SKV8: 225 columns for about 45 distributions
and 6 platform months). Storage is always long — one row per song per distribution — and never
grows sideways. Exports:

| Export | Shape |
|---|---|
| **Master (wide)** | the SKV layout for a chosen period; default = one financial year. Above the rule set's soft limit of distribution blocks the platform asks for a narrower period |
| **Summary** | one row per song, one column per section, per FY |
| **Detail (long)** | one row per song × distribution: identity, section, distribution, date, period, amount, money kind, holder |
| **Works view** | one row per work (composition) with its linked recordings listed beneath it, society royalty on the work line and platform money on each recording line. It shows the many-to-many truth that the per-entry SKV layout flattens |

The cover sheet of every export states the **grain** in words — "one row per song-list entry",
"one row per work" or "one row per recording" — so no reader assumes one row = one song.

### 13.3 Companion workbooks

| Workbook | Content |
|---|---|
| **Paid but not in base** — list | 3 columns: `ISRC · Song Name · Internal No`, sorted by money at stake; banner names the base, sources, period and mode |
| **Paid but not in base** — revenue | the same songs in the SKV layout, every figure recomputed from the source files (never copied from the master) |
| **Same name, different code** | group · title as each source spells it · ISRCs · work numbers · kind · score with its signals · decision · money before/after per kind · which codes are in the base |
| **Mismatch report** | `SAME_CODE_DIFF_NAME` and friends with class (§7.2), status (§7.3), money per kind in separate columns |
| **Held money** | every held amount, its guard, its codes, its money kind |
| **Statement register** | every file: holder, society, category, distribution, period, dates, lines, total, check result, included / excluded / replaced |
| **Change log** | incremental runs: rows changed, before → after |
| **Cover sheet** (first sheet of every export) | build id and state, rule set, software version, inputs with fingerprints, excluded files and their totals, held totals, headline quality metrics |

### 13.4 The `_rd_meta` sheet

Every export carries a hidden, protected sheet `_rd_meta`: workspace, build id, generation,
rule set, software version, grain, one line per row (`row_key`, codes), one line per
distribution column (signature), grand totals per money kind, and the sha256 of the visible
sheet's values. It makes a later re-import (§11) exact and detects edits made after export.

### 13.5 Excel safety and determinism

* Any text cell beginning with `=`, `+`, `-`, `@`, tab or carriage return is written as a
  literal string (prefixed with `'`). Titles and names come from outside and are untrusted.
* No timestamps inside sheets; sorted iteration everywhere; `penny_fix` the only rounding
  path; totals located by content, never by row arithmetic; number formats applied by column
  role. Same build ⇒ same sha256.

---

## 14. Accuracy model — invariants

Every build asserts all of these in S9. One failure fails the build and names the rows.

| # | Invariant | Reference value |
|---|---|---|
| I1 | per included statement: Σ money lines = Σ sub-totals = printed total (± tolerance) | 46/46 files |
| I2 | extraction stops before `TOTAL ROYALTIES` | last work of the IPRS Spotify file = `0.37` |
| I3 | footer tables agree with the lines | — |
| I4 | Σ output society royalty = Σ included statements' printed totals | ₹33,23,794.31 (46 files) |
| I5 | Σ output platform gross = Σ included reports' totals, per platform | ₹78,89,496.76 (Spotify MRM) |
| I6 | Σ FY buckets = Σ Total Amount, for each FY view | ₹33,23,794.31 |
| I7 | every base entry has exactly one row per rights holder in scope (per-entry grain) | 2,762 |
| I8 | every work's royalty is shown on exactly one row (book-once) | — |
| I9 | every platform month column sums to that month's reported total | — |
| I10 | no money kind is ever added to another (checked on every numeric column's declared kind) | — |
| I11 | held money appears in the held report and in the totals as `not yet assigned` | — |
| I12 | no statement identity counts twice; no prior distribution is added again | — |
| I13 | incremental conservation: new total = prior total + Σ new sources, per kind | SKV4 ₹32,09,945.73 + ₹1,13,848.57 = SKV5 ₹33,23,794.31 (compared unrounded; the paisa comes from rounding) |
| I14 | a merge or link decision changes no column total | 60/60 columns SKV7 → SKV8 |
| I15 | a merge loses no code | — |
| I16 | no finding's code is present in the base it was audited against (leak test) | 0 |
| I17 | the paid-but-not-in-base list and its revenue workbook hold the same songs in the same order | 93 = 93 |
| I18 | every companion-workbook amount is re-derived from the source files by an independent pass | 0 differences |
| I19 | Σ(finding money) + Σ(excluded-by-base money) = the source's own total | per source |
| I20 | every attachment of money records its rung, evidence and rule-set version | — |
| I21 | a published build's rows are unchanged since publish (hash) | — |
| I22 | re-importing an export's `_rd_meta` reproduces its rows and totals exactly | — |
| I23 | a printed total equals the sum of its printed parts | — |
| I24 | files outside the holder scope contribute ₹0 | (S-32) excluded → ₹53.47 out |
| I25 | same five build inputs ⇒ byte-identical exports | sha256 equality |

**Two independent implementations.** The test suite recomputes I4–I9, I13 and I16–I19 from
the raw files with a deliberately different method (pairwise instead of grouped, per-line
instead of per-row). A number only one implementation produces is not trusted.

---

## 15. Quality metrics

Pipeline checks prove the process ran. These measure whether the answers are right. They are
computed on every build, printed on the cover sheet and trended in the workspace.

| Metric | Definition | Baseline from the reference files |
|---|---|---|
| Coverage precision | findings reviewed as `CONFIRMED_MISSING` ÷ findings reviewed | 41 of 93 (44%) — SVF's review of the 93-song list: 34 not SVF's, 18 already linked |
| Not-ours rate | findings reviewed as `NOT_OURS` ÷ reviewed | 34 of 93 |
| Title-moved money | rows / money attached through any title rung | 81 rows carrying ₹8,25,822.62 platform gross in SKV8 |
| False-link rate | automatic code links later corrected by a `CODE_OVERRIDE`, `ASSIGN_HELD` or revoked `LINK` ÷ automatic links | measured from the first review |
| Hold rate | automatic links held by a guard ÷ automatic links, per guard | measured on the first V3 build |
| Shared codes | recordings under more than one work in the base | 263 |
| Other-holder files | files outside scope in the upload set | 1 of 46 |
| Held money | total held, by guard | — |
| Period not stated | society royalty with no readable period | ₹29,275.34 |
| Proposal acceptance | accepted ÷ decided, per score band | measured from the first review |
| Reversal rate | decisions revoked within 90 days ÷ decisions made | measured from the first review |
| Label checks | labels that restate a count (row count, distribution count) match the data | SKV8 `TOTAL` row says "3,149 song rows"; the data has 3,144 |

Proposal weights (§6.6) are re-fitted every quarter against the accepted/rejected decisions,
as a rule-set change.

---

## 16. Data model

**Engine:** PostgreSQL 16. Every table carries `workspace_id`; row-level security limits every
query to the caller's workspace (§19.4). Money is `NUMERIC(20,8)`. Pipe-joined strings never
exist in the database — lists are child rows, joined only when exporting.

### 16.1 Entity overview

```
workspace ─┬─< party (rights holders, distributors)         rule_set ─┬─< layout
           ├─< app_user ─< role_grant                                  ├─< fx_rate
           │                                                           └─< matching / money / output settings (JSONB)
           ├─< source_file ─┬─< statement ─< royalty_line >── work
           │                │     └─< statement_footer
           │                ├─< platform_report ─< platform_line >── recording
           │                ├─< song_list ─< song_list_entry ─┬─< entry_work >── work
           │                │                                 └─< entry_isrc >── recording
           │                └─< prior_output ─┬─< prior_row ─┬─< prior_row_work / prior_row_isrc
           │                                  │              └─< prior_cell >── prior_distribution
           │                                  └─< prior_distribution
           ├─< decision ─< decision_member
           ├─< finding_status
           ├─< series (one line of versions, its holder scope, its current build)
           └─< build ─┬─< build_input
                      ├─< song_row ─┬─< song_row_work / song_row_recording
                      │             └─< cell (row × column, amount, money kind)
                      ├─< column_def            ├─< row_fy (row, fy, view, amount)
                      ├─< link_used (rung, evidence)
                      ├─< hold      ├─< finding      ├─< proposal
                      └─< export_artifact
job (queue)                                   audit_event  → separate database (§19.5)
```

### 16.2 Core tables (abridged DDL)

```sql
CREATE TABLE workspace (id BIGSERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL,   -- 'SVF'
                        name TEXT NOT NULL, output_pattern TEXT NOT NULL);       -- '{code}-RD-SKV{gen}'

CREATE TABLE party (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL REFERENCES workspace,
  kind TEXT NOT NULL CHECK (kind IN ('RIGHTS_HOLDER','DISTRIBUTOR')),
  society TEXT, member_no TEXT, ipi_name_no TEXT, ipi_base_no TEXT, name TEXT NOT NULL,
  is_own BOOLEAN NOT NULL DEFAULT FALSE,           -- the workspace's own holders
  UNIQUE (workspace_id, kind, society, member_no));

CREATE TABLE rule_set (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL, version INT NOT NULL,
  settings JSONB NOT NULL, content_sha256 TEXT NOT NULL,
  created_by BIGINT NOT NULL, approved_by BIGINT, reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (workspace_id, version),
  CHECK (approved_by IS NULL OR approved_by <> created_by));

CREATE TABLE layout (
  id BIGSERIAL PRIMARY KEY, rule_set_id BIGINT NOT NULL REFERENCES rule_set,
  kind CHAR(1) NOT NULL, header_signature TEXT NOT NULL, mapping JSONB NOT NULL,
  UNIQUE (rule_set_id, kind, header_signature));

CREATE TABLE source_file (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL,
  sha256 TEXT NOT NULL, original_name TEXT NOT NULL, bytes BIGINT NOT NULL,
  detected_kind CHAR(1), layout_id BIGINT REFERENCES layout, status TEXT NOT NULL
    CHECK (status IN ('QUARANTINED','REVIEW','READY','EXCLUDED','REJECTED')),
  object_key TEXT NOT NULL,                      -- write-once originals store
  uploaded_by BIGINT NOT NULL, uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, sha256));

CREATE TABLE statement (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL, source_file_id BIGINT NOT NULL,
  holder_id BIGINT NOT NULL REFERENCES party, society TEXT NOT NULL, category TEXT NOT NULL,
  dist_no TEXT, sub_run TEXT, overseas_society TEXT,
  period_start DATE, period_end DATE, payment_date DATE, file_date DATE, date_estimated BOOLEAN,
  identity_key TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  printed_total NUMERIC(20,8), lines_total NUMERIC(20,8), subtotal_total NUMERIC(20,8),
  recon TEXT NOT NULL CHECK (recon IN ('PASS','FAIL','ACCEPTED_WITH_DIFFERENCE')),
  relation TEXT NOT NULL DEFAULT 'ORIGINAL' CHECK (relation IN ('ORIGINAL','REPLACEMENT','SUPPLEMENTARY')),
  replaces_id BIGINT REFERENCES statement);

CREATE TABLE work      (id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL,
                        society TEXT NOT NULL, work_no TEXT NOT NULL, UNIQUE (workspace_id, society, work_no));
CREATE TABLE recording (id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL,
                        isrc TEXT NOT NULL, UNIQUE (workspace_id, isrc));

CREATE TABLE royalty_line (
  id BIGSERIAL PRIMARY KEY, statement_id BIGINT NOT NULL REFERENCES statement,
  line_no INT NOT NULL, work_id BIGINT REFERENCES work, raw_work_no TEXT, title TEXT,
  language TEXT, party_name TEXT, role TEXT, own_pct NUMERIC(7,4), coll_pct NUMERIC(7,4),
  pool TEXT, source TEXT, usage_split JSONB,
  amount NUMERIC(20,8) NOT NULL, currency CHAR(3) NOT NULL DEFAULT 'INR',
  is_negative BOOLEAN GENERATED ALWAYS AS (amount < 0) STORED,
  UNIQUE (statement_id, line_no));

CREATE TABLE platform_report (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL, source_file_id BIGINT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('REVENUE','USAGE')), platform TEXT NOT NULL,
  distributor_id BIGINT REFERENCES party, holder_id BIGINT REFERENCES party,
  currency CHAR(3), month_from DATE, month_to DATE, content_sha256 TEXT NOT NULL);

CREATE TABLE platform_line (
  id BIGSERIAL PRIMARY KEY, report_id BIGINT NOT NULL REFERENCES platform_report,
  month DATE NOT NULL, recording_id BIGINT REFERENCES recording, content_name TEXT,
  album TEXT, upc TEXT, amount NUMERIC(20,8), plays BIGINT);

CREATE TABLE decision (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL, kind TEXT NOT NULL,
  subject JSONB NOT NULL,              -- keyed by codes / statement identities, never row numbers
  evidence JSONB NOT NULL, reason TEXT, rule_set_version INT NOT NULL,
  maker BIGINT NOT NULL, checker BIGINT,
  state TEXT NOT NULL CHECK (state IN ('PROPOSED','APPROVED','REJECTED','REVOKED')),
  moves_money BOOLEAN NOT NULL, made_on_generation INT NOT NULL,
  revokes_id BIGINT REFERENCES decision, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (checker IS NULL OR checker <> maker),
  CHECK (NOT (moves_money AND state = 'APPROVED') OR checker IS NOT NULL));

CREATE TABLE series (id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL, name TEXT NOT NULL,
                     holder_scope BIGINT[] NOT NULL, current_build_id BIGINT,
                     UNIQUE (workspace_id, name));

CREATE TABLE build (
  id BIGSERIAL PRIMARY KEY, workspace_id BIGINT NOT NULL, series_id BIGINT NOT NULL REFERENCES series,
  generation INT NOT NULL, UNIQUE (series_id, generation),
  parent_build_id BIGINT REFERENCES build, rule_set_id BIGINT NOT NULL REFERENCES rule_set,
  software_version TEXT NOT NULL, grain TEXT NOT NULL,
  inputs_sha256 TEXT NOT NULL, decisions_sha256 TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('DRAFT','BUILDING','CHECKED','PUBLISHED','SUPERSEDED','FAILED')),
  is_final BOOLEAN NOT NULL DEFAULT FALSE, approved_by BIGINT,
  created_by BIGINT NOT NULL, published_at TIMESTAMPTZ,
  CHECK (NOT is_final OR (approved_by IS NOT NULL AND approved_by <> created_by)));

CREATE TABLE cell (                                   -- the long format: never grows sideways
  build_id BIGINT NOT NULL, row_id BIGINT NOT NULL, column_id BIGINT NOT NULL,
  money_kind TEXT NOT NULL CHECK (money_kind IN ('SOCIETY_ROYALTY','PLATFORM_GROSS','PLATFORM_NET','USAGE')),
  amount NUMERIC(20,8) NOT NULL, origin TEXT NOT NULL,   -- 'source' | 'previous_output'
  PRIMARY KEY (build_id, row_id, column_id));
```

Published rows are protected by a trigger that rejects `UPDATE`/`DELETE` on any table row
whose build is `PUBLISHED` or `SUPERSEDED`; the application's database login has no right to
disable triggers. A trigger does not stop a database owner, so publishing also writes the
build's content hash to the separate audit database (§19.5); a nightly job re-hashes every
published build and alerts on any difference (I21).

`platform_report` also carries `revenue_basis` (`GROSS` | `NET`) and the confirmed
`holder_id`; `prior_output` carries its confirmed `holder_id`, detected generation, `legacy`
flag and integrity result.

---

## 17. Roles and permissions

Checked **on the server for every request**, including exports and downloads. The screen
only hides what the server already refuses.

| Action | Viewer | Analyst | Data operator | Approver | Admin |
|---|---|---|---|---|---|
| View published builds, download exports | ✓ | ✓ | ✓ | ✓ | ✓ |
| Upload song lists and previous outputs | | ✓ | ✓ | | |
| Upload statements and platform reports | | | ✓ | | |
| Confirm a column mapping / new layout (maker) | | | ✓ | | ✓ |
| Start a run, review proposals and findings | | ✓ | | | |
| Make money-moving decisions (maker) | | ✓ | | | |
| Approve decisions, `FINAL` builds, rule-set changes (checker) | | | | ✓ | |
| Manage users, holders, rule-set drafts | | | | | ✓ |

* Nobody approves their own change; the database enforces it (§16.2).
* Admins manage access but cannot approve money-moving decisions.
* Viewers see published builds of their workspace only.

---

## 18. System architecture

### 18.1 Components and trust zones

```
 ┌──────────────────────────── ZONE 1: PUBLIC EDGE ─────────────────────────────┐
 │  Browser (React app) ──HTTPS──► Load balancer + WAF ──► API gateway (nginx)   │
 │  company SSO (OIDC, MFA) ◄──────────────────────────────┘                     │
 └──────────────────────────────────────┬───────────────────────────────────────┘
                                        │ session cookie, every call checked
 ┌──────────────────────────── ZONE 2: APPLICATION ─────────────────────────────┐
 │  API service (FastAPI)  ── roles, workspace, maker-checker on every request   │
 │  Build workers          ── S3–S11, write to BUILDING builds only              │
 │  Export workers         ── read PUBLISHED builds, write to the exports store  │
 │  Job queue              ── a table in PostgreSQL (SKIP LOCKED)                │
 └───────┬──────────────────────────┬───────────────────────────┬───────────────┘
         │                          │                           │ add-only
 ┌───────▼──────── ZONE 3 ──────┐ ┌─▼──── ZONE 4: INTAKE ─────┐ ┌─▼──── ZONE 5: AUDIT ─────────┐
 │ PostgreSQL (results)         │ │ Quarantine worker          │ │ Audit database (separate     │
 │  row-level security,         │ │  no network, no DB write,  │ │  instance, INSERT-only login,│
 │  published rows locked       │ │  type + size + zip checks, │ │  hash-chained entries)       │
 │ Object store                 │ │  virus scan, safe parser   │ │ Daily copy → write-once      │
 │  originals  (write-once)     │ │  → clean JSON to Zone 2    │ │  bucket                      │
 │  exports    (90-day drafts)  │ │ Quarantine bucket (7 days) │ │                              │
 └──────────────────────────────┘ └────────────────────────────┘ └──────────────────────────────┘
   Secrets manager · KMS keys · backups in a separate account · monitoring and alerts (all zones)
```

### 18.2 Stack

| Concern | Choice | Reason |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite; TanStack Query + Table + Virtual | Proven in the prototype; 3,000+ rows × 200+ columns needs virtualisation |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic | All parsing, matching and Excel logic is Python |
| Money | `decimal.Decimal` in Python, `NUMERIC` in the database | Exact arithmetic end to end |
| Excel | `openpyxl` (read-only mode for large files; `defusedxml` installed) | Proven on every reference file |
| Queue | PostgreSQL job table (or Procrastinate) | One less system to secure; job state and results commit together |
| Database | PostgreSQL 16, managed (e.g. Amazon RDS, Mumbai region) | Point-in-time recovery, encryption at rest |
| Objects | S3 (Mumbai) with Object Lock, or MinIO on own servers | Write-once originals, separate stores |
| Identity | OIDC single sign-on (Google Workspace or Microsoft Entra ID), MFA from the company account | No local passwords; leaver access ends when the company account is disabled |
| Secrets | AWS Secrets Manager or HashiCorp Vault | No keys in `.env` files |
| Runtime | Containers (ECS or a small Kubernetes / Docker host), separate dev / staging / prod accounts | Same image in every environment |
| Observability | OpenTelemetry logs + metrics, alerting | Problems seen the day they happen |

### 18.3 Why the queue lives in PostgreSQL

A build writes thousands of rows and must never be half-visible. With the queue in the same
database, a job's final state and its build's `CHECKED` state commit in one transaction. A
worker that dies leaves the build in `BUILDING`; a sweeper marks it `FAILED` after a timeout,
and a retry starts a fresh build from the same fingerprints.

---

## 19. Security design

### 19.1 Web app and gateway

* Server-side sessions in `HttpOnly; Secure; SameSite=Strict` cookies; 8-hour lifetime; CSRF
  token on every state-changing call. No tokens in browser storage.
* Every endpoint checks workspace, role and object access; export and download endpoints
  re-check at download time. Object ids are random (UUIDv7); the access check is the guard.
* Downloads are always `Content-Disposition: attachment`, with the true content type and
  `X-Content-Type-Options: nosniff`. Uploaded originals are never rendered in the browser.
* Headers: HSTS, a strict Content-Security-Policy, `frame-ancestors 'none'`. Upload size limit
  and rate limits at the gateway.

### 19.2 File intake (the highest-risk surface)

* Accept `.xlsx` and `.csv` only. `.xlsm`, `.xls`, `.xlsb`, and any `.xlsx` containing
  `vbaProject.bin`, external links or OLE objects are **rejected**, not sent for mapping.
* The file type is checked from content (ZIP structure and `[Content_Types].xml`), not the name.
* Limits: 64 MB upload, 512 MB unzipped, 1,000,000 cells, 200 sheets; ZIP entries are checked
  for ratio and path tricks before extraction.
* XML is parsed with `defusedxml`; formulas are never evaluated; cached values are read.
* Virus scan (ClamAV) before parsing.
* All of this runs in the quarantine worker: its own container, no outbound network, a
  read-only filesystem except a temporary directory, no database write access. It hands clean
  JSON to Zone 2.
* A matching fingerprint only proves the bytes are the same; identity checks (§4, §8) decide
  what the file is.

### 19.3 Jobs and workers

* Every job is keyed by its input fingerprints and is safe to repeat: a re-run replaces its
  own output.
* Builds are transactional (§18.3). A failed build is never shown or exported.
* The queue has no network listener of its own; it sits behind PostgreSQL's authentication.

### 19.4 Database

* Separate logins: `app_rw` (drafts and decisions), `export_ro` (read published builds),
  `migrator` (schema changes; never used by the running app). None of them owns the tables.
* Row-level security on `workspace_id` for every table, set from the verified session.
* Published builds are locked by trigger (§16.2). Any change by `migrator` is written to the
  audit database. Because a database owner can bypass triggers, each published build's content
  hash is also stored in the audit database at publish time and re-verified nightly — an edit
  by anyone, including an administrator, is detected.
* No binary floating point for money or FX rates anywhere upstream (§9.2).

### 19.5 Audit log

* A separate PostgreSQL instance. The application login can only `INSERT`; it cannot update,
  delete or truncate.
* Each event: who, what, when, from where, before/after hashes, and the sha256 of the previous
  event (a hash chain) — any edit or gap breaks the chain, and a nightly job verifies it.
* A daily copy goes to a write-once bucket.
* Events: sign-in, upload, classification change, mapping and rule-set changes, every
  decision and its approval, build state changes, exports and downloads, role changes.
* Nobody who can change results can change the record of it.

### 19.6 Object store

* Three buckets with separate permissions: `originals` (Object Lock, compliance mode, for the
  retention period), `exports` (drafts expire after 90 days; published exports kept with the
  build), `quarantine` (7 days).
* Block all public access; SSE-KMS encryption; access logging.
* Every object key starts with its workspace (`<workspace>/…`), and the storage policy lets each
  service reach only its own workspace's prefix for the request it is serving — one client can
  never be served another client's file, even by a bug in the application.
* Download links are pre-signed for 5 minutes and issued only after the permission check.

### 19.7 Cross-cutting

| Area | Control |
|---|---|
| Secrets | secrets manager; separate keys per environment; rotation every 90 days |
| Encryption | TLS everywhere, including inside the private network; database, backups and buckets encrypted with KMS keys |
| Data residency | all data in an India region; statements contain writers' names and IPI numbers, which are personal data under the Digital Personal Data Protection Act, 2023 |
| Leavers | sign-in only through the company account, so disabling it ends all access; no local accounts; API tokens belong to a person and expire; quarterly access review |
| Monitoring | alerts on failed sign-ins, refused permissions, large or unusual downloads, failed builds, audit-chain breaks |

---

## 20. Operations

### 20.1 Retention (proposed, pending sign-off — §26)

| Data | Kept | Basis |
|---|---|---|
| Statements, platform reports, song lists used by a published build | 8 financial years | books-of-account retention under the Companies Act, 2013 |
| Published builds and their exports | 8 financial years | support the accounts |
| Draft exports | 90 days | rebuildable |
| Uploads never used by a published build | 2 years | working files |
| Audit events | 8 financial years | evidence |

Deletion needs an admin and an approver and is logged. Builds that used a deleted file are
marked `SOURCE REMOVED — cannot be rebuilt`.

**Personal data.** Statements carry writers' names and IPI numbers. If a person asks for their
data to be erased while the financial records must still be kept, their name is replaced by a
reference in every derived table and export; the original file stays under its legal hold until
the retention period ends, then is deleted. The request and the action are logged.

### 20.2 Backup and recovery

* PostgreSQL: continuous WAL archiving (point-in-time recovery) + nightly snapshots, copied to
  a separate account. Object store: versioning + cross-account replication.
* Targets (proposed): lose at most **1 hour** of data; service back within **4 hours**.
* A restore drill every quarter into a clean environment, ending with a golden-run comparison
  (§23) and a written result.

### 20.3 Configuration

Environment settings (`DATABASE_URL`, bucket names, SSO client id, limits) come from the
secrets manager. Anything that changes a number is **not** an environment setting — it is in
the rule set (§12.1).

---

## 21. API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/files` | upload (multipart) → quarantine; returns `{id, sha256, duplicate}` |
| `GET` | `/api/files/{id}` | status, detected kind, layout match, holder / distributor, checks |
| `POST` | `/api/files/{id}/mapping` | propose a column mapping (layout draft) |
| `POST` | `/api/runs` | body: `{bases[], sources[], holders[], rule_set}` → run manifest |
| `GET` | `/api/runs/{id}/validation` | per file: totals, footer checks, identity, duplicates, relation |
| `POST` | `/api/runs/{id}/build` | start a build → job |
| `GET` | `/api/builds/{id}` | state, cover data, totals per money kind, quality metrics |
| `GET` | `/api/builds/{id}/rows` · `/rows/{key}` | paginated rows · one row with every cell and its provenance |
| `GET` | `/api/builds/{id}/findings?kind=&status=` | findings with carried status |
| `GET` | `/api/builds/{id}/proposals?band=` | review queue |
| `GET` | `/api/builds/{id}/holds` | held money |
| `POST` | `/api/decisions` | make a decision (maker) |
| `POST` | `/api/decisions/{id}/approve` · `/reject` · `/revoke` | checker actions |
| `POST` | `/api/builds/{id}/publish` | publish (FINAL requires an approver) |
| `POST` | `/api/builds/{id}/exports/{kind}` · `GET /api/exports/{id}` | generate → job · short-lived download link |
| `GET` | `/api/rule-sets` · `POST /api/rule-sets` | list · propose a new version |
| `GET` · `POST` | `/api/parties` | rights holders and distributors of the workspace |
| `POST` | `/api/files/{id}/metadata` | confirm holder, category, period, currency, revenue basis (operator) |
| `GET` · `POST` | `/api/layouts` · `/api/layouts/{id}/approve` | layout drafts and their approval |
| `PATCH` | `/api/findings/{fingerprint}/status` | set a finding's status (logged) |
| `GET` | `/api/series` · `/api/series/{id}/builds` | series and their version history |
| `GET` | `/api/rule-sets/{a}/diff/{b}` · `/api/builds/{a}/diff/{b}` | what changed between two rule sets or two builds |
| `GET` | `/api/jobs/{id}` | queued / running / succeeded / failed, progress |

Lists use cursor pagination and deterministic order. Lists of codes are returned as arrays,
never joined strings.

---

## 22. Workspace (frontend)

| Tab | What the user does |
|---|---|
| **Files** | drag and drop any files; each card shows kind, layout match (exact / changed / new), rights holder or distributor, period, checks; duplicates and other-holder files are badged |
| **New run** | 1. pick rights holder(s) · 2. optional base: song list and/or previous output · 3. pick sources · 4. see the detected mode and what the output will contain |
| **Validation** | every statement's line total, sub-total and printed total, footer checks, identity and relation; excluded files and their money |
| **Review** | held money · proposals by score band (accept, reject, bulk-accept exact under the policy) · conflicts with earlier decisions · shared codes |
| **Master** | the matrix (virtualised), search by ISRC / title / work number, filters by origin and flags; a row opens every cell with its file, line, rung and decision |
| **Findings** | paid but not in base · same name / different code · mismatches, each with status and history |
| **Approvals** | the approver's queue: decisions, `FINAL` builds, rule-set changes, accepted differences |
| **Exports** | every workbook per build, with sha256 and history |
| **Settings** | rights holders, distributors, platforms, rule-set versions (diff view), users and roles |

UI rules: money right-aligned `#,##0.00`; money kinds visually separated and never summed on
screen; a blank code renders blank ("not in any source"); anything a title decided carries a
visible basis chip; the build's version and rule set sit in the header of every page.

---

## 23. Test plan

| Layer | Tests |
|---|---|
| Unit | `noi`, `ik`, `norm`, `norm2`, `fold`; `Decimal` parsing; `penny_fix`; file-name parsing over all 46 real names; letterhead parsing |
| Kinds | detection on all 50 reference files; a changed-layout file (extra column) goes to review; a macro file is rejected; a ZIP bomb is stopped |
| Extraction | three-way and footer checks on every reference statement; the `TOTAL ROYALTIES` hard-stop regression |
| Golden runs, one per mode (rule set **v0**) | statements only → matches `SVF-RD-SKV4` rows and totals · + IPRS Spotify statement → `SKV5` · + Spotify MRM → `SKV6` · + song list → `SKV7` · + reference merges → `SKV8` (with `(S-32)` in scope) |
| v0 → v1 difference report | the same inputs under rule set v1 must differ from SKV8 **only** in the expected ways: `(S-32)` out (−₹53.47), shared-ISRC money held (up to 19 ISRCs, ₹1,43,068.13 gross), title-placed platform money turned into proposals (81 rows), and new flags. Any other difference fails the test |
| Metadata | every reference file name parses; a statement renamed to a bare `statement.xlsx` still gets its category from the footer and asks the operator only for the period |
| Scenarios from practice | statements only (no list) · statements + list with same name / different ISRC flagged · previous output + IPRS Spotify statement · previous output + Spotify MRM ⇒ 148-song list · multi-holder run with one work paid to two holders stays on separate rows · a `NET` report never adds to a `GROSS` one · ISRC family flagged, not merged |
| Incremental | `SKV4` as previous output + the IPRS Spotify statement ⇒ same money as the full `SKV5` build; `SKV5` + MRM ⇒ the 148-song paid-but-not-in-previous-output list; re-adding an included statement ⇒ `ALREADY_IN_BASE` |
| Holders | the 46-file set with SVF scope ⇒ `(S-32)` excluded and totals lower by ₹53.47 |
| Identity | a recording under two works ⇒ held as shared; a `NOT_SAME` decision blocks a later code join and raises a conflict |
| Money | negative-line and re-issue fixtures; FX fixture; both FY views; kinds never summed |
| Decisions | maker ≠ checker enforced by the database; undo of a middle decision with a dependent decision |
| Round trip | export → re-import `_rd_meta` ⇒ identical rows and totals; an edited export is detected |
| Security | role checks on every endpoint incl. download; cross-workspace access denied by row-level security; formula-escaping in exports |
| Property | shuffling input order changes no output byte; two runs of the same build ⇒ same sha256 |

---

## 24. Migration from V2 and the prototype

| Area | Keep | Change |
|---|---|---|
| Parsing rules (carry-forward, money-line rule, hard stop, overseas columns, file-name grammar) | ✓ | add letterhead holder parsing and footer checks |
| SKV layout, colours, section order | ✓ | add money-kind totals per platform, two FY views, `_rd_meta` |
| Link ladder L1–L6 (V2) | as M1–M6 | add guards, precedence, policy |
| Catalogue as `user_sheet` with `is_catalogue` | — | replaced by the song-list role, optional |
| `build_run` lineage | ✓ | builds fixed by five inputs; lifecycle states; maker-checker |
| Prototype SQLite, in-process jobs | — | PostgreSQL + PostgreSQL queue |
| Prototype role from `X-Role` header (default `analyst`) | — | removed; SSO session + server-side checks |
| Floats in `num()` | — | `Decimal` |
| Settings in environment (`RECON_TOLERANCE`, `MERGE_SUGGEST_THRESHOLD`) | — | moved into the rule set |

The existing outputs `SVF-RD-SKV4` … `SKV8` are accepted as previous outputs (legacy kind F),
so work continues from `SKV8` without a rebuild. Importing `SKV8` as the base of the first V3
run will, by design:

1. ask the operator to confirm its rights holder (SVF `5154290`);
2. raise `TITLE_PLACED_IN_BASE` on the 81 rows whose platform money a title placed;
3. raise `SHARED_CODE` on the ISRCs listed under more than one work;
4. flag the `(S-32)` column (member `8875288`, ₹53.47) as `OTHER_HOLDER` money inside the base,
   for a `SCOPE_HOLDER` or removal decision;
5. recompute the FY block and correct the stale `TOTAL`-row label.

Before rule set v1 is adopted, the v0 → v1 difference report (§23) is reviewed and signed off.

---

## 25. Build order

1. `domain/normalize.py` (with `Decimal` and `fold`), `domain/filename.py`, `domain/letterhead.py`,
   `domain/link.py` + unit tests.
2. PostgreSQL schema, row-level security, publish-lock triggers, seeds; rule set v0 (legacy)
   and v1 from the reference settings.
3. Quarantine worker: type checks, limits, scan, safe parsing → clean JSON.
4. Kind detection + layout registry with exact signatures; prove on all 50 reference files.
5. Statement extraction with footer checks and statement identity; I1–I3.
6. Song-list and platform-report loading; previous-output reader (legacy + `_rd_meta`).
7. Identity resolution: works, recordings, links, guards, holds, precedence, proposals.
8. Money placement, book-once, FY views, conservation; I4–I13.
9. SKV writer + companion workbooks + cover + `_rd_meta`; golden runs for all modes.
10. Incremental merge; the SKV4 → SKV5 → SKV6 and 148-song tests.
11. Decisions with maker-checker, undo with dependencies, finding statuses.
12. API with server-side authorisation; SSO; audit database with hash chain.
13. Frontend tabs in §22 order.
14. Operations: backups, restore drill, monitoring, retention jobs.

---

## 26. Items needing business sign-off

| # | Item | Proposed default |
|---|---|---|
| 1 | Financial-year headline view | Earned in FY, with Received in FY alongside |
| 2 | Retention periods (§20.1) | 8 financial years for statements and published builds |
| 3 | Who acts as approver | a named finance or operations lead per workspace |
| 4 | Reconciliation tolerance | ₹0.05 per file |
| 5 | Hosting | cloud, India region |
| 6 | Recovery targets | 1 hour data loss, 4 hours to restore |
| 7 | Currency of the Spotify MRM report | to be confirmed by the distributor |
| 8 | `name_link_policy` default | `suggest` |
| 9 | `(S-32)` (member 8875288) in SVF's run | excluded from SVF's scope |
| 10 | Revenue basis of each distributor's reports | confirmed per distributor at first upload |
| 11 | Outside approver for one-person teams | the client's finance lead |
| 12 | Adopting rule set v1 over the legacy behaviour | after the v0 → v1 difference report is reviewed |

---

## 27. Appendices

### Appendix A — reference inputs (measured)

| Location | Files | Kind | Facts |
|---|---|---|---|
| `input/batch-1` | 45 statements | A (27) + B (18) | rights holder SVF `5154290` on 44 files; `(S-32)` is member `8875288` |
| `input/batch-1` | `(S-46)SVF list of Song -April 2026.xlsx` | C | 2,762 rows · 2,571 work numbers · 4,278 ISRCs · 1,037 works with >1 ISRC · 263 ISRCs under >1 work · 148 work numbers on >1 row |
| `input/batch-2` | `Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx` | A | 1,379 works · ₹1,13,848.57 |
| `input/batch-3` | `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | D | 10,960 lines · 1,759 ISRCs · ₹78,89,496.76 gross · no currency column |
| `input/batch-3` | `Spotify L6M.xlsx` | E | 11,222 rows · Jan–Jun 2026 |
| `input/batch-4` | `Songs-Missing-From-SVF-List_Updated.xlsx` | C (reviewed findings) | 93 songs: 34 not SVF work · 18 already linked · 41 real gaps |

All 46 statements pass the three-way check within ₹0.05. None contains a negative line.
Distribution numbers repeat across files (§8.1).

### Appendix B — output lineage mapped to run modes

| Output | Run mode | Rows × columns | Society royalty | Platform gross |
|---|---|---|---|---|
| `SVF-RD-SKV4` | statements only (45 files) | ~2,120 × 193 | ₹32,09,945.73 | — |
| `SVF-RD-SKV5` | previous output + IPRS Spotify statement | 2,144 × 197 | ₹33,23,794.31 | — |
| `Spotify-RD-SKV1` | one statement only | 1,379 × 13 | ₹1,13,848.57 | — |
| `SVF-RD-SKV6` | previous output + Spotify MRM | 2,278 × 222 | ₹33,23,794.31 | ₹78,89,496.76 |
| `SVF-RD-SKV7` | + song list as base | 3,149 × 225 | ₹33,23,794.31 | ₹78,89,496.76 |
| `SVF-RD-SKV8` | + 5 merge decisions, 18 ISRCs attached | 3,144 × 225 | ₹33,23,794.31 | ₹78,89,496.76 |
| `Only-Spotify-RD-SKV2` | statements + platform reports, Spotify only | 1,610 × 44 | ₹1,13,848.57 | ₹78,89,496.76 |
| `Extra_songs_not_in_…SKV5` | paid but not in previous output | 148 | — | ₹62,729.83 |
| `Songs-Missing-From-SVF-List(-Revenue)` | paid but not in song list | 93 | ₹1,140.08 | ₹2,50,956.32 |

### Appendix C — known issues in the current outputs

| Issue | Where | V3 rule |
|---|---|---|
| a statement for another rights holder is inside SVF's totals (₹53.47) | `(S-32)`, SKV8 row 994 | holder scope (§4), I24 |
| society royalty and platform gross added into one total | Mismatch V2 (₹37,83,424.83), batch-4 workbooks | I10 |
| `TOTAL` row label says "3,149 song rows"; data has 3,144 | SKV8 row 3148 | label checks (§15) |
| 81 rows received platform money through a title match | SKV8 column 225 | title never moves money without a decision (§6.5) |
| 263 ISRCs listed under more than one work; first-row-wins | song list, SKV7/8 | shared-code hold (§5.4) |
| ₹29,275.34 has no usage period | SKV8 FY block | Received-in-FY view (§9.4) |
| money parsed as binary floats | V2 scripts, prototype | `Decimal` (§9.2) |

### Appendix D — glossary

| Term | Meaning |
|---|---|
| IPRS | Indian Performing Right Society — the collecting society that issues the statements |
| Rights holder | the society member a statement pays (publisher, composer or author) |
| Distributor | the company that delivers platform reports for a client |
| Work / work number | a composition and IPRS's number for it; society royalty is paid against it |
| Recording / ISRC | one recorded version and its international code; platform revenue is reported against it |
| Base | the rows new money is matched into: a song list, a previous output, or both |
| Source | a file that brings new money: a statement or a platform report |
| Run | base(s) + sources + holder scope + rule set + decisions |
| Build | the fixed result of a run; published builds never change |
| Rule set | the numbered, read-only settings that decide how numbers are produced |
| Guard / hold | a check that stops an automatic link; the money waits, still counted, until a person decides |
| Proposal | a suggested link from title evidence; moves no money until accepted |
| Maker / checker | the person who makes a money-moving decision / the different person who approves it |
| SKV layout | the master-matrix format of `SVF-RD-SKV8`, used for every client |

---

*End of `SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V3.md`. V1 and V2 are kept
for history; where they disagree with V3, V3 is authoritative.*
