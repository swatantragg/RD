"""Test helper for the earlier comparison module (moved out of the application in 1.0.1): an end-to-end walk
through the reference files in Docs/input, played through the real services by the people named on page 9."""
from __future__ import annotations

import datetime as dt
from mrm import audit, compare, config, db, identity, intake, packs, rules
from mrm.normalize import similarity

FILES = [
    ("batch-1/(S-46)SVF list of Song -April 2026.xlsx", "catalogue"),
    ("batch-4/Songs-Missing-From-SVF-List_Updated.xlsx", "catalogue additions"),
    ("batch-2/Spotify - for the Period October 2025 to March 2026(from IPRS).xlsx", "IPRS Spotify statement"),
    ("batch-3(Only spotify RD)/Raw_Spotify_MRM_Oct25_Mar26.xlsx", "MRM Spotify revenue"),
    ("batch-3(Only spotify RD)/Spotify L6M.xlsx", "Spotify streams"),
]
REVIEWED = "demo walkthrough - reviewer decision recorded for the demonstration"


def actor(conn, email: str) -> dict:
    u = db.one(conn, "SELECT id, email, name FROM app_user WHERE email = %s", (email,))
    u["roles"] = [r["role"] for r in db.all(conn, "SELECT role FROM user_role WHERE user_id = %s", (u["id"],))]
    return u


