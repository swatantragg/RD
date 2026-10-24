# Royalty Reports: Architecture

This document describes the system **as built, at version 1.4.4** (19 October 2026). Everything in it was taken from
the code in this repository. Where the older design documents in [Docs/](Docs/) disagree with the code, the code
wins; §24 lists the drift that is known.

**1.1.0 added the MRM royalty reconciliation platform** (catalogue, statement library, master view, reconciliation
against IPRS with the reference benchmark, enquiries and follow-up) and replaced the five old roles with exactly three:
Super Admin, Admin and User. §26 describes the new modules; §6.1–6.2, §7, §17–§19, §21.3 and §24 were updated.
**1.2.0** (no migration) is described in §27: the client chosen on each work page, the per-platform benchmark, the
master sheet on screen and wide-table scrolling. **1.3.0** (migration 0009) is described in §28: the side of a
statement is who sent it, every category is a platform, yearly reconciliation with the year before, and the
`clear-statements` maintenance command. **1.4.0** (no migration, §29): the reconciliation in the master layout, period by
period, and the brand colours and logo.

| If you need… | Read |
|---|---|
| To run it | [README.md](README.md) |
| Why it was designed this way (target architecture, the invariants) | [Docs/SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V3.md](Docs/SVF-Entertainment--IPRS-Royalty-Platform--ARCHITECTURE-V3.md) |
| The business rules, validation against the reference workbooks, limitations | [Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md) |
| The original audit and the business questions | [Docs/PHASE-1-AUDIT-AND-PLAN.md](Docs/PHASE-1-AUDIT-AND-PLAN.md) |
| How it works inside, module by module | this document |

---

## Contents

