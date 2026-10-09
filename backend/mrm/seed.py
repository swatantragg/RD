"""The first client (SVF) and its configuration. No demonstration people or data."""
from __future__ import annotations

from . import audit, db, security

# Demo accounts created by earlier versions (shared, published password). They are switched off on every bootstrap.
RETIRED_DEMO = ("admin@mrm.local", "swatantra@mrm.local", "devi@mrm.local", "accounts@mrm.local", "sherley@mrm.local",
                "viewer@mrm.local")


def create_user(conn, email: str, name: str, roles: list[str], password: str) -> int:
    uid = db.scalar(conn, "SELECT id FROM app_user WHERE email = %s", (email.lower(),))
    if uid is None:
        uid = db.insert(conn, "app_user", dict(email=email.lower(), name=name,
                                               password_hash=security.hash_password(password)))
    for r in roles:
        conn.execute("INSERT INTO user_role (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING", (uid, r))
    return uid


def seed(echo=print) -> None:
    """Real data only: the first client (SVF) and its configuration. People create their own accounts (the first one
    becomes the administrator) or are created with `python -m mrm.cli create-user`."""
    with db.tx() as conn:
        if not db.scalar(conn, "SELECT id FROM client WHERE code = 'SVF'"):
            cid = db.insert(conn, "client", dict(
                code="SVF", name="SVF Entertainment Private Limited", kind="PUBLISHER_AND_LABEL", society="IPRS",
                member_id="5154290", beneficiary_name="SVF ENTERTAINMENT PRIVATE LIMITED", mandate_verified=False,
                territories=["IN"], collection_route="IPRS", contact_email=None,
                notes="Publisher and label; IPRS member 5154290 (IPI 00871526032)."))
            audit.record(conn, "client.created", None, "client", cid, dict(code="SVF"))
        setup_svf(conn)
        retired = retire_demo_accounts(conn)
    echo("  client SVF ready" + (f"; {retired} demo account(s) switched off" if retired else ""))


def retire_demo_accounts(conn) -> int:
    rows = db.all(conn, "UPDATE app_user SET active = FALSE WHERE email = ANY(%s) AND active RETURNING id, email",
                  (list(RETIRED_DEMO),))
    for r in rows:
        conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (r["id"],))
        audit.record(conn, "user.demo_retired", None, "app_user", r["id"], dict(email=r["email"]))
    return len(rows)


SVF_SETTINGS = {"output_prefix": "SVF-RD-SKV", "next_generation": 9, "song_list_name": "SVF list",
                "distributors": [{"name": "MRM", "currency": "INR", "basis": "GROSS", "platforms": ["Spotify"]}]}


def setup_svf(conn) -> None:
    """The first client's configuration (Architecture V3 §4; business decisions of 9 Oct 2026: the MRM Spotify report
    is INR gross revenue, and statements of other members - e.g. 8875288 - are not SVF's)."""
    from .rd import access
    c = db.one(conn, "SELECT id, settings FROM client WHERE code = 'SVF'")
    if not c:
        return
    access.set_scope(conn, [c["id"]])
    if not c["settings"]:
        db.update(conn, "client", c["id"], dict(settings=SVF_SETTINGS))
    conn.execute("INSERT INTO client_holder (client_id, society, member_no, name, ipi_name_no, ipi_base_no) VALUES "
                 "(%s, 'IPRS', '5154290', 'SVF ENTERTAINMENT PRIVATE LIMITED', '00871526032', 'I-004791736-0') "
                 "ON CONFLICT DO NOTHING", (c["id"],))
