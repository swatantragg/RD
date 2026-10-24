"""The statement library: every report and statement the client's work depends on, uploaded in any order and kept for
good. Two kinds, each with its own tab under Statements (statement_source), chosen by the person uploading:
  PLATFORM  the platform's reports (for example MRM's Spotify report): revenue and usage per ISRC and month. Revenue
            and usage may come in one file or in two; they are combined by ISRC and song name, month by month
  IPRS      IPRS statements: what IPRS paid, received from IPRS or forwarded by the client (the same IPRS layout)
Until 1.6.0 the client's forwarded statements had a tab of their own (CLIENT); migration 0013 made them IPRS
statements. What the file holds is a separate fact:
  WORK_ROYALTY       money per musical work (WORK INT NO), party by party (the IPRS distribution layout)
  RECORDING_REVENUE  revenue per ISRC and month (plays too, when the report has them)
  RECORDING_USAGE    plays per ISRC and month, without money

Each upload is stored once (rd_file: the write-once original and its parsed lines, which never change). The
statements row is the registry entry: platform, usage period, currency, basis, status. Nothing is counted twice:
  * the same bytes again reuse the stored copy;
  * the same distribution (or the same platform report period) with the same entries is a DUPLICATE;
  * the same distribution with different entries waits for a person: a CORRECTION (the earlier one is SUPERSEDED but
    kept), a SUPPLEMENTARY statement (both count), or leave it out.
Normalised records are views (client_revenue_records, iprs_royalty_records) over the stored lines, so they always
reflect the current catalogue.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from .. import audit, db
from ..normalize import month_end
from . import access, detect, intake, names, platforms, xlsx
from .model import KIND_LABEL, PLATFORM_REVENUE, PLATFORM_USAGE, STATEMENT
from .service import RDError, _file_out, client_cfg

TYPE_OF = {STATEMENT: "WORK_ROYALTY", PLATFORM_REVENUE: "RECORDING_REVENUE", PLATFORM_USAGE: "RECORDING_USAGE"}
TYPE_LABEL = {"WORK_ROYALTY": "Per work (IPRS layout)", "RECORDING_REVENUE": "Revenue per ISRC and month",
              "RECORDING_USAGE": "Usage per ISRC and month"}
SOURCES = ("PLATFORM", "IPRS")                     # the tabs under Statements
# CLIENT: only a client's copy of a file that is also under IPRS statements, left out by migration 0013
SOURCE_LABEL = {"PLATFORM": "Platform", "IPRS": "IPRS", "CLIENT": "Client (before 1.6.0)"}
SIDE_LABEL = {"PLATFORM": "Platform report", "IPRS": "IPRS statement", "CLIENT": "Client statement (before 1.6.0)"}
TAB_LABEL = {"PLATFORM": "Platform reports", "IPRS": "IPRS statements", "CLIENT": "Client statements (before 1.6.0)"}
ISRC_TYPES = ("RECORDING_REVENUE", "RECORDING_USAGE")
STATUS_TEXT = {"IMPORTED": "Imported", "NEEDS_REVIEW": "Needs your answer", "REJECTED": "Rejected",
               "DUPLICATE": "Duplicate - counted once", "SUPERSEDED": "Replaced by a correction",
               "EXCLUDED": "Left out"}
FILE_STATUS = {"READY": "IMPORTED", "NEEDS_REVIEW": "NEEDS_REVIEW", "ERROR": "REJECTED", "UNSUPPORTED": "REJECTED",
               "LEFT_OUT": "EXCLUDED"}
RELATION_OPTIONS = [dict(value="CORRECTION", label="It corrects the earlier statement (replace it)"),
                    dict(value="SUPPLEMENTARY", label="It is a separate, additional statement (count both)"),
                    dict(value="LEAVE_OUT", label="Leave this file out")]
_WORK = "a royalty statement in the IPRS layout (WORK INT NO … ROYALTY AMT)"
ALLOWED = {"PLATFORM": {PLATFORM_REVENUE: "a platform revenue report (month, ISRC, song, revenue)",
                        PLATFORM_USAGE: "a platform usage report (month, ISRC, song, plays or streams)"},
           "IPRS": {STATEMENT: _WORK}}
_REFUSE = {"SONG_LIST": "This is a song catalogue. Upload it under Catalogue → Import catalogue.",
           "REVIEW_LIST": "This is a song list with review statuses. Upload it under Catalogue, or in a processing run.",
           "PREVIOUS_OUTPUT": "This is a master report (SKV layout). Use Reports → New processing run for it."}
_PLATFORM_ELSEWHERE = "This is a platform report (per ISRC and month). Upload it under Statements → Platform reports."
REFUSE = {"PLATFORM": dict(_REFUSE, STATEMENT="This is a royalty statement (per work). Upload it under Statements → "
                                              "IPRS statements."),
          "IPRS": dict(_REFUSE, PLATFORM_REVENUE=_PLATFORM_ELSEWHERE, PLATFORM_USAGE=_PLATFORM_ELSEWHERE)}
META_FIELDS = ("category", "dist_no", "overseas_society", "period", "date", "platform", "distributor", "currency",
               "basis")


class StatementError(RDError):
    pass


# ================================================================== registry values from the stored file
def _d(v) -> dt.date | None:
    if not v:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def _values(conn, f: dict, cfg: dict, actor: dict | None = None) -> dict:
    meta, facts, src = f["meta"] or {}, f["facts"] or {}, f["meta_source"] or {}
    if f["kind"] == STATEMENT:
        # a known platform (Spotify, YouTube Pre-Claims …), else the statement's own category becomes one (Radio, Zee
        # TV Broadcast, Overseas - SACEM (France), Other / Unclassified …), so every category can be reconciled
        p = platforms.resolve(conn, meta.get("category"), meta.get("section")) or \
            platforms.ensure(conn, meta.get("section") or meta.get("category"), actor)
        cur = (cfg.get("settings") or {}).get("iprs_currency")
        return dict(record_type="WORK_ROYALTY", category=meta.get("section") or meta.get("category"),
                    platform_id=p["id"] if p else None, reported_platform=meta.get("category"), distributor=None,
                    holder_member=meta.get("holder_member"), statement_reference=meta.get("dist_no"),
                    usage_period_start=_d(meta.get("period_start")), usage_period_end=_d(meta.get("period_end")),
                    statement_date=_d(meta.get("date")),
                    statement_date_estimated=bool(meta.get("date_estimated", True)),
                    currency=cur, currency_source="client setting (IPRS statements do not print a currency)"
                    if cur else None, revenue_basis=None, territory=meta.get("overseas_country"),
                    identity_key=meta.get("identity_key"), content_fingerprint=facts.get("content_sha256"),
                    record_count=facts.get("lines"), total_amount=facts.get("lines_total"), total_usage=None)
    months = [dt.date.fromisoformat(m) for m in (meta.get("months") or facts.get("months") or [])]
    p = platforms.resolve(conn, meta.get("platform"))
    usage_only = f["kind"] == PLATFORM_USAGE
    basis = "" if usage_only else str(meta.get("basis") or "").upper()
    first, last = (months[0], month_end(months[-1].year, months[-1].month)) if months else (None, None)
    plays = facts.get("plays")
    return dict(record_type="RECORDING_USAGE" if usage_only else "RECORDING_REVENUE", category=None,
                platform_id=p["id"] if p else None,
                reported_platform=meta.get("platform"), distributor=meta.get("distributor"),
                holder_member=None, statement_reference=names.short_label(f["filename"]),
                usage_period_start=first, usage_period_end=last, statement_date=None, statement_date_estimated=True,
                currency=None if usage_only else meta.get("currency"),
                currency_source=None if usage_only else src.get("currency"),
                revenue_basis=basis if basis in ("GROSS", "NET") else None, territory=None,
                identity_key="|".join(str(x or "") for x in ("USAGE" if usage_only else "REVENUE",
                                                             p["platform_code"] if p else meta.get("platform"),
                                                             meta.get("distributor"), first, last)),
                content_fingerprint=hashlib.sha256(f"{facts.get('total')}|{plays}|{facts.get('lines')}|"
                                                   f"{facts.get('recordings')}|{facts.get('months')}".encode()).hexdigest(),
                record_count=facts.get("lines"), total_amount=None if usage_only else facts.get("total"),
                total_usage=plays if plays not in (None, "0", 0) else None)


def _first_problem(f: dict, severities: tuple) -> str | None:
    for p in f["problems"] or []:
        if p.get("severity") in severities:
            return p.get("message")
    return None


def _same(conn, st_id: int | None, v: dict, client_id: int, source: str) -> list[dict]:
    """Imported statements on the same side that cover the same distribution (work layout) or the same platform report
    period (ISRC layout). The other side's copy of a statement is never a duplicate: it is what it is compared with."""
    if v["record_type"] == "WORK_ROYALTY":
        if not v["identity_key"]:
            return []
        return db.all(conn, "SELECT * FROM statements WHERE client_id = %s AND id IS DISTINCT FROM %s AND "
                            "import_status = 'IMPORTED' AND record_type = 'WORK_ROYALTY' AND identity_key = %s AND "
                            "statement_source = %s ORDER BY id", (client_id, st_id, v["identity_key"], source))
    if not v["platform_id"] or not v["usage_period_start"]:
        return []
    # a revenue report and a usage report of the same months are two halves of one picture, never duplicates
    return db.all(conn, "SELECT * FROM statements WHERE client_id = %s AND id IS DISTINCT FROM %s AND import_status = "
                        "'IMPORTED' AND record_type = %s AND platform_id = %s AND distributor IS NOT "
                        "DISTINCT FROM %s AND usage_period_start <= %s AND usage_period_end >= %s AND statement_source = "
                        "%s ORDER BY id", (client_id, st_id, v["record_type"], v["platform_id"], v["distributor"],
                                           v["usage_period_end"], v["usage_period_start"], source))


