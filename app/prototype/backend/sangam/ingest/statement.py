"""TYPE A / TYPE B statement extraction (architecture §5.1, §5.2, §9 S2).

Three rules keep the money honest:
  * extraction rule - Standard: keep a line iff SOURCE is non-blank (the bare line after it
    is a block sub-total). Overseas: keep a line iff NAME, ROLE and ROYALTY AMT are non-blank.
  * stop rule - parsing stops BEFORE the row whose any cell equals TOTAL ROYALTIES, or the
    printed grand total lands on the last work (defect D1).
  * three-way check - money lines == sub-total lines == printed TOTAL ROYALTIES.
"""
from __future__ import annotations

from ..domain.normalize import is_work_no, noi, num, s
from ..domain.sniff import statement_header_row

BUCKETS = ("RADIO", "TV", "CINEMAS", "PERMITS", "DEMAND", "GENERAL", "OTHERS")


def _letterhead(grid) -> dict:
    out = dict(member_no=None, member_name=None, ipi_name=None, ipi_base=None)
    if len(grid) >= 2 and s(grid[0][0]).upper() == "INTERNAL NO":
        out["member_no"] = noi(grid[0][1])
        out["ipi_name"] = s(grid[0][3]) if len(grid[0]) > 3 else None
        out["member_name"] = s(grid[1][1]).rstrip(", ").strip() or None
        out["ipi_base"] = s(grid[1][3]) if len(grid[1]) > 3 else None
    return out


def _footer(grid, start: int) -> dict:
    """SUMMARY OF ROYALTY (by language) and the pool/source summary - stored as independent
    reconciliation sources, never used as the primary extraction."""
    langs, pools = [], []
    i = start
    while i < len(grid):
        a = s(grid[i][0]).upper()
        if a == "LANGUAGE":
            hdr = [s(x).upper() for x in grid[i]]
            wi = hdr.index("NO. OF WORKS") if "NO. OF WORKS" in hdr else 1
            ai = hdr.index("ROYALTY AMT") if "ROYALTY AMT" in hdr else 2
            i += 1
            while i < len(grid) and s(grid[i][0]):
                langs.append(dict(language=s(grid[i][0]), works=num(grid[i][wi]),
                                  amount=num(grid[i][ai])))
                i += 1
            continue
        if a == "POOL":
            hdr = [s(x).upper() for x in grid[i]]
            idx = {h: j for j, h in enumerate(hdr) if h}
            i += 1
            while i < len(grid) and s(grid[i][0]):
                r = grid[i]
                pools.append(dict(pool=s(r[0]), source=s(r[idx.get("SOURCE", 1)]),
                                  description=s(r[idx.get("SOURCE DESCRIPTION", 2)]),
                                  works=num(r[idx["NO. OF WORKS"]]) if "NO. OF WORKS" in idx else 0,
                                  amount=num(r[idx["ROYALTY AMT"]]) if "ROYALTY AMT" in idx else 0))
                i += 1
            continue
        i += 1
    return dict(languages=langs, pools=pools,
                language_total=round(sum(x["amount"] for x in langs), 6) if langs else None,
                pool_total=round(sum(x["amount"] for x in pools), 6) if pools else None)


