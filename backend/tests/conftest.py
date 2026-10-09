"""Each test session gets a throw-away database (created through the PostgreSQL superuser), migrated by the owner
login and used through the application login - the same split as production."""
from __future__ import annotations

import io
import os
import tempfile
from decimal import Decimal

import openpyxl
import psycopg
import pytest

os.environ.setdefault("LEGACY_COMPARISON", "true")     # the flowchart comparison module keeps its own tests
os.environ.setdefault("RD_WORKER", "off")              # tests run background jobs explicitly (jobs.run_pending)

ADMIN = os.environ.get("TEST_ADMIN_URL", "postgresql://postgres:devroot@127.0.0.1:55433/postgres")
HOSTPART = ADMIN.split("@", 1)[1].rsplit("/", 1)[0]
DBNAME = "mrm_test"


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(ADMIN, autocommit=True) as c:
        for role, pw in (("mrm_owner", "devpass"), ("mrm_app", "devpass")):
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                c.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{pw}'")
        c.execute(f"DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {DBNAME} OWNER mrm_owner")
    with psycopg.connect(ADMIN.rsplit("/", 1)[0] + f"/{DBNAME}", autocommit=True) as c:
        c.execute("ALTER SCHEMA public OWNER TO mrm_owner")
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    os.environ["DATABASE_URL"] = f"postgresql://mrm_app:devpass@{HOSTPART}/{DBNAME}"
    os.environ["MIGRATOR_DATABASE_URL"] = f"postgresql://mrm_owner:devpass@{HOSTPART}/{DBNAME}"
    os.environ["STORAGE_ROOT"] = tempfile.mkdtemp(prefix="mrm-test-")
    os.environ["DEMO_PASSWORD"] = "test-password-1"
    from mrm import config, db, migrate, seed
    config.reload()
    db.reset()
    migrate.apply(config.settings.migrator_database_url, echo=lambda *_: None)
    seed.seed(echo=lambda *_: None)
    with db.tx() as conn:                          # the people the tests act as (the application seeds nobody)
        for email, name, roles in PEOPLE:
            uid = seed.create_user(conn, email, name, roles, "test-password-1")
            conn.execute("INSERT INTO client_grant (user_id, client_id) SELECT %s, id FROM client WHERE code = 'SVF'",
                         (uid,))
    yield
    db.reset()


PEOPLE = [
    ("admin@test.local", "Test Administrator", ["admin"]),
    ("swatantra@test.local", "Swatantra", ["importer"]),
    ("devi@test.local", "Devi", ["rights_reviewer"]),
    ("accounts@test.local", "Accounts", ["accounts"]),
    ("sherley@test.local", "Sherley Singh", ["approver", "sender"]),
    ("viewer@test.local", "Read-only viewer", ["viewer"]),
]


@pytest.fixture
def people():
    from mrm import db
    from legacy_walkthrough import actor
    with db.tx() as conn:
        return {k: actor(conn, f"{k}@test.local") for k in ("swatantra", "devi", "accounts", "sherley", "admin", "viewer")}


_n = [0]


@pytest.fixture
def client_id():
    """A fresh client per test (verified mandate, IPRS member 9000xxx) so tests never share data."""
    from mrm import db
    _n[0] += 1
    code = f"T{_n[0]:03d}"
    with db.tx() as conn:
        return db.insert(conn, "client", dict(code=code, name=f"Test Music {code} Private Limited", kind="PUBLISHER",
                                              member_id=f"9000{_n[0]:03d}", beneficiary_name=f"TEST MUSIC {code} PVT LTD",
                                              mandate_verified=True, territories=["IN"], collection_route="IPRS"))


# ------------------------------------------------------------------ workbook builders
def xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def statement(member: str, beneficiary: str, works: list[tuple], total=None) -> bytes:
    """works: (work_code, title, amount, pool='INTERNET WEBSITE', source='SPOTIFY AB'); amount None = blank."""
    rows = [["INTERNAL NO", member, "IPI NAME NO", "00000000001"], ["NAME", beneficiary + ", ", "IPI BASE NO", "I-0"], [],
            ["WORK INT NO", "TITLE", "AV", "LANGUAGE", "NAME", "ROLE", "SOCIETY", "OWN", "COLL", "POOL", "SOURCE",
             "ROYALTY AMT"]]
    t = Decimal(0)
    last = None
    for w in works:
        code, title, amt = w[0], w[1], w[2]
        pool = w[3] if len(w) > 3 else "INTERNET WEBSITE"
        src = w[4] if len(w) > 4 else "SPOTIFY AB"
        if code != last:
            rows.append([int(code), title, None, "BENGALI", "COMPOSER, A", "C", "IPRS", 25, 25, None, None, None])
            last = code
        rows.append([None, None, None, None, beneficiary, "E", "IPRS", 50, 50, pool, src,
                     None if amt is None else Decimal(str(amt))])
        rows.append([None] * 11 + [None if amt is None else Decimal(str(amt))])
        t += Decimal(str(amt or 0))
    rows.append([None] * 7 + ["TOTAL ROYALTIES", None, None, None, Decimal(str(total)) if total is not None else t])
    return xlsx(rows)


def revenue(lines: list[tuple], platform="Spotify", currency_col=None) -> bytes:
    """lines: (month 'YYYY-MM', isrc, title, amount)"""
    import datetime as dt
    head = ["Month", "Client", "Content Type", "Content Name", "Album name", "ISRC", "UPC", "Revenue"]
    if currency_col:
        head.append("Currency")
    rows = [head]
    for m, isrc, title, amt in lines:
        y, mo = m.split("-")
        r = [dt.datetime(int(y), int(mo), 1), platform, "App_Music", title, "Album", isrc, 890000000001,
             None if amt is None else Decimal(str(amt))]
        if currency_col:
            r.append(currency_col)
        rows.append(r)
    return xlsx(rows)


def usage(lines: list[tuple], platform="Spotify") -> bytes:
    import datetime as dt
    rows = [["Month", "Client", "Content Name", "Album name", "ISRC", "UPC", "Usage"]]
    for m, isrc, title, n in lines:
        y, mo = m.split("-")
        rows.append([dt.datetime(int(y), int(mo), 1), platform, title, "Album", isrc, 890000000001, n])
    return xlsx(rows)


def catalogue(entries: list[tuple]) -> bytes:
    """entries: (title, work_code, 'ISRC1|ISRC2')"""
    return xlsx([["Track Name", "Internal NO", "ISRC"], *[[t, int(w), i] for t, w, i in entries]])


MONTHS6 = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
