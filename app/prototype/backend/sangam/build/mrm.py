"""S6b attaching platform revenue - the ISRC-first cascade (architecture §9 S6b) - and the
platform-only / usage-only rows of the row universe (S5 steps 3 and 4).

    B1 ISRC is some entry's primary (ordinal-0) ISRC
    B2 ISRC is anywhere in an entry's ISRC list
    B3 ISRC sits on a statement-only row
    B4 norm(title) matches a catalogue name                  } a song name moves money:
    B5 norm(title) matches a statement-only row              } stamped in the basis column,
    B6 norm2(title) matches a catalogue name                 } ISRC written into column A
    B7 no match - the ISRC gets a row of its own

B4/B5 are the SKV7 legacy fallback the architecture keeps as its one explicit exception
(§8 rule 1), always stamped. B6 is an L5 (version-stripped) match, which V2 says never moves
money on its own, so it is opt-in. Per build, config name_fallback is:
    "exact"           B4 + B5 (default)
    "exact+stripped"  B4 + B5 + B6 (SKV7 behaviour)
    "off"             no name ever attaches money
Without a name rung the ISRC gets its own row and the merge review proposes the pairing.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from ..domain.normalize import norm, norm2
from .model import BASIS, NAME_BASES, Row
from .universe import pick_owner


def aggregate_platform(lines: list[dict]):
    """lines in report order -> per-ISRC monthly revenue, revenue-weighted title, album, UPC."""
    per_isrc: dict[str, dict[str, float]] = {}
    title_w: dict[str, Counter] = defaultdict(Counter)
    album_w: dict[str, Counter] = defaultdict(Counter)
    upcs: dict[str, set] = defaultdict(set)
    for ln in lines:
        i = ln["isrc"]
        per_isrc.setdefault(i, defaultdict(float))[ln["month"]] += ln["value"]
        if ln["content_name"]:
            title_w[i][ln["content_name"]] += abs(ln["value"]) or 1e-12
        if ln["album"]:
            album_w[i][ln["album"]] += abs(ln["value"]) or 1e-12
        if ln["upc"]:
            upcs[i].add(ln["upc"])
    meta = {}
    for i in per_isrc:
        meta[i] = dict(title=_top(title_w[i]), album=_top(album_w[i]), upcs=sorted(upcs[i]))
    return per_isrc, meta


def _top(c: Counter) -> str:
    if not c:
        return ""
    best = max(c.values())
    return next(k for k, v in c.items() if v == best)          # first-seen among ties


def fallback_mode(v) -> str:
    if v is True or v is None:
        return "exact"
    if v is False:
        return "off"
    if v not in ("exact", "exact+stripped", "off"):
        raise ValueError(f"name_fallback must be exact, exact+stripped or off - not {v!r}")
    return v


def attach_revenue(lines: list[dict], rows: list[Row], by_key: dict[str, Row], cat_label: str,
                   client: str, name_fallback="exact") -> dict:
    mode = fallback_mode(name_fallback)
    exact, stripped = mode in ("exact", "exact+stripped"), mode == "exact+stripped"
    per_isrc, meta = aggregate_platform(lines)
    cat_rows = [r for r in rows if r.origin == "catalogue"]
    stmt_rows = [r for r in rows if r.origin == "statement"]
    primary, anywhere, stmt_isrc = defaultdict(list), defaultdict(list), {}
    for r in cat_rows:
        if r.isrcs:
            primary[r.isrcs[0]].append(r)
        for i in r.isrcs:
            anywhere[i].append(r)
    for r in stmt_rows:
        for i in r.isrcs:
            stmt_isrc.setdefault(i, r)
    cat_name, stmt_name, cat_name2 = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in cat_rows:
        if norm(r.name):
            cat_name[norm(r.name)].append(r)
        if norm2(r.name):
            cat_name2[norm2(r.name)].append(r)
    for r in stmt_rows:
        if norm(r.name):
            stmt_name[norm(r.name)].append(r)

    counts: Counter = Counter()
    shared = 0
    for isrc, months in per_isrc.items():
        t = meta[isrc]["title"]
        k, k2 = norm(t), norm2(t)
        tie = None
        if isrc in primary:
            row, code = pick_owner(primary[isrc], t), "B1"
            tie = primary[isrc] if len(primary[isrc]) > 1 else None
        elif isrc in anywhere:
            row, code = pick_owner(anywhere[isrc], t), "B2"
            tie = anywhere[isrc] if len(anywhere[isrc]) > 1 else None
        elif isrc in stmt_isrc:
            row, code = stmt_isrc[isrc], "B3"
        elif exact and k and k in cat_name:
            row, code = cat_name[k][0], "B4"
        elif exact and k and k in stmt_name:
            row, code = stmt_name[k][0], "B5"
        elif stripped and k2 and k2 in cat_name2:
            row, code = cat_name2[k2][0], "B6"
        else:
            row = Row(key=f"isrc:{isrc}", origin="platform", name=t or isrc, seq=len(rows))
            row.add_isrc(isrc, False, "B7")
            rows.append(row)
            by_key[row.key] = row
            code = "B7"
        counts[code] += 1
        if tie:                       # one ISRC registered under several entries - a name broke the tie
            shared += 1
            row.notes.append(f"ISRC {isrc} is registered under {len(tie)} catalogue entries; its revenue is "
                             f"booked here because the entry name best matches {client}'s title '{t}'")
        for m, v in months.items():
            row.mrm_raw[m] = row.mrm_raw.get(m, 0.0) + v
        row.mrm_isrcs[isrc] = dict(basis=code, revenue=sum(months.values()), title=t,
                                   album=meta[isrc]["album"], upcs=meta[isrc]["upcs"])
        row.add_basis(code)
        if code in NAME_BASES:
            row.add_isrc(isrc, False, code)
            if row.origin == "catalogue":
                row.notes.append(f"ISRC {isrc} reported by {client} but NOT registered in {cat_label} "
                                 f"- attached by song name ({BASIS[code]})")
            else:
                row.notes.append(f"ISRC {isrc} reported by {client} - attached to this statement work "
                                 f"by song name ({BASIS[code]})")
    return dict(counts=dict(sorted(counts.items())), isrcs=len(per_isrc), meta=meta, shared_isrcs=shared)


def attach_usage(lines: list[dict], rows: list[Row], by_key: dict[str, Row]) -> dict:
    per_isrc, meta = aggregate_platform(lines)
    owner = {}
    for r in rows:
        for i in r.isrcs:
            owner.setdefault(i, r)
    attached = new = 0
    for isrc, months in per_isrc.items():
        total = sum(months.values())
        r = owner.get(isrc)
        if r is None:
            r = Row(key=f"usage:{isrc}", origin="usage", name=meta[isrc]["title"] or isrc, seq=len(rows))
            r.add_isrc(isrc, False, "usage")
            rows.append(r)
            by_key[r.key] = r
            owner[isrc] = r
            new += 1
        else:
            attached += 1
        r.usage += total
    return dict(isrcs=len(per_isrc), attached=attached, usage_only=new, meta=meta)
