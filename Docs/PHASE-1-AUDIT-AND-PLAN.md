# Royalty Processing Platform — Phase 1–3 Audit, Alignment Report and Plan

| | |
|---|---|
| Date | 9 October 2026 |
| Status | Decisions received 9 Oct 2026 (Q1 keep combined total · Q2/Q3 as recommended · Q4 deferred · Q7 exclude S-32 · Q8 INR gross). **Release 1 implemented** — see `RELEASE-1-SYSTEM-GUIDE.md` for what was built, tested and what remains open. |
| Inputs reviewed | `ARCHITECTURE-V3.md` (all 1,555 lines), `MRM_Royalty_Comparison_Flowchart_for_Swatantra.pdf` (13 pages), S-1, S-16, `SVF-RD-SKV8.xlsx`, both batch-4 companion workbooks, the scripts that produced them, SVF's reviewed missing-song list, and the existing `backend/` and `frontend/` code |

Labels used below: **[F]** fact checked against the files during this audit · **[V3]** figure stated in
Architecture V3 and not re-measured here · **[R]** recommendation · **[A]** assumption that needs confirming.

> **Reference file names.** The brief names `SVF-RD-SKV8(1).xlsx` and
> `Non-SVF-Works-Revenue-From-IPRS-And-Spotify(1).xlsx`. These "(1)" copies are not on disk. This audit used
> `Docs/output/batch3-output(Only Spotify RD)/SVF-RD-SKV8.xlsx` and
> `Docs/output/batch4-output/Non-SVF-Works-Revenue-From-IPRS-And-Spotify.xlsx` (see question Q13).

---

## 1. The existing repository

**What it is [F].** A working application called *MRM Royalty Comparison*. It implements the **flowchart**
(stages A–H: classify, validate, identities, like-for-like comparison, 6% benchmark rule, outcome, enquiry pack,
cases). It does **not** produce the SKV8 master or the two companion reports.

| Part | Contents | Verdict |
|---|---|---|
| Stack | FastAPI + PostgreSQL 16 (psycopg) + openpyxl; React 18 + TypeScript + Vite; nginx; docker compose (db, bootstrap, api, web), running locally on :8080 | **Keep.** It matches the brief and V3 §18.2 |
| `parsing/safety.py` | .xlsx/.csv only, content-type check, macros / external links / OLE rejected, ZIP-bomb and size limits | **Keep** |
| `parsing/reader.py` | Reads cached values, resets the wrong 1×1 dimension record, turns floats into exact `Decimal` | **Keep** |
| `parsing/iprs.py` | Standard IPRS statement (kind A): money-line rule, hard stop before `TOTAL ROYALTIES`, letterhead, pool footer | **Keep and extend.** It reconciles all **27 / 27** kind-A statements [F]. It reads **0 lines from all 18 overseas (kind B) statements** [F], because it requires a `SOURCE` column that overseas files do not have (S-16: printed ₹10.2588, extracted ₹0) |
| `parsing/tabular.py`, `detect.py` | Header-based detection of recording, usage and catalogue files | Reuse the parts that fit; detection is replaced by the V3 §2.4 rules |
| `normalize.py` | `Decimal` money, work number / ISRC keys, title keys, transliteration fold, period parsing | **Keep**; add `norm2` and the file-name grammar |
| `security.py`, `api/deps.py` | scrypt passwords, server-side sessions in HttpOnly cookies, CSRF, roles, maker ≠ checker | **Keep.** Gap: roles are global, and **no user-to-client access check exists**. Any signed-in user can read any client's files by id [F] |
| `audit.py` + `0002_controls.sql` | Hash-chained, append-only audit log; frozen approved rows; immutable source amounts | **Keep** |
| `storage.py` | Write-once originals on the local disk | **Keep** |
| `identity.py`, `compare.py`, `rules.py`, `packs.py`, `cases.py` | Flowchart C–H: comparison groups, 6% benchmark, 7-sheet evidence pack, IPRS email, enquiry cases | **Out of scope for this brief.** Keep the code, but take it out of the main navigation (Q11) |
| Frontend | 11 navigation items labelled with flowchart gates ("Intake & validation A–B", "Comparison D·F·G" …) | **Replace** with the simple 5-item interface (§6). It conflicts with the brief's simplicity rules |
| Tests | `tests/` holds 4 files (page-12 examples, page-13 demonstrations, API security, reference data). They need the dev database on port 55433 | **Not run** in this audit |
| `Docs/output/**/build_*.py` | The one-off scripts that produced SKV4 → SKV8 and the companion reports | They are the **executable definition** of today's outputs. Use them as golden-test oracles, not as application code |