def register(conn, f: dict, actor: dict | None, source: str | None = None, relation: str | None = None,
             related: int | None = None, st: dict | None = None) -> dict:
    """Create or refresh the statements row of one stored file on one side (st, or the file's row for source) and
    decide its status."""
    cfg = client_cfg(conn, f["client_id"])
    v = _values(conn, f, cfg, actor)
    if st is None and source:
        st = db.one(conn, "SELECT * FROM statements WHERE file_id = %s AND statement_source = %s", (f["id"], source))
    if st:
        relation = relation if relation is not None else st["relation"]
        source = st["statement_source"]
    source = source or ("IPRS" if f["kind"] == STATEMENT else "PLATFORM")
    if relation is None:                             # a run already said this statement is an additional payment
        if db.scalar(conn, "SELECT count(*) FROM rd_run_file rf JOIN rd_run r ON r.id = rf.run_id WHERE rf.file_id = %s "
                           "AND r.state <> 'DELETED' AND NOT rf.removed AND rf.choice->>'relation' = 'SUPPLEMENTARY'",
                     (f["id"],)):
            relation = "SUPPLEMENTARY"
    status = FILE_STATUS.get(f["status"], "REJECTED")
    reason = _first_problem(f, ("ERROR",)) if status == "REJECTED" else \
        _first_problem(f, ("EXCLUDE",)) if status == "EXCLUDED" else \
        _first_problem(f, ("REVIEW",)) if status == "NEEDS_REVIEW" else None
    related_id, supersede = None, []
    if status == "IMPORTED":
        if v["record_type"] in ISRC_TYPES and not v["platform_id"]:
            status, reason = "NEEDS_REVIEW", f"We do not know the platform '{v['reported_platform']}'. Choose the " \
                                             "platform below, or ask an Admin to add it under Settings → Platforms."
        elif v["record_type"] in ISRC_TYPES and not v["usage_period_start"]:
            status, reason = "REJECTED", "This report has no usage months."
    if status == "IMPORTED" and relation == "LEAVE_OUT":
        status, reason = "EXCLUDED", "You chose to leave this file out."
    elif status == "IMPORTED":
        same = _same(conn, st["id"] if st else None, v, f["client_id"], source)
        if same:
            o = next((x for x in same if x["id"] == related), same[0])
            related_id = o["id"]
            what = "distribution" if v["record_type"] == "WORK_ROYALTY" else "platform and period" + (
                " (usage)" if v["record_type"] == "RECORDING_USAGE" else " (revenue)")
            if relation == "CORRECTION":
                supersede = [x["id"] for x in same]
                reason = f"Corrects statement #{o['id']} ({o['original_filename']}), which is kept as replaced."
            elif relation == "SUPPLEMENTARY":
                reason = f"Counted in addition to statement #{o['id']} ({o['original_filename']})."
            elif o["content_fingerprint"] and o["content_fingerprint"] == v["content_fingerprint"]:
                status = "DUPLICATE"
                reason = f"Same {what} and the same entries as statement #{o['id']} ({o['original_filename']}), so " \
                         "it is counted once."
            else:
                status = "NEEDS_REVIEW"
                reason = f"Statement #{o['id']} ({o['original_filename']}) covers the same {what} with different " \
                         "entries. Is this file a correction of it, or an additional statement?"
    vals = dict(v, statement_source=source,
                original_filename=f["filename"], file_hash=f["sha256"], import_status=status, status_reason=reason,
                relation=relation, related_statement_id=related_id,
                error_summary="; ".join(p["message"] for p in (f["problems"] or []) if p.get("severity") == "ERROR")
                or None, uploaded_by=f["uploaded_by"], uploaded_at=f["uploaded_at"])
    if st:
        db.update(conn, "statements", st["id"], vals)
        conn.execute("UPDATE statements SET updated_at = now(), processed_at = coalesce(processed_at, now()) "
                     "WHERE id = %s", (st["id"],))
        sid = st["id"]
    else:
        sid = db.insert(conn, "statements", dict(vals, client_id=f["client_id"], file_id=f["id"], processed_at="now"))
    for x in supersede:
        conn.execute("UPDATE statements SET import_status = 'SUPERSEDED', superseded_by = %s, status_reason = %s, "
                     "updated_at = now() WHERE id = %s", (sid, f"Replaced by the correction #{sid} ({f['filename']}).",
                                                          x))
        audit.record(conn, "statement.superseded", actor, "statements", x, dict(by=sid))
    return db.one(conn, "SELECT * FROM statements WHERE id = %s", (sid,))


def sync(conn, client_id: int) -> int:
    """Until 1.2.0, statement files uploaded for processing runs joined the library on their own, with a side guessed
    from their layout. Since 1.3.0 a statement joins the library only when someone uploads it here and says who sent
    it, so there is nothing to do; kept so that callers stay simple."""
    return 0


