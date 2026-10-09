"""1.0.3: deleting people without recorded work, confirming a new password, and the one-time demo clean-up."""
from __future__ import annotations

import psycopg

from conftest import ADMIN, DBNAME
from mrm import db, seed
from rdflow import login, svf_id


def test_delete_person_only_without_recorded_work():
    admin, sw = login("admin@test.local"), login("swatantra@test.local")
    with db.tx() as conn:
        tmp = seed.create_user(conn, "temp.person@test.local", "Temp Person", ["viewer"], "temp-password-1")
    assert sw.delete(f"/api/people/{tmp}").status_code == 403                        # administrators only
    assert admin.delete(f"/api/people/{tmp}").status_code == 200
    with db.tx() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM app_user WHERE id = %s", (tmp,)) == 0
        worker = db.scalar(conn, "SELECT id FROM app_user WHERE email = 'swatantra@test.local'")
    r = admin.delete(f"/api/people/{worker}")                                          # has runs and uploads
    assert r.status_code == 400 and "Switch it off" in r.json()["detail"]
    me = admin.get("/api/auth/me").json()["id"]
    assert admin.delete(f"/api/people/{me}").status_code == 400


def test_new_password_must_be_typed_twice_the_same():
    c = login("devi@test.local")
    r = c.patch("/api/me", json=dict(current_password="test-password-1", new_password="another-password-1",
                                     confirm_password="another-password-2"))
    assert r.status_code == 400 and "not the same" in r.json()["detail"]


def test_purge_demo_keeps_one_account_with_every_role():
    from mrm.maintenance import purge_demo
    sw = login("swatantra@test.local")
    with db.tx() as conn:
        demo = seed.create_user(conn, "swatantra@mrm.local", "Old demo", ["importer"], "mrm-demo-2026")
        conn.execute("SELECT set_config('app.client_ids', %s, true)", (str(svf_id(sw)),))
        run = db.insert(conn, "rd_run", dict(client_id=svf_id(sw), title="made with the demo login", created_by=demo))
        seed.create_user(conn, "keeper@test.local", "Keeper", ["viewer"], "keeper-password-1")
    out = purge_demo("keeper@test.local", echo=lambda *_: None)
    assert out["deleted_accounts"] >= 1 and out["moved_records"] >= 1
    with psycopg.connect(ADMIN.rsplit("/", 1)[0] + f"/{DBNAME}") as su:
        kept = su.execute("SELECT id FROM app_user WHERE email = 'keeper@test.local'").fetchone()[0]
        assert su.execute("SELECT created_by FROM rd_run WHERE id = %s", (run,)).fetchone()[0] == kept
        assert su.execute("SELECT count(*) FROM app_user WHERE email LIKE '%%@mrm.local'").fetchone()[0] == 0
        roles = {r[0] for r in su.execute("SELECT role FROM user_role WHERE user_id = %s", (kept,))}
        assert {"admin", "importer", "rights_reviewer", "accounts", "approver"} <= roles
        assert su.execute("SELECT count(*) FROM comparison_run").fetchone()[0] == 0
        assert su.execute("SELECT action FROM audit_event ORDER BY id DESC LIMIT 1").fetchone()[0] == "maintenance.demo_purged"
    from mrm import audit
    with db.tx() as conn:
        assert audit.verify_chain(conn)["ok"]
