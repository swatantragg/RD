"""IPRS enquiries and their follow-up. The application prepares and tracks an enquiry; people send it.

  draft  ->  review  ->  approval  ->  manual sending (recorded)  ->  response  ->  investigation  ->  resolution
  -> closure (once the resolution is verified)

Rules enforced here (and by CHECK constraints on the table):
  * nothing is ever sent by the application; 'record sent' notes that a person sent it, after an approval;
  * a draft is never treated as sent; a recorded response or a new statement never resolves or closes an enquiry;
  * an item is only enquired about once (no duplicate enquiries for the same work, platform and period), and only
    when it is a missing IPRS entry or a positive indicative variance;
  * a later IPRS statement that may already address an item is reviewed before the item is used;
  * links that are not verified keep the enquiry at MAPPING_PENDING; it cannot go for approval until they are.
Every step is an enquiry event; approvals, sending, assignment and closure are also in the audit log.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from .. import audit, db
from ..security import Forbidden
from . import access, xlsx
from .recon import MISSING_IPRS, _later, why_not_query
from .service import RDError

STATUS_LABEL = {
    "NEEDS_REVIEW": "Needs review", "MAPPING_PENDING": "Waiting for link verification",
    "DATA_CLARIFICATION_REQUIRED": "Data clarification required", "DRAFT_PREPARED": "Draft prepared",
    "PENDING_APPROVAL": "Waiting for approval", "APPROVED_TO_SEND": "Approved - to be sent",
    "AWAITING_RESPONSE": "Sent - awaiting response", "UNDER_INVESTIGATION": "Under investigation",
    "PARTIALLY_RESOLVED": "Partially resolved", "RESOLVED": "Resolved - awaiting closure", "CLOSED": "Closed"}
DRAFTING = ("NEEDS_REVIEW", "MAPPING_PENDING", "DATA_CLARIFICATION_REQUIRED", "DRAFT_PREPARED")
OPEN_AFTER_SEND = ("AWAITING_RESPONSE", "UNDER_INVESTIGATION", "PARTIALLY_RESOLVED")
ACTION_TEXT = {
    "recheck": "Check the links again", "submit": "Send for approval", "return": "Return for correction",
    "approve": "Approve for sending", "record_sent": "Record that it was sent", "record_response": "Record a response",
    "record_follow_up": "Record a follow-up sent", "investigate": "Start investigating",
    "note_correction": "Note a correction or additional royalty", "partially_resolve": "Record partial resolution",
    "resolve": "Record resolution", "reopen": "Reopen", "close": "Close (resolution verified)",
    "withdraw": "Withdraw this draft", "new_statement_reviewed": "Mark the new statement as reviewed",
    "assign": "Assign"}
# action -> (allowed from, to (None = unchanged), capability needed)
TRANSITIONS = {
    "recheck": (DRAFTING, None, "prepare"),
    "submit": (("DRAFT_PREPARED",), "PENDING_APPROVAL", "prepare"),
    "return": (("PENDING_APPROVAL", "APPROVED_TO_SEND"), "DRAFT_PREPARED", "approve_enquiries"),
    "approve": (("PENDING_APPROVAL",), "APPROVED_TO_SEND", "approve_enquiries"),
    "record_sent": (("APPROVED_TO_SEND",), "AWAITING_RESPONSE", "approve_enquiries"),
    "record_response": (OPEN_AFTER_SEND, "UNDER_INVESTIGATION", "prepare"),
    "record_follow_up": (OPEN_AFTER_SEND, "AWAITING_RESPONSE", "prepare"),
    "investigate": (("AWAITING_RESPONSE",), "UNDER_INVESTIGATION", "prepare"),
    "note_correction": (OPEN_AFTER_SEND + ("RESOLVED",), None, "prepare"),
    "partially_resolve": (("AWAITING_RESPONSE", "UNDER_INVESTIGATION"), "PARTIALLY_RESOLVED", "prepare"),
    "resolve": (("UNDER_INVESTIGATION", "PARTIALLY_RESOLVED", "AWAITING_RESPONSE"), "RESOLVED", "prepare"),
    "reopen": (("RESOLVED", "PARTIALLY_RESOLVED"), "UNDER_INVESTIGATION", "prepare"),
    "close": (("RESOLVED",), "CLOSED", "close_enquiries"),
    "withdraw": (DRAFTING + ("PENDING_APPROVAL", "APPROVED_TO_SEND"), "CLOSED", "prepare"),
    "new_statement_reviewed": (tuple(STATUS_LABEL), None, "prepare"),
    "assign": (tuple(s for s in STATUS_LABEL if s != "CLOSED"), None, "assign_followups"),
}
EVENT = {"recheck": "LINKS_RECHECKED", "submit": "REVIEW_REQUESTED", "return": "RETURNED_FOR_CORRECTION",
         "approve": "APPROVED", "record_sent": "MANUALLY_SENT", "record_response": "RESPONSE_RECEIVED",
         "record_follow_up": "FOLLOW_UP_SENT", "investigate": "INVESTIGATION_STARTED",
         "note_correction": "CORRECTION_IDENTIFIED", "partially_resolve": "RESOLUTION_RECORDED",
         "resolve": "RESOLUTION_RECORDED", "reopen": "REOPENED", "close": "CLOSED", "withdraw": "WITHDRAWN",
         "new_statement_reviewed": "NEW_STATEMENT_REVIEWED", "assign": "ASSIGNED"}
COMM_TYPES = ("EMAIL", "LETTER", "PORTAL", "PHONE", "MEETING", "OTHER")


class EnquiryError(RDError):
    pass


def _today() -> dt.date:
    return dt.date.today()


def _date(v, what: str, required: bool = False) -> dt.date | None:
    if not v:
        if required:
            raise EnquiryError(f"Please enter the {what}.")
        return None
    try:
        return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise EnquiryError(f"The {what} is not a valid date.") from None


def _event(conn, e: dict, event_type: str, text: str, actor: dict | None, frm=None, to=None, meta=None) -> None:
    db.insert(conn, "enquiry_events", dict(enquiry_id=e["id"], client_id=e["client_id"], event_type=event_type,
                                           event_description=text, from_status=frm, to_status=to,
                                           actor_user_id=(actor or {}).get("id"), metadata_json=meta or {}),
              returning=None)


def _get(conn, enquiry_id: int, lock: bool = False) -> dict:
    e = db.one(conn, "SELECT * FROM enquiries WHERE id = %s" + (" FOR UPDATE" if lock else ""), (enquiry_id,))
    if not e:
        raise EnquiryError("This enquiry does not exist, or you do not have access to it.")
    return e


def _period(a, b) -> str:
    return f"{a:%B %Y} to {b:%B %Y}" if a and b else "period not stated"


def _money(v) -> str:
    return "" if v is None else f"Rs. {Decimal(v):,.2f}"


# ================================================================== creating a draft
def attachment_name(reference: str, platform: str, a, b) -> str:
    return f"{reference}_{xlsx.safe_name(platform)}_{a:%Y-%m}_to_{b:%Y-%m}_Songs.xlsx"


def _draft(client: dict, platform: str, a, b, items: list[dict], benchmark=None, reference: str = "") -> tuple[str, str]:
    """The letter to IPRS. The songs are not listed in it: they are in the attached song report (attachment())."""
    clar = [i for i in items if i["iprs_royalty_amount"] is None]
    low = [i for i in items if i["iprs_royalty_amount"] is not None and i["indicative_variance"] is not None
           and Decimal(i["indicative_variance"]) > 0]
    n = len(items)
    songs = f"{n:,} song{'s' if n != 1 else ''}"
    bench = f"{Decimal(benchmark).normalize()} %" if benchmark is not None else "the reference percentage"
    subject = f"{client['name']} - {platform}, {_period(a, b)}: request for clarification of royalty distribution " \
              f"({songs})"
    findings = []
    if low:
        findings.append(f"for {len(low):,} of these songs the royalty distributed appears lower than expected")
    if clar:
        findings.append(f"for {len(clar):,} we could not find an entry in the statements received")
    lines = ["Dear Sir / Madam,", "",
             f"We write on behalf of our client {client['name']} (IPRS member "
             f"{client.get('member_id') or '[member number]'}) regarding {platform} royalties for the usage period "
             f"{_period(a, b)}.", "",
             f"Please find attached the list of the {songs} used on {platform} during this period"
             + (f" ({attachment_name(reference, platform, a, b)})" if reference else "") + ". For each song it shows "
             f"the IPRS work number, the song name and its ISRCs; the revenue and the usage (plays) reported by "
             f"{platform} for the period; the royalty distributed by IPRS with its distribution number, date and period; "
             f"and, for comparison, an expected royalty of {bench} of the revenue with the difference.", ""]
    if findings:
        lines += ["Having compared these figures, " + " and ".join(findings) + ".", ""]
    lines += ["We would be grateful for your clarification of:",
              f"1. whether the usage of these songs on {platform} in this period was reported to IPRS, and in which "
              "distribution it was or will be paid;",
              "2. the basis on which the royalty for each song was calculated;",
              "3. why the royalty distributed is below the expected amount for the songs concerned, and whether any "
              "further amount will be distributed.", "",
              "This is a request for clarification only. The figures in the attachment are indicative and are not a "
              "claim of any amount payable.", "",
              "We would appreciate your response at your earliest convenience.", "", "Yours faithfully,", "",
              "[Name]", "Music Rights Management India"]
    return subject, "\n".join(lines)


def _letter(conn, e: dict, items: list[dict] | None = None) -> tuple[str, str] | None:
    """The subject and text the application writes for the enquiry's current songs (None without its reconciliation)."""
    run = db.one(conn, "SELECT r.*, p.platform_name FROM reconciliation_runs r JOIN platforms p ON p.id = r.platform_id "
                       "WHERE r.id = %s", (e["reconciliation_run_id"],))
    if not run:
        return None
    if items is None:
        items = db.all(conn, "SELECT ri.* FROM enquiry_items ei JOIN reconciliation_items ri ON ri.id = "
                             "ei.reconciliation_item_id WHERE ei.enquiry_id = %s AND ei.item_status <> 'REMOVED'",
                       (e["id"],))
    client = db.one(conn, "SELECT * FROM client WHERE id = %s", (e["client_id"],))
    return _draft(client, run["platform_name"], run["usage_period_start"], run["usage_period_end"], items,
                  run["benchmark_percentage"], e["enquiry_reference"])


