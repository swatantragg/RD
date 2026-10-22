"""The first client (SVF) and its configuration. Nothing else: no people, runs, files or reports."""
from __future__ import annotations

from . import audit, db, security


def create_user(conn, email: str, name: str, role: str, password: str, created_by: int | None = None,
                must_change_password: bool = False) -> int:
    """A new account with one of the three roles. The database refuses a second Super Admin (super_admin_guard)."""
    if role not in security.ROLES:
        raise ValueError(f"unknown role {role!r} - use one of {', '.join(security.ROLES)}")
    if db.scalar(conn, "SELECT id FROM app_user WHERE email = %s", (email.lower(),)):
        raise ValueError(f"an account with the email {email.lower()} already exists")
    return db.insert(conn, "app_user", dict(email=email.lower(), name=name, role=role, created_by=created_by,
                                            must_change_password=must_change_password,
                                            password_hash=security.hash_password(password)))


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
    echo("  client SVF ready")


SVF_SETTINGS = {"output_prefix": "SVF-RD-SKV", "next_generation": 9, "song_list_name": "SVF list",
                "distributors": [{"name": "MRM", "currency": "INR", "basis": "GROSS", "platforms": ["Spotify"]}],
                "iprs_currency": "INR"}
SVF_BENCHMARK = "4"            # the approved reference benchmark for the SVF proof of concept (per cent)


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
    elif "iprs_currency" not in c["settings"]:
        # IPRS statements do not print a currency; IPRS distributes to SVF in rupees (a client setting, shown as such)
        db.update(conn, "client", c["id"], dict(settings={**c["settings"], "iprs_currency": "INR"}))
    if not db.scalar(conn, "SELECT id FROM reconciliation_settings WHERE client_id = %s", (c["id"],)):
        db.insert(conn, "reconciliation_settings", dict(
            client_id=c["id"], platform_id=None, benchmark_percentage=SVF_BENCHMARK, client_interest_pct=None,
            revenue_basis="GROSS", note="Approved reference benchmark for the SVF proof of concept. The client "
                                        "interest is not established yet: set it before benchmarks are calculated."))
    conn.execute("INSERT INTO client_holder (client_id, society, member_no, name, ipi_name_no, ipi_base_no) VALUES "
                 "(%s, 'IPRS', '5154290', 'SVF ENTERTAINMENT PRIVATE LIMITED', '00871526032', 'I-004791736-0') "
                 "ON CONFLICT DO NOTHING", (c["id"],))