# ================================================================== upload, answers, edits
def _batch(conn, actor: dict, client_id: int, source: str, key: str) -> dict:
    """The upload batch a statement joins: the files uploaded together under one tab share a key chosen by the
    screen; the batch is numbered per client and tab when its first statement arrives (no gaps for failed uploads)."""
    b = db.one(conn, "SELECT * FROM statement_batches WHERE client_id = %s AND batch_key = %s", (client_id, key))
    if b:
        return b
    conn.execute("SELECT pg_advisory_xact_lock(84726500, %s)", (client_id,))
    b = db.one(conn, "SELECT * FROM statement_batches WHERE client_id = %s AND batch_key = %s", (client_id, key))
    if b:
        return b
    no = (db.scalar(conn, "SELECT max(batch_no) FROM statement_batches WHERE client_id = %s AND statement_source = %s",
                    (client_id, source)) or 0) + 1
    bid = db.insert(conn, "statement_batches", dict(client_id=client_id, statement_source=source, batch_no=no,
                                                    batch_key=key, created_by=actor["id"]))
    return db.one(conn, "SELECT * FROM statement_batches WHERE id = %s", (bid,))


def upload(actor: dict, client_id: int, filename: str, data: bytes, source: str | None = None,
           batch_key: str | None = None) -> dict:
    source = "IPRS" if source == "CLIENT" else source          # a screen from before 1.6.0
    if source not in SOURCES:
        raise StatementError("Choose the tab first: Platform reports or IPRS statements.")
    f, reused = intake.store(actor, client_id, filename, data, ALLOWED[source], REFUSE[source])
    with access.tx(actor, client_id) as conn:
        before = db.one(conn, "SELECT * FROM statements WHERE file_id = %s AND statement_source = %s", (f["id"], source))
        other = db.one(conn, "SELECT * FROM statements WHERE file_id = %s AND statement_source <> %s", (f["id"], source))
        st = register(conn, f, actor, source=source)
        if not before:
            key = (batch_key or "").strip()[:80] or f"single:{st['id']}"
            b = _batch(conn, actor, client_id, source, f"{source}:{key}")
            conn.execute("UPDATE statements SET batch_id = %s WHERE id = %s", (b["id"], st["id"]))
            st["batch_id"] = b["id"]
            audit.record(conn, "statement.uploaded", actor, "statements", st["id"],
                         dict(filename=f["filename"], type=st["record_type"], source=st["statement_source"],
                              status=st["import_status"], total=st["total_amount"]))
        flagged = _after_import(conn, actor, st)
        plat, people = _maps(conn)
        bno = db.scalar(conn, "SELECT batch_no FROM statement_batches WHERE id = %s", (st.get("batch_id"),))
    note = None
    if before:
        note = f"This file was uploaded before under {TAB_LABEL[source]} (#{before['id']}, " \
               f"{f['uploaded_at']:%d %b %Y}); nothing is counted twice."
    elif other:
        note = f"The same file is also under {TAB_LABEL[other['statement_source']]} (statement #{other['id']}); this " \
               f"copy is under {TAB_LABEL[source]}."
    elif reused:
        note = f"The stored copy from {f['uploaded_at']:%d %b %Y} is used."
    return dict(statement=_out(st, plat, people), note=note, enquiries_flagged=flagged, batch_no=bno)


def _after_import(conn, actor, st: dict) -> int:
    if st["import_status"] == "IMPORTED" and st["statement_source"] == "IPRS" and st["record_type"] == "WORK_ROYALTY":
        from .enquiries import flag_new_statement
        return flag_new_statement(conn, actor, st)
    return 0


def answer(actor: dict, statement_id: int, answers: dict) -> dict:
    """Answers to a statement's questions: missing metadata, or how it relates to an earlier statement."""
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        st = _get(conn, statement_id)
        f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (st["file_id"],))
        meta_ans = {k: v for k, v in answers.items() if k in META_FIELDS}
        if meta_ans:
            ov = dict(f["overrides"] or {})
            for k, v in meta_ans.items():
                ov[k] = str(v).strip() if v is not None else ""
            cfg = client_cfg(conn, f["client_id"])
            ev = detect.evaluate(f["kind"], f["facts"], f["filename"], cfg, ov,
                                 f["file_date"].isoformat() if f["file_date"] else None)
            db.update(conn, "rd_file", f["id"], dict(overrides=db.J(ov), status=ev["status"], label=ev["label"],
                                                     meta=db.J(ev["meta"]), meta_source=db.J(ev["meta_source"]),
                                                     problems=db.J(ev["problems"]),
                                                     summary=db.J(ev.get("summary") or {})))
            f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (st["file_id"],))
        relation = answers.get("relation")
        if relation is not None and relation not in ("CORRECTION", "SUPPLEMENTARY", "LEAVE_OUT", ""):
            raise StatementError("Choose correction, additional statement or leave out.")
        new = register(conn, f, actor, relation=(relation or None) if relation is not None else None,
                       related=st["related_statement_id"], st=st)
        if relation == "" and new["relation"]:
            conn.execute("UPDATE statements SET relation = NULL WHERE id = %s", (statement_id,))
            new = register(conn, f, actor, st=_get(conn, statement_id))
        for other in db.all(conn, "SELECT * FROM statements WHERE client_id = %s AND id <> %s AND identity_key = %s AND "
                                  "statement_source = %s AND import_status = 'NEEDS_REVIEW'",
                            (st["client_id"], statement_id, new["identity_key"], st["statement_source"])):
            register(conn, db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (other["file_id"],)), actor, st=other)
        audit.record(conn, "statement.answered", actor, "statements", statement_id,
                     dict(answers={k: v for k, v in answers.items()}), before=dict(status=st["import_status"]),
                     after=dict(status=new["import_status"]))
        if st["import_status"] != "IMPORTED":
            _after_import(conn, actor, new)
    return detail(actor, statement_id)


def update(actor: dict, statement_id: int, body: dict) -> dict:
    """Who sent it, and the payment date when it is known. The parsed money never changes."""
    access.require(actor, "prepare")
    with access.tx(actor) as conn:
        st = _get(conn, statement_id)
        vals = {}
        if body.get("statement_source") and body["statement_source"] != st["statement_source"]:
            new_source = body["statement_source"]
            if new_source not in SOURCES:
                raise StatementError("Choose Platform reports or IPRS statements.")
            if (new_source == "PLATFORM") != (st["record_type"] in ISRC_TYPES):
                raise StatementError("A per-ISRC report is always a platform report, and a per-work statement is "
                                     "always an IPRS statement.")
            twin = db.scalar(conn, "SELECT id FROM statements WHERE file_id = %s AND statement_source = %s",
                             (st["file_id"], new_source))
            if twin:
                raise StatementError(f"This file is already under {TAB_LABEL[new_source]} as statement #{twin}.")
            vals["statement_source"] = new_source
        if "payment_date" in body:
            vals["payment_date"] = _d(body.get("payment_date"))
        if vals:
            db.update(conn, "statements", statement_id, vals)
            audit.record(conn, "statement.updated", actor, "statements", statement_id,
                         before={k: st[k] for k in vals}, after=vals)
            if "statement_source" in vals:                # duplicates are checked again on the new side
                f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (st["file_id"],))
                new = register(conn, f, actor, st=_get(conn, statement_id))
                _after_import(conn, actor, new)
    return detail(actor, statement_id)


