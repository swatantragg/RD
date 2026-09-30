"""§12.1-12.2 merge candidates: group rows by name, keep groups whose identifiers disagree,
score each group from evidence the platform already holds. The score is advisory - it
orders the queue and sets the default tick - and every component is shown."""
from __future__ import annotations

from collections import defaultdict

from ..core import config, db
from ..domain.link import registrant
from ..domain.normalize import norm

KINDS = ("SAME_NAME_DIFF_ISRC", "SAME_NAME_DIFF_INTERNAL_NO", "SAME_NAME_NO_IDENTIFIER", "VERSION_VARIANT")
SIGNALS = {
    "name": (+0.30, "identical norm(name)"),
    "album": (+0.25, "same album name / UPC in the platform report"),
    "work": (+0.20, "same IPRS work number on one side and no conflicting number on the other"),
    "prefix": (+0.10, "ISRC registrant prefix identical"),
    "disjoint": (+0.10, "revenue periods disjoint (looks like a re-registration)"),
    "separate": (-0.40, "identifiers registered in the sheet as separate entries"),
    "version": (-0.50, "version words differ (Male / Female, Cover, Lofi ...)"),
}


def band(conf: float) -> str:
    if conf >= config.MERGE_SUGGEST_THRESHOLD:
        return "suggested"
    if conf >= config.MERGE_REVIEW_THRESHOLD:
        return "review"
    return "unlikely"


def _row_facts(conn, build_id: int) -> tuple[list[dict], dict]:
    rows = db.rows(conn, "SELECT id, row_key, name, name_key, name_key2, origin, catalogue_entry_id, "
                         "total_amount, total_mrm, ordinal, status_code FROM rd_row WHERE build_id = ?", (build_id,))
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r.update(isrcs=[], works=[], registered_isrcs=[], registered_works=[], albums=set(), upcs=set(),
                 months=set())
    q = "SELECT x.* FROM {t} x JOIN rd_row r ON r.id = x.row_id WHERE r.build_id = ? ORDER BY x.row_id{o}"
    for x in conn.execute(q.format(t="rd_row_isrc", o=", x.ordinal"), (build_id,)):
        r = by_id[x["row_id"]]
        r["isrcs"].append(x["isrc"])
        if x["registered"]:
            r["registered_isrcs"].append(x["isrc"])
    for x in conn.execute(q.format(t="rd_row_work", o=", x.ordinal"), (build_id,)):
        r = by_id[x["row_id"]]
        r["works"].append(x["work_no"])
        if x["registered"]:
            r["registered_works"].append(x["work_no"])
    for x in conn.execute(q.format(t="rd_row_mrm", o=""), (build_id,)):
        if x["amount"]:
            by_id[x["row_id"]]["months"].add(x["month"])
    # album / UPC signal (L6): every platform line of the build's reports, by ISRC
    isrc_rows = defaultdict(list)
    for r in rows:
        for i in r["isrcs"]:
            isrc_rows[i].append(r)
    for x in conn.execute("SELECT DISTINCT pl.isrc, pl.album, pl.upc FROM platform_line pl JOIN build_report br "
                          "ON br.report_id = pl.report_id WHERE br.build_id = ?", (build_id,)):
        for r in isrc_rows.get(x["isrc"], []):
            if x["album"]:
                r["albums"].add(norm(x["album"]))
            if x["upc"]:
                r["upcs"].add(x["upc"])
    return rows, by_id


def classify(members: list[dict]) -> str:
    w_rows = [m for m in members if m["works"]]
    i_rows = [m for m in members if m["isrcs"]]
    if len(w_rows) >= 2 and len({frozenset(m["works"]) for m in w_rows}) > 1:
        return "SAME_NAME_DIFF_INTERNAL_NO"
    if len(i_rows) >= 2 and len({frozenset(m["isrcs"]) for m in i_rows}) > 1:
        return "SAME_NAME_DIFF_ISRC"
    return "SAME_NAME_NO_IDENTIFIER"


