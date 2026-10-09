"""Helpers that drive the royalty platform through its HTTP API, the way the screens do."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mrm import config
from mrm.api.app import app

REF = config.REPO_ROOT / "Docs" / "input"
OUT = config.REPO_ROOT / "Docs" / "output"
S1 = REF / "batch-1" / "(S-1)Royalty Distribution - M2506 For MUSREK - Collectiones during F.Y. 2025-26 - Mechanical.xlsx"
S16 = REF / "batch-1" / ("(S-16)Royalty Distribution - P2555 Collections from Overseas Societies - April 2024 to March "
                         "2025 - 026 CASH.xlsx")
S32 = REF / "batch-1" / ("(S-32)Royalty Distribution - P2577 YouTube Post Claims - for the Period - April 2025 To June "
                         "2025 -.xlsx")
S44 = REF / "batch-1" / "(S-44)Royalty Redistribution - for P2101 to P2550 - SVF ENTERTAINMENT PRIVATE LIMITED.xlsx"
S45 = REF / "batch-1" / "(S-45)Royalty Redistribution - for P2101 to P2550 - SVF ENTERTAINMENT PRIVATE LIMITED_1.xlsx"
SPOT_IPRS = REF / "batch-2" / "Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx"
MRM = REF / "batch-3(Only spotify RD)" / "Raw_Spotify_MRM_Oct25_Mar26.xlsx"
L6M = REF / "batch-3(Only spotify RD)" / "Spotify L6M.xlsx"
S46 = REF / "batch-1" / "(S-46)SVF list of Song -April 2026.xlsx"
REVIEW = REF / "batch-4" / "Songs-Missing-From-SVF-List_Updated.xlsx"
SKV8 = OUT / "batch3-output(Only Spotify RD)" / "SVF-RD-SKV8.xlsx"
NON_SVF_REF = OUT / "batch4-output" / "Non-SVF-Works-Revenue-From-IPRS-And-Spotify.xlsx"
MISSING_REF = OUT / "batch4-output" / "Missing-Songs-Revenue-From-IPRS-And-Spotify.xlsx"


def login(email: str, password: str = "test-password-1") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json=dict(email=email, password=password))
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf"]
    return c


def svf_id(c: TestClient) -> int:
    return next(x["id"] for x in c.get("/api/clients").json() if x["code"] == "SVF")


def upload(c: TestClient, run_id: int, *paths: Path, names: list[str] | None = None) -> list[dict]:
    files = [("files", ((names[i] if names else p.name), p.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
             for i, p in enumerate(paths)]
    r = c.post(f"/api/runs/{run_id}/files", files=files)
    assert r.status_code == 200, r.text
    return r.json()


def process(c: TestClient, run_id: int) -> dict:
    from mrm.rd import jobs
    r = c.post(f"/api/runs/{run_id}/process")
    assert r.status_code == 200, r.text
    jobs.run_pending()
    b = c.get(f"/api/builds/{r.json()['build_id']}").json()
    return b


def report(b: dict, kind: str) -> dict:
    return next(r for r in b["reports"] if r["kind"] == kind)