def _eligible(it: dict) -> str | None:
    """Why an item cannot go into an enquiry, or None."""
    return why_not_query(it)


def _status_for(conn, items: list[dict]) -> tuple[str, str | None]:
    """The drafting status the items allow: links first, then data."""
    if not items:
        return "NEEDS_REVIEW", "The enquiry has no items."
    # the ISRCs whose revenue the items rest on (not every ISRC the catalogue lists for the work)
    isrcs = [r["isrc"] for r in db.all(conn, "SELECT DISTINCT isrc FROM reconciliation_sources WHERE "
                                             "reconciliation_item_id = ANY(%s) AND source_type IN ('CLIENT_REVENUE', "
                                             "'PLATFORM_REVENUE', 'PLATFORM_USAGE') AND "
                                             "isrc IS NOT NULL", ([i["id"] for i in items],))]
    unverified = db.all(conn, "SELECT r.isrc, coalesce(x.mapping_status, 'NOT IN CATALOGUE') AS mapping_status FROM "
                              "unnest(%s::TEXT[]) AS r(isrc) LEFT JOIN isrc_resolution x ON x.client_id = %s AND "
                              "x.isrc = r.isrc WHERE x.mapping_status IS DISTINCT FROM 'VERIFIED'",
                        (isrcs, items[0]["client_id"]))
    works = db.all(conn, "SELECT internal_work_number, catalogue_status FROM works WHERE id = ANY(%s) AND "
                         "catalogue_status IN ('REVIEW', 'TO_REGISTER')", ([i["work_id"] for i in items],))
    if unverified or works:
        what = [f"{u['isrc']} ({u['mapping_status'].lower()})" for u in unverified[:6]] + \
               [f"work {w['internal_work_number'] or '(no number)'} needs review" for w in works[:4]]
        return "MAPPING_PENDING", "Catalogue links to verify first: " + ", ".join(what) + "."
    if any(i["calculation_status"] != "CALCULATED" and i["sound_recording_revenue"] is not None for i in items):
        return "DATA_CLARIFICATION_REQUIRED", "Some items have no calculated benchmark (the revenue basis is not " \
                                              "established)."
    return "DRAFT_PREPARED", None


