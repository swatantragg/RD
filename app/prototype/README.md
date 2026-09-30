# Sangam — IPRS Royalty Intelligence Platform (prototype)

**Sangam** (संगम, *confluence*) is where SVF Entertainment's three money streams meet: the IPRS
distribution statements, the SVF song catalogue, and Spotify's own revenue and usage reports.
They flow into one reconciled matrix, and every rupee in it can be traced back to the file that paid it.

This folder is a working prototype of
[`Docs/SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V2.md`](../../Docs/SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V2.md).
It covers every workflow in the architecture: ingest, the SKV matrix, the Coverage Audit, the Merge
Review, the Song-ID-Mismatch report, the gap lists, and the Excel exports. It runs on the real April-2026
inputs in `Docs/input` and reproduces the architecture's reference numbers. Where a published number
differs, the reason is shown next to it.

## Run it

```bash
cd app/prototype
./run.sh --demo        # first run: sets up backend/.venv and frontend/dist, loads the reference run, serves the app
./run.sh               # later runs: serve the existing database
./run.sh --demo --fresh  # wipe the database and load the reference run again
```

Open <http://127.0.0.1:8765>. The REST API docs are at `/docs`. You need Python 3.12 and Node 18 or newer (the
UI is built once, on the first run). You can also click **Load the April-2026 reference run** in the UI: it loads
the same data without the command line.

Development mode, with hot reload on both sides:

```bash
cd backend && .venv/bin/uvicorn sangam.api.app:app --reload --port 8765
cd frontend && npm run dev            # http://localhost:5173, proxies /api to :8765
```

Command line:

```bash
cd backend
.venv/bin/python -m sangam.cli demo [--fresh]   # ingest -> extract -> build -> coverage x2 -> mismatch -> 5 merges -> all exports
.venv/bin/python -m sangam.cli verify           # prints the §20 invariants and the Appendix C comparison
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q   # 57 tests, about 40 s
```

## What is in the box

| Architecture | Where | UI tab |
|---|---|---|
| §5 shape detection (TYPE A–F), §6 filename grammar | `domain/sniff.py`, `domain/filename.py` | Batches & Upload |
| §5.6 TYPE F auto-mapping, confirmed map reused by header fingerprint | `domain/sniff.py`, `ingest/sheets.py` | My Sheets |
| §9 S2 extraction: SOURCE-line rule, hard stop at TOTAL ROYALTIES, three-way reconciliation | `ingest/statement.py` | Validation |
| §7 normalisation, `penny_fix`, Indian FY | `domain/normalize.py` | — |
| §8 link ladder (L3 needs a title unique on both sides) | `domain/link.py` | — |
| §9 S5–S8: row universe, book-once, ISRC-first B1–B7 cascade, FY split, 8-value status | `build/` | RD Viewer (SKV) |
| §10 the 225-column SKV workbook, SKV colour system | `export/skv.py`, `export/style.py` | Exports |
| §11 Coverage Audit: E1–E4, STRICT/RESOLVED, evidence flag, accuracy contract | `coverage/engine.py` | Coverage Audit |
| §12 merge candidates, confidence signals, decisions, apply into a new build, undo | `merge/` | Merge Review |
| §13 Song-ID-Mismatch rules A/B/C with wildcards, V1 and V2 | `mismatch/engine.py` | Mismatch Report |
| §14 statement register and gap lists | `export/reports.py` | Statements & Gaps |
| §15–16 relational schema: pipe-joined lists live only in exports | `core/schema.sql` | — |
| §17 REST API and background jobs | `api/`, `core/jobs.py` | job tray |
| §20 invariants I1–I25 | asserted in every build, coverage run, merge apply and export | every tab |

## Verified against the architecture (Appendix C)

`sangam.cli verify` and the test suite check these figures on every run.

| Figure | Architecture | Prototype |
|---|---|---|
| Statements (standard + overseas), reconciled | 46 (28 + 18), 46/46 | **same** |
| Royalty distributed (col D) | 3,323,794.31 | **same** |
| Catalogue rows · internal nos · ISRCs · name keys | 2,762 · 2,571 · 4,278 · 2,570 | **same** |
| IPRS Spotify Oct'25–Mar'26 | 113,848.57 over 1,379 works | **same** |
| Spotify MRM lines · ISRCs · gross (col E) | 10,960 · 1,759 · 7,889,496.76 | **same** |
| Status: received · paid-not-in-list · 0.00 in list · 0.00 not in list | 1,795 · 318 · 18 · 13 | **same** |
| Merge apply | 5 rows folded, every total unchanged, 2,902 → 2,902 internal nos | **same**; the five merged rows' ISRC and internal-no strings match §10.3 character for character |
| Coverage, RESOLVED | 93 songs (13 · 71 · 9) · 250,956.32 at stake · 1,140.08 received · 18 name-present | **same** (reference title-link rule); the finding list matches the delivered workbook cell for cell |
| Coverage, STRICT · exclusion rungs | 36 works + 129 ISRCs · E1 1,343 · E2 1,630 · E3 14 · E4 48 | **same** |
| Mismatch V2 totals | 61,206.05 · 3,722,218.78 · 3,783,424.83 | **same** |
| SKV8 workbook | 3,144 × 225 | 225/225 headers identical; of 3,101 rows matched one-to-one, col D is identical on 3,059 and col E on 3,095 |

