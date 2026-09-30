"""S5 row universe and S6a book-once (architecture §9).

    1. one row per catalogue recording - paid or not
    2. + every work a statement paid that the catalogue does not list
    (3. + platform-only ISRCs and 4. + usage-only ISRCs are added by mrm.py)

Catalogue -> statement linking uses L1 only (internal number). A song name never attaches
statement money. Money paid once against a work is booked once: on the recording whose
name matches the statement title, else the version-stripped match, else the first
catalogue entry; the siblings carry 0.00 and a note naming the owner.
"""
from __future__ import annotations

from collections import defaultdict

from ..domain.normalize import norm, norm2
from .model import Row


def catalogue_rows(entries: list[dict], rows: list[Row], by_key: dict[str, Row]) -> dict[str, list[Row]]:
    cat_by_work: dict[str, list[Row]] = defaultdict(list)
    for e in entries:
        r = Row(key=f"cat:{e['ordinal']}", origin="catalogue", name=e["name"], seq=len(rows),
                entry_id=e["id"])
        for w in e["work_nos"]:
            r.add_work(w, True)
            cat_by_work[w].append(r)
        for i in e["isrcs"]:
            r.add_isrc(i, True, "catalogue")
        rows.append(r)
        by_key[r.key] = r
    return cat_by_work


def pick_owner(entries: list[Row], title: str) -> Row:
    cand = ([e for e in entries if norm(e.name) == norm(title)]
            or [e for e in entries if norm2(e.name) and norm2(e.name) == norm2(title)]
            or entries)
    return cand[0]


def book_statement_money(blocks: list[dict], cat_by_work: dict[str, list[Row]], rows: list[Row],
                         by_key: dict[str, Row]) -> dict:
    """blocks: statement blocks that carry money lines, in statement (s_no) then sheet order."""
    work_amt: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    work_title: dict[str, str] = {}
    for b in blocks:
        work_amt[b["work_no"]][b["statement_id"]] += b["amount"]
        if b["title"] and not work_title.get(b["work_no"]):
            work_title[b["work_no"]] = b["title"]
    owner_of: dict[str, str] = {}
    for w, per_st in work_amt.items():
        title = work_title.get(w, "")
        if w in cat_by_work:
            owner = pick_owner(cat_by_work[w], title)
            for sib in cat_by_work[w]:
                if sib is not owner:
                    sib.sibling_of[w] = owner.key
        else:
            owner = Row(key=f"work:{w}", origin="statement", name=title or w, seq=len(rows))
            owner.add_work(w, False)
            rows.append(owner)
            by_key[owner.key] = owner
        owner.owned_works.add(w)
        owner_of[w] = owner.key
        for st, amt in per_st.items():
            owner.raw_amounts[st] = owner.raw_amounts.get(st, 0.0) + amt
    # the sibling note, e.g. "IPRS work 15628861 - royalty booked once, on 'Tomake Chai' (INS2X1600134)"
    for r in rows:
        if r.sibling_of:
            notes = []
            for w, ok in sorted(r.sibling_of.items()):
                o = by_key[ok]
                prim = o.ordered_isrcs()[0] if o.isrcs else ""
                notes.append(f"IPRS work {w} - royalty booked once, on '{o.name}'"
                             + (f" ({prim})" if prim else ""))
            r.booked_note = " ; ".join(notes)
    return dict(work_amt=work_amt, work_title=work_title, owner_of=owner_of)
