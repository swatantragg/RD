"""In-memory row model of one build (the SKV matrix before it is persisted)."""
from __future__ import annotations

from dataclasses import dataclass, field

BASIS = {
    "B1": "ISRC - catalogue (primary ISRC of the recording)",
    "B2": "ISRC - catalogue (secondary ISRC of the recording)",
    "B3": "ISRC - royalty statement work (not in the SVF list)",
    "B4": "Song name - catalogue",
    "B5": "Song name - royalty statement work",
    "B6": "Song name, version words stripped - catalogue",
    "B7": "No match - song is only in Spotify's report",
}
NAME_BASES = ("B4", "B5", "B6")                     # a song name moved money - always stamped

# the eight catalogue-status values (architecture §9 S7), each with a fixed colour in the UI
STATUS = {
    "IN_RECEIVED": "In SVF list ({cat}) - royalty received",
    "IN_NONE": "In SVF list ({cat}) - no royalty distributed in any of the {n} statements",
    "NOT_PAID": "NOT in SVF list ({cat}) - work paid by a royalty statement",
    "IN_SIBLING": "In SVF list ({cat}) - separate recording of an IPRS work paid on another row",
    "NOT_PLATFORM": "NOT in SVF list ({cat}) - appears only in {client}'s revenue report",
    "IN_ZERO": "In SVF list ({cat}) - named in a statement, but the amount distributed was 0.00",
    "NOT_ZERO": "NOT in SVF list ({cat}) - named in a statement, but the amount distributed was 0.00",
    "NOT_USAGE": "NOT in SVF list ({cat}) - appears only in {client}'s usage report "
                 "(streams, but no revenue and no royalty in this period)",
}
STATUS_ORDER = list(STATUS)


@dataclass
class Row:
    key: str                                   # stable across a lineage: cat:<ord> | work:<no> | isrc:<isrc> | usage:<isrc>
    origin: str                                # catalogue | statement | platform | usage
    name: str
    seq: int                                   # creation order - the final tie-break
    entry_id: int | None = None
    works: list[str] = field(default_factory=list)
    work_registered: dict[str, bool] = field(default_factory=dict)
    isrcs: list[str] = field(default_factory=list)
    isrc_registered: dict[str, bool] = field(default_factory=dict)
    isrc_via: dict[str, str] = field(default_factory=dict)
    raw_amounts: dict[int, float] = field(default_factory=dict)       # statement_id -> raw money
    owned_works: set[str] = field(default_factory=set)                # works whose money is booked here
    sibling_of: dict[str, str] = field(default_factory=dict)          # work -> owner row key
    mrm_raw: dict[str, float] = field(default_factory=dict)           # 'YYYY-MM' -> raw revenue
    mrm_isrcs: dict[str, dict] = field(default_factory=dict)          # isrc -> basis, revenue, title, album
    usage: float = 0.0
    basis: list[str] = field(default_factory=list)                    # B-codes, in rung order
    notes: list[str] = field(default_factory=list)
    booked_note: str | None = None
    merged_keys: list[str] = field(default_factory=list)
    merged_from_decision: int | None = None
    # derived (S7)
    amounts: dict[int, float] = field(default_factory=dict)
    mrm: dict[str, float] = field(default_factory=dict)
    fy: dict[str, float] = field(default_factory=dict)
    total_amount: float = 0.0
    total_mrm: float = 0.0
    status_code: str = ""
    status: str = ""

    def add_isrc(self, isrc: str, registered: bool, via: str) -> None:
        if isrc not in self.isrc_registered:
            self.isrcs.append(isrc)
            self.isrc_registered[isrc] = registered
            self.isrc_via[isrc] = via

    def add_work(self, work_no: str, registered: bool) -> None:
        if work_no not in self.work_registered:
            self.works.append(work_no)
            self.work_registered[work_no] = registered

    def add_basis(self, code: str) -> None:
        if code not in self.basis:
            self.basis.append(code)
            self.basis.sort()

    def ordered_isrcs(self) -> list[str]:
        """Registered ISRCs in catalogue order first, then the unregistered ones."""
        return ([i for i in self.isrcs if self.isrc_registered[i]] +
                [i for i in self.isrcs if not self.isrc_registered[i]])

    def ordered_works(self) -> list[str]:
        return ([w for w in self.works if self.work_registered[w]] +
                [w for w in self.works if not self.work_registered[w]])
