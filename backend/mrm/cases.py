"""H4-H5: replies, promised adjustments, payments and closure. Every change is a new case event; nothing is
overwritten or deleted, so a resolved case keeps its whole history."""
from __future__ import annotations

import datetime as dt

from . import audit, db
from .normalize import amount, as_date, s
from .packs import event

OPEN_STATES = ("OPEN", "AWAITING_REPLY", "REPLIED", "ADJUSTMENT_PROMISED")


class CaseError(Exception):
    pass


def _case(conn, case_id: int) -> dict:
    c = db.one(conn, "SELECT * FROM enquiry_case WHERE id = %s FOR UPDATE", (case_id,))
    if not c:
        raise CaseError("unknown case")
    return c


def _now():
    return dt.datetime.now(dt.timezone.utc)


def log_reply(conn, actor: dict, case_id: int, reply: dict) -> dict:
    """The society's answer against the case ID: status, amount/period, reason, correction, expected distribution."""
    c = _case(conn, case_id)
    if c["status"] not in OPEN_STATES:
        raise CaseError("case is closed - reopen it by including it in a new pack")
    fields = ("society_status", "amount", "period", "reason", "correction_requested", "expected_distribution",
              "received_on", "reference")
    r = {k: s(reply.get(k)) or None for k in fields}
    if not r["reason"] and not r["society_status"]:
        raise CaseError("record at least the society status or reason given in the reply")
    if not r["reference"]:
        raise CaseError("record the reply reference (email / letter)")
    promised = bool(r["expected_distribution"]) or s(reply.get("adjustment_promised")).lower() in ("1", "true", "yes")
    status = "ADJUSTMENT_PROMISED" if promised else "REPLIED"
    db.update(conn, "enquiry_case", case_id, dict(reply=r, status=status, updated_at=_now(),
                                                  next_action="track the promised adjustment" if promised else
                                                  "review the reply: close with reason or keep open"))
    event(conn, case_id, actor, "reply_logged", dict(r, status=status))
    audit.record(conn, "case.reply", actor, "enquiry_case", case_id, dict(r, status=status))
    return db.one(conn, "SELECT * FROM enquiry_case WHERE id = %s", (case_id,))


def keep_open(conn, actor: dict, case_id: int, reason: str, requested: str | None, owner_id: int | None,
              follow_up) -> dict:
    c = _case(conn, case_id)
    if not s(reason):
        raise CaseError("record why the case stays open")
    fu = as_date(follow_up)
    if not fu:
        raise CaseError("set the next follow-up date")
    db.update(conn, "enquiry_case", case_id, dict(owner_id=owner_id or c["owner_id"], follow_up_date=fu,
                                                  next_action=requested or reason, updated_at=_now(),
                                                  status=c["status"] if c["status"] in OPEN_STATES else "OPEN"))
    event(conn, case_id, actor, "kept_open", dict(reason=reason, requested=requested, owner_id=owner_id,
                                                  follow_up=fu))
    audit.record(conn, "case.kept_open", actor, "enquiry_case", case_id, dict(reason=reason, follow_up=fu))
    return db.one(conn, "SELECT * FROM enquiry_case WHERE id = %s", (case_id,))


def payment(conn, actor: dict, case_id: int, status: str, value, reference: str, linked_file_id: int | None = None) -> dict:
    """Pending, credited and received are tracked separately; a later statement or receipt is linked before a
    recovery is recorded."""
    c = _case(conn, case_id)
    if status not in ("PENDING", "CREDITED", "RECEIVED"):
        raise CaseError("payment status is PENDING, CREDITED or RECEIVED")
    a = amount(value) if s(value) else None
    if status in ("CREDITED", "RECEIVED") and (a is None or not s(reference)):
        raise CaseError("a credited or received amount needs the amount and its statement / receipt reference")
    if status == "RECEIVED" and not linked_file_id and not s(reference):
        raise CaseError("link the later statement or receipt before recording a recovery")
    refs = list(c["linked_refs"] or [])
    refs.append(dict(kind=status, amount=None if a is None else format(a, "f"), reference=reference,
                     file_id=linked_file_id, at=_now().isoformat(), by=actor["email"]))
    db.update(conn, "enquiry_case", case_id, dict(payment_status=status, linked_refs=refs, updated_at=_now()))
    event(conn, case_id, actor, "payment_" + status.lower(), dict(amount=a, reference=reference,
                                                                  file_id=linked_file_id))
    audit.record(conn, "case.payment", actor, "enquiry_case", case_id, dict(status=status, amount=a,
                                                                            reference=reference))
    return db.one(conn, "SELECT * FROM enquiry_case WHERE id = %s", (case_id,))


def close(conn, actor: dict, case_id: int, outcome: str, reason: str, evidence: str) -> dict:
    c = _case(conn, case_id)
    if outcome not in ("CLOSED_EXPLAINED", "CLOSED_CORRECTED"):
        raise CaseError("close as CLOSED_EXPLAINED (explained / no adjustment) or CLOSED_CORRECTED (correction done)")
    if not s(reason) or not s(evidence):
        raise CaseError("closing needs a reason and its evidence")
    if c["status"] not in OPEN_STATES:
        raise CaseError("case is already closed")
    if c["status"] == "ADJUSTMENT_PROMISED" and c["payment_status"] not in ("CREDITED", "RECEIVED"):
        raise CaseError("a promised adjustment stays open until it is credited or received")
    if outcome == "CLOSED_CORRECTED" and c["payment_status"] not in ("CREDITED", "RECEIVED") \
            and "correct" not in reason.lower():
        raise CaseError("a corrected close needs the credited / received payment, or state the correction made")
    db.update(conn, "enquiry_case", case_id, dict(status=outcome, close_reason=reason, close_evidence=evidence,
                                                  next_action=None, updated_at=_now()))
    event(conn, case_id, actor, "closed", dict(outcome=outcome, reason=reason, evidence=evidence,
                                              previous=c["status"]))
    audit.record(conn, "case.closed", actor, "enquiry_case", case_id, dict(outcome=outcome, reason=reason))
    return db.one(conn, "SELECT * FROM enquiry_case WHERE id = %s", (case_id,))


def history(conn, case_id: int) -> list[dict]:
    return db.all(conn, "SELECT e.*, u.name AS actor_name FROM case_event e LEFT JOIN app_user u ON u.id = e.actor_id "
                        "WHERE e.case_id = %s ORDER BY e.id", (case_id,))
