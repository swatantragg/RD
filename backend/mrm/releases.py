"""Release notes shown once to each person after an update (newest first). The first entry is the running version."""
from __future__ import annotations

from . import __version__

RELEASES: list[dict] = [
    dict(version="1.0.4", date="10 Oct 2026",
         summary="Draft reports can be deleted, so you can start again with the same files, and every drop-down is new.",
         points=["Past Reports → Delete (or Delete run on the run page) removes a run that was never published, with "
                 "its draft reports. Published reports are kept for good.",
                 "Start again: upload the same files to a new run; the stored copies are reused, nothing is counted "
                 "twice.",
                 "Drop-down lists now open in the app's own style, light or dark, with a tick on the current choice "
                 "and keyboard support (arrows, Enter, Esc, first letters).",
                 "Expandable sections are shown as panels with a turning arrow."]),
    dict(version="1.0.3", date="9 Oct 2026",
         summary="Clients and people are now edited in small pop-up windows, and the drop-down menus got a cleaner look.",
         points=["Edit a client: Clients → Edit opens a pop-up with all its details; empty rows can be removed with ×.",
                 "People: Settings → People and access → Edit opens a pop-up for role and client access; accounts "
                 "without recorded work can be deleted.",
                 "Change password now asks you to type the new password twice.",
                 "Restyled drop-down lists and expandable sections, in both light and dark theme."]),
    dict(version="1.0.2", date="9 Oct 2026",
         summary="You can now add your own clients, and your profile menu sits behind your initials.",
         points=["Add a client: Clients → Add a client, or from the first step of a new run. SVF stays as it is.",
                 "Profile button: click your initials (top right) for your profile, role, theme and sign out.",
                 "My profile: change your name or password under Settings → My profile.",
                 "What's new: after each update a short note like this one appears once."]),
    dict(version="1.0.1", date="9 Oct 2026",
         summary="Your own accounts, a dark theme and a roomier layout.",
         points=["Create your own account on the sign-in page; the first account becomes the administrator.",
                 "New accounts follow everyone's work and download published reports, saved with their own name.",
                 "Shared sign-ins and bundled example files were removed.",
                 "Light and dark theme, full-width pages and larger text."]),
    dict(version="1.0.0", date="9 Oct 2026",
         summary="First release: statements in, checked master reports out.",
         points=["Upload, check, process, review and download the master, Missing Songs and out-of-scope reports."]),
]


def _key(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def unseen(seen: str | None) -> list[dict]:
    """Notes the person has not seen yet. Someone who never saw a note gets only the current one."""
    if seen == __version__:
        return []
    if not seen:
        return [r for r in RELEASES if r["version"] == __version__]
    return [r for r in RELEASES if _key(seen) < _key(r["version"]) <= _key(__version__)]
