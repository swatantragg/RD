"""Legacy comparison module (flowchart D-H): people, clients, dashboard, audit. Mounted under /api/compare only
when LEGACY_COMPARISON is enabled. Sign-in lives in routes_auth."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Body, Depends

from .. import audit, config, db, identity, security
from ..compare import HOLD_REASONS, OUTCOME_LABEL, P_STATUS_LABEL
from ..normalize import as_date, s
from ..parsing.detect import META_FIELDS, REQUIRED_META
from ..parsing.scope import PLATFORMS, RIGHT_SCOPES, USE_TYPES
from .deps import J, actor, need

router = APIRouter()


@router.get("/meta")
def meta(_: dict = Depends(actor)):
    return J(dict(roles=security.ROLE_LABELS, outcomes=OUTCOME_LABEL, hold_reasons=HOLD_REASONS,
                  p_status=P_STATUS_LABEL, use_types=USE_TYPES, right_scopes=RIGHT_SCOPES,
                  platforms=sorted({p for _, p in PLATFORMS}), meta_fields=META_FIELDS, required_meta=REQUIRED_META,
                  demo=config.settings.demo_enabled))


# ------------------------------------------------------------------ clients
CLIENT_FIELDS = ("code", "name", "kind", "society", "member_id", "beneficiary_name", "mandate_verified", "mandate_ref",
                 "mandate_from", "mandate_to", "territories", "controlled_share", "collection_route", "contact_email",
                 "notes")


def _client_values(body: dict) -> dict:
    v = {k: body[k] for k in CLIENT_FIELDS if k in body}
    for k in ("mandate_from", "mandate_to"):
        if k in v:
            v[k] = as_date(v[k])
    if "territories" in v:
        v["territories"] = [s(t).upper() for t in (v["territories"] or []) if s(t)]
    if "controlled_share" in v:
        v["controlled_share"] = s(v["controlled_share"]) or None
    for k in ("member_id", "beneficiary_name", "mandate_ref", "contact_email", "notes"):
        if k in v:
            v[k] = s(v[k]) or None
    return v


@router.get("/clients")
def clients(_: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT c.*, (SELECT count(*) FROM source_file f WHERE f.client_id = c.id) AS files, "
                              "(SELECT count(*) FROM enquiry_case e WHERE e.client_id = c.id AND e.status NOT LIKE "
                              "'CLOSED%%') AS open_cases FROM client c ORDER BY c.name"))


@router.post("/clients")
def create_client(body: dict = Body(...), a: dict = Depends(need("clients"))):
    v = _client_values(body)
    if not s(v.get("code")) or not s(v.get("name")):
        raise ValueError("a client needs a short code and a name")
    v["code"] = s(v["code"]).upper()
    v.setdefault("kind", "PUBLISHER")
    with db.tx() as conn:
        cid = db.insert(conn, "client", v)
        audit.record(conn, "client.created", a, "client", cid, v)
        return J(db.one(conn, "SELECT * FROM client WHERE id = %s", (cid,)))


@router.patch("/clients/{cid}")
def update_client(cid: int, body: dict = Body(...), a: dict = Depends(need("clients"))):
    v = _client_values(body)
    v.pop("code", None)
    with db.tx() as conn:
        before = db.one(conn, "SELECT * FROM client WHERE id = %s", (cid,))
        db.update(conn, "client", cid, v)
        audit.record(conn, "client.updated", a, "client", cid,
                     {k: dict(before=before.get(k), after=x) for k, x in v.items() if before.get(k) != x})
        return J(db.one(conn, "SELECT * FROM client WHERE id = %s", (cid,)))


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard/{cid}")
def dashboard(cid: int, _: dict = Depends(actor)):
    with db.tx() as conn:
        files = db.all(conn, "SELECT status, income_type, count(*) AS n FROM source_file WHERE client_id = %s GROUP BY "
                             "1, 2", (cid,))
        run = db.one(conn, "SELECT id, version_no, platform, territory, use_type, right_scope, period_from, period_to, "
                           "cutoff, summary, checks, created_at FROM comparison_run WHERE client_id = %s AND status = "
                           "'COMPLETE' ORDER BY id DESC LIMIT 1", (cid,))
        packs = db.all(conn, "SELECT status, count(*) AS n FROM report_pack WHERE client_id = %s GROUP BY 1", (cid,))
        cases = db.all(conn, "SELECT status, payment_status, count(*) AS n FROM enquiry_case WHERE client_id = %s "
                             "GROUP BY 1, 2", (cid,))
        due = db.scalar(conn, "SELECT count(*) FROM enquiry_case WHERE client_id = %s AND follow_up_date <= "
                              "current_date AND status IN ('AWAITING_REPLY', 'OPEN', 'ADJUSTMENT_PROMISED')", (cid,))
        rules_draft = db.scalar(conn, "SELECT count(*) FROM rule_version WHERE status = 'DRAFT' AND (client_id = %s OR "
                                      "client_id IS NULL)", (cid,))
        pack_draft = db.one(conn, "SELECT id, version_no, built_by FROM report_pack WHERE client_id = %s AND status = "
                                  "'DRAFT' ORDER BY id DESC LIMIT 1", (cid,))
        ident = identity.summary(conn, cid)
        recent = audit.recent(conn, 12)
    return J(dict(files=files, run=run, packs=packs, cases=cases, follow_ups_due=due, rules_draft=rules_draft,
                  pack_draft=pack_draft, identity=ident, recent=recent))


# ------------------------------------------------------------------ people
@router.get("/users")
def users(_: dict = Depends(actor)):
    with db.tx() as conn:
        return J(db.all(conn, "SELECT u.id, u.email, u.name, u.active, u.last_login_at, coalesce(array_agg(r.role "
                              "ORDER BY r.role) FILTER (WHERE r.role IS NOT NULL), '{}') AS roles FROM app_user u LEFT "
                              "JOIN user_role r ON r.user_id = u.id GROUP BY u.id ORDER BY u.name"))


@router.post("/users")
def create_user(body: dict = Body(...), a: dict = Depends(need("users"))):
    from ..seed import create_user as mk
    roles = [r for r in body.get("roles") or [] if r in security.ROLES]
    if not s(body.get("email")) or not s(body.get("name")) or not roles:
        raise ValueError("a person needs an email, a name and at least one role")
    with db.tx() as conn:
        uid = mk(conn, s(body["email"]), s(body["name"]), roles, body.get("password") or "")
        audit.record(conn, "user.created", a, "app_user", uid, dict(email=body["email"], roles=roles))
    return J({"id": uid})


@router.patch("/users/{uid}")
def update_user(uid: int, body: dict = Body(...), a: dict = Depends(need("users"))):
    with db.tx() as conn:
        if "roles" in body:
            roles = [r for r in body["roles"] if r in security.ROLES]
            if uid == a["id"] and "admin" not in roles:
                raise ValueError("you cannot remove your own administrator role")
            conn.execute("DELETE FROM user_role WHERE user_id = %s", (uid,))
            for r in roles:
                conn.execute("INSERT INTO user_role (user_id, role) VALUES (%s, %s)", (uid, r))
        if "active" in body:
            if uid == a["id"] and not body["active"]:
                raise ValueError("you cannot deactivate yourself")
            conn.execute("UPDATE app_user SET active = %s WHERE id = %s", (bool(body["active"]), uid))
            if not body["active"]:
                conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                             (uid,))
        if s(body.get("password")):
            conn.execute("UPDATE app_user SET password_hash = %s WHERE id = %s",
                         (security.hash_password(body["password"]), uid))
        audit.record(conn, "user.updated", a, "app_user", uid,
                     {k: v for k, v in body.items() if k != "password"} | ({"password": "changed"}
                                                                           if body.get("password") else {}))
    return J({"ok": True})


# ------------------------------------------------------------------ audit
@router.get("/audit")
def audit_log(before: int | None = None, kind: str | None = None, a: dict = Depends(need("audit"))):
    with db.tx() as conn:
        return J(audit.recent(conn, 200, before, kind or None))


@router.get("/audit/verify")
def audit_verify(a: dict = Depends(need("audit"))):
    with db.tx() as conn:
        r = audit.verify_chain(conn)
        audit.record(conn, "audit.verified", a, None, None, r)
    return J(dict(r, checked_at=dt.datetime.now(dt.timezone.utc)))
