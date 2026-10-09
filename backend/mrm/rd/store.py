"""Parsed files <-> database rows. Source lines are stored once and never changed (database triggers refuse it)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from .. import db
from .model import (PLATFORM_REVENUE, PLATFORM_USAGE, PREVIOUS_OUTPUT, REVIEW_LIST, SONG_LIST, STATEMENT, PlatformData,
                    PlatformLine, PriorColumn, PriorOutputData, PriorRow, RoyaltyLine, SongEntry, SongListData,
                    StatementData)


def _d(v):
    return None if v is None else format(v, "f")


def save_data(conn, file_id: int, client_id: int, kind: str, data) -> int:
    if kind == STATEMENT:
        d: StatementData = data
        return db.insert_many(conn, "rd_royalty_line", (
            "file_id", "client_id", "line_no", "row_no", "work_no", "raw_work", "title", "language", "party", "role",
            "own_pct", "coll_pct", "pool", "source", "usage", "amount"),
            ((file_id, client_id, x.line_no, x.row_no, x.work_no, x.raw_work, x.title, x.language, x.party, x.role,
              x.own_pct, x.coll_pct, x.pool, x.source, {k: _d(v) for k, v in x.usage.items()} if x.usage else None,
              x.amount) for x in d.lines))
    if kind in (PLATFORM_REVENUE, PLATFORM_USAGE):
        p: PlatformData = data
        return db.insert_many(conn, "rd_platform_line", (
            "file_id", "client_id", "line_no", "row_no", "month", "isrc", "title", "album", "upc", "amount", "plays"),
            ((file_id, client_id, x.line_no, x.row_no, x.month, x.isrc, x.title, x.album, x.upc, x.amount, x.plays)
             for x in p.lines))
    if kind in (SONG_LIST, REVIEW_LIST):
        s: SongListData = data
        return db.insert_many(conn, "rd_song_entry", (
            "file_id", "client_id", "entry_no", "row_no", "title", "work_nos", "isrcs", "other_codes", "status_text",
            "note"), ((file_id, client_id, e.entry_no, e.row_no, e.title, e.work_nos, e.isrcs, e.other_codes,
                       e.status_text or None, e.note or None) for e in s.entries))
    if kind == PREVIOUS_OUTPUT:
        db.insert(conn, "rd_prior", dict(file_id=file_id, client_id=client_id, data=prior_to_json(data)),
                  returning=None)
        return len(data.rows)
    return 0


def prior_to_json(p: PriorOutputData) -> dict:
    return dict(sheet=p.sheet, generation=p.generation, native=p.native, grand_total=_d(p.grand_total),
                platform_grand={k: _d(v) for k, v in p.platform_grand.items()}, integrity=p.integrity, meta=p.meta,
                columns=[dict(index=c.index, band=c.band, kind=c.kind, section=c.section, dist_no=c.dist_no,
                              period_label=c.period_label, date=c.date.isoformat() if c.date else None,
                              total=_d(c.total), platform=c.platform, distributor=c.distributor,
                              month=c.month.isoformat() if c.month else None) for c in p.columns],
                rows=[dict(row_no=r.row_no, isrcs=r.isrcs, title=r.title, work_nos=r.work_nos, total=_d(r.total),
                           platform_totals={k: _d(v) for k, v in r.platform_totals.items()},
                           cells={str(k): _d(v) for k, v in r.cells.items()}, status_text=r.status_text,
                           booked_on=r.booked_on, basis=r.basis) for r in p.rows])


def prior_from_json(j: dict) -> PriorOutputData:
    D = lambda v: None if v is None else Decimal(v)                   # noqa: E731
    date = lambda v: dt.date.fromisoformat(v) if v else None          # noqa: E731
    return PriorOutputData(
        sheet=j["sheet"], generation=j["generation"], native=j["native"], grand_total=D(j["grand_total"]),
        platform_grand={k: D(v) for k, v in j["platform_grand"].items()}, integrity=j["integrity"], meta=j.get("meta"),
        columns=[PriorColumn(index=c["index"], band=c["band"], kind=c["kind"], section=c["section"],
                             dist_no=c["dist_no"], period_label=c["period_label"], date=date(c["date"]),
                             total=D(c["total"]), platform=c["platform"], distributor=c["distributor"],
                             month=date(c["month"])) for c in j["columns"]],
        rows=[PriorRow(row_no=r["row_no"], isrcs=r["isrcs"], title=r["title"], work_nos=r["work_nos"],
                       total=D(r["total"]), platform_totals={k: D(v) for k, v in r["platform_totals"].items()},
                       cells={int(k): D(v) for k, v in r["cells"].items()}, status_text=r["status_text"],
                       booked_on=r["booked_on"], basis=r["basis"]) for r in j["rows"]])


def load_data(conn, file_id: int, kind: str, facts: dict):
    if kind == STATEMENT:
        rows = db.all(conn, "SELECT * FROM rd_royalty_line WHERE file_id = %s ORDER BY line_no", (file_id,))
        lines = [RoyaltyLine(line_no=r["line_no"], row_no=r["row_no"], work_no=r["work_no"], raw_work=r["raw_work"] or "",
                             title=r["title"] or "", amount=r["amount"], party=r["party"] or "", role=r["role"] or "",
                             language=r["language"] or "", own_pct=r["own_pct"], coll_pct=r["coll_pct"],
                             pool=r["pool"] or "", source=r["source"] or "", usage=r["usage"]) for r in rows]
        return StatementData(layout=facts.get("layout", ""), sheet=facts.get("sheet", ""), header_row=0,
                             holder_member=facts.get("holder_member"), holder_name=facts.get("holder_name"),
                             ipi_name_no=facts.get("ipi_name_no"), ipi_base_no=facts.get("ipi_base_no"), lines=lines,
                             printed_total=Decimal(facts["printed_total"]) if facts.get("printed_total") else None,
                             lines_total=Decimal(facts.get("lines_total") or "0"),
                             subtotal_total=Decimal(facts.get("subtotal_total") or "0"), footers=[],
                             blank_amount_rows=[], pool_sources=facts.get("pool_sources") or [])
    if kind in (PLATFORM_REVENUE, PLATFORM_USAGE):
        rows = db.all(conn, "SELECT * FROM rd_platform_line WHERE file_id = %s ORDER BY line_no", (file_id,))
        return PlatformData(kind=kind, sheet=facts.get("sheet", ""), header_row=0, mapping={}, lines=[
            PlatformLine(line_no=r["line_no"], row_no=r["row_no"], month=r["month"], isrc=r["isrc"] or "",
                         title=r["title"] or "", album=r["album"] or "", upc=r["upc"] or "", amount=r["amount"],
                         plays=r["plays"]) for r in rows], platform_values=[], currency_values=[], basis_hint=None)
    if kind in (SONG_LIST, REVIEW_LIST):
        rows = db.all(conn, "SELECT * FROM rd_song_entry WHERE file_id = %s ORDER BY entry_no", (file_id,))
        return SongListData(kind=kind, sheet=facts.get("sheet", ""), header_row=0, mapping={}, entries=[
            SongEntry(entry_no=r["entry_no"], row_no=r["row_no"], title=r["title"] or "", work_nos=list(r["work_nos"]),
                      isrcs=list(r["isrcs"]), other_codes=list(r["other_codes"]), status_text=r["status_text"] or "",
                      note=r["note"] or "") for r in rows])
    if kind == PREVIOUS_OUTPUT:
        j = db.scalar(conn, "SELECT data FROM rd_prior WHERE file_id = %s", (file_id,))
        return prior_from_json(j)
    return None
