# Royalty Reports

Turns royalty statements (IPRS, standard and overseas layouts), platform reports (Spotify revenue and usage), a
client's song list and the previous master report into three checked workbooks:

1. **Master royalty report**: the `SVF-RD-SKV8` layout, numbered per client (`SVF-RD-SKV9`, `SVF-RD-SKV10` …).
2. **Missing Songs**: songs that earned money but whose ISRC and work number are not in the song list, with their
   review status.
3. **Out-of-scope (Non-SVF) works**: songs a reviewer marked as not belonging to the client.

The user selects a client, uploads files, answers questions only when needed, processes, reviews and downloads. An
approver (a different person) publishes.

- Every statement total is checked.
- Money moves only through codes; a title only proposes.
- Society royalty and platform revenue are kept apart.
- Published reports never change.

Documentation:

- [Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md): architecture, updated flowchart, rules, validation
  against the reference workbooks, feature status, known limitations, open decisions, deployment, backup.
- [Docs/PHASE-1-AUDIT-AND-PLAN.md](Docs/PHASE-1-AUDIT-AND-PLAN.md): the audit and the business questions.
- [Docs/SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V3.md](Docs/SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V3.md):
  the technical foundation.

## Run it

```bash
cp .env.example .env            # set real passwords and SECRET_KEY before any shared use
docker compose up -d --build    # db, bootstrap (migrations + seed), api, worker, web
open http://localhost:8080
```

### Accounts

There are no demo accounts or sample data: everything works on real files and real people.

- **Create account** on the sign-in page:
  - the **first** account on an installation becomes the **Administrator**, who may also prepare reports;
  - every later account is a **Viewer**: it follows everyone's work and downloads **published** reports.
- An administrator gives more rights in **Settings → People and access**.
- Publishing needs an **Approver** who is a different person from the one who prepared the report.
- Downloads are saved with the person's name, e.g. `SVF-RD-SKV9_Ravi-Menon.xlsx`.
- To allow only accounts made by an administrator, set `ALLOW_SIGNUP=false` and create people with:

  ```bash
  docker compose run --rm api python -m mrm.cli create-user name@company.com "Name" importer 'long-password' --clients SVF
  ```

| Role | Can |
|---|---|
| Administrator (`admin`) | clients (add, change, switch off), people and roles; technical details; may prepare |
| Preparer (`importer`) / Reviewer (`rights_reviewer`) | add clients; upload, process, review and send for approval for their clients |
| Approver (`approver`) | approve changes that move money; approve and publish reports |
| Viewer (`viewer`) | see every client's runs and results; download published reports |

Upgrading from 1.0.0 switches off the six demo accounts (`*@mrm.local`). To remove them for good, keeping one real
account with every role (work done with the demo login is moved to it, and the earlier comparison module's demo data is
removed):

```bash
docker compose run --rm api python -m mrm.cli purge-demo --keep you@company.com
```

Click your **initials** (top right) for your profile, role, the **Light / Dark** theme and sign out; **Settings → My
profile** changes your name or password. After each update a one-time **What's new** note sums up the changes (once per
person, on any browser). The version is shown in the footer (**V1.0.4**).

**Clients:** SVF is set up already. Preparers and administrators add more under **Clients → Add a client** (or **Add a
new client** in step 1 of a run): a short code (used in report names, e.g. `ACME-RD-SKV1`), the name and the rights
holders (society member numbers) whose statements belong to the client. **Edit** on a client opens the same pop-up
with all its details; any row can be removed with ×. The person who adds a client can work on it straight away;
switching a client off is for administrators.

**Starting again:** a run that was never published can be deleted with its draft reports (**Past Reports → Delete**,
or **Delete run** on the run page). Upload the same files to a new run: the stored copies are reused, so nothing is
counted twice, and review decisions stay with the client. Published reports are never deleted; a run that is
processing or waiting for approval must finish or be returned first. A deleted run is only hidden: its history stays
in the database and the audit log.

**People** (Settings → People and access): **Add a person** and **Edit** open a pop-up for role and client access. An
account with no recorded work can be **deleted**; anyone who uploaded, prepared, approved or decided something can only
be switched off, so every report stays traceable. Before any shared use, follow the production checklist and the backup
procedure in the system guide (§13–14).