All invariants pass: 11/11 on the base build, 14/14 on the merged build, 7/7 per coverage run and 4/4 per mismatch run.
Exports are deterministic: the same build gives a byte-identical `.xlsx`, and uploading the inputs in a different
order gives the same SKV workbook, byte for byte.

## Where the prototype and the architecture disagree

Building this surfaced several points where the V2 text, its published numbers and the delivered workbooks disagree.
Each one was traced to its cause.

1. **L3 uniqueness (§8, §11.2) vs the published 93.** The text says a title link must be unique on *both*
   sides. The reference scripts did not check this: E3 accepted any linked ISRC, and E4 checked only the statement
   side. The Coverage Audit therefore offers two title-link rules. The *V2 rule* (the default) returns 127 songs. The
   *reference run* rule returns exactly 93. The spec's reference numbers should be re-measured, or the rule
   relaxed, so that the two agree.
2. **The delivered Song-ID-Mismatch report has 3 junk rows.** Its parser read the statement's footer (the
   *SUMMARY OF ROYALTY* language table) as works, which produced internal numbers such as `BENGALI` and `SANSKRIT`
   with names `1.0` and `54.0`. The prototype gives 778 rows: 781 minus those 3. Every revenue total still matches. This
   is worth adding to the §23 defect log as D8.
3. **Book-once owner (§9 S6a).** SKV7 booked a shared work on the *first* catalogue entry. V2 books it on the entry
   whose name matches the statement title, so `BOJHENA SHEY BOJHENA (FEMALE VERSION)` now lands on the Female Version.
   SKV7 also labelled 2 never-paid shared works as siblings. That is why the prototype has 165 siblings instead of 168.
4. **376 ISRCs are listed under more than one catalogue entry**, and 31 of them earn revenue. For example,
   `INS231421096` appears under five songs, including the unrelated *Mon Bojhe Naa*. The prototype breaks the tie
   with the same exact-name, then version-stripped, rule and writes a note on the row. The catalogue should be
   cleaned at source.
5. **B6 (version-stripped name) moves money.** This contradicts L5, which says such a match "never moves money on its
   own". B6 is therefore opt-in per build; the default is B4 + B5, both stamped. When B6 is off, an ISRC that only a
   version-stripped name would attach gets its own row, and the Merge Review proposes the pairing.
6. **Row universe.** §9 S5 counts "372 statement-only works". That figure is really 331 statement works plus 41
   Spotify-only rows that SKV6 appended by name. The clean-room build has 2,762 + 331 + 47 revenue-only + 12
   usage-only = 3,152 rows. §9 S7 also prints 780 where SKV7 actually has 781.
7. **Month rounding.** Two MRM month totals differ by one paisa (Oct 2025 and Dec 2025). The prototype applies §7's
   `penny_fix`, which gives the paisa to the month that gained the most in rounding. The delivered workbook gave it to the
   largest month. The grand total is identical.
8. **225 columns** includes three blank spacer columns (214–216) that SKV5–SKV8 carry. They are kept so that column
   letters, such as HO for Catalogue Status, stay the same.

## Prototype choices (the production stack is in §17 and §22)

| Production (V2) | Prototype | Why it is safe to swap back |
|---|---|---|
| PostgreSQL 16, `NUMERIC(18,6)` | SQLite, money as IEEE double, which round-trips Python floats exactly; every rounding goes through `penny_fix` | the schema mirrors §15, and the SQL is plain |
| Celery + Redis workers | in-process thread pool with the same job contract (`queued/running/succeeded/failed`, progress, log) | job functions take `(ctx, conn)` and are idempotent |
| S3 / MinIO | `data/storage/<sha256>` and `data/exports/` | files are keyed by sha256 |
| OIDC + RBAC | `X-User` / `X-Role` headers; the role switch is top right; only analyst and admin may decide or apply merges | enforced on the server (403) |
| Tailwind + shadcn/ui, TanStack Table | hand-written CSS tokens (light and dark), a 2-D virtualised grid on `@tanstack/react-virtual` | React 18 + TS + Vite + TanStack Query + Recharts as specified |

## Layout

```
app/prototype/
  run.sh                   launcher
  backend/
    sangam/
      domain/              normalize, filename, sniff, link        (§5-§8)
      ingest/              reader, statement, sheets, platform, pipeline (S0-S4)
      build/               model, universe, mrm, derive, engine     (S5-S8)
      coverage/            engine                                    (§11)
      merge/               candidates, apply                         (§12)
      mismatch/            engine                                    (§13)
      export/              style, writer, skv, coverage_xlsx, reports, service (§14, §19)
      api/                 FastAPI app + routes                      (§17.3)
      core/                config, db, schema.sql, jobs
      reference.py         Appendix C comparison
      cli.py               demo / verify / serve
    tests/                 unit, fixtures, golden reference run, merge reversibility, API, determinism
  frontend/src/            React UI: 10 tabs, job tray, charts, virtualised matrix
  data/                    runtime: sangam.db, uploads, exports (git-ignored)
```

Configuration comes from environment variables: `SANGAM_DATA_DIR`, `SANGAM_REFERENCE_INPUT`, `MAX_UPLOAD_MB` (64),
`RECON_TOLERANCE` (0.05), `MERGE_SUGGEST_THRESHOLD` (0.70), `MERGE_REVIEW_THRESHOLD` (0.40) and `SANGAM_JOB_WORKERS` (2).