def extract_statement(grid: list[list], sheet_label: str, tolerance: float = 0.05) -> dict:
    h = statement_header_row(grid)
    if h is None:
        raise ValueError("no 'WORK INT NO' header row - not a statement")
    hdr = [s(x).upper() for x in grid[h]]
    schema = "Overseas" if ("RADIO" in hdr and "TV" in hdr) else "Standard"
    col = {name: j for j, name in enumerate(hdr) if name}
    amt = col.get("ROYALTY AMT", 16 if schema == "Overseas" else 11)
    c_src, c_pool = col.get("SOURCE", 10), col.get("POOL", 9)
    c_name, c_role, c_soc = col.get("NAME", 4), col.get("ROLE", 5), col.get("SOCIETY", 6)
    c_own, c_coll = col.get("OWN", 7), col.get("COLL", 8)
    bucket_cols = [(b, col[b]) for b in BUCKETS if b in col]

    stop = next((i for i in range(h + 1, len(grid))
                 if any(s(c).upper() == "TOTAL ROYALTIES" for c in grid[i])), None)
    anomalies: list[dict] = []
    if stop is None:
        anomalies.append(dict(kind="no_total_row", sheet_row=None,
                              detail="no TOTAL ROYALTIES row - the file cannot be reconciled"))
        end = len(grid)
        file_total = None
    else:
        end = stop
        file_total = num(grid[stop][amt])

    blocks: list[dict] = []
    lines: list[dict] = []
    subtotal, subtotal_lines, party_lines = 0.0, 0, 0
    cur = None
    for i in range(h + 1, end):
        r = grid[i]
        raw_a, title = s(r[0]), s(r[1])
        if raw_a or (title and (cur is None or title != cur["title"])):
            no = noi(r[0])
            synthetic = not is_work_no(no)
            work_no = no if not synthetic else f"?{sheet_label}:{raw_a or 'BLANK'}"
            if synthetic:
                anomalies.append(dict(kind="unparseable_work_id", sheet_row=i + 1,
                                      detail=f"work id {raw_a or '(blank)'!r} on '{title}' "
                                             f"booked as {work_no} - money kept"))
            cur = dict(ordinal=len(blocks), sheet_row=i + 1, work_no=work_no, raw_no=raw_a or None,
                       synthetic=synthetic, title=title, av=s(r[2]) or None,
                       language=s(r[3]) or None, amount=0.0, money_lines=0)
            blocks.append(cur)
        elif cur is not None:
            if s(r[2]) and not cur["av"]:
                cur["av"] = s(r[2])
            if s(r[3]) and not cur["language"]:
                cur["language"] = s(r[3])

        amount_cell = r[amt] if amt < len(r) else None
        if schema == "Standard":
            keep = bool(s(r[c_src]))
            is_sub = not keep and bool(s(amount_cell)) and not s(r[c_name])
        else:
            keep = bool(s(r[c_name]) and s(r[c_role]) and s(amount_cell))
            is_sub = not keep and bool(s(amount_cell)) and not s(r[c_name]) and not s(r[c_role])
        if is_sub:
            subtotal += num(amount_cell)
            subtotal_lines += 1
            continue
        if not keep:
            if s(r[c_name]):
                party_lines += 1
            continue
        if cur is None:                                       # money before any block
            cur = dict(ordinal=0, sheet_row=i + 1, work_no=f"?{sheet_label}:BLANK", raw_no=None,
                       synthetic=True, title="", av=None, language=None, amount=0.0,
                       money_lines=0)
            blocks.append(cur)
            anomalies.append(dict(kind="money_before_block", sheet_row=i + 1,
                                  detail="money line before the first work block"))
        a = num(amount_cell)
        cur["amount"] += a
        cur["money_lines"] += 1
        lines.append(dict(block=cur["ordinal"], sheet_row=i + 1, work_no=cur["work_no"],
                          party=s(r[c_name]) or None, role=s(r[c_role]) or None,
                          society=s(r[c_soc]) or None, own=num(r[c_own]), coll=num(r[c_coll]),
                          pool=s(r[c_pool]) or None if schema == "Standard" else None,
                          source=s(r[c_src]) or None if schema == "Standard" else None,
                          buckets={b: num(r[j]) for b, j in bucket_cols} if schema == "Overseas" else None,
                          amount=a))

    extracted = sum(x["amount"] for x in lines)
    diff = None if file_total is None else extracted - file_total
    checks = {
        "money_vs_printed": None if diff is None else abs(diff) <= tolerance,
        "money_vs_subtotal": None if subtotal_lines == 0 else abs(extracted - subtotal) <= tolerance,
        "stopped_before_total": stop is not None,
    }
    reconciled = bool(checks["money_vs_printed"]) and checks["money_vs_subtotal"] is not False
    works = {b["work_no"] for b in blocks}
    return dict(schema=schema, header_row=h + 1, stop_row=None if stop is None else stop + 1,
                file_total=file_total, extracted_total=extracted, subtotal_total=subtotal,
                subtotal_lines=subtotal_lines, party_lines=party_lines, recon_diff=diff,
                reconciled=reconciled, checks=checks, blocks=blocks, lines=lines,
                work_count=len(works), anomalies=anomalies,
                footer=_footer(grid, stop + 1) if stop is not None else None,
                letterhead=_letterhead(grid))
