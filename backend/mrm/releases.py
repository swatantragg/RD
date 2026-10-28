"""Release notes shown once to each person after an update (newest first). The first entry is the running version."""
from __future__ import annotations

from . import __version__

RELEASES: list[dict] = [
    dict(version="1.7.3", date="28 Oct 2026",
         summary="A security and quality release: the whole application was tested - 130 unit, integration and "
                 "test-driven tests, and every one of its 112 server actions tried with wrong input by three kinds of "
                 "account - and every bug found was fixed.",
         points=[],
         sections=[
             dict(title="Bugs fixed", points=[
                 "Downloads (reconciliation report, enquiry attachment, working paper) failed with a server error when "
                 "a song title, a note or other text held an invisible control character. Such characters are now "
                 "left out and the download works.",
                 "A file name with quotes, a semicolon or a line break could break the download. Names are cleaned "
                 "for every download.",
                 "12 actions answered 'Something went wrong on the server' when a field was missing or of the wrong "
                 "kind - raising a query, starting a reconciliation, adding a work or an ISRC, importing a stored "
                 "catalogue, saving reconciliation settings, reviewing and verifying, marking notifications read. "
                 "They now say what is missing.",
                 "Giving work - a follow-up, an exception, an enquiry, a new query - to an account that does not "
                 "exist failed with a server error, and to a switched-off account it was accepted. Both are now "
                 "refused with a plain message.",
                 "Giving a User a client that does not exist failed with a server error; naming a client twice failed "
                 "too. Both are handled.",
                 "On / off answers sent as text ('false', 'no') counted as 'yes': switching an account or a client on "
                 "or off, 'I reviewed the later IPRS statements', 'mark the links verified'. Only a real yes or no "
                 "counts now.",
                 "Sign-in and My profile failed with a server error when the password was not text, and a damaged "
                 "stored password could stop sign-in. Both now count as a wrong password."]),
             dict(title="Security fixes", points=[
                 "Catalogue → Import: a User could mark every link of an imported catalogue as verified, although "
                 "verifying links is an Admin's task - and verified links decide which works go into a query to "
                 "IPRS. Only Admins verify now; a User's import leaves new links pending, and the box is shown to "
                 "Admins only.",
                 "A refusal by the database no longer shows table or rule names; it says 'You do not have access to "
                 "this.'",
                 "Passwords have at most 128 characters (very long input is refused before it is checked), and only "
                 "the application's own password strength settings are accepted.",
                 "The security token sent with every change is compared in constant time.",
                 "The web server passes only the real address of the computer to the application, so a forged "
                 "address cannot appear in its logs."]),
             dict(title="Security in place", points=[
                 "Sign-in: passwords stored only as salted scrypt hashes; 15-minute lock after 8 failed attempts; "
                 "the same message for a wrong email or password; at most 10 sign-in attempts a minute per computer.",
                 "Sessions: random tokens kept only as hashes, ending after 10 hours or at sign-out; the cookie "
                 "cannot be read by scripts or sent from other sites; every change needs the session's security "
                 "token; changing the password signs the other browsers out; switching an account off or changing "
                 "its role signs it out at once.",
                 "Accounts: three roles checked on the server for every request; one Super Admin, protected by the "
                 "database; temporary passwords must be changed at the first sign-in; nobody changes their own role.",
                 "Clients: a User sees only the clients granted to them - checked by the application and again by "
                 "the database (row-level security), for lists and for every record opened by number.",
                 "Duties: the preparer never confirms their own enquiry; a second person verifies a reconciliation; "
                 "nothing can be copied or recorded as sent before the confirmation; completed reconciliations "
                 "never change.",
                 "Activity log: sign-ins (and failed attempts), changes and report downloads are recorded, chained "
                 "so that any edit or deletion shows; passwords and tokens are never written to it.",
                 "Files: only plain .xlsx and .csv; macro workbooks, external links, embedded objects, path tricks "
                 "and ZIP bombs refused before reading; size, sheet and cell limits; stored write-once; text that "
                 "looks like a formula is never a formula in a download.",
                 "Web page: strict content security policy, no framing by other sites, no content sniffing, no "
                 "caching of data; the web server does not show its software version; production refuses weak "
                 "database passwords and hides the API documentation.",
                 "Checked in this version: no known vulnerability in the application's packages (web and server)."]),
             dict(title="Also since 1.7.0", points=[
                 "1.7.1: a query to IPRS lists every properly matched work of the Works tab (works whose link is not "
                 "verified, or that need review, are left out); pop-up notifications when someone gives you work; "
                 "'Check the links again' says what it found; one-line help under Follow-ups and Send a note.",
                 "1.7.2: Home shows the enquiries waiting in two lanes - 1 Internal (not sent yet) and 2 External "
                 "(sent); the notes and the Activity log read who, what, then the date and time, with a name tag per "
                 "person."])]),
    dict(version="1.7.2", date="28 Oct 2026",
         summary="Home shows the enquiries waiting in two clearly different lanes - 1 Internal (not sent yet) and 2 "
                 "External (sent to IPRS / PRS) - and every enquiry log reads who, what, then the date and time.",
         points=["Home → Enquiries waiting: two lanes side by side (one under the other on a narrow screen). 1 "
                 "Internal, in amber: not sent yet, a colleague confirms the report inside the company. 2 External, "
                 "in teal: sent, waiting for IPRS / PRS to reply. Each lane shows its count and its steps (Prepared → "
                 "Forwarded → Confirmed → Sent; Sent → Reminder 1 → 2 → 3 → Call to the IPRS CEO), and each enquiry "
                 "a bar with how far it is, what it waits for, the next follow-up and the last note.",
                 "Enquiry → Notes and Activity log: still on their time line, each line now shows the person first - a "
                 "name tag with initials, one colour per person - then what they did, then the date and time, in "
                 "aligned columns (Who · What · Date and time).",
                 "Settings → Activity log: the same order - Who, What, Details, Date and time."]),
    dict(version="1.7.1", date="28 Oct 2026",
         summary="A query to IPRS now lists the works of the Works tab that are properly matched, a pop-up tells you "
                 "when someone gives you work, and 'Check the links again' says what it found.",
         points=["Reconciliation → Raise a query to IPRS: the query and its attachment list every work of the Works "
                 "tab that is properly matched - its ISRC link verified and the work active in the Catalogue - "
                 "whether IPRS underpaid it, did not list it, paid it in full or there is no platform revenue to "
                 "compare. Unmatched recordings and works not in the catalogue never go. Works whose link is not "
                 "verified yet, or that need review in the Catalogue, are left out (the draft says how many), so the "
                 "query no longer waits for them; check them in the Catalogue and put them in a later query.",
                 "Pop-up notifications in the top-right corner when someone else gives you work: an enquiry assigned "
                 "to you, a report to confirm, a follow-up, a reconciliation exception - and, for the person who "
                 "prepared an enquiry, the report returned or confirmed. 'Open' goes to it; × dismisses it. The "
                 "screen checks every 30 seconds.",
                 "Enquiry: one line under Follow-ups and under Send a note says what each does and does not do. A "
                 "follow-up is a task with a due date for one person; a note is a message. Neither sends anything to "
                 "IPRS or moves the enquiry to the next step.",
                 "Enquiry → Check the links again: it said 'Done.' even when nothing had changed. It now says whether "
                 "the draft is ready to forward, or what still holds it back (how many ISRC links to verify and works "
                 "to review, with their numbers); the page shows the same, and checking again with no change adds no "
                 "new line to the history."]),
    dict(version="1.7.0", date="27 Oct 2026",
         summary="Enquiries are in two parts - internal (a colleague confirms the report before it goes to IPRS / PRS) "
                 "and external (sent, with weekly reminders until IPRS / PRS replies) - and a second person verifies "
                 "each reconciliation.",
         points=["Home → Enquiries waiting has two lists. 'Internal - confirmation before sending': cleared by the "
                 "preparer, waiting for a senior colleague to confirm the report. 'External - reply from IPRS / PRS': "
                 "sent, waiting for their reply. Each line shows the enquiry number and what it waits for, and opens "
                 "the enquiry.",
                 "Enquiry, internal: 'Forward for confirmation' sends it to a colleague (any person with an account), "
                 "who gets 'Confirm the report' in their follow-ups, reads the text, downloads both reports and "
                 "confirms them or returns them with a comment; notes can go both ways. If the colleague is busy and "
                 "saw the report live on your screen, or confirmed it by a text message, 'Record a confirmation given "
                 "outside the application' notes how (live demonstration, text, call, meeting), who and the date and "
                 "time. The preparer does not confirm their own enquiry. 'Copy text' and 'Record that it was sent' "
                 "open only after the confirmation.",
                 "Enquiry, external: after the sending, reminder 1 is due 7 days later (the same mail again), then "
                 "every 7 days, 3 times; the 4th reminder is a call, escalated to the CEO of IPRS. A reply from IPRS / "
                 "PRS stops the reminders.",
                 "The enquiry's Activity log lists every step in two parts, inside the company and with IPRS / PRS, in "
                 "plain words with who and when; each step is also in Settings → Activity log.",
                 "Reconciliation: the Review column names who reviewed (else 'Not reviewed'), on the list of earlier "
                 "reconciliations and on every item. 'Verify this reconciliation': a second person - not the one who "
                 "ran it - verifies it once; the name and time are shown on the run, in its list and on Home, and "
                 "recorded in the activity log.",
                 "Catalogue → Import: say how the catalogue was received (mail or WhatsApp) and from whom before "
                 "applying it. Home → My follow-ups lists the catalogues received with the file name, the date and "
                 "time imported and how it came; Import history shows the same.",
                 "Home: under the greeting, 'This calculation is taken into consideration with the understanding that "
                 "the master revenue received is from the Indian territory only.' Every page and Home section has a "
                 "one-line description of what it is for."]),
    dict(version="1.6.3", date="26 Oct 2026",
         summary="A reconciliation now has a Usage tab beside Works: the months with platform usage (e.g. Jan - Mar "
                 "2026), every figure for those months only, and the start page and run page say what is available.",
         points=["Reconciliation, start: 'Available for Spotify' shows the statements from IPRS, the revenue from "
                 "Spotify and the usage from Spotify, each with its months. Once the months are chosen it says what "
                 "the Works tab compares (revenue and IPRS, e.g. Oct 2025 - Mar 2026) and what the Usage tab compares "
                 "(the months with Spotify usage, e.g. Jan - Mar 2026).",
                 "Run page: the same 'Available' lines at the top, and a Usage tab beside Works. It lists the works "
                 "with revenue in the usage months, with every figure for those months only: the Spotify amount and "
                 "usage, what IPRS paid, the total revenue, expected, received %, variance % and variance amount, with "
                 "the totals above the table.",
                 "IPRS pays one amount for its whole period (e.g. Oct 2025 - Mar 2026). For the usage months the "
                 "Usage tab counts the part of it that follows the song's revenue: Rs. 60 paid, half the song's "
                 "Oct - Mar revenue earned in Jan - Mar -> Rs. 30. The tab, the item pop-up and the downloads say so.",
                 "Export report on the Usage tab downloads the usage months only (file name '..._usage_2026-01_to_"
                 "2026-03_...').",
                 "Enquiry 'Download with usage': only the usage months - the songs with revenue in them, every figure "
                 "for those months, with Usage and Revenue per usage (file name with those months). Songs with no "
                 "revenue in them are left out and counted in the notes."]),
    dict(version="1.6.2", date="26 Oct 2026",
         summary="The downloaded reports have a shorter check - Client revenue, Received from IPRS, Received % and "
                 "Variance % - and the check columns have shorter names everywhere.",
         points=["Reconciliation 'Export report' and a query's attachment ('Download attachment'): the check section is "
                 "Client revenue · Received from IPRS · Received % · Variance %; the expected value and the variance "
                 "amount are left out (also the expected royalty and total shortfall lines of the report's Summary "
                 "sheet). The letter to IPRS describes the attachment the same way.",
                 "Column names: 'Client share (52 %)' / 'Revenue' is now 'Client revenue', 'Received % of total "
                 "revenue' is 'Received %' and 'Variance % (7 % - received %)' is 'Variance %' - on the "
                 "reconciliation page and in every download.",
                 "The reconciliation page and the query attachment with usage ('Download with usage') keep every "
                 "column, with the expected value and the variance amount.",
                 "Home: 'Enquiries waiting' says what it means - queries to IPRS that are not finished, waiting for a "
                 "step from us or a reply from IPRS."]),
    dict(version="1.6.1", date="24 Oct 2026",
         summary="The variance % is the difference in percentage points (7 % expected, 1 % received = 6 %), the "
                 "reconciliation says in plain words which months it compares, and its page shows one dashboard.",
         points=["Variance % = IPRS % - received %: the difference in percentage points. IPRS should pay 7 % of the "
                 "total revenue and paid 1 %, so the variance % is 6 % (before, it was the variance amount as a % of "
                 "the expected value). The Variance amount comes right after it: ... Received % · Variance % · Variance "
                 "amount - on the reconciliation page, in its Excel report and in a query's attachment.",
                 "Reconciliation: the Platform list shows only platforms with both their revenue report and an IPRS "
                 "statement uploaded.",
                 "Reconciliation: 'Which months to compare?' - each choice shows its months, the IPRS statement and how "
                 "much of it the platform's revenue and plays cover; a period without platform revenue is named but "
                 "not offered; the line under it says, for example, 'Compares Spotify revenue for Oct 2025 – Mar 2026 "
                 "with what IPRS paid for the same months'. The run page starts with the same line.",
                 "Reconciliation table: the platform section has no Date column (Amount · Period with its Usage · "
                 "Distribution No) and the IPRS royalty section no Usage column (Amount · Date · Period · Distribution "
                 "No) - as in the Excel report and the query attachment, for works, unmatched recordings and works not "
                 "in the catalogue.",
                 "Run page: one dashboard - the figures and, under 'To review', the tiles that filter the list; no "
                 "number is shown twice. The run's reference, who ran it and the calculation basis are at the bottom, "
                 "with the statements used.",
                 "The Reports section is gone: the reconciliation (with its unmatched songs and Excel report) and the "
                 "query attachment are the reports.",
                 "Songs are listed by song name, A → Z, unless another order is chosen: the master sheet, Works by "
                 "platform, the reconciliation list, and every download - the master statement and master view, the "
                 "reconciliation's Excel report (in the order chosen on screen) and a query's attachments.",
                 "Home: the Statements section shows one box per source - IPRS with the number of statements received "
                 "from IPRS, then each platform that sent reports (e.g. Spotify, 2 statements); the status counts and the "
                 "list of recent files are gone. A box opens its Statements tab."]),
    dict(version="1.6.0", date="23 Oct 2026",
         summary="The reconciliation works out each song's total revenue from the client's share before checking what "
                 "IPRS paid, and Statements has two tabs: Platform reports and IPRS statements.",
         points=["Reconciliation: the platform report shows the client's share of a song's revenue. The song's total "
                 "revenue (100 %) = revenue ÷ client share, and IPRS is expected to pay the IPRS % of that total. For "
                 "example a song earns Rs. 100 on Spotify and the client receives 52 %, Rs. 52: total revenue = 52 ÷ "
                 "52 % = Rs. 100, expected at 7 % = Rs. 7; IPRS paid Rs. 3, so 3 % was received and the variance is "
                 "Rs. 4 (57.14 % of the expected value).",
                 "Settings → Reconciliation: two client-wide values, the IPRS % and the client share %, and for each "
                 "platform an IPRS % and a client share of its own - or the client-wide values ('Select all' ticks every "
                 "platform). A client share that is not set counts as 100 % (the revenue reported is the total).",
                 "Statements has two tabs: Platform reports and IPRS statements. The client's statements were IPRS "
                 "statements the client forwards (the same layout), so they are under IPRS statements now, with the "
                 "others; the batches of each tab are numbered again in upload order. A reconciliation needs the "
                 "platform's revenue report: a platform with IPRS statements only shows 'No platform report'.",
                 "Reconciliation, 'Check: expected vs paid': total revenue (100 %), the client share (the revenue the "
                 "platform reported), the expected value, received from IPRS, received % of the total revenue, the "
                 "variance amount and the variance %.",
                 "Excel report and query attachment: no Date column in the platform section and no Usage in the IPRS "
                 "royalty section; the check section shows Revenue (the client share amount), the expected value, "
                 "Received from IPRS, Received % of the total revenue, Variance amount and Variance % - the Result column "
                 "is gone.",
                 "Query to IPRS: two downloads - the attachment, and the attachment with usage: the same report with each "
                 "song's usage and its revenue per usage (the song's total revenue ÷ its usage: Rs. 100 for 100 plays = "
                 "Rs. 1 per play) at the end. When the usage report covers only some months, the revenue of those months "
                 "is used."]),
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
