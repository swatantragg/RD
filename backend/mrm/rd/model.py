"""Plain data passed between parsers, the engine and the workbook writers. Money is Decimal everywhere."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

# file kinds (what the user sees in brackets)
STATEMENT = "STATEMENT"                  # Royalty statement (IPRS standard or overseas layout)
SONG_LIST = "SONG_LIST"                  # Song list
REVIEW_LIST = "REVIEW_LIST"              # Missing-song review list (a song list with a status column)
PLATFORM_REVENUE = "PLATFORM_REVENUE"    # Platform revenue report
PLATFORM_USAGE = "PLATFORM_USAGE"        # Platform usage report (plays; never money)
PREVIOUS_OUTPUT = "PREVIOUS_OUTPUT"      # Previous master report (SKV layout)
UNKNOWN = "UNKNOWN"

KIND_LABEL = {STATEMENT: "Royalty statement", SONG_LIST: "Song list", REVIEW_LIST: "Missing-song review list",
              PLATFORM_REVENUE: "Platform revenue report", PLATFORM_USAGE: "Platform usage report",
              PREVIOUS_OUTPUT: "Previous master report", UNKNOWN: "Unknown file"}
KINDS = tuple(KIND_LABEL)


@dataclass
class Problem:
    code: str                 # machine code, e.g. RECON_MISMATCH
    severity: str             # ERROR (cannot be used) | REVIEW (needs a person) | WARNING | INFO
    message: str              # plain-language text for the user
    detail: str = ""          # technical detail, shown under "More details"
    field: str | None = None  # the metadata field to ask for, when the fix is a missing value

    def as_dict(self) -> dict:
        return dict(code=self.code, severity=self.severity, message=self.message, detail=self.detail, field=self.field)


@dataclass
class RoyaltyLine:
    line_no: int
    row_no: int                       # 1-based row in the original sheet
    work_no: str | None               # numeric IPRS work number, or None when the line has none (held)
    raw_work: str
    title: str
    amount: Decimal
    party: str = ""
    role: str = ""
    language: str = ""
    own_pct: Decimal | None = None
    coll_pct: Decimal | None = None
    pool: str = ""
    source: str = ""
    usage: dict | None = None         # overseas usage split: RADIO, TV, ...


@dataclass
class Footer:
    name: str                         # 'SUMMARY OF ROYALTY' | 'POOL'
    rows: list[dict]
    rows_total: Decimal
    grand_total: Decimal | None


@dataclass
class StatementData:
    layout: str                       # IPRS_STANDARD | IPRS_OVERSEAS
    sheet: str
    header_row: int
    holder_member: str | None
    holder_name: str | None
    ipi_name_no: str | None
    ipi_base_no: str | None
    lines: list[RoyaltyLine]
    printed_total: Decimal | None
    lines_total: Decimal
    subtotal_total: Decimal
    footers: list[Footer]
    blank_amount_rows: list[int]
    pool_sources: list[str]


@dataclass
class PlatformLine:
    line_no: int
    row_no: int
    month: dt.date | None
    isrc: str
    title: str
    album: str = ""
    upc: str = ""
    amount: Decimal | None = None
    plays: Decimal | None = None


@dataclass
class PlatformData:
    kind: str                         # PLATFORM_REVENUE | PLATFORM_USAGE
    sheet: str
    header_row: int
    mapping: dict
    lines: list[PlatformLine]
    platform_values: list[str]
    currency_values: list[str]
    basis_hint: str | None


@dataclass
class SongEntry:
    entry_no: int
    row_no: int
    title: str
    work_nos: list[str]               # numeric work numbers in list order (element 0 = primary)
    isrcs: list[str]
    other_codes: list[str] = field(default_factory=list)   # non-numeric text kept verbatim ('NEED TO REGISTER')
    status_text: str = ""
    note: str = ""


@dataclass
class SongListData:
    kind: str                         # SONG_LIST | REVIEW_LIST
    sheet: str
    header_row: int
    mapping: dict
    entries: list[SongEntry]


@dataclass
class PriorColumn:
    index: int                        # 0-based column of the block's Date cell
    band: str                         # row-1 label without the count
    kind: str                         # ROYALTY | PLATFORM
    section: str                      # statement section, or platform band key
    dist_no: str
    period_label: str
    date: dt.date | None
    total: Decimal                    # TOTAL row amount (or sum of the column)
    platform: str | None = None
    distributor: str | None = None
    month: dt.date | None = None


@dataclass
class PriorRow:
    row_no: int
    isrcs: list[str]
    title: str
    work_nos: list[str]
    total: Decimal
    platform_totals: dict             # header -> Decimal
    cells: dict                       # column index -> Decimal
    status_text: str = ""
    booked_on: str = ""
    basis: str = ""


@dataclass
class PriorOutputData:
    sheet: str
    generation: str                   # e.g. 'SVF-RD-SKV8'
    native: bool                      # carries our _rd_meta sheet
    columns: list[PriorColumn]
    rows: list[PriorRow]
    grand_total: Decimal
    platform_grand: dict
    integrity: list[str]              # differences found by the import check (edited after export)
    meta: dict | None = None


@dataclass
class Parsed:
    kind: str
    layout: str
    confidence: str                   # HIGH | LOW
    why: str
    data: object | None
    problems: list[Problem] = field(default_factory=list)
    meta: dict = field(default_factory=dict)            # field -> value
    meta_source: dict = field(default_factory=dict)     # field -> filename | content | client setting | user
    summary: dict = field(default_factory=dict)
