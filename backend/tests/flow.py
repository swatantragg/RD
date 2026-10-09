"""Drive the real services the way the screens do, with the page-9 people."""
from __future__ import annotations

from decimal import Decimal

from mrm import compare, db, identity, intake, rules

OCT = ("2025-10-01", "2025-10-31")
STMT_OCT = "Spotify - for the Period October 2025 to October 2025.xlsx"


def upload(people, client_id, name, data, **meta):
    with db.tx() as conn:
        return intake.upload(conn, people["swatantra"], client_id, name, data, batch_code="T", meta=meta or None)


def confirm_revenue(people, fid, **over):
    m = dict(territory="IN", currency="INR", basis="NET", share="1")
    m.update(over)
    with db.tx() as conn:
        intake.set_meta(conn, people["swatantra"], fid, {k: v for k, v in m.items() if v is not None})
        f = db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,))
        if f["status"] == "RECONCILIATION_HOLD":
            t = "recording_line" if f["income_type"] == "RECORDING" else "usage_line"
            col = "amount" if t == "recording_line" else "streams"
            total = db.scalar(conn, f"SELECT sum({col}) FROM {t} WHERE file_id = %s", (fid,))
            intake.approve_control(conn, people["accounts"], fid, str(total), "test: independently checked total")
        return db.one(conn, "SELECT * FROM source_file WHERE id = %s", (fid,))


def approve_identity(people, client_id, decide="SEPARATE"):
    with db.tx() as conn:
        identity.refresh(conn, client_id, people["devi"])
        for c in db.all(conn, "SELECT id FROM duplicate_candidate WHERE client_id = %s AND status = 'PENDING'",
                        (client_id,)):
            identity.decide_candidate(conn, people["devi"], c["id"], decide, "test decision")
        return identity.approve_version(conn, people["devi"], client_id, "test version")


def rule(people, client_id, **over):
    v = dict(name="MRM 6% screening benchmark", method="MRM_BENCHMARK", rate="0.06",
             denominator="net recording revenue for the usage period", revenue_basis="NET",
             share_treatment="BENEFICIARY_SPECIFIC", territories=["IN"], use_types=["AUDIO_STREAMING"], currency="INR",
             effective_from="2025-04-01", tolerance="1.00", owner_id=people["accounts"]["id"])
    v.update(over)
    with db.tx() as conn:
        rid = rules.draft(conn, people["accounts"], client_id, "MRM-6PCT", v, "test rule")
        rules.approve(conn, people["sherley"], rid)
        return rid


def run(people, client_id, period=OCT, cutoff="2026-10-01"):
    with db.tx() as conn:
        r = compare.run(conn, people["swatantra"], client_id, "Spotify", "IN", "AUDIO_STREAMING", "PERFORMING",
                        period[0], period[1], cutoff)
        r["groups"] = {g["work_code"]: g for g in db.all(conn, "SELECT * FROM comparison_group WHERE run_id = %s",
                                                         (r["run_id"],))}
        r["exceptions"] = db.all(conn, "SELECT * FROM run_exception WHERE run_id = %s", (r["run_id"],))
        r["checks"] = r["checks"]
        return r


def D(x) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def member(client_id):
    with db.tx() as conn:
        c = db.one(conn, "SELECT * FROM client WHERE id = %s", (client_id,))
    return c["member_id"], c["beneficiary_name"]
