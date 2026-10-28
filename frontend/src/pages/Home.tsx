import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api";
import { int } from "../format";
import { useApp } from "../session";
import { NeedClient, period } from "../parts";
import { Button, Card, Loading, Pill, day, when } from "../ui";

/** One enquiry waiting, inside the company (internal) or with IPRS / PRS (external). */
type Waiting = { id: number; reference: string; platform: string | null; status: string; status_label: string; usage_period_start: string | null;
  usage_period_end: string | null; stage: string; next: string | null; due: string | null; overdue: boolean; mine: boolean;
  last_note?: { text: string; by: string | null; at: string } | null; reminders_sent?: number };

type Overview = {
  catalogue: { works: number; works_to_check: number; links: number; pending: number; conflicts: number };
  statements: Record<string, number>;
  statement_boxes: { iprs: number; platforms: { name: string; n: number }[] };
  runs: { id: number; run_reference: string; usage_period_start: string; usage_period_end: string; platform_name: string; started_at: string;
    verified_by: string | null; verified_at: string | null;
    summary: { compared: number; missing_iprs: number; unmatched_recordings: number; underpaid?: number } }[];
  catalogue_received: { id: number; filename: string; applied_at: string; received_via: string | null; received_from: string | null; imported_by: string | null }[];
  waiting: { internal: Waiting[]; external: Waiting[]; labels: Record<string, string> };
  previews_waiting: number; queues: { key: string; label: string; count: number }[];
  my_actions: { id: number; enquiry_id: number; enquiry_reference: string; action_title: string; due_at: string | null; overdue: boolean }[];
  overdue: number;
};

export function Guide() {
  return (
    <Card title="How it works">
      <ol className="guide">
        <li><b>Catalogue.</b> Import the client's song list. Each IPRS work number becomes a work; each ISRC is linked to it. A preview shows
          new works, new ISRCs, conflicts and invalid rows before anything changes.</li>
        <li><b>Statements</b>, two tabs, in any order: <b>platform reports</b> (revenue and usage per ISRC and month - two files are
          combined by ISRC and song name) and the <b>IPRS statements</b> (per work, all platforms - from IPRS or forwarded by the client).
          Each file is checked and stored once; nothing is counted twice.</li>
        <li><b>Master.</b> See every work with its platform revenue and plays and what IPRS paid, for any period, and export the master
          statement.</li>
        <li><b>Reconciliation.</b> For a platform and period: the platform revenue is the client's share of each song's revenue (for
          example 52 % on Spotify), so the song's total revenue = revenue ÷ 52 %; IPRS is expected to pay the IPRS % of that total (for
          example 7 %). Underpaid works are flagged with the % received and the variance; missing entries, unknown ISRCs and conflicts
          too - nothing is assumed.</li>
        <li><b>Enquiries.</b> Raise a query to IPRS from the underpaid works (why was this song paid 1.2 % instead of 7 %?). Internal: a
          colleague confirms the report (in the application, or live / by text - recorded with who and when). External: send it yourself,
          then record the reminders (every 7 days, 3 times; the 4th is a call to IPRS) and the replies until the issue is resolved and closed.</li>
      </ol>
    </Card>
  );
}

const VIA: Record<string, string> = { EMAIL: "mail", WHATSAPP: "WhatsApp", OTHER: "other" };

/** The two halves of an enquiry, told apart at a glance: 1 internal (amber, not sent yet - a colleague confirms the
 *  report) and 2 external (teal, sent - waiting for IPRS / PRS). Each enquiry shows how far it is along its half. */
const LANES = {
  internal: { no: 1, title: "Internal", tag: "Not sent yet · confirmation inside the company", steps: ["Prepared", "Forwarded", "Confirmed", "Sent"],
    empty: "Nothing is waiting inside the company." },
  external: { no: 2, title: "External", tag: "Sent · waiting for IPRS / PRS to reply", steps: ["Sent", "Reminder 1", "Reminder 2", "Reminder 3", "Call to the IPRS CEO"],
    empty: "Nothing is waiting for a reply from IPRS / PRS." },
} as const;

/** How many steps of its half the enquiry has done (the lane's steps). */
function stepsDone(side: keyof typeof LANES, x: Waiting): number {
  if (side === "external") return Math.min(1 + (x.reminders_sent ?? 0), LANES.external.steps.length);
  return x.status === "APPROVED_TO_SEND" ? 3 : x.status === "PENDING_APPROVAL" ? 2 : 1;
}