---

## 2. Assessment of Architecture V3

**Strengths.** V3 is detailed and was measured against the reference files. It covers:

- the four input roles and six file kinds;
- run modes, including a run with no song list and a run on top of a previous output;
- the identity model: works, recordings and many-to-many links;
- the link ladder M1–M6, with guards that hold money;
- the rule that a title never moves money without a person's decision;
- money kinds that are never added together;
- statement identity, re-issues and negative lines;
- versioned rule sets, maker-checker approval, builds fixed by their inputs;
- 25 invariants checked on every build;
- a full test plan.

**Fit to this brief.** V3 is the right technical foundation. Three things need adjusting:

1. **V3 is not designed around a simple interface.** §22 has 9 tabs (Files, New run, Validation, Review, Master,
   Findings, Approvals, Exports, Settings). The brief asks for 5 navigation items and a 6-step guided flow.
   *[R] Keep the V3 engine and put the §6 interface on top of it.*
2. **V3 conflicts with the reference companion workbooks** (Q1–Q4). The batch-4 workbooks:
   - add IPRS royalty and Spotify gross in a "Total (Both Sources)" column, which V3 §9.1 / I10 forbids;
   - use only the two Spotify sources;
   - take their population from a list that SVF reviewed by hand.

   V3's "paid but not in base" is computed from every source.
3. **V3's infrastructure is heavier than a first release needs.** It specifies SSO/OIDC, a separate audit
   database, a quarantine worker with no network, ClamAV, S3 Object Lock and row-level security.
   *[R] Release 1 keeps the existing single PostgreSQL and its hash-chained audit, local write-once storage and
   local accounts. It adds client grants, enforced in the API and by row-level security. The rest is listed under
   "Not implemented" in §10, with a path to add it.*

**Where V3 is right and the old outputs are wrong** (V3 Appendix C):

| Issue in today's outputs | Where | Status |
|---|---|---|
| The `(S-32)` statement belongs to member `8875288`, not SVF, yet its ₹53.47 is inside SKV8's total | SKV8 | [F] |
| The `TOTAL` row label says "3,149 song rows"; there are 3,144 data rows | SKV8 | [F] |
| 81 rows received platform money (₹8,25,822.62) through a title match | SKV8 | [V3] |
| 263 ISRCs sit under more than one work, and the first row wins | SKV7 / SKV8 | [V3] |

---

## 3. Assessment of the flowchart (approval draft v1.0)

The flowchart solves a **different but related** problem. It compares recording income with publishing income,
uses an optional 6% MRM benchmark, and ends in an IPRS clarification email and case tracking.

| Flowchart stage | Maps to | In this brief? |
|---|---|---|
| A Intake + income type, B Import controls (unusable file, repeat, required fields, reconcile to printed total, overlaps / restatements) | V3 S0–S3, §8, §9.5 | **Yes.** The two documents agree |
| C Work + recording identities (registers, approved link table, no title-only merge, decide every duplicate, totals preserved) | V3 §5–§6, I14–I15 | **Yes.** The two documents agree |
| D Like-for-like comparison, E Rule (6%), F Money / streams route, G Outcomes | — (V3 §1 puts this out of scope) | **No** |
| H Pack, approval, dispatch, cases | — | **No** (only the approval control carries over) |

Rules that both documents share, and that the platform will enforce:

