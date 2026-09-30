"""API layer (§24): the happy path through the REST surface, duplicate upload, RBAC, and a
build blocked by a statement that fails reconciliation."""
import io
import time

import openpyxl
import pytest
from fastapi.testclient import TestClient

from sangam.api.app import app

from .conftest import REF_INPUT, needs_reference
from .test_domain import _type_a

client = TestClient(app)
AN = {"X-User": "t", "X-Role": "analyst"}


def wait(job_id, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timeout")


def xlsx(grid) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in grid:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_health_and_meta():
    assert client.get("/api/health").json()["ok"]
    m = client.get("/api/meta").json()
    assert len(m["statuses"]) == 8 and "B7" in m["basis"]


def test_upload_extract_build_blocked_on_fail():
    b = client.post("/api/batches", json={"label": "api test"}, headers=AN).json()
    good = xlsx(_type_a())
    bad = xlsx(_type_a(total_override=5000.0))
    files = [("files", ("(S-1)Royalty Distribution - P2550 YouTube Pre Claims - July 2025 to September 2025.xlsx", good)),
             ("files", ("(S-2)Royalty Distribution - P2551 Spotify - April 2025 to June 2025.xlsx", bad))]
    up = client.post(f"/api/batches/{b['id']}/files", files=files, headers=AN).json()
    assert [u["detected_kind"] for u in up] == ["STATEMENT_STANDARD", "STATEMENT_STANDARD"]
    again = client.post(f"/api/batches/{b['id']}/files", files=files[:1], headers=AN).json()[0]
    assert again["duplicate"] and again["id"] == up[0]["id"]               # same sha256 -> same file
    j = wait(client.post(f"/api/batches/{b['id']}/extract", headers=AN).json()["job_id"])
    assert j["status"] == "succeeded"
    v = client.get(f"/api/batches/{b['id']}/validation").json()
    assert (v["pass"], v["fail"]) == (1, 1)
    j = wait(client.post(f"/api/batches/{b['id']}/builds", json={}, headers=AN).json()["job_id"])
    assert j["status"] == "failed" and "reconciliation" in j["message"]    # a FAIL blocks the build
    j = wait(client.post(f"/api/batches/{b['id']}/builds", json={"force": True}, headers=AN).json()["job_id"])
    assert j["status"] == "succeeded"
    bid = j["result"]["build_id"]
    rows = client.get(f"/api/builds/{bid}/rows").json()
    assert all(isinstance(r["isrcs"], list) and isinstance(r["works"], list) for r in rows)   # arrays, never pipes


@needs_reference
def test_reference_surface(ref):
    base = ref["base"]
    r = client.get(f"/api/builds/{base}/rows", params={"q": "INS2X2209002"})
    assert r.status_code == 200 and int(r.headers["X-Total-Count"]) >= 1
    row = client.get(f"/api/builds/{base}/rows/{r.json()[0]['id']}").json()
    assert row["distributions"] and row["isrcs"]
    cov = client.get(f"/api/coverage/{ref['coverage']['reference']}/rows").json()
    assert len(cov) == 93
    ex = client.get(f"/api/coverage/{ref['coverage']['reference']}/explain", params={"row_id": cov[0]["id"]}).json()
    assert ex["trace"]
    cands = client.get(f"/api/builds/{base}/merge-candidates", params={"kind": "SAME_NAME_DIFF_INTERNAL_NO"}).json()
    assert cands and cands[0]["members"]
    denied = client.post(f"/api/builds/{base}/merge-decisions", json=[{"candidate_id": cands[0]["id"], "verdict": "MERGE"}],
                         headers={"X-Role": "viewer"})
    assert denied.status_code == 403
    mm = client.get(f"/api/mismatch/{ref['mismatch']}/rows", params={"kind": "Different ISRC"})
    assert mm.headers["X-Total-Count"] == "245"
    assert client.get("/api/reference-check").json()["rows"]
