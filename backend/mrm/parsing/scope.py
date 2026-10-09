"""Scope vocabulary: underlying platform, use type and publishing-right scope.

Sender, payer and underlying platform are separate fields (page 2): an IPRS statement is sent by IPRS, but its
SOURCE column names the platform whose usage it pays for.
"""
from __future__ import annotations

from ..normalize import s

PLATFORMS = [("spotify", "Spotify"), ("youtube", "YouTube"), ("facebook", "Meta"), ("instagram", "Meta"),
             ("meta", "Meta"), ("jiosaavn", "JioSaavn"), ("saavn", "JioSaavn"), ("gaana", "Gaana"),
             ("apple", "Apple Music"), ("itunes", "Apple Music"), ("amazon", "Amazon Music"), ("wynk", "Wynk"),
             ("hungama", "Hungama"), ("resso", "Resso"), ("netflix", "Netflix"), ("hotstar", "JioHotstar")]
STREAMING = {"Spotify", "JioSaavn", "Gaana", "Apple Music", "Amazon Music", "Wynk", "Hungama", "Resso"}
UGC = {"YouTube", "Meta"}
OTT = {"Netflix", "JioHotstar"}
USE_TYPES = ("AUDIO_STREAMING", "UGC_VIDEO", "OTT", "RADIO", "TV", "OTHER")
RIGHT_SCOPES = ("PERFORMING", "MECHANICAL")


def platform_of(text) -> str | None:
    t = s(text).lower().replace(" ", "")
    if not t:
        return None
    for key, name in PLATFORMS:
        if key in t:
            return name
    return s(text).title()


def use_type_of(pool=None, source=None, content_type=None) -> str | None:
    p = platform_of(source) if source else None
    pool_u, ct = s(pool).upper(), s(content_type).lower()
    if "RADIO" in pool_u:
        return "RADIO"
    if pool_u in ("TV", "TELEVISION") or "BROADCAST" in pool_u:
        return "TV"
    if p in STREAMING or "music" in ct or "audio" in ct or "stream" in ct:
        return "AUDIO_STREAMING"
    if p in UGC or "video" in ct or "ugc" in ct:
        return "UGC_VIDEO"
    if p in OTT:
        return "OTT"
    return None if not (pool_u or ct) else "OTHER"


def right_scope_of(pool) -> str:
    u = s(pool).upper()
    if "MECH" in u:
        return "MECHANICAL"
    if u:
        return "PERFORMING"
    return "UNKNOWN"