def create(actor: dict, client_id: int, run_id: int, item_ids: list[int], later_reviewed: bool = False,
           assigned_to: int | None = None) -> dict:
    access.require(actor, "prepare")
    if not item_ids:
        raise EnquiryError("Choose the items to include.")
    with access.tx(actor, client_id) as conn:
        run = db.one(conn, "SELECT r.*, p.platform_name FROM reconciliation_runs r JOIN platforms p ON p.id = "
                           "r.platform_id WHERE r.id = %s AND r.client_id = %s", (run_id, client_id))
        if not run or run["status"] != "COMPLETED":
            raise EnquiryError("Choose items from a completed reconciliation.")
        its = db.all(conn, "SELECT * FROM reconciliation_items WHERE reconciliation_run_id = %s AND id = ANY(%s) ORDER BY "
                           "item_no", (run_id, item_ids))
        if len(its) != len(set(item_ids)):
            raise EnquiryError("Some items are not part of this reconciliation.")
        bad = [f"item {i['item_no']} ({i['work_title'] or ', '.join(i['isrcs'])}): {_eligible(i)}" for i in its
               if _eligible(i)]
        if bad:
            raise EnquiryError("These items cannot go into an enquiry: " + "; ".join(bad[:5]) + ".")
        dup = db.all(conn, "SELECT ei.work_id, e.enquiry_reference, e.status, e.resolution_status FROM enquiry_items ei "
                           "JOIN enquiries e ON e.id = ei.enquiry_id WHERE ei.client_id = %s AND ei.item_status <> "
                           "'REMOVED' AND ei.work_id = ANY(%s) AND ei.platform_id = %s AND ei.usage_period_start <= %s "
                           "AND ei.usage_period_end >= %s AND NOT (e.status = 'CLOSED' AND e.resolution_status = "
                           "'WITHDRAWN')", (client_id, [i["work_id"] for i in its], run["platform_id"],
                                             run["usage_period_end"], run["usage_period_start"]))
        if dup:
            raise EnquiryError("Already enquired about: " + "; ".join(
                f"{next(i['work_title'] for i in its if i['work_id'] == d['work_id'])} in {d['enquiry_reference']} "
                f"({STATUS_LABEL[d['status']].lower()})" for d in dup[:5]) + ". Add new information to that enquiry "
                "instead of starting another.")
        later = _later(conn, run)
        hit = {i["internal_work_number"]: later[i["internal_work_number"]] for i in its
               if i["internal_work_number"] in later}
        if hit and not later_reviewed:
            raise EnquiryError("A later IPRS statement may already address " + ", ".join(sorted(hit)[:6]) + " (" + ", ".join(
                sorted({s["filename"] for v in hit.values() for s in v})[:3]) + "). Review it first; if it does not "
                "change anything, confirm that you reviewed it.")
        client = db.one(conn, "SELECT * FROM client WHERE id = %s", (client_id,))
        n = (db.scalar(conn, "SELECT count(*) FROM enquiries WHERE client_id = %s", (client_id,)) or 0) + 1
        ref = f"{client['code']}-ENQ-{n:04d}"
        subject, body = _draft(client, run["platform_name"], run["usage_period_start"], run["usage_period_end"], its,
                               run["benchmark_percentage"], ref)
        status, why = _status_for(conn, its)
        eid = db.insert(conn, "enquiries", dict(
            client_id=client_id, enquiry_reference=ref, subject=subject, draft_body=body,
            status=status, platform_id=run["platform_id"], usage_period_start=run["usage_period_start"],
            usage_period_end=run["usage_period_end"], reconciliation_run_id=run_id, created_by=actor["id"],
            assigned_to=assigned_to if assigned_to and access.can(actor, "assign_followups") else actor["id"],
            resolution_status="UNRESOLVED"))
        for i in its:
            db.insert(conn, "enquiry_items", dict(
                enquiry_id=eid, reconciliation_item_id=i["id"], client_id=client_id, work_id=i["work_id"],
                platform_id=run["platform_id"], usage_period_start=run["usage_period_start"],
                usage_period_end=run["usage_period_end"],
                section="CLARIFICATION" if i["iprs_royalty_amount"] is None else "VARIANCE", added_by=actor["id"]),
                returning=None)
        e = _get(conn, eid)
        _event(conn, e, "DRAFT_CREATED", f"Draft prepared from {run['run_reference']} with {len(its)} item(s)."
               + (f" {why}" if why else ""), actor, None, status, dict(run=run["run_reference"], items=len(its)))
        if hit:
            _event(conn, e, "LATER_STATEMENT_REVIEWED", "Later IPRS statements were reviewed before drafting: "
                   + ", ".join(sorted({s["filename"] for v in hit.values() for s in v})), actor)
        audit.record(conn, "enquiry.created", actor, "enquiries", eid,
                     dict(reference=e["enquiry_reference"], run=run["run_reference"], items=len(its), status=status))
    return detail(actor, eid)


# ================================================================== editing and moving through the workflow
def update_draft(actor: dict, enquiry_id: int, body: dict) -> dict:
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        e = _get(conn, enquiry_id, lock=True)
        if e["status"] not in DRAFTING:
            raise EnquiryError("Only a draft can be edited. Return it for correction first.")
        vals = {}
        for k in ("subject", "draft_body"):
            if body.get(k) is not None:
                v = str(body[k]).strip()
                if not v:
                    raise EnquiryError("The subject and the text cannot be empty.")
                vals[k] = v
        edited = bool(vals)
        if body.get("rebuild"):                        # the letter again, for the songs now in the enquiry
            letter = _letter(conn, e)
            if not letter:
                raise EnquiryError("This enquiry has no reconciliation to write its text from.")
            vals = dict(subject=letter[0], draft_body=letter[1])
            edited = False
            _event(conn, e, "DRAFT_REBUILT", "The text was written again for the songs in the enquiry; the songs "
                   "themselves are listed in the attachment.", actor)
        if body.get("remove_item"):
            n = db.scalar(conn, "SELECT count(*) FROM enquiry_items WHERE enquiry_id = %s AND item_status <> 'REMOVED'",
                          (enquiry_id,))
            if n <= 1:
                raise EnquiryError("An enquiry needs at least one item; withdraw the draft instead.")
            untouched = not vals and _letter(conn, e) == (e["subject"], e["draft_body"])
            conn.execute("UPDATE enquiry_items SET item_status = 'REMOVED', outcome_note = 'removed from the draft' "
                         "WHERE enquiry_id = %s AND reconciliation_item_id = %s", (enquiry_id, int(body["remove_item"])))
            if untouched:                              # an unedited letter keeps counting the right songs
                vals = dict(zip(("subject", "draft_body"), _letter(conn, e)))
            _event(conn, e, "ITEM_REMOVED", f"Item {body['remove_item']} removed from the draft."
                   + (" The text now counts the remaining songs." if untouched else ""), actor)
        if vals:
            db.update(conn, "enquiries", enquiry_id, vals)
            conn.execute("UPDATE enquiries SET updated_at = now() WHERE id = %s", (enquiry_id,))
            if edited:
                _event(conn, e, "DRAFT_EDITED", "The draft text was edited.", actor)
    return detail(actor, enquiry_id)