def score(kind: str, members: list[dict]) -> tuple[float, list[dict]]:
    hit = []
    if kind != "VERSION_VARIANT":
        hit.append("name")
    albums = defaultdict(int)
    for m in members:
        for a in m["albums"] | {f"upc:{u}" for u in m["upcs"]}:
            albums[a] += 1
    if any(c >= 2 for c in albums.values()):
        hit.append("album")
    works = {w for m in members for w in m["works"]}
    if len(works) == 1:
        hit.append("work")
    prim = [m["isrcs"][0] for m in members if m["isrcs"]]
    if len(prim) >= 2 and len({registrant(i) for i in prim}) == 1:
        hit.append("prefix")
    earners = [m["months"] for m in members if m["months"]]
    if len(earners) >= 2 and all(not (a & b) for i, a in enumerate(earners) for b in earners[i + 1:]):
        hit.append("disjoint")
    cat = [m for m in members if m["origin"] == "catalogue"]
    if len({m["catalogue_entry_id"] for m in cat}) >= 2 and len(
            {(frozenset(m["registered_works"]), frozenset(m["registered_isrcs"])) for m in cat}) >= 2:
        hit.append("separate")
    if kind == "VERSION_VARIANT":
        hit.append("version")
    conf = max(0.0, min(1.0, round(sum(SIGNALS[h][0] for h in hit), 3)))
    return conf, [dict(code=h, weight=SIGNALS[h][0], label=SIGNALS[h][1]) for h in hit]


def default_survivor(members: list[dict]) -> dict:
    """The sheet-registered row first, then the largest Total Amount (§12.3)."""
    return sorted(members, key=lambda m: (0 if m["origin"] == "catalogue" else 1, -m["total_amount"],
                                          -m["total_mrm"], m["ordinal"]))[0]


def generate_candidates(conn, build_id: int) -> dict:
    rows, _ = _row_facts(conn, build_id)
    root = db.scalar(conn, "SELECT root_build_id FROM build_run WHERE id = ?", (build_id,)) or build_id
    rejected = {(d["kind"], d["name_key"]) for d in db.rows(
        conn, "SELECT kind, name_key FROM merge_decision WHERE root_build_id = ? AND active = 1 AND "
              "verdict = 'NOT_THE_SAME'", (root,))}
    exact, fuzzy = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["name_key"]:
            exact[r["name_key"]].append(r)
        if r["name_key2"]:
            fuzzy[r["name_key2"]].append(r)
    cands = []
    for key, members in exact.items():
        if len(members) < 2:
            continue
        if len({(frozenset(m["isrcs"]), frozenset(m["works"])) for m in members}) < 2:
            continue                                  # identical identifiers - nothing to decide
        kind = classify(members)
        cands.append((kind, key, members))
    for key2, members in fuzzy.items():
        if len({m["name_key"] for m in members}) >= 2:
            cands.append(("VERSION_VARIANT", key2, members))
    with db.tx(conn):
        conn.execute("DELETE FROM merge_candidate WHERE build_id = ?", (build_id,))
        stats = defaultdict(int)
        for kind, key, members in cands:
            conf, signals = score(kind, members)
            surv = default_survivor(members)
            status = "not_same" if (kind, key) in rejected else "open"
            cid = db.insert(conn, "merge_candidate", dict(
                build_id=build_id, kind=kind, name_key=key, display_name=surv["name"], confidence=conf,
                band=band(conf), signals_json=db.dumps(signals), default_survivor=surv["id"], status=status))
            conn.executemany("INSERT INTO merge_candidate_member(candidate_id, rd_row_id) VALUES (?,?)",
                             [(cid, m["id"]) for m in members])
            stats[kind] += 1
            stats[f"band:{band(conf)}"] += 1
    exact_groups = [c for c in cands if c[0] != "VERSION_VARIANT"]
    return dict(groups=len(exact_groups), rows=sum(len(c[2]) for c in exact_groups),
                version_variants=len(cands) - len(exact_groups), **stats)