- recording and publishing money are never added;
- blank, an explicit zero, a missing entry and a pending distribution are four different states;
- no invented balancing entry;
- a corrected statement supersedes the old one and is never added to it;
- every exception stays visible;
- the person who prepares something cannot approve it.

**Updated flowchart.** See §6.2. Flowchart stages A–C become the background checks of steps 3–5. Stages D–H stay
an optional later module (Q11).

---

## 4. Input workbooks

### 4.1 The two named examples (checked [F])

| | **S-1** M2506 Mechanical (MUSERK) | **S-16** P2555 Overseas — 026 CASH |
|---|---|---|
| Kind | A — standard, 12 columns, money in column L | B — overseas, 17 columns, usage split in J–P, money in column Q |
| Sheet | `overseasMemberDetail` (the name is misleading) | `MemberDetail` |
| Letterhead | `INTERNAL NO 5154290`, `IPI NAME NO 00871526032`, `SVF ENTERTAINMENT PRIVATE LIMITED`, `IPI BASE NO I-004791736-0` | same holder |
| Money-line rule | a line counts only when `SOURCE` is filled; the bare line after it is the block sub-total | `NAME` + `ROLE` + `ROYALTY AMT` are filled; `0.0` is a real line (4 of the 5 works are named with ₹0.00) |
| Lines / works | 1,686 money lines, all role `E`; 573 works | 5 works; work 15662148 has 2 SVF lines (COLL 8.33 % and 16.67 %) |
| Printed `TOTAL ROYALTIES` | ₹82,769.6412, in column L. The label is in column **H**, not A | ₹10.2588, in column Q. The label is in column **H** |
| Three-way check | lines = sub-totals = printed = 82,769.6412 ✔ | lines = printed = 10.2588 ✔ when column Q is used |
| Footers | `SUMMARY OF ROYALTY` by language (BENGALI appears twice: 59 and 5 works); a POOL/SOURCE table of 4 MUSERK quarters adding to the total | language table; POOL table: ON DEMAND 9.7756 + OTHERS 0.4832 |
| Traps | footer "NO. OF WORKS" = 2,059, not 573, so it is **not** a work count | the sub-total row's `OTHERS` cell shows **10.2588**, not 0.4832 (an IPRS quirk). Only column Q can be used for the sub-total check |
| Metadata from the file name | distribution `M2506`; category Mechanical (MUSERK); period "F.Y. 2025-26" → Apr 2025 – Mar 2026 | `P2555`; Overseas; society `026 CASH` → CASH (Hong Kong); period Apr 2024 – Mar 2025 |
| In SKV8 | band `MECHANICAL (MUSERK)`, column DK = ₹82,769.64 over 573 cells ✔ | band `OVERSEAS - CASH (HONG KONG)`, column EY = ₹10.26 ✔ |

### 4.2 The full reference set

