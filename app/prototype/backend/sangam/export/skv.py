"""The SKV master workbook writer (architecture §10, §19) - the band plan comes from the build
layout (i.e. from the database), never from a constant."""
from __future__ import annotations

from ..build.engine import build_summary, load_rows
from ..build.model import BASIS
from ..domain.normalize import JOIN, fy_label
from . import style as S
from .writer import Band, Col, as_date, new_workbook, note, save_deterministic, write_bands


def skv_bands(layout: dict, client: str) -> tuple[list[Band], dict]:
    bands = [Band(None, S.IDENTITY[0], None, [
        Col("ISRC", S.WIDTHS["isrc"], "text", lambda r: JOIN.join(r.ordered_isrcs())),
        Col("Song Name", S.WIDTHS["name"], "text", lambda r: r.name),
        Col("Internal No", S.WIDTHS["internal"], "text", lambda r: JOIN.join(r.ordered_works()) or None),
        Col("Total Amount", S.WIDTHS["total"], "money", lambda r: r.total_amount, bold=True, total=True),
        Col(f"Total {client} Revenue (MRM)", S.WIDTHS["total_mrm"], "money", lambda r: r.total_mrm, bold=True,
            total=True),
    ])]
    total_extra = {}
    col = 6
    for sec in layout["sections"]:
        cols = []
        if sec["kind"] == "statement":
            for st in sec["statements"]:
                sid = st["id"]
                cols += [
                    Col("Date", S.WIDTHS["date"], "date",
                        lambda r, sid=sid, d=as_date(st["date"]): d if sid in r.amounts else None),
                    Col("Amount", S.WIDTHS["amount"], "money",
                        lambda r, sid=sid: r.amounts.get(sid), total=True),
                    Col("Period", 26, "text", lambda r, sid=sid, p=st["period"]: p if sid in r.amounts else None),
                    Col("Distribution Number", 15, "text",
                        lambda r, sid=sid, d=st["dist_no"]: d if sid in r.amounts else None),
                ]
                total_extra[col + 3] = st["dist_no"]
                col += 4
        else:
            for m in sec["months"]:
                mk = m["month"]
                cols += [
                    Col("Date", S.WIDTHS["date"], "date", lambda r, mk=mk, d=as_date(m["date"]): d if mk in r.mrm else None),
                    Col("Amount", S.WIDTHS["amount"], "money", lambda r, mk=mk: r.mrm.get(mk), total=True),
                    Col("Period", 13, "text", lambda r, mk=mk, p=m["label"]: p if mk in r.mrm else None),
                    Col("Distribution Number", 24, "text", lambda r, mk=mk, d=m["dist"]: d if mk in r.mrm else None),
                ]
                total_extra[col + 2] = m["label"]
                col += 4
        bands.append(Band(sec["title"], sec["band"], sec["tint"], cols))
    bands.append(Band(None, None, None, [Col("", 3, "text", lambda r: None) for _ in range(3)]))   # SKV spacers
    fy_cols = [Col(fy_label(k), 16, "money", lambda r, k=k: r.fy.get(k, 0.0), total=True) for k in layout["fy_keys"]]
    fy_cols.append(Col("Total Revenue", 16, "money", lambda r: r.total_amount, bold=True, total=True))
    bands.append(Band("TOTAL REVENUE  (by Indian Financial Year, 1 Apr - 31 Mar, of the period the royalty was "
                      "earned in)", S.TOTAL_REVENUE["band"], S.TOTAL_REVENUE["tint"], fy_cols,
                      header_fills=[S.TOTAL_REVENUE["header"]] * len(layout["fy_keys"]) + [S.TOTAL_REVENUE["band"]]))
    bands.append(Band("AUDIT / TRACEABILITY", S.AUDIT[0], S.AUDIT[1], [
        Col("Catalogue Status", 60, "text", lambda r: " ; ".join([r.status] + r.notes)),
        Col("Royalty Booked On", 48, "text", lambda r: r.booked_note),
        Col(f"{client} (MRM) Match Basis", 48, "text", lambda r: " ; ".join(BASIS[b] for b in r.basis) or None),
    ]))
    return bands, total_extra


def generation_note(b: dict) -> str:
    L, st = b["layout"], b["stats"]
    cat = L["cat_label"]
    text = (f"{b['label']} - one row for every recording in the catalogue ({cat}), plus every work a royalty "
            f"statement paid that the catalogue does not list, plus every ISRC only {L['client']}'s revenue or "
            f"usage report knows: {L['row_count']:,} rows over {L['statement_count']} statements.  Royalty is booked "
            f"once per IPRS WORK INT NO (siblings of a work paid on another row carry 0.00 and say where the money "
            f"is); {L['client']}'s gross revenue is matched ISRC-first, and wherever a song name decided the match "
            f"the ISRC is written into column A and the basis into the last column.  Col D (royalty distributed) "
            f"= {L['total_amount']:,.2f} and col E (gross revenue {L['client']} reports) = {L['total_mrm']:,.2f} are "
            f"different kinds of money and must never be added together.  Every total ties back to the source "
            f"files' own printed totals; every rounded total equals the sum of its rounded parts.")
    if b.get("parent_build_id"):
        merges = st.get("merges", [])
        text += (f"  This generation applies {len(merges)} recorded merge decision(s) to the base build: "
                 f"{st.get('merged_away', 0)} row(s) were folded into their survivor (amounts added, identifiers "
                 f"joined registered-first); the Catalogue Status column names each merge so it can be traced or "
                 f"reversed; every column total is unchanged, rupee for rupee.")
    return text


def write_skv(conn, build_id: int, path) -> dict:
    b = build_summary(conn, build_id)
    rows = load_rows(conn, build_id)
    layout = b["layout"]
    wb, ws = new_workbook(b["label"])
    bands, total_extra = skv_bands(layout, layout["client"])
    info = write_bands(ws, bands, rows, total_values=total_extra)
    tr = info["total_row"]
    fy_start = next(s for t, s, e in info["spans"] if t and t.startswith("TOTAL REVENUE"))
    fy_end = next(e for t, s, e in info["spans"] if t and t.startswith("TOTAL REVENUE"))
    note(ws, tr + 1, "Basis: each distribution's amount is placed in the Indian FY (1 Apr - 31 Mar) of the period it "
                     "was earned in; a statement covering more than one FY is split month-weighted. Row total = "
                     "Total Amount (col D).", fy_end, italic=True, start_col=fy_start)
    note(ws, tr + 3, generation_note(b), min(info["ncol"], 30), height=120)
    size, sha = save_deterministic(wb, path)
    return dict(size=size, sha256=sha, rows=len(rows), columns=info["ncol"])