def _recompute_follow_up(conn, enquiry_id: int) -> None:
    conn.execute("UPDATE enquiries SET next_follow_up_at = (SELECT min(due_at) FROM enquiry_actions WHERE enquiry_id = "
                 "%s AND status = 'OPEN'), updated_at = now() WHERE id = %s", (enquiry_id, enquiry_id))


def act(actor: dict, enquiry_id: int, action: str, p: dict) -> dict:
    if action not in TRANSITIONS:
        raise EnquiryError("Unknown action.")
    frm, to, cap = TRANSITIONS[action]
    with access.tx(actor) as conn:
        e = _get(conn, enquiry_id, lock=True)
        if action in ("record_sent",) and e["assigned_to"] == actor["id"] and not access.can(actor, cap):
            pass                                           # the person the enquiry is assigned to may record sending
        else:
            access.require(actor, cap)
        if e["status"] not in frm:
            raise EnquiryError(f"'{ACTION_TEXT[action]}' is not possible while the enquiry is "
                               f"{STATUS_LABEL[e['status']].lower()}.")
        if e["new_statement_review"] and action in ("submit", "approve", "record_sent", "resolve", "close"):
            raise EnquiryError("A new IPRS statement may concern this enquiry. Review it first, then mark the new statement "
                               "as reviewed.")
        note = (p.get("note") or "").strip() or None
        new = to or e["status"]
        vals: dict = {}
        meta: dict = {}
        text = ACTION_TEXT[action] + "."
        its = db.all(conn, "SELECT ri.* FROM enquiry_items ei JOIN reconciliation_items ri ON ri.id = "
                           "ei.reconciliation_item_id WHERE ei.enquiry_id = %s AND ei.item_status <> 'REMOVED'",
                     (enquiry_id,))
        if action == "recheck":
            new, why = _status_for(conn, its)
            text = f"Links checked again: {STATUS_LABEL[new].lower()}." + (f" {why}" if why else "")
        elif action == "submit":
            st, why = _status_for(conn, its)
            if st != "DRAFT_PREPARED":
                raise EnquiryError(why or "The draft is not ready for approval.")
            vals.update(reviewed_by=None, returned_reason=None)
            text = "Sent for review and approval."
            rid = int(p["reviewer"]) if p.get("reviewer") else None
            if rid:
                rv = db.one(conn, "SELECT id, name FROM app_user WHERE id = %s AND active AND deleted_at IS NULL AND "
                                  "role IN ('ADMIN', 'SUPER_ADMIN')", (rid,))
                if not rv:
                    raise EnquiryError("Choose an Admin to review it.")
                # the reviewer's review notification: a follow-up in their queue and on their Home page
                db.insert(conn, "enquiry_actions", dict(
                    enquiry_id=enquiry_id, client_id=e["client_id"], action_title=f"Review and approve {e['enquiry_reference']}",
                    action_description="Verify the links, platform, period, territory, currency, calculation basis and any "
                                       "later statement, payment or adjustment; then approve or return it.",
                    assigned_to=rv["id"], due_at=_today() + dt.timedelta(days=3), created_by=actor["id"]), returning=None)
                text = f"Sent to {rv['name']} for review and approval (review due {_today() + dt.timedelta(days=3):%d %b %Y})."
                meta = dict(reviewer=rv["id"])
        elif action == "return":
            if not note:
                raise EnquiryError("Please say what needs correcting.")
            vals.update(returned_reason=note, reviewed_by=actor["id"], reviewed_at=dt.datetime.now(dt.timezone.utc),
                        approved_by=None, approved_at=None)
            text = f"Returned for correction: {note}"
        elif action == "approve":
            st, why = _status_for(conn, its)
            if st != "DRAFT_PREPARED":
                raise EnquiryError("It cannot be approved yet. " + (why or ""))
            vals.update(reviewed_by=actor["id"], reviewed_at=dt.datetime.now(dt.timezone.utc), approved_by=actor["id"],
                        approved_at=dt.datetime.now(dt.timezone.utc), returned_reason=None)
            text = "Reviewed and approved for sending. The application does not send it: a person sends it and records "\
                   "it here."
        elif action == "record_sent":
            st, why = _status_for(conn, its)              # links may have changed since the approval
            if st != "DRAFT_PREPARED":
                raise EnquiryError("The catalogue links changed since the approval. " + (why or "") + " Return it for "
                                   "correction.")
            recipient = (p.get("recipient") or "").strip()
            if not recipient:
                raise EnquiryError("Please enter the IPRS recipient it was sent to.")
            sent_on = _date(p.get("sent_on"), "date it was sent", required=True)
            if sent_on > _today():
                raise EnquiryError("The sending date cannot be in the future.")
            channel = (p.get("channel") or "EMAIL").upper()
            if channel not in COMM_TYPES:
                raise EnquiryError("Unknown way of sending.")
            vals.update(sent_by=actor["id"], sent_at=dt.datetime.combine(sent_on, dt.time(12), dt.timezone.utc),
                        recipient_reference=recipient, send_channel=channel)
            db.insert(conn, "enquiry_communications", dict(
                enquiry_id=enquiry_id, client_id=e["client_id"], communication_type=channel, direction="OUTBOUND",
                subject=e["subject"], message_reference=p.get("message_reference"), recipient_reference=recipient,
                communication_date=sent_on, summary="Enquiry sent (recorded by hand)", recorded_by=actor["id"]),
                returning=None)
            meta = dict(recipient=recipient, channel=channel, sent_on=sent_on, message_reference=p.get("message_reference"))
            text = f"Sent by hand to {recipient} on {sent_on:%d %b %Y} ({channel.lower()})."
            follow = _date(p.get("follow_up_on"), "follow-up date")
            if follow:
                db.insert(conn, "enquiry_actions", dict(enquiry_id=enquiry_id, client_id=e["client_id"],
                                                        action_title="Follow up if there is no response",
                                                        assigned_to=e["assigned_to"] or actor["id"], due_at=follow,
                                                        created_by=actor["id"]), returning=None)
        elif action in ("record_response", "record_follow_up"):
            on = _date(p.get("date"), "date", required=True)
            summary = (p.get("summary") or "").strip()
            if not summary:
                raise EnquiryError("Please summarise the " + ("response." if action == "record_response" else
                                                               "follow-up."))
            channel = (p.get("channel") or "EMAIL").upper()
            if channel not in COMM_TYPES:
                raise EnquiryError("Unknown communication type.")
            rel = int(p["related_statement_id"]) if p.get("related_statement_id") else None
            db.insert(conn, "enquiry_communications", dict(
                enquiry_id=enquiry_id, client_id=e["client_id"], communication_type=channel,
                direction="INBOUND" if action == "record_response" else "OUTBOUND", subject=p.get("subject"),
                summary=summary, message_reference=p.get("message_reference"), sender_reference=p.get("sender"),
                recipient_reference=p.get("recipient"), communication_date=on,
                attachment_reference=p.get("attachment_reference"), related_statement_id=rel,
                recorded_by=actor["id"]), returning=None)
            if action == "record_response":
                vals["last_response_at"] = dt.datetime.combine(on, dt.time(12), dt.timezone.utc)
                text = f"Response received on {on:%d %b %Y}: {summary}. The enquiry is not resolved until the " \
                       "explanation is verified."
            else:
                text = f"Follow-up sent on {on:%d %b %Y}: {summary}"
            meta = dict(date=on, channel=channel, related_statement_id=rel)
        elif action == "note_correction":
            kind = p.get("kind") if p.get("kind") in ("CORRECTION", "ADDITIONAL_ROYALTY", "PAYMENT") else "CORRECTION"
            if not note:
                raise EnquiryError("Please describe the correction, payment or additional royalty.")
            amount = p.get("amount")
            meta = dict(kind=kind, amount=str(Decimal(str(amount))) if amount not in (None, "") else None,
                        related_statement_id=p.get("related_statement_id"))
            text = {"CORRECTION": "Correction identified", "ADDITIONAL_ROYALTY": "Additional royalty identified",
                    "PAYMENT": "Payment identified"}[kind] + (f" ({_money(amount)})" if meta["amount"] else "") + \
                f": {note}"
            _event(conn, e, "ADDITIONAL_ROYALTY_IDENTIFIED" if kind == "ADDITIONAL_ROYALTY" else
                   "CORRECTION_IDENTIFIED", text, actor, e["status"], e["status"], meta)
            audit.record(conn, "enquiry.correction_noted", actor, "enquiries", enquiry_id, meta)
            conn.execute("UPDATE enquiries SET updated_at = now() WHERE id = %s", (enquiry_id,))
            action = None
        elif action in ("partially_resolve", "resolve"):
            if not note:
                raise EnquiryError("Please summarise the resolution and its evidence.")
            vals.update(resolution_status="PARTIALLY_RESOLVED" if action == "partially_resolve" else "RESOLVED",
                        resolution_summary=note)
            for x in p.get("items") or []:
                if x.get("status") in ("OPEN", "PARTIALLY_RESOLVED", "RESOLVED", "NO_CHANGE"):
                    conn.execute("UPDATE enquiry_items SET item_status = %s, outcome_note = %s WHERE enquiry_id = %s AND "
                                 "reconciliation_item_id = %s", (x["status"], x.get("note"), enquiry_id,
                                                                 int(x["item_id"])))
            text = ("Partially resolved: " if action == "partially_resolve" else "Resolution recorded: ") + note
        elif action == "reopen":
            vals["resolution_status"] = "UNRESOLVED"
            text = "Reopened" + (f": {note}" if note else ".")
        elif action == "close":
            if not note:
                raise EnquiryError("Please confirm how the resolution was verified.")
            vals.update(closed_by=actor["id"], closed_at=dt.datetime.now(dt.timezone.utc))
            text = f"Closed after verifying the resolution: {note}"
            conn.execute("UPDATE enquiry_actions SET status = 'CANCELLED', updated_at = now() WHERE enquiry_id = %s AND "
                         "status = 'OPEN'", (enquiry_id,))
        elif action == "withdraw":
            if e["created_by"] != actor["id"] and not access.can(actor, "close_enquiries"):
                raise Forbidden("Only the person who drafted it, or an Admin, can withdraw this enquiry.")
            vals.update(closed_by=actor["id"], closed_at=dt.datetime.now(dt.timezone.utc),
                        resolution_status="WITHDRAWN", resolution_summary=note)
            text = "Withdrawn before sending" + (f": {note}" if note else ".")
            conn.execute("UPDATE enquiry_items SET item_status = 'REMOVED' WHERE enquiry_id = %s", (enquiry_id,))
        elif action == "new_statement_reviewed":
            vals["new_statement_review"] = False
            text = "The new statement was reviewed" + (f": {note}" if note else ".")
        elif action == "assign":
            who = int(p["assigned_to"]) if p.get("assigned_to") else None
            if who and not db.scalar(conn, "SELECT id FROM app_user WHERE id = %s AND active AND deleted_at IS NULL",
                                     (who,)):
                raise EnquiryError("Choose an active person.")
            vals["assigned_to"] = who
            name = db.scalar(conn, "SELECT name FROM app_user WHERE id = %s", (who,)) if who else "nobody"
            text = f"Assigned to {name}."
        if action is None:                              # a note only: no status change
            return_now = True
        else:
            return_now = False
            vals["status"] = new
            db.update(conn, "enquiries", enquiry_id, vals)
        if not return_now and action in ("approve", "return", "withdraw"):
            conn.execute("UPDATE enquiry_actions SET status = 'DONE', completed_by = %s, completed_at = now(), "
                         "completion_note = %s, updated_at = now() WHERE enquiry_id = %s AND status = 'OPEN' AND "
                         "action_title LIKE 'Review and approve %%'",
                         (actor["id"], {"approve": "approved", "return": f"returned: {note}",
                                        "withdraw": "draft withdrawn"}[action], enquiry_id))
        if not return_now:
            conn.execute("UPDATE enquiries SET updated_at = now() WHERE id = %s", (enquiry_id,))
            _recompute_follow_up(conn, enquiry_id)
            _event(conn, e, EVENT[action], text, actor, e["status"], new, meta)
            audit.record(conn, f"enquiry.{EVENT[action].lower()}", actor, "enquiries", enquiry_id,
                         dict(reference=e["enquiry_reference"], note=note, **{k: v for k, v in meta.items()}),
                         before=dict(status=e["status"]), after=dict(status=new))
    return detail(actor, enquiry_id)