# ================================================================== reading
def _get(conn, statement_id: int) -> dict:
    st = db.one(conn, "SELECT * FROM statements WHERE id = %s", (statement_id,))
    if not st:
        raise StatementError("This statement does not exist, or you do not have access to it.")
    return st


def _out(st: dict, plat: dict | None = None, people: dict | None = None) -> dict:
    return dict(id=st["id"], file_id=st["file_id"], filename=st["original_filename"], source=st["statement_source"],
                source_label=SOURCE_LABEL[st["statement_source"]], side_label=SIDE_LABEL[st["statement_source"]],
                record_type=st["record_type"],
                type_label=TYPE_LABEL[st["record_type"]], category=st["category"], platform_id=st["platform_id"],
                platform=(plat or {}).get(st["platform_id"]), reported_platform=st["reported_platform"],
                distributor=st["distributor"], reference=st["statement_reference"],
                period_start=st["usage_period_start"], period_end=st["usage_period_end"],
                statement_date=st["statement_date"], statement_date_estimated=st["statement_date_estimated"],
                payment_date=st["payment_date"], currency=st["currency"], basis=st["revenue_basis"],
                territory=st["territory"], records=st["record_count"], total=st["total_amount"],
                usage=st["total_usage"],
                status=st["import_status"], status_text=STATUS_TEXT[st["import_status"]], reason=st["status_reason"],
                relation=st["relation"], related_statement_id=st["related_statement_id"],
                superseded_by=st["superseded_by"], uploaded_at=st["uploaded_at"],
                uploaded_by=(people or {}).get(st["uploaded_by"]))


def _maps(conn) -> tuple[dict, dict]:
    plat = {p["id"]: p["platform_name"] for p in db.all(conn, "SELECT id, platform_name FROM platforms")}
    people = {p["id"]: p["name"] for p in db.all(conn, "SELECT id, name FROM app_user")}
    return plat, people


def listing(actor: dict, client_id: int, record_type: str | None = None, platform_id: int | None = None,
            status: str | None = None, q: str | None = None, offset: int = 0, source: str | None = None) -> dict:
    with access.tx(actor, client_id) as conn:
        where, p = ["client_id = %(c)s"], dict(c=client_id, o=max(0, offset))
        if source:
            where.append("statement_source = %(src)s")
            p["src"] = source
        if record_type:
            where.append("record_type = %(t)s")
            p["t"] = record_type
        if platform_id:
            where.append("platform_id = %(p)s")
            p["p"] = platform_id
        if status:
            where.append("import_status = %(s)s")
            p["s"] = status
        if q:
            where.append("(original_filename ILIKE %(q)s OR statement_reference ILIKE %(q)s OR category ILIKE %(q)s)")
            p["q"] = f"%{q}%"
        sql = " AND ".join(where)
        rows = db.all(conn, f"SELECT * FROM statements WHERE {sql} ORDER BY uploaded_at DESC, id DESC OFFSET %(o)s "
                            "LIMIT 100", p)
        total = db.scalar(conn, f"SELECT count(*) FROM statements WHERE {sql}", p)
        counts = {r["import_status"]: r["n"] for r in db.all(conn, "SELECT import_status, count(*) AS n FROM statements "
                                                                   "WHERE client_id = %s AND (%s::TEXT IS NULL OR "
                                                                   "statement_source = %s) GROUP BY 1",
                                                             (client_id, source, source))}
        sides = {r["statement_source"]: r["n"] for r in db.all(conn, "SELECT statement_source, count(*) AS n FROM "
                                                                     "statements WHERE client_id = %s GROUP BY 1",
                                                               (client_id,))}
        plat, people = _maps(conn)
        used = db.all(conn, "SELECT DISTINCT p.id, p.platform_name FROM statements s JOIN platforms p ON p.id = "
                            "s.platform_id WHERE s.client_id = %s AND (%s::TEXT IS NULL OR s.statement_source = %s) "
                            "ORDER BY p.platform_name", (client_id, source, source))
    return dict(rows=[_out(r, plat, people) for r in rows], total=total, offset=offset, counts=counts, sides=sides,
                sources=[dict(value=k, label=TAB_LABEL[k]) for k in SOURCES], platforms=used,
                statuses=[dict(value=k, label=v) for k, v in STATUS_TEXT.items()],
                types=[dict(value=k, label=v) for k, v in TYPE_LABEL.items()
                       if not source or (source == "PLATFORM") == (k in ISRC_TYPES)])


def _plabel(a, b) -> str:
    if not a or not b:
        return "period not stated"
    return f"{a:%b %Y}" if (a.year, a.month) == (b.year, b.month) else f"{a:%b %Y} - {b:%b %Y}"


def _batch_out(r: dict, people: dict) -> dict:
    plats = sorted(r["platforms"] or [])
    pl = ", ".join(plats) if len(plats) <= 3 else f"{len(plats)} platforms"
    period = _plabel(r["period_start"], r["period_end"])
    label = " · ".join(x for x in (f"Batch {r['batch_no']}" if r["batch_no"] else "Without a batch", pl or None,
                                   period) if x)
    return dict(id=r["id"], batch_no=r["batch_no"], label=label, platforms=plats, period_start=r["period_start"],
                period_end=r["period_end"], period_label=period, no_period=r["no_period"], files=r["files"],
                matching=r.get("matching"), statuses={k: r[k] for k in ("IMPORTED", "NEEDS_REVIEW", "DUPLICATE",
                                                                        "EXCLUDED", "REJECTED", "SUPERSEDED") if r[k]},
                lines=r["lines"], total=r["total"], usage=r["usage"], types=sorted(r["types"] or []),
                uploaded_at=r["created_at"], uploaded_by=people.get(r["created_by"]))


_BATCH_SELECT = ("SELECT coalesce(b.id, -s.id) AS id, b.batch_no, coalesce(b.created_at, min(s.uploaded_at)) AS "
                 "created_at, coalesce(b.created_by, min(s.uploaded_by)) AS created_by, count(*) AS files, "
                 "min(s.usage_period_start) AS period_start, max(s.usage_period_end) AS period_end, count(*) FILTER "
                 "(WHERE s.usage_period_start IS NULL) AS no_period, array_agg(DISTINCT p.platform_name) FILTER (WHERE "
                 "p.platform_name IS NOT NULL) AS platforms, array_agg(DISTINCT s.record_type) AS types, "
                 + ", ".join(f"count(*) FILTER (WHERE s.import_status = '{k}') AS \"{k}\"" for k in
                             ("IMPORTED", "NEEDS_REVIEW", "DUPLICATE", "EXCLUDED", "REJECTED", "SUPERSEDED"))
                 + ", sum(s.record_count) AS lines, sum(s.total_amount) FILTER (WHERE s.import_status = 'IMPORTED') AS "
                 "total, sum(s.total_usage) FILTER (WHERE s.import_status = 'IMPORTED') AS usage FROM statements s LEFT "
                 "JOIN statement_batches b ON b.id = s.batch_id LEFT JOIN platforms p ON p.id = s.platform_id")


