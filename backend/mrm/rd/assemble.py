"""Parsed files + their confirmed metadata -> engine inputs. Shared by the service (data from the database) and by
tests and command-line runs (data straight from files)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from . import names
from .engine import ReviewMark, SrcList, SrcPlatform, SrcPrior, SrcStatement, SrcUsage
from .model import PlatformData, PriorOutputData, SongListData, StatementData
from .rules import map_status


def _d(v) -> dt.date | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def statement_src(file_id: int, filename: str, data: StatementData, meta: dict) -> SrcStatement:
    return SrcStatement(file_id=file_id, label=meta.get("label") or names.short_label(filename), filename=filename,
                        section=meta["section"], dist_no=meta.get("dist_no"),
                        period_label=meta.get("period_label") or "Not specified",
                        period_start=_d(meta.get("period_start")), period_end=_d(meta.get("period_end")),
                        date=_d(meta.get("date")), date_estimated=bool(meta.get("date_estimated", True)),
                        holder_member=meta.get("holder_member"), printed_total=data.printed_total, lines=data.lines,
                        identity_key=meta.get("identity_key", ""))


def platform_src(file_id: int, filename: str, data: PlatformData, meta: dict) -> SrcPlatform:
    return SrcPlatform(file_id=file_id, label=names.short_label(filename), filename=filename,
                       platform=meta["platform"], distributor=meta["distributor"],
                       basis=str(meta.get("basis") or "GROSS").upper(), currency=str(meta.get("currency") or "INR"),
                       lines=data.lines)


def usage_src(file_id: int, filename: str, data: PlatformData, meta: dict) -> SrcUsage:
    return SrcUsage(file_id=file_id, label=names.short_label(filename), platform=meta.get("platform") or "Platform",
                    lines=data.lines)


def list_src(file_id: int, filename: str, data: SongListData, meta: dict) -> SrcList:
    return SrcList(file_id=file_id, label=meta.get("label") or names.short_label(filename), entries=data.entries)


def prior_src(file_id: int, filename: str, data: PriorOutputData, meta: dict) -> SrcPrior:
    return SrcPrior(file_id=file_id, label=data.generation, data=data)


def review_marks(file_id: int, label: str, data: SongListData) -> list[ReviewMark]:
    out = []
    for e in data.entries:
        st = map_status(e.status_text)
        if not st or not (e.isrcs or e.work_nos):
            continue
        out.append(ReviewMark(isrcs=e.isrcs, work_nos=e.work_nos, status=st, original=e.status_text, note=e.note,
                              source=f"review list {label}, row {e.row_no}", ref=file_id))
    return out


ZERO = Decimal("0")