## Screens

| Menu | What it is for |
|---|---|
| Home | What to do next, recent runs and their status, items waiting for you, published reports |
| Process Files | The guided run: 1 Select client · 2 Upload files · 3 Check files · 4 Process data · 5 Review results · 6 Download reports |
| Past Reports | Every published version, with its three downloads; drafts for preparers and approvers; delete a never-published run |
| Clients | Rights holders, report naming, platform-report distributors; add a client (administrator) |
| Settings | Approvals · People and access · Technical details (administrators, approvers) · Help |

## Develop and test

```bash
docker run -d --name mrm-devdb -e POSTGRES_PASSWORD=devroot -e POSTGRES_DB=mrm \
  -e MRM_OWNER_PASSWORD=devpass -e MRM_APP_PASSWORD=devpass -p 127.0.0.1:55433:5432 \
  -v $PWD/deploy/postgres/init.sh:/docker-entrypoint-initdb.d/10-init.sh:ro postgres:16-alpine

cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m mrm.cli bootstrap            # migrations and client SVF (no demo data)
.venv/bin/uvicorn mrm.api.app:app --port 8010     # API with an in-process worker thread
.venv/bin/python -m pytest                        # 85 tests, on a throw-away database

cd ../frontend && npm install && API_URL=http://127.0.0.1:8010 npm run dev    # UI on :5173
```

Main tests:

| File | Covers |
|---|---|
| `tests/test_50_rd_parsing.py` | S-1 and S-16 in detail; all 45 statements reconcile; file-name metadata; file kinds; blank, zero and negative amounts; review-status vocabulary; edited previous reports |
| `tests/test_60_rd_reports.py` | Book-once; held shared recordings; title proposals and decisions; already-in-previous-report; FY split; rounding; money kinds kept apart; master vs SKV8 (structure and per-distribution totals); Non-SVF vs reference (34/34); Missing Songs rule; byte-identical exports; Excel review round trip |
| `tests/test_96_release_104.py` | Deleting a never-published run (preparers only, once); same title and same file in a new run; refused while waiting for approval and after publication |
| `tests/test_95_release_103.py` | Deleting people only without recorded work (admin only, never yourself); new password typed twice; `purge-demo` moves work, deletes demo accounts, keeps the audit chain intact |
| `tests/test_90_release_102.py` | Adding clients (preparers; duplicates refused; switching off is admin-only); the one-time What's new note; My profile (name, password); backend, frontend and release-note versions agree |
| `tests/test_80_accounts.py` | Sign-up rules and the on/off switch; first account administers, later accounts view; viewer downloads only published files, named with their name; old demo accounts cannot sign in |
| `tests/test_70_rd_workflow.py` | The whole workflow over HTTP: upload → check → process → review → submit → approve by another person → publish SKV9 → SKV10; same distribution twice; unreadable and unknown files; client isolation (API and row-level security); download authorisation; decisions carried into the next run |

## Layout

```
backend/mrm/rd/          the royalty platform: rules, names, parsers, detect, engine, verify, excel,
                         store, service, jobs, access
backend/mrm/api/         routes_auth (sign-in), routes_rd (the platform); routes_admin / intake / identity / results
                         = the earlier comparison module, mounted at /api/compare only when LEGACY_COMPARISON=true
backend/mrm/migrations/  0001-0002 (earlier module, audit chain), 0003_rd_platform (this platform), 0004_profile,
                         0005_run_delete
backend/mrm/releases.py  release notes shown once after each update (add an entry with every version change)
frontend/src/            Home, Process (guided run), Results (process / review / download), Past Reports,
                         Clients, Settings
frontend/legacy-src/     screens of the earlier comparison module (not built)
```

## The earlier comparison module

The flowchart's stages D–H (recording vs publishing comparison, 6% MRM benchmark, IPRS enquiry packs and cases) were
built before this platform. Its code and tests are kept:

- the API is switched off by default (`LEGACY_COMPARISON=false`);
- its screens are outside the build (`frontend/legacy-src/`).