def batches(actor: dict, client_id: int, source: str, platform_id: int | None = None, status: str | None = None,
            q: str | None = None, offset: int = 0) -> dict:
    """One row per upload batch of a tab: its platforms, the usage period it spans, its files and their status. The
    filters pick the batches with at least one matching file."""
    source = "IPRS" if source == "CLIENT" else source
    if source not in SOURCES:
        raise StatementError("Choose Platform reports or IPRS statements.")
    with access.tx(actor, client_id) as conn:
        where, p = ["s.client_id = %(c)s", "s.statement_source = %(src)s"], dict(c=client_id, src=source,
                                                                               o=max(0, offset))
        if platform_id:
            where.append("s.platform_id = %(p)s")
            p["p"] = platform_id
        if status:
            where.append("s.import_status = %(s)s")
            p["s"] = status
        if q:
            where.append("(s.original_filename ILIKE %(q)s OR s.statement_reference ILIKE %(q)s OR s.category ILIKE "
                         "%(q)s)")
            p["q"] = f"%{q}%"
        match = f"SELECT coalesce(s.batch_id, -s.id) AS id, count(*) AS n FROM statements s WHERE {' AND '.join(where)} " \
                "GROUP BY 1"
        rows = db.all(conn, f"WITH m AS ({match}) SELECT x.*, m.n AS matching FROM ({_BATCH_SELECT} WHERE s.client_id = "
                            "%(c)s AND s.statement_source = %(src)s GROUP BY coalesce(b.id, -s.id), b.batch_no, "
                            "b.created_at, b.created_by) x JOIN m ON m.id = x.id ORDER BY x.batch_no DESC NULLS LAST, "
                            "x.created_at DESC OFFSET %(o)s LIMIT 50", p)
        total = db.scalar(conn, f"SELECT count(*) FROM ({match}) m", p)
        files = db.scalar(conn, f"SELECT count(*) FROM statements s WHERE {' AND '.join(where)}", p)
        people = {x["id"]: x["name"] for x in db.all(conn, "SELECT id, name FROM app_user")}
    return dict(rows=[_batch_out(r, people) for r in rows], total=total, files=files, offset=offset)


def batch(actor: dict, batch_id: int) -> dict:
    """One upload batch with every file in it (the files needing an answer first)."""
    with access.tx(actor) as conn:
        if batch_id < 0:                                  # a statement uploaded without a batch
            sts = db.all(conn, "SELECT * FROM statements WHERE id = %s AND batch_id IS NULL", (-batch_id,))
            cond, arg = "s.id = %s AND s.batch_id IS NULL", -batch_id
        else:
            sts = db.all(conn, "SELECT * FROM statements WHERE batch_id = %s", (batch_id,))
            cond, arg = "s.batch_id = %s", batch_id
        if not sts:
            raise StatementError("This batch does not exist, or you do not have access to it.")
        r = db.one(conn, f"{_BATCH_SELECT} WHERE {cond} GROUP BY coalesce(b.id, -s.id), b.batch_no, b.created_at, "
                         "b.created_by", (arg,))
        plat, people = _maps(conn)
    order = {"NEEDS_REVIEW": 0, "REJECTED": 1, "IMPORTED": 2}
    sts.sort(key=lambda x: (order.get(x["import_status"], 3), plat.get(x["platform_id"]) or "~",
                            x["usage_period_start"] or dt.date.max, x["original_filename"]))
    return dict(batch=_batch_out(r, people), source=sts[0]["statement_source"],
                statements=[_out(x, plat, people) for x in sts])


def detail(actor: dict, statement_id: int) -> dict:
    with access.tx(actor) as conn:
        st = _get(conn, statement_id)
        f = db.one(conn, "SELECT * FROM rd_file WHERE id = %s", (st["file_id"],))
        plat, people = _maps(conn)
        if st["record_type"] == "RECORDING_REVENUE":
            mapping = db.all(conn, "SELECT r.mapping_status AS status, count(*) AS lines, sum(r.reported_amount) AS amount, "
                                   "count(*) FILTER (WHERE r.reported_amount IS NULL) AS blank, sum(pl.plays) AS plays "
                                   "FROM client_revenue_records r JOIN rd_platform_line pl ON pl.file_id = r.file_id AND "
                                   "pl.line_no = r.line_no WHERE r.statement_id = %s GROUP BY 1 ORDER BY 1",
                             (statement_id,))
            months = db.all(conn, "SELECT r.usage_period_start AS month, count(*) AS lines, sum(r.reported_amount) AS "
                                  "amount, sum(pl.plays) AS plays FROM client_revenue_records r JOIN rd_platform_line pl "
                                  "ON pl.file_id = r.file_id AND pl.line_no = r.line_no WHERE r.statement_id = %s GROUP "
                                  "BY 1 ORDER BY 1", (statement_id,))
        elif st["record_type"] == "RECORDING_USAGE":
            mapping = db.all(conn, "SELECT mapping_status AS status, count(*) AS lines, NULL AS amount, sum(plays) AS "
                                   "plays FROM platform_usage_records WHERE statement_id = %s GROUP BY 1 ORDER BY 1",
                             (statement_id,))
            months = db.all(conn, "SELECT usage_period_start AS month, count(*) AS lines, NULL AS amount, sum(plays) AS "
                                  "plays FROM platform_usage_records WHERE statement_id = %s GROUP BY 1 ORDER BY 1",
                            (statement_id,))
        else:
            mapping = db.all(conn, "SELECT mapping_status AS status, count(*) AS lines, sum(royalty_amount) AS amount, "
                                   "count(DISTINCT internal_work_number) AS works FROM iprs_royalty_records WHERE "
                                   "statement_id = %s GROUP BY 1 ORDER BY 1", (statement_id,))
            months = []
        related = db.all(conn, "SELECT * FROM statements WHERE client_id = %s AND id <> %s AND (id = %s OR "
                               "related_statement_id = %s OR superseded_by = %s OR id = %s)",
                         (st["client_id"], statement_id, st["related_statement_id"], statement_id, statement_id,
                          st["superseded_by"]))
    fo = _file_out(f)
    questions = [q for q in fo["questions"] if q["field"] != "kind"]
    if st["import_status"] == "NEEDS_REVIEW" and st["related_statement_id"] and not st["relation"]:
        questions.append(dict(field="relation", message=st["status_reason"], options=RELATION_OPTIONS, required=True))
    if st["record_type"] in ISRC_TYPES and not st["platform_id"] and \
            not any(q["field"] == "platform" for q in questions):
        questions.append(dict(field="platform", message=st["status_reason"], required=True,
                              options=[dict(value=p, label=p) for p in sorted(set(plat.values()))]))
    for q in questions:
        if q["field"] == "platform" and not q["options"]:
            q["options"] = [dict(value=p, label=p) for p in sorted(set(plat.values()))]
    return dict(statement=_out(st, plat, people), problems=fo["problems"], questions=questions,
                meta=fo["meta"], meta_source=fo["meta_source"], layout=f["layout"], kind_label=KIND_LABEL[f["kind"]],
                sha256=f["sha256"], bytes=f["bytes"], mapping=mapping, months=months,
                related=[_out(r, plat, people) for r in related])


