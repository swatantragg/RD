"""Workbook bytes -> sheets of cached cell values.

Some IPRS statements carry a wrong 1x1 dimension record, so dimensions are reset and every row is read.
Floats become exact Decimals (repr text); formulas are never evaluated.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import warnings
import zipfile
from decimal import Decimal

os.environ.setdefault("OPENPYXL_DEFUSEDXML", "True")

import openpyxl  # noqa: E402

from .. import config  # noqa: E402
from .safety import Rejected, Report  # noqa: E402

warnings.filterwarnings("ignore", module="openpyxl")


def zip_date(data: bytes) -> dt.date | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            ts = max(i.date_time for i in z.infolist())
        return dt.date(ts[0], ts[1], ts[2])
    except Exception:                                          # noqa: BLE001
        return None


def _cell(v):
    if isinstance(v, float):
        return None if v != v or v in (float("inf"), float("-inf")) else Decimal(repr(v))
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _trim(rows: list[list]) -> list[list]:
    while rows and all(v is None for v in rows[-1]):
        rows.pop()
    return rows


def read_xlsx(data: bytes, rep: Report) -> list[dict]:
    limit = config.settings.max_cells
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    sheets, cells = [], 0
    try:
        for ws in wb.worksheets:
            ws.reset_dimensions()
            rows = []
            for r in ws.iter_rows(values_only=True):
                rows.append([_cell(v) for v in r])
                cells += len(r)
                if cells > limit:
                    raise Rejected(f"cells: more than {limit:,} cells")
            sheets.append(dict(title=ws.title, state=getattr(ws, "sheet_state", "visible") or "visible",
                               rows=_trim(rows)))
    finally:
        wb.close()
    rep.ok("parse", f"{len(sheets)} sheet(s), {cells:,} cells read (cached values; formulas not evaluated)")
    return sheets


def read_csv(data: bytes, rep: Report) -> list[dict]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[_cell(v) for v in r] for r in csv.reader(io.StringIO(text), dialect)]
    rep.ok("parse", f"{len(rows):,} rows read")
    return [dict(title="csv", state="visible", rows=_trim(rows))]


def parse(data: bytes, rep: Report) -> list[dict]:
    return read_xlsx(data, rep) if rep.kind == "xlsx" else read_csv(data, rep)