| Location | Files | Kind | Facts |
|---|---|---|---|
| `input/batch-1` | 45 statements | 27 A + 18 B [F] | Σ printed totals = ₹32,09,945.73 = SKV4 [F]. `(S-32)` is member `8875288` [F]. Distribution numbers repeat across files (P2580 × 8 …) [V3] |
| `input/batch-1` | `(S-46)SVF list of Song -April 2026.xlsx` | C, song list | 2,762 rows · 1,037 works with more than one ISRC · 263 ISRCs under more than one work · 148 work numbers on more than one row [V3] |
| `input/batch-2` | `Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx` | A | ₹1,13,848.57 [V3]. **The file name carries no P-number**, so SKV8 prints "Not specified" [F] |
| `input/batch-3` | `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | D, platform revenue | 10,960 lines · ₹78,89,496.76 · **no currency column** [V3] |
| `input/batch-3` | `Spotify L6M.xlsx` | E, usage | 11,222 rows, Jan–Jun 2026 [V3] |
| `input/batch-4` | `Songs-Missing-From-SVF-List_Updated.xlsx` | SVF's reviewed findings | 93 songs. Column D holds **11 different free-text statuses**: "Not SVF work" 34 · "need to update ISRC" 19 · "already linked" 18 · "Need to update song in report" 13 · "Updated in SVF Report" 3 · 6 one-off texts [F] |

---

## 5. Output workbooks

### 5.1 Master — `SVF-RD-SKV8.xlsx` [F]

| Feature | Measured |
|---|---|
| Sheets | one sheet, named `SVF-RD-SKV8`; 3,156 rows × 225 columns (A:HQ) |
| Row 1 | 24 merged section bands, bold 12 pt, text colour `1F1F1F`, one fill per band. Each label states its distribution count, e.g. `YOUTUBE PRE-CLAIMS  (3 distributions)` |
| Row 2 | headers, grey `D9D9D9` for the identity and total columns, band colour elsewhere, centred and wrapped; height 30 |
| Identity + totals (A–E) | `ISRC` (` \| `-joined) · `Song Name` · `Internal No` · `Total Amount` · `Total Spotify Revenue (MRM)`. D and E are bold `#,##0.00`; rows alternate `F2F2F2` |
| Distribution blocks | `Date` (`DD-MMM-YYYY`) · `Amount` (`#,##0.00`) · `Period` · `Distribution Number`, repeated per distribution. Each band has a light tint |
| Section order | YouTube Pre · YouTube Post · Facebook/Meta · Spotify (IPRS) · Spotify gross (MRM, 6 month blocks) · Apple Music · Radio · Zee TV · Mechanical · Other · Redistribution · Overseas A→Z (APRA … SUISA) |
| Spacer | HF:HH are three empty columns before the total block |
| Total block (HI–HN) | `FY 2022-23` … `FY 2025-26` · `Period Not Stated` · `Total Revenue`, by the FY in which the money was **earned** |
| Audit block (HO–HQ) | `Catalogue Status` · `Royalty Booked On` · `Spotify (MRM) Match Basis` |
| TOTAL row | row 3148, grey; static **values** (the master holds no formulas). Each block shows its distribution number in bold; `TOTAL` sits in column B |
| Notes | FY-basis note at HI3149; provenance note at A3151; an empty merged row A3156:HQ3156 |
| Freeze, filter, widths | freeze `F3`; autofilter `A2:HQ3146`; widths A 34 · B 42 · C 13 · D 15 · E 21 · per block 13 / 12 / 26 / 15 |
| Sort | `Total Amount` descending, then platform total, then title |
| Totals | ₹33,23,794.31 society royalty; ₹78,89,496.76 Spotify gross; the FY buckets add to the society total |
| `Date` column | **the latest timestamp inside the xlsx ZIP**, i.e. when the file was saved, not a payment date (`build_rd_v4.py: stmt_date`) |

### 5.2 Missing Songs — `Missing-Songs-Revenue-From-IPRS-And-Spotify.xlsx` [F]

- One sheet, `Missing Songs Revenue`: 93 songs × 41 columns. Freeze `F3`, autofilter, notes in a merged row 98
  (height 118).
- Columns A–E: identity and two totals (`Total Royalty From IPRS`, `Total Revenue From Spotify (MRM)`).
- **Section A**: one IPRS block, from the Spotify IPRS statement only. Date blank, distribution "Not specified".
- **Section B**: 6 monthly Spotify gross blocks.
- **Total block**: `FY 2025-26 - IPRS Royalty` · `FY 2025-26 - Spotify Revenue` · **`Total (Both Sources)`**.
- **Audit block**: `Status Given In Source 1` · `Note From Source 1` (only when any note exists) ·
  `Present In The IPRS Statement` (tested by work number, then title, then title without the film name) ·
  `Spotify (MRM) Match Basis` · `In SVF Catalogue (S-46)?`.
- The TOTAL row uses `=SUM()` **formulas**.
- **Population** = every song on SVF's **hand-reviewed** list, including songs SVF marked "already linked" or
  "Updated in SVF Report". Those songs are not missing.