def records(actor: dict, statement_id: int, q: str | None = None, mapping: str | None = None,
            offset: int = 0, limit: int = 200) -> dict:
    with access.tx(actor) as conn:
        st = _get(conn, statement_id)
        p = dict(s=statement_id, o=max(0, offset), n=max(1, min(500, limit)))
        where = ["statement_id = %(s)s"]
        if mapping:
            where.append("mapping_status = %(m)s")
            p["m"] = mapping
        if st["record_type"] in ISRC_TYPES:
            if q:
                where.append("(pl.isrc = %(qu)s OR pl.title ILIKE %(q)s OR pl.album ILIKE %(q)s)")
                p.update(q=f"%{q}%", qu=q.strip().upper())
            where[0] = "st.id = %(s)s"
            if mapping:
                where[1] = ("(CASE WHEN coalesce(pl.isrc, '') = '' THEN 'NO_ISRC' ELSE coalesce(ir.mapping_status, "
                            "'UNKNOWN') END) = %(m)s")
            sql = " AND ".join(where)
            frm = ("FROM rd_platform_line pl JOIN statements st ON st.file_id = pl.file_id LEFT JOIN isrc_resolution ir "
                   "ON ir.client_id = st.client_id AND ir.isrc = pl.isrc LEFT JOIN works w ON w.id = ir.work_id")
            rows = db.all(conn, f"SELECT pl.row_no AS row, pl.month, pl.isrc, pl.title, pl.album, pl.upc, pl.amount, "
                                f"pl.plays, CASE WHEN coalesce(pl.isrc, '') = '' THEN 'NO_ISRC' ELSE "
                                f"coalesce(ir.mapping_status, 'UNKNOWN') END AS mapping_status, w.internal_work_number "
                                f"AS work_number, w.work_title {frm} WHERE {sql} ORDER BY pl.line_no OFFSET %(o)s "
                                f"LIMIT %(n)s", p)
            total = db.scalar(conn, f"SELECT count(*) {frm} WHERE {sql}", p)
        else:
            if q:
                where.append("(internal_work_number = %(qq)s OR reported_title ILIKE %(q)s OR party_name ILIKE %(q)s)")
                p.update(q=f"%{q}%", qq=q.strip())
            sql = " AND ".join(where)
            rows = db.all(conn, f"SELECT source_row_number AS row, internal_work_number AS work_number, reported_title AS "
                                f"title, party_name AS party, role, ownership_share AS own, collection_share AS coll, "
                                f"pool_reference AS pool, source_reference AS source, royalty_amount AS amount, "
                                f"mapping_status, validation_status FROM iprs_royalty_records WHERE {sql} ORDER BY "
                                f"line_no OFFSET %(o)s LIMIT %(n)s", p)
            total = db.scalar(conn, f"SELECT count(*) FROM iprs_royalty_records WHERE {sql}", p)
    return dict(rows=rows, total=total, offset=offset, record_type=st["record_type"])


def original(actor: dict, statement_id: int) -> tuple[str, bytes]:
    with access.tx(actor) as conn:
        st = _get(conn, statement_id)
    return intake.original(actor, st["file_id"])


def error_report(actor: dict, statement_id: int) -> tuple[str, bytes]:
    """The statement's problems and every line that is not matched or not valid, with its source row."""
    d = detail(actor, statement_id)
    st = d["statement"]
    with access.tx(actor) as conn:
        if st["record_type"] == "RECORDING_USAGE":
            lines = db.all(conn, "SELECT source_row_number, usage_period_start, isrc, reported_title, plays, "
                                 "mapping_status FROM platform_usage_records WHERE statement_id = %s AND mapping_status "
                                 "<> 'VERIFIED' ORDER BY line_no", (statement_id,))
            cols = [("Row", 7, None), ("Month", 12, "date"), ("ISRC", 16, None), ("Title", 40, None),
                    ("Plays", 14, None), ("Catalogue link", 18, None)]
            rows = [[x["source_row_number"], x["usage_period_start"], x["isrc"], x["reported_title"], x["plays"],
                     x["mapping_status"].replace("_", " ").lower()] for x in lines]
        elif st["record_type"] == "RECORDING_REVENUE":
            lines = db.all(conn, "SELECT r.source_row_number, r.usage_period_start, r.isrc, r.reported_title, "
                                 "r.reported_amount, r.mapping_status, r.validation_status FROM client_revenue_records r "
                                 "WHERE statement_id = %s AND (mapping_status <> 'VERIFIED' OR validation_status <> 'OK') "
                                 "ORDER BY line_no", (statement_id,))
            cols = [("Row", 7, None), ("Month", 12, "date"), ("ISRC", 16, None), ("Title", 40, None),
                    ("Amount", 14, "money"), ("Catalogue link", 18, None), ("Line check", 16, None)]
            rows = [[x["source_row_number"], x["usage_period_start"], x["isrc"], x["reported_title"],
                     x["reported_amount"], x["mapping_status"].replace("_", " ").lower(),
                     x["validation_status"].replace("_", " ").lower()] for x in lines]
        else:
            lines = db.all(conn, "SELECT source_row_number, internal_work_number, raw_work, reported_title, party_name, "
                                 "royalty_amount, mapping_status FROM iprs_royalty_records WHERE statement_id = %s AND "
                                 "mapping_status <> 'MATCHED' ORDER BY line_no", (statement_id,))
            cols = [("Row", 7, None), ("Work number", 14, None), ("As written", 14, None), ("Title", 40, None),
                    ("Party", 30, None), ("Amount", 14, "money"), ("Catalogue", 22, None)]
            rows = [[x["source_row_number"], x["internal_work_number"], x["raw_work"], x["reported_title"],
                     x["party_name"], x["royalty_amount"], x["mapping_status"].replace("_", " ").lower()]
                    for x in lines]
        audit.record(conn, "export.statement_error_report", actor, "statements", statement_id, dict(lines=len(rows)))
    head = [f"Statement #{st['id']} - {st['filename']}", f"Status: {st['status_text']}" + (
        f" - {st['reason']}" if st["reason"] else ""),
            "Unmatched lines are kept with their status; they are never discarded and never counted as zero."]
    data = xlsx.book([
        dict(title="Problems", heading=head, columns=[("Severity", 12, None), ("Problem", 100, None)],
             rows=[[p["severity"].title(), p["message"]] for p in d["problems"]]),
        dict(title="Lines to check", heading=head, columns=cols, rows=rows)])
    return f"Statement_{st['id']}_Error_Report.xlsx", data


