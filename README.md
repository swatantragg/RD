# MRM Royalty Reconciliation

Music Rights Management India's internal platform for a client's royalties (first client: SVF Entertainment):

1. **Catalogue**: the client's works (IPRS work numbers) and the ISRCs linked to them, imported from the song list with a
   preview of new works, new ISRCs, conflicts and invalid rows before anything changes.
2. **Statements**: the client's sound-recording revenue reports and the IPRS statements, uploaded in any order, checked,
   stored once and kept as evidence.
3. **Master**: every work with its revenue per platform and its IPRS royalty; exports of the view, the records and the
   master statement in the `SVF-RD-SKV8` layout.
4. **Reconciliation**: a platform's revenue against IPRS's work royalty for the same usage period, with the approved
   indicative reference benchmark (4 % for SVF). Missing IPRS entries, unknown or conflicting ISRCs and incomplete data
   are flagged, never assumed.
5. **Enquiries**: drafts for IPRS, approval, manual sending (the application never sends anything), responses,
   follow-ups and closure, all recorded.
6. **Reports**: the guided processing run that publishes the numbered master report, Missing Songs and out-of-scope
   reports (unchanged from 1.0.x).

- Every statement total is checked; money is exact and a missing amount is never zero.
- Money reaches a work only through its catalogue links; a title only ever suggests.
- Sound-recording revenue and IPRS royalty are never added together.
- Evidence, reconciliation runs and published reports never change.

Documentation: **[architecture.md](architecture.md)** describes the system as built (1.4.4: §6.2 roles, §26 the
reconciliation platform, §27 1.2.0, §28 statement sides and yearly reconciliation, §29 master-layout reconciliation and brand). The older documents in [Docs/](Docs/) describe release 1 and its design.

## Run it

```bash
cp backend/.env.example backend/.env && chmod 600 backend/.env   # then put strong random passwords in it
docker compose up -d --build    # db, bootstrap (migrations + seed), api, worker, web
open http://localhost:8080
```

**Settings and secrets** live in `backend/.env` (template with explanations: `backend/.env.example`): database
links and passwords, `APP_ENV`, sign-up switch, session length, sign-in limits, cookie and upload limits. The file is
ignored by git and by the Docker build. With `APP_ENV=production` the application refuses to start on default or short
database passwords, and `/api/docs` is hidden. The page is served on `127.0.0.1:8080` (this computer only); the
`.env` next to `docker-compose.yml` can change `WEB_BIND` / `WEB_PORT`. Changing a database password later needs
`ALTER ROLE` in the database first (explained in the template).

### Accounts and roles

There are no demo accounts, sample files or example data: a new installation holds only the client SVF and its
settings (including the 4 % reference benchmark).

- On a new installation the sign-in page offers **Set up (first account)**: that account becomes the **Super Admin**.
  After that, self sign-up is closed and **Admins create accounts** under **Settings → People and access**.
- A new account's first password is temporary (typed by the Admin, or generated and shown once). The person must
  choose their own password at the first sign-in.
- The **Super Admin** resets passwords (a temporary password, shown once; the person is signed out everywhere) — no one
  can see an existing password, only its one-way fingerprint is stored.

| Role | Can |
|---|---|
| **User** | catalogue, statements, master view, reconciliation, exports, enquiry drafts and responses, processing runs |
| **Admin** | everything a User does, plus: create, change, switch off and delete Users and Admins; verify / reject / move ISRC links; approve enquiries and record their sending; assign follow-ups and dates; close enquiries; client settings; technical details |
| **Super Admin** (one) | everything an Admin does, plus: reset passwords, sign accounts out, the activity log, the reconciliation settings (benchmark, client interest, revenue basis) |

The Super Admin cannot be deleted, switched off or demoted, and nobody can create a second one — the database refuses
it, whatever the application asks. In an exceptional case the server operator can run
`python -m mrm.cli recover-super-admin EMAIL --reason "…"` (audited). Upgrading from 1.0.x maps the earliest active
administrator to Super Admin, other administrators to Admin and everyone else to User.

Click your **initials** (top right) for your profile, role, the **Light / Dark** theme and sign out. After each update a
one-time **What's new** note appears in the bottom-right corner; click it to read the changes. The version is shown
in the bottom-right corner of the footer (**V1.4.4**); click it to read every version's notes.