# ================================================================== follow-up actions
def add_action(actor: dict, enquiry_id: int, body: dict) -> dict:
    """Admins assign follow-ups and set their dates; anyone may note a follow-up for themselves."""
    access.require(actor, "prepare")
    title = (body.get("title") or "").strip()
    if not title:
        raise EnquiryError("Please say what needs to be done.")
    who = int(body["assigned_to"]) if body.get("assigned_to") else actor["id"]
    if who != actor["id"]:
        access.require(actor, "assign_followups")
    due = _date(body.get("due_at"), "due date")
    with access.tx(actor) as conn:
        e = _get(conn, enquiry_id, lock=True)
        if e["status"] == "CLOSED":
            raise EnquiryError("This enquiry is closed.")
        aid = db.insert(conn, "enquiry_actions", dict(enquiry_id=enquiry_id, client_id=e["client_id"], action_title=title,
                                                      action_description=body.get("description"), assigned_to=who,
                                                      due_at=due, created_by=actor["id"]))
        name = db.scalar(conn, "SELECT name FROM app_user WHERE id = %s", (who,))
        _event(conn, e, "FOLLOW_UP_SCHEDULED", f"Follow-up '{title}' for {name}" + (f", due {due:%d %b %Y}." if due
                                                                                    else "."), actor)
        _recompute_follow_up(conn, enquiry_id)
        audit.record(conn, "enquiry.follow_up_scheduled", actor, "enquiry_actions", aid,
                     dict(enquiry=e["enquiry_reference"], title=title, assigned_to=who, due_at=due))
    return detail(actor, enquiry_id)


