"""TYPE C catalogue and TYPE F user song sheets (architecture §5.3, §5.6, §9 S3/S3b).

The catalogue is simply the user sheet the platform knows by name: both load into
user_sheet_entry, with the ISRC '|' list exploded into ordered child rows (ordinal 0 is
the primary ISRC - the MRM cascade depends on it).
"""
from __future__ import annotations

from ..domain.normalize import isrc_list, month_key, noi, norm, num, s, split_ids
from ..domain.sniff import header_fingerprint, propose_mapping

FOOTER_NAMES = {"TOTAL", "GRAND TOTAL", "SUB TOTAL", "SUBTOTAL"}


def catalogue_mapping(grid) -> dict:
    """TYPE C is known by shape: header row 1 = Track Name | Internal NO | ISRC."""
    hdr = [s(x).lower() for x in grid[0]]

    def find(*names, default):
        for n in names:
            if n in hdr:
                return hdr.index(n)
        return default
    mapping = {
        "song_name": dict(col_index=find("track name", default=0), confidence=1.0),
        "internal_no": dict(col_index=find("internal no", "internal no.", default=1), confidence=1.0),
        "isrc": dict(col_index=find("isrc", default=2), confidence=1.0),
    }
    for f, m in mapping.items():
        m["header"] = s(grid[0][m["col_index"]]) if m["col_index"] < len(grid[0]) else ""
    return dict(header_row=0, header=[s(x) for x in grid[0]], mapping=mapping, columns=[],
                fingerprint=header_fingerprint(grid[0]), identity_ok=True)


def load_entries(grid, header_row: int, mapping: dict) -> list[dict]:
    """Rows below the header through the confirmed column map. ISRC cells may hold pipe-,
    comma- or semicolon-separated lists; a non-numeric internal number is kept verbatim."""
    col = {f: m["col_index"] for f, m in mapping.items()}

    def cell(r, f):
        j = col.get(f)
        return r[j] if j is not None and j < len(r) else None

    out = []
    for i in range(header_row + 1, len(grid)):
        r = grid[i]
        name = s(cell(r, "song_name"))
        raw_no = s(cell(r, "internal_no"))
        isrcs = isrc_list(cell(r, "isrc"))
        if not name and not raw_no and not isrcs:
            continue
        if name.upper() in FOOTER_NAMES and not isrcs:
            break                                            # TOTAL row - end of the list
        nos: list[str] = []
        for x in split_ids(raw_no, r"[|,;/\n]+") if raw_no else []:
            n = noi(x)
            if n and n not in nos:
                nos.append(n)
        out.append(dict(ordinal=len(out), sheet_row=i + 1, name=name, name_key=norm(name),
                        raw_no=raw_no or None, work_nos=nos, isrcs=isrcs,
                        amount=num(cell(r, "amount")) if "amount" in col else None,
                        period=month_key(cell(r, "period")) if "period" in col else None))
    return out


def user_sheet_proposal(grid) -> dict:
    p = propose_mapping(grid)
    if not p or not p["identity_ok"]:
        raise ValueError("no identity column (song name, internal number or ISRC) could be "
                         "recognised in this sheet - map the columns by hand or check the file")
    return p
