"""Creating an account: the first one administers, later ones follow everyone's work and download published reports
(named with their own name); sign-up can be switched off."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from mrm import config, db
from mrm.api.app import app
from rdflow import S1, login, process, svf_id, upload


def _signup(name, email, password="a-good-password-1"):
    c = TestClient(app)
    r = c.post("/api/auth/signup", json=dict(name=name, email=email, password=password))
    if r.status_code == 200:
        c.headers["X-CSRF-Token"] = r.json()["csrf"]
    return c, r


def test_signup_rules_and_switch(monkeypatch):
    assert TestClient(app).get("/api/auth/options").json()["signup"] is True
    _, r = _signup("Short", "short@test.local", "too-short")
    assert r.status_code == 400 and "10 characters" in r.json()["detail"]
    _, r = _signup("Bad", "not-an-email")
    assert r.status_code == 400
    _, r = _signup("Again", "viewer@test.local")
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, allow_signup=False))
    _, r = _signup("Closed", "closed@test.local")
    assert r.status_code == 403


def test_first_account_administers_later_accounts_view_everything():
    with db.tx() as conn:
        admins = [r["id"] for r in db.all(conn, "SELECT u.id FROM app_user u JOIN user_role r ON r.user_id = u.id "
                                                "WHERE r.role = 'admin' AND u.active")]
        conn.execute("UPDATE app_user SET active = FALSE WHERE id = ANY(%s)", (admins,))
    try:
        first, r = _signup("First Person", "first@test.local")
        assert r.status_code == 200 and set(r.json()["roles"]) == {"admin", "importer"}
        second, r = _signup("Second Person", "second@test.local")
        assert r.json()["roles"] == ["viewer"] and r.json()["can"]["prepare"] is False
    finally:
        with db.tx() as conn:
            conn.execute("UPDATE app_user SET active = TRUE WHERE id = ANY(%s)", (admins,))
            conn.execute("UPDATE app_user SET active = FALSE WHERE email = 'first@test.local'")
    # user 1 does the work; user 2 follows it and downloads the published end result under their own name
    sw, sh = login("swatantra@test.local"), login("sherley@test.local")
    rid = sw.post("/api/runs", json=dict(client_id=svf_id(sw), title="for the viewer")).json()["id"]
    upload(sw, rid, S1)
    b = process(sw, rid)
    assert second.get(f"/api/runs/{rid}").status_code == 200                 # sees the work in progress
    master = next(x for x in b["reports"] if x["kind"] == "MASTER")
    assert second.get(f"/api/reports/{master['id']}/download").status_code == 403   # drafts: no
    assert second.post(f"/api/runs/{rid}/process").status_code == 403
    sw.post(f"/api/builds/{b['id']}/submit")
    sh.post(f"/api/builds/{b['id']}/approve")
    from mrm.rd import jobs
    jobs.run_pending()
    final = next(x for x in second.get(f"/api/builds/{b['id']}").json()["reports"] if x["kind"] == "MASTER")
    r = second.get(f"/api/reports/{final['id']}/download")
    assert r.status_code == 200
    assert '_Second-Person.xlsx"' in r.headers["content-disposition"]


@pytest.mark.parametrize("email", ["swatantra@mrm.local", "sherley@mrm.local"])
def test_retired_demo_accounts_cannot_sign_in(email):
    from mrm import seed
    with db.tx() as conn:
        seed.create_user(conn, email, "Old demo", ["approver"], "mrm-demo-2026")
        seed.retire_demo_accounts(conn)
    r = TestClient(app).post("/api/auth/login", json=dict(email=email, password="mrm-demo-2026"))
    assert r.status_code == 401
