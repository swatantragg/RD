import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api";
import { int } from "../format";
import { useApp } from "../session";
import { NeedClient, STATEMENT_TONE, period } from "../parts";
import { Button, Card, Loading, Pill, day } from "../ui";

type Overview = {
  catalogue: { works: number; works_to_check: number; links: number; pending: number; conflicts: number };
  statements: Record<string, number>;
  recent_statements: { id: number; original_filename: string; record_type: string; import_status: string; uploaded_at: string;
    usage_period_start: string | null; usage_period_end: string | null; platform_name: string | null }[];
  runs: { id: number; run_reference: string; usage_period_start: string; usage_period_end: string; platform_name: string; started_at: string;
    summary: { compared: number; missing_iprs: number; unmatched_recordings: number; underpaid?: number } }[];
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
        <li><b>Statements</b>, one tab each, in any order: <b>platform reports</b> (revenue and usage per ISRC and month - two files are
          combined by ISRC and song name), the <b>client's statements</b> (per work, all platforms) and the <b>IPRS statements</b>. Each file
          is checked and stored once; nothing is counted twice.</li>
        <li><b>Master.</b> See every work with its platform revenue and plays, the client's statements and what IPRS paid, for any period,
          and export the master statement.</li>
        <li><b>Reconciliation.</b> For a platform and period: 4 % of each work's platform revenue (expected) against what IPRS paid, with
          the client's statement beside it. Underpaid works are flagged with the % paid and the shortfall; missing entries, unknown ISRCs
          and conflicts too - nothing is assumed.</li>
        <li><b>Enquiries.</b> Raise a query to IPRS from the underpaid works (why was this song paid 1.2 % instead of 4 %?), have it
          approved, send it yourself, then record responses and follow-ups until the issue is resolved and closed.</li>
      </ol>
    </Card>
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
    : !imported ? { text: "Upload the platform reports, the client's statements and the IPRS statements (one tab each).", go: "statements", label: "Upload statements" }
      : (st.NEEDS_REVIEW ?? 0) > 0 ? { text: `${st.NEEDS_REVIEW} statement${st.NEEDS_REVIEW === 1 ? " needs" : "s need"} an answer before ${st.NEEDS_REVIEW === 1 ? "it counts" : "they count"}.`, go: "statements", label: "Answer now" }
        : !d.runs.length ? { text: "Everything is in place for a first reconciliation.", go: "reconciliation", label: "Run a reconciliation" }
          : d.overdue ? { text: `${d.overdue} follow-up${d.overdue === 1 ? " is" : "s are"} overdue.`, go: "enquiries", label: "Open enquiries" }
            : { text: "Review the latest reconciliation, or upload new statements as they arrive.", go: `reconciliation/${d.runs[0].id}`, label: "Latest reconciliation" };
  const active = d.queues.filter((x) => x.count > 0);
  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Hello, {name}</h1>
          <p className="next">{client?.name} · {next.text}</p>
        </div>
        <div className="hero-actions">
          {me.can.prepare && <Button kind="primary" className="big" onClick={() => go(next.go)}>{next.label}</Button>}
        </div>
      </section>
      <div className="two">
        <Card title="Enquiries waiting" actions={<Button kind="ghost" onClick={() => go("enquiries")}>Open</Button>}>
          {active.length === 0 ? <p className="muted">Nothing is waiting.</p> : (
            <ul className="list">{active.map((x) => <li key={x.key} className="click" onClick={() => go("enquiries")}><div className="li-t">{x.label}</div><b>{int(x.count)}</b></li>)}</ul>
          )}
        </Card>
        <Card title="My follow-ups">
          {d.my_actions.length === 0 ? <p className="muted">No follow-up is assigned to you.</p> : (
            <ul className="list">{d.my_actions.map((a) => (
              <li key={a.id} className="click" onClick={() => go(`enquiries/${a.enquiry_id}`)}>
                <div><div className="li-t">{a.action_title}</div><div className="muted small">{a.enquiry_reference}</div></div>
                <span className={a.overdue ? "bad-t" : ""}>{a.due_at ? day(a.due_at) : "no date"}{a.overdue ? " · overdue" : ""}</span>
              </li>))}</ul>
          )}
        </Card>
      </div>
      <div className="two">
        <Card title="Catalogue" actions={<Button kind="ghost" onClick={() => go("catalogue")}>Open</Button>}>
          <dl className="facts">
            <dt>Works</dt><dd>{int(d.catalogue.works)}</dd>
            <dt>ISRC links</dt><dd>{int(d.catalogue.links)}</dd>
            <dt>Links to verify</dt><dd>{d.catalogue.pending ? <a href="#/catalogue/works">{int(d.catalogue.pending)}</a> : 0}</dd>
            <dt>ISRCs in conflict</dt><dd>{d.catalogue.conflicts ? <a href="#/catalogue/conflicts">{int(d.catalogue.conflicts)}</a> : 0}</dd>
            {d.previews_waiting > 0 && <><dt>Previews not applied</dt><dd><a href="#/catalogue/history">{d.previews_waiting}</a></dd></>}
          </dl>
        </Card>
        <Card title="Reconciliations" actions={<Button kind="ghost" onClick={() => go("reconciliation")}>Open</Button>}>
          {d.runs.length === 0 ? <p className="muted">None yet.</p> : (
            <ul className="list">{d.runs.map((r) => (
              <li key={r.id} className="click" onClick={() => go(`reconciliation/${r.id}`)}>
                <div><div className="li-t">{r.platform_name} · {period(r.usage_period_start, r.usage_period_end)}</div>
                  <div className="muted small">{r.run_reference} · {int(r.summary.compared)} compared{r.summary.underpaid != null ? ` · ${int(r.summary.underpaid)} underpaid` : ""} · {int(r.summary.missing_iprs)} without IPRS entry · {day(r.started_at)}</div></div>
              </li>))}</ul>
          )}
        </Card>
      </div>
      <Card title="Statements" actions={<Button kind="ghost" onClick={() => go("statements/platform")}>Open</Button>}>
        <dl className="facts">
          <dt>Imported</dt><dd>{int(imported)}</dd>
          {Object.entries(st).filter(([k]) => k !== "IMPORTED").map(([k, v]) => <span key={k} style={{ display: "contents" }}><dt>{k.replace("_", " ").toLowerCase()}</dt><dd>{int(v)}</dd></span>)}
        </dl>
        <ul className="list">{d.recent_statements.map((s) => (
          <li key={s.id} className="click" onClick={() => go(`statements/${s.id}`)}>
            <div><div className="li-t small">{s.original_filename}</div><div className="muted small">{s.platform_name ?? (s.record_type === "WORK_ROYALTY" ? "per work" : "")} · {period(s.usage_period_start, s.usage_period_end)} · {day(s.uploaded_at)}</div></div>
            <Pill tone={STATEMENT_TONE[s.import_status] ?? "neutral"}>{s.import_status.replace("_", " ").toLowerCase()}</Pill>
          </li>))}</ul>
      </Card>
    </div>
  );
}