def update_action(actor: dict, action_id: int, body: dict) -> dict:
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        a = db.one(conn, "SELECT * FROM enquiry_actions WHERE id = %s FOR UPDATE", (action_id,))
        if not a:
            raise EnquiryError("This follow-up does not exist.")
        e = _get(conn, a["enquiry_id"], lock=True)
        vals = {}
        if "due_at" in body or "assigned_to" in body:
            access.require(actor, "assign_followups")
            if "due_at" in body:
                vals["due_at"] = _date(body.get("due_at"), "due date")
            if "assigned_to" in body:
                vals["assigned_to"] = int(body["assigned_to"]) if body.get("assigned_to") else None
        if body.get("status"):
            if body["status"] not in ("DONE", "CANCELLED", "OPEN"):
                raise EnquiryError("Unknown follow-up status.")
            if a["assigned_to"] != actor["id"] and not access.can(actor, "assign_followups"):
                raise Forbidden("Only the person it is assigned to, or an Admin, can complete this follow-up.")
            note = (body.get("note") or "").strip() or None
            if body["status"] == "DONE" and not note:
                raise EnquiryError("Please note what was done.")
            vals.update(status=body["status"], completion_note=note,
                        completed_by=actor["id"] if body["status"] != "OPEN" else None,
                        completed_at=dt.datetime.now(dt.timezone.utc) if body["status"] != "OPEN" else None)
        if vals:
            db.update(conn, "enquiry_actions", action_id, vals)
            conn.execute("UPDATE enquiry_actions SET updated_at = now() WHERE id = %s", (action_id,))
            _recompute_follow_up(conn, e["id"])
            ev = "FOLLOW_UP_COMPLETED" if vals.get("status") == "DONE" else "FOLLOW_UP_UPDATED"
            _event(conn, e, ev, f"Follow-up '{a['action_title']}' " + (
                f"completed: {vals.get('completion_note')}" if ev == "FOLLOW_UP_COMPLETED" else "updated."), actor,
                meta={k: v for k, v in vals.items() if k in ("due_at", "assigned_to", "status")})
            audit.record(conn, "enquiry.follow_up_updated", actor, "enquiry_actions", action_id,
                         before={k: a[k] for k in vals if k in a}, after=vals)
    return detail(actor, e["id"])


# ================================================================== a new IPRS statement may concern open enquiries
def flag_new_statement(conn, actor: dict | None, st: dict) -> int:
    """Called when an IPRS statement is imported: open enquiries (and reconciliation items) about the same works,
    platform and an overlapping period are flagged for review. Nothing is resolved automatically."""
    if not st["platform_id"]:
        return 0
    works = [r["work_id"] for r in db.all(conn, "SELECT DISTINCT work_id FROM iprs_royalty_records WHERE statement_id = "
                                                "%s AND work_id IS NOT NULL", (st["id"],))]
    if not works:
        return 0
    overlap = "(%(a)s::DATE IS NULL OR (usage_period_start <= %(b)s AND usage_period_end >= %(a)s))"
    p = dict(c=st["client_id"], w=works, pl=st["platform_id"], a=st["usage_period_start"], b=st["usage_period_end"],
             s=st["id"])
    enqs = db.all(conn, "SELECT DISTINCT e.* FROM enquiries e JOIN enquiry_items ei ON ei.enquiry_id = e.id WHERE "
                        "e.client_id = %(c)s AND e.status <> 'CLOSED' AND ei.item_status <> 'REMOVED' AND ei.work_id = "
                        "ANY(%(w)s) AND ei.platform_id = %(pl)s AND (%(a)s::DATE IS NULL OR (ei.usage_period_start <= "
                        "%(b)s AND ei.usage_period_end >= %(a)s))", p)
    for e in enqs:
        conn.execute("UPDATE enquiries SET new_statement_review = TRUE, updated_at = now() WHERE id = %s", (e["id"],))
        _event(conn, e, "NEW_STATEMENT_RECEIVED", f"A new IPRS statement was imported ({st['original_filename']}). It may "
               "concern this enquiry: review it before going further. The enquiry is not resolved automatically.",
               actor, meta=dict(statement_id=st["id"]))
    conn.execute(f"UPDATE reconciliation_items SET later_statement_status = 'REVIEW_REQUIRED', updated_at = now() "
                 f"WHERE client_id = %(c)s AND work_id = ANY(%(w)s) AND platform_id = %(pl)s AND {overlap} AND "
                 f"later_statement_status = 'NONE' AND reconciliation_run_id IN (SELECT id FROM reconciliation_runs "
                 f"WHERE client_id = %(c)s AND NOT (source_snapshot->'iprs_statements' @> "
                 f"jsonb_build_array(jsonb_build_object('id', %(s)s::BIGINT))))", p)
    return len(enqs)


# ================================================================== reading
def _people(conn) -> dict:
    return {r["id"]: r["name"] for r in db.all(conn, "SELECT id, name FROM app_user")}


