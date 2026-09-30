"""The identity link ladder (architecture §8) - the ONLY place identity is decided.

    L1  same internal number                                   certain    money may attach
    L2  same ISRC                                              certain    money may attach
    L3  missing identifier recovered through an exact norm(name) match that is UNIQUE on
        both sides, and the recovered identifier then matches L1/L2   strong  stamped
    L4  exact norm(name) match, identifiers known on both sides and different - candidate only
    L5  norm2(name) match (version words stripped)             weak candidate
    L6  album / UPC / period / registrant prefix agreement      corroborating signal only

L4 and L5 never move money on their own; they feed the merge review (§12).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable, TypeVar

from .normalize import norm, norm2

T = TypeVar("T")

RUNGS = {
    "L1": "same internal number",
    "L2": "same ISRC",
    "L3": "identifier recovered through a unique exact title match",
    "L4": "same title, different identifiers (candidate)",
    "L5": "same title once version words are stripped (weak candidate)",
    "L6": "album / UPC / period / registrant agreement (signal only)",
}


class NameIndex:
    """norm(name) -> records, remembering how many records carry each key."""

    def __init__(self, records: Iterable[T], name_of: Callable[[T], str], fuzzy: bool = False):
        self.key = norm2 if fuzzy else norm
        self.by_key: dict[str, list[T]] = defaultdict(list)
        for r in records:
            k = self.key(name_of(r))
            if k:
                self.by_key[k].append(r)

    def get(self, name: str) -> list[T]:
        return self.by_key.get(self.key(name), [])

    def unique(self, name: str) -> T | None:
        hits = self.get(name)
        return hits[0] if len(hits) == 1 else None

    def __contains__(self, name: str) -> bool:
        return bool(self.get(name))


def l3_recover(name: str, this_side: NameIndex, other_side: NameIndex):
    """L3: an exact title match that is unique on BOTH sides, or None.

    `AAJ JYOTSNA RAATEY` is two different works with the same title - a non-unique title
    match would have merged them (defect D6), so uniqueness is required on both sides."""
    if len(this_side.get(name)) != 1:
        return None
    return other_side.unique(name)


def registrant(isrc: str) -> str:
    """ISRC registrant prefix (country + registrant code, first 5 characters)."""
    return isrc[:5]