**Clients:** SVF is set up already. Admins add more under **Settings → Clients → Add a client** (or **Add a new
client** in step 1 of a run): a short code (used in report names, e.g. `ACME-RD-SKV1`), the name and the rights
holders (society member numbers) whose statements belong to the client. **Edit** on a client opens the same pop-up
with all its details; any row can be removed with ×. Admins see every client; a User sees the clients an Admin
granted (Settings → People and access).

**Starting again:** a run that was never published can be deleted with its draft reports (**Reports → Delete**,
or **Delete run** on the run page). Upload the same files to a new run: the stored copies are reused, so nothing is
counted twice, and review decisions stay with the client. Published reports are never deleted; a run that is
processing or publishing must finish first. A deleted run is only hidden: its history stays
in the database and the audit log.

**People** (Settings → People and access): **Add a person** and **Manage** open a pop-up for the name, role, client
access, switching off, deleting and (Super Admin) password reset. Deleting is a soft delete: the account can no longer
sign in, and everything it did keeps its name in the history. Before any shared use, follow the production checklist
and the backup procedure in the system guide (§13–14).

## Screens

| Menu | What it is for |
|---|---|
| Home | The next step, catalogue and statement counts, recent reconciliations, enquiries waiting, my follow-ups |
| Catalogue | Works and their ISRC links, conflicts, import (preview → apply), import history, export |
| Statements | Upload (received from the client or IPRS), the library with statuses and questions, records, error reports |
| Master | Works × platforms with filters and the lines behind every amount; unmatched money; exports |
| Reconciliation | Run a reconciliation; results, exceptions, item review, the report; prepare an enquiry draft |
| Enquiries | Queues (drafts, approval, awaiting response, due, overdue …), follow-ups, each enquiry's workflow and history |
| Reports | The guided processing run and every published master report (SKV numbering) |
| Settings | My profile · People and access · Reconciliation · Platforms · Clients · Activity log · Technical details · Help |

## Develop

```bash
docker run -d --name mrm-devdb -e POSTGRES_PASSWORD=devroot -e POSTGRES_DB=mrm \
  -e MRM_OWNER_PASSWORD=devpass -e MRM_APP_PASSWORD=devpass -p 127.0.0.1:55433:5432 \
  -v $PWD/deploy/postgres/init.sh:/docker-entrypoint-initdb.d/10-init.sh:ro postgres:16-alpine

cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export ENV_FILE=none                             # ignore backend/.env (that one is for Docker); dev defaults apply
.venv/bin/python -m mrm.cli bootstrap            # migrations, client SVF and its 4 % benchmark (nothing else)
.venv/bin/uvicorn mrm.api.app:app --port 8010     # API with an in-process worker thread

cd ../frontend && npm install && API_URL=http://127.0.0.1:8010 npm run dev    # UI on :5173
```

The automated tests and the earlier comparison module (flowchart stages D–H) were removed on 10 October 2026; both
are in the git history (commit `78a205d`, "version 1.0.4").

## Layout

```
backend/mrm/rd/          the platform: catalogue, library (statements), intake, platforms, master, recon,
                         enquiries, overview; and the report engine: rules, names, parsers, detect, engine,
                         verify, excel, store, service, jobs, access
backend/mrm/people.py    accounts (three roles), password resets, the activity log
backend/mrm/api/         routes_auth (sign-in), routes_rd (runs and reports), routes_recon (catalogue, statements,
                         master, reconciliation, enquiries), routes_admin (people, audit, platforms)
backend/mrm/parsing/     safe reading of uploaded workbooks (size and zip checks)
backend/mrm/migrations/  0001-0002 (base tables, audit chain), 0003_rd_platform, 0004_profile, 0005_run_delete,
                         0006_no_approval, 0007_three_roles, 0008_reconciliation
backend/mrm/releases.py  release notes shown once after each update (add an entry with every version change)
frontend/src/            Home, Catalogue, Statements, Master, Reconciliation, Enquiries, Process + Results (runs),
                         Past Reports, Clients, Settings
deploy/postgres/         database logins created on first start
```