def run_demo(echo=print) -> dict:
    root = config.settings.reference_input
    with db.tx() as conn:
        if db.scalar(conn, "SELECT count(*) FROM comparison_run r JOIN client c ON c.id = r.client_id WHERE "
                           "c.code = 'SVF'"):
            echo("  demo already loaded")
            return {}
        cid = db.scalar(conn, "SELECT id FROM client WHERE code = 'SVF'")
        sw, devi, acc, sher = (actor(conn, e) for e in ("swatantra@test.local", "devi@test.local", "accounts@test.local",
                                                         "sherley@test.local"))
    ids = {}
    for rel, label in FILES:
        p = root / rel
        if not p.exists():
            echo(f"  skipped {label}: {p} not found")
            continue
        with db.tx() as conn:
            r = intake.upload(conn, sw, cid, p.name, p.read_bytes(), batch_code="SPOTIFY-OCT25-MAR26")
        ids[label] = r["id"]
        echo(f"  A/B {label}: file #{r['id']} -> {r['status']}{' (' + r['hold_reason'] + ')' if r['hold_reason'] else ''}")
    with db.tx() as conn:
        if "MRM Spotify revenue" in ids:                                 # B3: Swatantra confirms what the file omits
            r = intake.set_meta(conn, sw, ids["MRM Spotify revenue"], dict(territory="IN", currency="INR", basis="NET",
                                                                           share="1", sender="MRM",
                                                                           payer="Spotify via distributor"))
            echo(f"  B3 revenue metadata confirmed -> {r['status']}")
        if "Spotify streams" in ids:
            r = intake.set_meta(conn, sw, ids["Spotify streams"], dict(territory="IN", sender="MRM"))
            echo(f"  B3 streams metadata confirmed -> {r['status']}")
    with db.tx() as conn:                                                # B4: accounts approves alternative controls
        for label in ("MRM Spotify revenue", "Spotify streams"):
            if label not in ids:
                continue
            f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (ids[label],))
            t = "recording_line" if f["income_type"] == "RECORDING" else "usage_line"
            col = "amount" if t == "recording_line" else "streams"
            independent = db.scalar(conn, f"SELECT sum({col}) FROM {t} WHERE file_id = %s", (f["id"],))
            r = intake.approve_control(conn, acc, f["id"], str(independent),
                                       "demo: independently re-summed from the supplier's raw report (no printed total)")
            echo(f"  B4 {label}: alternative control approved -> {r['status']}")
    with db.tx() as conn:                                                # B5: identical rows decided with evidence
        for label in ("MRM Spotify revenue", "Spotify streams"):
            f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (ids.get(label, 0),))
            if f and f["status"] == "DUPLICATE_REVIEW" and not (f["decisions"] or {}).get("overlaps"):
                r = intake.decide_row_duplicates(conn, acc, f["id"], "RETAIN",
                                                 "demo: identical rows come from different releases (album / UPC) - "
                                                 "legitimate repeated usage")
                echo(f"  B5 {label}: identical rows retained as legitimate -> {r['status']}")
    with db.tx() as conn:
        for label in ("catalogue", "catalogue additions"):
            if label in ids:
                f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (ids[label],))
                if f["status"] == "DATA_EXCEPTION" and f["rows_invalid"]:
                    r = intake.accept_row_exceptions(conn, sw, f["id"], "rows without a usable work code or ISRC stay "
                                                                        "listed and are excluded from the link table")
                    echo(f"  B3 {label}: {f['rows_invalid']} invalid row(s) accepted as exclusions -> {r['status']}")
        st = {r["id"]: r["status"] for r in db.all(conn, "SELECT id, status FROM source_file")}
        echo(f"  file statuses: {st}")

    # C - identities
    with db.tx() as conn:
        r = identity.refresh(conn, cid, devi)
        echo(f"  C1 registers: {r['compositions']} works, {r['recordings']} recordings, {r['links_approved']} approved "
             f"links, {r['issues_open']} open issues, {r['candidates_pending']} duplicate candidates")
    with db.tx() as conn:
        n_conf = n_link = 0
        for i in db.all(conn, "SELECT * FROM identity_issue WHERE client_id = %s AND status = 'OPEN' AND kind = "
                              "'ISRC_CONFLICT' ORDER BY amount DESC NULLS LAST", (cid,)):
            works = i["detail"]["works"]
            scored = sorted(((similarity(i["title"], w["title"]), w) for w in works), key=lambda x: -x[0])
            if len(scored) > 1 and scored[0][0] >= 0.9 and scored[0][0] - scored[1][0] >= 0.3:
                identity.resolve_conflict(conn, devi, i["id"], [dict(link_id=w["link_id"], keep=w is scored[0][1])
                                                                for _, w in scored],
                                          f"{REVIEWED}: recording title '{i['title']}' matches work "
                                          f"'{scored[0][1]['title']}'; other catalogue entry rejected for this ISRC")
                n_conf += 1
        for i in db.all(conn, "SELECT * FROM identity_issue WHERE client_id = %s AND status = 'OPEN' AND kind = "
                              "'UNMAPPED_RECORDING' ORDER BY amount DESC NULLS LAST", (cid,)):
            cands = i["detail"].get("candidates") or []
            if len(cands) >= 1 and cands[0]["score"] >= 0.97 and (len(cands) == 1 or cands[1]["score"] < 0.9):
                rec = db.scalar(conn, "SELECT id FROM recording WHERE client_id = %s AND isrc = %s", (cid, i["subject_key"]))
                identity.link(conn, devi, cid, cands[0]["composition_id"], rec,
                              f"{REVIEWED}: single strong title candidate ({cands[0]['score']})", issue_id=i["id"])
                identity.resolve_issue(conn, devi, i["id"], f"linked to work {cands[0]['work_code']}")
                n_link += 1
        echo(f"  C2/C3 Devi resolved {n_conf} ISRC conflicts and linked {n_link} unmapped recordings (others stay open)")
    with db.tx() as conn:
        identity.refresh(conn, cid, devi)
        cands = db.all(conn, "SELECT id FROM duplicate_candidate WHERE client_id = %s AND status = 'PENDING' ORDER BY id",
                       (cid,))
        for k, c in enumerate(cands):
            identity.decide_candidate(conn, devi, c["id"], "SEPARATE" if k == 0 else "DEFERRED",
                                      f"{REVIEWED}: distinct IPRS work codes kept separate pending registration check")
        echo(f"  C4 {len(cands)} duplicate candidate(s) decided (first kept separate, rest deferred to review)")
        v = identity.approve_version(conn, devi, cid, "demo: first approved identity version")
        echo(f"  C5 identity version: {'v' + str(v.get('version_no')) if v['ok'] else 'REBUILD HOLD'} "
             f"{v['counts']}")
        conn.execute("UPDATE client SET mandate_verified = TRUE, mandate_ref = %s, mandate_from = %s WHERE id = %s",
                     ("IPRS membership 5154290 - publisher (demo record)", dt.date(2020, 4, 1), cid))
        audit.record(conn, "client.mandate_verified", devi, "client", cid, dict(ref="IPRS membership 5154290"))
    # E - the 6% MRM benchmark, drafted by accounts and approved by Sherley
    with db.tx() as conn:
        rid = rules.draft(conn, acc, None, "MRM-6PCT", dict(
            name="MRM 6% screening benchmark", method="MRM_BENCHMARK", rate="0.06",
            denominator="the client's net recording revenue from the platform for the usage period, as reported by "
                        "its distributor", revenue_basis="NET", share_treatment="BENEFICIARY_SPECIFIC",
            platforms=[], territories=["IN"], use_types=["AUDIO_STREAMING"], currency="INR",
            effective_from="2025-04-01", tolerance="1.00", owner_id=acc["id"],
            formula="B = R x 0.06 (beneficiary-specific); V = B - P"),
            "Sherley's 6% retained as a configurable MRM screening assumption (page 1, page 13 item 2)")
        rules.approve(conn, sher, rid)
        echo("  E  rule MRM-6PCT v1 drafted by accounts, approved by Sherley")
    with db.tx() as conn:
        res = compare.run(conn, sw, cid, "Spotify", "IN", "AUDIO_STREAMING", "PERFORMING", "2025-10-01", "2026-03-31",
                          "2026-10-01")
        echo(f"  D-G run v{res['version_no']}: {res['summary']['groups']} groups {res['summary']['outcomes']}")
    with db.tx() as conn:
        p = packs.build(conn, sw, res["run_id"])
        echo(f"  H1 pack v{p['version_no']} built ({len(p['case_codes'])} enquiry cases), awaiting Sherley's approval")
    return dict(run_id=res["run_id"], pack_id=p["id"])