def export_records(actor: dict, client_id: int, record_type: str, platform_id: int | None = None,
                   period_from: dt.date | None = None, period_to: dt.date | None = None,
                   statement_id: int | None = None, mapping: str | None = None, q: str | None = None,
                   source: str | None = None) -> tuple[str, bytes]:
    """Filtered revenue (or IPRS royalty) records, one row per source line, with the source row reference."""
    if record_type not in TYPE_LABEL:
        raise StatementError("Choose per-ISRC lines or per-work lines.")
    with access.tx(actor, client_id) as conn:
        code = db.scalar(conn, "SELECT code FROM client WHERE id = %s", (client_id,))
        plat, _ = _maps(conn)
        p: dict = dict(c=client_id, pl=platform_id, a=period_from, b=period_to, s=statement_id, m=mapping,
                       src=source if source in SOURCES else None)
        common = ("r.client_id = %(c)s AND r.import_status = 'IMPORTED' AND (%(src)s::TEXT IS NULL OR "
                  "r.statement_source = %(src)s) AND (%(pl)s::BIGINT IS NULL OR r.platform_id = "
                  "%(pl)s) AND (%(s)s::BIGINT IS NULL OR r.statement_id = %(s)s) AND (%(m)s::TEXT IS NULL OR "
                  "r.mapping_status = %(m)s)")
        if record_type == "RECORDING_REVENUE":
            sql = common + (" AND (%(a)s::DATE IS NULL OR r.usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR "
                            "r.usage_period_end <= %(b)s)")
            if q:
                sql += " AND (r.isrc = %(qu)s OR r.reported_title ILIKE %(q)s)"
                p.update(q=f"%{q}%", qu=q.strip().upper())
            lines = db.all(conn, f"SELECT r.*, w.internal_work_number, w.work_title, s.original_filename FROM "
                                 f"client_revenue_records r JOIN statements s ON s.id = r.statement_id LEFT JOIN works w "
                                 f"ON w.id = r.work_id WHERE {sql} ORDER BY r.usage_period_start, r.statement_id, "
                                 f"r.line_no", p)
            cols = [("Statement", 10, None), ("Source file", 36, None), ("Source row", 9, None),
                    ("Platform", 14, None), ("Usage month", 12, "date"), ("ISRC", 16, None), ("Reported title", 36, None),
                    ("Currency", 8, None), ("Basis", 8, None), ("Amount", 14, "money"), ("Catalogue link", 16, None),
                    ("Work number", 12, None), ("Work title", 32, None), ("Line check", 12, None)]
            rows = [[x["statement_id"], x["original_filename"], x["source_row_number"], plat.get(x["platform_id"]),
                     x["usage_period_start"], x["isrc"], x["reported_title"], x["currency"], x["revenue_basis"],
                     x["reported_amount"], x["mapping_status"].replace("_", " ").lower(), x["internal_work_number"],
                     x["work_title"], x["validation_status"].replace("_", " ").lower()] for x in lines]
        else:
            sql = common + (" AND (%(a)s::DATE IS NULL OR r.usage_period_start >= %(a)s) AND (%(b)s::DATE IS NULL OR "
                            "r.usage_period_end <= %(b)s)")
            if q:
                sql += " AND (r.internal_work_number = %(qq)s OR r.reported_title ILIKE %(q)s)"
                p.update(q=f"%{q}%", qq=q.strip())
            lines = db.all(conn, f"SELECT r.*, s.original_filename FROM iprs_royalty_records r JOIN statements s ON "
                                 f"s.id = r.statement_id WHERE {sql} ORDER BY r.statement_id, r.line_no", p)
            cols = [("Statement", 10, None), ("Source file", 36, None), ("Source row", 9, None),
                    ("Category", 18, None), ("Platform", 14, None), ("Distribution", 12, None),
                    ("Period from", 12, "date"), ("Period to", 12, "date"), ("Work number", 12, None),
                    ("Title", 36, None), ("Party", 30, None), ("Role", 6, None), ("Own %", 8, "pct"),
                    ("Coll %", 8, "pct"), ("Pool", 16, None), ("Source", 20, None), ("Currency", 8, None),
                    ("Royalty", 14, "money"), ("Catalogue", 14, None)]
            rows = [[x["statement_id"], x["original_filename"], x["source_row_number"], x["category"],
                     plat.get(x["platform_id"]), x["statement_reference"], x["usage_period_start"],
                     x["usage_period_end"], x["internal_work_number"], x["reported_title"], x["party_name"], x["role"],
                     x["ownership_share"], x["collection_share"], x["pool_reference"], x["source_reference"],
                     x["currency"], x["royalty_amount"], x["mapping_status"].replace("_", " ").lower()] for x in lines]
        audit.record(conn, "export.records", actor, "client", client_id,
                     dict(type=record_type, platform_id=platform_id, period_from=period_from, period_to=period_to,
                          statement_id=statement_id, rows=len(rows)))
    span = f"{period_from:%Y-%m}_to_{period_to:%Y-%m}" if period_from and period_to else "All_Periods"
    what = "Platform_Revenue_Records" if record_type == "RECORDING_REVENUE" else \
        "IPRS_Statement_Records" if source == "IPRS" else "Per_Work_Records"
    pname = xlsx.safe_name(plat.get(platform_id, "")) if platform_id else ""
    name = "_".join(x for x in (code, pname, what, span) if x) + ".xlsx"
    heading = [f"{code} - {TYPE_LABEL[record_type]}",
               "Filters: " + ", ".join(x for x in (
                   f"platform {plat.get(platform_id)}" if platform_id else "all platforms",
                   f"usage {period_from:%b %Y} to {period_to:%b %Y}" if period_from and period_to else "all periods",
                   f"statement #{statement_id}" if statement_id else None,
                   f"catalogue link {mapping.lower()}" if mapping else None, f"search '{q}'" if q else None) if x),
               "Only imported statements are included. A blank amount is unknown, not zero."]
    return name, xlsx.book([dict(title="Records", heading=heading, columns=cols, rows=rows)])


# ================================================================== platform reports: revenue and usage combined
# A platform often sends revenue and usage in two files. Line by line they are combined by ISRC (by song name when a
# line has no ISRC) and month. The plays of a month come from the usage report when one covers that month, otherwise
# from the revenue report's own plays column, so nothing is counted twice.
_TKEY = "lower(regexp_replace(coalesce(pl.title, ''), '[^[:alnum:]]+', '', 'g'))"
_COMBINED = f"""
WITH ln AS (
  SELECT st.platform_id, pl.month, nullif(pl.isrc, '') AS isrc, pl.title, pl.album, {_TKEY} AS tkey,
         st.record_type, CASE WHEN st.record_type = 'RECORDING_REVENUE' THEN pl.amount END AS revenue, pl.plays
    FROM rd_platform_line pl JOIN statements st ON st.file_id = pl.file_id
   WHERE st.client_id = %(c)s AND st.statement_source = 'PLATFORM' AND st.import_status = 'IMPORTED'
     AND (%(pl)s::BIGINT IS NULL OR st.platform_id = %(pl)s)
     AND (%(a)s::DATE IS NULL OR pl.month >= %(a)s) AND (%(b)s::DATE IS NULL OR pl.month <= %(b)s)),
um AS (SELECT DISTINCT platform_id, month FROM ln WHERE record_type = 'RECORDING_USAGE'),
c AS (
  SELECT ln.platform_id, ln.month, coalesce(ln.isrc, 'TITLE:' || ln.tkey) AS k, min(ln.isrc) AS isrc,
         coalesce(min(ln.title) FILTER (WHERE ln.record_type = 'RECORDING_REVENUE'), min(ln.title)) AS title,
         min(ln.album) AS album,
         sum(ln.revenue) AS revenue, count(*) FILTER (WHERE ln.record_type = 'RECORDING_REVENUE') AS revenue_lines,
         sum(ln.plays) FILTER (WHERE ln.record_type = 'RECORDING_USAGE' OR um.month IS NULL) AS usage,
         count(*) FILTER (WHERE ln.record_type = 'RECORDING_USAGE' OR (um.month IS NULL AND ln.plays IS NOT NULL))
           AS usage_lines,
         count(DISTINCT ln.tkey) > 1 AS names_differ
    FROM ln LEFT JOIN um ON um.platform_id = ln.platform_id AND um.month = ln.month
   GROUP BY 1, 2, 3)"""


def _cf(platform_id, period_from, period_to) -> dict:
    a = _d(period_from)
    b = _d(period_to)
    return dict(pl=int(platform_id) if platform_id else None, a=a.replace(day=1) if a else None,
                b=month_end(b.year, b.month) if b else None)