def _out(e: dict, people: dict, plat: dict | None = None) -> dict:
    today = _today()
    return dict(e, status_label=STATUS_LABEL[e["status"]], platform=(plat or {}).get(e["platform_id"]),
                assigned_to_name=people.get(e["assigned_to"]), created_by_name=people.get(e["created_by"]),
                approved_by_name=people.get(e["approved_by"]), sent_by_name=people.get(e["sent_by"]),
                closed_by_name=people.get(e["closed_by"]),
                follow_up_due=bool(e["next_follow_up_at"] and e["next_follow_up_at"] <= today
                                   and e["status"] != "CLOSED"),
                overdue=bool(e["next_follow_up_at"] and e["next_follow_up_at"] < today and e["status"] != "CLOSED"))


def listing(actor: dict, client_id: int, status: str | None = None, q: str | None = None, mine: bool = False,
            queue: str | None = None) -> dict:
    with access.tx(actor, client_id) as conn:
        where, p = ["client_id = %(c)s"], dict(c=client_id, me=actor["id"], t=_today())
        if status:
            where.append("status = %(s)s")
            p["s"] = status
        if mine:
            where.append("assigned_to = %(me)s")
        if q:
            where.append("(enquiry_reference ILIKE %(q)s OR subject ILIKE %(q)s)")
            p["q"] = f"%{q}%"
        if queue:
            where.append(QUEUES[queue][1])
        rows = db.all(conn, f"SELECT * FROM enquiries WHERE {' AND '.join(where)} ORDER BY (status = 'CLOSED'), "
                            f"next_follow_up_at NULLS LAST, id DESC LIMIT 200", p)
        people = _people(conn)
        plat = {x["id"]: x["platform_name"] for x in db.all(conn, "SELECT id, platform_name FROM platforms")}
        counts = {r["status"]: r["n"] for r in db.all(conn, "SELECT status, count(*) AS n FROM enquiries WHERE "
                                                             "client_id = %s GROUP BY 1", (client_id,))}
    return dict(rows=[_out(r, people, plat) for r in rows], counts=counts,
                statuses=[dict(value=k, label=v) for k, v in STATUS_LABEL.items()])


QUEUES = {
    "drafts": ("Drafts awaiting review", "status IN ('NEEDS_REVIEW', 'MAPPING_PENDING', 'DATA_CLARIFICATION_REQUIRED', "
                                         "'DRAFT_PREPARED')"),
    "approval": ("Drafts awaiting approval", "status = 'PENDING_APPROVAL'"),
    "to_send": ("Approved, to be sent", "status = 'APPROVED_TO_SEND'"),
    "awaiting": ("Awaiting response", "status = 'AWAITING_RESPONSE'"),
    "due_today": ("Follow-ups due today", "status <> 'CLOSED' AND next_follow_up_at = %(t)s"),
    "overdue": ("Overdue follow-ups", "status <> 'CLOSED' AND next_follow_up_at < %(t)s"),
    "investigating": ("Under investigation", "status = 'UNDER_INVESTIGATION'"),
    "partial": ("Partially resolved", "status = 'PARTIALLY_RESOLVED'"),
    "new_statement": ("New statements to review", "status <> 'CLOSED' AND new_statement_review"),
    "to_close": ("Resolved, awaiting closure", "status = 'RESOLVED'"),
}


def dashboard(actor: dict, client_id: int) -> dict:
    with access.tx(actor, client_id) as conn:
        p = dict(c=client_id, t=_today(), me=actor["id"])
        counts = {k: db.scalar(conn, f"SELECT count(*) FROM enquiries WHERE client_id = %(c)s AND {sql}", p)
                  for k, (_l, sql) in QUEUES.items()}
        actions = db.all(conn, "SELECT a.*, e.enquiry_reference, e.subject, e.status AS enquiry_status FROM "
                               "enquiry_actions a JOIN enquiries e ON e.id = a.enquiry_id WHERE a.client_id = %(c)s AND "
                               "a.status = 'OPEN' ORDER BY a.due_at NULLS LAST, a.id LIMIT 100", p)
        people = _people(conn)
    today = _today()
    for a in actions:
        a["assigned_to_name"] = people.get(a["assigned_to"])
        a["overdue"] = bool(a["due_at"] and a["due_at"] < today)
        a["due_today"] = a["due_at"] == today
        a["mine"] = a["assigned_to"] == actor["id"]
    return dict(queues=[dict(key=k, label=lbl, count=counts[k]) for k, (lbl, _s) in QUEUES.items()], actions=actions,
                can_assign=access.can(actor, "assign_followups"), can_approve=access.can(actor, "approve_enquiries"))


def _allowed(actor: dict, e: dict) -> list[dict]:
    out = []
    for a, (frm, _to, cap) in TRANSITIONS.items():
        if e["status"] not in frm:
            continue
        if a == "new_statement_reviewed" and not e["new_statement_review"]:
            continue
        if e["new_statement_review"] and a in ("submit", "approve", "record_sent", "resolve", "close"):
            continue                                       # the new statement is reviewed first
        ok = access.can(actor, cap) or (a == "record_sent" and e["assigned_to"] == actor["id"])
        if a == "withdraw" and e["created_by"] != actor["id"] and not access.can(actor, "close_enquiries"):
            ok = False
        if ok:
            out.append(dict(action=a, label=ACTION_TEXT[a]))
    return out