- **Sources** = the Spotify IPRS statement and the Spotify MRM report only. The other 45 statements are not used.

### 5.3 Non-SVF — `Non-SVF-Works-Revenue-From-IPRS-And-Spotify.xlsx` [F]

- Same layout, sheet `Non-SVF Works Revenue`: 34 songs × 40 columns. There is no Note column, because none of these
  songs has a note.
- **Population = the rows where SVF wrote "Not SVF work".** It is a person's decision. No algorithm produced it.

---

## 6. Proposed simple workflow

### 6.1 Screens

Navigation: **Home · Process Files · Past Reports · Clients · Settings.** Admin diagnostics sit inside Settings.

| Step | What the user sees | What the backend does |
|---|---|---|
| 1 Select client | one drop-down, preselected when the user has a single client | checks the client grant on the server |
| 2 Upload files | drag and drop; each card shows the name, the detected type ("Royalty statement — Mechanical, M2506, FY 2025-26") and a status. One question only when needed ("What type of file is this?", "Which period does this statement cover?") | S0 safety checks, sha256, write-once original; S1 kind detection; S2 extraction; metadata from the file name, then the content, then a person, with the source of each field kept |
| 3 Check files | "12 uploaded · 10 ready · 2 need attention"; statuses **Ready / Needs Review / Unsupported / Error**; plain-language reasons; "More details" on request | S3 checks: three-way and footer reconciliation, holder in scope, duplicate or re-issue, missing metadata. A failed file is set aside without blocking the others |
| 4 Process | one button; real stage progress (Checking statements · Extracting royalty entries · Checking financial totals · Matching song records · Preparing reports); safe to leave the page | job queue in PostgreSQL; S4–S9 build; invariants I1–I25; any failure fails the build |
| 5 Review results | summary computed from this run; a numbered list "Needs your review", with money problems kept apart from matching problems; one card per issue, with only the valid actions (Confirm match · Keep separate · Review later · Mark "Not ours" …) | findings, proposals and holds; decisions keyed by code, carried into later runs; maker-checker |
| 6 Download | three cards (**Master Royalty Report · Missing Songs · Non-SVF / Out-of-scope**), each with its own state: Validated · Waiting for approval · Published · Held · Failed. Optional "Download all" | S10 publish (approval by a second person); S11 export; the download re-checks permission; published outputs never change, and a re-run creates the next version |

### 6.2 Updated flowchart (text form; drawn in Phase 13)

```
SELECT CLIENT -> UPLOAD -> [auto] safety, type, metadata, extract
   -> CHECK FILES: reconcile? holder in scope? duplicate / re-issue? metadata complete?
        no  -> file set aside, plain-language fix shown (others continue)
        yes -> PROCESS: identities (code links, guards, holds), place money (book-once),
                 FY totals, findings, invariants
                 invariant fails -> run FAILED, nothing downloadable, reason shown
   -> REVIEW: matching proposals / held money / missing-song statuses (Not ours, Confirmed missing ...)
        decisions that move money -> second-person approval -> rebuild
   -> DOWNLOAD: Master (SKV layout) + Missing Songs + Non-SVF, each validated -> approved -> published
(Optional later module: flowchart D-H comparison, 6% benchmark, IPRS enquiry pack)
```

---

## 7. Proposed backend architecture

The repository's stack stays. V3's engine is built inside it, in modules that can each be tested alone:

```
backend/mrm/
  clients/       client config: holders (member, IPI), catalogue versions, rules, naming, grants
  ingest/        safety (existing), reader (existing), detect (V3 §2.4), filename grammar, metadata resolver
  parsers/       iprs_standard (kind A, existing + footers), iprs_overseas (kind B, new), song_list (C),
                 platform_revenue (D), platform_usage (E), previous_output (F, legacy SKV + _rd_meta)
  reconcile/     three-way + footer checks, statement identity, duplicates / re-issues, scope check
  identity/      works, recordings, links, link ladder M1-M6, guards G1-G6, proposals and scores
  classify/      missing-song statuses, out-of-scope (Not ours), carried finding statuses
  review/        decisions (maker / checker), undo, finding status history
  build/         run manifest, money placement (book-once), FY views, penny_fix, invariants I1-I25
  outputs/       skv_master writer, missing_songs writer, non_client writer, cover + _rd_meta, verifier
  jobs/          PostgreSQL job table (SKIP LOCKED), progress stages, sweeper
  api/           thin routes: one module per screen; every route checks the client grant
```

