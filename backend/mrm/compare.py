"""D. like-for-like groups, F. calculation route, G. outcomes (pages 5, 7, 8).

One group per client/beneficiary + composition + platform + territory + usage period + use type + publishing-right
scope. R is summed across the group's mapped masters once; P is matched at composition level once (never repeated
per ISRC). Blank stays blank: a missing publishing entry is not a zero, a missing statement is not an unpaid royalty.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from . import audit, db, rules
from .normalize import ZERO, as_date, month_end, months_between, period_label, q2, s
from .parsing.iprs import beneficiary_lines
from .parsing.scope import use_type_of

ONE = Decimal(1)
OUTCOMES = ("BELOW_COMPARISON", "NO_MATCHING_ENTRY", "STATUS_ENQUIRY", "HOLD", "COVERAGE_ONLY", "WITHIN_OR_ABOVE")
OUTCOME_LABEL = {"BELOW_COMPARISON": "Below comparison amount", "NO_MATCHING_ENTRY": "No matching entry (provisional)",
                 "STATUS_ENQUIRY": "Status enquiry", "HOLD": "Hold", "COVERAGE_ONLY": "Coverage-only review",
                 "WITHIN_OR_ABOVE": "Within / above benchmark"}
HOLD_REASONS = ("DATA_GAP", "MAPPING", "BASIS", "RIGHTS", "PENDING_DISTRIBUTION")
P_STATUS_LABEL = {"FOUND": "entry found", "EXPLICIT_ZERO": "explicit zero in statement",
                  "NOT_FOUND": "not found in statements reviewed", "PENDING_CYCLE": "distribution cycle pending",
                  "MISSING_STATEMENT": "statement missing"}
ENQUIRY_OUTCOMES = ("BELOW_COMPARISON", "NO_MATCHING_ENTRY", "STATUS_ENQUIRY", "COVERAGE_ONLY")


class RunError(Exception):
    pass


def _short(platform: str) -> str:
    return "".join(ch for ch in platform.upper() if ch.isalnum())[:4] or "PLAT"


def case_code(client_code: str, platform: str, work_code: str, pf: dt.date, pt: dt.date, scope: str) -> str:
    sc = "" if scope == "PERFORMING" else "-" + scope[:4]
    return f"{client_code}-{_short(platform)}-{work_code}-{pf:%y%m}{pt:%y%m}{sc}"


def _in_period(month: dt.date | None, f_meta: dict, pf: dt.date, pt: dt.date) -> bool:
    if month is not None:
        return pf <= month <= pt
    a, b = as_date(f_meta.get("period_from")), as_date(f_meta.get("period_to"))
    return bool(a and b and pf <= a and b <= pt)


def run(conn, actor: dict, client_id: int, platform: str, territory: str, use_type: str, right_scope: str,
        period_from, period_to, cutoff=None, distribution_lag_months: int = 6) -> dict:
    client = db.one(conn, "SELECT * FROM client WHERE id = %s", (client_id,))
    if not client:
        raise RunError("unknown client")
    pf, pt = as_date(period_from), as_date(period_to)
    if not pf or not pt or pt < pf:
        raise RunError("usage period from / to are required dates (from <= to)")
    pf, pt = pf.replace(day=1), month_end(pt.year, pt.month)
    cut = as_date(cutoff) or dt.date.today()
    territory = s(territory).upper()
    if not (s(platform) and territory and s(use_type) and s(right_scope)):
        raise RunError("platform, territory, use type and publishing-right scope are all required")
    iv = db.one(conn, "SELECT * FROM identity_version WHERE client_id = %s AND status = 'APPROVED'", (client_id,))
    if not iv:
        raise RunError("no approved identity version for this client (C5) - approve one on the Identity page first")
    no = (db.scalar(conn, "SELECT max(version_no) FROM comparison_run WHERE client_id = %s", (client_id,)) or 0) + 1
    rid = db.insert(conn, "comparison_run", dict(
        client_id=client_id, version_no=no, platform=platform, territory=territory, use_type=use_type,
        right_scope=right_scope, period_from=pf, period_to=pt, cutoff=cut, identity_version_id=iv["id"],
        status="RUNNING", created_by=actor["id"]))
    ctx = dict(client=client, platform=platform, territory=territory, use_type=use_type, scope=right_scope, pf=pf,
               pt=pt, cutoff=cut, lag=distribution_lag_months, iv=iv, run_id=rid)
    result = _compute(conn, ctx)
    conn.execute("UPDATE comparison_run SET status = 'COMPLETE', summary = %s, checks = %s, file_ids = %s, "
                 "rule_version_ids = %s WHERE id = %s",
                 (db.J(result["summary"]), db.J(result["checks"]), result["file_ids"], result["rule_ids"], rid))
    audit.record(conn, "run.completed", actor, "comparison_run", rid,
                 dict(version_no=no, scope=dict(platform=platform, territory=territory, use_type=use_type,
                                                right_scope=right_scope, period=period_label(pf, pt),
                                                cutoff=cut.isoformat()),
                      identity_version=iv["version_no"], groups=result["summary"]["groups"],
                      outcomes=result["summary"]["outcomes"]))
    return dict(run_id=rid, version_no=no, summary=result["summary"], checks=result["checks"])


# ------------------------------------------------------------------ the computation
def _compute(conn, ctx: dict) -> dict:
    c, plat, terr, use, scope, pf, pt = (ctx["client"], ctx["platform"], ctx["territory"], ctx["use_type"],
                                         ctx["scope"], ctx["pf"], ctx["pt"])
    rid = ctx["run_id"]
    files = db.all(conn, "SELECT * FROM source_file WHERE client_id = %s AND status = 'VALIDATED' AND income_type IN "
                         "('PUBLISHING', 'RECORDING', 'USAGE') ORDER BY id", (c["id"],))

    def file_in_scope(f, need_platform=True):
        m = f["meta"]
        a, b = as_date(m.get("period_from")), as_date(m.get("period_to"))
        if not (a and b and a <= pt and pf <= b):
            return False
        if s(m.get("territory")).upper() != terr:
            return False
        if need_platform and m.get("platform") and m["platform"] != plat:
            return False
        return True

    rec_files = [f for f in files if f["income_type"] == "RECORDING" and file_in_scope(f)]
    use_files = [f for f in files if f["income_type"] in ("USAGE", "RECORDING") and file_in_scope(f)]
    pub_files = [f for f in files if f["income_type"] == "PUBLISHING" and file_in_scope(f, need_platform=False)]
    fmeta = {f["id"]: f for f in files}
    exceptions: list[dict] = []

    # ---- recording side (R) and usage (N)
    r_lines = [x for x in db.all(conn, "SELECT l.*, s.meta AS fm FROM recording_line l JOIN source_file s ON s.id = "
                                       "l.file_id WHERE l.file_id = ANY(%s) AND l.is_valid AND l.duplicate_state <> "
                                       "'SUPPRESSED' ORDER BY l.file_id, l.row_no", ([f["id"] for f in rec_files],))
               if (x["platform"] or x["fm"].get("platform")) == plat and _in_period(x["month"], x["fm"], pf, pt)]
    scope_unknown_r = [x for x in r_lines if (_line_use(x) or x["fm"].get("use_type")) is None]
    r_lines = [x for x in r_lines if (_line_use(x) or x["fm"].get("use_type")) == use]
    n_lines = [x for x in db.all(conn, "SELECT l.*, s.meta AS fm FROM usage_line l JOIN source_file s ON s.id = "
                                       "l.file_id WHERE l.file_id = ANY(%s) AND l.is_valid AND l.duplicate_state <> "
                                       "'SUPPRESSED' ORDER BY l.file_id, l.row_no", ([f["id"] for f in use_files],))
               if (x["platform"] or x["fm"].get("platform")) == plat and _in_period(x["month"], x["fm"], pf, pt)
               and (x.get("use_type") or x["fm"].get("use_type") or use) == use]
    if scope_unknown_r:
        exceptions.append(dict(kind="SCOPE_UNKNOWN", subject="recording rows without a use type",
                               amount=sum((x["amount"] for x in scope_unknown_r), ZERO),
                               detail=dict(rows=len(scope_unknown_r)), owner="importer",
                               next_action="state the use type (audio / UGC / OTT) of these rows"))
    run_months = months_between(pf, pt)
    r_months = sorted({x["month"] for x in r_lines if x["month"]})
    n_months = sorted({x["month"] for x in n_lines if x["month"]})

    # ---- publishing side (P)
    names = [n for n in (c["beneficiary_name"], c["name"]) if n]
    all_p = db.all(conn, "SELECT l.*, s.meta AS fm FROM publishing_line l JOIN source_file s ON s.id = l.file_id "
                         "WHERE l.file_id = ANY(%s) AND l.is_valid ORDER BY l.file_id, l.row_no",
                   ([f["id"] for f in pub_files],))
    mine = beneficiary_lines(all_p, names)
    others_share = len(all_p) - len(mine)
    p_platform = [x for x in mine if x["platform"] == plat]
    p_scope_unknown = [x for x in p_platform if x["right_scope"] == "UNKNOWN"]
    p_other_scope = [x for x in p_platform if x["right_scope"] not in (scope, "UNKNOWN")]
    p_lines = [x for x in p_platform if x["right_scope"] == scope and (x["use_type"] or use) == use]
    if p_other_scope:
        exceptions.append(dict(kind="OTHER_RIGHT_SCOPE", subject=f"{len(p_other_scope)} publishing line(s) for "
                                                                f"{', '.join(sorted({x['right_scope'] for x in p_other_scope}))}",
                               amount=sum((x["amount"] for x in p_other_scope), ZERO),
                               detail=dict(rows=len(p_other_scope)), owner="accounts",
                               next_action="compare in a separate run for that right scope - mixed rights stay "
                                           "separate"))
    if p_scope_unknown:
        exceptions.append(dict(kind="SCOPE_UNKNOWN", subject="publishing lines with no pool / right scope",
                               amount=sum((x["amount"] for x in p_scope_unknown), ZERO),
                               detail=dict(rows=len(p_scope_unknown)), owner="importer",
                               next_action="request a breakdown from the society; never invent an allocation"))
    statements = []
    for f in pub_files:
        a, b = as_date(f["meta"].get("period_from")), as_date(f["meta"].get("period_to"))
        has_plat = any(x["platform"] == plat for x in all_p if x["file_id"] == f["id"])
        if has_plat:
            statements.append(dict(file_id=f["id"], filename=f["filename"], period_from=a, period_to=b,
                                   member_id=f["meta"].get("member_id")))
    if statements:
        covered = set()
        for st in statements:
            covered.update(months_between(max(st["period_from"], pf), min(st["period_to"], pt)))
        coverage = "FULL" if all(m in covered for m in run_months) else "PARTIAL"
    else:
        expected = _add_months(pt, ctx["lag"])
        coverage = "PENDING" if ctx["cutoff"] < expected else "MISSING"
    member_mismatch = sorted({st["member_id"] for st in statements if st["member_id"] and c["member_id"]
                              and st["member_id"] != c["member_id"]})

    # ---- identity version: recording -> works (with allocation)
    vlinks = db.all(conn, "SELECT v.composition_id, v.allocation, r.isrc FROM identity_version_link v JOIN recording r "
                          "ON r.id = v.recording_id WHERE v.version_id = %s", (ctx["iv"]["id"],))
    by_isrc: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    for v in vlinks:
        by_isrc[v["isrc"]].append((v["composition_id"], v["allocation"] if v["allocation"] is not None else ONE))
    comp_rows = db.all(conn, "SELECT * FROM composition WHERE client_id = %s", (c["id"],))
    comps = {x["id"]: x for x in comp_rows}
    root = {}
    for x in comp_rows:
        y, seen = x["id"], set()
        while comps[y]["canonical_id"] and y not in seen:
            seen.add(y)
            y = comps[y]["canonical_id"]
        root[x["id"]] = y
    code_to_root = {x["work_code"]: root[x["id"]] for x in comp_rows}
    linked_roots = {cid for ls in by_isrc.values() for cid, _ in ls}

    groups: dict[int, dict] = {}

    def g(cid: int) -> dict:
        if cid not in groups:
            groups[cid] = dict(composition_id=cid, r=None, n=None, p=None, r_rows=[], n_rows=[], p_rows=[],
                               masters=defaultdict(lambda: dict(r=None, n=None, title=None, allocation=ONE)),
                               r_files=set(), n_months=set(), p_codes=set())
        return groups[cid]

    unmapped: dict[str, dict] = defaultdict(lambda: dict(r=ZERO, n=0, rows=0, title=None, has_r=False))
    for x in r_lines:
        links = by_isrc.get(x["isrc"])
        if not links:
            u = unmapped[x["isrc"]]
            u["r"] += x["amount"]
            u["has_r"] = True
            u["rows"] += 1
            u["title"] = u["title"] or x["title"]
            continue
        for cid, alloc in links:
            grp = g(cid)
            share = x["amount"] * alloc
            grp["r"] = (grp["r"] or ZERO) + share
            m = grp["masters"][x["isrc"]]
            m["r"] = (m["r"] or ZERO) + share
            m["title"], m["allocation"] = m["title"] or x["title"], alloc
            grp["r_files"].add(x["file_id"])
            grp["r_rows"].append(dict(file_id=x["file_id"], row=x["row_no"], sheet=x["sheet"], isrc=x["isrc"],
                                      month=x["month"], amount=x["amount"], allocation=alloc,
                                      currency=x["currency"] or x["fm"].get("currency")))
    for x in n_lines:
        links = by_isrc.get(x["isrc"])
        if not links:
            u = unmapped[x["isrc"]]
            u["n"] += x["streams"]
            u["rows"] += 1
            u["title"] = u["title"] or x["title"]
            continue
        for cid, alloc in links:
            grp = g(cid)
            grp["n"] = (grp["n"] or ZERO) + x["streams"] * alloc
            m = grp["masters"][x["isrc"]]
            m["n"] = (m["n"] or ZERO) + x["streams"] * alloc
            m["title"] = m["title"] or x["title"]
            if x["month"]:
                grp["n_months"].add(x["month"])
            grp["n_rows"].append(dict(file_id=x["file_id"], row=x["row_no"], sheet=x["sheet"], isrc=x["isrc"],
                                      month=x["month"], streams=x["streams"], allocation=alloc))
    p_unregistered = []
    for x in p_lines:
        cid = code_to_root.get(x["work_code"])
        if cid is None:
            p_unregistered.append(x)
            continue
        grp = g(cid)
        grp["p"] = (grp["p"] or ZERO) + x["amount"]
        grp["p_codes"].add(x["work_code"])
        grp["p_rows"].append(dict(file_id=x["file_id"], row=x["row_no"], sheet=x["sheet"], work_code=x["work_code"],
                                  title=x["title"], party=x["party"], role=x["role"], pool=x["pool"],
                                  source=x["source"], amount=x["amount"]))
    for code, u in sorted(unmapped.items(), key=lambda kv: -(kv[1]["r"])):
        exceptions.append(dict(kind="UNMAPPED_RECORDING", subject=f"{code} {u['title'] or ''}".strip(),
                               amount=u["r"] if u["has_r"] else None, streams=u["n"] or None,
                               detail=dict(isrc=code, title=u["title"], rows=u["rows"]), owner="rights_reviewer",
                               next_action="link to its work on the Identity page (evidence + approval), then re-run"))

    # ---- rule (E) - one scope per run
    sel = rules.select(conn, c["id"], plat, terr, use, pf, pt)
    rule = sel["rule"]
    rule_ids = [rule["id"]] if rule else []

    # ---- open identity matters touching grouped works
    open_issue_codes = {r["subject_key"] for r in db.all(conn, "SELECT subject_key FROM identity_issue WHERE "
                                                               "client_id = %s AND status = 'OPEN' AND kind = "
                                                               "'TITLE_MISMATCH'", (c["id"],))}
    deferred = defaultdict(list)
    for r in db.all(conn, "SELECT a_id, b_id, status FROM duplicate_candidate WHERE client_id = %s AND status IN "
                          "('DEFERRED', 'PENDING')", (c["id"],)):
        deferred[root.get(r["a_id"], r["a_id"])].append(r["b_id"])
        deferred[root.get(r["b_id"], r["b_id"])].append(r["a_id"])

    # ---- file-level facts for D4 / D5
    p_currency = {fmeta[f]["meta"].get("currency") for f in {x["file_id"] for x in p_lines}} or \
        {f["meta"].get("currency") for f in pub_files}
    rows_out = []
    case_by_cid = {}
    for cid, grp in groups.items():
        comp = comps[cid]
        code = case_code(c["code"], plat, comp["work_code"], pf, pt, scope)
        case_by_cid[cid] = code
        gates, limits = [], []
        hold = None

        def gate(name, ok, detail, reason=None):  # noqa: B023 - used within this iteration only
            nonlocal hold
            gates.append(dict(gate=name, result="PASS" if ok else "HOLD", detail=detail))
            if not ok and hold is None:
                hold = (reason, detail)

        gate("D1", True, f"{len(grp['masters'])} master(s), {len(grp['p_rows'])} publishing line(s) linked to "
                         f"work {comp['work_code']} (identity v{ctx['iv']['version_no']})")
        # mapping
        if cid not in linked_roots:
            gate("C3", False, "no approved recording is linked to this work in the identity version", "MAPPING")
        elif comp["work_code"] in open_issue_codes or (grp["p_codes"] & open_issue_codes):
            gate("C3", False, "statement and catalogue titles differ for this work code - mapping review open",
                 "MAPPING")
        else:
            gate("C3", True, "work-to-recording links approved")
        if deferred.get(cid):
            limits.append("a possible duplicate work registration is deferred for review")
        # D2 rights
        m_ok, m_detail = True, "mandate verified"
        if not c["mandate_verified"]:
            m_ok, m_detail = False, "client publishing authority (mandate) is not verified - label ownership alone " \
                                    "is insufficient"
        elif c["mandate_from"] and c["mandate_from"] > pf or c["mandate_to"] and c["mandate_to"] < pt:
            m_ok, m_detail = False, "mandate dates do not cover the usage period"
        elif c["territories"] and terr not in c["territories"]:
            m_ok, m_detail = False, f"territory {terr} is outside the mandate ({', '.join(c['territories'])})"
        elif member_mismatch:
            m_ok, m_detail = False, f"statement member ID {', '.join(member_mismatch)} differs from the mandate " \
                                    f"({c['member_id']})"
        gate("D2", m_ok, m_detail, "RIGHTS")
        # D3 scope
        gate("D3", True, f"{plat} / {terr} / {use.replace('_', ' ').lower()} / {scope.lower()} rights - other scopes "
                         f"kept separate")
        # D4 timing / coverage
        if grp["r"] is not None:
            missing_r = [m for m in run_months if m not in r_months]
            if missing_r:
                gate("D4", False, f"recording revenue covers {len(run_months) - len(missing_r)} of {len(run_months)} "
                                  f"months (missing {', '.join(m.strftime('%b %Y') for m in missing_r[:6])})",
                     "DATA_GAP")
        if coverage == "PARTIAL":
            gate("D4", False, "publishing statements cover only part of the usage period - record missing cycles",
                 "PENDING_DISTRIBUTION")
        elif hold is None or hold[0] != "DATA_GAP":
            gate("D4", True, {"FULL": "statement covers the whole usage period",
                              "PENDING": f"no statement yet; distribution not expected before "
                                         f"{_add_months(pt, ctx['lag']):%d %b %Y}",
                              "MISSING": "no statement received for this period"}[coverage])
        # D5 basis
        bases = {fmeta[f]["meta"].get("basis") for f in grp["r_files"]}
        shares = {fmeta[f]["meta"].get("share") for f in grp["r_files"]}
        cur_r = {fmeta[f]["meta"].get("currency") for f in grp["r_files"]}
        d5 = []
        if grp["r"] is not None:
            if len(cur_r) > 1:
                d5.append(f"recording revenue in several currencies ({', '.join(sorted(map(str, cur_r)))}) - FX bridge "
                          f"needed")
            if p_currency and cur_r and not (cur_r <= p_currency) and grp["p"] is not None:
                d5.append(f"recording currency {', '.join(sorted(map(str, cur_r)))} differs from publishing "
                          f"{', '.join(sorted(map(str, p_currency)))}")
            if None in bases or len(bases) > 1:
                d5.append("recording revenue basis (gross / net) not confirmed or mixed")
            if None in shares or len(shares) > 1:
                d5.append("recording revenue share not confirmed")
            if rule and rule["revenue_basis"] and bases and bases != {rule["revenue_basis"]}:
                d5.append(f"rule is defined on {rule['revenue_basis'].lower()} revenue; report is "
                          f"{', '.join(sorted(map(str, bases))).lower()}")
            if rule and rule["currency"] and cur_r and cur_r != {rule["currency"]}:
                d5.append(f"rule currency {rule['currency']} differs from revenue currency")
        gate("D5", not d5, "; ".join(d5) if d5 else "currency, basis and share confirmed and comparable", "BASIS")

        # P status (G3) - distinct statuses
        if grp["p"] is not None:
            p_status = "EXPLICIT_ZERO" if grp["p"] == 0 else "FOUND"
        elif coverage in ("FULL", "PARTIAL"):
            p_status = "NOT_FOUND"
        else:
            p_status = "PENDING_CYCLE" if coverage == "PENDING" else "MISSING_STATEMENT"

        # E + F
        r_amt = grp["r"]
        n_amt = grp["n"]
        method = sel["method"]
        b, b_stream, route, formula = None, None, None, None
        money_ok = r_amt is not None and r_amt > 0
        if method in ("RULE_HOLD", "CONFIGURATION_HOLD"):
            route = "MONEY" if money_ok else ("STREAM" if n_amt else "INSUFFICIENT")
        elif method == "NO_BENCHMARK":
            route = "COVERAGE" if (money_ok or n_amt) else "INSUFFICIENT"
        elif money_ok and rule["rate"] is not None:
            route = "MONEY"
            b, formula = rules.benchmark_amount(rule, r_amt)
            if n_amt and rule["stream_rate"] is not None:
                b_stream = n_amt * rule["stream_rate"]
        elif n_amt and rule["stream_rate"] is not None:
            route = "STREAM"
            b = n_amt * rule["stream_rate"]
            formula = f"B = N x q = {q2(n_amt):,.0f} x {rule['stream_rate']}"
        elif money_ok or n_amt:
            route = "COVERAGE"
            if not money_ok:
                limits.append("streams only: no approved per-stream publishing rate q - B stays blank")
        else:
            route = "INSUFFICIENT"

        # G outcome
        tol = rule["tolerance"] if rule else ZERO
        v = gap = None
        provisional = False
        outcome, reason = None, None
        if hold is not None:
            outcome, reason = "HOLD", hold[0]
            if reason == "PENDING_DISTRIBUTION":
                outcome = "STATUS_ENQUIRY"
            b = b_stream = None
        elif method in ("RULE_HOLD", "CONFIGURATION_HOLD"):
            outcome, reason = "HOLD", "BASIS"
            hold = ("BASIS", sel["reason"])
        elif route == "INSUFFICIENT":
            outcome, reason = "HOLD", "DATA_GAP"
            hold = ("DATA_GAP", "no recording revenue or valid usage for this work in scope - request data")
        elif p_status in ("PENDING_CYCLE", "MISSING_STATEMENT"):
            outcome = "STATUS_ENQUIRY"
            reason = "PENDING_DISTRIBUTION" if p_status == "PENDING_CYCLE" else "DATA_GAP"
            limits.append("publishing amount is unknown or pending - not an unpaid royalty")
        elif route == "COVERAGE":
            outcome = "COVERAGE_ONLY"
        elif p_status == "NOT_FOUND":
            outcome, provisional = "NO_MATCHING_ENTRY", True
            limits.append("no matching publishing row: any B - 0 illustration is provisional, not an observed zero")
        else:
            v = b - grp["p"]
            gap = max(ZERO, v)
            outcome = "BELOW_COMPARISON" if v > tol else "WITHIN_OR_ABOVE"
        if method == "MRM_BENCHMARK" and b is not None:
            limits.append("6% is an MRM screening assumption (indicative benchmark), not an IPRS tariff or amount due")
        if b_stream is not None:
            limits.append("stream estimate shown separately as a cross-check; never added to the money benchmark")
        if grp["n"] is not None and n_months and len(n_months) < len(run_months):
            limits.append(f"usage counts cover {len(n_months)} of {len(run_months)} months")
        if any(m["allocation"] != ONE for m in grp["masters"].values()):
            limits.append("medley / multi-work allocation applied to recording income")

        question = _question(outcome, reason, hold, comp, plat, terr, pf, pt, r_amt, n_amt, b, grp["p"], v, p_status,
                             method)
        masters = [dict(isrc=k, title=m["title"], r=m["r"], n=m["n"], allocation=m["allocation"])
                   for k, m in sorted(grp["masters"].items())]
        rows_out.append(dict(
            run_id=rid, case_code=code,
            group_key=f"{c['id']}|{comp['work_code']}|{plat}|{terr}|{pf}..{pt}|{use}|{scope}",
            composition_id=cid, work_code=comp["work_code"], title=comp["title"], film=comp["film"],
            composer=comp["composer"], lyricist=comp["lyricist"], isrcs=sorted(grp["masters"]), recordings=masters,
            mapping_status=f"identity v{ctx['iv']['version_no']}" + (" (merged codes: " + ", ".join(
                sorted(grp["p_codes"] - {comp["work_code"]})) + ")" if grp["p_codes"] - {comp["work_code"]} else ""),
            r_amount=r_amt, n_streams=int(n_amt) if n_amt is not None else None,
            n_definition="streams (valid usage rows, platform report)" if n_amt is not None else None,
            p_amount=grp["p"], p_status=p_status,
            currency=(sorted(x for x in cur_r if x) or sorted(x for x in p_currency if x) or [None])[0],
            gates=gates, rule_version_id=rule["id"] if rule else None, method=method, route=route,
            b_amount=b, b_stream=b_stream, variance=v, positive_gap=gap, provisional=provisional, outcome=outcome,
            hold_reason=reason, question=question, limitations="; ".join(dict.fromkeys(limits)) or None,
            evidence=dict(formula=formula, tolerance=tol, r_rows=grp["r_rows"], n_rows=grp["n_rows"][:200],
                          n_rows_total=len(grp["n_rows"]), p_rows=grp["p_rows"], hold_detail=hold[1] if hold else None,
                          rule=dict(id=rule["id"], key=rule["rule_key"], version=rule["version_no"]) if rule else None,
                          rule_reason=sel["reason"])))
    cols = ("run_id", "case_code", "group_key", "composition_id", "work_code", "title", "film", "composer", "lyricist",
            "isrcs", "recordings", "mapping_status", "r_amount", "n_streams", "n_definition", "p_amount", "p_status",
            "currency", "gates", "rule_version_id", "method", "route", "b_amount", "b_stream", "variance",
            "positive_gap", "provisional", "outcome", "hold_reason", "question", "limitations", "evidence")
    rows_out.sort(key=lambda r: (OUTCOMES.index(r["outcome"]), -(r["positive_gap"] or ZERO), -(r["r_amount"] or ZERO),
                                 r["work_code"]))
    db.insert_many(conn, "comparison_group", cols, ([db.J(r[k]) if k in ("gates", "recordings", "evidence") else r[k]
                                                     for k in cols] for r in rows_out))

    # ---- exceptions that are not groups
    for x in p_unregistered:
        exceptions.append(dict(kind="PUBLISHING_NOT_REGISTERED", subject=f"{x['work_code']} {x['title'] or ''}",
                               amount=x["amount"], detail=dict(file_id=x["file_id"], row=x["row_no"]),
                               owner="rights_reviewer", next_action="add the work to the register"))
    held = db.all(conn, "SELECT id, filename, income_type, status, gate, hold_reason, meta FROM source_file WHERE "
                        "client_id = %s AND status IN ('CLASSIFICATION_HOLD', 'DATA_EXCEPTION', 'RECONCILIATION_HOLD', "
                        "'DUPLICATE_REVIEW', 'FILE_EXCEPTION', 'UPLOADED')", (c["id"],))
    for f in held:
        a, b2 = as_date(f["meta"].get("period_from")), as_date(f["meta"].get("period_to"))
        if a and b2 and not (a <= pt and pf <= b2):
            continue
        exceptions.append(dict(kind="FILE_HELD", subject=f"file #{f['id']} {f['filename']}", amount=None,
                               detail=dict(file_id=f["id"], status=f["status"], gate=f["gate"],
                                           reason=f["hold_reason"], income_type=f["income_type"]),
                               owner="importer", next_action=f"clear gate {f['gate'] or 'A2'} - its figures are not "
                                                             f"included in this run"))
    for r in db.all(conn, "SELECT kind, subject_key, title, amount, detail, status FROM identity_issue WHERE "
                          "client_id = %s AND status IN ('OPEN', 'DEFERRED') AND kind <> 'UNMAPPED_RECORDING' ORDER BY "
                          "amount DESC NULLS LAST", (c["id"],)):
        exceptions.append(dict(kind="IDENTITY_" + r["kind"], subject=f"{r['subject_key']} {r['title'] or ''}".strip(),
                               amount=r["amount"], detail=r["detail"], owner="rights_reviewer",
                               next_action="decide on the Identity page"))
    for r in db.all(conn, "SELECT d.id, d.status, d.differences FROM duplicate_candidate d WHERE d.client_id = %s AND "
                          "d.status IN ('PENDING', 'DEFERRED')", (c["id"],)):
        if any(code_to_root.get(w) in groups for w in r["differences"].get("work_codes", [])):
            exceptions.append(dict(kind="DUPLICATE_PENDING_REVIEW", subject=" / ".join(r["differences"]["titles"]),
                                   amount=None, detail=r["differences"], owner="rights_reviewer",
                                   next_action="confirm same entity, keep separate or keep deferred"))
    if others_share:
        exceptions.append(dict(kind="OTHER_BENEFICIARY_LINES", subject=f"{others_share} statement line(s) paid to "
                                                                       f"other parties", amount=None, detail={},
                               owner="accounts", next_action="none - not the client's income"))
    db.insert_many(conn, "run_exception", ("run_id", "kind", "subject", "detail", "amount", "streams", "currency",
                                           "owner", "next_action"),
                   ((rid, e["kind"], e["subject"][:300], db.J(e.get("detail") or {}), e.get("amount"), e.get("streams"),
                     e.get("currency"), e.get("owner"), e.get("next_action")) for e in exceptions))

    # ---- controls (page 10)
    r_in_scope = sum((x["amount"] for x in r_lines), ZERO)
    r_grouped = sum((r["r_amount"] for r in rows_out if r["r_amount"] is not None), ZERO)
    r_unmapped = sum((u["r"] for u in unmapped.values()), ZERO)
    p_in_scope = sum((x["amount"] for x in p_lines), ZERO)
    p_grouped = sum((r["p_amount"] for r in rows_out if r["p_amount"] is not None), ZERO)
    p_unreg = sum((x["amount"] for x in p_unregistered), ZERO)
    p_row_use = defaultdict(int)
    for r in rows_out:
        for pr in r["evidence"]["p_rows"]:
            p_row_use[(pr["file_id"], pr["row"])] += 1
    checks = [
        dict(check="recording income summed once across masters", result="PASS" if abs(r_in_scope - r_grouped -
                                                                                       r_unmapped) < Decimal("0.000001")
             else "FAIL", detail=f"in scope {r_in_scope:,.2f} = grouped {r_grouped:,.2f} + unmapped {r_unmapped:,.2f}"),
        dict(check="publishing amount counted once per composition",
             result="PASS" if all(v == 1 for v in p_row_use.values()) and abs(p_in_scope - p_grouped - p_unreg) <
             Decimal("0.000001") else "FAIL",
             detail=f"in scope {p_in_scope:,.2f} = grouped {p_grouped:,.2f} + unregistered {p_unreg:,.2f}; no "
                    f"statement row used twice"),
        dict(check="publishing statement coverage", result="PASS" if coverage == "FULL" else "HOLD",
             detail={"FULL": "statements cover the whole usage period", "PARTIAL": "statements cover part of the "
                     "period", "PENDING": "no statement - distribution pending", "MISSING": "no statement received"}[
                 coverage]),
        dict(check="rule selection", result="PASS" if sel["method"] in ("EVIDENCED", "MRM_BENCHMARK") else "HOLD",
             detail=(f"{rule['rule_key']} v{rule['version_no']} ({sel['method'].replace('_', ' ').lower()})"
                     if rule else "") + (f" - {sel['reason']}" if sel["reason"] else "")),
    ]
    summary = _summary(rows_out, scope)
    summary.update(groups=len(rows_out), coverage=coverage, statements=statements,
                   r_in_scope=r_in_scope, r_grouped=r_grouped, r_unmapped=r_unmapped, p_in_scope=p_in_scope,
                   p_grouped=p_grouped, p_unregistered=p_unreg, n_in_scope=sum((x["streams"] for x in n_lines)),
                   r_months=[m.isoformat() for m in r_months], n_months=[m.isoformat() for m in n_months],
                   method=sel["method"], rule=dict(id=rule["id"], key=rule["rule_key"], version=rule["version_no"],
                                                   rate=rule["rate"], tolerance=rule["tolerance"]) if rule else None,
                   rule_reason=sel["reason"], exceptions=len(exceptions),
                   identity_version=ctx["iv"]["version_no"],
                   inputs=dict(recording_files=[f["id"] for f in rec_files], usage_files=[f["id"] for f in use_files],
                               publishing_files=[f["id"] for f in pub_files]),
                   works_input=len({x["work_code"] for x in p_lines}) + len(unmapped),
                   works_eligible=sum(1 for r in rows_out if r["outcome"] in ("BELOW_COMPARISON", "WITHIN_OR_ABOVE")))
    file_ids = sorted({f["id"] for f in rec_files + use_files + pub_files})
    return dict(summary=summary, checks=checks, file_ids=file_ids, rule_ids=rule_ids)


def _line_use(x: dict) -> str | None:
    return use_type_of(None, x.get("platform"), x.get("content_type"))


def _add_months(d: dt.date, n: int) -> dt.date:
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return month_end(y, m)


def _summary(rows: list[dict], scope: str) -> dict:
    """Summary control: per currency and right; only comparable groups are added; positive gaps and amounts above
    benchmark are separate (one work never conceals another's gap)."""
    by: dict[str, dict] = {}
    outcomes = defaultdict(int)
    holds = defaultdict(lambda: dict(groups=0, r=ZERO))
    for r in rows:
        outcomes[r["outcome"]] += 1
        if r["outcome"] in ("HOLD", "STATUS_ENQUIRY"):
            h = holds[r["hold_reason"] or "OTHER"]
            h["groups"] += 1
            h["r"] += r["r_amount"] or ZERO
        key = f"{r['currency'] or 'n/a'}|{scope}"
        t = by.setdefault(key, dict(currency=r["currency"], right_scope=scope, comparable_groups=0, r=ZERO, b=ZERO,
                                    p=ZERO, positive_gaps=ZERO, above_benchmark=ZERO, below_groups=0,
                                    within_groups=0, provisional_groups=0, provisional_b=ZERO, coverage_only=0,
                                    coverage_r=ZERO, coverage_n=0))
        if r["outcome"] in ("BELOW_COMPARISON", "WITHIN_OR_ABOVE"):
            t["comparable_groups"] += 1
            t["r"] += r["r_amount"] or ZERO
            t["b"] += r["b_amount"] or ZERO
            t["p"] += r["p_amount"] or ZERO
            if r["variance"] is not None and r["variance"] > 0:
                t["positive_gaps"] += r["variance"]
            if r["variance"] is not None and r["variance"] < 0:
                t["above_benchmark"] += -r["variance"]
            t["below_groups" if r["outcome"] == "BELOW_COMPARISON" else "within_groups"] += 1
        elif r["outcome"] == "NO_MATCHING_ENTRY":
            t["provisional_groups"] += 1
            t["provisional_b"] += r["b_amount"] or ZERO
        elif r["outcome"] == "COVERAGE_ONLY":
            t["coverage_only"] += 1
            t["coverage_r"] += r["r_amount"] or ZERO
            t["coverage_n"] += r["n_streams"] or 0
    return dict(by_currency=list(by.values()), outcomes=dict(outcomes), holds=dict(holds))


def _question(outcome, reason, hold, comp, plat, terr, pf, pt, r, n, b, p, v, p_status, method) -> str:
    what = f"'{comp['title']}' (work {comp['work_code']}) on {plat}, {terr}, {period_label(pf, pt)}"
    bl, vl = rules.LABELS.get(method, ("comparison amount", "difference"))
    if outcome == "BELOW_COMPARISON":
        return (f"For {what}, recording revenue was {q2(r):,.2f}; the {bl} is {q2(b):,.2f} and the publishing "
                f"statement shows {q2(p):,.2f} - a {vl} of {q2(v):,.2f}. Please confirm the calculation basis, the "
                f"beneficiary share and whether further distribution is pending.")
    if outcome == "NO_MATCHING_ENTRY":
        base = f"recording revenue was {q2(r):,.2f}" if r else f"{int(n or 0):,} streams were reported"
        return (f"For {what}, {base} but no entry was found in the statements reviewed. Please locate the usage and "
                f"payment, or confirm the registration and distribution status." +
                (f" (Provisional {bl}: {q2(b):,.2f}.)" if b is not None else ""))
    if outcome == "COVERAGE_ONLY":
        parts = []
        if r is not None:
            parts.append(f"recording revenue {q2(r):,.2f}")
        if n is not None:
            parts.append(f"{int(n):,} streams")
        found = f"the statement shows {q2(p):,.2f}" if p is not None else "no publishing entry was found"
        return (f"For {what}, {' and '.join(parts)} were reported and {found}. No monetary benchmark applies; please "
                f"verify the usage, its allocation and distribution status.")
    if outcome == "STATUS_ENQUIRY":
        why = P_STATUS_LABEL.get(p_status, "") if reason != "PENDING_DISTRIBUTION" or not hold else hold[1]
        return f"For {what}: {why}. Please confirm the distribution status and expected distribution period."
    if outcome == "HOLD":
        return f"Internal hold ({(reason or '').replace('_', ' ').lower()}): {hold[1] if hold else ''}"
    return f"For {what}, the publishing amount is within or above the {bl}; no clarification requested."
