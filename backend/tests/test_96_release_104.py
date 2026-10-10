"""1.0.4: deleting a run that was never published (with its draft reports) and starting again with the same files."""
from __future__ import annotations

from mrm import db
from mrm.rd import jobs
from rdflow import S1, login, process, svf_id, upload


def test_delete_a_draft_run_and_start_again_with_the_same_files():
    sw, viewer = login("swatantra@test.local"), login("viewer@test.local")
    cid = svf_id(sw)
    rid = sw.post("/api/runs", json=dict(client_id=cid, title="start over")).json()["id"]
    upload(sw, rid, S1)
    b = process(sw, rid)
    assert b["state"] == "CHECKED", b["error"]
    draft = next(r for r in b["reports"] if r["kind"] == "MASTER")
    v = sw.get(f"/api/runs/{rid}").json()
    assert v["can_delete"] and v["delete_note"] is None
    assert any(e["run_id"] == rid and e["can_delete"] for e in sw.get("/api/past-reports").json())
    assert viewer.delete(f"/api/runs/{rid}").status_code == 403                       # viewers never delete
    r = sw.delete(f"/api/runs/{rid}")
    assert r.status_code == 200 and "deleted" in r.json()["message"]
    assert all(e["run_id"] != rid for e in sw.get("/api/past-reports").json())
    assert all(x["id"] != rid for x in sw.get("/api/runs").json())
    assert "deleted" in sw.get(f"/api/runs/{rid}").json()["detail"]
    assert sw.get(f"/api/reports/{draft['id']}/download").status_code == 400
    assert sw.delete(f"/api/runs/{rid}").status_code == 400                           # only once
    # a new run may take the same name and the same file: the stored copy is used again
    again = sw.post("/api/runs", json=dict(client_id=cid, title="start over")).json()
    assert again["title"] == "start over"
    assert "uploaded before" in upload(sw, again["id"], S1)[0]["note"]
    assert process(sw, again["id"])["state"] == "CHECKED"
    with db.tx() as conn:                                     # marked, not erased: the audit trail stays complete
        conn.execute("SELECT set_config('app.client_ids', %s, true)", (str(cid),))
        assert db.scalar(conn, "SELECT state FROM rd_run WHERE id = %s", (rid,)) == "DELETED"
        assert db.scalar(conn, "SELECT count(*) FROM rd_build WHERE run_id = %s", (rid,)) == 1
        assert db.scalar(conn, "SELECT count(*) FROM audit_event WHERE action = 'run.deleted'") >= 1


def test_runs_waiting_for_approval_or_published_cannot_be_deleted():
    sw, sh = login("swatantra@test.local"), login("sherley@test.local")
    rid = sw.post("/api/runs", json=dict(client_id=svf_id(sw), title="kept for good")).json()["id"]
    upload(sw, rid, S1)
    b = process(sw, rid)
    assert sw.post(f"/api/builds/{b['id']}/submit").status_code == 200
    r = sw.delete(f"/api/runs/{rid}")
    assert r.status_code == 400 and "waiting for approval" in r.json()["detail"]
    assert sh.post(f"/api/builds/{b['id']}/approve").status_code == 200
    jobs.run_pending()
    assert sh.get(f"/api/builds/{b['id']}").json()["state"] == "PUBLISHED"
    v = sw.get(f"/api/runs/{rid}").json()
    assert not v["can_delete"] and "kept for good" in v["delete_note"]
    r = sw.delete(f"/api/runs/{rid}")
    assert r.status_code == 400 and "kept for good" in r.json()["detail"]
    assert not any(e["can_delete"] for e in sw.get("/api/past-reports").json() if e["run_id"] == rid)
