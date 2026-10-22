"""Release notes shown once to each person after an update (newest first). The first entry is the running version."""
from __future__ import annotations

from . import __version__

RELEASES: list[dict] = [
    dict(version="1.5.4", date="22 Oct 2026",
         summary="The check section shows the revenue the expected royalty is taken of, and Internal No, song name "
                 "and ISRC stay in view in the wide tables.",
         points=["Reconciliation and its Excel report (and a query's attachment): the 'Check: expected vs paid' "
                 "section starts with the song's total revenue, then the expected value (4 % of it), what IPRS paid, "
                 "% paid and the variance - e.g. revenue Rs. 100.00, expected Rs. 4.00, IPRS paid Rs. 2.00, variance "
                 "Rs. 2.00 (50 %). With a client interest set, the column shows the revenue counted at that interest.",
                 "Internal No, Song name and ISRC stay in place while scrolling sideways: in the reconciliation, the "
                 "master sheet, Works by platform (now with its own Internal No column and the ISRCs themselves) and "
                 "in the Excel reconciliation report and query attachment.",
                 "Number fields take numbers only: the benchmark %, a platform's own %, the client interest % "
                 "(Settings → Reconciliation) and the amounts and statement number in the reconciliation and enquiry "
                 "dialogs drop letters and signs as they are typed; the server refuses anything else (e.g. '4a', "
                 "'1e2', 'NaN', '-4') with a clear message."]),
    dict(version="1.5.3", date="22 Oct 2026",
         summary="The master sheet can be sorted, shows a platform's revenue total only for that platform, and an "
                 "older query draft can be written again without its song list.",
         points=["Master sheet: a Sort choice - Total amount high → low or low → high, Song name A → Z or Z → A, and, "
                 "with a platform chosen, that platform's revenue high → low or low → high. Clicking the Song Name, "
                 "Total Amount or Total <platform> Revenue heading sorts too; a second click turns the order round.",
                 "Master sheet: with All platforms only the Total Amount is shown next to the song. With one platform "
                 "chosen, its Total <platform> Revenue (from its revenue reports, e.g. Total Spotify Revenue) is shown "
                 "next to it; when that platform has no revenue report yet, a note says so.",
                 "Works by platform: song title Z → A and platform revenue low → high join the Sort choices.",
                 "Query to IPRS: a draft written before 1.5.2 still listed every song in the text ('A. Works for which "
                 "we could not find an entry …', 'B. …'). The songs are in the attachment, so the page now offers "
                 "'Rebuild the text', which writes the letter again with only the number of songs and the questions.",
                 "Enquiry page: the long Items table (every song of the enquiry) is gone; the songs are in the "
                 "attachment, downloaded with 'Download attachment'."]),
    dict(version="1.5.2", date="21 Oct 2026",
         summary="Statements are listed by upload batch, the song report has a clearer layout, and a query to IPRS "
                 "carries that report as its attachment.",
         points=["Statements: each tab lists its upload batches instead of every file - for example 'Batch 1 · Spotify "
                 "· Oct 2025 - Mar 2026' under Platform reports, or 'Batch 1 · Apr 2022 - Mar 2026' under Client "
                 "statements (many platforms). Click a batch to see all its files; each opens its statement.",
                 "Reconciliation, on screen and in Excel: Internal No, song name and ISRC; then a section for the "
                 "platform (e.g. Spotify) and one for the IPRS royalty, with per statement the Amount, Date, Period "
                 "(the period and the usage in it) and Distribution number; then the check - expected value (4 % of "
                 "the revenue), IPRS paid, % paid, variance % and variance amount.",
                 "Query to IPRS: the letter no longer lists the songs. It refers to the attached list of the songs used "
                 "on the platform in the period, says what was found, and asks IPRS for clarification. The attachment "
                 "(the song report in the layout above) is downloaded from the enquiry with 'Download attachment'.",
                 "Pages are shorter: the explanatory sentences under the page and section titles are gone."]),
    dict(version="1.5.1", date="21 Oct 2026",
         summary="Catalogues in more shapes are read, the imported songs open straight in the catalogue, and the "
                 "Super Admin can delete the catalogue to start fresh.",
         points=["Import catalogue reads the client's song list in its usual shapes: the song (track) name; the IPRS "
                 "work number as 'Internal No', 'Work No', 'IPRS Song Code 1', 'Work Code' …; the ISRCs in one cell or "
                 "spread over columns 'ISRC 1' … 'ISRC 16'; the heading row anywhere in the first rows; every sheet with "
                 "such a table. For example 'SVF Song list 19-10-2026': 2,791 songs, 2,550 work numbers, 4,347 ISRCs.",
                 "The album / film column and a language column are kept: they show in the catalogue, can be "
                 "searched, are filled in for existing works that had none, and are in the catalogue export.",
                 "After 'Apply', the catalogue opens with exactly the songs of that import ('Show every work' returns "
                 "to the whole catalogue).",
                 "Catalogue → Delete catalogue (Super Admin only): removes the works, ISRC links and their history, the "
                 "catalogue imports and the uploaded song lists - and the reconciliations and enquiries built on them. "
                 "The statements are kept and find the new catalogue's works as soon as it is imported. The client "
                 "code is typed to confirm, and the activity log records it."]),
    dict(version="1.5.0", date="21 Oct 2026",
         summary="Three kinds of statement, one tab each, and a reconciliation that checks each song's IPRS payment "
                 "against 4 % of its platform revenue - with the usage beside it and a query to IPRS for the "
                 "underpaid songs.",
         points=["Statements has three tabs: Platform reports (the platform's revenue and usage per ISRC and month), "
                 "Client statements (the client's statements per platform, in bulk) and IPRS statements (what IPRS "
                 "paid). Each tab takes only its own kind of file and says where a file belongs if it is put in the "
                 "wrong one.",
                 "Revenue and usage that come in two files (for example the MRM Spotify revenue report and the Spotify "
                 "usage report) are combined by ISRC and song name, month by month. 'Revenue and usage, combined' shows "
                 "every song with its revenue, its plays and the months each covers, and exports them.",
                 "Reconciliation, work by work for a platform and period: the platform revenue and plays, the expected "
                 "royalty (4 % of the revenue; the whole revenue counts while no client interest is set), the client's "
                 "statement and what IPRS paid, with the % IPRS paid and the shortfall. For example Aaj Amaye on "
                 "Spotify, Oct 2025 - Mar 2026: revenue Rs. 9,633.50, expected Rs. 385.34, IPRS paid Rs. 119.23 "
                 "(1.24 %), Rs. 266.11 underpaid.",
                 "Underpaid works are flagged ('Underpaid by IPRS') and counted with their total shortfall; a work whose "
                 "client statement differs from what IPRS paid is flagged too. 'Raise a query to IPRS' prepares one "
                 "draft letter for every such work, asking why it was underpaid in that period, with the revenue, plays, "
                 "amount paid, % paid and expected amount of each.",
                 "Master: every work with its platform revenue, usage (plays), client statements and what IPRS paid, "
                 "for any period, on screen and in the export.",
                 "The Excel reconciliation report has the same columns: platform revenue and plays month by month, the "
                 "client statement, IPRS paid, expected, % paid, shortfall and 'Underpaid?'."]),
    dict(version="1.4.4", date="21 Oct 2026",
         summary="Tick every matching reconciliation item at once, exception counts that go down as you review, a "
                 "Super Admin button to delete all statements and start fresh, and the reconciliation page reordered.",
         points=["Statements (Super Admin only): 'Delete all statements' removes every uploaded statement of the client, "
                 "with its reconciliations, enquiries and processing runs, so everyone can start fresh. The catalogue, "
                 "the settings, the platforms and the people are kept; you type the client code to confirm, and the "
                 "activity log records it.",
                 "Reviewing: marking the last items of a filtered list (for example 'Not reviewed') no longer leaves an "
                 "empty page - the list goes back to the items still shown. 'Items reviewed' counts only reviewed items "
                 "and names those that need information; Earlier reconciliations shows how far each run's review has "
                 "got, with '✓ Reviewed' once every item is.",
                 "Reconciliation: 'Run a reconciliation' and 'Earlier reconciliations' come first; the platforms in the "
                 "client's statements are below them.",
                 "After ticking a page, 'Tick all N items that match' ticks every item on every page that matches the "
                 "filters; Mark reviewed, Needs information, Mark not reviewed and the enquiry draft then apply to all of "
                 "them.",
                 "The exception tiles (No IPRS entry, Work not in catalogue, Work needs review …) count the items still to "
                 "review; reviewed items move to '… reviewed', and a finished tile shows 0 with a tick."]),
    dict(version="1.4.3", date="19 Oct 2026",
         summary="Review many reconciliation items at once, clear every filter with one click, and a home page that "
                 "starts with what is waiting for you.",
         points=["Reconciliation run: every item has a tick box (the box in the heading ticks the whole page). For the "
                 "ticked items: Mark reviewed, Needs information (with a note), Mark not reviewed, or Prepare an "
                 "enquiry draft from those that qualify. The calculated figures never change.",
                 "'Clear filters' next to every list's filters puts them back to their starting values.",
                 "Home: Enquiries waiting and My follow-ups come first, then the catalogue and the reconciliations; the "
                 "statements are at the bottom."]),
    dict(version="1.4.2", date="19 Oct 2026",
         summary="The final colours: forest and leaf green with lime on ink black, and a clearer selected tab.",
         points=["Light theme: a white title bar and pages, forest-green buttons and links, leaf-green markers.",
                 "Dark theme: an ink-black title bar and panels, leaf-green buttons and lime links.",
                 "The selected tab - in the title bar and on every page - is shown by its text colour (dark green in "
                 "the light theme, lime in the dark theme) and a green underline; nothing else on the page changes.",
                 "The logo, the reconciliation bands and the Excel headers use the same colours."]),
    dict(version="1.4.1", date="19 Oct 2026",
         summary="New colours: charcoal, deep teal and aqua, in the light and the dark theme.",
         points=["Light theme: a charcoal title bar, deep teal buttons and links on white.",
                 "Dark theme: charcoal and graphite panels with aqua buttons and links.",
                 "The logo, the reconciliation bands and the Excel headers use the same colours."]),
    dict(version="1.4.0", date="19 Oct 2026",
         summary="The reconciliation is laid out like the master - source revenue and IPRS royalty period by period - "
                 "and the application has new colours and a new logo.",
         points=["Reconciliation run: a band row with the platform, 'Source revenue (from SVF)' and 'IPRS royalty', each "
                 "with one column per usage period (a month for a per-ISRC report, the statement's period for a "
                 "per-work statement) and a total; the calculation, year-before and review columns follow. The song "
                 "column stays in view while you scroll sideways.",
                 "The Excel report's first sheet has the same layout as the master workbook: bands, two header rows, "
                 "the song title frozen, a TOTAL row, and every earlier column kept.",
                 "New colours (deep indigo and electric blue) in the light and the dark theme, a navy title bar and a new "
                 "logo: two overlapping circles - the client's statements and IPRS's - and what they agree on."]),
    dict(version="1.3.0", date="19 Oct 2026",
         summary="'Received from' now decides the side of a statement in a reconciliation, every IPRS category can be "
                 "reconciled, and a whole financial year can be compared with the year before.",
         points=["Statements: a file from the client is the source revenue, also when it is in the IPRS layout; a file "
                 "received from IPRS is the IPRS royalty it is compared with. The list shows each statement's side; "
                 "the same file can be uploaded once for each side.",
                 "Nothing joins the statement library by itself any more: a statement is in it only when it is uploaded "
                 "under Statements with who sent it.",
                 "Every category in a statement is its own platform (Radio, Zee TV Broadcast, Overseas - SACEM …, Other "
                 "/ Unclassified), so all of them appear in the reconciliation drop-down. An 'Other / Unclassified' "
                 "statement is no longer counted as Apple Music.",
                 "Reconciliation → Compare 'A financial year': the months both sides cover in the year are compared, the "
                 "other months are named, and the same months a year earlier are shown beside each work with the "
                 "change in per cent.",
                 "One side never adds a per-ISRC revenue report and a per-work statement for the same months.",
                 "Master: the sheet shows the client's statements or the statements received from IPRS; the works view "
                 "keeps the two sides apart."]),
    dict(version="1.2.0", date="19 Oct 2026",
         summary="Choose the client on every work page, a per-platform reference benchmark, the master sheet on screen "
                 "in the SKV layout, and wide tables that scroll from the top or by dragging.",
         points=["Catalogue → Add a work: typing an IPRS work number suggests the works already in the catalogue. Pick "
                 "one to link the ISRCs to it (the song title is filled in), or keep the number as a new work.",
                 "Statements: 'Received from' is now the client or IPRS. Choose the client in the drop-down; the "
                 "statement is stored under that client.",
                 "Reconciliation: choose the client first. Every platform in the client's statements is listed with its "
                 "client revenue and IPRS statements and whether it can be reconciled yet.",
                 "Settings → Reconciliation: pick any client (new ones too). Change sets the reference benchmark "
                 "(4 % by default) for the ticked platforms; an unticked platform gets its own percentage.",
                 "Master: choose the client, then the master sheet opens in the SKV layout - ISRC, song name, totals, "
                 "then one section per platform (Spotify, Apple Music, YouTube …) with date, amount, period and "
                 "distribution number. ISRC and song name stay in view while you scroll sideways.",
                 "Wide tables have a scroll bar on top as well, and you can hold the mouse button and drag to scroll "
                 "sideways.",
                 "The version is in the bottom-right corner; click it to read these notes again."]),
    dict(version="1.1.0", date="17 Oct 2026",
         summary="Royalty reconciliation: a song catalogue, a statement library, reconciliation against IPRS with the 4 % "
                 "reference benchmark, and IPRS enquiries with follow-up. Accounts now have three roles.",
         points=["Catalogue: import the client's song list with a preview of new works, new ISRCs, conflicts and invalid "
                 "rows; nothing changes until you apply it. Admins verify, reject or move ISRC links.",
                 "Statements: upload client revenue reports and IPRS statements in any order. Duplicates and corrections "
                 "are recognised; nothing is counted twice.",
                 "Master: every work with its revenue per platform and its IPRS royalty, with the lines behind each amount "
                 "and the master statement export.",
                 "Reconciliation: revenue against IPRS royalty for one platform and usage period, with an indicative "
                 "reference benchmark. 'No corresponding IPRS entry found in the statements uploaded.' is flagged, never "
                 "treated as zero.",
                 "Enquiries: drafts, approval, manual sending, responses, follow-ups and closure, all recorded.",
                 "Roles: Super Admin, Admin and User. Admins create accounts; the first password is temporary."]),
    dict(version="1.0.6", date="10 Oct 2026",
         summary="In a report preview, the first two columns (for example ISRC and song name) stay in view while you "
                 "scroll sideways.",
         points=["Preview: columns A and B are frozen, like frozen panes in Excel."]),
    dict(version="1.0.5", date="10 Oct 2026",
         summary="No more approval step: you publish your own reports, and you can preview any report before "
                 "downloading it.",
         points=["Publish: on the last step of a run, Publish Reports saves the final version under the next report "
                 "number (after a short confirmation). Published reports still never change.",
                 "Review choices that move money (song matches, held money) now apply straight away; process again to "
                 "see them in the reports.",
                 "The Approver role and the Approvals page are gone. Approver-only accounts became Viewers.",
                 "Preview: next to every download, Preview shows the report's sheets and first rows in the browser."]),
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