function Lane({ side, rows }: { side: keyof typeof LANES; rows: Waiting[] }) {
  const { go } = useApp();
  const l = LANES[side];
  return (
    <section className={`lane ${side}`} aria-label={`${l.title}: ${l.tag}`}>
      <header className="lane-h">
        <span className="lane-no" aria-hidden>{l.no}</span>
        <div className="grow"><div className="lane-t">{l.title}</div><div className="lane-tag">{l.tag}</div></div>
        <span className="lane-n" title={`${rows.length} enquir${rows.length === 1 ? "y" : "ies"}`}>{int(rows.length)}</span>
      </header>
      <p className="lane-flow">{l.steps.join(" → ")}</p>
      {!rows.length ? <p className="lane-empty">{l.empty}</p> : (
        <ul className="lane-list">{rows.map((x) => {
          const done = stepsDone(side, x);
          return (
            <li key={x.id} className="lane-item" role="link" tabIndex={0} onClick={() => go(`enquiries/${x.id}`)}
                onKeyDown={(e) => e.key === "Enter" && go(`enquiries/${x.id}`)}>
              <div className="lane-top"><b>{x.reference}</b>
                {x.mine ? <Pill tone="warn">Your turn</Pill> : <Pill tone="neutral">{x.status_label}</Pill>}</div>
              <div className="muted small">{x.platform} · {period(x.usage_period_start, x.usage_period_end)}</div>
              <div className="prog-row">
                <span className="prog" aria-hidden>{l.steps.map((st, k) => <i key={st} className={k < done ? "on" : ""} title={st} />)}</span>
                <span className="muted small">Step {done} of {l.steps.length} · {l.steps[done - 1]}</span>
              </div>
              <div className="small">{x.stage}</div>
              {x.next && <div className={`small ${x.overdue ? "bad-t" : "muted"}`}>Next: {x.next}{x.due ? ` · due ${day(x.due)}` : ""}{x.overdue ? " · overdue" : ""}</div>}
              {x.last_note && <div className="muted small">Last note · {x.last_note.by ?? "—"}: {x.last_note.text} · {when(x.last_note.at)}</div>}
            </li>);
        })}</ul>
      )}
    </section>
  );
}

/** One source of statements on the dashboard: IPRS, or one platform (e.g. Spotify), with how many it sent. */
function StatementBox({ name, n, onClick }: { name: string; n: number; onClick: () => void }) {
  return (
    <button type="button" className="st-box" onClick={onClick}>
      <span className="st-box-t">{name}</span>
      <span className="st-box-n">{int(n)}</span>
      <span className="st-box-s">statement{n === 1 ? "" : "s"}</span>
    </button>
  );
}

export default function Home() {
  const { me } = useApp();
  return (
    <NeedClient>{(cid) => <Dashboard cid={cid} name={me.name.split(" ")[0]} />}</NeedClient>
  );
}

