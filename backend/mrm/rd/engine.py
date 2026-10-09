"""The build: base rows + money sources + decisions + rule set -> one checked result (Architecture V3 §5, §6, §10).

Money lands only through codes:
  * a statement line attaches to its WORK (IPRS work number), a platform line to its RECORDING (ISRC);
  * a work claimed by several base rows is booked ONCE, on the owner row (title match, else first entry); the
    other rows show 0.00 and say where the money was booked;
  * a recording claimed by rows of DIFFERENT songs is HELD on its own row until a person assigns it;
  * a title never moves money: title matches become proposals that need an approved decision;
  * society royalty and platform revenue are different kinds of money and are never added together.

Every build asserts its invariants (S9). One failure fails the build and names what broke.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from ..normalize import base_title, fold, is_version, similarity, title_key
from . import names
from .model import PlatformLine, PriorOutputData, RoyaltyLine, SongEntry
from .rules import (NEW, NOT_OURS, OVERSEAS_CYCLE, PALETTE, PLATFORM_AFTER, PLATFORM_FILL, STATUS_LABEL, UNRESOLVED,
                    section_rank)

ZERO = Decimal("0")
q2 = names.q2


# ================================================================== inputs
@dataclass
class SrcStatement:
    file_id: int
    label: str
    filename: str
    section: str
    dist_no: str | None
    period_label: str
    period_start: dt.date | None
    period_end: dt.date | None
    date: dt.date | None
    date_estimated: bool
    holder_member: str | None
    printed_total: Decimal | None
    lines: list[RoyaltyLine]
    identity_key: str = ""
    relation: str = ""             # '' | SUPPLEMENTARY (count it even though a previous report has this distribution)


@dataclass
class SrcPlatform:
    file_id: int
    label: str
    filename: str
    platform: str
    distributor: str
    basis: str                     # GROSS | NET
    currency: str
    lines: list[PlatformLine]


@dataclass
class SrcUsage:
    file_id: int
    label: str
    platform: str
    lines: list[PlatformLine]


@dataclass
class SrcList:
    file_id: int
    label: str
    entries: list[SongEntry]


@dataclass
class SrcPrior:
    file_id: int
    label: str
    data: PriorOutputData


@dataclass
class ReviewMark:
    isrcs: list[str]
    work_nos: list[str]
    status: str
    original: str = ""
    note: str = ""
    source: str = ""               # 'review list S-x' | 'decision #n'
    ref: int | None = None


@dataclass
class Decision:
    id: int
    kind: str                      # LINK | NOT_SAME | ASSIGN_HELD
    subject: dict                  # {code_kind: ISRC|WORK, code: ...}
    value: dict                    # {target: {code_kind, code}}  (LINK / ASSIGN_HELD)
    approved_by: str = ""


@dataclass
class RunInput:
    client_code: str
    client_name: str
    statements: list[SrcStatement] = field(default_factory=list)
    platforms: list[SrcPlatform] = field(default_factory=list)
    usages: list[SrcUsage] = field(default_factory=list)
    song_list: SrcList | None = None
    prior: SrcPrior | None = None
    reviews: list[ReviewMark] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    ruleset: dict = field(default_factory=dict)
    generation: str = ""           # e.g. 'SVF-RD-SKV9' (or a draft name)


# ================================================================== result
@dataclass
class Col:
    key: str
    kind: str                      # ROYALTY | PLATFORM
    band: str                      # section (royalty) or platform band key
    dist_no: str
    period_label: str
    period_start: dt.date | None
    period_end: dt.date | None
    date: dt.date | None
    origin: str                    # source | prior
    file_id: int | None
    label: str
    printed_total: Decimal | None = None
    platform: str | None = None
    distributor: str | None = None
    basis: str | None = None
    month: dt.date | None = None
    exact_total: Decimal = ZERO
    shown_total: Decimal = ZERO


@dataclass
class Cell:
    exact: Decimal
    shown: Decimal = ZERO
    named_zero: bool = False
    sibling: bool = False
    lines: int = 0


@dataclass
class Row:
    key: str
    title: str
    isrcs: list[str]
    work_nos: list[str]
    origin: str                    # list | prior | work | recording | usage | hold
    in_base: bool
    order: int
    extra_isrcs: list[str] = field(default_factory=list)
    extra_works: list[str] = field(default_factory=list)
    cells: dict = field(default_factory=dict)
    booked_on: list[str] = field(default_factory=list)
    basis: dict = field(default_factory=lambda: defaultdict(list))
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    hold: str | None = None
    hold_candidates: list[str] = field(default_factory=list)
    prior_status: str = ""
    prior_basis: str = ""
    stmt_titles: Counter = field(default_factory=Counter)
    plat_titles: Counter = field(default_factory=Counter)
    usage_plays: Decimal = ZERO
    status: str = ""
    royalty: Decimal = ZERO
    platform: dict = field(default_factory=dict)
    fy: dict = field(default_factory=dict)
    review: ReviewMark | None = None
    proposals: list[dict] = field(default_factory=list)
    basis_note: str = ""
    usage_platform: str = ""
    assigned_isrcs: list[str] = field(default_factory=list)

    @property
    def all_isrcs(self) -> list[str]:
        return list(dict.fromkeys(self.isrcs + self.extra_isrcs))

    @property
    def all_works(self) -> list[str]:
        return list(dict.fromkeys(self.work_nos + self.extra_works))


@dataclass
class Band:
    key: str
    kind: str
    section: str
    label: str
    fill: str
    tint: str
    cols: list[Col]
    platform: str | None = None
    distributor: str | None = None
    basis: str | None = None
    total_header: str | None = None
    basis_header: str | None = None


@dataclass
class Result:
    rows: list[Row]
    bands: list[Band]
    fy_keys: list
    base_label: str
    grain: str
    findings: list[Row]            # paid but not in the base (the Missing Songs population), in report order
    issues: list[dict]
    checks: list[dict]
    totals: dict
    notices: list[str]
    ok: bool
    statements: list[SrcStatement]
    platforms: list[SrcPlatform]


class BuildFailed(Exception):
    def __init__(self, message: str, checks: list[dict]):
        super().__init__(message)
        self.checks = checks


# ================================================================== helpers
_BOOKED = re.compile(r"IPRS work (\S+) - royalty booked once, on '(.*)' \((.*)\)")


def same_title(a: str, b: str) -> str | None:
    """-> 'same' | 'version' | 'spelling' | None (different words)  (V3 §7.2)."""
    if not a or not b:
        return None
    if title_key(a) == title_key(b):
        return "same"
    if base_title(a) == base_title(b):
        return "version"
    if fold(a) == fold(b) or similarity(a, b) >= 0.90:
        return "spelling"
    return None


def isrc_family(a: str, b: str, gap: int) -> str | None:
    if len(a) != 12 or len(b) != 12 or a == b:
        return None
    if a[:7] == b[:7] and a[7:].isdigit() and b[7:].isdigit() and abs(int(a[7:]) - int(b[7:])) <= gap:
        return "family"
    if a[:5] == b[:5]:
        return "registrant"
    return None


# ================================================================== the build
def build(inp: RunInput) -> Result:
    rs = inp.ruleset
    gap = int(rs.get("isrc_family_gap", 50))
    rows: list[Row] = []
    by_key: dict[str, Row] = {}
    idx_work: dict[str, list[Row]] = defaultdict(list)
    idx_isrc: dict[str, list[Row]] = defaultdict(list)
    issues: list[dict] = []
    notices: list[str] = []

    def add_row(r: Row) -> Row:
        rows.append(r)
        by_key[r.key] = r
        if r.origin == "hold":                    # a held row never claims a code: it waits for a decision
            return r
        for w in r.all_works:
            if r not in idx_work[w]:
                idx_work[w].append(r)
        for i in r.all_isrcs:
            if r not in idx_isrc[i]:
                idx_isrc[i].append(r)
        return r

    base_parts = []
    cols: dict[str, Col] = {}
    owner_hint: dict[str, Row] = {}              # work -> owner row named by a previous output

    # ---------------------------------------------------------------- 1. base: previous output
    if inp.prior:
        po = inp.prior.data
        base_parts.append(f"previous report {po.generation}")
        for c in po.columns:
            a, b = names.parse_period_label(c.period_label)
            key = f"X:{inp.prior.file_id}:{c.index}"
            cols[key] = Col(key=key, kind=c.kind, band=c.section if c.kind == "ROYALTY" else
                            _pband(c.platform or "Platform", c.distributor or "", "GROSS"), dist_no=c.dist_no,
                            period_label=c.period_label, period_start=a, period_end=b, date=c.date, origin="prior",
                            file_id=inp.prior.file_id, label=po.generation, printed_total=c.total,
                            platform=c.platform, distributor=c.distributor, basis="GROSS" if c.kind == "PLATFORM" else
                            None, month=c.month)
        for n, pr in enumerate(po.rows):
            r = Row(key=f"prior:{inp.prior.file_id}:{pr.row_no}", title=pr.title, isrcs=pr.isrcs, work_nos=pr.work_nos,
                    origin="prior", in_base=True, order=n, prior_status=pr.status_text, prior_basis=pr.basis)
            for ci, amt in pr.cells.items():
                k = f"X:{inp.prior.file_id}:{ci}"
                r.cells[k] = Cell(exact=amt, shown=q2(amt), named_zero=(amt == 0))
            if pr.booked_on:
                r.booked_on.append(pr.booked_on)
            if pr.basis and cols and any(cols[k].kind == "PLATFORM" for k in r.cells if k in cols):
                pb = next(cols[k].band for k in r.cells if k in cols and cols[k].kind == "PLATFORM")
                r.basis[pb].append(pr.basis)
            if pr.basis.lower().startswith("song name") or "; song name" in pr.basis.lower():
                r.flags.append("Platform money placed by song name in an earlier report - please confirm")
                issues.append(_issue("TITLE_PLACED_IN_BASE", "INFO", "MATCHING",
                                     f"'{pr.title}' received platform money through a song-name match in "
                                     f"{po.generation}", "The money is carried as it is. Confirm the match, or ask "
                                     "for it to be moved.", dict(row=r.key, title=pr.title, basis=pr.basis,
                                                                  isrcs=pr.isrcs, work_nos=pr.work_nos), []))
            add_row(r)
        for r in rows:
            for text in r.booked_on:
                m = _BOOKED.match(text)
                if m:
                    owner = next((x for x in rows if x.title == m.group(2) and
                                  (not m.group(3) or m.group(3) in x.isrcs)), None)
                    if owner:
                        owner_hint[m.group(1)] = owner

    # ---------------------------------------------------------------- 2. base: song list
    if inp.song_list:
        sl = inp.song_list
        base_parts.append(f"song list {sl.label}")
        for e in sl.entries:
            if inp.prior:
                hit = [r for w in e.work_nos for r in idx_work.get(w, []) if r.origin == "prior"] + \
                      [r for i in e.isrcs for r in idx_isrc.get(i, []) if r.origin == "prior"]
                if hit:
                    for r in dict.fromkeys(hit):
                        r.notes.append("in list")
                    continue
            add_row(Row(key=f"list:{sl.file_id}:{e.entry_no}", title=e.title, isrcs=e.isrcs, work_nos=e.work_nos,
                        origin="list", in_base=True, order=len(rows)))
    has_base = bool(inp.prior or inp.song_list)
    base_label = _base_label(inp)

    # ---------------------------------------------------------------- 3. approved decisions that add codes to rows
    not_same: set[tuple] = set()
    for d in inp.decisions:
        if d.kind == "NOT_SAME":
            t = d.value.get("target") or {}
            not_same.add((d.subject.get("code"), t.get("code")))
    assigned: dict[str, Row] = {}
    for d in sorted(inp.decisions, key=lambda x: x.id):
        if d.kind not in ("LINK", "ASSIGN_HELD"):
            continue
        t = d.value.get("target") or {}
        target = _find_row(t, idx_work, idx_isrc, by_key)
        if target is None:
            notices.append(f"Decision #{d.id} could not be applied: the song it points to is not in this run.")
            continue
        code, ck = str(d.subject.get("code")), d.subject.get("code_kind")
        if d.kind == "ASSIGN_HELD":
            assigned[code] = target
            target.assigned_isrcs.append(code)
            if code not in target.all_isrcs:
                target.extra_isrcs.append(code)
            target.notes.append(f"Shared recording {code} assigned here by decision #{d.id}")
            continue
        if ck == "ISRC" and code not in target.all_isrcs:
            target.extra_isrcs.append(code)
            idx_isrc[code] = [target]
            target.basis_note = f"ISRC - confirmed match (decision #{d.id}{', approved by ' + d.approved_by if d.approved_by else ''})"
            target.notes.append(f"Linked by decision #{d.id}: ISRC {code}")
        elif ck == "WORK" and code not in target.all_works:
            target.extra_works.append(code)
            idx_work[code] = [target]
            target.notes.append(f"Linked by decision #{d.id}: work {code}")

    # ---------------------------------------------------------------- 4. columns for the new money
    stmts, plats = _not_already_in_base(inp, cols, issues, notices)
    stmts = sorted(stmts, key=lambda s_: (section_rank(s_.section), s_.date or dt.date.min, s_.file_id))
    seen_ids: dict[str, int] = {}
    for st in stmts:
        if st.identity_key and st.identity_key in seen_ids:
            raise BuildFailed(f"Two statements with the same identity were included ({st.label}).",
                              [dict(id="I12", ok=False, text="no statement identity counts twice")])
        seen_ids[st.identity_key] = st.file_id
        key = f"S:{st.file_id}"
        cols[key] = Col(key=key, kind="ROYALTY", band=st.section, dist_no=st.dist_no or "Not specified",
                        period_label=st.period_label, period_start=st.period_start, period_end=st.period_end,
                        date=st.date, origin="source", file_id=st.file_id, label=st.label,
                        printed_total=st.printed_total)
    for pr in plats:
        band = _pband(pr.platform, pr.distributor, pr.basis)
        months = sorted({x.month for x in pr.lines if x.month})
        period = names.period_label(months[0], names.month_end_of(months[-1])) if months else ""
        for m in months:
            key = f"P:{pr.file_id}:{m.isoformat()[:7]}"
            cols[key] = Col(key=key, kind="PLATFORM", band=band, dist_no=f"{pr.distributor} {period}".strip(),
                            period_label=f"{names.MONTH_LABEL[m.month]} {m.year}", period_start=m,
                            period_end=names.month_end_of(m), date=names.month_end_of(m), origin="source",
                            file_id=pr.file_id, label=pr.label, platform=pr.platform, distributor=pr.distributor,
                            basis=pr.basis, month=m)

    # ---------------------------------------------------------------- 5. place statement money (works)
    by_work: dict[str, list[tuple[SrcStatement, RoyaltyLine]]] = defaultdict(list)
    no_code: list[tuple[SrcStatement, RoyaltyLine]] = []
    for st in stmts:
        for ln in st.lines:
            (by_work[ln.work_no].append((st, ln)) if ln.work_no else no_code.append((st, ln)))
    for w in sorted(by_work, key=lambda x: (len(x), x)):
        entries = by_work[w]
        titles = Counter(ln.title for _, ln in entries if ln.title)
        latest_title = max(entries, key=lambda e: (e[0].date or dt.date.min, e[0].file_id))[1].title
        cands = idx_work.get(w, [])
        if not cands:
            r = add_row(Row(key=f"work:{w}", title=latest_title or w, isrcs=[], work_nos=[w], origin="work",
                            in_base=False, order=len(rows)))
            cands = [r]
        owner = _owner(w, cands, titles, owner_hint)
        siblings = [r for r in cands if r is not owner]
        for st, ln in entries:
            k = f"S:{st.file_id}"
            c = owner.cells.setdefault(k, Cell(exact=ZERO))
            c.exact += ln.amount
            c.lines += 1
            if ln.amount < 0 and "Negative adjustment" not in " ".join(owner.flags):
                owner.flags.append(f"Negative adjustment in {st.label}")
        for st in {st.file_id: st for st, _ in entries}.values():
            k = f"S:{st.file_id}"
            if owner.cells[k].exact == 0 and all(ln.amount == 0 for s_, ln in entries if s_.file_id == st.file_id):
                owner.cells[k].named_zero = True
            for sib in siblings:
                sib.cells.setdefault(k, Cell(exact=ZERO, sibling=True))
        owner.stmt_titles.update(titles)
        for sib in siblings:
            ptxt = f"IPRS work {w} - royalty booked once, on '{owner.title}' ({owner.all_isrcs[0] if owner.all_isrcs else 'no ISRC'})"
            if ptxt not in sib.booked_on:
                sib.booked_on.append(ptxt)
        for t in titles:
            if same_title(t, owner.title) is None and owner.in_base:
                flag = f"Code matches but song names differ: statement says '{t}'"
                if flag not in owner.flags:
                    owner.flags.append(flag)
    for st, ln in no_code:
        key = f"hold:nocode:{st.file_id}:{ln.raw_work or 'blank'}"
        r = by_key.get(key) or add_row(Row(key=key, title=ln.title or "(no title)", isrcs=[], work_nos=[],
                                           origin="hold", in_base=False, order=len(rows),
                                           hold="Statement entry without a work number - needs a decision"))
        c = r.cells.setdefault(f"S:{st.file_id}", Cell(exact=ZERO))
        c.exact += ln.amount
        c.lines += 1
        r.flags.append(f"HELD: {st.label} entry '{ln.raw_work or 'blank'}' has no work number")
    if no_code:
        amt = sum((ln.amount for _, ln in no_code), ZERO)
        issues.append(_issue("HELD_NO_CODE", "REVIEW", "MONEY", f"{len(no_code)} statement entries have no work "
                             f"number ({_money(amt)})", "The money is shown on its own 'held' rows and counted in "
                             "every total until someone decides where it belongs.", dict(count=len(no_code)), []))

    # ---------------------------------------------------------------- 6. place platform money (recordings)
    hold_shared = bool(rs.get("hold_shared_recordings", True))
    for pr in plats:
        band = _pband(pr.platform, pr.distributor, pr.basis)
        grouped: dict[tuple, list[PlatformLine]] = defaultdict(list)
        best_title: dict[str, Counter] = defaultdict(Counter)
        for ln in pr.lines:
            if ln.amount is None or not ln.month:
                continue
            grouped[(ln.isrc, ln.month)].append(ln)
            best_title[ln.isrc][ln.title] += ln.amount
        for (isrc, month) in sorted(grouped, key=lambda k: (k[0], k[1])):
            lns = grouped[(isrc, month)]
            amt = sum((x.amount for x in lns), ZERO)
            k = f"P:{pr.file_id}:{month.isoformat()[:7]}"
            if not isrc:
                key = f"hold:noisrc:{pr.file_id}:{title_key(lns[0].title)}"
                r = by_key.get(key) or add_row(Row(key=key, title=lns[0].title or "(no title)", isrcs=[], work_nos=[],
                                                   origin="hold", in_base=False, order=len(rows),
                                                   hold="Platform line without an ISRC - needs a decision"))
            else:
                title = max(best_title[isrc].items(), key=lambda kv: (kv[1], kv[0]))[0] if best_title[isrc] else isrc
                r = _platform_row(isrc, idx_isrc, assigned, hold_shared, add_row, by_key, rows, lns, pr, issues, title)
            c = r.cells.setdefault(k, Cell(exact=ZERO))
            c.exact += amt
            c.lines += len(lns)
            for x in lns:
                r.plat_titles[x.title] += x.amount
            r.basis[band].append(_basis_text(r, isrc, pr))
    # ---------------------------------------------------------------- 7. usage-only recordings
    for ur in inp.usages:
        plays: dict[str, Decimal] = defaultdict(lambda: ZERO)
        titles: dict[str, str] = {}
        for ln in ur.lines:
            if ln.isrc:
                plays[ln.isrc] += ln.plays or ZERO
                titles.setdefault(ln.isrc, ln.title)
        for isrc in sorted(plays):
            hit = idx_isrc.get(isrc)
            if hit:
                for r in hit:
                    r.usage_plays += plays[isrc]
                continue
            add_row(Row(key=f"usage:{isrc}", title=titles[isrc], isrcs=[isrc], work_nos=[], origin="usage",
                        in_base=False, order=len(rows), usage_plays=plays[isrc], usage_platform=ur.platform))

    # ---------------------------------------------------------------- 8. rounding: each column's printed cells add up
    # A statement column prints the statement's own rounded total. A platform report's month columns print month
    # totals that add up exactly to the report's rounded total (the paisa lost in rounding goes to the month that
    # lost most), so no total is ever a paisa off the source.
    members_of = {key: [(r, r.cells[key]) for r in rows if key in r.cells] for key in cols}
    for col in cols.values():
        col.exact_total = sum((c.exact for _, c in members_of[col.key]), ZERO)
    targets = {k: c.exact_total for k, c in cols.items()}
    for pr in plats:
        mk = [k for k, c in cols.items() if c.kind == "PLATFORM" and c.origin == "source" and c.file_id == pr.file_id]
        targets.update(names.penny_fix({k: cols[k].exact_total for k in mk},
                                       sum((cols[k].exact_total for k in mk), ZERO)))
    for key, col in cols.items():
        members = members_of[key]
        if col.origin == "prior":
            for _, c in members:
                c.shown = q2(c.exact)
            col.shown_total = sum((c.shown for _, c in members), ZERO)
            continue
        fixed = names.penny_fix({r.key: c.exact for r, c in members if c.exact != 0}, targets[key])
        for r, c in members:
            c.shown = fixed.get(r.key, Decimal("0.00"))
        col.shown_total = sum((c.shown for _, c in members), ZERO)
    # drop columns that ended up with no rows (e.g. a statement whose every line was zero and no row) - keep all
    bands = _bands(cols, inp)
    # ---------------------------------------------------------------- 9. per-row totals, FY split, statuses
    fy_set: set = set()
    roy_cols = [c for b in bands if b.kind == "ROYALTY" for c in b.cols]
    n_statements = len({c.key for c in roy_cols})
    for r in rows:
        r.royalty = sum((r.cells[c.key].shown for c in roy_cols if c.key in r.cells), ZERO)
        for b in bands:
            if b.kind == "PLATFORM":
                r.platform[b.key] = sum((r.cells[c.key].shown for c in b.cols if c.key in r.cells), ZERO)
        raw: dict = defaultdict(lambda: ZERO)
        for c in roy_cols:
            if c.key not in r.cells:
                continue
            w = names.fy_weights(c.period_start, c.period_end)
            if not w:
                raw["NA"] += r.cells[c.key].shown
            else:
                for y, f in w.items():
                    raw[y] += r.cells[c.key].shown * f
        r.fy = names.penny_fix(dict(raw), r.royalty) if raw else {}
        fy_set |= set(r.fy)
        _status(r, inp, base_label, has_base, n_statements, bands)
    fy_keys = sorted(k for k in fy_set if k != "NA") + (["NA"] if "NA" in fy_set else [])

    # ---------------------------------------------------------------- 10. order: SKV rule
    plat_keys = [b.key for b in bands if b.kind == "PLATFORM"]
    rows.sort(key=lambda r: (-r.royalty, *[-r.platform.get(k, ZERO) for k in plat_keys], title_key(r.title), r.key))

    # ---------------------------------------------------------------- 11. findings: paid but not in the base
    findings: list[Row] = []
    if has_base:
        marks_i, marks_w = _review_index(inp.reviews)
        base_rows = [r for r in rows if r.in_base]
        bt_exact: dict[str, list[Row]] = defaultdict(list)
        bt_close: dict[str, list[Row]] = defaultdict(list)
        for r in base_rows:
            bt_exact[title_key(r.title)].append(r)
            bt_close[base_title(r.title)].append(r)
            bt_close["f:" + fold(r.title)].append(r)
        cand_rows = [r for r in rows if not r.in_base and r.origin in ("work", "recording") and r.cells]
        paid_exact = Counter(title_key(r.title) for r in cand_rows)
        for r in cand_rows:
            r.review = next((marks_i[i] for i in r.all_isrcs if i in marks_i), None) or \
                       next((marks_w[w] for w in r.all_works if w in marks_w), None)
            r.proposals = _proposals(r, bt_exact, bt_close, paid_exact, not_same, rs, gap)
            if r.proposals and r.proposals[0]["band"] != "unlikely":
                r.flags.append(f"Possible match in {base_label}: '{r.proposals[0]['title']}'")
            findings.append(r)
        status_rank = {s_: i for i, s_ in enumerate([NEW, "NEEDS_CHECK", "IDENTIFIER_TO_UPDATE", "CONFIRMED_MISSING",
                                                     "ALREADY_IN_LIST", NOT_OURS])}
        findings.sort(key=lambda r: (status_rank.get(r.review.status if r.review else NEW, 0) > 1,
                                     -(r.royalty + sum(r.platform.values(), ZERO)), r.title.upper(), r.key))
        for r in findings:
            for p in r.proposals[:1]:
                if p["band"] == "unlikely":
                    continue
                issues.append(_issue("PROPOSAL", "REVIEW", "MATCHING", f"'{r.title}' may be '{p['title']}' in "
                                     f"{base_label}", p["why"],
                                     dict(row=r.key, title=r.title, isrcs=r.all_isrcs, work_nos=r.all_works,
                                          code_kind="ISRC" if r.origin == "recording" else "WORK",
                                          code=(r.all_isrcs or r.all_works or [""])[0],
                                          royalty=str(r.royalty), platform={k: str(v) for k, v in r.platform.items()},
                                          target=p), ["CONFIRM_MATCH", "KEEP_SEPARATE", "LATER"]))
        unreviewed = sum(1 for r in findings if (r.review.status if r.review else NEW) in UNRESOLVED)
        if unreviewed:
            issues.append(_issue("MISSING_UNREVIEWED", "REVIEW", "MATCHING",
                                 f"{unreviewed} paid songs are not in {base_label} and have not been reviewed",
                                 "Mark each one: not ours, confirmed missing, already in the list, or identifier "
                                 "to update. 'Not ours' songs go to the out-of-scope report.",
                                 dict(count=unreviewed), ["SET_STATUS"]))

    # ---------------------------------------------------------------- 12. checks (S9) and totals
    checks = _checks(inp, stmts, plats, rows, cols, bands, findings, has_base)
    totals = _totals(rows, bands, cols, findings)
    ok = all(c["ok"] for c in checks if c.get("blocking", True))
    return Result(rows=rows, bands=bands, fy_keys=fy_keys, base_label=base_label,
                  grain="one row per song-list entry" if inp.song_list and not inp.prior else
                  ("one row per previous-report row" if inp.prior else
                   ("one row per work" if stmts else "one row per recording")),
                  findings=findings, issues=issues, checks=checks, totals=totals, notices=notices, ok=ok,
                  statements=stmts, platforms=plats)


# ================================================================== pieces
def _norm_dist(v) -> str:
    v = (v or "").strip()
    return "" if v.lower() in ("", "not specified") else v.upper()


def _norm_period(v) -> str:
    a, b = names.parse_period_label(v)
    return f"{a}:{b}" if a else ""


def _not_already_in_base(inp: RunInput, cols: dict, issues: list, notices: list):
    """V3 §11.3: a new statement whose distribution is already a column of the previous report is skipped when the
    totals agree and held for a decision when they differ; platform months the same way."""
    prior_roy = [c for c in cols.values() if c.origin == "prior" and c.kind == "ROYALTY"]
    prior_plat = [c for c in cols.values() if c.origin == "prior" and c.kind == "PLATFORM"]
    gen = inp.prior.data.generation if inp.prior else ""
    stmts = []
    for st in inp.statements:
        hit = [c for c in prior_roy if c.band == st.section and _norm_dist(c.dist_no) == _norm_dist(st.dist_no)
               and _norm_period(c.period_label) == _norm_period(st.period_label)]
        if not hit:
            stmts.append(st)
            continue
        tot = q2(sum((ln.amount for ln in st.lines), ZERO))
        if any(q2(c.printed_total or ZERO) == tot for c in hit):
            notices.append(f"{st.label} ({st.section}, {st.dist_no or 'no distribution number'}, {st.period_label}) "
                           f"is already in {gen} with the same total; it was not added again.")
            continue
        if st.relation == "SUPPLEMENTARY":
            stmts.append(st)
            continue
        issues.append(_issue("ALREADY_IN_BASE", "BLOCKING", "MONEY",
                             f"{st.label} may already be in {gen} with a different total",
                             f"{gen} already has {st.section} {st.dist_no or ''} for {st.period_label} "
                             f"({_money(hit[0].printed_total or ZERO)}), but this file totals {_money(tot)}. It may "
                             "be a re-issue. It has been left out until you decide.",
                             dict(file_id=st.file_id, label=st.label, prior_total=str(hit[0].printed_total),
                                  total=str(tot), identity_key=st.identity_key),
                             ["ADD_AS_SEPARATE", "LEAVE_OUT"]))
    plats = []
    for pr in inp.platforms:
        months: dict = defaultdict(lambda: ZERO)
        for ln in pr.lines:
            if ln.amount is not None and ln.month:
                months[ln.month] += ln.amount
        same, differ = [], []
        for m, amt in months.items():
            hit = [c for c in prior_plat if c.month == m and (c.platform or "").lower() == pr.platform.lower()
                   and (c.distributor or "").lower() == pr.distributor.lower()]
            if hit:
                (same if any(q2(c.printed_total or ZERO) == q2(amt) for c in hit) else differ).append(m)
        if differ:
            issues.append(_issue("ALREADY_IN_BASE", "BLOCKING", "MONEY",
                                 f"{pr.label}: some months are already in {gen} with different totals",
                                 f"{', '.join(names.MONTH_LABEL[m.month] + ' ' + str(m.year) for m in sorted(differ))} "
                                 f"of {pr.platform} ({pr.distributor}) are already in {gen} with different amounts. "
                                 "The report has been left out until you decide.",
                                 dict(file_id=pr.file_id, label=pr.label), ["LEAVE_OUT"]))
            continue
        if same:
            notices.append(f"{pr.label}: {len(same)} month(s) already in {gen} with the same totals were not added "
                           "again.")
            keep = set(months) - set(same)
            pr = SrcPlatform(file_id=pr.file_id, label=pr.label, filename=pr.filename, platform=pr.platform,
                             distributor=pr.distributor, basis=pr.basis, currency=pr.currency,
                             lines=[ln for ln in pr.lines if ln.month in keep])
            if not keep:
                continue
        plats.append(pr)
    return stmts, plats


def _issue(kind, severity, category, title, message, subject, actions) -> dict:
    return dict(kind=kind, severity=severity, category=category, title=title, message=message, subject=subject,
                actions=actions)


def _money(v: Decimal) -> str:
    from .detect import money
    return money(v)


def _pband(platform: str, distributor: str, basis: str) -> str:
    return f"PLATFORM|{platform}|{distributor}|{basis}"


def _base_label(inp: RunInput) -> str:
    if inp.song_list:
        return f"{inp.client_code} list ({inp.song_list.label})"
    if inp.prior:
        return f"previous report ({inp.prior.data.generation})"
    return ""


def _find_row(t: dict, idx_work, idx_isrc, by_key) -> Row | None:
    if t.get("row_key") and t["row_key"] in by_key:
        return by_key[t["row_key"]]
    code = str(t.get("code") or "")
    if t.get("code_kind") == "WORK":
        hit = idx_work.get(code)
    else:
        hit = idx_isrc.get(code)
    if hit:
        return hit[0]
    title = t.get("title")
    for r in by_key.values():
        if title and r.title == title and r.in_base:
            return r
    return None


def _owner(w: str, cands: list[Row], titles: Counter, hint: dict) -> Row:
    if len(cands) == 1:
        return cands[0]
    if w in hint and hint[w] in cands:
        return hint[w]
    keys = {title_key(t) for t in titles}
    for r in cands:
        if title_key(r.title) in keys:
            return r
    bases = {base_title(t) for t in titles}
    for r in cands:
        if base_title(r.title) in bases:
            return r
    return min(cands, key=lambda r: r.order)


def _same_song(cands: list[Row]) -> bool:
    works = [set(r.all_works) for r in cands]
    if all(works) and set.intersection(*works):
        return True
    return len({base_title(r.title) for r in cands}) == 1


def _platform_row(isrc, idx_isrc, assigned, hold_shared, add_row, by_key, rows, lns, pr, issues, title) -> Row:
    cands = list(idx_isrc.get(isrc, []))
    if isrc in assigned:
        return assigned[isrc]
    if not cands:
        key = f"rec:{isrc}"
        return by_key.get(key) or add_row(Row(key=key, title=title, isrcs=[isrc], work_nos=[], origin="recording",
                                              in_base=False, order=len(rows)))
    if len(cands) == 1 or _same_song(cands) or not hold_shared:
        return min(cands, key=lambda r: r.order)
    key = f"hold:shared:{isrc}"
    r = by_key.get(key)
    if r is None:
        names_ = " / ".join(f"'{c.title}'" for c in cands[:4])
        r = add_row(Row(key=key, title=title or isrc, isrcs=[isrc], work_nos=[], origin="hold",
                        in_base=False, order=len(rows),
                        hold=f"SHARED RECORDING - claimed by {len(cands)} songs ({names_}) - needs decision"))
        r.hold_candidates = [c.key for c in cands]
        r.flags.append(r.hold)
        issues.append(_issue("SHARED_RECORDING", "REVIEW", "MONEY",
                             f"Platform money for ISRC {isrc} is claimed by {len(cands)} different songs",
                             f"The song list puts this recording under {names_}. Its money is held on its own row "
                             "(and still counted in every total) until you choose the song it belongs to.",
                             dict(row=key, code_kind="ISRC", code=isrc, title=lns[0].title,
                                  candidates=[dict(row_key=c.key, title=c.title, isrcs=c.all_isrcs,
                                                   work_nos=c.all_works) for c in cands]),
                             ["ASSIGN_HELD", "LATER"]))
    return r


def _basis_text(r: Row, isrc: str, pr: SrcPlatform) -> str:
    if r.origin == "hold":
        return "Held - needs decision"
    if getattr(r, "basis_note", None) and isrc in r.extra_isrcs:
        return r.basis_note
    if r.origin == "recording":
        return f"No match - song is only in {pr.platform}'s report"
    if r.origin == "usage":
        return "ISRC - usage report"
    if isrc in r.isrcs:
        if r.origin == "prior":
            return "ISRC - previous report"
        if r.origin == "work":
            return "ISRC - royalty statement work (not in the list)"
        return "ISRC - catalogue (primary ISRC of the recording)" if r.isrcs.index(isrc) == 0 else \
               "ISRC - catalogue (secondary ISRC of the recording)"
    return "ISRC - shared recording assigned by decision"


def _bands(cols: dict[str, Col], inp: RunInput) -> list[Band]:
    roy: dict[str, list[Col]] = defaultdict(list)
    plat: dict[str, list[Col]] = defaultdict(list)
    for c in cols.values():
        (roy if c.kind == "ROYALTY" else plat)[c.band].append(c)
    out: list[Band] = []
    overseas_i = 0
    plat_platforms = {k.split("|")[1].lower() for k in plat}
    sections = sorted(roy, key=section_rank)
    plat_bands = []
    for key in sorted(plat, key=lambda k: (k.split("|")[1], k.split("|")[2], k.split("|")[3])):
        cs = sorted(plat[key], key=lambda c: (c.month or dt.date.min, c.origin != "prior", c.key))
        _, platform, dist, basis = key.split("|")
        months = [c.month for c in cs if c.month]
        per = names.period_label(min(months), names.month_end_of(max(months))) if months else ""
        n = len(cs)
        label = f"{platform.upper()} - {'NET' if basis == 'NET' else 'GROSS'} REVENUE REPORTED BY {platform.upper()}" \
                f" ({dist} report)  ({per}, {n} month{'s' if n != 1 else ''})"
        plat_bands.append(Band(key=key, kind="PLATFORM", section=platform, label=label, fill=PLATFORM_FILL[0],
                               tint=PLATFORM_FILL[1], cols=cs, platform=platform, distributor=dist, basis=basis,
                               total_header=f"Total {platform} Revenue ({dist}{', net' if basis == 'NET' else ''})",
                               basis_header=f"{platform} ({dist}) Match Basis"))
    placed = False

    def put_platforms():
        nonlocal placed
        if not placed:
            out.extend(plat_bands)
            placed = True

    for sec in sections:
        if not placed and section_rank(sec) > section_rank(PLATFORM_AFTER):
            put_platforms()
        cs = sorted(roy[sec], key=lambda c: (c.date or dt.date.min, c.origin != "prior", c.label, c.key))
        n = len(cs)
        if sec in PALETTE:
            fill, tint = PALETTE[sec]
        else:
            fill, tint = OVERSEAS_CYCLE[overseas_i % len(OVERSEAS_CYCLE)]
            overseas_i += 1
        if sec.lower() in plat_platforms:
            pers = " and ".join(dict.fromkeys(c.period_label for c in cs))
            label = f"{sec.upper()} - ROYALTY DISTRIBUTED BY IPRS  ({n} distribution{'s' if n != 1 else ''}: {pers})"
        else:
            label = f"{sec.upper()}  ({n} distribution{'s' if n != 1 else ''})"
        out.append(Band(key=f"ROY|{sec}", kind="ROYALTY", section=sec, label=label, fill=fill, tint=tint, cols=cs))
        if sec == PLATFORM_AFTER:
            put_platforms()
    put_platforms()
    return out


def _status(r: Row, inp: RunInput, base_label: str, has_base: bool, n: int, bands: list[Band]) -> None:
    roy_cols = {c.key for b in bands if b.kind == "ROYALTY" for c in b.cols}
    roy = [r.cells[k] for k in r.cells if k in roy_cols and not r.cells[k].sibling]
    plat = [r.cells[k] for k in r.cells if k not in roy_cols]
    sib = any(c.sibling for c in r.cells.values())
    paid = any(c.exact != 0 for c in roy)
    named_zero = roy and all(c.named_zero or c.exact == 0 for c in roy)
    platforms = sorted({b.platform for b in bands if b.kind == "PLATFORM" and any(c.key in r.cells for c in b.cols)})
    if r.origin == "hold":
        text = f"Held - {r.hold}"
    elif r.in_base:
        lbl = f"In {base_label}"
        if paid:
            text = f"{lbl} - royalty received"
        elif named_zero:
            text = f"{lbl} - named in a statement, but the amount distributed was 0.00"
        elif sib:
            text = f"{lbl} - separate recording of an IPRS work paid on another row"
        elif plat:
            text = f"{lbl} - platform revenue only, no royalty distributed in any of the {n} statements"
        else:
            text = f"{lbl} - no royalty distributed in any of the {n} statements"
    elif has_base:
        lbl = f"NOT in {base_label}"
        if r.origin == "work":
            text = f"{lbl} - work paid by a royalty statement" if paid else \
                   f"{lbl} - named in a statement, but the amount distributed was 0.00"
        elif r.origin == "recording":
            text = f"{lbl} - appears only in {', '.join(platforms) or 'the platform'}'s revenue report"
        else:
            text = f"{lbl} - appears only in {r.usage_platform or 'a platform'}'s usage report (streams, but no " \
                   f"revenue and no royalty in this run)"
    else:
        text = {"work": "No base - work", "recording": "No base - recording", "usage": "No base - usage only"}.get(
            r.origin, "No base")
    if r.notes:
        text += "".join(f" ; {x}" for x in r.notes if x != "in list")
    r.status = text


def _review_index(marks: list[ReviewMark]) -> tuple[dict, dict]:
    by_i, by_w = {}, {}
    for m in marks:                                   # later marks win (marks are passed oldest first)
        for i in m.isrcs:
            by_i[i] = m
        for w in m.work_nos:
            by_w[w] = m
    return by_i, by_w


def _proposals(r: Row, bt_exact, bt_close, paid_exact, not_same, rs, gap) -> list[dict]:
    wts = {k: Decimal(v) for k, v in rs.get("proposal_weights", {}).items()}
    bands = rs.get("proposal_bands", {"suggested": "0.70", "review": "0.40"})
    tk = title_key(r.title)
    cands: dict[str, tuple[Row, str]] = {}
    for b in bt_exact.get(tk, []):
        cands[b.key] = (b, "exact")
    for b in bt_close.get(base_title(r.title), []) + bt_close.get("f:" + fold(r.title), []):
        cands.setdefault(b.key, (b, "close"))
    code = (r.all_isrcs or r.all_works or [""])[0]
    out = []
    for b, how in cands.values():
        anchor = (b.all_isrcs or b.all_works or [""])[0]
        if (code, anchor) in not_same or (code, b.key) in not_same:
            continue
        score = wts.get("exact_title", Decimal("0.30")) if how == "exact" else wts.get("close_title", Decimal("0.15"))
        why = ["the song titles are the same" if how == "exact" else "the song titles are very similar"]
        if how == "exact" and len(bt_exact.get(tk, [])) == 1 and paid_exact.get(tk, 0) == 1:
            score += wts.get("unique_both_sides", Decimal("0.20"))
            why.append("no other song has this title")
        fam = None
        for i in r.all_isrcs:
            for j in b.all_isrcs:
                fam = isrc_family(i, j, gap) or fam
        if fam == "family":
            score += wts.get("isrc_family", Decimal("0.15"))
            why.append("the ISRCs come from the same registrant and year")
        elif fam == "registrant":
            score += wts.get("isrc_registrant", Decimal("0.05"))
            why.append("the ISRCs come from the same registrant")
        if is_version(r.title) != is_version(b.title) or (base_title(r.title) == base_title(b.title)
                                                         and title_key(r.title) != title_key(b.title)
                                                         and how == "close"):
            score += wts.get("version_words_differ", Decimal("-0.50"))
            why.append("but one title looks like a different version (for example a cover or lo-fi)")
        band = "suggested" if score >= Decimal(bands["suggested"]) else (
            "review" if score >= Decimal(bands["review"]) else "unlikely")
        out.append(dict(row_key=b.key, title=b.title, isrcs=b.all_isrcs, work_nos=b.all_works, score=str(score),
                        band=band, how=how, why="; ".join(why).capitalize() + ". They have not been confirmed as the "
                        "same song.", code_kind="ISRC" if b.all_isrcs else "WORK", code=anchor))
    out.sort(key=lambda p: (-Decimal(p["score"]), p["title"], p["row_key"]))
    return out[:3]


def _checks(inp: RunInput, stmts: list[SrcStatement], plats: list[SrcPlatform], rows: list[Row],
            cols: dict[str, Col], bands: list[Band], findings: list[Row], has_base: bool) -> list[dict]:
    tol = Decimal(inp.ruleset.get("recon_tolerance", "0.05"))
    out = []

    def add(cid, ok, text, detail="", blocking=True):
        out.append(dict(id=cid, ok=bool(ok), text=text, detail=detail, blocking=blocking))

    bad = [st.label for st in stmts if st.printed_total is None or
           abs(sum((ln.amount for ln in st.lines), ZERO) - st.printed_total) > tol]
    add("I1", not bad, "every included statement: entries = printed total", ", ".join(bad))
    src_cols = [c for c in cols.values() if c.kind == "ROYALTY" and c.origin == "source"]
    placed = sum((c.exact_total for c in src_cols), ZERO)
    lines = sum((ln.amount for st in stmts for ln in st.lines), ZERO)
    add("I4", placed == lines, "all statement money is in the report, once",
        f"placed {placed} vs extracted {lines}")
    printed = sum((st.printed_total or ZERO for st in stmts), ZERO)
    add("I4b", abs(placed - printed) <= tol * max(1, len(stmts)),
        "report total = sum of the statements' printed totals", f"{placed} vs {printed}")
    for pr in plats:
        tot = sum((x.amount for x in pr.lines if x.amount is not None and x.month), ZERO)
        got = sum((c.exact_total for c in cols.values() if c.kind == "PLATFORM" and c.file_id == pr.file_id), ZERO)
        add("I5", tot == got, f"{pr.platform} ({pr.distributor}) revenue in the report = the report's own total",
            f"{got} vs {tot}")
    for c in cols.values():
        if c.origin == "source" and c.kind == "ROYALTY" and c.shown_total != q2(c.exact_total):
            add("I23", False, f"printed column {c.label} adds up", f"{c.shown_total} vs {q2(c.exact_total)}")
    for pr in plats:
        pc = [c for c in cols.values() if c.kind == "PLATFORM" and c.file_id == pr.file_id and c.origin == "source"]
        shown, exact = sum((c.shown_total for c in pc), ZERO), sum((c.exact_total for c in pc), ZERO)
        add("I23", shown == q2(exact), f"printed {pr.platform} months add up to the report's total",
            f"{shown} vs {q2(exact)}")
    fy_bad = [r.key for r in rows if r.fy and sum(r.fy.values(), ZERO) != r.royalty]
    add("I6", not fy_bad, "financial-year columns add up to each song's total", ", ".join(fy_bad[:5]))
    if inp.song_list and not inp.prior:
        n_list = sum(1 for r in rows if r.origin == "list")
        add("I7", n_list == len(inp.song_list.entries), "every song-list entry has exactly one row",
            f"{n_list} rows for {len(inp.song_list.entries)} entries")
    if has_base:
        base_codes = {i for r in rows if r.in_base for i in r.all_isrcs} | \
                     {w for r in rows if r.in_base for w in r.all_works}
        leak = [r.key for r in findings if any(i in base_codes for i in r.all_isrcs + r.all_works)]
        add("I16", not leak, "no song on the missing list carries a code that is in the base", ", ".join(leak[:5]))
    if inp.prior:
        po = inp.prior.data
        prior_roy = sum((c.exact_total for c in cols.values() if c.origin == "prior" and c.kind == "ROYALTY"), ZERO)
        add("I13", q2(prior_roy) == q2(sum((r.total for r in po.rows), ZERO)) or bool(po.integrity),
            "previous report money is carried unchanged", f"{prior_roy} vs {sum((r.total for r in po.rows), ZERO)}")
    return out


def _totals(rows: list[Row], bands: list[Band], cols: dict[str, Col], findings: list[Row]) -> dict:
    roy = sum((r.royalty for r in rows), ZERO)
    plat = {b.key: sum((r.platform.get(b.key, ZERO) for r in rows), ZERO) for b in bands if b.kind == "PLATFORM"}
    held_roy = sum((r.royalty for r in rows if r.origin == "hold"), ZERO)
    held_plat = sum((sum(r.platform.values(), ZERO) for r in rows if r.origin == "hold"), ZERO)
    return dict(royalty=roy, platform=plat, rows=len(rows), held_royalty=held_roy, held_platform=held_plat,
                held_rows=sum(1 for r in rows if r.origin == "hold"),
                distributions=sum(len(b.cols) for b in bands if b.kind == "ROYALTY"),
                platform_months=sum(len(b.cols) for b in bands if b.kind == "PLATFORM"),
                missing=len(findings),
                not_ours=sum(1 for r in findings if r.review and r.review.status == NOT_OURS),
                unreviewed=sum(1 for r in findings if (r.review.status if r.review else NEW) in UNRESOLVED),
                matched_rows=sum(1 for r in rows if r.in_base and r.cells))


def status_label(r: Row) -> str:
    return STATUS_LABEL[r.review.status] if r.review else STATUS_LABEL[NEW]