def detail(actor: dict, enquiry_id: int) -> dict:
    with access.tx(actor) as conn:
        e = _get(conn, enquiry_id)
        people = _people(conn)
        plat = {x["id"]: x["platform_name"] for x in db.all(conn, "SELECT id, platform_name FROM platforms")}
        items = db.all(conn, "SELECT ei.section, ei.item_status, ei.outcome_note, ri.* FROM enquiry_items ei JOIN "
                             "reconciliation_items ri ON ri.id = ei.reconciliation_item_id WHERE ei.enquiry_id = %s "
                             "ORDER BY ei.section, ri.item_no", (enquiry_id,))
        events = db.all(conn, "SELECT * FROM enquiry_events WHERE enquiry_id = %s ORDER BY id DESC", (enquiry_id,))
        actions = db.all(conn, "SELECT * FROM enquiry_actions WHERE enquiry_id = %s ORDER BY status = 'OPEN' DESC, "
                               "due_at NULLS LAST, id", (enquiry_id,))
        comms = db.all(conn, "SELECT c.*, s.original_filename AS statement_filename FROM enquiry_communications c LEFT "
                             "JOIN statements s ON s.id = c.related_statement_id WHERE c.enquiry_id = %s ORDER BY "
                             "c.communication_date DESC, c.id DESC", (enquiry_id,))
        run = db.one(conn, "SELECT * FROM reconciliation_runs WHERE id = %s", (e["reconciliation_run_id"],))
        later = _later(conn, run) if run else {}
        assignees = db.all(conn, "SELECT id, name, role FROM app_user WHERE active AND deleted_at IS NULL ORDER BY name")
        current = e["status"] not in DRAFTING or _letter(conn, e, [i for i in items if i["item_status"] != "REMOVED"]) \
            in (None, (e["subject"], e["draft_body"]))
    for ev in events:
        ev["actor"] = people.get(ev["actor_user_id"])
    for a in actions:
        a["assigned_to_name"] = people.get(a["assigned_to"])
        a["completed_by_name"] = people.get(a["completed_by"])
        a["overdue"] = bool(a["status"] == "OPEN" and a["due_at"] and a["due_at"] < _today())
        a["can_complete"] = a["assigned_to"] == actor["id"] or access.can(actor, "assign_followups")
    for c in comms:
        c["recorded_by_name"] = people.get(c["recorded_by"])
    for i in items:
        i["later_statements"] = later.get(i["internal_work_number"] or "", [])
    att = attachment_name(e["enquiry_reference"], plat.get(e["platform_id"]) or "Platform", e["usage_period_start"],
                          e["usage_period_end"]) if run else None
    return dict(enquiry=_out(e, people, plat), items=items, events=events, actions=actions, communications=comms,
                attachment=att,
                allowed=_allowed(actor, e), run=dict(id=run["id"], reference=run["run_reference"]) if run else None,
                assignees=assignees, can_assign=access.can(actor, "assign_followups"),
                editable=e["status"] in DRAFTING, text_current=current, missing_text=MISSING_IPRS,
                comm_types=list(COMM_TYPES))


def attachment(actor: dict, enquiry_id: int) -> tuple[str, bytes]:
    """The song report sent with the letter: the enquiry's songs in the reconciliation layout - Internal No, song name,
    ISRC; the platform's revenue and usage per report; the IPRS royalty per distribution; expected vs paid."""
    from openpyxl import Workbook
    from .excel import stable
    from .recon import block_sheet, block_values, run_blocks
    with access.tx(actor) as conn:
        e = _get(conn, enquiry_id)
        run = db.one(conn, "SELECT r.*, p.platform_name, c.code, c.name AS client_name FROM reconciliation_runs r JOIN "
                           "platforms p ON p.id = r.platform_id JOIN client c ON c.id = r.client_id WHERE r.id = %s",
                     (e["reconciliation_run_id"],))
        if not run:
            raise EnquiryError("This enquiry has no reconciliation to build its song report from.")
        its = db.all(conn, "SELECT ri.* FROM enquiry_items ei JOIN reconciliation_items ri ON ri.id = "
                           "ei.reconciliation_item_id WHERE ei.enquiry_id = %s AND ei.item_status <> 'REMOVED' ORDER BY "
                           "ri.sound_recording_revenue DESC NULLS LAST, ri.item_no", (enquiry_id,))
        blocks = run_blocks(conn, run)
        vals = block_values(conn, [i["id"] for i in its], blocks)
        audit.record(conn, "export.enquiry_attachment", actor, "enquiries", enquiry_id,
                     dict(reference=e["enquiry_reference"], songs=len(its)))
    a, b = e["usage_period_start"], e["usage_period_end"]
    wb = Workbook()
    block_sheet(wb, "Songs", platform=run["platform_name"], client_code=run["code"],
                benchmark=run["benchmark_percentage"], blocks=blocks, items=its, values=vals,
                notes=[f"{run['client_name']} - {run['platform_name']} songs for {_period(a, b)} "
                       f"({e['enquiry_reference']}).",
                       "Usage = the plays the platform reported for the song in the period shown. Expected value = "
                       f"{Decimal(run['benchmark_percentage']).normalize()} % of the revenue; Variance = expected - "
                       "IPRS paid; Variance % = variance / expected. Indicative figures for clarification only, not a "
                       "claim of any amount payable. An empty cell means no record."])
    return attachment_name(e["enquiry_reference"], run["platform_name"], a, b), stable(wb)


def annex(actor: dict, enquiry_id: int) -> tuple[str, bytes]:
    """The items of an enquiry with their evidence, for the reviewer (internal: it includes the indicative figures)."""
    d = detail(actor, enquiry_id)
    e = d["enquiry"]
    with access.tx(actor) as conn:
        audit.record(conn, "export.enquiry_annex", actor, "enquiries", enquiry_id, dict(reference=e["enquiry_reference"]))
    rows = [[i["item_no"], "Clarification (no IPRS entry)" if i["section"] == "CLARIFICATION" else "Variance",
             i["internal_work_number"], i["work_title"], i["isrcs"], i["sound_recording_revenue"],
             i["iprs_royalty_amount"], i["reference_benchmark_amount"], i["indicative_variance"],
             i["mapping_status"].title(), i["item_status"].replace("_", " ").title(), i["outcome_note"]]
            for i in d["items"]]
    data = xlsx.book([dict(
        title="Items", heading=[f"{e['enquiry_reference']} - {e['subject']}",
                                f"Status: {e['status_label']}. Internal working paper: the indicative figures are not "
                                "amounts payable and are not part of the enquiry text.",
                                f"Missing entries read: '{MISSING_IPRS}'"],
        columns=[("Item", 6, None), ("Section", 26, None), ("Work number", 12, None), ("Title", 34, None),
                 ("ISRCs", 30, None), ("[Source] Revenue (client's statements)", 16, "money"),
                 ("[Source] IPRS royalty", 14, "money"), ("[Calculated] Indicative Reference Benchmark", 16, "money"),
                 ("[Calculated] Indicative Variance - Requires Verification", 18, "money"), ("Mapping", 12, None),
                 ("Item status", 14, None), ("Outcome", 40, None)], rows=rows),
        dict(title="Draft", columns=[("Draft text", 120, None)],
             rows=[[e["subject"]], [""]] + [[ln] for ln in e["draft_body"].splitlines()]),
        dict(title="History", columns=[("When", 20, None), ("Event", 26, None), ("By", 18, None), ("What", 100, None)],
             rows=[[ev["event_timestamp"].strftime("%d %b %Y %H:%M"), ev["event_type"].replace("_", " ").title(),
                    ev["actor"], ev["event_description"]] for ev in d["events"]])])
    return f"{e['enquiry_reference']}_Annex.xlsx", data
