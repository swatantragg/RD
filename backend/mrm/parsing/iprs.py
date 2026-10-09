"""IPRS / society publishing statements (A3 publishing record).

    * a line carries money only when SOURCE is filled; the bare line after it repeats the block sub-total
    * parsing stops before the row containing TOTAL ROYALTIES (the printed total, B4)
    * a written 0 is an explicit zero; a blank amount stays unknown
"""
from __future__ import annotations

from ..normalize import ZERO, amount, s, work_code
from .scope import platform_of, right_scope_of, use_type_of


def header_row(grid: list[list]) -> int | None:
    for i, r in enumerate(grid[:40]):
        if s(r[0] if r else None).upper() == "WORK INT NO" or any(s(c).upper() == "WORK INT NO" for c in r[:3]):
            return i
    return None


def letterhead(grid: list[list]) -> dict:
    out = dict(member_id=None, beneficiary=None, ipi_name_no=None)
    if len(grid) >= 2 and grid[0] and s(grid[0][0]).upper() == "INTERNAL NO":
        out["member_id"] = work_code(grid[0][1]) if len(grid[0]) > 1 else None
        out["ipi_name_no"] = (s(grid[0][3]) if len(grid[0]) > 3 else None) or None
        out["beneficiary"] = (s(grid[1][1]).rstrip(", ").strip() if len(grid[1]) > 1 else "") or None
    return out


def extract(grid: list[list], sheet: str) -> dict:
    h = header_row(grid)
    if h is None:
        raise ValueError("no 'WORK INT NO' header row - not an IPRS statement layout")
    hdr = [s(x).upper() for x in grid[h]]
    col = {name: j for j, name in enumerate(hdr) if name}
    amt = col.get("ROYALTY AMT", 11)
    c_src, c_pool = col.get("SOURCE"), col.get("POOL")
    c_name, c_role = col.get("NAME", 4), col.get("ROLE", 5)
    c_own, c_coll, c_title = col.get("OWN", 7), col.get("COLL", 8), col.get("TITLE", 1)

    def cell(r, j):
        return r[j] if j is not None and j < len(r) else None

    stop = next((i for i in range(h + 1, len(grid)) if any(s(c).upper() == "TOTAL ROYALTIES" for c in grid[i])), None)
    end = stop if stop is not None else len(grid)
    printed = amount(cell(grid[stop], amt)) if stop is not None else None
    lines: list[dict] = []
    issues: list[dict] = []
    subtotal = ZERO
    cur_code, cur_title = None, None
    for i in range(h + 1, end):
        r = grid[i]
        if not r or all(v is None for v in r):
            continue
        raw_a, title = s(cell(r, 0)), s(cell(r, c_title))
        if raw_a or title:
            cur_code, cur_title = work_code(cell(r, 0)), title or cur_title
        src = s(cell(r, c_src))
        a_cell = cell(r, amt)
        if not src:
            if a_cell is not None and not s(cell(r, c_name)):
                subtotal += amount(a_cell) or ZERO
            continue
        a = amount(a_cell)
        valid, reason = True, None
        if not cur_code or not cur_code.isdigit():
            valid, reason = False, f"work code {raw_a or '(blank)'!r} is not a work number"
        elif a is None:
            valid, reason = False, "royalty amount is blank or not a number (kept unknown, not zero)"
        if not valid:
            issues.append(dict(row=i + 1, reason=reason))
        pool = s(cell(r, c_pool)) or None
        lines.append(dict(row_no=i + 1, sheet=sheet, work_code=cur_code, title=cur_title,
                          party=s(cell(r, c_name)).rstrip(", ").strip() or None, role=s(cell(r, c_role)) or None,
                          own_pct=amount(cell(r, c_own)), coll_pct=amount(cell(r, c_coll)), pool=pool, source=src,
                          platform=platform_of(src), use_type=use_type_of(pool, src), right_scope=right_scope_of(pool),
                          amount=a, is_valid=valid, invalid_reason=reason))
    lines_total = sum((x["amount"] for x in lines if x["is_valid"]), ZERO)
    pools = _pool_footer(grid, stop + 1) if stop is not None else []
    return dict(header_row=h + 1, printed_total=printed, lines_total=lines_total, subtotal=subtotal, lines=lines,
                issues=issues, pools=pools, letterhead=letterhead(grid),
                works=len({x["work_code"] for x in lines if x["work_code"]}))


def _pool_footer(grid, start: int) -> list[dict]:
    out = []
    for i in range(start, len(grid)):
        if grid[i] and s(grid[i][0]).upper() == "POOL":
            hdr = [s(x).upper() for x in grid[i]]
            idx = {h: j for j, h in enumerate(hdr) if h}
            for r in grid[i + 1:]:
                if not r or not s(r[0]):
                    break
                def g(n, r=r, idx=idx):
                    return r[idx[n]] if n in idx and idx[n] < len(r) else None
                out.append(dict(pool=s(r[0]), source=s(g("SOURCE DESCRIPTION")) or s(g("SOURCE")),
                                works=s(g("NO. OF WORKS")), amount=amount(g("ROYALTY AMT"))))
            break
    return out


def fingerprint(lines: list[dict]) -> set[str]:
    return {f"{x['work_code']}|{x['source']}|{x['party']}|{x['amount']}" for x in lines}


def beneficiary_lines(lines: list[dict], member_names: list[str]) -> list[dict]:
    """Lines paid to the client (the statement may list co-owners' shares that are not the client's money)."""
    keys = [n.upper().replace(",", "").split() for n in member_names if n]
    out = []
    for ln in lines:
        p = (ln["party"] or "").upper().replace(",", "").split()
        if any(k and all(w in p for w in k[:2]) for k in keys):
            out.append(ln)
    return out

