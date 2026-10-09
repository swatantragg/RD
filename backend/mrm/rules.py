"""E. Rule selection (page 6) - define exactly what 6% means.

A rule version is drafted by one person and approved by another; an approved version never changes (the database
refuses it). A change is a new version that supersedes the old one. Comparison groups record the rule version
they used.

    E2 an EVIDENCED method (society / contract reference) wins inside its covered scope and dates
    E3 otherwise the MRM 6% benchmark, if enabled for the scope -> "indicative benchmark"
       neither -> NO MONETARY BENCHMARK (coverage / status questions only)
    E4 denominator and beneficiary share must be explicit -> else RULE HOLD (never assume 100%)
    E5 scope, dates, owner and approval recorded -> else CONFIGURATION HOLD
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from . import audit, db
from .normalize import ZERO, amount, as_date, s
from .security import not_same_person

FIELDS = ("name", "method", "rate", "denominator", "revenue_basis", "share_treatment", "controlled_share",
          "stream_rate", "stream_rate_basis", "platforms", "territories", "use_types", "currency", "effective_from",
          "effective_to", "evidence_ref", "formula", "tolerance", "owner_id")
LABELS = {"MRM_BENCHMARK": ("indicative benchmark", "difference for clarification"),
          "EVIDENCED": ("expected amount (evidenced method)", "difference")}


class RuleError(Exception):
    pass


def _clean(v: dict) -> dict:
    out = {}
    for k in FIELDS:
        if k not in v:
            continue
        x = v[k]
        if k in ("rate", "controlled_share", "stream_rate", "tolerance"):
            x = amount(x) if s(x) else None
        elif k in ("platforms", "territories", "use_types"):
            x = [s(i) for i in (x or []) if s(i)]
            if k == "territories":
                x = [i.upper() for i in x]
        elif k in ("effective_from", "effective_to"):
            x = as_date(x)
        elif k == "owner_id":
            x = int(x) if s(x) else None
        else:
            x = s(x) or None
        out[k] = x
    if out.get("method") not in (None, "MRM_BENCHMARK", "EVIDENCED"):
        raise RuleError("method is MRM_BENCHMARK or EVIDENCED")
    if out.get("revenue_basis") not in (None, "GROSS", "NET"):
        raise RuleError("revenue basis is GROSS or NET")
    if out.get("share_treatment") not in (None, "BENEFICIARY_SPECIFIC", "WORK_100_TIMES_SHARE"):
        raise RuleError("share treatment is BENEFICIARY_SPECIFIC or WORK_100_TIMES_SHARE")
    if out.get("tolerance") is None and "tolerance" in out:
        out["tolerance"] = ZERO
    return out


def draft(conn, actor: dict, client_id: int | None, rule_key: str, values: dict, reason: str,
          supersedes_id: int | None = None) -> int:
    if not s(reason):
        raise RuleError("give the reason for this rule version")
    v = _clean(values)
    if not v.get("name") or not v.get("method"):
        raise RuleError("a rule needs a name and a method")
    no = (db.scalar(conn, "SELECT max(version_no) FROM rule_version WHERE client_id IS NOT DISTINCT FROM %s AND "
                          "rule_key = %s", (client_id, rule_key)) or 0) + 1
    rid = db.insert(conn, "rule_version", dict(client_id=client_id, rule_key=s(rule_key), version_no=no, status="DRAFT",
                                               reason=reason, supersedes_id=supersedes_id, created_by=actor["id"],
                                               **{k: v.get(k) for k in FIELDS if k in v}))
    audit.record(conn, "rule.drafted", actor, "rule_version", rid, dict(rule_key=rule_key, version_no=no,
                                                                       values=v, reason=reason))
    return rid


def revise(conn, actor: dict, rule_id: int, values: dict, reason: str) -> int:
    """A change to an approved rule is a new DRAFT version (the approved one stays until the new one is approved)."""
    r = db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (rule_id,))
    if not r:
        raise RuleError("unknown rule")
    if r["status"] == "DRAFT":
        v = _clean(values)
        db.update(conn, "rule_version", rule_id, dict(v, reason=reason or r["reason"]))
        audit.record(conn, "rule.draft_edited", actor, "rule_version", rule_id, dict(values=v))
        return rule_id
    base = {k: r[k] for k in FIELDS}
    base.update(values)
    return draft(conn, actor, r["client_id"], r["rule_key"], base, reason, supersedes_id=rule_id)


def approve(conn, actor: dict, rule_id: int) -> dict:
    r = db.one(conn, "SELECT * FROM rule_version WHERE id = %s FOR UPDATE", (rule_id,))
    if not r or r["status"] != "DRAFT":
        raise RuleError("only a draft rule can be approved")
    not_same_person(actor, r["created_by"], "a rule version")
    problems = completeness(r)
    if problems:
        raise RuleError("configuration hold - " + "; ".join(problems))
    prev = db.all(conn, "SELECT id, effective_from FROM rule_version WHERE client_id IS NOT DISTINCT FROM %s AND "
                        "rule_key = %s AND status = 'APPROVED'", (r["client_id"], r["rule_key"]))
    for p in prev:                                   # the superseded version stops the day before the new one starts
        end = (r["effective_from"] - dt.timedelta(days=1)) if r["effective_from"] else None
        conn.execute("UPDATE rule_version SET status = 'RETIRED', effective_to = coalesce(%s, effective_to) "
                     "WHERE id = %s", (end, p["id"]))
    conn.execute("UPDATE rule_version SET status = 'APPROVED', approved_by = %s, approved_at = now() WHERE id = %s",
                 (actor["id"], rule_id))
    audit.record(conn, "rule.approved", actor, "rule_version", rule_id,
                 dict(rule_key=r["rule_key"], version_no=r["version_no"], retired=[p["id"] for p in prev]))
    return db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (rule_id,))


def retire(conn, actor: dict, rule_id: int, reason: str) -> None:
    r = db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (rule_id,))
    if not r or r["status"] != "APPROVED":
        raise RuleError("only an approved rule can be retired")
    if not s(reason):
        raise RuleError("give the reason")
    conn.execute("UPDATE rule_version SET status = 'RETIRED' WHERE id = %s", (rule_id,))
    audit.record(conn, "rule.retired", actor, "rule_version", rule_id, dict(reason=reason))


def delete_draft(conn, actor: dict, rule_id: int) -> None:
    r = db.one(conn, "SELECT * FROM rule_version WHERE id = %s", (rule_id,))
    if not r or r["status"] != "DRAFT":
        raise RuleError("only a draft can be discarded")
    conn.execute("DELETE FROM rule_version WHERE id = %s", (rule_id,))
    audit.record(conn, "rule.draft_discarded", actor, "rule_version", rule_id, dict(rule_key=r["rule_key"]))


def completeness(r: dict) -> list[str]:
    """E4 + E5: what is missing before the rule may be applied."""
    out = []
    if r["method"] == "MRM_BENCHMARK" or r["method"] == "EVIDENCED":
        if r["rate"] is None and r["stream_rate"] is None:
            out.append("no rate (k) or approved per-stream rate (q)")
        if r["rate"] is not None:
            if not r["denominator"]:
                out.append("state what revenue the rate applies to (denominator)")
            if not r["revenue_basis"]:
                out.append("state gross or net revenue")
            if not r["share_treatment"]:
                out.append("state whose publishing share it predicts (share treatment)")
            if r["share_treatment"] == "WORK_100_TIMES_SHARE" and r["controlled_share"] is None:
                out.append("100%-of-work rule needs the evidenced controlled share s - never assume 100%")
        if r["stream_rate"] is not None and not r["stream_rate_basis"]:
            out.append("state the basis of the per-stream publishing rate q (platform, period, beneficiary)")
    if r["method"] == "EVIDENCED" and not r["evidence_ref"]:
        out.append("an evidenced method needs its society / contract reference")
    if not r["effective_from"]:
        out.append("effective-from date")
    if not r["currency"]:
        out.append("currency")
    if not r["owner_id"]:
        out.append("rule owner")
    return out


def _covers(rule: dict, platform: str, territory: str, use_type: str, pf: dt.date, pt: dt.date) -> bool:
    if rule["platforms"] and platform not in rule["platforms"]:
        return False
    if rule["territories"] and territory not in rule["territories"]:
        return False
    if rule["use_types"] and use_type not in rule["use_types"]:
        return False
    if rule["effective_from"] and rule["effective_from"] > pt:
        return False
    if rule["effective_to"] and rule["effective_to"] < pf:
        return False
    return True


def select(conn, client_id: int, platform: str, territory: str, use_type: str, pf: dt.date, pt: dt.date) -> dict:
    """-> {method, rule, status, reason}: EVIDENCED | MRM_BENCHMARK | NO_BENCHMARK | RULE_HOLD | CONFIGURATION_HOLD."""
    rules = db.all(conn, "SELECT * FROM rule_version r WHERE approved_by IS NOT NULL AND (client_id = %s OR client_id "
                         "IS NULL) AND (status = 'APPROVED' OR (status = 'RETIRED' AND effective_to IS NOT NULL AND "
                         "EXISTS (SELECT 1 FROM rule_version n WHERE n.supersedes_id = r.id AND n.status = 'APPROVED'))) "
                         "ORDER BY client_id NULLS LAST, id", (client_id,))
    for method in ("EVIDENCED", "MRM_BENCHMARK"):
        scoped = [r for r in rules if r["method"] == method and _covers(r, platform, territory, use_type, pf, pt)]
        if not scoped:
            continue
        own = [r for r in scoped if r["client_id"] is not None] or scoped
        if len(own) > 1:
            names = ", ".join(f"{r['rule_key']} v{r['version_no']}" for r in own)
            return dict(method="RULE_HOLD", rule=None, reason=f"more than one {method.lower()} rule version applies "
                                                              f"to this scope and period ({names}) - split the "
                                                              f"period or retire one")
        r = own[0]
        if (r["effective_from"] and r["effective_from"] > pf) or (r["effective_to"] and r["effective_to"] < pt):
            return dict(method="CONFIGURATION_HOLD", rule=r,
                        reason=f"{r['rule_key']} v{r['version_no']} covers only part of the usage period")
        problems = completeness(r)
        if problems:
            kind = "RULE_HOLD" if any("denominator" in p or "share" in p or "gross" in p for p in problems) \
                else "CONFIGURATION_HOLD"
            return dict(method=kind, rule=r, reason="; ".join(problems))
        return dict(method=method, rule=r, reason=None)
    return dict(method="NO_BENCHMARK", rule=None, reason="no evidenced method and the MRM benchmark is not enabled for "
                                                         "this platform / territory / use type / period")


def benchmark_amount(rule: dict, r_amount: Decimal) -> tuple[Decimal, str]:
    """F: B = R x k (beneficiary-specific) or R x k x s (rule written for 100% of the work). s is never applied twice."""
    k = rule["rate"]
    kt = format(k.normalize(), "f")
    if rule["share_treatment"] == "WORK_100_TIMES_SHARE":
        st = format(rule["controlled_share"].normalize(), "f")
        return r_amount * k * rule["controlled_share"], f"B = R x k x s = {r_amount:,.2f} x {kt} x {st}"
    return r_amount * k, f"B = R x k = {r_amount:,.2f} x {kt}"