def combined(actor: dict, client_id: int, platform_id=None, period_from=None, period_to=None, q: str | None = None,
             only: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """The platform reports combined: per platform, ISRC (song) the revenue and the usage of the selected months, with
    the months each side covers. only: 'both' | 'revenue_only' | 'usage_only' | 'names_differ'."""
    p = dict(c=client_id, o=max(0, offset), n=max(1, min(500, limit)), **_cf(platform_id, period_from, period_to))
    having = {"both": "bool_or(c.revenue_lines > 0) AND bool_or(c.usage_lines > 0)",
              "revenue_only": "NOT bool_or(c.usage_lines > 0)", "usage_only": "NOT bool_or(c.revenue_lines > 0)",
              "names_differ": "bool_or(c.names_differ)"}.get(only or "")
    where = ""
    if q:
        where = "WHERE (c.isrc = %(qu)s OR c.title ILIKE %(q)s OR w.internal_work_number = %(qq)s)"
        p.update(q=f"%{q.strip()}%", qu=q.strip().upper(), qq=q.strip())
    sel = (f"{_COMBINED} SELECT c.platform_id, c.k, min(c.isrc) AS isrc, min(c.title) AS title, min(c.album) AS album, "
           "sum(c.revenue) AS revenue, sum(c.usage) AS usage, sum(c.revenue_lines) AS revenue_lines, "
           "sum(c.usage_lines) AS usage_lines, array_agg(c.month ORDER BY c.month) FILTER (WHERE c.revenue_lines > 0) "
           "AS revenue_months, array_agg(c.month ORDER BY c.month) FILTER (WHERE c.usage_lines > 0) AS usage_months, "
           "bool_or(c.names_differ) AS names_differ, min(w.internal_work_number) AS work_number, min(w.work_title) AS "
           "work_title, min(coalesce(ir.mapping_status, CASE WHEN c.isrc IS NULL THEN 'NO_ISRC' ELSE 'UNKNOWN' END)) "
           "AS mapping_status FROM c LEFT JOIN isrc_resolution ir ON ir.client_id = %(c)s AND ir.isrc = c.isrc LEFT "
           f"JOIN works w ON w.id = ir.work_id {where} GROUP BY 1, 2" + (f" HAVING {having}" if having else ""))
    with access.tx(actor, client_id) as conn:
        rows = db.all(conn, f"{sel} ORDER BY sum(c.revenue) DESC NULLS LAST, sum(c.usage) DESC NULLS LAST, 2 "
                            "OFFSET %(o)s LIMIT %(n)s", p)
        tot = db.one(conn, f"SELECT count(*) AS n, sum(revenue) AS revenue, sum(usage) AS usage, count(*) FILTER "
                           f"(WHERE revenue_lines > 0 AND usage_lines > 0) AS both, count(*) FILTER (WHERE "
                           f"usage_lines = 0) AS revenue_only, count(*) FILTER (WHERE revenue_lines = 0) AS usage_only, "
                           f"count(*) FILTER (WHERE names_differ) AS names_differ FROM ({sel}) x", p)
        months = db.all(conn, f"{_COMBINED} SELECT c.platform_id, c.month, sum(c.revenue) AS revenue, sum(c.usage) AS "
                              "usage, count(*) FILTER (WHERE c.revenue_lines > 0) AS revenue_songs, count(*) FILTER "
                              "(WHERE c.usage_lines > 0) AS usage_songs, count(*) FILTER (WHERE c.revenue_lines > 0 AND "
                              "c.usage_lines > 0) AS both_songs FROM c GROUP BY 1, 2 ORDER BY 1, 2", p)
        plat, _ = _maps(conn)
        used = db.all(conn, "SELECT DISTINCT p.id, p.platform_name FROM statements s JOIN platforms p ON p.id = "
                            "s.platform_id WHERE s.client_id = %s AND s.statement_source = 'PLATFORM' AND "
                            "s.import_status = 'IMPORTED' ORDER BY p.platform_name", (client_id,))
    for r in rows:
        r["platform"] = plat.get(r["platform_id"])
        r.pop("k", None)
    for m in months:
        m["platform"] = plat.get(m["platform_id"])
    return dict(rows=rows, total=tot["n"], totals=tot, months=months, platforms=used, offset=offset)


def export_combined(actor: dict, client_id: int, platform_id=None, period_from=None, period_to=None,
                    q: str | None = None, only: str | None = None) -> tuple[str, bytes]:
    """The combined platform data as a workbook: one row per ISRC (song) for the period, and one per ISRC and month."""
    p = dict(c=client_id, **_cf(platform_id, period_from, period_to))
    first = combined(actor, client_id, platform_id, period_from, period_to, q, only, 0, 500)
    rows, off = list(first["rows"]), 500
    while off < first["total"]:
        rows += combined(actor, client_id, platform_id, period_from, period_to, q, only, off, 500)["rows"]
        off += 500
    with access.tx(actor, client_id) as conn:
        code = db.scalar(conn, "SELECT code FROM client WHERE id = %s", (client_id,))
        per_month = db.all(conn, f"{_COMBINED} SELECT c.*, w.internal_work_number, w.work_title FROM c LEFT JOIN "
                                 "isrc_resolution ir ON ir.client_id = %(c)s AND ir.isrc = c.isrc LEFT JOIN works w ON "
                                 "w.id = ir.work_id ORDER BY c.platform_id, c.k, c.month", p)
        plat, _ = _maps(conn)
        audit.record(conn, "export.platform_combined", actor, "client", client_id,
                     dict(rows=len(rows), platform_id=platform_id, period_from=period_from, period_to=period_to))
    span = (f"{p['a']:%Y-%m}_to_{p['b']:%Y-%m}" if p["a"] and p["b"] else "All_Periods")
    head = [f"{code} - platform reports, revenue and usage combined by ISRC and song name",
            "Plays come from the usage report of a month when there is one, otherwise from the revenue report's own "
            "plays column. An empty cell means no record for that side, not zero."]
    by_isrc = [[r["platform"], r["isrc"], r["title"], r["album"], r["work_number"], r["work_title"],
                (r["mapping_status"] or "").replace("_", " ").lower(), r["revenue"], r["usage"],
                len(r["revenue_months"] or []), len(r["usage_months"] or []),
                "names differ" if r["names_differ"] else None] for r in rows]
    by_month = [[plat.get(r["platform_id"]), r["month"], r["isrc"], r["title"], r["album"], r["internal_work_number"],
                 r["work_title"], r["revenue"], r["usage"], r["revenue_lines"], r["usage_lines"],
                 "names differ" if r["names_differ"] else None] for r in per_month]
    data = xlsx.book([
        dict(title="By ISRC", heading=head, columns=[
            ("Platform", 14, None), ("ISRC", 16, None), ("Song name", 36, None), ("Album", 30, None),
            ("Work number", 12, None), ("Work title", 30, None), ("Catalogue link", 14, None),
            ("Revenue", 15, "money"), ("Usage (plays)", 14, None), ("Months with revenue", 10, None),
            ("Months with usage", 10, None), ("Check", 14, None)], rows=by_isrc),
        dict(title="By month", heading=head, columns=[
            ("Platform", 14, None), ("Month", 12, "date"), ("ISRC", 16, None), ("Song name", 36, None),
            ("Album", 30, None), ("Work number", 12, None), ("Work title", 30, None), ("Revenue", 15, "money"),
            ("Usage (plays)", 14, None), ("Revenue lines", 9, None), ("Usage lines", 9, None), ("Check", 14, None)],
             rows=by_month)])
    return f"{code}_Platform_Revenue_and_Usage_{span}.xlsx", data