**Data model.** V3 §16, adapted to the existing schema (`client` = workspace). A new migration `0003` adds:

| Group | Tables |
|---|---|
| Clients | `client_party` (rights holders), `client_grant` (user × client × role), `catalogue_version` |
| Sources | `statement`, `royalty_line`, `statement_footer`, `platform_report`, `platform_line`, `song_list_entry` (+ work, ISRC children), `prior_output` / `prior_row` / `prior_cell` |
| Identity | `work`, `recording`, `work_recording_link` |
| Review | `decision`, `finding_status` |
| Builds | `rule_set`, `series`, `build`, `song_row`, `cell` (long format), `row_fy`, `hold`, `finding`, `proposal`, `export_artifact`, `job` |

Every table carries `client_id` and has a row-level-security policy.

**Processing contract.** A build is fixed by five things: input fingerprints, base fingerprints, the approved
decisions, the rule-set version and the software version. The same five inputs always give byte-identical exports.
Every money cell records its source file, line, rung and decision.

---

## 8. Business-rule gaps found

| # | Gap | Why it matters |
|---|---|---|
| G1 | The reference companion reports add society royalty and platform gross ("Total (Both Sources)"). V3, the flowchart and the brief all forbid this | it changes a headline figure |
| G2 | The Missing Songs population was produced once by scripts over the Spotify sources, then reviewed by hand. There is no approved rule for which sources count | it decides which songs appear |
| G3 | "Non-SVF" exists only as SVF's hand-written status. There is no approved rule and no evidence standard | it decides client scope |
| G4 | 11 free-text statuses need a fixed vocabulary before decisions can be carried into later runs | it decides classification |
| G5 | SKV8 placed ₹8,25,822.62 of platform gross through title matches and gave shared ISRCs to the first row. Under V3 that money waits for a decision | the master will not equal SKV8 until it is reviewed |
| G6 | `(S-32)` ₹53.47 belongs to another member | holder scope |
| G7 | The statement `Date` is the file's save time. No payment date is supplied | Received-in-FY view; dates shown in the report |
| G8 | Currency and gross / net basis of the Spotify MRM report are not stated | money kind |
| G9 | Who approves, and what happens when only one person is available | publishing |
| G10 | The Spotify IPRS statement has no distribution number in its name or content | metadata; the user is asked once |

---

## 9. Questions that need approval

**Must answer before the related code is finalised** (they change money or classification):

| # | Question | Options | Recommendation |
|---|---|---|---|
| **Q1** | Companion reports: what replaces the "Total (Both Sources)" column? | (a) remove it; IPRS royalty and Spotify gross stay in separate columns · (b) keep it, labelled "not a royalty — for reference" · (c) replace it with a ratio column | **(a)** |
| **Q2** | Missing Songs: which sources count? | (a) every money source in the run (all statements and platform reports) checked against the song list · (b) Spotify sources only, as in the reference | **(a)**, with the source of each amount shown |
| **Q3** | Missing Songs: which rows appear? | (a) every song flagged as paid-but-not-in-list, with its review status column (as the reference does) · (b) only songs still unresolved or confirmed missing | **(a)**, sorted with unresolved songs first |
| **Q4** | Non-SVF: what puts a song on this report? | (a) only a reviewer's "Not ours" decision on that song's ISRC / work number. The system may *suggest* (e.g. registered to another member), never decide · (b) an automatic rule (please define it) | **(a)** |
| **Q5** | Approve this status mapping? | "Not SVF work" → **Not ours** · "already linked", "Updated in SVF Report" → **Already in list** · "need to update ISRC", "… ISRC to update", "Need to update song in report" → **In list – identifier to update** · "Need to register", "Need Hangover Songs", "Ask for all … songs" → **Confirmed missing** · "Please confirm if …" → **Needs check** | approve, with SVF's original text kept beside each status |
| **Q6** | Title-placed platform money (81 rows) and shared ISRCs: apply the V3 rule? | (a) V3: shown as "awaiting confirmation" until a reviewer confirms; the master differs from SKV8 until then · (b) reproduce SKV8 behaviour | **(a)**. A one-off v0→v1 difference report will show every change for sign-off |
| **Q7** | `(S-32)`, member 8875288, ₹53.47 | (a) exclude from SVF's run, with a notice · (b) include | **(a)** |
| **Q8** | Spotify MRM report: currency and basis? | INR + GROSS? | confirm |

