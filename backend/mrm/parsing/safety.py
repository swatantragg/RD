"""B1/B2 file checks - the highest-risk surface.

    * .xlsx and .csv only; the type is decided from content (ZIP structure and [Content_Types].xml)
    * macro workbooks, vbaProject.bin, external links and OLE objects are rejected, not sent for mapping
    * limits: upload size, unzipped size, cells, sheets; ZIP entries checked for ratio and path tricks
    * XML is parsed with defusedxml; formulas are never evaluated (cached values are read)
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from .. import config

MACRO_TYPES = ("macroEnabled", "vbaProject", "ms-excel.sheet.binary", "ms-excel.addin", "ms-excel.template.macro")
FORBIDDEN_PARTS = ("vbaproject.bin", "xl/externallinks/", "xl/embeddings/", "xl/activex/", "customui/")


class Rejected(Exception):
    """The file must not be parsed. The message is shown to the operator."""


@dataclass
class Report:
    kind: str = ""                      # xlsx | csv
    checks: list[dict] = field(default_factory=list)

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append(dict(check=name, result="PASS", detail=detail))

    def fail(self, name: str, detail: str) -> None:
        self.checks.append(dict(check=name, result="FAIL", detail=detail))
        raise Rejected(f"{name}: {detail}")


def check_bytes(data: bytes, filename: str, rep: Report | None = None) -> Report:
    s = config.settings
    rep = rep if rep is not None else Report()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        rep.fail("size", f"{len(data):,} bytes is over the {s.max_upload_mb} MB upload limit")
    rep.ok("size", f"{len(data):,} bytes")
    if data[:4] == b"PK\x03\x04":
        rep.kind = "xlsx"
        _check_zip(data, rep)
    else:
        if not filename.lower().endswith(".csv"):
            rep.fail("type", "not an .xlsx workbook (no ZIP signature) and not a .csv file - .xls, .xlsb and "
                             "other formats are not accepted")
        _check_csv(data, rep)
        rep.kind = "csv"
    return rep


def _check_zip(data: bytes, rep: Report) -> None:
    s = config.settings
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        rep.fail("zip", f"damaged workbook: {e}")
    names = z.namelist()
    if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
        rep.fail("type", "ZIP file is not an Excel workbook ([Content_Types].xml / xl/ missing)")
    total = 0
    for info in z.infolist():
        n = info.filename
        if n.startswith("/") or ".." in n.split("/") or "\\" in n or ":" in n:
            rep.fail("zip-path", f"suspicious entry name {n!r}")
        total += info.file_size
        if info.compress_size and info.file_size / info.compress_size > s.max_zip_ratio and info.file_size > 1_000_000:
            rep.fail("zip-ratio", f"{n} expands {info.file_size / info.compress_size:.0f}x - possible ZIP bomb")
        low = n.lower()
        if any(low.startswith(p) or low.endswith(p) for p in FORBIDDEN_PARTS):
            rep.fail("active-content", f"workbook contains {n} (macros, external links, ActiveX or OLE objects "
                                       f"are not accepted)")
    if total > s.max_unzipped_mb * 1024 * 1024:
        rep.fail("unzipped-size", f"{total:,} bytes unzipped is over the {s.max_unzipped_mb} MB limit")
    rep.ok("zip", f"{len(names)} entries, {total:,} bytes unzipped")
    ct = z.read("[Content_Types].xml").decode("utf-8", "replace")
    if any(t.lower() in ct.lower() for t in MACRO_TYPES):
        rep.fail("type", "macro-enabled or binary workbook (.xlsm / .xlsb) - save it as .xlsx first")
    if "spreadsheetml.sheet.main+xml" not in ct and "spreadsheetml.template.main+xml" not in ct:
        rep.fail("type", "[Content_Types].xml does not declare an Excel workbook")
    rep.ok("content-types", "plain .xlsx workbook")
    sheets = [n for n in names if n.startswith("xl/worksheets/") and n.endswith(".xml")]
    if len(sheets) > s.max_sheets:
        rep.fail("sheets", f"{len(sheets)} sheets is over the {s.max_sheets} limit")
    rep.ok("sheets", f"{len(sheets)} sheet(s)")


def _check_csv(data: bytes, rep: Report) -> None:
    head = data[:4096]
    if b"\x00" in head:
        rep.fail("type", "binary content - not a text .csv file")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            data.decode("cp1252")
        except UnicodeDecodeError:
            rep.fail("encoding", "the .csv file is neither UTF-8 nor Windows-1252 text")
    rep.ok("csv", "text file")