1. [What the system does](#1-what-the-system-does)
2. [Principles the code enforces](#2-principles-the-code-enforces)
3. [Runtime topology](#3-runtime-topology)
4. [Codebase map](#4-codebase-map)
5. [Request lifecycle](#5-request-lifecycle)
6. [Security architecture](#6-security-architecture)
7. [Data model](#7-data-model)
8. [File intake](#8-file-intake)
9. [Run-level checks](#9-run-level-checks)
10. [Processing pipeline](#10-processing-pipeline)
11. [The build engine](#11-the-build-engine)
12. [Independent verification](#12-independent-verification)
13. [Review and decisions](#13-review-and-decisions)
14. [Publishing](#14-publishing)
15. [Report outputs](#15-report-outputs)
16. [Background jobs and concurrency](#16-background-jobs-and-concurrency)
17. [Audit log](#17-audit-log)
18. [Frontend](#18-frontend)
19. [HTTP API reference](#19-http-api-reference)
20. [Configuration reference](#20-configuration-reference)
21. [Build, deploy and operate](#21-build-deploy-and-operate)
22. [Rule set and versioning](#22-rule-set-and-versioning)
23. [Extension guide](#23-extension-guide)
24. [Known limitations, technical debt and doc drift](#24-known-limitations-technical-debt-and-doc-drift)
25. [Glossary](#25-glossary)
26. [Reconciliation platform (1.1.0)](#26-reconciliation-platform-110)
27. [Version 1.2.0](#27-version-120)
28. [Version 1.3.0: statement sides, yearly reconciliation](#28-version-130-statement-sides-yearly-reconciliation)
29. [Version 1.4.0: reconciliation in the master layout, brand](#29-version-140-reconciliation-in-the-master-layout-brand)

---

## 1. What the system does

Royalty Reports is a web application for a music publisher/label (first client: **SVF Entertainment**, IPRS member
`5154290`). It takes in:

| Input file kind (`model.py`) | Example | Carries money? |
|---|---|---|
| `STATEMENT`: royalty statement, IPRS standard (12-column) or overseas (17-column) layout | `(S-13)Royalty Distribution - P2550 YouTube Pre Claims - July 2025 to September 2025 …xlsx` | Yes, society royalty, per **work** (IPRS work number) |
| `PLATFORM_REVENUE`: platform revenue report | `Raw_Spotify_MRM_Oct25_Mar26.xlsx` | Yes, platform revenue, per **recording** (ISRC) and month |
| `PLATFORM_USAGE`: platform usage report | plays/streams per ISRC | No (plays only) |
| `SONG_LIST`: the client's catalogue | `(S-46)SVF list of Song -April 2026.xlsx` | No (the base) |
| `REVIEW_LIST`: a song list with a review-status column | the client's reviewed Missing Songs list | No (review decisions) |
| `PREVIOUS_OUTPUT`: the previous master report | `SVF-RD-SKV8.xlsx` | Carried forward unchanged (the base) |

It produces three workbooks per published version:

1. **Master royalty report** (`SVF-RD-SKV9`, `SVF-RD-SKV10`, …): one row per song, one 4-column block (Date ·
   Amount · Period · Distribution Number) per distribution, grouped in coloured section bands. A financial-year block
   and an audit/traceability block follow.
2. **Missing Songs** (`Missing-Songs-Revenue-<generation>.xlsx`): songs that earned money but whose codes are not in
   the base, with their review status.
3. **Out-of-scope works** (`Non-<CODE>-Works-Revenue-<generation>.xlsx`): songs a reviewer marked "Not ours".

The user works through a guided run of six steps: **Select client → Upload files → Check files → Process data →
Review results → Download reports** (preview and publish happen in the last step). Since 1.0.5 there is no approval
step: the preparer publishes.

---

## 2. Principles the code enforces

These rules hold everywhere. Most are enforced in more than one layer.

| Principle | Where it is enforced |
|---|---|
| **Money is exact.** `Decimal` from cell to workbook; floats are converted through `repr`, never through binary arithmetic. JSON carries money as decimal text. | [normalize.py](backend/mrm/normalize.py) `amount()`, [parsing/reader.py](backend/mrm/parsing/reader.py) `_cell()`, [db.py](backend/mrm/db.py) `_json_default`, [api/deps.py](backend/mrm/api/deps.py) `J` |
| **Missing data is not zero.** A blank amount is `None`/`NULL`; only a written 0 is zero. | `normalize.amount`, `rd_platform_line.amount NULL`, `BLANK_AMOUNTS` warnings |
| **Money moves only through codes.** A statement line lands on its work number, a platform line on its ISRC. A title match only *proposes*; a person must confirm it (`LINK` decision). | [rd/engine.py](backend/mrm/rd/engine.py) steps 5–6, `rules.name_link_policy = "suggest"` |
| **Book once.** A work claimed by several base rows is booked on one owner row; the others show 0.00 and say where the money went. | `engine._owner`, sibling cells, "Royalty Booked On" column |
| **Hold, don't guess.** No work number, no ISRC, or a recording claimed by two different songs: the money goes on its own *held* row, counted in every total, until someone decides. | `hold:*` rows in `engine` |
| **Society royalty and platform revenue are never added together** in the master. | Separate `Total Amount` and `Total <Platform> Revenue` columns; `engine._totals` |
| **Every statement total is checked.** Lines = sub-totals = printed `TOTAL ROYALTIES`, within ₹0.05. | [rd/detect.py](backend/mrm/rd/detect.py) `_eval_statement`, engine check `I1` |
| **Two independent computations.** The engine groups and places; `verify.py` re-walks every source line. Any number only one method produces fails the build. | [rd/verify.py](backend/mrm/rd/verify.py) |
| **Evidence never changes.** Uploaded originals are write-once; parsed source lines cannot be updated or deleted; published reports and builds are frozen. | [storage.py](backend/mrm/storage.py), triggers in [0003_rd_platform.sql](backend/mrm/migrations/0003_rd_platform.sql) |
| **Every action is traceable.** An append-only, hash-chained audit log, computed by the database. | [audit.py](backend/mrm/audit.py), [0002_controls.sql](backend/mrm/migrations/0002_controls.sql) |
| **Reproducible output.** The same inputs, decisions and rule set give byte-identical workbooks. | `excel.stable()`, `inputs_sha256`, `ruleset_sha256` |
| **Client isolation.** Checked in the API, then again by PostgreSQL row-level security. | [rd/access.py](backend/mrm/rd/access.py), RLS policies |

---

## 3. Runtime topology

```mermaid
flowchart LR
  B["Browser<br/>(React SPA)"] -- "HTTP :8080<br/>(127.0.0.1 by default)" --> W

  subgraph compose["docker compose project 'mrm'"]
    W["web<br/>nginx 1.27 + built SPA<br/>:80 in container"]
    A["api<br/>FastAPI / uvicorn ×2 workers<br/>:8000, RD_WORKER=off"]
    K["worker<br/>python -m mrm.cli worker"]
    BS["bootstrap (one-shot)<br/>python -m mrm.cli bootstrap"]
    D[("db<br/>PostgreSQL 16")]
    V1[["volume: objects<br/>/data/objects"]]
    V2[["volume: pgdata"]]
  end

  W -- "/api/* proxy<br/>(re-resolves 'api' every 10 s)" --> A
  A -- "mrm_app login" --> D
  K -- "mrm_app login" --> D
  BS -- "mrm_owner login (migrations)<br/>mrm_app (seed)" --> D
  A --- V1
  K --- V1
  BS --- V1
  D --- V2
```

| Service | Image / command | Role | Start order |
|---|---|---|---|
| `db` | `postgres:16-alpine`; [deploy/postgres/init.sh](deploy/postgres/init.sh) runs on first volume start | Creates logins `mrm_owner` (owns the schema) and `mrm_app` (the application) | first; healthcheck `pg_isready` |
| `bootstrap` | backend image, `python -m mrm.cli bootstrap` | Applies migrations as `mrm_owner`, then seeds client SVF. Exits. | after `db` is healthy |
| `api` | backend image, `uvicorn mrm.api.app:app --workers 2 --proxy-headers` | HTTP API. `RD_WORKER=off`: it never processes jobs itself. | after `bootstrap` completed |
| `worker` | backend image, `python -m mrm.cli worker` | Claims and runs processing and publishing jobs | after `bootstrap` completed |
| `web` | multi-stage: `node:22-alpine` builds, `nginx:1.27-alpine` serves | Static SPA + reverse proxy for `/api/` | after `api` is healthy |

**Volumes.** `pgdata` holds the database. `objects` holds the file store (§7.5). Both must be backed up together.

**Binding.** `web` publishes `${WEB_BIND:-127.0.0.1}:${WEB_PORT:-8080}:80`: by default only this computer can reach
the app. `WEB_BIND=0.0.0.0` exposes it, which is only safe behind HTTPS and a firewall.

**Containers run as non-root.** The backend image creates the user `mrm` (uid/gid 10001), owns `/data` and drops
privileges. Its healthcheck calls `GET /api/health`, which runs `SELECT 1`.

**Development mode** uses one process instead: `uvicorn mrm.api.app:app --port 8010` with the default
`RD_WORKER=thread` starts a daemon worker thread inside the API process (`app._start_worker`). Port 8000 is used by
another project on the development machine, so the dev API runs on 8010 and Vite proxies to it (`API_URL`).

---

## 4. Codebase map

```
RD/
├── docker-compose.yml          services db, bootstrap, api, worker, web
├── .env.example                Compose-only: WEB_BIND, WEB_PORT
├── deploy/postgres/init.sh     first-start DB logins and schema ownership
├── backend/
│   ├── Dockerfile              python:3.12-slim, non-root, uvicorn ×2
│   ├── requirements.txt        fastapi, uvicorn, python-multipart, openpyxl, defusedxml, psycopg[pool]
│   ├── .env.example            every backend setting and secret, explained (copy to backend/.env, chmod 600)
│   └── mrm/
│       ├── __init__.py         __version__ = "1.0.6"
│       ├── config.py           Settings from env + backend/.env; production refuses weak DB passwords
│       ├── db.py               connection pool, tx(), insert/update/insert_many helpers, exact JSON
│       ├── migrate.py          ordered plain-SQL migrations with sha256 tamper check
│       ├── migrations/         0001…0006 *.sql
│       ├── security.py         roles, scrypt passwords, server-side sessions
│       ├── audit.py            record / recent / verify_chain
│       ├── storage.py          write-once object store (originals, packs, reports)
│       ├── seed.py             client SVF and its configuration; create_user()
│       ├── releases.py         "What's new" notes, newest first
│       ├── cli.py              migrate | seed | bootstrap | worker | create-user | verify-audit
│       ├── normalize.py        money, codes (ISRC, work no), titles (fold/similarity), dates
│       ├── parsing/
│       │   ├── safety.py       upload checks: type by content, macros, ZIP bombs, limits
│       │   └── reader.py       workbook/CSV bytes → sheets of cached values
│       ├── rd/                 the royalty platform
│       │   ├── model.py        plain dataclasses passed between stages
│       │   ├── rules.py        RULESET_V1, review statuses, section order, palette
│       │   ├── names.py        file-name grammar, periods, Indian FY, penny-exact rounding
│       │   ├── parsers.py      readers per file kind
│       │   ├── detect.py       identify() kind from content; evaluate() metadata + problems + status
│       │   ├── assemble.py     parsed data + confirmed metadata → engine inputs
│       │   ├── engine.py       the build
│       │   ├── verify.py       independent re-computation
│       │   ├── excel.py        master + companion workbook writers (deterministic)
│       │   ├── store.py        parsed data ↔ rows
│       │   ├── access.py       capabilities, client scope, scoped transactions
│       │   ├── service.py      what the screens do
│       │   └── jobs.py         background processing and publishing
│       └── api/
│           ├── app.py          FastAPI app, CSRF middleware, error mapping, /api/health
│           ├── deps.py         actor(), exact JSON response, paging
│           ├── routes_auth.py  sign-up, sign-in, sign-out, me, profile
│           └── routes_rd.py    clients, runs, files, builds, review, publish, reports, people, diagnostics
├── frontend/
│   ├── Dockerfile              node build → nginx
│   ├── nginx/                  nginx.conf, security-headers.conf
│   ├── vite.config.ts          dev server :5173, /api proxy, __APP_VERSION__
│   └── src/                    React 18 + TanStack Query (see §18)
└── Docs/                       design docs, reference inputs (Docs/input) and reference outputs (Docs/output)
```

### 4.1 Layering inside `rd/`

```mermaid
flowchart TB
  subgraph pure["Pure modules: no database, no I/O beyond bytes in / bytes out"]
    rules[rules.py]
    names[names.py]
    model[model.py]
    parsers[parsers.py]
    detect[detect.py]
    assemble[assemble.py]
    engine[engine.py]
    verify[verify.py]
    excel[excel.py]
  end
  subgraph dbb["Database-backed"]
    access[access.py]
    store[store.py]
    service[service.py]
    jobs[jobs.py]
  end
  api["api/routes_*.py"] --> service
  api --> access
  service --> detect & store & access & rules & names
  jobs --> engine & verify & excel & assemble & store & access
  jobs --> service
  detect --> parsers & names
  parsers --> model
  engine --> names & rules & model
  verify --> engine
  excel --> engine & names & rules
```

The pure modules can be run over files directly, with no database: `assemble.py` exists so that tests and
command-line runs can build `RunInput` from parsed files. That keeps the money logic testable on its own.

---

## 5. Request lifecycle

```mermaid
sequenceDiagram
  participant Br as Browser
  participant Nx as nginx (web)
  participant MW as csrf_guard middleware
  participant Rt as route (routes_rd / routes_auth)
  participant Sv as service.py
  participant Ac as access.tx(actor)
  participant PG as PostgreSQL (RLS)

  Br->>Nx: POST /api/runs/12/process<br/>Cookie mrm_session, X-CSRF-Token
  Nx->>Nx: rate limit (api zone 40 r/s, burst 200)
  Nx->>MW: proxy to api:8000
  MW->>PG: load_session(token) to compare CSRF
  MW-->>Br: 403 if X-CSRF-Token ≠ session.csrf
  MW->>Rt: call_next
  Rt->>Rt: Depends(actor): load_session again → actor {id, email, roles, csrf}
  Rt->>Sv: service.start_build(actor, 12)
  Sv->>Sv: access.require(actor, "prepare")
  Sv->>Ac: open transaction
  Ac->>PG: client_ids(actor) → set_config('app.client_ids', '1,4', true)
  Sv->>PG: queries, which RLS filters to client_id = ANY(rd_scope())
  Sv->>PG: audit.record(...) → trigger chains the hash
  Ac->>PG: COMMIT
  Sv-->>Rt: plain dict
  Rt-->>Br: J(...) exact-decimal JSON, Cache-Control: no-store
```

**One transaction per unit of work.** `db.tx()` takes a pooled connection (`psycopg_pool`, `autocommit=False`,
`dict_row`) and opens one transaction. `access.tx(actor, client_id=None)` wraps it and sets the transaction-local
setting `app.client_ids` before any query runs. Inside the transaction the database shows only the rows of those
clients.

**CPU work stays outside transactions.** For example, `service.add_file` runs `detect.identify()` (parsing a workbook
can take seconds) between two short transactions.

**Error mapping** ([api/app.py](backend/mrm/api/app.py)):

| Raised | HTTP | Body `detail` |
|---|---|---|
| `deps.Unauthorized` | 401 | "Please sign in." (the frontend then shows the sign-in page) |
| `security.Forbidden` | 403 | the reason from `access.WHY` |
| `ValueError`, `service.RDError` | 400 | the plain-language message |
| `psycopg.errors.InsufficientPrivilege` (a guard trigger refused) | 409 | "This record is locked and cannot be changed. …" |
| `psycopg.errors.UniqueViolation` | 409 | "This already exists." |
| anything else | 500 | generic message; the stack trace goes only to the log |

Every response gets `Cache-Control: no-store` unless one is already set.

---

## 6. Security architecture

### 6.1 Identity and sessions ([security.py](backend/mrm/security.py), [routes_auth.py](backend/mrm/api/routes_auth.py))

- **Passwords.** scrypt from the standard library (N=2¹⁴, r=8, p=1, 16-byte salt, 32-byte key), stored as
  `scrypt$N$r$p$salt$dk`. The minimum length is 10. A password equal to the name or email is refused at sign-up. When
  the user is unknown, `check_password` still spends one scrypt, so a response's timing does not reveal whether an
  account exists.
- **Sessions are server-side.** The token is 32 random bytes (`token_urlsafe`). Only its sha256 is stored, in
  `app_session`. It lasts `SESSION_HOURS` (default 10). The cookie is `mrm_session`: `HttpOnly`, `SameSite=Strict`,
  `Path=/`, and `Secure` according to `COOKIE_SECURE` (`auto` follows the request scheme).
- **CSRF.** Each session has its own random token (24 bytes), returned by `/auth/me`, `/auth/login` and `/auth/signup`.
  The SPA sends it as `X-CSRF-Token` on every non-GET request. The middleware checks it for every state change under
  `/api/` except `/api/auth/login`, whenever a session cookie is present.
- **Sign-in throttling, in two layers.**
  - In the app: `LOGIN_MAX_FAILURES` (default 8) failed attempts per email in 15 minutes give `429`. Every attempt is
    stored in `login_attempt`, and failures are audited.
  - At nginx: the `signin` zone allows 10 requests/min per IP (burst 5) on `/api/auth/(login|signup)`.
- **Sign-up** only sets up a new installation (1.1.0): it is offered while `ALLOW_SIGNUP=true` **and** there is no active
  Super Admin. `pg_advisory_xact_lock(84726200)` serialises it; the account becomes the `SUPER_ADMIN`. After that,
  `/auth/signup` refuses (403) and Admins create accounts.
- **Temporary passwords** (1.1.0). Every account an Admin creates, and every password the Super Admin resets, gets
  `must_change_password = TRUE`. Until the person changes it, `deps.actor` refuses every request except `GET /auth/me`,
  `PATCH /me` and `POST /auth/logout` (403 "Please change your temporary password…"), and the SPA shows only the
  change-password screen. A generated temporary password (`security.temporary_password`, 16 random characters in four
  groups) is returned once to the person who set it; only its scrypt hash is stored. Existing passwords can never be
  shown.
- **Revocation.**
  - A password change revokes the person's other sessions (every one whose `csrf` differs from the current one).
  - Switching an account off, deleting it, changing its role or resetting its password revokes all of its sessions;
    the Super Admin can also sign an account out everywhere.
  - `load_session` rejects inactive and soft-deleted users, so such an account stops working at once.

### 6.2 Roles and capabilities ([rd/access.py](backend/mrm/rd/access.py), [people.py](backend/mrm/people.py))

Since 1.1.0 there are **exactly three roles**, stored in `app_user.role` (CHECK `SUPER_ADMIN | ADMIN | USER`). The
old `user_role` rows are kept as history and are not read. Migration 0007 mapped the earliest active `admin` to
`SUPER_ADMIN`, other `admin`s to `ADMIN` and everyone else to `USER` (former Viewers were granted every existing
client, so they keep seeing them). Each capability names the roles that grant it:

| Capability | SUPER_ADMIN | ADMIN | USER |
|---|:-:|:-:|:-:|
| `view`, `prepare`, `draft_download`: catalogue, statements, master, reconciliation, exports, enquiry drafts, reports | ✓ | ✓ | ✓ |
| `clients`: add a client, change its settings, switch it off | ✓ | ✓ | |
| `manage`: accounts (Users and Admins only) | ✓ | ✓ | |
| `diagnostics`: failed processing, jobs, rule set (without the activity log) | ✓ | ✓ | |
| `platforms`: platform names and aliases | ✓ | ✓ | |
| `verify_mappings`: verify, reject or move an ISRC-to-work link; edit a work | ✓ | ✓ | |
| `approve_enquiries`: approve or return a draft, record the manual sending | ✓ | ✓ | |
| `assign_followups`: assign follow-ups and set their dates, assign enquiries | ✓ | ✓ | |
| `close_enquiries`: close an enquiry once its resolution is verified | ✓ | ✓ | |
| `audit`: the administrative activity and security log (Settings → Activity log) | ✓ | | |
| `reset_passwords`: issue a temporary password, sign an account out everywhere | ✓ | | |
| `settings`: reference benchmark, client interest, revenue basis, IPRS currency | ✓ | | |

Workflow duties (who reviews an enquiry, who owns a follow-up) are assignments to people, not roles. The person an
enquiry is assigned to may also record that it was sent (after an approval).

**Account rules** ([people.py](backend/mrm/people.py)), all checked on the server:

- Admins create Users and Admins, change their names, roles (USER ↔ ADMIN only) and client grants, switch them off and
  delete them. Nobody can create a Super Admin, change the Super Admin, or change their own role, switch themselves
  off or delete themselves through the API.
- Deleting is a soft delete (`deleted_at`, `deleted_by`, `active = FALSE`): the account can no longer sign in, and
  every recorded action keeps its person.
- The **database** protects the Super Admin whatever the application asks for (`super_admin_guard` trigger, 0007): the
  Super Admin row can never be deleted; the last active Super Admin can never be demoted, switched off or
  soft-deleted; a second Super Admin can only be created inside a transaction that set `app.recovery = on`, which only
  the audited command `python -m mrm.cli recover-super-admin EMAIL --reason … [--demote-current]` does (shell access to
  the server is the separate security for that exceptional path).

`GET /auth/me` returns `role`, `role_label`, `must_change_password` and `can: {capability: bool}`. The frontend uses
them only to hide controls; the server checks every request itself (`access.require`).

**Which clients a person sees** (`access.client_ids`): Super Admin and Admins see every client; a User sees the
clients granted in `client_grant` (an Admin chooses them when creating the account).

### 6.3 Client isolation in the database

Migration `0003` enables row-level security on every table that holds client data:

```sql
CREATE POLICY client_scope ON <table>
  USING (client_id = ANY (rd_scope())) WITH CHECK (client_id = ANY (rd_scope()));
-- rd_scope() = string_to_array(current_setting('app.client_ids', true), ',')::BIGINT[], or '{}' when unset
```

Scoped tables: `client_holder`, `rd_file`, `rd_royalty_line`, `rd_platform_line`, `rd_song_entry`, `rd_prior`,
`rd_run`, `rd_run_file`, `rd_build`, `rd_issue`, `rd_finding`, `rd_report`, `rd_decision`, and since 1.1.0 every table
of §26.2 that holds client data (`works`, `work_recordings`, `mapping_events`, `catalogue_imports`,
`catalogue_import_rows`, `statements`, `reconciliation_*`, `enquiries`, `enquiry_*`). The record views are
`security_invoker`, so the same policies apply through them. `platforms`, `platform_aliases` and `recordings` (an ISRC
on its own) hold no client data and are not scoped.

**If the scope is not set, nothing is visible.** A forgotten `access.tx` therefore fails closed: the query sees no
rows rather than another client's rows. Background work scopes itself to exactly one client:
`access.tx(None, client_id)`.

Not scoped (they hold no client data, or are needed before a scope exists): `client`, `client_grant`, `app_user`,
`user_role`, `app_session`, `login_attempt`, `audit_event`, `rd_job`, `schema_migrations`.

### 6.4 Database logins and privileges

| Login | Used by | Can |
|---|---|---|
| `postgres` | inside the db container only | superuser |
| `mrm_owner` | `bootstrap` (`MIGRATOR_DATABASE_URL`) | owns the schema; runs migrations. RLS does not apply to the table owner. |
| `mrm_app` | `api`, `worker` (`DATABASE_URL`) | `SELECT, INSERT, UPDATE, DELETE` on the working tables, except: line tables (`rd_royalty_line`, `rd_platform_line`, `rd_song_entry`, `rd_prior`) are `SELECT, INSERT` only; `DELETE` is revoked on `rd_file`, `rd_build`, `rd_report`, `rd_decision`; `UPDATE, DELETE, TRUNCATE` are revoked on `audit_event`; `schema_migrations` is read-only. No DDL (`REVOKE CREATE ON SCHEMA public FROM PUBLIC`). |

The guard triggers in §7.3 back these grants up: a privilege mistake still cannot rewrite evidence.

### 6.5 Upload hardening ([parsing/safety.py](backend/mrm/parsing/safety.py), [parsing/reader.py](backend/mrm/parsing/reader.py))

The file type is decided by the bytes, not by the name:

1. **Size.** The route reads at most `MAX_UPLOAD_MB`+1 bytes and refuses anything larger. nginx also caps a request
   body at 70 MB.
2. **ZIP signature `PK\x03\x04`** means an `.xlsx` candidate. Anything else must be named `.csv`, contain no NUL bytes
   and decode as UTF-8 or Windows-1252.
3. **ZIP checks.**
   - `[Content_Types].xml` and `xl/` must be present.
   - Entry names may not be absolute, contain `..`, `\` or `:`.
   - Each entry over 1 MB may expand at most `MAX_ZIP_RATIO` times (default 200).
   - All entries together may unzip to at most `MAX_UNZIPPED_MB` (default 512).
   - There may be at most `MAX_SHEETS` worksheets (default 100).
4. **Active content is refused:** `vbaProject.bin`, `xl/externalLinks/`, `xl/embeddings/`, `xl/activeX/`,
   `customUI/`, and macro-enabled or binary content types (`.xlsm`, `.xlsb`, add-ins, macro templates).
5. **Parsing.**
   - openpyxl runs with `OPENPYXL_DEFUSEDXML=True`, `read_only`, `data_only` (cached values; formulas are never
     evaluated) and `keep_links=False`.
   - Dimensions are reset, because some IPRS files carry a wrong 1×1 dimension record.
   - Reading stops after `MAX_CELLS` cells (default 2,000,000).
6. A rejected or damaged file is stored with status `UNSUPPORTED` / `ERROR` and a plain message. It is never parsed
   further.

### 6.6 Output hardening

- **Formula injection.** `excel.put()` stores any string that starts with `= + - @ \t \r` as a text cell, so text
  taken from an upload cannot become a formula in our workbook.
- **Downloads.**
  - The permission is checked again on every download (`_report_bytes`): `draft_download` for non-final reports, and
    no download at all while a build is `QUEUED`, `RUNNING` or `FAILED`.
  - The stored bytes are re-hashed and compared with `rd_report.sha256` before they are sent.
  - Files go out as attachments (RFC 5987 `filename*`) with `X-Content-Type-Options: nosniff` and
    `Cache-Control: no-store`.
- **Browser headers** (nginx, [security-headers.conf](frontend/nginx/security-headers.conf)): a strict CSP
  (`default-src 'self'`, `script-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`), `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, a `Permissions-Policy` that denies camera, microphone and geolocation, and
  `server_tokens off`.

### 6.7 Secrets and production guard ([config.py](backend/mrm/config.py))

- All secrets live in `backend/.env`. It is created from `backend/.env.example`, set to `chmod 600`, and ignored by
  both git and the Docker build context. Compose passes it to `db`, `bootstrap`, `api` and `worker` through `env_file`.
- **Loading order.** A variable already in the environment wins over the file. `ENV_FILE=<path>` reads another file;
  `ENV_FILE=none` reads none (this is required for local development, otherwise the Docker `.env` with host `db` is
  loaded). A value `file:/run/secrets/x` reads a Docker secret.
- **Production guard.** With `APP_ENV=production` the process refuses to start (`SystemExit`) if either database
  password is in the weak list or shorter than 16 characters. `/api/docs` and `/api/openapi.json` are switched off
  unless `API_DOCS=true`.

---

## 7. Data model

### 7.1 Entity relationships (platform tables)

```mermaid
erDiagram
  client ||--o{ client_holder : "rights holders"
  client ||--o{ client_grant : "who may see"
  app_user ||--o{ client_grant : ""
  app_user ||--o{ user_role : ""
  app_user ||--o{ app_session : ""
  client ||--o{ rd_file : "uploaded (dedup by sha256)"
  rd_file ||--o{ rd_royalty_line : "STATEMENT"
  rd_file ||--o{ rd_platform_line : "PLATFORM_*"
  rd_file ||--o{ rd_song_entry : "SONG_LIST / REVIEW_LIST"
  rd_file ||--o| rd_prior : "PREVIOUS_OUTPUT (JSONB)"
  client ||--o{ rd_run : ""
  rd_run ||--o{ rd_run_file : "files in the run"
  rd_file ||--o{ rd_run_file : "reused across runs"
  rd_run ||--o{ rd_build : "one per Process (version)"
  rd_build ||--o{ rd_issue : "review queue"
  rd_build ||--o{ rd_finding : "paid, not in base"
  rd_build ||--o{ rd_report : "MASTER / MISSING / NON_CLIENT × draft/final"
  rd_build ||--o{ rd_job : "process / publish"
  client ||--o{ rd_decision : "keyed by codes, outlives runs"
```

### 7.2 Tables by group

| Group | Table | Key columns and notes |
|---|---|---|
| People | `app_user` | `email` unique, `password_hash`, `active`, `last_login_at`, `seen_version` (last What's new note read) |
| | `user_role` | `(user_id, role)`; CHECK role ∈ admin, importer, rights_reviewer, accounts, viewer |
| | `app_session` | `token_sha256` PK, `csrf`, `expires_at`, `revoked_at` |
| | `login_attempt` | email, ok, at (throttling window) |
| Clients | `client` | `code` unique; `settings` JSONB (`output_prefix`, `next_generation`, `song_list_name`, `distributors[{name, currency, basis, platforms}]`); `active` |
| | `client_holder` | society member numbers whose statements belong to the client; unique `(client_id, society, member_no)` |
| | `client_grant` | `(user_id, client_id)`, `granted_by` |
| Files | `rd_file` | unique `(client_id, sha256)`; `kind`, `kind_source`, `layout`, `why`; `facts` (a JSON summary of what was read); `overrides` (the user's answers); `status`; `meta` and `meta_source` (each value and where it came from); `problems`; `summary`; `object_key` |
| | `rd_royalty_line` | statement lines: `work_no` (NULL means no code), `raw_work`, `title`, party/role/shares, `pool`, `source`, `usage` JSONB (overseas split), `amount NUMERIC NOT NULL` |
| | `rd_platform_line` | `month`, `isrc`, `title`, `album`, `upc`, `amount` (NULL = blank), `plays` |
| | `rd_song_entry` | `work_nos[]`, `isrcs[]`, `other_codes[]` (unreadable codes kept as written), `status_text`, `note` |
| | `rd_prior` | the previous SKV report's columns and rows as JSONB, exactly as read |
| Runs | `rd_run` | `state` OPEN / ARCHIVED / DELETED (soft delete: `deleted_at`, `deleted_by`) |
| | `rd_run_file` | `(run_id, file_id)`, `removed`, `choice` JSONB (`relation`: SUPPLEMENTARY / LEAVE_OUT) |
| Builds | `rd_build` | `version` per run; `state`; `stages` JSONB; `inputs_sha256`, `decisions_sha256`, `ruleset_version`, `ruleset_sha256`, `software_version`; `summary`, `checks`, `notices`, `left_out`, `inputs`; `generation`, `generation_no` (unique per client); `approved_by` (holds the publisher since 1.0.5), `returned_reason` |
| | `rd_issue` | `(build_id, issue_no)`; `kind`, `severity`, `category`, `subject` JSONB, `actions` JSONB, `later` |
| | `rd_finding` | `(build_id, finding_no)`; `row_key`, `title`, codes, `royalty`, `platform`, `status`, `status_original`, `proposal` |
| | `rd_report` | `kind` MASTER / MISSING / NON_CLIENT; `final`; `object_key`, `sha256`, `bytes`, `rows`; `available` + `reason`; unique `(build_id, kind, final)` |
| Decisions | `rd_decision` | `kind` LINK / NOT_SAME / ASSIGN_HELD / SONG_STATUS; `subject`, `subject_key`, `value`, `original`, `evidence`, `reason`, `source`; `moves_money`; `state`; `made_by` |
| Jobs | `rd_job` | `build_id`, `state` QUEUED / RUNNING / DONE / FAILED, `attempts`, `heartbeat_at` |
| Audit | `audit_event` | `id`, `at`, `actor_id`, `actor`, `action`, `object_kind`, `object_id`, `detail`, `prev_hash`, `hash` |

Money columns are `NUMERIC`, with no fixed scale, so the source precision is kept (overseas statements carry 4+
decimals). Rounding to the paisa happens only when output is written (§11.8).

The 1.1.0 tables (catalogue, statement registry, reconciliation, enquiries) are described in §26.2.

### 7.3 Immutability (database triggers)

Each refusal raises `insufficient_privilege`, which the API maps to HTTP 409.

| Trigger | Table | What it refuses |
|---|---|---|
| `refuse_change` | `rd_royalty_line`, `rd_platform_line`, `rd_song_entry`, `rd_prior` | any UPDATE or DELETE |
| `rd_file_guard` | `rd_file` | DELETE; changing identity (`client_id`, `sha256`, `filename`, `bytes`, `object_key`, `uploaded_by`, `uploaded_at`). Metadata, answers and status may change. |
| `rd_build_guard` | `rd_build` | DELETE; any change to a PUBLISHED or SUPERSEDED build, except PUBLISHED → SUPERSEDED with every other column unchanged |
| `rd_report_guard` | `rd_report` | DELETE; any change to a `final` report |
| `rd_decision_guard` | `rd_decision` | DELETE; editing content (only `state` and the `checked_*` columns may change); any state move other than WAITING_APPROVAL → ACTIVE / REJECTED or ACTIVE → SUPERSEDED / REVOKED |
| `audit_chain` + `audit_append_only` | `audit_event` | computes `id`, `at`, `prev_hash`, `hash` on INSERT; refuses UPDATE and DELETE |

So deleting a run is a **soft delete**: `rd_run.state='DELETED'`, and its draft reports are marked
`available=FALSE`. Published reports can never be deleted. People with recorded work cannot be deleted either: the
foreign keys refuse it, and the API turns that into "switch it off instead".

### 7.4 State machines

**Build (`rd_build.state`)**

```mermaid
stateDiagram-v2
  [*] --> QUEUED: POST /runs/{id}/process
  QUEUED --> RUNNING: worker claims job
  RUNNING --> CHECKED: build + checks + draft reports OK
  RUNNING --> FAILED: a check failed / exception / stale heartbeat (20 min)
  QUEUED --> FAILED: stale sweep
  CHECKED --> SUBMITTED: POST /builds/{id}/publish ("Publishing")
  SUBMITTED --> PUBLISHED: worker rebuilds, proves same numbers, writes final reports
  SUBMITTED --> CHECKED: publish refused or failed (returned_reason set)
  PUBLISHED --> SUPERSEDED: a newer version of the same client is published
  FAILED --> [*]
  SUPERSEDED --> [*]
```

**Run (`rd_run.state`):** `OPEN` → `ARCHIVED` (closed; its files and reports are kept) or `DELETED` (only when no
build is PUBLISHED, SUPERSEDED, QUEUED, RUNNING or SUBMITTED).

**File (`rd_file.status`)**, decided by `detect.evaluate` from the most severe problem:

| Status | Comes from a problem of severity | Effect |
|---|---|---|
| `ERROR` | `ERROR` (e.g. `RECON_MISMATCH`, `NO_PRINTED_TOTAL`, `MIXED_CURRENCY`, `NO_MONTH`) | left out of the run |
| `UNSUPPORTED` | upload rejected by the safety checks | left out |
| `LEFT_OUT` | `EXCLUDE` (e.g. `OTHER_HOLDER`: a statement of a member not in the client's holders) | left out, with the reason shown |
| `NEEDS_REVIEW` | `REVIEW` (a question with a `field`: category, society, currency, basis, platform, distributor, kind, accept_edited) | processing is blocked until answered |
| `READY` | only `WARNING` / `INFO` | used |

**Decision (`rd_decision.state`):** created `ACTIVE` (since 1.0.5). A newer decision for the same `subject_key`
moves the old one to `SUPERSEDED`. `WAITING_APPROVAL`, `REJECTED` and `REVOKED` are still allowed by the schema; only
migration 0006 uses them.

### 7.5 Object store ([storage.py](backend/mrm/storage.py))

One directory per bucket under `STORAGE_ROOT` (`/data/objects` in Docker):

| Bucket | Key | Written by |
|---|---|---|
| `originals` | `{CLIENT_CODE}/{sha256}.xlsx` or `.csv` | `service.add_file` |
| `reports` | `{CLIENT_CODE}/{build_id}/{draft\|final}/{sha256}.xlsx` | `jobs._save_reports` |
| `packs` | (unused; left over from the removed comparison module) | none |

- **Write-once.** `put()` returns quietly if the key already holds the same bytes, and refuses if it holds different
  bytes.
- **Atomic.** Bytes go to a temporary file first, which `os.replace` moves into place; the file is then made
  read-only (`chmod 0400`).
- **Path safety.** A key whose resolved path leaves its bucket directory is refused.

Because keys contain the content hash, re-uploading a file reuses the stored copy (§8.1).

### 7.6 Tables left over from the comparison module

Migration `0001_schema.sql` still creates the tables of the earlier MRM comparison module, which was removed from the
code on 10 October 2026: `batch`, `source_file`, `publishing_line`, `recording_line`, `usage_line`, `catalogue_line`,
`composition`, `recording`, `work_link`, `identity_issue`, `duplicate_candidate`, `identity_version`,
`identity_version_link`, `rule_version`, `comparison_run`, `comparison_group`, `run_exception`, `report_pack`,
`enquiry_case`, `case_event`. The same goes for their guards in `0002_controls.sql`. **No current code reads or
writes them.** They stay because applied migrations must not change (§21.3). Dropping them needs a new migration.

---

## 8. File intake

### 8.1 Upload (`POST /api/runs/{rid}/files` → `service.add_file`)

```mermaid
flowchart TD
  U[upload bytes] --> H{sha256 already<br/>stored for this client?}
  H -- yes --> R[re-attach the existing rd_file to this run<br/>'the same copy is used, nothing counted twice']
  H -- no --> I["detect.identify(name, bytes)<br/>(outside any transaction)"]
  I --> S[storage.put originals]
  S --> E["detect.evaluate(kind, facts, name, client cfg)"]
  E --> F[INSERT rd_file + source lines<br/>store.save_data]
  F --> RL{REVIEW_LIST and READY?}
  RL -- yes --> SS[import each status as a SONG_STATUS decision]
  RL -- no --> Done
  SS --> Done[audit file.uploaded]
```

### 8.2 `detect.identify()`: what is this file?

1. `safety.check_bytes` (§6.5), then `reader.parse` into `[{title, state, rows}]`.
2. The kind is decided **from the content**, in this order. The first match wins, and only visible sheets are tried:

| Order | Test | Result |
|---|---|---|
| 1 | A sheet looks like the SKV layout: row 2 = `ISRC · Song Name · Internal No · Total Amount` + `Date · Amount · Period · Distribution Number` blocks (`parsers.looks_like_skv`) | `PREVIOUS_OUTPUT` (layout `SKV_NATIVE` if a hidden `_rd_meta` sheet is present, else `SKV_LEGACY`) |
| 2 | One of our own Missing Songs / out-of-scope reports, edited and uploaded back (`looks_like_companion`) | `REVIEW_LIST` (if it has statuses) or `SONG_LIST` |
| 3 | A `WORK INT NO` cell in the first 4 columns of the first 40 rows | `STATEMENT` (`IPRS_OVERSEAS` if `RADIO` and `TV` columns exist, else `IPRS_STANDARD`) |
| 4 | A header row in the first 15 rows naming ≥ 2 known columns (`find_table` + `table_kind`): ISRC + month + revenue | `PLATFORM_REVENUE` |
| | ISRC + month + plays/streams | `PLATFORM_USAGE` |
| | title + work number / ISRC (+ a status column) | `SONG_LIST` / `REVIEW_LIST` |
| 5 | nothing matched | `UNKNOWN`, with a `kind` question (the user picks; `identify` runs again with `forced_kind`) |

3. The result is a `Parsed` with the typed data (§4, `model.py`) and a JSON-safe `facts` summary: totals, counts,
   months, footers, a `content_sha256` fingerprint for statements, and so on.

### 8.3 Statement parsing rules ([parsers.py](backend/mrm/rd/parsers.py))

These were proven on the reference set.

- **Standard layout** (12 columns, money in `ROYALTY AMT` = column L): a line carries money only when `SOURCE` is
  filled. The bare line after a block repeats the block's sub-total and is never counted again.
- **Overseas layout** (17 columns, usage split RADIO … OTHERS, money in column Q): a line is kept when `NAME`, `ROLE`
  and `ROYALTY AMT` are all filled. `0.0` is a real line ("named, 0.00 paid"). The `OTHERS` cell of the overseas
  sub-total row is unreliable, so only column Q is used.
- Work number, title, AV and language appear only on a block's first line and are carried forward to the following
  lines.
- Reading stops before the `TOTAL ROYALTIES` row; its label sits in column H, not A.
- **Letterhead** (above the header): `INTERNAL NO` gives the holder member number, plus `NAME`, `IPI NAME NO` and
  `IPI BASE NO`.
- **Footer tables** (`SUMMARY OF ROYALTY` by language, `POOL` / `SOURCE`) are independent totals and are checked
  against the lines. Their `NO. OF WORKS` column is not a work count and is never checked.

### 8.4 `detect.evaluate()`: metadata, problems, status

`evaluate()` never re-reads the file: it works from `facts`, the client configuration and the user's answers
(`overrides`). Answering a question is therefore instant. Every metadata value records its source in `meta_source`
(file name / file content / client setting / "you entered" / assumed).

**Statements:**

- **From the file name** (`names.statement_meta_from_name`):
  - `label` (`S-13`);
  - `dist_no`: `P2550`, `P2107A008`, or a range like `P2101 to P2540`;
  - `category`, from keywords: Redistribution, Mechanical (MUSERK), Apple Music, Spotify, YouTube Pre-/Post-Claims,
    Facebook / Meta, Radio, Zee TV Broadcast, Overseas;
  - overseas society code → name and country (`rules.OVERSEAS_SOCIETIES`);
  - period, including misspelt months (the first three letters count) and `F.Y. 2025-26`.
- **From the content,** when the name says nothing: the category comes from the footer pool sources (`spotify`,
  `apple`, `muserk`, …) or from the overseas layout.
- **Section** = category, or `Overseas - <SOCIETY> (<Country>)`.
- **Date** = the date the file was last saved, read from the ZIP entries, unless the user enters one. This matches
  SKV8.
- **Money checks:**
  - `NO_PRINTED_TOTAL`, `RECON_MISMATCH` (lines vs printed total), `SUBTOTAL_MISMATCH` and `FOOTER_MISMATCH` are
    `ERROR`s, within `recon_tolerance` (₹0.05);
  - `BLANK_AMOUNTS`, `NO_WORK_NUMBER` (held) and `NEGATIVE_LINES` are warnings or info.
- **Whose statement:** a member number missing from the letterhead gives `NO_HOLDER` (REVIEW). A member not among the
  client's holders gives `OTHER_HOLDER` (EXCLUDE → `LEFT_OUT`).
- **`identity_key`** = `IPRS|member|section|dist_no|period_start|period_end`. It is used to detect the same
  distribution uploaded twice.

**Platform reports:**

- The platform comes from the file's own platform column (when it has a single value), else from the file name.
- The distributor comes from a name token that matches a configured distributor, else from the client's single
  distributor.
- Currency and basis come from the file, else from the distributor's settings. For SVF: MRM → INR, GROSS (business
  decision Q8).
- Problems:
  - `MIXED_CURRENCY`, `FOREIGN_CURRENCY` (only INR is supported) and `NO_MONTH` are `ERROR`s;
  - `BLANK_ISRC` is a warning: that money is held;
  - `NO_PRINTED_TOTAL_PLATFORM` is info: the total is calculated from the lines.

**Lists:**

- `EMPTY_LIST` is an error.
- `TITLE_ONLY` (entries with no code can only be matched by title) is a warning; `ODD_CODES` is info.
- For review lists, the status counts are shown and `UNRECOGNISED_STATUS` is a warning.

**Previous report:**

- `EDITED_BASE` (REVIEW): the report's own totals no longer add up. The question is `accept_edited`; a yes turns it
  into the warning `EDITED_BASE_ACCEPTED`.
- `TITLE_PLACED_IN_BASE` (info) lists songs that got platform money through a song-name match in an earlier report.

### 8.5 Review-list import

Each entry of a `READY` review list whose status maps to a standard status (§13.3) and which has an ISRC or a work
number becomes a `SONG_STATUS` decision. Its `subject_key` is the sorted codes joined with `|`; any older active
status for the same codes is superseded. The reviewer's wording is kept in `value.original`. Statuses are therefore
remembered **per client, across runs**.

---

## 9. Run-level checks

`service.run_checks(conn, run, files)` runs on every view of a run and again just before processing. It decides which
files are `used` and which are `left_out` (each with a reason), and which questions **block** processing:

| Check | Result |
|---|---|
| A file is `ERROR` / `UNSUPPORTED` / `LEFT_OUT`, or the user chose "leave out" | left out, with the first ERROR/EXCLUDE message as the reason |
| Two READY statements with the same `identity_key` **and** the same `content_sha256` | the later one is left out ("counted once") |
| Same `identity_key`, **different** entries | blocking `SAME_DISTRIBUTION`: use both (SUPPLEMENTARY) / use only A / use only B |
| More than one song list, or more than one previous report | blocking `CHOOSE_BASE` |
| A statement whose section + distribution number + period is already a column of the previous report, with the same total | left out ("already included in SKVn") |
| … with a different total | blocking `ALREADY_IN_BASE`: add as a separate payment / leave out |
| Statements of more than one rights holder | blocking `MIXED_HOLDERS`: process each holder in its own run |
| Any file `NEEDS_REVIEW` | blocked until it is answered |
| No money file and no previous report | blocked |

`can_process = not blocked`. `start_build` refuses with the same messages.

---

## 10. Processing pipeline

```mermaid
sequenceDiagram
  participant UI
  participant API as service.start_build
  participant DB as PostgreSQL
  participant W as worker (jobs.py)
  participant FS as object store

  UI->>API: POST /runs/{rid}/process
  API->>DB: advisory lock (84726100, client)<br/>refuse if this client has a QUEUED/RUNNING build
  API->>DB: run_checks → can_process?
  API->>DB: INSERT rd_build (QUEUED, version n, stages[5], inputs_sha256, ruleset sha, software)<br/>INSERT rd_job (QUEUED)
  API->>W: jobs.wake() (in-process event; the separate worker polls every 5 s)
  W->>DB: SELECT … FOR UPDATE SKIP LOCKED → RUNNING, heartbeat
  W->>DB: stage 0–1: load_inputs (files used, data, ACTIVE decisions)
  W->>W: stage 2: engine.build + verify.master; any failed check → FAILED
  W->>DB: stage 3: rd_issue + rd_finding rows
  W->>W: stage 4: excel.master + companions (+ verify.companion)
  W->>FS: put reports/{CODE}/{build}/draft/{sha}.xlsx
  W->>DB: rd_report rows; build CHECKED (summary, checks, notices, inputs, decisions_sha256)
  UI->>API: polls GET /runs/{rid} (2 s) and GET /builds/{bid} (1.5 s)
```

The five stages shown in the UI (`service.STAGES`) are: *Checking statements · Extracting royalty entries · Checking
financial totals · Matching song records · Preparing reports*. Each one is written back to `rd_build.stages` together
with a heartbeat.

**`jobs.load_inputs`** rebuilds the engine input from the database, never from the browser:

1. `run_checks` → the `used` files with status READY.
2. Per kind, `store.load_data` → `assemble.*_src`. A statement marked SUPPLEMENTARY gets
   `identity_key += "#supplementary:<file_id>"`, so it may coexist with the column it overlaps.
3. The client's `ACTIVE` decisions: `SONG_STATUS` become `ReviewMark`s; LINK, NOT_SAME and ASSIGN_HELD become
   `Decision`s.
4. The rule set `RULESET_V1`.

**Failure behaviour.**

- A failed blocking check or an exception marks the build `FAILED`. The user gets a plain message (`error`); the
  technical detail (`error_detail`) is shown only to administrators.
- No report is written, or reports from a failed build are never offered. A half-made report is never possible.

**`inputs_sha256`** is a sha256 over:

- each used file's sha256, kind, `overrides` and SUPPLEMENTARY relation;
- the IDs of every ACTIVE decision of the client;
- the rule-set sha.

If it changes after a build (a new file, an answer, any review decision), `run_view.changed_since_build` turns true.
The UI then asks the user to process again, and publishing is refused.

---

## 11. The build engine

[rd/engine.py](backend/mrm/rd/engine.py) `build(RunInput) -> Result`. It is a pure function with no I/O. The steps
below follow the numbered comments in the code.

### 11.1 Vocabulary

| Thing | Key format | Meaning |
|---|---|---|
| Row origin `prior` | `prior:{file}:{row}` | a row carried from the previous master report |
| `list` | `list:{file}:{entry}` | a song-list entry not already in the previous report |
| `work` | `work:{work_no}` | a work paid by a statement but in no base row |
| `recording` | `rec:{isrc}` | a recording paid by a platform but in no base row |
| `usage` | `usage:{isrc}` | streams only (no money) for an ISRC in no row |
| `hold` | `hold:nocode:{file}:{raw}` · `hold:noisrc:{file}:{title}` · `hold:shared:{isrc}` | money waiting for a decision. A held row never claims a code. |
| Column `X:{file}:{idx}` | | a column of the previous report (origin `prior`) |
| `S:{file}` | | one statement = one distribution column |
| `P:{file}:{YYYY-MM}` | | one platform report month |
| `Cell` | `exact`, `shown`, `named_zero`, `sibling`, `lines` | one row × column; `exact` is unrounded, `shown` is what is printed |
| `Band` | `ROY\|<section>` · `PLATFORM\|<platform>\|<distributor>\|<basis>` | a row-1 coloured section of columns |

### 11.2 Steps

1. **Base: previous report.** Every prior column becomes a `Col` and every prior row a `Row` (`in_base=True`), with its
   cells as they were. A "booked once on '…'" note in the prior report becomes an `owner_hint`, so a work keeps the
   same owner row across generations. Rows whose platform basis says "song name" are flagged, and a
   `TITLE_PLACED_IN_BASE` issue (INFO) is raised.
2. **Base: song list.** Each entry whose work number or ISRC is already on a prior row only marks that row "in list".
   Every other entry becomes a `list` row.
3. **Decisions that add codes.** `NOT_SAME` pairs are collected for step 11. In ID order:
   - `LINK` adds the ISRC or work to the target row (`extra_isrcs` / `extra_works`), so its money lands there;
   - `ASSIGN_HELD` sends a shared ISRC to the chosen row.

   A decision whose target is not in this run is reported as a notice, not applied.
4. **Columns for new money.** `_not_already_in_base` drops what the previous report already has:
   - a statement with the same section + distribution + period and the same total is skipped (a notice);
   - with a different total, it is a BLOCKING `ALREADY_IN_BASE` issue, unless it is SUPPLEMENTARY;
   - platform months are handled the same way.

   Statements are then sorted by section rank, date and file. Two statements with the same `identity_key` raise
   `BuildFailed` (check `I12`).
5. **Place statement money (works).** Lines are grouped by work number. Works in no row get a new `work` row titled
   with the latest statement title. If several rows claim the work, `_owner` picks one, in this order:
   1. the only candidate;
   2. the `owner_hint`;
   3. an exact title-key match;
   4. a base-title match;
   5. the first in list order.

   The owner row receives the money. The other candidate rows get a `sibling` cell (shown blank) and a "Royalty Booked
   On" note. A statement title that differs from the owner's title is flagged. Lines with no work number go to
   `hold:nocode` rows, and a `HELD_NO_CODE` issue (REVIEW) is raised.
6. **Place platform money (recordings).** Lines are grouped by (ISRC, month); `_platform_row` picks the row:
   - an assigned ISRC goes to the assigned row;
   - with no candidate, a new `recording` row is made;
   - one candidate, several rows of the *same song* (a shared work number or the same base title), or
     `hold_shared_recordings=False`: the earliest row gets it;
   - otherwise the money goes to `hold:shared:{isrc}`, and a `SHARED_RECORDING` issue (REVIEW, action ASSIGN_HELD) is
     raised.

   Lines without an ISRC go to `hold:noisrc`. Each row records its "Match Basis" text, for example *"ISRC - catalogue
   (primary ISRC of the recording)"*.
7. **Usage-only recordings.** Plays are added to the matching rows. An ISRC in no row becomes a `usage` row.
8. **Rounding** (§11.8).
9. **Totals per row.** `royalty` = the sum of shown royalty cells; `platform[band]` per platform band. The **FY
   split**: each royalty cell is spread across Indian financial years (1 Apr – 31 Mar), weighted by month, over the
   period it was *earned* in (`fy_view = EARNED`), then penny-fixed to the row total. A cell with no period goes to
   "Period Not Stated". The row also gets its **status text** (§11.6).
10. **Order** (the SKV rule): by royalty descending, then each platform total descending, then title, then key.
11. **Findings** (only when there is a base): rows not in the base, of origin `work` or `recording`, that have cells.
    Each finding:
    - is matched to the newest review mark by any of its ISRCs or work numbers;
    - gets up to three **proposals** (§11.7).

    The top proposal, unless it is "unlikely", raises a `PROPOSAL` issue with the actions CONFIRM_MATCH,
    KEEP_SEPARATE and LATER. Unreviewed findings raise one `MISSING_UNREVIEWED` issue (action SET_STATUS). Findings
    are ordered unresolved first, then by money.
12. **Checks and totals** (§11.9).

### 11.3 Bands and columns

`_bands()` orders royalty sections by `rules.SECTION_ORDER`:

- YouTube Pre-Claims, YouTube Post-Claims, Facebook / Meta, Spotify, Apple Music, Radio, Zee TV Broadcast,
  Mechanical (MUSERK), Mechanical, Other / Unclassified, Redistribution;
- then any other section;
- then the Overseas sections (alphabetical; each takes the next colour of `OVERSEAS_CYCLE`).

Platform bands come **directly after the Spotify statement band** (`PLATFORM_AFTER`). A royalty band whose platform
also has a platform band is labelled "… ROYALTY DISTRIBUTED BY IPRS" to tell the two kinds of money apart. Colours are
the values measured from SKV8 (`rules.PALETTE`).

### 11.4 Holds

Held money is **counted in every total**: it is never lost and never guessed. It sits on its own row with a
`Held - …` status, and `totals.held_royalty`, `held_platform` and `held_rows` report it. It leaves the held row only
through a decision:

| Hold | Released by |
|---|---|
| `hold:shared` | `ASSIGN_HELD` |
| `hold:noisrc` | no decision path yet (see §24) |
| `hold:nocode` | no decision path yet (see §24) |

### 11.5 Base label and grain

- **Base label:** `"{CODE} list ({label})"` when a song list is in the run, else `"previous report ({generation})"`.
- **Grain** (shown in the summary):
  - *one row per song-list entry* (list only);
  - *one row per previous-report row* (a previous report);
  - *one row per work* (no base, statements);
  - *one row per recording* (no base, platform only).

### 11.6 Status text (column "Catalogue Status")

| Row | Text |
|---|---|
| held | `Held - <reason>` |
| in base, paid | `In <base> - royalty received` |
| in base, named with 0.00 | `In <base> - named in a statement, but the amount distributed was 0.00` |
| in base, sibling only | `In <base> - separate recording of an IPRS work paid on another row` |
| in base, platform only | `In <base> - platform revenue only, no royalty distributed in any of the N statements` |
| in base, nothing | `In <base> - no royalty distributed in any of the N statements` |
| not in base | `NOT in <base> - work paid by a royalty statement` / `… appears only in <platform>'s revenue report` / `… usage report` |
| no base at all | `No base - work / recording / usage only` |

Decision notes (linked, assigned) are appended after ` ; `.

### 11.7 Proposals (title matching, which only ever suggests)

For each finding, candidate base rows are found by an exact title key (`title_key`), a close one (`base_title`, which
drops brackets, quotes and version words) or a folded transliteration (`fold`: chh→ch, sh→s, aa→a, o→a, doubled
letters → one). Each candidate gets a score:

| Evidence | Weight (`RULESET_V1.proposal_weights`) |
|---|---|
| exact title | +0.30 (close title +0.15) |
| no other song on either side has this exact title | +0.20 |
| ISRC family: same first 7 characters, numeric suffixes within `isrc_family_gap` = 50 | +0.15 |
| same ISRC registrant (first 5 characters) | +0.05 |
| one title is a version (cover, lo-fi, remix, …) and the other is not | −0.50 |

Bands: `suggested` ≥ 0.70, `review` ≥ 0.40, else `unlikely`. Pairs that a `NOT_SAME` decision separated are skipped.
The three best are kept, each with a plain-language reason.

### 11.8 Penny-exact rounding (`names.penny_fix`)

Rounding the printed cells must not make any printed total a paisa off its source:

- **Statement column:** the exact cells are rounded to 0.01, and the gap to the rounded column total goes to the cells
  with the largest remainders (the largest-remainder method).
- **Platform report:** the month totals are penny-fixed to the report's rounded total first; then each month column's
  cells are fixed to its month total.
- **Prior columns** are printed as they were (rounded per cell).
- **FY split** per row: penny-fixed to the row's royalty.

### 11.9 Built-in checks (all blocking)

| ID | Check |
|---|---|
| I1 | every included statement: entries = printed total (± tolerance) |
| I4 | all statement money is in the report, once (placed = extracted, exact) |
| I4b | report total = the sum of the printed totals (± tolerance × statements) |
| I5 | per platform report: revenue in the report = the report's own total |
| I23 | each printed statement column adds up; each platform report's printed months add up to its total |
| I6 | FY columns add up to each row's total |
| I7 | (song list without a previous report) every list entry has exactly one row |
| I16 | no song on the missing list carries a code that is in the base |
| I13 | (previous report) previous money is carried unchanged, or the user accepted an edited base |
| I12 | no statement identity counts twice (raised as `BuildFailed`) |

`Result.ok` is false if any blocking check fails; `jobs.process` then fails the build.

---

## 12. Independent verification

[rd/verify.py](backend/mrm/rd/verify.py) recomputes the numbers **without the engine's grouping**. It walks every
source line by itself, finds the row(s) that may carry it by their codes, and compares:

| ID | Re-derivation |
|---|---|
| I18a | every royalty line, looked up by work number among non-sibling cells (or its `hold:nocode` row), lands on **exactly one** row with the same amount |
| I18b | every platform line, looked up by ISRC (held, then assigned, then the earliest row), lands on its row with the same amount |
| I23b | the Total Amount column = the sum of all royalty distribution columns |
| I23c | each `Total <Platform> Revenue` = the sum of its month columns |
| I6b | the sum of all FY cells = Total Amount |
| I18c | every companion-report amount, re-derived from the source lines by the group's own codes (within 0.01 × columns) |
| I16b | no song listed in a companion report carries a code that is in the base |

The `verify.master` results join the engine checks in stage 2. `verify.companion` runs while the reports are written,
and any failure raises, which fails the build. The same verification runs again at publish.

---

## 13. Review and decisions

### 13.1 Issues (`rd_issue`)

| Kind | Severity | Category | Actions | Effect of answering |
|---|---|---|---|---|
| `PROPOSAL` | REVIEW | MATCHING | CONFIRM_MATCH · KEEP_SEPARATE · LATER | a `LINK` (moves money) or `NOT_SAME` decision |
| `SHARED_RECORDING` | REVIEW | MONEY | ASSIGN_HELD (choose a candidate row) · LATER | an `ASSIGN_HELD` decision (moves money) |
| `ALREADY_IN_BASE` | BLOCKING | MONEY | ADD_AS_SEPARATE · LEAVE_OUT (platform reports: LEAVE_OUT only) | sets the file's run `choice` |
| `MISSING_UNREVIEWED` | REVIEW | MATCHING | SET_STATUS | statuses set on findings (§13.3) |
| `HELD_NO_CODE` | REVIEW | MONEY | none | information only |
| `TITLE_PLACED_IN_BASE` | INFO | MATCHING | none | information only |

`LATER` sets `rd_issue.later=TRUE`; the issue then stops counting towards "Needs your review".

### 13.2 Decisions (`rd_decision`)

- **Keyed by codes, owned by the client.** A decision is not tied to a run: it applies to every later build of that
  client.
- **Applies at once** (since 1.0.5). It is created `ACTIVE`, and the previous ACTIVE decision with the same
  `subject_key` and kind group becomes `SUPERSEDED`:

| Kind | subject_key | Moves money | Recorded with it |
|---|---|---|---|
| `LINK` / `NOT_SAME` (one group) | `{ISRC\|WORK}:{code}` | LINK yes, NOT_SAME no | `original` (paid title, codes and amounts; base title and codes), `evidence` (score, why), `reason` |
| `ASSIGN_HELD` | `ISRC:{code}` | yes | the candidate rows offered |
| `SONG_STATUS` | sorted ISRCs + work numbers joined by `\|` | no | status, the reviewer's original wording, note, source (review list row or build) |

A decision changes `inputs_sha256`. The money therefore moves only when the files are **processed again**, and the
UI says so ("Saved. Process the files again to move the money.").

### 13.3 Review statuses ([rules.py](backend/mrm/rd/rules.py))

| Code | Label | Typical free text that maps to it (`map_status`, Q5 default) |
|---|---|---|
| `NEW` | Not reviewed yet | (blank, "not reviewed") |
| `NEEDS_CHECK` | Needs check | "Please confirm if …", anything unrecognised |
| `IDENTIFIER_TO_UPDATE` | In song list - identifier to update | "need to update ISRC", "… to update" |
| `CONFIRMED_MISSING` | Confirmed missing - to register | "Need to register", "Ask for all … songs", "missing" |
| `ALREADY_IN_LIST` | Already in song list | "already linked", "Updated in SVF Report" |
| `NOT_OURS` | Not ours (belongs to someone else) | "Not SVF work", "belongs to someone else" |

`NEW` and `NEEDS_CHECK` count as unresolved. `NOT_OURS` decides membership of the out-of-scope report. Per business
decision Q4, there is no automatic "not ours" rule: only reviewers' statuses drive it.

---

## 14. Publishing

```mermaid
sequenceDiagram
  participant UI
  participant S as service.publish
  participant DB
  participant W as jobs.publish
  participant FS as object store

  UI->>S: POST /builds/{bid}/publish (after a confirm dialog)
  S->>DB: lock build FOR UPDATE; state must be CHECKED; no BLOCKING issues
  S->>DB: inputs_sha256 must equal the current one
  S->>DB: state=SUBMITTED, submitted_by = approved_by = actor; INSERT rd_job
  W->>DB: load_inputs again; inputs sha must still match (else PublishRefused)
  W->>DB: generation_no = max(settings.next_generation, max(generation_no)+1)
  W->>W: engine.build + verify.master again
  W->>W: royalty total must equal the CHECKED summary (else PublishRefused)
  W->>FS: write final reports (name = generation, no DRAFT suffix)
  W->>DB: advisory lock (84726101, client)<br/>earlier PUBLISHED → SUPERSEDED<br/>build → PUBLISHED, generation, published_at<br/>client.settings.next_generation = n+1
  W->>DB: audit build.published {generation, master_sha256, values_sha256}
```

- **Rebuilt, not copied.** The final reports are produced by building again from the same stored inputs. Because the
  output is deterministic, they match the validated draft except for the name and state labels. Any difference in the
  royalty total refuses the publication.
- **Refusal path.** On `PublishRefused`, or any error, the build goes back to `CHECKED`: `approved_by` is cleared and
  `returned_reason` holds the message the UI shows. Nothing is published.
- **Report numbers** are unique per client (`UNIQUE (client_id, generation_no)`) and increase from the client's
  `next_generation` (SVF starts at 9 after SKV8).

---

## 15. Report outputs

### 15.1 Master workbook ([excel.py](backend/mrm/rd/excel.py) `master`)

Sheet 1 is named after the generation (e.g. `SVF-RD-SKV9`):

```
row 1 │ (identity)            │ BAND: YOUTUBE PRE-CLAIMS (n distributions) │ … │ SPOTIFY - GROSS REVENUE … │ … │ ␣␣␣ │ TOTAL REVENUE (by Indian FY …) │ AUDIT / TRACEABILITY
row 2 │ ISRC │ Song Name │ Internal No │ Total Amount │ Total Spotify Revenue (MRM) │ Date │ Amount │ Period │ Distribution Number │ … │ FY 2024-25 │ … │ Total Revenue │ Catalogue Status │ Royalty Booked On │ Spotify (MRM) Match Basis │ Held / Flags
row 3…│ one row per song, sorted by the SKV rule
TOTAL │ column totals (shown totals), distribution numbers / periods
notes │ FY basis note; provenance note (generation, state, build, rule set, left-out files, decisions)
```

- **Formatting** (measured from SKV8):
  - money `#,##0.00`, dates `DD-MMM-YYYY`;
  - band fills with tinted data cells, striped identity columns, medium borders around bands;
  - freeze panes at `F3` (with platform bands) or `E3`, and an autofilter over the header row.
- **Run Summary** sheet:
  - a key-value header: client, report, state, build, who prepared, who published, rule set (version + sha prefix),
    software, grain, base, the royalty and platform totals, song rows, held rows, missing count;
  - tables: FILES USED (with a sha256 prefix), LEFT OUT (with the reasons), CHECKS (the engine checks), DECISIONS
    APPLIED, NOTICES.
- **`_rd_meta`** sheet (hidden): workspace, build, generation, rule-set version and sha, software version, grain,
  totals, `values_sha256`, then every `row_key → isrcs/work_nos` and `column_key → band/distribution/period`. When this
  report is uploaded as the next run's previous report, this sheet makes it `SKV_NATIVE`.
- **`values_sha256`** is a hash of every printed value. It is recorded at publish, so a published report can later be
  proven unchanged.

### 15.2 Companion reports (`companion_groups`, `companion`)

- **Grouping.** Findings are grouped so that one reviewed song is one line. A song whose review-list row carries both
  an ISRC and a work number has a royalty row and a recording row, and they become one group.
- **Missing Songs:** every finding group with its status.
- **Non-`<CODE>` Works:** the groups with status `NOT_OURS`.
- **Columns:** separate IPRS royalty and per-platform revenue columns, plus **"Total (Both Sources)"**
  (`companion_combined_total`, business decision Q1). That combined total exists only in the companion reports, never
  in the master.
- **When a report is unavailable,** it is still listed, with `available=FALSE` and a plain reason:
  - no base in the run: neither companion report can be made;
  - no `NOT_OURS` songs yet: the out-of-scope report.

### 15.3 Determinism (`excel.stable`)

The workbook properties get fixed dates (2000-01-01). The ZIP is rewritten with the entries sorted
(`[Content_Types].xml` first), every entry time set to 1980-01-01, and `dcterms:modified` fixed. The same `Result`
therefore always gives the same bytes and the same sha256.

### 15.4 Names, download, preview, bundle

| | Name |
|---|---|
| Draft | `SVF-RD-SKV9-DRAFT-{run}.{version}.xlsx` |
| Final | `SVF-RD-SKV9.xlsx`, `Missing-Songs-Revenue-SVF-RD-SKV9.xlsx`, `Non-SVF-Works-Revenue-SVF-RD-SKV9.xlsx` |
| Saved by the browser | `_<Person-Name>` is appended to the stem (`service.with_person`); every download is audited |
| Bundle | `GET /builds/{bid}/download-all` → `{generation}-reports_<Person>.zip`, holding the final reports, or the drafts when none are final |
| Preview | `GET /reports/{id}/preview?sheet=n`: the visible sheets, the first 300 rows × 60 columns as text (Indian digit grouping), the same permission checks as a download |

---

## 16. Background jobs and concurrency

### 16.1 Job loop ([rd/jobs.py](backend/mrm/rd/jobs.py))

```
_loop():  while run_one(): pass   →   sweep()   →   wait on _wake event (≤ 5 s)
run_one(): SELECT … FROM rd_job WHERE state='QUEUED' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
           → RUNNING (attempts+1, heartbeat)
           build QUEUED                         → process()
           build SUBMITTED and approved_by set  → publish()
           → job DONE / FAILED
sweep():   RUNNING jobs whose heartbeat is older than 20 min → FAILED; their QUEUED/RUNNING build → FAILED with a message
```

- **Survives the browser.** Processing does not depend on the request that started it.
- **Safe with several workers.** `SKIP LOCKED` means two processes never claim the same job. (`uvicorn --workers 2`
  with `RD_WORKER=thread` would run two worker threads; Compose avoids that with `RD_WORKER=off` and a dedicated
  `worker` service.)
- **Wake-up.** `jobs.wake()` only wakes a worker thread in the same process. The separate `worker` service notices new
  jobs within 5 seconds.

### 16.2 Locks and guards

| Mechanism | Key | Protects |
|---|---|---|
| `pg_advisory_lock(84726000)` | migrations | one migrator at a time |
| `pg_advisory_xact_lock(84726001)` | audit trigger | a strict hash-chain order |
| `pg_advisory_xact_lock(84726100, client)` | `start_build` | at most one QUEUED/RUNNING build per client |
| `pg_advisory_xact_lock(84726101, client)` | `jobs.publish` | the supersede + publish switch |
| `pg_advisory_xact_lock(84726200)` | sign-up | exactly one first administrator |
| `SELECT … FOR UPDATE` | `rd_run` in `delete_run`; `rd_build` in `publish` and `_delete_block` | one delete or publish at a time |
| `UNIQUE (client_id, generation_no)` | `rd_build` | no two reports with the same number |
| `UNIQUE (client_id, sha256)` | `rd_file` | each upload is stored once per client |

### 16.3 Measured cost

The full reference set (45 statements, 2 platform reports, the song list) takes about 30 s and about 500 MB in the
worker ([Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md) §10).

---

## 17. Audit log

- `audit.record(conn, action, actor, object_kind, object_id, detail)` inserts into `audit_event` **inside the same
  transaction** as the change it describes. Either both are saved or neither is.
- The `audit_chain` BEFORE INSERT trigger:
  1. takes advisory lock 84726001;
  2. sets `id` from `audit_event_seq` and `at = clock_timestamp()`;
  3. sets `prev_hash` to the previous row's `hash` (64 zeros for the first row);
  4. sets `hash = sha256(audit_canon(row))`, where `audit_canon` joins id | at (UTC, µs) | actor_id | actor | action |
     object_kind | object_id | detail | prev_hash.
- Updates and deletes are refused by a trigger, and `mrm_app` has no UPDATE/DELETE/TRUNCATE privilege on the table.
- **Verification:** `python -m mrm.cli verify-audit` (exit code 1 if broken), or Settings → Technical details. The
  check recomputes every hash and every link: an edit, a deletion or an out-of-order insert shows up as a broken id.

Since 1.1.0 every event made by a person also carries `actor_role` in its detail, and changes record `before` and
`after` states (never a password, hash, token or session secret). The Super Admin reads the log under Settings →
Activity log (`GET /audit?area=&q=&before=`, with the chain check); `GET /diagnostics` no longer returns events to
Admins.

Actions recorded:

| Area | Actions |
|---|---|
| Sign-in and accounts | `auth.signed_up`, `auth.signed_in`, `auth.signed_out`, `auth.failed` (with the reason: unknown email, wrong password, switched off, deleted), `user.created`, `user.updated`, `user.role_changed`, `user.deactivated`, `user.reactivated`, `user.deleted`, `user.profile_updated`, `user.name_changed` |
| Security (1.1.0) | `security.password_reset`, `security.sessions_revoked`, `security.super_admin_recovery` |
| Catalogue (1.1.0) | `catalogue.import_previewed`, `catalogue.import_applied`, `catalogue.import_discarded`, `catalogue.work_updated`, `mapping.created`, `mapping.verified`, `mapping.rejected`, `mapping.pending`, `mapping.corrected` |
| Statements (1.1.0) | `statement.uploaded`, `statement.answered`, `statement.updated`, `statement.superseded`, `statement.original_downloaded` |
| Reconciliation and enquiries (1.1.0) | `recon.run_completed`, `recon.item_reviewed`, `recon.exception_updated`, `enquiry.created`, `enquiry.<event>` (review_requested, approved, returned_for_correction, manually_sent, response_received, follow_up_sent, resolution_recorded, closed, withdrawn, assigned, new_statement_reviewed, …), `enquiry.correction_noted`, `enquiry.follow_up_scheduled`, `enquiry.follow_up_updated` |
| Settings (1.1.0) | `settings.reconciliation_changed`, `settings.iprs_currency_changed`, `platform.created`, `platform.alias_added` |
| Exports (1.1.0) | `export.catalogue`, `export.catalogue_import_report`, `export.statement_error_report`, `export.records`, `export.master_view`, `export.master_statement`, `export.reconciliation_report`, `export.enquiry_annex` |
| Clients | `client.created`, `client.updated` |
| Runs | `run.created`, `run.closed`, `run.deleted` |
| Files | `file.uploaded`, `file.reused`, `file.answered`, `file.kind_chosen`, `file.choice`, `file.removed_from_run` |
| Review | `review.imported`, `review.status`, `review.later`, `decision.link`, `decision.not_same`, `decision.assign_held` |
| Builds | `build.queued`, `build.checked`, `build.failed`, `build.publish_requested`, `build.published`, `build.publish_refused`, `build.publish_failed` |
| Reports | `report.downloaded` |

---

## 18. Frontend

### 18.1 Stack

React 18.3, TypeScript 5.9, Vite 6, TanStack Query 5. There is no router library and no UI kit: the primitives are in
[ui.tsx](frontend/src/ui.tsx), and the styles in one stylesheet, [styles.css](frontend/src/styles.css), with light and
dark tokens. The production build (`tsc --noEmit && vite build`) is served by nginx; `/assets/` is cached as
immutable for a year and `index.html` is served `no-cache`.

### 18.2 Structure

| File | Responsibility |
|---|---|
| [main.tsx](frontend/src/main.tsx) | applies the theme, creates the `QueryClient` (no refetch on focus, retry once on 5xx or network errors, staleTime 5 s), mounts `Root` |
| [App.tsx](frontend/src/App.tsx) | `Root`: loads `/auth/me` → `Login` (sign in / create account) or `Shell` (top bar, nav, page, footer `V{__APP_VERSION__}`, `WhatsNew`) |
| [session.tsx](frontend/src/session.tsx) | `Me` type; `AppProvider` context (`me`, `route`, `go`, `toast`, `signOut`, `refreshMe`); hash routing `useRoute`; `local` (localStorage wrapper for per-person conveniences only) |
| [api.ts](frontend/src/api.ts) | `fetch` wrapper: same-origin cookie, `X-CSRF-Token` on non-GET, `ApiError(status, detail)`; a 401 fires `mrm:signed-out`, which returns the app to the sign-in page; `download()` saves a blob under the server's filename |
| [types.ts](frontend/src/types.ts) | the API response shapes; money is decimal **text** |
| [format.ts](frontend/src/format.ts) | display formatting (₹, Indian grouping, dates) |
| [ui.tsx](frontend/src/ui.tsx) | Page, Card, Pill, statuses, Money, Button, DownloadButton, More (details panel), Notice, Steps, PasswordField, Dialog, a custom `Select` (keyboard: arrows, Enter, Esc, type-ahead) |
| [theme.tsx](frontend/src/theme.tsx) | light/dark: follows the system until the person chooses; the choice is remembered in localStorage |
| [ProfileMenu.tsx](frontend/src/ProfileMenu.tsx), [WhatsNew.tsx](frontend/src/WhatsNew.tsx), [DeleteRun.tsx](frontend/src/DeleteRun.tsx), [ReportPreview.tsx](frontend/src/ReportPreview.tsx) | the initials menu; the one-time release note (`POST /me/seen`); the delete-run dialog; the report preview (columns A–B frozen) |

### 18.3 Routes (hash-based)

| Hash | Page | Notes |
|---|---|---|
| `#/` | [Home](frontend/src/pages/Home.tsx) | the next step, catalogue and statement counts, recent reconciliations, enquiry queues, my follow-ups (`GET /overview`, every 30 s) |
| `#/catalogue/{works\|conflicts\|import\|history}` , `#/catalogue/import/{id}` | [Catalogue](frontend/src/pages/Catalogue.tsx) | works and links (work pop-up: verify, reject, move, link an ISRC), conflicts, import preview and apply, import history |
| `#/statements[/{id}]` | [Statements](frontend/src/pages/Statements.tsx) | upload (received from client / IPRS), the library, one statement (questions, facts, matching, records), records export |
| `#/master[/unmatched]` | [Master](frontend/src/pages/Master.tsx) | works × platforms with filters, the lines behind an amount, unmatched money, view export, master statement export |
| `#/reconciliation[/{runId}]` | [Reconciliation](frontend/src/pages/Reconciliation.tsx) | start a run (platform, suggested periods, calculation basis), earlier runs; a run's notes, exception tiles, items, item pop-up, enquiry draft, report export |
| `#/enquiries[/{id}]` | [Enquiries](frontend/src/pages/Enquiries.tsx) | queue tiles, open follow-ups, list; one enquiry: allowed actions, draft text, items, follow-ups, communications, history |
| `#/process` | [Process](frontend/src/pages/Process.tsx) → `SelectClient` | step 1: choose or add a client, create a run |
| `#/process/{runId}` | `RunWizard` | steps 2–6 |
| `#/reports` | [PastReports](frontend/src/pages/PastReports.tsx) | published versions (and drafts for preparers), preview, delete a never-published run |
| `#/clients[/new]` | [Clients](frontend/src/pages/Clients.tsx) | the list and the add/edit dialog (holders, prefix, next number, distributors) |
| `#/settings/{tab}` | [Settings](frontend/src/pages/Settings.tsx) | My profile · People and access (Admins) · Reconciliation (benchmark; the Super Admin edits) · Platforms · Clients · Activity log (Super Admin) · Technical details (Admins) · Help |

The top bar has eight entries (Home, Catalogue, Statements, Master, Reconciliation, Enquiries, Reports, Settings); the
client picker appears next to the profile button only when a person sees more than one client (remembered per
browser). A person with a temporary password sees only the change-password screen.

### 18.4 The run wizard

`naturalStep(run, build)` derives the current step from **server state**. Nothing about the run's progress is kept in
the browser:

| Condition | Step |
|---|---|
| no files | Upload files |
| files but no build | Check files |
| latest build QUEUED / RUNNING / FAILED | Process data (stage progress) |
| CHECKED with open REVIEW/BLOCKING issues (not "later", no decision) | Review results |
| otherwise | Download reports (preview, publish) |

The person can look at an earlier step (`view`). The view resets when a new build starts or the build changes state.

**Polling:** the run every 2 s while it is PROCESSING; the build every 1.5 s while it is QUEUED, RUNNING or
publishing.

**Read-only mode:** a person without `prepare` sees the steps and files, with a note that they are following the run.

The Review step ([Results.tsx](frontend/src/pages/Results.tsx)) shows the issues as queues with their actions, and the
findings list with filters, search and bulk status. A `ChangesBanner` appears when `changed_since_build` is true and
offers to process again. **Publish Reports** is enabled only when `can_publish` is true and nothing has changed since
the build.

---

## 19. HTTP API reference

All paths are under `/api`. **Auth** means a session cookie is needed; non-GET requests also need `X-CSRF-Token`.

| Method | Path | Capability | Purpose |
|---|---|---|---|
| GET | `/health` | none | DB ping + version |
| GET | `/auth/options` | none | `{signup, version}` for the sign-in page (`signup` only while there is no Super Admin) |
| POST | `/auth/signup` | none (if `ALLOW_SIGNUP` and no Super Admin yet) | create the first account (Super Admin), then sign in |
| POST | `/auth/login` | none | sign in; sets the cookie; returns `me` |
| POST | `/auth/logout` | none | revoke the session, clear the cookie |
| GET | `/auth/me` | auth | identity, roles, `can`, clients, version, `whats_new`, csrf |
| POST | `/me/seen` | auth | mark the current release note as read |
| PATCH | `/me` | auth | change the name, or the password (needs the current one; revokes other sessions) |
| GET | `/home` | view | the Home data |
| GET | `/past-reports?client_id=` | view | published (and, for preparers, draft) versions |
| GET | `/clients` | view | the clients this person sees |
| POST | `/clients` | clients | add a client (the adder is granted it) |
| PATCH | `/clients/{cid}` | clients (`active` needs manage) | edit the settings and holders, switch off |
| GET | `/runs?client_id=` | view | open runs (50) |
| POST | `/runs` | prepare | create a run `{client_id, title?}` (titles made unique) |
| GET | `/runs/{rid}` | view | the run view: files, issues, blocked, builds, state, can_delete |
| POST | `/runs/{rid}/close` | prepare | archive |
| DELETE | `/runs/{rid}` | prepare | soft-delete a never-published run |
| POST | `/runs/{rid}/files` | prepare | multipart `files[]`; a result per file (`file`, `note`, or `error`) |
| POST | `/runs/{rid}/files/{fid}/answer` | prepare | `{answers: {field: value}}`, or `{kind}` for an unknown file |
| POST | `/runs/{rid}/files/{fid}/choice` | prepare | `{choice: SUPPLEMENTARY \| LEAVE_OUT \| USE}` |
| DELETE | `/runs/{rid}/files/{fid}` | prepare | remove from the run (the file stays stored) |
| GET | `/files/{fid}/details` | view (`facts` for preparers and admins) | everything detected about a file |
| POST | `/runs/{rid}/process` | prepare | queue a build |
| GET | `/builds/{bid}` | view | the build view: stages, summary, checks, issues, reports, can_publish |
| GET | `/builds/{bid}/findings?status=&q=&offset=` | view | paid-not-in-base songs (200 per page) with counts |
| POST | `/builds/{bid}/issues/{no}/act` | prepare | `{action, row_key?, reason?}` |
| POST | `/builds/{bid}/findings/status` | prepare | `{findings: [no…], status, note?}` |
| POST | `/builds/{bid}/publish` | prepare | request publication |
| GET | `/reports/{id}/download` | view (drafts: draft_download) | the workbook |
| GET | `/reports/{id}/preview?sheet=` | as download | the first rows as text |
| GET | `/builds/{bid}/download-all` | as download | a ZIP of the build's reports |
| GET | `/diagnostics` | diagnostics | failed builds, jobs, the rule set, the storage path (+ the last 200 audit events and the chain check for the Super Admin) |
| GET / POST | `/people` | manage | list (`?include_deleted=`) / create a User or Admin (temporary password generated when none is given; returned once) |
| PATCH / DELETE | `/people/{uid}` | manage | name, role (USER/ADMIN), client grants, active / soft delete — never the Super Admin, never oneself |
| POST | `/people/{uid}/reset-password` | reset_passwords | issue a temporary password (returned once), revoke sessions |
| POST | `/people/{uid}/revoke-sessions` | reset_passwords | sign the account out everywhere |
| GET | `/assignees` | auth | active people (names) for assignment |
| GET | `/audit?area=&q=&before=` | audit | the activity log (200 per page) and the chain check |
| GET / POST | `/platforms`, `/platforms/{pid}/aliases` | view / platforms | platforms with their aliases; add a platform or a source spelling |
| GET | `/overview?client_id=` | view | the Home dashboard |
| GET | `/catalogue/works?client_id=&q=&status=&mapping=&offset=` | view | works with their current links (100 per page) and catalogue counts |
| GET / PATCH | `/catalogue/works/{wid}` | view / verify_mappings | a work with its links (current and closed), rivals and history / edit title, status, work number |
| POST | `/catalogue/works` | prepare | add a work outside an import (number optional → TO_REGISTER; its ISRC links PENDING) |
| POST | `/catalogue/link-isrc` | prepare | link an ISRC to the work with a given IPRS work number (from an unmatched revenue line) |
| POST | `/catalogue/works/{wid}/links` | prepare | link an ISRC by hand (PENDING; VERIFIED when an Admin asks; CONFLICT when another work has it) |
| POST | `/catalogue/links/{mid}/status`, `/catalogue/links/{mid}/move` | verify_mappings | verify / reject / reopen a link; move it to another work (old link closed) |
| GET | `/catalogue/conflicts?client_id=` | view | ISRCs claimed by more than one work |
| GET | `/catalogue/export?client_id=` | view | the catalogue workbook (works sheet in the song-list layout + links sheet) |
| GET / POST | `/catalogue/imports`, `/catalogue/imports/from-file` | view / prepare | import history / upload a catalogue (multipart `file`, `client_id`) or preview a stored song list |
| GET | `/catalogue/imports/{iid}?status=&action=&q=&offset=` | view | the preview: counts and rows (200 per page) |
| POST | `/catalogue/imports/{iid}/apply`, `/discard` | prepare | apply (`verify_mappings`) or discard a preview |
| GET | `/catalogue/imports/{iid}/report` | view | rows not applied as they stand (Excel) |
| GET / POST | `/statements` | view / prepare | the library (filters) / upload statements (multipart `files[]`, `client_id`, `source`) |
| GET / PATCH | `/statements/{sid}` | view / prepare | facts, questions, problems, matching summary, related statements / who sent it, payment date |
| POST | `/statements/{sid}/answer` | prepare | `{answers}`: metadata fields or `relation` (CORRECTION / SUPPLEMENTARY / LEAVE_OUT) |
| GET | `/statements/{sid}/records`, `/error-report`, `/original` | view | the lines (200 per page) / error report / the original file (re-hashed before sending) |
| GET | `/records/export?client_id=&record_type=&platform_id=&period_from=&period_to=&statement_id=&mapping=&q=` | view | filtered revenue or IPRS records (Excel) |
| GET | `/master?client_id=&platform_id=&period_from=&period_to=&statement_id=&q=&status=&mapping=&money=&sort=&offset=` | view | the master view (100 works per page, totals for all pages, unmatched money) |
| GET | `/master/works/{wid}/sources`, `/master/unmatched` | view | the lines behind a work's amounts / money that reaches no work |
| GET | `/master/export`, `/master/export-statement` | view | the filtered view (Excel) / the master statement in the SKV layout |
| GET / POST | `/reconciliation/settings` | view / settings | the basis in force and its history / save new values (with a reason) |
| GET | `/reconciliation/options?client_id=` | view | platforms with their statements and suggested periods |
| GET / POST | `/reconciliation/runs` | view / prepare | runs / start a run `{client_id, platform_id, period_from, period_to}` |
| GET | `/reconciliation/runs/{rid}`, `/items?…`, `/report?…` | view | a run (notes, exception counts, later statements) / items (filters, sort, 100 per page) / the report (Excel) |
| GET / POST | `/reconciliation/items/{iid}`, `/review` | view / prepare | an item with its sources, exceptions, later statements, enquiries / review it |
| POST | `/reconciliation/items/{iid}/addressed` | prepare | a later statement, payment or adjustment already addressed it: evidence recorded, exceptions closed, item reviewed |
| POST | `/reconciliation/exceptions/{eid}` | prepare (assign: assign_followups) | resolve / dismiss (note required) / assign |
| GET | `/enquiries/dashboard`, `/enquiries?status=&q=&mine=&queue=` | view | queue counts and open follow-ups / the list |
| POST | `/enquiries` | prepare | a draft from run items `{client_id, run_id, item_ids, later_reviewed}` |
| GET / PATCH | `/enquiries/{eid}` | view / prepare | detail with allowed actions / edit the draft or remove an item (drafts only) |
| POST | `/enquiries/{eid}/act` | per action (§26.6) | a workflow step `{action, …}` |
| POST / PATCH | `/enquiries/{eid}/actions`, `/enquiry-actions/{aid}` | prepare (others' / dates: assign_followups) | add / change or complete a follow-up |
| GET | `/enquiries/{eid}/annex` | view | the internal working paper (Excel) |

The interactive description is at `/api/docs` (only when `API_DOCS=true`, the default outside production).

---

## 20. Configuration reference

**Backend** (`backend/.env`; template [backend/.env.example](backend/.env.example)):

| Variable | Default (no file) | Meaning |
|---|---|---|
| `APP_ENV` | `development` | `production` refuses weak DB passwords and hides the API docs |
| `API_DOCS` | true unless production | `/api/docs`, `/api/openapi.json` |
| `DATABASE_URL` | `postgresql://mrm_app:devpass@127.0.0.1:55433/mrm` | the application login |
| `MIGRATOR_DATABASE_URL` | `DATABASE_URL` with `mrm_owner` | the migration login |
| `DB_POOL_SIZE` | 10 | the maximum pool size per process |
| `POSTGRES_PASSWORD`, `MRM_OWNER_PASSWORD`, `MRM_APP_PASSWORD` | none | read by the db container when its volume is first created ([init.sh](deploy/postgres/init.sh)). Changing them later needs `ALTER ROLE` first. |
| `STORAGE_ROOT` | `./data/objects` (Compose: `/data/objects`) | the object store root |
| `ALLOW_SIGNUP` | true | the first-account set-up on the sign-in page (only while there is no Super Admin) |
| `SESSION_HOURS` | 10 | session lifetime |
| `LOGIN_MAX_FAILURES` | 8 | failures per email per 15 min before `429` |
| `COOKIE_SECURE` | auto | `true` behind HTTPS, `false` for local HTTP only |
| `MAX_UPLOAD_MB` / `MAX_UNZIPPED_MB` / `MAX_CELLS` / `MAX_SHEETS` / `MAX_ZIP_RATIO` | 64 / 512 / 2,000,000 / 100 / 200 | upload limits |
| `LOG_LEVEL` | INFO | Python logging |
| `RD_WORKER` | `thread` (Compose api: `off`) | `thread` = an in-process worker thread |
| `ENV_FILE` | `backend/.env` | another file, or `none` |

**Compose** (the root `.env`, template [.env.example](.env.example)): `WEB_BIND` (127.0.0.1), `WEB_PORT` (8080).

**Frontend dev:** `API_URL` (Vite proxy target, default `http://127.0.0.1:8000`; use `:8010` on the development
machine).

Numbers that change a *result* (tolerance, weights, policies) are deliberately **not** settings: they live in the
versioned rule set (§22).

---

## 21. Build, deploy and operate

### 21.1 Commands ([cli.py](backend/mrm/cli.py))

| Command | Does |
|---|---|
| `python -m mrm.cli migrate` | waits for the DB, applies pending migrations as `mrm_owner` |
| `python -m mrm.cli seed` | creates client SVF (IPRS member 5154290, IPI 00871526032) and its settings; idempotent |
| `python -m mrm.cli bootstrap` | migrate + seed (the Compose `bootstrap` service) |
| `python -m mrm.cli worker` | runs the job loop forever |
| `python -m mrm.cli create-user EMAIL NAME ROLE PASSWORD --clients SVF` | creates a person: `SUPER_ADMIN` (only when there is none), `ADMIN` or `USER` |
| `python -m mrm.cli recover-super-admin EMAIL --reason "…" [--demote-current]` | exceptional recovery: makes an existing account the Super Admin (and optionally the current one an Admin), audited as `security.super_admin_recovery` |
| `python -m mrm.cli verify-audit` | checks the audit hash chain |

### 21.2 Production stack

```bash
cp backend/.env.example backend/.env && chmod 600 backend/.env   # strong random passwords (16+ chars)
docker compose up -d --build                                     # db → bootstrap → api + worker → web
```

Back up `pgdata` and `objects` together. The procedure is in
[Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md) §14, and the pre-production checklist in §13.

### 21.3 Migrations ([migrate.py](backend/mrm/migrate.py))

- Plain SQL files in `backend/mrm/migrations/`, applied in file-name order, each in its own transaction, under
  advisory lock 84726000.
- `schema_migrations(version, sha256, applied_at)` records each one. **If an applied file changes, startup fails**
  ("add a new file instead").
- Grants to `mrm_app` are written inside the migrations and are conditional on the role existing.

| File | Content |
|---|---|
| `0001_schema.sql` | people, sessions, `client`, the audit table, and the comparison module's tables (unused, §7.6) |
| `0002_controls.sql` | the audit hash chain, append-only and frozen-state triggers, `mrm_app` grants |
| `0003_rd_platform.sql` | the platform: holders, grants, files, lines, runs, builds, issues, findings, reports, decisions, jobs, guards, RLS |
| `0004_profile.sql` | `app_user.seen_version` |
| `0005_run_delete.sql` | the run `DELETED` state + `deleted_at` / `deleted_by` |
| `0006_no_approval.sql` | removes maker≠checker; pending approvals applied; approver/sender → viewer; role CHECK updated |
| `0007_three_roles.sql` | `app_user.role` (SUPER_ADMIN / ADMIN / USER) mapped from the old roles, `must_change_password`, `created_by`, `updated_at`, soft delete; the `super_admin_guard` trigger |
| `0008_reconciliation.sql` | platforms and aliases, works, recordings, work_recordings (+ history), catalogue imports, the statement registry, reconciliation settings / runs / items / sources / exceptions, enquiries and their items / events / actions / communications, the record views, guards, RLS and grants (§26) |

### 21.4 Releasing a version

Do all of these in one change:

1. Bump `backend/mrm/__init__.py` `__version__`.
2. Bump `frontend/package.json` `version`; the footer reads it through `__APP_VERSION__`.
3. Add a new **first** entry to `backend/mrm/releases.py` `RELEASES`. The first entry must be the running version:
   `unseen()` uses it to show each person the notes they have missed.
4. Update the version mentioned in [README.md](README.md).

A test used to check that these agree; it was removed with the other tests on 10 October 2026, so check it by hand.

### 21.5 Verifying a change (there are no automated tests)

The automated tests and the earlier comparison module were removed on 10 October 2026 (still in git, commit
`78a205d`). Until tests return, check a change by:

1. Running the API against an **empty development database** (`mrm-devdb` on `127.0.0.1:55433`, with
   `ENV_FILE=none`) and uploading the reference inputs from `Docs/input/`.
2. Comparing the totals with the reference outputs in `Docs/output/`.
3. Recreating the development database empty afterwards.

---

## 22. Rule set and versioning

[rules.py](backend/mrm/rd/rules.py) `RULESET_V1` is the **only** place for values that change a number or a
classification:

```python
{"version": 1, "recon_tolerance": "0.05", "name_link_policy": "suggest", "title_similarity": "0.90",
 "isrc_family_gap": 50, "hold_shared_recordings": True, "companion_combined_total": True, "fy_view": "EARNED",
 "proposal_weights": {...}, "proposal_bands": {"suggested": "0.70", "review": "0.40"}}
```

- Every build records `ruleset_version` and `ruleset_sha256` (sha256 of the sorted JSON). The rule-set sha is part of
  `inputs_sha256`, so a rule change invalidates every validated-but-unpublished build.
- **Changing any value is a new version.** Add `RULESET_V2`, switch the references to it (`service`, `jobs`), and
  leave V1 intact so that old builds stay explainable.
- Other fixed vocabularies in `rules.py`: the review statuses and `map_status`, `SECTION_ORDER`, `PLATFORM_AFTER`,
  `OVERSEAS_SOCIETIES`, and the measured SKV colours.

---

## 23. Extension guide

| To add… | Touch |
|---|---|
| **A statement category** (new IPRS distribution type) | `names._category_from_text` (file-name keyword), maybe `names.category_from_footer`; `rules.SECTION_ORDER` + `PALETTE` (colours); `detect.CATEGORIES` (the answer options) |
| **An overseas society** | `rules.OVERSEAS_SOCIETIES` (`code: (name, country)`) |
| **A platform** | `names.PLATFORM_WORDS`; the client's `settings.distributors` (name, currency, basis) through Clients → Edit |
| **A column heading variant** in song lists or platform reports | `parsers.TITLE_H`, `WORK_H`, `ISRC_H`, `MONTH_H`, `REV_H`, `USE_H`, `STATUS_H`, … |
| **A new file kind** | `model.py` (constant + label); `parsers.py` (reader → dataclass); `detect._identify_sheets` (where it sits in the detection order) + `facts_of` + an `_eval_*`; `store.save_data` / `load_data` (+ a migration: table, `refuse_change` trigger, RLS policy, `mrm_app` grant); `assemble.py`; the engine input; `jobs.load_inputs` |
| **A review status** | `rules` constants, `STATUS_LABEL`, `STATUS_ORDER`, `map_status`; `engine` status ranks |
| **A rule or weight change** | a new `RULESET_Vn` (§22) |
| **A table holding client data** | a new migration: `client_id` column, `ENABLE ROW LEVEL SECURITY` + a `client_scope` policy, the right `mrm_app` grants, a guard trigger if it is evidence; always access it through `access.tx` |
| **A capability** | `access.CAN` + `WHY`; it appears in `/auth/me` `can` automatically; check it in the service with `access.require` |
| **An API endpoint** | `routes_rd.py` (thin) → `service.py` (role check, `access.tx`, audit, plain return); return with `deps.J` so money stays exact |
| **A release** | §21.4 |

---

## 24. Known limitations, technical debt and doc drift

**Limitations by design in this release** (details in [Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md)
§10):

- One rights holder per run.
- INR only: no exchange rates.
- A statement outside the tolerance cannot be "accepted with a difference".
- An earlier distribution cannot be replaced.
- A previous report's platform columns are assumed gross.
- No screen to revoke a decision: only superseding it with a newer one.
- No SSO/MFA, no separate audit database, no antivirus scan, no object lock, no nightly re-verification of published
  builds.

**Limitations of the 1.1.0 reconciliation platform:**

- A reconciliation compares one platform and one usage period at a time; IPRS statements whose period only partly
  overlaps are left out (never prorated). Territory is compared only where a statement states one.
- The benchmark is calculated only when the client interest is set (§26.8). Since 1.2.0 the screen edits the
  client-wide value and, per platform, either "use the client-wide value" or a value of its own (§27).
- Statement intake recognises the IPRS standard/overseas layouts and per-ISRC revenue reports (any column names the
  parsers know, §23). Other client statement formats need a parser (the "adapter" of the brief): add it to `parsers.py`
  / `detect.py` as in §23.
- No email integration: enquiries are sent by people outside the application and recorded by hand; there are no
  automatic reminders beyond the due/overdue queues on the dashboard.
- A historical IPRS-versus-IPRS comparison is not a feature (the data for it is kept).
- The sum shown in the master view's footer and unmatched notice is added in the browser from exact strings (display
  only); every export and stored figure is exact.
- Still no automated tests: 1.1.0 was verified with an end-to-end script against a development database (§26.5–26.7)
  and by running migrations 0007–0008 on a copy of the live database.

**Observed in the code:**

| # | Item | Where |
|---|---|---|
| 1 | **No automated tests** (removed on 10 Oct 2026). The pure modules (`engine`, `verify`, `parsers`, `names`, `excel`) are the natural first target again: `assemble.py` already lets them run without a database. | §21.5 |
| 2 | **The "suggested" proposal band cannot be reached** with the V1 weights: the best case is 0.30 + 0.20 + 0.15 = 0.65 < 0.70, so every proposal is `review` or `unlikely`. This has no effect on money (a proposal never moves money), but the band is dead. Fixing it means a new rule-set version. | `rules.RULESET_V1`, `engine._proposals` |
| 3 | **Held money without a code has no decision path.** `HELD_NO_CODE` has no actions, and `hold:noisrc` raises no issue, so this money stays held (and counted) until the source file is corrected. Only `hold:shared` can be resolved in the UI (ASSIGN_HELD). | `engine` steps 5–6 |
| 4 | **Platform-month overlap with the previous report is checked only in the engine.** `run_checks` covers statements only, so a platform overlap is found only after processing (a BLOCKING `ALREADY_IN_BASE`, which the build view shows). | `service.run_checks`, `engine._not_already_in_base` |
| 5 | **`BuildFailed` (I12) is reported as a generic error.** `jobs.process` catches it as an ordinary exception, so the user sees "Something went wrong"; the real message is in `error_detail` (administrators only). In practice `run_checks` stops this case earlier. | `jobs.process` |
| 6 | Unused schema: the comparison-module tables (§7.6), the `packs` bucket, and in `rd_decision` the `checked_by`/`checked_at`/`check_note` columns and the `WAITING_APPROVAL`/`REJECTED`/`REVOKED` states (no current code path; `approved_by` holds the publisher). | migrations 0001, 0003, 0006 |
| 7 | A state-changing request loads the session twice (once in the CSRF middleware, once in `deps.actor`): two small queries per request. | `api/app.py`, `api/deps.py` |
| 8 | FastAPI `@app.on_event("startup")` is deprecated in favour of lifespan handlers. It still works. | `api/app.py` |
| 9 | The stale-job sweep relies on heartbeats, which are written per *stage*. A single stage longer than 20 minutes would be marked failed. The measured worst case is about 30 s. | `jobs.STALE_MINUTES` |
| 10 | The version must be kept in step in 3–4 places by hand (§21.4). | |

**Doc drift.** These documents were written before 1.0.5 and still describe things that are gone:

| Document | Says | Reality since |
|---|---|---|
| [Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md) §3–4 | an approval step, the Approver role, maker ≠ checker constraints, money-moving decisions needing a checker | 1.0.5: the preparer publishes; the constraints were dropped (0006) |
| same §3 | `LEGACY_COMPARISON` / `/api/compare` | 10 Oct 2026: the comparison module was removed |
| [README.md](README.md) "Layout" | migrations 0001–0005 | updated in 1.1.0 |
| [Docs/RELEASE-1-SYSTEM-GUIDE.md](Docs/RELEASE-1-SYSTEM-GUIDE.md) §3 | five roles (admin, importer, …), self sign-up as Viewer | 1.1.0: three roles, accounts created by Admins (§6.2) |

(The user asked for `Docs/` to be left unchanged when 1.0.5 shipped. This document is the current reference.)

---

## 25. Glossary

| Term | Meaning |
|---|---|
| **IPRS** | Indian Performing Right Society, which issues the royalty statements |
| **Work / work number** | a composition; the IPRS internal work number (`WORK INT NO`). Statement money attaches to it. |
| **ISRC** | International Standard Recording Code: one recording. Platform money attaches to it. |
| **Distribution** | one IPRS payment (e.g. `P2550`), i.e. one statement file → one 4-column block in the master |
| **SKV layout / generation** | the master workbook format measured from `SVF-RD-SKV8.xlsx`; each published version is the next generation (`SKV9`, …) |
| **Base** | what "ours" means in a run: the song list and/or the previous master report |
| **Finding** | a song that was paid but whose codes are not in the base (the Missing Songs population) |
| **Hold / held row** | money that cannot be placed by codes alone; counted in totals, waiting for a decision |
| **Book once / sibling** | a work claimed by several rows is paid on one owner row; the others carry an empty sibling cell |
| **Proposal** | a title-based suggestion that a finding is a base song; never moves money by itself |
| **Decision** | a person's answer, keyed by codes and owned by the client: LINK, NOT_SAME, ASSIGN_HELD, SONG_STATUS |
| **Build** | one processing of a run (versioned); CHECKED = validated draft; PUBLISHED = final, frozen |
| **Run** | a working set of uploaded files for one client |
| **Supplementary** | the user confirmed that a statement overlapping another (or the previous report) is a separate payment |
| **FY** | Indian financial year, 1 April – 31 March |
| **Gross / Net** | platform revenue before / after the distributor's fee (MRM's Spotify report: INR gross) |
| **Rule set** | `RULESET_V1`: the versioned, hashed values that change results |

---

## 26. Reconciliation platform (1.1.0)

### 26.1 What it adds, and the rules it keeps

| Module | Code | Screen |
|---|---|---|
| Catalogue: works, ISRCs, links, imports | [rd/catalogue.py](backend/mrm/rd/catalogue.py) | Catalogue |
| Statement library | [rd/library.py](backend/mrm/rd/library.py), [rd/intake.py](backend/mrm/rd/intake.py) | Statements |
| Platforms | [rd/platforms.py](backend/mrm/rd/platforms.py) | Settings → Platforms |
| Master view and exports | [rd/master.py](backend/mrm/rd/master.py), [rd/xlsx.py](backend/mrm/rd/xlsx.py) | Master |
| Reconciliation | [rd/recon.py](backend/mrm/rd/recon.py) | Reconciliation |
| Enquiries and follow-up | [rd/enquiries.py](backend/mrm/rd/enquiries.py) | Enquiries |
| Accounts and the activity log | [people.py](backend/mrm/people.py) | Settings → People and access, Activity log |
| Home dashboard | [rd/overview.py](backend/mrm/rd/overview.py) | Home |
| Routes | [api/routes_recon.py](backend/mrm/api/routes_recon.py), [api/routes_admin.py](backend/mrm/api/routes_admin.py) | |

The principles of §2 hold unchanged (exact money, missing ≠ zero, money moves only through codes, evidence never
changes, every action audited, client isolation). In addition:

- **Content decides what a statement holds; the uploader says who sent it.** IPRS distribution statements (`WORK INT
  NO … ROYALTY AMT`) hold *work royalties*; MRM-style reports (`Month, ISRC, Revenue`) hold *sound-recording revenue*.
  The reference files `(S-6)`, `(S-10)` and `(S-24)`, described in the brief as client statements, are IPRS statements
  by content (forwarded by the client): they are stored as `statement_source = CLIENT`, `record_type = WORK_ROYALTY`.
  The client's sound-recording revenue for the proof of concept is `Raw_Spotify_MRM_Oct25_Mar26.xlsx`.
- **No allegation.** The benchmark and the variance are *indicative* everywhere they appear. A missing IPRS line is
  NULL with the exception "No corresponding IPRS entry found in the statements uploaded.", never 0. Nothing is sent to
  IPRS by the application.
- **No guessing.** An unknown client interest, an unclear revenue basis, a currency difference or an incomplete usage
  period stops the calculation for the items concerned and says why; 100 % is never substituted.
- **One record of truth.** Normalised records are views over the immutable source lines; master totals are summed
  from them on every read; nothing is stored twice.

### 26.2 Data model (migration 0008)

```mermaid
erDiagram
  client ||--o{ works : ""
  works ||--o{ work_recordings : "links (history kept)"
  recordings ||--o{ work_recordings : ""
  work_recordings ||--o{ mapping_events : "append-only"
  catalogue_imports ||--o{ catalogue_import_rows : "preview rows"
  rd_file ||--o| statements : "registry entry"
  platforms ||--o{ platform_aliases : ""
  platforms ||--o{ statements : ""
  reconciliation_settings ||--o{ reconciliation_runs : "values used"
  reconciliation_runs ||--o{ reconciliation_items : ""
  reconciliation_items ||--o{ reconciliation_sources : "every source line"
  reconciliation_items ||--o{ reconciliation_exceptions : ""
  enquiries ||--o{ enquiry_items : ""
  reconciliation_items ||--o{ enquiry_items : ""
  enquiries ||--o{ enquiry_events : "append-only"
  enquiries ||--o{ enquiry_actions : "follow-ups"
  enquiries ||--o{ enquiry_communications : "append-only"
```

| Table / view | Notes |
|---|---|
| `platforms`, `platform_aliases` | codes SPOTIFY, APPLE_MUSIC, FACEBOOK, INSTAGRAM, META (IPRS's single Meta licence), YOUTUBE, YOUTUBE_MUSIC, JIOSAAVN, AMAZON_MUSIC, GAANA, WYNK; `alias_key` (letters and digits, lower case) is unique, so a spelling means exactly one platform |
| `works` | `(client_id, internal_work_number)` unique when the number is present; `catalogue_status` ACTIVE / TO_REGISTER (no work number) / REVIEW (different titles for one number) / INACTIVE; soft delete |
| `recordings` | one row per normalised ISRC (CHECK `^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$`) |
| `work_recordings` | one link = one row; `mapping_status` PENDING / VERIFIED / REJECTED / CONFLICT; `mapping_source` CLIENT_CATALOGUE / MANUAL / CORRECTION; `recording_title` keeps the version name; `valid_from` / `valid_to` (NULL = current); unique current `(work, recording)`; VERIFIED needs `verified_by` + `verified_at`. Guard: never deleted, a closed link never changes, the work and recording of a link never change |
| `mapping_events` | append-only history of every link change |
| `catalogue_imports`, `catalogue_import_rows` | one preview per upload with its counts and the catalogue fingerprint it was compared with; one row per source row with the raw cells, normalised codes, proposed action, validation status, message and per-ISRC detail |
| `statements` | the registry entry of one `rd_file` (unique): source, record type, category, platform, reported platform, distributor, holder, reference, usage period, statement date (+ estimated), payment date, currency (+ where it came from), revenue basis, territory, identity key, content fingerprint, record count, total, `import_status` IMPORTED / NEEDS_REVIEW / REJECTED / DUPLICATE / SUPERSEDED / EXCLUDED, `relation` CORRECTION / SUPPLEMENTARY / LEAVE_OUT, `related_statement_id`, `superseded_by` |
| `reconciliation_settings` | benchmark %, client interest % (NULL = not established), revenue basis, per client (optionally per platform); a new value replaces the one in force (`replaced_at`, `replaced_by`); guard: never edited, never deleted |
| `reconciliation_runs` | reference (`SVF-REC-0001`), platform, usage period, the benchmark / interest / basis used, the settings row, `source_snapshot` (statements with file hashes and totals, line counts, catalogue size) and its sha256, `notes`, `summary`; guard: frozen once COMPLETED, never deleted |
| `reconciliation_items` | one per work (or per unmatched ISRC / IPRS work number): revenue, eligible revenue, interest, the IPRS client share as printed, benchmark %, indicative reference, IPRS royalty, indicative variance, observed %, mapping / data / calculation status, recommended action; guard: only `review_*`, `exception_status`, `later_statement_status` change |
| `reconciliation_sources` | every statement line behind every item (statement, file, line, sheet row, ISRC / work, month, amount); frozen |
| `reconciliation_exceptions` | type (CHECK list incl. MISSING_IPRS_ENTRY, UNKNOWN_ISRC, CONFLICTING_ISRC_MAPPING, WORK_NOT_FOUND, AMBIGUOUS_WORK_MATCH, MISSING_USAGE_PERIOD, MISSING_CURRENCY, REVENUE_BASIS_UNCLEAR, CLIENT_INTEREST_UNCLEAR, SOURCE_VALIDATION_ERROR, LATER_STATEMENT_REVIEW_REQUIRED, MAPPING_NOT_VERIFIED, …), severity, OPEN / IN_REVIEW / RESOLVED / DISMISSED, assignee, reviewer, note |
| `enquiries` | reference (`SVF-ENQ-0001`), subject, draft text, status (§26.6), platform and period, run, assignee, creator, reviewer, approver, sender, sent date, channel, recipient, last response, next follow-up, `new_statement_review`, resolution status and summary, closer. CHECKs: never sent without an approval; AWAITING_RESPONSE and later need a sent date; APPROVED_TO_SEND needs an approver; CLOSED needs a closer |
| `enquiry_items` | `(enquiry, reconciliation item)` with work, platform and period (for the duplicate check), section CLARIFICATION / VARIANCE, item status and outcome |
| `enquiry_events`, `enquiry_communications` | append-only history; communications are recorded by hand (direction, type, date, references, related statement) |
| `enquiry_actions` | follow-ups: title, assignee, due date, OPEN / DONE / CANCELLED, completion note |
| view `current_work_recordings` | current, non-rejected links of non-deleted works, with ISRC, work number and title |
| view `isrc_resolution` | per (client, ISRC): CONFLICT if more than one work or any CONFLICT link, VERIFIED if every link is, else PENDING; `work_id` only when unambiguous |
| view `client_revenue_records` | `rd_platform_line` × `statements` (RECORDING_REVENUE) × `isrc_resolution`: work, recording, month, amount, gross/net by the statement's basis, `mapping_status` (VERIFIED / PENDING / CONFLICT / UNKNOWN / NO_ISRC), `validation_status` (OK / BLANK_AMOUNT / NO_MONTH / NO_ISRC / INVALID_ISRC) |
| view `iprs_royalty_records` | `rd_royalty_line` × `statements` (WORK_ROYALTY) × `works`: party, role, own/coll shares, pool, source, amount, the statement's period / platform / currency, `mapping_status` (MATCHED / WORK_NOT_FOUND / NO_WORK_NUMBER) |

The brief's `statement_files` and `statement_rows` are the existing `rd_file` (write-once original, sha256, size, object
key, authorised download) and the immutable line tables (`rd_royalty_line`, `rd_platform_line`, with the sheet row of
every detail line). Metadata, sub-total and total rows are not stored as rows: they are verified at intake (§8.3–8.4,
printed total, sub-totals, footers) and the original file is kept. The brief's `audit_logs` is the existing
hash-chained `audit_event` (§17).

### 26.3 Catalogue import

1. `intake.store` checks and stores the workbook once (`rd_file`, kind SONG_LIST); a file of another kind is refused
   with a pointer to where it belongs. A song list uploaded earlier (e.g. in a processing run) can be previewed too.
2. `_rows_of` finds the heading row (track name + work number and/or ISRC), and reads every row with its raw cells.
   Several ISRCs in one cell (`|`, `,`, `;`, `/`, new line) become separate ISRCs.
3. `classify` (pure) compares the rows with the current catalogue and decides, per row: NEW_WORK,
   EXISTING_WORK_NEW_ISRC, EXISTING_WORK_KNOWN_ISRC, NO_WORK_NUMBER, CONFLICT, DUPLICATE_ROW or INVALID, with a
   validation status OK / WARNING / CONFLICT / DUPLICATE / INVALID and a plain message. The rules are in the module
   docstring; in short: invalid rows are never applied (documented partial-import policy), an ISRC claimed by two works
   becomes a CONFLICT link on both (never moved), a different title for one work number is a version when only version
   words differ, otherwise its links stay PENDING and the work goes to REVIEW; a title alone never links anything.
4. The preview is stored with the catalogue fingerprint. **Apply** runs in one transaction under advisory lock
   `84726300` (per client); a preview made against an older catalogue is refreshed instead of applied. Clean links from
   the client's catalogue are VERIFIED by the person applying it (unless they untick the option), with the file and
   row as evidence; older links of a now-conflicting ISRC are flagged CONFLICT with an event.
5. The catalogue is a reference, not a limit: any role can add a work by hand (e.g. an IPRS work the client confirms)
   or link an unknown ISRC to a work; such links start PENDING.
6. Admins verify / reject / move links afterwards (Catalogue → work pop-up, Conflicts → *Keep this one*). Rejecting
   closes a link (`valid_to`), moving closes it and creates a verified CORRECTION link; nothing is deleted.

Measured on `(S-46)SVF list of Song -April 2026.xlsx`: 2,762 rows → 2,571 works (148 work numbers appear on several
rows: male/female/cover/lo-fi versions of one work), 4,278 ISRCs, 4,541 links (3,974 verified, 41 to verify,
526 conflict links for 263 ISRCs claimed by two works), 12 duplicate rows, 240 rows to check, 1 row without a work
number ("NEED TO REGISTER" → a work to register), 0 invalid rows. Importing the same file again adds nothing.

### 26.4 Statement library

`library.upload` → `intake.store` (same bytes again → the stored copy, "nothing is counted twice") → `register`:

- **Values** come from the evaluated file (§8.4): IPRS category → platform (via aliases: Spotify, Apple Music, YouTube
  Pre/Post-Claims → YouTube, Facebook / Meta → META; radio, TV, mechanical, overseas and redistribution have no
  platform), period from the name or the user's answer, statement date = the file's save date (marked estimated),
  currency for IPRS statements = the client setting `iprs_currency` (IPRS statements print none; recorded as such),
  revenue currency and basis from the file or the distributor setting (SVF/MRM: INR, gross — business decision Q8).
- **Status**: READY → IMPORTED; NEEDS_REVIEW → NEEDS_REVIEW (questions); ERROR / UNSUPPORTED → REJECTED; LEFT_OUT
  (another member's statement, e.g. S-32 / member 8875288) → EXCLUDED.
- **Same distribution** (IPRS identity key) or **same platform report period** (platform + distributor + overlapping
  months) as an imported statement: same content fingerprint → DUPLICATE (counted once); different entries →
  NEEDS_REVIEW with the question *correction / additional statement / leave out*. A CORRECTION supersedes the earlier
  statement (kept, SUPERSEDED); SUPPLEMENTARY counts both. A statement marked SUPPLEMENTARY in a processing run keeps
  that answer.
- `library.sync` registers files uploaded before 1.1.0 (through runs), oldest first, the first time the library is
  read. On a copy of the live database this registered 46 statements: 43 IPRS + 1 revenue imported, S-32 excluded,
  S-45 waiting for the S-44 question.
- An imported IPRS statement calls `enquiries.flag_new_statement`: open enquiries about the same works, platform and an
  overlapping period get `new_statement_review` and an event; completed reconciliation items that did not use it get
  `later_statement_status = REVIEW_REQUIRED`. Nothing is resolved automatically.

### 26.5 Reconciliation

`recon.start_run(client, platform, first month, last month)` (advisory lock `84726400` per client):

1. **Inputs.** Imported RECORDING_REVENUE statements of the platform overlapping the period (their lines inside the
   months), and imported WORK_ROYALTY statements of the platform whose usage period lies **inside** the period
   (others are left out with a note: a partial overlap is never prorated). The settings in force are copied onto the
   run; the snapshot (statements, file hashes, totals, line counts, links) is hashed.
2. **Comparability (run level).** Revenue for every month of the period; IPRS statements covering every month; one
   known currency on both sides; territories that agree when stated; the revenue basis equal to the configured basis;
   an established client interest. Failures become run notes and per-item exceptions (MISSING_USAGE_PERIOD,
   MISSING_CURRENCY, REVENUE_BASIS_UNCLEAR, CLIENT_INTEREST_UNCLEAR); affected items are NOT_COMPARABLE or
   NOT_CALCULATED. Without any IPRS statement for the period, no missing-entry exception is raised.
3. **Items** (`recon.compute`, pure). Revenue lines reach a work only through `isrc_resolution` (VERIFIED or PENDING);
   all ISRCs of one work are summed (each ISRC's revenue stays in the sources); the work's IPRS lines are summed once.
   Unknown ISRCs, conflicting ISRCs and lines without ISRC become UNMATCHED_RECORDING items; IPRS lines whose work number
   is not in the catalogue become UNMATCHED_WORK items. Blank amounts are left out of totals as unknown.
4. **Calculation** (exact `Decimal`, stored to 8 decimals):
   `eligible = revenue × client interest %`, `reference = eligible × benchmark %`, `variance = reference − IPRS`,
   `observed % = IPRS ÷ eligible × 100`. Missing IPRS → variance NULL + MISSING_IPRS_ENTRY (HIGH) with the exact
   wording. Unverified links → MAPPING_NOT_VERIFIED; work under review / to register → AMBIGUOUS_WORK_MATCH.
5. **Recommended next action** per item (verify links, candidate for a clarification request, review the variance, or
   no action when IPRS is at or above the reference).
6. **Already addressed.** When a later statement, payment or adjustment is found to have addressed an item, *Already
   addressed* records the evidence (kind, statement, amount, note), closes the item's exceptions with it and marks the
   item reviewed (`recon.mark_addressed`, audited); the calculated values never change.
7. **Later statements** (`_later`): IPRS statements of the platform not in the snapshot whose period overlaps — shown on
   the run, on items and in the report; an enquiry draft for such an item needs an explicit "I reviewed it".

The report (`recon.report`) has four sheets — Summary (parameters, notes, totals, statement fingerprints),
Reconciliation (the brief's columns, `[Source]` / `[Setting]` / `[Calculated]` prefixes, missing entries spelled
out, previous enquiry, later statement review, recommended action, statement and row references, review), Exceptions,
and Source lines (every line behind every item). The file name carries the period:
`SVF_Reconciliation_Spotify_2025-10_to_2026-03_SVF-REC-0002.xlsx`.

Measured, Spotify Oct 2025 – Mar 2026 (MRM revenue ₹78,89,496.76, IPRS ₹1,13,848.57), benchmark 4 % and — for the test
only — client interest 100 %: 1,799 items; 1,615 works; 1,135 compared; 272 with no corresponding IPRS entry; revenue
on catalogue works ₹72,85,404.71 + not linked ₹6,04,092.06 (= the report total exactly); IPRS on catalogue works
₹1,10,918.41 + works not in the catalogue ₹2,930.16 (= the statement total exactly). Example: *Tomake Chai* (work
15628861, 15 ISRCs): revenue ₹1,80,634.68, IPRS ₹2,694.24, reference ₹7,225.39, indicative variance ₹4,531.14,
observed 1.49 %.

### 26.6 Enquiry workflow

| Action | From | To | Who |
|---|---|---|---|
| (create) | items of a completed run | MAPPING_PENDING / DATA_CLARIFICATION_REQUIRED / DRAFT_PREPARED | any role |
| recheck | NEEDS_REVIEW, MAPPING_PENDING, DATA_CLARIFICATION_REQUIRED, DRAFT_PREPARED | recomputed | any role |
| submit (reviewer) | DRAFT_PREPARED | PENDING_APPROVAL; the chosen Admin gets a "Review and approve" follow-up (the review notification, on their Home page), closed automatically on approve / return / withdraw | any role |
| return (note) | PENDING_APPROVAL, APPROVED_TO_SEND | DRAFT_PREPARED | Admin |
| approve | PENDING_APPROVAL | APPROVED_TO_SEND | Admin |
| record_sent (recipient, date, channel, follow-up date) — links re-checked first | APPROVED_TO_SEND | AWAITING_RESPONSE | Admin or the assignee |
| record_response (date, summary) | AWAITING_RESPONSE, UNDER_INVESTIGATION, PARTIALLY_RESOLVED | UNDER_INVESTIGATION | any role |
| record_follow_up | same | AWAITING_RESPONSE | any role |
| note_correction (correction / additional royalty / payment, amount) | after sending | unchanged | any role |
| partially_resolve / resolve (note, per-item outcome) | AWAITING_RESPONSE, UNDER_INVESTIGATION (, PARTIALLY_RESOLVED) | PARTIALLY_RESOLVED / RESOLVED | any role |
| reopen | RESOLVED, PARTIALLY_RESOLVED | UNDER_INVESTIGATION | any role |
| close (verification note) | RESOLVED | CLOSED | Admin |
| withdraw | any draft state, PENDING_APPROVAL, APPROVED_TO_SEND | CLOSED (WITHDRAWN) | the drafter or an Admin |
| new_statement_reviewed, assign | any | unchanged | any role / Admin |

Rules: an item goes into an enquiry only if it is a catalogue work with revenue, comparable, and either has no IPRS
entry or a positive indicative variance; the same work, platform and overlapping period is never enquired about twice
(unless withdrawn); unverified links keep the draft at MAPPING_PENDING and block submit and approval; while a new
statement is unreviewed, submit / approve / record sent / resolve / close are refused. "Follow-up due" and "overdue"
are derived from the open follow-ups' dates (`next_follow_up_at` = the earliest); the dashboard shows the queues of the
brief (drafts awaiting review, awaiting approval, to be sent, awaiting response, due today, overdue, under
investigation, partially resolved, new statements to review, resolved awaiting closure). The draft text is a neutral
clarification request (no benchmark, no variance, no allegation); the internal working paper (annex) carries the
indicative figures.

### 26.7 Master view and exports

`master.view` sums `client_revenue_records` (VERIFIED or PENDING links only) and `iprs_royalty_records` (matched works,
statements inside the period) per work and platform on every read; totals cover all pages; money that reaches no work
is reported beside the table and listed under *Unmatched money*. Filters: search, platform, usage period (or Indian FY),
catalogue status, link status, money, statement; sorts; 100 works per page; the lines behind any amount.

| Export | Name (example) |
|---|---|
| Master statement (SKV layout, rebuilt with the §11 engine from the imported statements and the catalogue as the song list) | `SVF_Master_Statement_All_Periods.xlsx`, `SVF_Master_Statement_Spotify_2025-10_to_2026-03.xlsx` |
| Filtered master view | `SVF_Master_View_Spotify_2025-10_to_2026-03.xlsx` |
| Filtered records | `SVF_Spotify_Revenue_Records_2025-10_to_2026-03.xlsx`, `SVF_IPRS_Royalty_Records_All_Periods.xlsx` |
| Reconciliation report | §26.5 |
| Catalogue | `SVF_Catalogue.xlsx` (works in the song-list layout + a links sheet) |
| Catalogue import report / statement error report | `Catalogue_Import_7_Rows_To_Check.xlsx`, `Statement_12_Error_Report.xlsx` |

A period is only put in a file name when it is known: a filter, or the stated periods of every included statement;
otherwise *All_Periods*.

**Validated against `SVF-RD-SKV8.xlsx`** with all 45 statements of batch 1 + the MRM Spotify report imported: all 44
distribution columns (section + distribution number + period) present with equal totals, except YouTube Post-Claims
P2577 (Apr – Jun 2025): ₹77,322.51 instead of ₹77,375.98 — the ₹53.47 of S-32 (member 8875288), excluded under business
decision Q7; Spotify (MRM) revenue ₹78,89,496.76 equal. Rows differ (3,048 instead of 3,144) because the catalogue has
one row per work, and four SKV8 rows where two work numbers had been merged by hand are split by work number (same
money). The export took 11–21 s.

### 26.8 Open business questions

1. **Client interest.** The benchmark needs the client's interest in the reported revenue; it is not established, so
   it is NULL and no benchmark is calculated until the Super Admin sets it. IPRS statements print SVF's collection share
   (50 % on the reference files): should the 4 % apply to 100 % of the revenue and be compared with SVF's 50 % share, or
   be adjusted by that share? The report shows both the interest used and the printed share.
2. **Meta.** IPRS pays one Meta licence (Facebook Inc, WhatsApp); revenue reports would split Facebook and Instagram.
   They are not compared until a rule says how.
3. **Catalogue conflicts.** 263 ISRCs of the SVF list belong to two work numbers; their revenue stays unmatched until
   an Admin keeps one link per ISRC.
4. Earlier open questions Q4–Q6 (§13.3) are unchanged.

## 27. Version 1.2.0

No migration; the release notes are in `backend/mrm/releases.py`.

- **Client on the page.** `ClientSelect` ([parts.tsx](frontend/src/parts.tsx)) is shown on Statements (upload),
  Reconciliation, Master and Settings → Reconciliation, always (also with one client). It sets the same remembered
  client as the top-bar picker; whoever may add clients gets "+ Add a client" (the Clients pop-up, exported from
  [Clients.tsx](frontend/src/pages/Clients.tsx)). Statement upload sends `source` CLIENT or IPRS (the "work it out" choice
  is gone; content still decides WORK_ROYALTY vs RECORDING_REVENUE).
- **Work number suggestions.** `GET /catalogue/works/search` (`catalogue.find_works`) matches the exact number, then
  numbers that start with the text, then titles. `WorkNumberField` ([Catalogue.tsx](frontend/src/pages/Catalogue.tsx))
  is used by Add a work (existing work → its title is filled in and the ISRCs are linked to it with
  `POST /catalogue/works/{id}/links`; otherwise a new work), Move link and the reconciliation's Link ISRC.
- **Per-platform benchmark.** `POST /reconciliation/settings/platforms` (`recon.save_platform_settings`): the client-wide
  row (`platform_id` NULL) plus, for each platform in the client's statements (`recon.statement_platforms`), either
  `use_default` (its own row, if any, is closed: `replaced_at` without a successor) or its own benchmark (a platform
  row with the same interest and basis). Unchanged rows are left alone. `current_settings` already preferred a platform
  row, so runs pick it up. `recon.options` adds per platform `setting`, `own_benchmark`, `revenue_months` and `status`
  (READY / NO_REVENUE / NO_IPRS / NO_OVERLAP), and `others` (imported statements without a platform).
- **Master sheet.** `GET /master/sheet` (`master.sheet`) builds the SKV master with the same `_build` as the export
  (engine + checks), turns it into columns / groups / rows in the exact column order of `excel.master`, and keeps the
  last six results in process memory keyed by client, filters and a fingerprint of the client's statements, works and
  links (`_fingerprint`), so a change is never shown stale. Search and paging (100 rows) run on the cached rows. Measured
  on the SVF data: 211 columns, 3,047 rows, about 1.3 s to build, 20 ms from the cache.
- **Wide tables.** `ScrollX` ([ui.tsx](frontend/src/ui.tsx)) adds a top scroll bar kept in step with the bottom one and
  hold-and-drag scrolling (a press that does not move still clicks; form controls and links are not dragged).
- **Footer and notes.** The footer shows only the version, bottom right; signed in it opens every version's notes
  (`GET /releases`). After an update a small note appears once in the corner; "See what's new" opens that version's
  notes (`POST /me/seen` as before).

## 28. Version 1.3.0: statement sides, yearly reconciliation

Migration `0009_statement_sides.sql`.

- **Side = who sent it.** `statements.statement_source` decides the side in a reconciliation and in the master views:
  CLIENT = the source revenue, IPRS = the IPRS royalty. The layout (`record_type`: per ISRC and month, or per work in
  the IPRS layout) is a separate fact; a client often forwards statements in the IPRS layout and they stay on the
  client's side. `statements.file_id` is unique per side (`statements_file_source_key`), so the same stored file can
  be uploaded once as the client's copy and once as IPRS's copy. Duplicates and corrections (`library._same`) are
  looked for on the same side only. Upload refuses a missing side; changing the side of a statement re-checks it on
  the new side and refuses when the file is already there. `client_revenue_records` and `iprs_royalty_records` carry
  `statement_source` (new last column). Only IPRS-side imports flag open enquiries.
- **No auto-join.** `library.sync` no longer registers files uploaded through processing runs; a statement is in the
  library only when it is uploaded under Statements with its side.
- **Every category is a platform.** `platforms.ensure` makes a platform (and its alias) for a statement category that
  is not a known platform (Radio, Zee TV Broadcast, Overseas - SACEM (France), Mechanical (MUSERK), Other /
  Unclassified, Redistribution …), so each category is reconciled and listed on its own. The 1.1.0 guess that put an
  "Other / Unclassified" statement under the platform of its first pool sources (S-3 → Apple Music) is gone.
- **Reconciliation by side** (`recon._side_statements`, `_lines`, `_coverage`, `_keep`, `_one_kind`, `compute`): both
  sides are read in one line shape; an ISRC-layout line reaches a work through its ISRC link, a work-layout line
  through its work number. Work numbers that are not in the catalogue are paired across the sides
  (UNMATCHED_WORK, "Work not in catalogue"). One side never adds a per-ISRC revenue report and a per-work statement
  for the same months: the client's side keeps its revenue report, IPRS's side its royalty statement; the other is
  left out with a note. The revenue-basis check applies to per-ISRC client reports only.
- **Yearly run** (`reconciliation_runs.run_kind = 'YEAR'`, `POST /reconciliation/runs {mode: "YEAR", fy}`): the Indian
  financial year Apr–Mar; the months both sides cover are compared (`compared_months`), months only one side covers
  and work-layout statements reaching outside them are named in the notes and left out (never prorated). The same
  months one year earlier (`previous_period_start/end`) give `reconciliation_items.previous_revenue` and
  `previous_iprs_royalty`, shown with the change in per cent; they are not part of the calculation. `recon.options`
  lists per platform the financial years with each side's months (`years`), and a status YEAR_ONLY.
- **Master.** "Works by platform" shows the client's statements and IPRS's statements as two column groups; a
  per-ISRC report gets its own column ("Spotify - revenue report"). The master sheet and its export take `side`
  (CLIENT by default).
- **`python -m mrm.cli clear-statements CODE --reason … [--confirm CODE]`** (`mrm/maintenance.py`): without
  `--confirm` a dry run with counts. With it, as the owner login and with the guard triggers switched off inside the
  one transaction, it removes the client's statement files and their lines, the statement library, reconciliation
  runs, enquiries and processing runs with their draft reports, then the stored originals and report files. It keeps
  the catalogue (and the song-list file it came from), clients, people, platforms, reconciliation settings and the
  activity log, where it records `maintenance.statements_cleared`. Published reports stop it.

## 29. Version 1.4.0: reconciliation in the master layout, brand

No migration.

- **Period columns.** `recon.period_columns(conn, run_id)` lists a run's usage periods per side from its frozen
  `reconciliation_sources`: a month for per-ISRC lines (`usage_month`), the statement's usage period for per-work lines
  (with the distribution numbers). `recon.period_amounts(conn, item_ids)` gives each item's amount per period; a period
  with only blank amounts stays out (never zero). `run_view` returns `periods`; `items` returns each row's `periods`.
- **Run page.** The items table uses the master sheet's style (`table.skv.recon-skv`): band row (platform · "Source
  revenue (from CODE)" · "IPRS royalty" · Indicative calculation · Year before · Status and review), header row, one
  column per period and a total per side, the work column frozen (with the tick box for enquiries).
- **Excel report.** The first sheet, *Reconciliation*, is written by `recon._master_sheet` in the master workbook's
  system (`excel._band_header`, `excel._head`): bands in row 1, headers in row 2, the song title frozen (`B3`), the
  period columns of each side, every earlier column kept, a TOTAL row (money columns except the variance) and the notes
  under it. Summary, Exceptions, ISRC detail and Source lines follow. Plain exports use the brand header colour
  (`xlsx.HEAD_FILL`); the SKV master keeps its measured SKV8 colours.
- **Brand** (final palette in 1.4.2). Tokens in `styles.css` from #191A19, #1E5128, #4E9F3D and #D8E9A8. Light: white
  title bar and surfaces, forest #1E5128 buttons and links (white on it 9.3:1), leaf #4E9F3D for indicators, focus and
  ticks. Dark: #191A19 title bar and panels on #121312, leaf #4E9F3D buttons with #191A19 text (5.3:1), lime #D8E9A8
  links (13.4:1). The selected tab (title bar and in-page tabs) is shown only by its text colour (`--topbar-on-ink`,
  `--accent-ink`: dark green in light, lime in dark) and a leaf underline (`--indicator`). Logo `Logo.tsx` /
  `public/favicon.svg` (two overlapping circles: the client's statements and IPRS's, and what they agree on),
  `theme-color`, reconciliation bands and plain Excel headers (`xlsx.HEAD_FILL` 1E5128) follow the palette.
- **1.4.3.** `POST /reconciliation/runs/{id}/review {item_ids, status, note}` (`recon.review_items`): review several items
  of one run in one transaction (REVIEWED, NEEDS_INFO, or UNREVIEWED, which clears the reviewer); one activity-log event
  `recon.items_reviewed` with the counts before. On the run page every item has a tick box (the heading box ticks the
  page); the action bar offers the three statuses and the enquiry draft for the ticked items that qualify.
  `ResetFilters` / `changed` (`parts.tsx`) add "Clear filters" to every filtered list. Home lists Enquiries waiting and
  My follow-ups first, statements last.
- **1.4.4.** `GET /reconciliation/runs/{id}/item-ids` (`recon.item_ids`) returns every item matching the run filters
  (all pages) and those eligible for an enquiry, for "Tick all N items that match"; the run page keeps ticked ids across
  pages. `run_view.exceptions` counts items per exception type: `open` = still to review (open exception, item not
  reviewed), `reviewed`, `closed`, `items`.
  Later in 1.4.4 (21 Oct 2026): Super Admin "Delete all statements" on the Statements page — `GET|POST
  /clients/{id}/clear-statements` (capability `clear_statements`, SUPER_ADMIN only; the POST needs `confirm` = the client
  code) runs `maintenance.clear_statements` (the `mrm.cli clear-statements` code, on the owner connection) with the
  person as the audited actor: statements, files and lines, reconciliations, enquiries and processing runs go; the
  catalogue, settings, platforms, people and the activity log stay; published reports still refuse it (`ClearRefused`).
  `Pager` steps back to the last page when the list shrinks under it (reviewing items out of a "Not reviewed" filter
  emptied the page). `run_view.reviewed` and `recon.runs(...).review` count REVIEWED and NEEDS_INFO separately; Earlier
  reconciliations has a Review column ("✓ Reviewed" when every item is). The Reconciliation page shows Run a
  reconciliation and Earlier reconciliations above the platform table.


## 30. Version 1.5.0: three kinds of statement, usage, underpaid works

**Statement kinds** (`statements.statement_source`, migration `0010_three_sources.sql`), one tab each under
Statements (`#/statements/platform|client|iprs`); the tab decides the kind and `library.ALLOWED[source]` refuses
files of another kind with a message naming the right tab:

| Source | Holds | Record types | Role in a reconciliation |
|---|---|---|---|
| `PLATFORM` | the platform's reports (MRM Spotify revenue, Spotify usage) | `RECORDING_REVENUE`, `RECORDING_USAGE` (new) | revenue (basis of the 4 %) and plays |
| `CLIENT` | the client's statements per platform, in bulk (IPRS layout) | `WORK_ROYALTY` | shown beside IPRS paid; difference flagged |
| `IPRS` | statements received from IPRS | `WORK_ROYALTY` | what IPRS paid |

The migration moves existing per-ISRC statements to `PLATFORM` (other copies `EXCLUDED`). `statements.total_usage`
holds a report's plays. A usage report and a revenue report of the same months are never duplicates (`_same` compares
the record type).

**Revenue and usage combined.** View `platform_usage_records` = every platform line with plays (usage reports, and
revenue reports that carry plays), linked to works through `isrc_resolution`. The combination rule is used everywhere
(`library._COMBINED`, `recon._usage`, `master.USE_LINES`): lines are joined by ISRC (normalised song name when a line
has no ISRC) and month; a month's plays come from the usage report when one covers that platform and month, otherwise
from the revenue report's plays column. `GET /platform-data` (+ `/export`, sheets "By ISRC" and "By month") shows
per song the revenue, plays, months on each side and whether the two reports name it differently.

**Reconciliation** (`recon.start_run` → `_gather` per side → `compute`). Base = platform revenue when the platform
report covers the period, otherwise the client's statements (client-vs-IPRS mode, no benchmark). PERIOD runs need the
base and IPRS to cover every month; YEAR runs compare the months both cover. Client statements are included when their
usage period is inside the compared months. Per work:

```
expected (reference_benchmark_amount) = revenue × client interest (100 % while not set) × benchmark %   (4 %)
observed_percentage                    = IPRS paid / eligible revenue × 100
indicative_variance (shortfall)        = expected − IPRS paid           > 0.005 → exception UNDERPAID (HIGH)
client_iprs_difference                 = client statement − IPRS paid   ≠ 0     → exception AMOUNT_MISMATCH
```

New item columns: `usage_plays`, `usage_lines`, `client_statement_amount`, `client_statement_lines`,
`client_iprs_difference`; source types `PLATFORM_REVENUE`, `PLATFORM_USAGE` (contribution = plays),
`CLIENT_STATEMENT` (`CLIENT_REVENUE` stays readable for older runs); exceptions `UNDERPAID`, `NO_PLATFORM_REVENUE`
(IPRS or the client's statement show the work but the platform report has no revenue for it — usually a missing
ISRC link). Run summary adds `underpaid`, `shortfall`, `usage`, `client_matched`, `client_differences`, `base`.
Item filter `variance=underpaid|client_diff`. `recon.why_not_query` is the single rule for what can go into a query
(enquiry): a catalogue work, comparable, and IPRS underpaid it, paid less than the client's statement, or did not
list it. "Raise a query to IPRS" on the run page ticks every such work (`item-ids` → `eligible`) and opens the draft;
`enquiries._draft` writes revenue, plays (with their months), paid, % paid, expected and difference per work.
Worked check (SVF, Spotify Oct 2025 – Mar 2026): Aaj Amaye (15617483, INS2X1600035 on two UPCs) revenue ₹9,633.50,
plays 122,988 (Jan–Mar 2026), expected ₹385.34, IPRS paid ₹119.23 = 1.24 %, shortfall ₹266.11.

**Master.** Works by platform shows four groups per platform — platform revenue, usage (plays), client statements,
IPRS paid — for any period (`master.ALL_CTE`); sort/filter by plays. The SKV sheet's first side is "client statements
+ platform revenue reports" (usage reports are not distributions and stay out of the SKV engine).

## 31. Version 1.5.1: flexible catalogue import, album, Delete catalogue

**Reading a catalogue** (`parsers.map_header`, `parsers.codes_in`, `catalogue._rows_of`). Headings are classified
flexibly instead of matched exactly: ISRC = any heading with the word ISRC (`ISRC`, `ISRC 1` … `ISRC 16`, `ISRC1`,
`ISRC Code 2`); IPRS work number = the known names (`Internal No`, `Work No` …) or a heading that pairs
IPRS / work / internal / tune with code / no / number / id (`IPRS Song Code 1`, `Work Code`, `IPRS Work ID`, `Tune
Code`), never a serial number (`S.No`, `Sr No`); title = the exact names first, then a heading with song / track /
title that is not a code or album; album = album / movie / film / web series / serial name / release; language.
`m["isrc_cols"]` and `m["work_cols"]` list every such column; codes are read from all of them, in column order, once.
The heading row is searched in the first 15 rows; `_rows_of` reads **every** visible sheet with a catalogue table
(each preview row keeps its sheet; `catalogue_imports.source_sheet` lists them joined with " + "). Rows are applied in
file order (`ORDER BY id`).

**Album / language** (migration `0011_catalogue_album.sql`: `works.album`). Kept in `catalogue_import_rows.raw_row_data`,
set on new works and filled in (`coalesce`) on existing works that have none (`applied.albums_filled`); shown, searched,
editable (Admin) and exported ("Album / film", "Language").

**After Apply** the UI opens `#/catalogue/works/{import id}` = `GET /catalogue/works?import_id=` (works the import
created, linked ISRCs to, or matched).

**Delete catalogue** (Super Admin, capability `clear_catalogue`): `GET|POST /clients/{id}/clear-catalogue` (POST needs
`confirm` = client code) → `maintenance.clear_catalogue` on the owner connection with the guard triggers disabled for
the transaction: enquiries, reconciliation runs/items/sources/exceptions (built on the works — FKs), mapping events,
import rows, links, works, imports, the uploaded song lists (unless a processing run or a statement uses the file) and
recordings no client links any more. Statements, reports, settings, platforms, people and the activity log stay; audit
action `maintenance.catalogue_cleared`. The UI dialog (`ClearDialog` in `ClearData.tsx`, shared with Delete all
statements) shows the dry-run counts first.

## 32. Version 1.5.2: upload batches, the song report layout, query attachment

**Batches** (migration `0012_statement_batches.sql`): `statement_batches` (client, tab = `statement_source`,
`batch_no` per client and tab, `batch_key`), `statements.batch_id`. The Statements screen sends one random
`batch_key` with every file of one drop; `library._batch` creates the batch (numbered under an advisory lock) when the
first statement of that key arrives, so failed drops leave no gaps. Older statements were grouped by tab and person
(uploads < 10 minutes apart). `GET /statement-batches?client_id&source&platform_id&status&q` lists batches (filters
pick batches with a matching file; `matching` counts them) labelled "Batch N · Platform(s) · period" (the client tab
leaves out the platform); `GET /statement-batches/{id}` lists the files.

**Song report layout** (`recon.run_blocks`, `recon.block_values`, `recon.block_sheet`): Internal No · Song name · ISRC;
one section per kind (the platform, e.g. SPOTIFY; client statement; IPRS ROYALTY) with one block per statement:
Amount · Date · Period (Period, Usage) · Distribution No; then CHECK: expected value (benchmark % of revenue), IPRS
paid, IPRS paid % of revenue, Variance % (= variance / expected) and Variance amount (= expected - paid), Result.
A block's period is the statement's period inside the run; its usage is the plays the platform reported for the song
in that period (the heading says when the usage report covers only part of it). Date = statement date, else payment
date, else the upload date. Used by the run page (three heading rows), the Excel report's first sheet (frozen at C4,
with status / year-before / source-row columns) and the enquiry attachment. Items carry `blocks` and `variance_pct`.

**Query to IPRS**: `enquiries._draft` no longer lists songs; it refers to the attachment
(`attachment_name` = `{reference}_{platform}_{from}_to_{to}_Songs.xlsx`), states what was found (underpaid / no
entry counts) and asks three clarification questions. `GET /enquiries/{id}/attachment` builds it from the enquiry's
items (`enquiries.attachment`, audit `export.enquiry_attachment`); the enquiry page shows it with "Download
attachment".

**Shorter pages**: the explanatory page intros and card subtitles were removed (data lines such as a run's reference
or an import's sheet stay).

## 33. Version 1.5.3: master sheet sorting and platform totals, rebuilding a query's text

**Master sheet** (`master.sheet`, `GET /master/sheet?…&sort=`): the cached SKV sheet records `plat_n` (its platform
bands). Per request, with every platform the `Total <platform> Revenue` columns (index 4 …) are cut from the columns,
rows and TOTAL row and the IDENT group's span / later groups' starts shift; with one platform they stay
(`platform_revenue` says whether there are any, so the screen can say when the platform has no revenue report). The
Excel export (`export_skv`) keeps the full SKV layout. `sort` ∈ `SHEET_SORTS` (`amount_desc` = the engine's own order,
`amount_asc`, `title_asc`/`title_desc` by `title_key`, `platform_desc`/`platform_asc` only with a platform that has a
revenue column; anything else falls back to `amount_desc`, returned as `sort`). Sortable columns carry
`sort` = title / amount / platform; the screen turns them into heading buttons with `aria-sort`. Works by platform
gains `revenue_asc` and `title_desc` in `SORTS`.

**Query text**: `enquiries._letter(conn, e)` writes the subject and text for the enquiry's current (not removed) items
with `_draft`. `PATCH /enquiries/{id}` with `rebuild: true` replaces both (event `DRAFT_REBUILT`); removing an item from
a draft whose text is still the generated letter rewrites it for the remaining songs. `detail` returns `text_current`
(false for a draft whose text differs from `_letter`, e.g. drafts from before 1.5.2 that listed every work under
"A. Works for which we could not find an entry …" / "B. …"); the page then offers "Rebuild the text". The enquiry
page no longer shows the Items table (the songs are in the attachment and the Excel working paper), so items are not
removed from the screen any more; `remove_item` stays in the API.

## 34. Version 1.5.4: revenue in the check section, three frozen columns

**Check section**: the run page and `recon.block_sheet` (Excel report, enquiry attachment) start the CHECK section
with the revenue the benchmark is taken of: `sound_recording_revenue` ("Total revenue"), or, when the run has a client
interest, `eligible_revenue_basis` ("Revenue counted (N % client interest)"); `block_sheet(…, interest=)` takes the
run's `client_interest_pct`. Summed in the Excel TOTAL row.

**Frozen columns**: `parts.freeze(table)` sets `--fz1`, `--fz2` … from the widths of the header cells `th.fz0`,
`th.fz1` … (the one with colspan 1), so each frozen column starts where the ones before it end; called on every render
of the reconciliation table and Works by platform, and in the master sheet's layout effect. Three columns are frozen:
reconciliation (Internal No, Song name, ISRC), master sheet (ISRC, Song Name, Internal No, the SKV order) and Works
by platform (now Internal No, Song, ISRCs as separate columns). The thick divider moved from `.fz1` to `.fz2`. Excel:
`block_sheet` freezes at D4 (was C4); the SKV master workbook already froze at E3/F3.

**Number fields** (1.5.4): `format.numeric(v, places)` keeps digits and one decimal point as a person types or pastes
(percentages 4 places, amounts 2, statement number 0) and `NUMBER_PATTERN` refuses a dangling '4.' on submit. The
server parses with `recon.plain_number` (`\d+(\.\d+)?` only; thousands commas only for amounts), so '1e2', 'NaN',
'Infinity', '-4' and '1,5' as a percentage are refused instead of being read by `Decimal`.

## 35. Version 1.6.0: client share and total revenue, two statement tabs

**The calculation** (`recon.compute`). The platform report (MRM's Spotify report) shows the client's share of a song's
revenue: the platform pays the client a share of what the song earned (Spotify 52 %). Per work:

```
total revenue (eligible_revenue_basis)   = platform revenue (sound_recording_revenue) / client share % x 100
expected (reference_benchmark_amount)    = total revenue x IPRS % (benchmark_percentage)
received % (observed_percentage)         = IPRS paid / total revenue x 100
variance (indicative_variance)           = expected - IPRS paid          > 0.005 -> UNDERPAID
variance %  (recon.variance_pct)         = variance / expected x 100
```

Example: Rs. 52 reported at 52 % → total Rs. 100 → expected at 7 % Rs. 7; IPRS paid Rs. 3 → 3 % received, variance
Rs. 4 (57.14 %). Worked check (live copy, Spotify Oct 2025 – Mar 2026, 7 % / 52 %): Aaj Amaye revenue ₹9,633.50 → total
₹18,525.97, expected ₹1,296.82, paid ₹119.23 (0.64 %), variance ₹1,177.59 (90.81 %). A client share that is not set
counts as 100 % (`recon.share_of`; the run notes say so). The client interest of earlier versions (`client_interest_pct`,
multiplying the revenue) is no longer set or used; runs before 1.6.0 keep it and show it as before. The usage lines
of `compute` are always stored as `PLATFORM_USAGE` (plays) - a revenue line that stands for its plays is no longer
also stored as revenue.

**Settings** (migration `0013_iprs_tab_client_share.sql`: `client_share_pct` on `reconciliation_settings`,
`reconciliation_runs` and `reconciliation_items`). `POST /reconciliation/settings/platforms` takes the client-wide
`benchmark_percentage` (IPRS %) and `client_share_pct` (both required) and per platform `use_default` or its own pair;
a row in force is replaced only when the IPRS %, the share or the basis changes, or it still carries a client interest.
Settings → Reconciliation: two client-wide fields, 'Select all' (every platform follows them) and, per unticked platform,
an IPRS % and a client share (starting from the client-wide values). A run records the share it used (100 when not
set) on the run and on each item; `summary.share_set` says whether it was set.

**Two statement tabs.** `library.SOURCES = ("PLATFORM", "IPRS")`. The client's statements were IPRS statements the client
forwards (the same layout), so migration 0013 makes every `CLIENT` statement an `IPRS` statement, except a client copy
of a file that is also under IPRS (`statements_file_source_key`): it stays `CLIENT`, `EXCLUDED`, without a batch. A
client copy of a distribution already received from IPRS (same `identity_key`) becomes `DUPLICATE` (same fingerprint)
or `NEEDS_REVIEW` (correction / additional / leave out). Batches: empty ones (left by Delete all statements) are
deleted, the client tab's batches join the IPRS tab, and every tab is numbered again in upload order (live: IPRS
Batch 1 = the 45 S-files, Batch 2 = Spotify Oct 2025 – Mar 2026; Platform Batch 1). `maintenance.clear_statements`
now deletes the batches too. `upload`/`batches` read `CLIENT` as `IPRS` (older screens); `#/statements/client` opens the
IPRS tab. A run needs the platform's revenue in its months (`start_run` refuses otherwise; the client-vs-IPRS mode of
1.3.0–1.5.4 is gone); `options()` reports `NO_REVENUE` for platforms with IPRS statements only. Master sheet: the first
side is the platform revenue reports only.

**Run page, check section** (new runs): Total revenue (100 %) · Client share (N %) · Expected value (IPRS %) · Received
from IPRS · Received % of total revenue · Variance amount · Variance %. Runs before 1.6.0 keep their columns (and the
client-statement band and Client − IPRS column when they have one).

**Song report** (`recon.block_sheet`: Excel report sheet 1, enquiry attachment). Platform blocks: Amount · Period (Period,
Usage) · Distribution No (no Date). IPRS blocks: Amount · Date · Period · Distribution No (no Usage). CHECK: Revenue (the
client share amount as reported) · Expected value (`N % of total revenue = revenue ÷ S %`) · Received from IPRS · Received
% of total revenue · Variance amount · Variance % (TOTAL row: Σ ratios); no Result column. `check_note` writes the
formula under the table. `block_sheet(…, share=, usage=)`.

**Query attachment with usage**: `GET /enquiries/{id}/attachment?usage=true` (`attachment_name(…, usage=True)` =
`…_Songs_with_usage.xlsx`; `detail` returns `attachment_usage`) adds a USAGE section at the end: Usage (plays) and
Revenue per usage = the song's total revenue ÷ its plays, over the months the usage reports cover only
(`recon.usage_rates`, `recon.usage_label`: the headings say "Jan 2026 - Mar 2026 only" when the usage covers part of the
run). Example: Bhalobeshe Kono Bhool, Oct 2025 – Mar 2026 with the full-year Spotify usage report: ₹12,420.68 ÷ 52 % ÷
254,386 plays = ₹0.0939 per play. The letter (`enquiries._draft(…, share=)`) says the expected royalty is of the song's
total revenue and that the revenue reported is the client's share; drafts of runs before 1.6.0 keep their exact text.

## 36. Version 1.6.1: variance % in percentage points, one dashboard, no Reports section

**Variance %** (`recon.variance_pct`) = IPRS % − received % (`benchmark_percentage − observed_percentage`): the
difference in percentage points (7 % expected, 1 % received → 6 %), no longer variance ÷ expected. It is computed when
read, so earlier runs show it the new way too. The check section is now: … Received % · Variance % (N % − received %) ·
Variance amount (the amount moved after the %), on the run page, in the Excel report and in the query attachment
(`block_sheet`; TOTAL row = IPRS % − Σ received / Σ total revenue of the works compared). Excel summary sheet: received %
and variance % of the works compared (`recon._pct_rows`). `check_note` explains it under the table.

**Song report blocks on screen** match the Excel: platform blocks Amount · Period (Period, Usage) · Distribution No;
IPRS blocks Amount · Date · Period · Distribution No - for Works, Unmatched recordings and Works not in catalogue alike.
`block_values` attaches plays to the platform blocks only (an IPRS block no longer shows its date / period / number for
a song IPRS did not list just because the song had plays).

**Start page.** The Platform list offers only platforms with both a revenue report and an IPRS statement
(`revenue_months` and `iprs`); the Platforms table shows Choose only for those. 'Which months to compare?': the IPRS
statement periods the platform revenue meets (each with its months, the IPRS statement, the platform revenue and plays
coverage), periods with no platform revenue named in one line instead of offered, From month / To month, and a plain
line "Compares Spotify revenue for Oct 2025 – Mar 2026 with what IPRS paid for the same months." Earlier reconciliations:
'Months compared'.

**Run page.** The intro is that plain line. One dashboard card: the figures (works compared, revenue, total revenue,
expected, received with its %, variance %, shortfall, plays, unlinked money, items reviewed) and the exception tiles
under 'To review'; the underpaid and no-IPRS-entry counts are in the tiles only. The run's reference / run by / basis
line, the 'Indicative figures' note and 'Statements used in this run' are at the bottom.

**Reports section removed** from the app (nav item, `#/reports`, `#/process`; pages Process, Results, PastReports,
DeleteRun, ReportPreview - copies in /home/swatantra/RD/backups/2026-10-24-before-1.6.1-reports-section/). The
reconciliation (unmatched recordings, works not in catalogue, its Excel report) and the query attachment replace it.
The processing-run API stays in the backend, unused by the screens.

**Default order: song name A → Z** (no longer highest revenue / Total Amount first). Master sheet `sheet()` sort
`title_asc` (also the fallback when a platform sort no longer applies); Works by platform `view()` / `export_view` sort
`title` (`lower(work_title) NULLS LAST`); `GET /master/export-statement?sort=` → `master._export_order` reorders
`res.rows` before `excel.master` (default `title_asc`; `amount_desc` = the engine's own order). Reconciliation
`items()` and `report()` default `title` (`lower(i.work_title) NULLS LAST, item_no`); the run page passes its Sort to
`GET /reconciliation/runs/{id}/report?sort=` (left out of the report's Filters line). Query attachment and annex:
`lower(work_title)`, then item number.

**Home, Statements** (`overview.overview` → `statement_boxes`): `iprs` = imported statements with `statement_source =
'IPRS'`; `platforms` = imported `PLATFORM` statements per platform name. One box each (IPRS first, a platform only when
it has reports); a box opens `#/statements/iprs` or `#/statements/platform`. The status counts and the recent-files
list are gone from the card (`statements` by status stays in the payload for the hero's next step).
