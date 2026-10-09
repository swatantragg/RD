"""Sign-in, CSRF, server-side permissions, exact money in JSON, tamper-evident audit."""
from __future__ import annotations

import psycopg
from fastapi.testclient import TestClient

from conftest import ADMIN, DBNAME
from mrm import audit, db
from mrm.api.app import app


def _login(email, password="test-password-1"):
    c = TestClient(app)
    r = c.post("/api/auth/login", json=dict(email=email, password=password))
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf"]
    return c


def test_login_csrf_and_permissions(client_id):
    c = TestClient(app)
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json=dict(email="devi@test.local", password="wrong-password")).status_code == 401
    v = _login("viewer@test.local")
    assert v.get("/api/clients").status_code == 200
    r = v.post("/api/compare/rules", json=dict(rule_key="X", values=dict(name="x", method="MRM_BENCHMARK"), reason="r"))
    assert r.status_code == 403                                                 # server refuses, not just the screen
    s = _login("swatantra@test.local")
    del s.headers["X-CSRF-Token"]
    assert s.post(f"/api/compare/identity/{client_id}/refresh").status_code == 403      # missing CSRF token


def test_money_is_exact_text(client_id):
    s = _login("accounts@test.local")
    r = s.post("/api/compare/rules", json=dict(client_id=client_id, rule_key="EXACT", reason="test",
                                       values=dict(name="exact", method="MRM_BENCHMARK", rate="0.06", tolerance="0.10")))
    assert r.status_code == 200
    assert r.json()["rate"] == "0.06000000" and isinstance(r.json()["tolerance"], str)


def test_audit_chain_detects_tampering():
    with db.tx() as conn:
        audit.record(conn, "test.event", None, "x", 1, dict(a=1))
        assert audit.verify_chain(conn)["ok"]
    with psycopg.connect(ADMIN.rsplit("/", 1)[0] + f"/{DBNAME}", autocommit=True) as su:
        su.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_append_only")
        su.execute("UPDATE audit_event SET detail = '{\"a\": 2}' WHERE action = 'test.event'")
        su.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_append_only")
    with db.tx() as conn:
        assert audit.verify_chain(conn)["ok"] is False
    with psycopg.connect(ADMIN.rsplit("/", 1)[0] + f"/{DBNAME}", autocommit=True) as su:
        su.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_append_only")
        su.execute("UPDATE audit_event SET detail = '{\"a\": 1}' WHERE action = 'test.event'")
        su.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_append_only")


def test_app_login_cannot_rewrite_history():
    with db.tx() as conn:
        try:
            conn.execute("DELETE FROM audit_event")
            raise AssertionError("delete should be refused")
        except psycopg.errors.InsufficientPrivilege:
            pass
