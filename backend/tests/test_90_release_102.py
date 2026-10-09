"""1.0.2: clients added by preparers, the one-time 'what's new' note, and My profile."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mrm import __version__, config, releases
from mrm.api.app import app
from rdflow import login


def test_versions_agree_and_notes_exist():
    pkg = json.loads((config.REPO_ROOT / "frontend" / "package.json").read_text())
    assert pkg["version"] == __version__ == releases.RELEASES[0]["version"]
    assert all(r["summary"] and r["points"] for r in releases.RELEASES)


def test_unseen_notes():
    assert [r["version"] for r in releases.unseen(None)] == [__version__]
    assert [r["version"] for r in releases.unseen("1.0.2")] == ["1.0.3"]
    assert [r["version"] for r in releases.unseen("1.0.0")] == ["1.0.3", "1.0.2", "1.0.1"]
    assert releases.unseen(__version__) == []


def test_whats_new_is_shown_once_per_person():
    c = login("devi@test.local")
    me = c.get("/api/auth/me").json()
    assert me["whats_new"] and me["whats_new"][0]["version"] == __version__
    assert c.post("/api/me/seen").status_code == 200
    assert c.get("/api/auth/me").json()["whats_new"] == []
    assert login("devi@test.local").get("/api/auth/me").json()["whats_new"] == []     # another browser: not again
    n = TestClient(app)
    r = n.post("/api/auth/signup", json=dict(name="New Person", email="new.person@test.local", password="new-person-pw-1"))
    assert [x["version"] for x in r.json()["whats_new"]] == [__version__]             # a new account sees the current note once
    n.headers["X-CSRF-Token"] = r.json()["csrf"]
    n.post("/api/me/seen")
    assert n.get("/api/auth/me").json()["whats_new"] == []


def test_my_profile_name_and_password():
    c = login("accounts@test.local")
    r = c.patch("/api/me", json=dict(name="Accounts Team"))
    assert r.status_code == 200 and r.json()["name"] == "Accounts Team"
    r = c.patch("/api/me", json=dict(current_password="wrong-password", new_password="a-new-password-1"))
    assert r.status_code == 400 and "current password" in r.json()["detail"]
    r = c.patch("/api/me", json=dict(current_password="test-password-1", new_password="short"))
    assert r.status_code == 400
    assert c.patch("/api/me", json=dict(current_password="test-password-1", new_password="a-new-password-1")).status_code == 200
    login("accounts@test.local", "a-new-password-1")
    c.patch("/api/me", json=dict(current_password="a-new-password-1", new_password="test-password-1"))


def test_preparers_add_clients_and_work_on_them():
    sw, viewer, admin = login("swatantra@test.local"), login("viewer@test.local"), login("admin@test.local")
    r = sw.post("/api/clients", json=dict(code="ACME", name="Acme Music Private Limited",
                                          holders=[dict(member_no="7000001", name="ACME MUSIC PRIVATE LIMITED")]))
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["output_prefix"] == "ACME-RD-SKV" and c["next_generation"] == 1 and c["holders"][0]["member_no"] == "7000001"
    assert any(x["code"] == "ACME" for x in sw.get("/api/clients").json())            # the person who added it can work on it
    assert sw.post("/api/runs", json=dict(client_id=c["id"])).status_code == 200
    assert any(x["code"] == "ACME" for x in viewer.get("/api/clients").json())         # viewers follow every client
    assert viewer.post("/api/clients", json=dict(code="NOPE", name="Nope")).status_code == 403
    r = sw.post("/api/clients", json=dict(code="ACME", name="Again"))
    assert r.status_code == 400 and "already exists" in r.json()["detail"]
    assert sw.patch(f"/api/clients/{c['id']}", json=dict(name="Acme Music Pvt Ltd")).json()["name"] == "Acme Music Pvt Ltd"
    assert sw.patch(f"/api/clients/{c['id']}", json=dict(active=False)).status_code == 403   # switching off: admin only
    assert admin.patch(f"/api/clients/{c['id']}", json=dict(active=True)).status_code == 200
    svf = next(x for x in sw.get("/api/clients").json() if x["code"] == "SVF")
    assert svf["name"] == "SVF Entertainment Private Limited"                              # SVF stays as it is
