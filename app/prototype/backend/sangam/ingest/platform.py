"""TYPE D (Spotify MRM revenue) and TYPE E (Spotify usage) reports (architecture §5.4, §5.5).

The two reports have different column orders (usage has no Content Type) - columns are
found by header text, never by position. Revenue is kept at full precision; nothing is
rounded before aggregation.
"""
from __future__ import annotations

from ..domain.normalize import ik, month_key, num, s

ALIASES = {
    "month": ("month",),
    "client": ("client",),
    "content_type": ("content type",),
    "content_name": ("content name", "track name", "title"),
    "album": ("album name", "album"),
    "isrc": ("isrc",),
    "upc": ("upc",),
    "revenue": ("revenue", "net revenue", "gross revenue"),
    "usage": ("usage", "streams"),
}


def extract_platform(grid, kind: str) -> dict:
    hdr = [s(x).lower() for x in grid[0]]
    col = {}
    for f, names in ALIASES.items():
        for n in names:
            if n in hdr:
                col[f] = hdr.index(n)
                break
    value_field = "revenue" if kind == "PLATFORM_REVENUE" else "usage"
    missing = [f for f in ("month", "isrc", value_field) if f not in col]
    if missing:
        raise ValueError(f"platform report is missing column(s): {', '.join(missing)}")

    def g(r, f):
        j = col.get(f)
        return r[j] if j is not None and j < len(r) else None

    lines, skipped, clients = [], 0, set()
    for i, r in enumerate(grid[1:], start=2):
        isrc = ik(g(r, "isrc"))
        mk = month_key(g(r, "month"))
        if not isrc or not mk:
            if any(v is not None for v in r):
                skipped += 1
            continue
        upc = g(r, "upc")
        if isinstance(upc, float) and upc.is_integer():
            upc = int(upc)
        client = s(g(r, "client")) or "Spotify"
        clients.add(client)
        lines.append(dict(ordinal=len(lines), sheet_row=i, month=mk, isrc=isrc,
                          content_name=s(g(r, "content_name")), album=s(g(r, "album")) or None,
                          upc=s(upc) or None, content_type=s(g(r, "content_type")) or None,
                          value=num(g(r, value_field))))
    months = sorted({x["month"] for x in lines})
    return dict(lines=lines, skipped=skipped, months=months,
                client=sorted(clients)[0] if clients else "Spotify",
                total=sum(x["value"] for x in lines),
                isrc_count=len({x["isrc"] for x in lines}))