function Dashboard({ cid, name }: { cid: number; name: string }) {
  const { me, go, client } = useApp();
  const q = useQuery({ queryKey: ["overview", cid], queryFn: () => api.get<Overview>(`/overview${qs({ client_id: cid })}`), refetchInterval: 30000 });
  if (!q.data) return <Loading />;
  const d = q.data;
  const st = d.statements;
  const imported = st.IMPORTED ?? 0;
  const next = !d.catalogue.works ? { text: "Start by importing the client's catalogue (song list).", go: "catalogue/import", label: "Import catalogue" }
    : !imported ? { text: "Upload the platform reports and the IPRS statements (one tab each).", go: "statements", label: "Upload statements" }
      : (st.NEEDS_REVIEW ?? 0) > 0 ? { text: `${st.NEEDS_REVIEW} statement${st.NEEDS_REVIEW === 1 ? " needs" : "s need"} an answer before ${st.NEEDS_REVIEW === 1 ? "it counts" : "they count"}.`, go: "statements", label: "Answer now" }
        : !d.runs.length ? { text: "Everything is in place for a first reconciliation.", go: "reconciliation", label: "Run a reconciliation" }
          : d.overdue ? { text: `${d.overdue} follow-up${d.overdue === 1 ? " is" : "s are"} overdue.`, go: "enquiries", label: "Open enquiries" }
            : { text: "Review the latest reconciliation, or upload new statements as they arrive.", go: `reconciliation/${d.runs[0].id}`, label: "Latest reconciliation" };
  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Hello, {name}</h1>
          <p className="basis">This calculation is taken into consideration with the understanding that the master revenue received is from the Indian territory only.</p>
          <p className="next">{client?.name} · {next.text}</p>
        </div>
        <div className="hero-actions">
          {me.can.prepare && <Button kind="primary" className="big" onClick={() => go(next.go)}>{next.label}</Button>}
        </div>
      </section>
      <div className="two">
        <Card title="Enquiries waiting" sub="Queries to IPRS / PRS that are not finished. 1 Internal: not sent yet, a colleague confirms the report. 2 External: sent, waiting for IPRS / PRS to reply."
              actions={<Button kind="ghost" onClick={() => go("enquiries")}>Open</Button>}>
          <div className="lanes">
            <Lane side="internal" rows={d.waiting.internal} />
            <Lane side="external" rows={d.waiting.external} />
          </div>
        </Card>
        <Card title="My follow-ups" sub="Once the mail is sent out to IPRS, this section tracks the movement of the communication until the matter is closed.">
          {d.my_actions.length === 0 ? <p className="muted">No follow-up is assigned to you.</p> : (
            <ul className="list">{d.my_actions.map((a) => (
              <li key={a.id} className="click" onClick={() => go(`enquiries/${a.enquiry_id}`)}>
                <div><div className="li-t">{a.action_title}</div><div className="muted small">{a.enquiry_reference}</div></div>
                <span className={a.overdue ? "bad-t" : ""}>{a.due_at ? day(a.due_at) : "no date"}{a.overdue ? " · overdue" : ""}</span>
              </li>))}</ul>
          )}
          <div className="waiting-part">
            <h3 className="part-h">Catalogue received</h3>
            <p className="part-sub">Every Tuesday a mail goes to Durga for the updated catalogue; each import is noted here with how it came.</p>
            {d.catalogue_received.length === 0 ? <p className="muted small">No catalogue imported yet.</p> : (
              <ul className="list">{d.catalogue_received.map((c) => (
                <li key={c.id} className="click" onClick={() => go(`catalogue/import/${c.id}`)}>
                  <div className="grow"><div className="li-t wrap-any">{c.filename}</div>
                    <div className="muted small">Imported {when(c.applied_at)}{c.imported_by ? ` by ${c.imported_by}` : ""}</div></div>
                  <Pill tone={c.received_via ? "info" : "neutral"}>{c.received_via ? `By ${VIA[c.received_via]}` : "how: not recorded"}{c.received_from ? ` · from ${c.received_from}` : ""}</Pill>
                </li>))}</ul>
            )}
          </div>
        </Card>
      </div>
      <div className="two">
        <Card title="Catalogue" sub="The client's song list: works and their ISRCs. Every Tuesday a mail goes to Durga for the updated catalogue." actions={<Button kind="ghost" onClick={() => go("catalogue")}>Open</Button>}>
          <dl className="facts">
            <dt>Works</dt><dd>{int(d.catalogue.works)}</dd>
            <dt>ISRC links</dt><dd>{int(d.catalogue.links)}</dd>
            <dt>Links to verify</dt><dd>{d.catalogue.pending ? <a href="#/catalogue/works">{int(d.catalogue.pending)}</a> : 0}</dd>
            <dt>ISRCs in conflict</dt><dd>{d.catalogue.conflicts ? <a href="#/catalogue/conflicts">{int(d.catalogue.conflicts)}</a> : 0}</dd>
            {d.previews_waiting > 0 && <><dt>Previews not applied</dt><dd><a href="#/catalogue/history">{d.previews_waiting}</a></dd></>}
          </dl>
        </Card>
        <Card title="Reconciliations" sub="Compares the platform's revenue (e.g. Spotify) with what IPRS paid for the same period; a second person verifies each one." actions={<Button kind="ghost" onClick={() => go("reconciliation")}>Open</Button>}>
          {d.runs.length === 0 ? <p className="muted">None yet.</p> : (
            <ul className="list">{d.runs.map((r) => (
              <li key={r.id} className="click" onClick={() => go(`reconciliation/${r.id}`)}>
                <div><div className="li-t">{r.platform_name} · {period(r.usage_period_start, r.usage_period_end)}</div>
                  <div className="muted small">{r.run_reference} · {int(r.summary.compared)} compared{r.summary.underpaid != null ? ` · ${int(r.summary.underpaid)} underpaid` : ""} · {int(r.summary.missing_iprs)} without IPRS entry · {day(r.started_at)}</div></div>
                <span className="small nowrap">{r.verified_by ? <span className="good-t">✓ Verified by {r.verified_by}</span> : <span className="muted">Not verified</span>}</span>
              </li>))}</ul>
          )}
        </Card>
      </div>
      <Card title="Statements" sub="The files received: the platforms' revenue and usage reports, and the IPRS statements. Each counts once." actions={<Button kind="ghost" onClick={() => go("statements/platform")}>Open</Button>}>
        {!d.statement_boxes.iprs && !d.statement_boxes.platforms.length ? <p className="muted">No statements yet.</p> : (
          <div className="st-boxes">
            {d.statement_boxes.iprs > 0 && <StatementBox name="IPRS" n={d.statement_boxes.iprs} onClick={() => go("statements/iprs")} />}
            {d.statement_boxes.platforms.map((x) => <StatementBox key={x.name} name={x.name} n={x.n} onClick={() => go("statements/platform")} />)}
          </div>)}
      </Card>
    </div>
  );
}