**Defaults that will be applied unless you object:**

| # | Default |
|---|---|
| Q9 | Statement `Date` = the date entered at upload or read from the file. When neither exists, the file's save time, marked "estimated". The FY headline stays "earned in FY", as in SKV8 |
| Q10 | Two-person rule: Swatantra prepares, Sherley (or a named approver) approves money-moving decisions and the final publish. Admins cannot self-approve |
| Q11 | Flowchart D–H (6% comparison, enquiry packs, cases) is removed from the main navigation and kept as an optional later module. Its code is not deleted |
| Q12 | The song list is stored as the client's catalogue version and reused until a new list is uploaded |
| Q13 | The repository copies of SKV8 and the Non-SVF workbook are the "(1)" files named in the brief. Send the "(1)" files if they differ |
| Q14 | Reconciliation tolerance ₹0.05 per file (V3). All reference statements pass within this |
| Q15 | Release 1 security: local accounts plus client grants, enforced in the API and by row-level security; hash-chained audit in the same database. SSO, a separate audit database, ClamAV and object lock come later |

---

## 10. Phased implementation plan

| Phase | Work | Proof that it is done |
|---|---|---|
| 1–3 | Audit, alignment, questions | **this document** |
| 4 | Migration `0003`: client grants, statements, lines, identity, builds, long-format cells, jobs, row-level security; processing contracts | migration tests; a cross-client read is refused |
| 5 | Parsers: kind A + footers, **kind B (new)**, file-name grammar, song list, platform revenue / usage, legacy SKV reader | S-1 = ₹82,769.6412 and S-16 = ₹10.2588 three-way; **45 / 45** statements reconcile; metadata parses on every reference name; zero, blank and negative fixtures |
| 6 | Reconciliation, statement identity, duplicates / re-issues, holder scope; identity engine M1–M6, guards, holds, proposals | `(S-32)` excluded (−₹53.47); repeat upload ignored; re-issue held; NOT_SAME blocks a later join |
| 7 | Build engine + SKV master writer (dynamic bands, measured formats) | golden tests against the old scripts (rule set v0) for SKV4 → SKV8 rows and totals; v0 → v1 difference report; I1–I25 |
| 8 | Missing Songs + Non-SVF writers (per Q1–Q5); independent re-derivation | the 93 / 34 reference populations reproduced from SVF's statuses; totals re-derived by a second method |
| 9 | Client management backend: holders, catalogue versions, grants, naming | test G (two clients, no mixing) |
| 10 | New frontend: 5 navigation items, 6-step guided flow, review cards, three downloads, first-use guide | UI tests A–H run against the real backend |
| 11 | Integration: jobs, progress, approval, publish, versioned downloads | end-to-end run on the reference set |
| 12 | End-to-end validation of every output against the references (values and structure) | comparison report |
| 13 | Documentation: architecture, flowchart, setup, deployment, known limitations, open decisions | docs in `Docs/` |

**Status today:** every feature in the new scope is **Not implemented**. The reused parts (safety checks, reader,
kind-A parser, sessions, audit chain) are **implemented in the existing code**. Their tests were **not run** in this
audit.
