"""Rule set v1: everything that can change a number or a classification, in one versioned, hashable place.

A build records the rule set it used (version + sha256). Changing any value here is a new version.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

RULESET_V1: dict = {
    "version": 1,
    "recon_tolerance": "0.05",            # per file: lines = sub-totals = printed total (Architecture V3 §9.5)
    "name_link_policy": "suggest",        # a title never moves money without an approved decision (V3 §6.5)
    "title_similarity": "0.90",
    "isrc_family_gap": 50,
    "hold_shared_recordings": True,       # Q6 default: a recording claimed by two different songs waits for a person
    "companion_combined_total": True,     # Q1 (2026-10-09): keep "Total (Both Sources)" in the companion reports
    "fy_view": "EARNED",                  # FY of the period the royalty was earned in (as SKV8)
    "proposal_weights": {
        "exact_title": "0.30", "close_title": "0.15", "unique_both_sides": "0.20",
        "isrc_family": "0.15", "isrc_registrant": "0.05", "version_words_differ": "-0.50",
    },
    "proposal_bands": {"suggested": "0.70", "review": "0.40"},
}


def ruleset_sha(rs: dict) -> str:
    return hashlib.sha256(json.dumps(rs, sort_keys=True).encode()).hexdigest()


def tolerance(rs: dict) -> Decimal:
    return Decimal(rs["recon_tolerance"])


# ------------------------------------------------------------------ review statuses for paid-but-not-in-list songs
NEW = "NEW"
NEEDS_CHECK = "NEEDS_CHECK"
IDENTIFIER_TO_UPDATE = "IDENTIFIER_TO_UPDATE"
CONFIRMED_MISSING = "CONFIRMED_MISSING"
ALREADY_IN_LIST = "ALREADY_IN_LIST"
NOT_OURS = "NOT_OURS"

STATUS_LABEL = {
    NEW: "Not reviewed yet",
    NEEDS_CHECK: "Needs check",
    IDENTIFIER_TO_UPDATE: "In song list - identifier to update",
    CONFIRMED_MISSING: "Confirmed missing - to register",
    ALREADY_IN_LIST: "Already in song list",
    NOT_OURS: "Not ours (belongs to someone else)",
}
STATUS_ORDER = [NEW, NEEDS_CHECK, IDENTIFIER_TO_UPDATE, CONFIRMED_MISSING, ALREADY_IN_LIST, NOT_OURS]
UNRESOLVED = (NEW, NEEDS_CHECK)


def map_status(text: str | None) -> str | None:
    """A reviewer's free-text status -> one standard status (Q5 default mapping; the original text is always kept).

    'Not SVF work' -> NOT_OURS · 'already linked', 'Updated in SVF Report' -> ALREADY_IN_LIST ·
    'need to update ISRC', '... ISRC to update', 'Need to update song in report' -> IDENTIFIER_TO_UPDATE ·
    'Need to register', 'Need Hangover Songs', 'Ask for all ... songs' -> CONFIRMED_MISSING ·
    'Please confirm if ...' and anything unrecognised -> NEEDS_CHECK.  Blank -> None.
    """
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not t or t.startswith(("not reviewed", "unreviewed", "to be reviewed", "pending review")):
        return None
    if "please confirm" in t or "confirm if" in t or t.startswith("check") or "to be checked" in t:
        return NEEDS_CHECK
    if re.match(r"^not\b", t) or "not our" in t or "belongs to someone else" in t:
        return NOT_OURS
    if "already linked" in t or "already in" in t or t.startswith("updated in") or "already updated" in t:
        return ALREADY_IN_LIST
    if "to update" in t or "update isrc" in t or "update the isrc" in t:
        return IDENTIFIER_TO_UPDATE
    if "register" in t or "ask for" in t or re.match(r"^need\b.*\bsongs?\b", t) or "missing" in t:
        return CONFIRMED_MISSING
    return NEEDS_CHECK


def status_is_recognised(text: str | None) -> bool:
    t = (text or "").strip().lower()
    return bool(t) and (map_status(text) != NEEDS_CHECK or "confirm" in t or "check" in t)


# ------------------------------------------------------------------ sections (row 1 bands of the SKV layout)
SECTION_ORDER = ["YouTube Pre-Claims", "YouTube Post-Claims", "Facebook / Meta", "Spotify", "Apple Music", "Radio",
                 "Zee TV Broadcast", "Mechanical (MUSERK)", "Mechanical", "Other / Unclassified", "Redistribution"]
PLATFORM_AFTER = "Spotify"                # platform-report bands follow the Spotify statement band (V3 §13.1)

OVERSEAS_SOCIETIES = {"008": ("APRA", "Australia"), "021": ("BMI", "USA"), "023": ("BUMA", "Netherlands"),
                      "026": ("CASH", "Hong Kong"), "058": ("SACEM", "France"), "080": ("SUISA", "Switzerland"),
                      "101": ("SOCAN", "Canada"), "104": ("MACP", "Malaysia"), "106": ("COMPASS", "Singapore"),
                      "126": ("MCT", "Thailand"), "128": ("IMRO", "Ireland")}

# measured SKV colour system: band fill, row tint
PALETTE = {
    "Spotify": ("BFD9BF", "E8F2E8"), "Apple Music": ("E0B4B4", "F7E7E7"),
    "YouTube Pre-Claims": ("E7C3D8", "F9E9F2"), "YouTube Post-Claims": ("CBC1E0", "EEEAF7"),
    "Facebook / Meta": ("B7CBE4", "E6EDF7"), "Radio": ("E6CBA6", "F9F0E2"),
    "Zee TV Broadcast": ("ADCECA", "E6F1EF"), "Mechanical (MUSERK)": ("DAD7A0", "F3F2DF"),
    "Mechanical": ("DAD7A0", "F3F2DF"), "Other / Unclassified": ("CFCFCF", "EFEFEF"),
    "Redistribution": ("D5BFA7", "F2E9DE"),
}
PLATFORM_FILL = ("B7CBE4", "E6EDF7")
OVERSEAS_CYCLE = [("B9C4D6", "E9EDF4"), ("C2CFB8", "ECF1E8"), ("DCC0C0", "F5EAEA"), ("C9C2D9", "EFECF5"),
                  ("DBCEB1", "F5F0E5"), ("B3CDD1", "E7F0F2"), ("D2BFCE", "F2E9F0"), ("C9CDA8", "F0F1E3")]
FY_FILLS = ["E8F2E8", "E6EDF7", "F9E9F2", "F5F0E5", "EEEAF7", "E7F0F2"]


def section_rank(section: str) -> tuple:
    if section in SECTION_ORDER:
        return (0, SECTION_ORDER.index(section), "")
    if section.startswith("Overseas"):
        return (2, 0, section.lower())
    return (1, 0, section.lower())


def is_known_section(section: str | None) -> bool:
    return bool(section) and (section in SECTION_ORDER or section.startswith("Overseas"))
