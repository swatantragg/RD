import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { NUMBER_PATTERN, int, numeric, today, plusDays } from "../format";
import { useApp } from "../session";
import { FormDialog, NeedClient, period, ResetFilters } from "../parts";
import { Button, Card, DownloadButton, Empty, Loading, More, Notice, Page, Pill, Select, day, when, type Tone } from "../ui";

const STATUS_TONE: Record<string, Tone> = { NEEDS_REVIEW: "warn", MAPPING_PENDING: "warn", DATA_CLARIFICATION_REQUIRED: "warn", DRAFT_PREPARED: "info",
  PENDING_APPROVAL: "info", APPROVED_TO_SEND: "good", AWAITING_RESPONSE: "info", UNDER_INVESTIGATION: "warn", PARTIALLY_RESOLVED: "warn",
  RESOLVED: "good", CLOSED: "neutral" };

type Enq = { id: number; enquiry_reference: string; subject: string; draft_body: string; status: string; status_label: string; platform: string | null;
  usage_period_start: string | null; usage_period_end: string | null; assigned_to: number | null; assigned_to_name: string | null; created_by_name: string;
  approved_by_name: string | null; approved_at: string | null; sent_by_name: string | null; sent_at: string | null; recipient_reference: string | null;
  send_channel: string | null; next_follow_up_at: string | null; follow_up_due: boolean; overdue: boolean; new_statement_review: boolean;
  returned_reason: string | null; resolution_status: string | null; resolution_summary: string | null; closed_by_name: string | null; closed_at: string | null;
  last_response_at: string | null; created_at: string; updated_at: string };
type Action = { id: number; enquiry_id: number; action_title: string; action_description: string | null; assigned_to: number | null; assigned_to_name: string | null;
  due_at: string | null; status: string; overdue: boolean; due_today?: boolean; mine?: boolean; completion_note: string | null; completed_by_name?: string | null;
  can_complete?: boolean; enquiry_reference?: string; subject?: string };

export default function Enquiries({ id }: { id?: number }) {
  return <NeedClient>{(cid) => (id ? <EnquiryPage id={id} /> : <Overview cid={cid} />)}</NeedClient>;
}

function Overview({ cid }: { cid: number }) {
  const { go } = useApp();
  const [queue, setQueue] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [mine, setMine] = useState(false);
  const dash = useQuery({ queryKey: ["enq-dash", cid], queryFn: () => api.get<{ queues: { key: string; label: string; count: number }[]; actions: Action[]; can_assign: boolean }>(`/enquiries/dashboard${qs({ client_id: cid })}`) });
  const list = useQuery({ queryKey: ["enq-list", cid, queue, status, q, mine], queryFn: () => api.get<{ rows: Enq[]; statuses: { value: string; label: string }[] }>(`/enquiries${qs({ client_id: cid, queue, status, q, mine })}`) });
  const parts: [string, string][] = [["", "All"], ["internal", "Internal - confirmation before sending"], ["external", "External - reply from IPRS / PRS"]];
  return (
    <Page title="Enquiries" intro="Queries to IPRS / PRS about the matched works of a reconciliation: a colleague confirms the report inside the company first, then it is sent and followed up until the matter is closed.">
      <div className="tabs" role="tablist">
        {parts.map(([k, l]) => <button key={k} role="tab" aria-selected={queue === k || (!k && !["internal", "external"].includes(queue))}
                                        className={queue === k || (!k && !["internal", "external"].includes(queue)) ? "on" : ""} onClick={() => setQueue(k)}>{l}</button>)}
      </div>
      {queue === "internal" && <Notice>Cleared by the preparer and waiting inside the company: a senior colleague confirms the report before it is forwarded to IPRS / PRS.</Notice>}
      {queue === "external" && <Notice>Mail sent to IPRS / PRS and waiting for their reply. No reply within 7 days: the same mail again, every week for 3 weeks; the 4th reminder is a call, escalated to the CEO of IPRS.</Notice>}
      {!dash.data ? <Loading /> : (
        <div className="tiles small-tiles">
          {dash.data.queues.map((x) => (
            <button key={x.key} className={`tile ${queue === x.key ? "on" : ""} ${["overdue"].includes(x.key) && x.count ? "alert" : ""}`} onClick={() => setQueue(queue === x.key ? "" : x.key)}>
              <span className="tile-n">{int(x.count)}</span><span className="tile-t">{x.label}</span>
            </button>))}
        </div>
      )}
      {dash.data && dash.data.actions.length > 0 && <FollowUps actions={dash.data.actions} title="Open follow-ups" />}
      <Card>
        <div className="toolbar">
          <input className="input" placeholder="Find a reference or subject" value={q} onChange={(e) => setQ(e.target.value)} />
          <Select size="sm" label="Status" value={status} placeholder="Any status" onChange={setStatus}
                  options={[{ value: "", label: "Any status" }, ...(list.data?.statuses ?? [])]} />
          <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me</label>
          <ResetFilters active={!!(queue || status || q || mine)} onReset={() => { setQueue(""); setStatus(""); setQ(""); setMine(false); }} />
        </div>
        {!list.data ? <Loading /> : list.data.rows.length === 0 ? (
          <Empty title="No enquiry here">Enquiry drafts are prepared from a <a href="#/reconciliation">reconciliation</a>: tick the works to ask IPRS about.</Empty>
        ) : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Reference</th><th>Subject</th><th>Platform / period</th><th>Status</th><th>Assigned to</th><th>Next follow-up</th><th>Updated</th></tr></thead>
            <tbody>{list.data.rows.map((e) => (
              <tr key={e.id} className="click" onClick={() => go(`enquiries/${e.id}`)}>
                <td><b>{e.enquiry_reference}</b></td>
                <td className="small">{e.subject}{e.new_statement_review && <div><Pill tone="warn">New statement to review</Pill></div>}</td>
                <td className="small nowrap">{e.platform} · {period(e.usage_period_start, e.usage_period_end)}</td>
                <td><Pill tone={STATUS_TONE[e.status] ?? "neutral"}>{e.status_label}</Pill></td>
                <td>{e.assigned_to_name ?? <span className="muted">nobody</span>}</td>
                <td className={e.overdue ? "bad-t" : e.follow_up_due ? "warn-t" : ""}>{e.next_follow_up_at ? `${day(e.next_follow_up_at)}${e.overdue ? " (overdue)" : e.follow_up_due ? " (today)" : ""}` : "—"}</td>
                <td className="small nowrap">{day(e.updated_at)}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Card>
    </Page>
  );
}

function FollowUps({ actions, title, sub, enquiryId, canAdd, assignees, onChanged }: { actions: Action[]; title: string; sub?: string; enquiryId?: number; canAdd?: boolean;
  assignees?: { id: number; name: string }[]; onChanged?: (d: Detail) => void }) {
  const { me } = useApp();
  const qc = useQueryClient();
  const [done, setDone] = useState<Action | null>(null);
  const [edit, setEdit] = useState<Action | null>(null);
  const [add, setAdd] = useState(false);
  const after = (d: Detail) => { onChanged?.(d); qc.invalidateQueries({ queryKey: ["enq-dash"] }); qc.invalidateQueries({ queryKey: ["enq-list"] }); };
  return (
    <Card title={title} sub={sub} actions={canAdd && <Button kind="secondary" className="sm" onClick={() => setAdd(true)}>Add a follow-up</Button>}>
      {actions.length === 0 ? <p className="muted">No follow-up.</p> : (
        <div className="tbl-wrap short"><table className="tbl">
          <thead><tr><th>Follow-up</th>{!enquiryId && <th>Enquiry</th>}<th>Assigned to</th><th>Due</th><th>Status</th><th></th></tr></thead>
          <tbody>{actions.map((a) => (
            <tr key={a.id} className={a.status !== "OPEN" ? "inactive" : ""}>
              <td><b>{a.action_title}</b>{a.action_description && <div className="muted small">{a.action_description}</div>}
                {a.completion_note && <div className="muted small">Done: {a.completion_note}{a.completed_by_name ? ` (${a.completed_by_name})` : ""}</div>}</td>
              {!enquiryId && <td className="small"><a href={`#/enquiries/${a.enquiry_id}`}>{a.enquiry_reference}</a></td>}
              <td>{a.assigned_to_name ?? "—"}{a.mine && <span className="muted"> (you)</span>}</td>
              <td className={a.overdue ? "bad-t" : a.due_today ? "warn-t" : ""}>{a.due_at ? day(a.due_at) : "—"}{a.overdue ? " · overdue" : a.due_today ? " · today" : ""}</td>
              <td><Pill tone={a.status === "OPEN" ? (a.overdue ? "bad" : "info") : "neutral"}>{a.status.toLowerCase()}</Pill></td>
              <td className="num nowrap">{a.status === "OPEN" && <>
                {(a.can_complete ?? (a.assigned_to === me.id || me.can.assign_followups)) && <Button kind="ghost" className="sm" onClick={() => setDone(a)}>Done</Button>}
                {me.can.assign_followups && <Button kind="ghost" className="sm" onClick={() => setEdit(a)}>Change</Button>}</>}</td>
            </tr>))}</tbody>
        </table></div>
      )}
      {done && <DoneDialog a={done} onClose={() => setDone(null)} onDone={after} />}
      {edit && <EditFollowUp a={edit} assignees={assignees} onClose={() => setEdit(null)} onDone={after} />}
      {add && enquiryId && <AddFollowUp enquiryId={enquiryId} assignees={assignees ?? []} onClose={() => setAdd(false)} onDone={after} />}
    </Card>
  );
}

function DoneDialog({ a, onClose, onDone }: { a: Action; onClose: () => void; onDone: (d: Detail) => void }) {
  const [note, setNote] = useState("");
  return (
    <FormDialog title={`Complete: ${a.action_title}`} submit="Mark done" onClose={onClose}
                onSubmit={async () => onDone(await api.patch<Detail>(`/enquiry-actions/${a.id}`, { status: "DONE", note }))}>
      <label className="field">What was done<textarea className="input" rows={3} required value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}

function EditFollowUp({ a, assignees, onClose, onDone }: { a: Action; assignees?: { id: number; name: string }[]; onClose: () => void; onDone: (d: Detail) => void }) {
  const people = useQuery({ queryKey: ["assignees"], queryFn: () => api.get<{ id: number; name: string }[]>("/assignees"), enabled: !assignees });
  const [due, setDue] = useState(a.due_at ?? "");
  const [who, setWho] = useState(a.assigned_to ? String(a.assigned_to) : "");
  return (
    <FormDialog title={`Change: ${a.action_title}`} submit="Save" onClose={onClose}
                onSubmit={async () => onDone(await api.patch<Detail>(`/enquiry-actions/${a.id}`, { due_at: due || null, assigned_to: who || null }))}>
      <label className="field">Assigned to<Select value={who} onChange={setWho} options={(assignees ?? people.data ?? []).map((p) => ({ value: String(p.id), label: p.name }))} /></label>
      <label className="field">Due<input className="input" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
      <Button type="button" kind="ghost" onClick={async () => { onDone(await api.patch<Detail>(`/enquiry-actions/${a.id}`, { status: "CANCELLED" })); onClose(); }}>Cancel this follow-up</Button>
    </FormDialog>
  );
}

function AddFollowUp({ enquiryId, assignees, onClose, onDone }: { enquiryId: number; assignees: { id: number; name: string }[]; onClose: () => void; onDone: (d: Detail) => void }) {
  const { me } = useApp();
  const [f, setF] = useState({ title: "", description: "", assigned_to: String(me.id), due_at: plusDays(14) });
  return (
    <FormDialog title="Add a follow-up" submit="Add" onClose={onClose} onSubmit={async () => onDone(await api.post<Detail>(`/enquiries/${enquiryId}/actions`, f))}>
      <p className="hint">{FOLLOW_UP_LINE}</p>
      <label className="field">What needs to be done<input className="input" required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="For example: chase IPRS for a reply" /></label>
      <label className="field">Details (optional)<textarea className="input" rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      {me.can.assign_followups ? <label className="field">Assigned to<Select value={f.assigned_to} onChange={(v) => setF({ ...f, assigned_to: v })}
                                                                             options={assignees.map((p) => ({ value: String(p.id), label: p.name }))} /></label>
        : <p className="hint">The follow-up is yours. An Admin can assign follow-ups to other people.</p>}
      <label className="field">Due<input className="input" type="date" value={f.due_at} onChange={(e) => setF({ ...f, due_at: e.target.value })} /></label>
    </FormDialog>
  );
}

// ================================================================== one enquiry
type Ev = { id: number; event_type: string; label: string; phase: "internal" | "external"; event_description: string; actor: string | null; event_timestamp: string; from_status: string | null; to_status: string | null };
type Detail = { enquiry: Enq; items: any[]; events: Ev[];
  actions: Action[]; communications: { id: number; communication_type: string; direction: string; subject: string | null; summary: string | null;
    message_reference: string | null; sender_reference: string | null; recipient_reference: string | null; communication_date: string; recorded_by_name: string;
    statement_filename: string | null; related_statement_id: number | null }[];
  allowed: { action: string; label: string }[]; run: { id: number; reference: string } | null; assignees: { id: number; name: string; role: string }[];
  can_assign: boolean; editable: boolean; text_current: boolean; comm_types: string[]; attachment: string | null; attachment_usage: string | null; usage_months: string | null;
  internal: { prepared_by: string; prepared_at: string; forwarded_to: string | null; forwarded_at: string | null; confirmed: boolean; confirmed_by: string | null;
    confirmed_at: string | null; method: string | null; note: string | null; recorded_by: string | null; waiting_on_me: boolean };
  can_copy: boolean; reminders: { sent: number; of: number; every_days: number }; confirm_methods: { value: string; label: string }[]; hold: string | null };

const PRIMARY = ["submit", "approve", "record_sent", "record_response", "resolve", "close"];
/** What a follow-up and a note do - and do not do - in one line each. */
const FOLLOW_UP_LINE = "A follow-up is a task for one person with a due date: it pops up for them and stays in their follow-ups until marked done. It does not send anything to IPRS and does not move the enquiry to the next step.";
const NOTE_LINE = "A note is a message to your colleague on this enquiry, kept in the notes below. It is not a task, has no due date and does not move the enquiry to the next step.";
const INTERNAL_TALK = ["REVIEW_REQUESTED", "INTERNAL_NOTE", "RETURNED_FOR_CORRECTION", "APPROVED", "CONFIRMATION_RECORDED"];
/** Now, as the value of a date-and-time field (local time). */
const nowLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

function EnquiryPage({ id }: { id: number }) {
  const { me, go, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["enquiry", id], queryFn: () => api.get<Detail>(`/enquiries/${id}`) });
  const [action, setAction] = useState<string | null>(null);
  const update = (d: Detail) => { qc.setQueryData(["enquiry", id], d); qc.invalidateQueries({ queryKey: ["enq-dash"] }); qc.invalidateQueries({ queryKey: ["enq-list"] }); };
  if (q.isError) return <Page title="Enquiry"><Notice tone="bad">{(q.error as Error).message}</Notice></Page>;
  if (!q.data) return <Loading />;
  const d = q.data;
  const e = d.enquiry;
  const quick = async (a: string) => {
    try {
      const x = await api.post<Detail>(`/enquiries/${id}/act`, { action: a });
      update(x);
      if (a !== "recheck") toast("Done.");
      else if (x.enquiry.status === "DRAFT_PREPARED") toast("All links are verified: the draft can now be forwarded for confirmation.");
      else toast(`Still ${x.enquiry.status_label.toLowerCase()}. ${x.hold ?? ""}`, true);
    } catch (x) { toast((x as Error).message, true); }
  };
  return (
    <Page title={e.enquiry_reference} intro={<>{e.platform} · {period(e.usage_period_start, e.usage_period_end)} · drafted by {e.created_by_name} {day(e.created_at)}
      {d.run && <> · from <a href={`#/reconciliation/${d.run.id}`}>{d.run.reference}</a></>}</>}
          actions={<>
            <Button kind="ghost" onClick={() => go("enquiries")}>All enquiries</Button>
            <DownloadButton kind="secondary" path={`/enquiries/${id}/annex`} onError={(m) => toast(m, true)}>Working paper (Excel)</DownloadButton>
          </>}>
      <Card title={<Pill tone={STATUS_TONE[e.status] ?? "neutral"}>{e.status_label}</Pill>}
            sub={<>Assigned to {e.assigned_to_name ?? "nobody"}{d.internal.confirmed && ` · confirmed by ${d.internal.confirmed_by} ${day(d.internal.confirmed_at)}`}
              {e.sent_at && ` · sent ${day(e.sent_at)} by ${e.sent_by_name} to ${e.recipient_reference} (${(e.send_channel ?? "").toLowerCase()})`}
              {e.last_response_at && ` · last response ${day(e.last_response_at)}`}{e.next_follow_up_at && ` · next follow-up ${day(e.next_follow_up_at)}`}</>}>
        {e.new_statement_review && <Notice tone="warn">A new IPRS statement was imported that may concern this enquiry. Review it before going further; nothing was resolved automatically.</Notice>}
        {e.returned_reason && d.editable && <Notice tone="warn">Returned for correction: {e.returned_reason}</Notice>}
        {e.status === "MAPPING_PENDING" && <Notice tone="warn">Some works of this query are not properly matched. {d.hold} An Admin verifies them in the <a href="#/catalogue">Catalogue</a>; then use <b>Check the links again</b>.
          {" "}Or withdraw this draft and raise the query again from the reconciliation: works that are not properly matched are then left out.</Notice>}
        {d.internal.waiting_on_me && <Notice tone="warn">{d.internal.prepared_by} forwarded this to you. Read the text, download both reports below, then <b>confirm the report</b> - or return it with a comment.</Notice>}
        {e.status === "APPROVED_TO_SEND" && <Notice tone="good">Confirmed by {d.internal.confirmed_by}. Copy the text, send it yourself (mail, letter or portal) with the attachment to IPRS / PRS, then <b>record that it was sent</b>. The application never sends it.</Notice>}
        {e.resolution_summary && <p><b>Resolution:</b> {e.resolution_summary}</p>}
        <div className="actions">
          {d.allowed.map((a) => (
            <Button key={a.action} kind={PRIMARY.includes(a.action) ? "primary" : a.action === "withdraw" ? "danger" : "secondary"}
                    onClick={() => (["recheck", "investigate"].includes(a.action) ? quick(a.action) : setAction(a.action))}>{a.label}</Button>))}
          {d.allowed.length === 0 && <span className="muted small">{e.status === "CLOSED" ? "This enquiry is closed." : "Nothing to do for your role at this step."}</span>}
        </div>
      </Card>
      <Internal d={d} onNote={d.allowed.some((a) => a.action === "internal_note") ? () => setAction("internal_note") : undefined} />
      <Draft key={`${e.subject}\n${e.draft_body}`} d={d} onSaved={update} />
      <FollowUps title="Follow-ups" sub={FOLLOW_UP_LINE} actions={d.actions} enquiryId={id} canAdd={e.status !== "CLOSED" && me.can.prepare} assignees={d.assignees} onChanged={update} />
      <Card title="External - with IPRS / PRS" sub={e.sent_at ? <>Sent {day(e.sent_at)} to {e.recipient_reference}. {e.last_response_at ? `Last reply ${day(e.last_response_at)}.` : `No reply yet · reminders sent: ${d.reminders.sent} of ${d.reminders.of} (every ${d.reminders.every_days} days); the ${d.reminders.of + 1}th is a call, escalated to the CEO of IPRS.`}</>
        : "Nothing is sent before the report is confirmed inside the company."}>
        {d.communications.length === 0 ? <p className="muted">Nothing recorded yet. A draft is not a sent message.</p> : (
          <ul className="plain">{d.communications.map((c) => (
            <li key={c.id} className="comm"><Pill tone={c.direction === "INBOUND" ? "info" : "neutral"}>{c.direction === "INBOUND" ? "Received" : "Sent"} · {c.communication_type.toLowerCase()}</Pill>
              <b> {day(c.communication_date)}</b> {c.summary}{c.recipient_reference && ` · to ${c.recipient_reference}`}{c.sender_reference && ` · from ${c.sender_reference}`}
              {c.message_reference && <span className="muted"> · ref {c.message_reference}</span>}
              {c.related_statement_id && <> · statement <a href={`#/statements/${c.related_statement_id}`}>{c.statement_filename}</a></>}
              <span className="muted small"> · recorded by {c.recorded_by_name}</span></li>))}</ul>
        )}
      </Card>
      <Card title="Activity log" sub="Every step of this enquiry, newest first: with IPRS / PRS (after it was sent), then inside the company.">
        {(["external", "internal"] as const).map((ph) => {
          const evs = d.events.filter((ev) => ev.phase === ph);
          return evs.length > 0 && <div key={ph}>
            <h3 className="phase-h">{ph === "external" ? "External - with IPRS / PRS" : "Internal - inside the company"}</h3>
            <Log events={evs} tints={tintsOf(d.events)} />
          </div>;
        })}
      </Card>
      {action && <ActionDialog id={id} action={action} d={d} onClose={() => setAction(null)} onDone={update} />}
    </Page>
  );
}

/** Each person's colour in the logs of one enquiry, in the order they first appear (the preparer first), so two people
 *  never share a colour and who said what reads at a glance. */
const TINTS = ["p1", "p2", "p3"];
const tintsOf = (events: Ev[]) => {
  const out: Record<string, string> = {};
  [...events].sort((a, b) => a.id - b.id).forEach((ev) => { if (ev.actor && !(ev.actor in out)) out[ev.actor] = TINTS[Object.keys(out).length % TINTS.length]; });
  return out;
};
const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** A log on its time line: who (a name tag), what they did (the step and its text), then the date and time. */
function Log({ events, tints }: { events: Ev[]; tints: Record<string, string> }) {
  return (
    <div className="log">
      <div className="log-row log-head" aria-hidden><span>Who</span><span>What</span><span>Date and time</span></div>
      <ul className="timeline">{events.map((ev) => {
        const who = ev.actor ?? "System";
        return (
          <li key={ev.id} className="log-row">
            <span className={`who-tag ${ev.actor ? tints[ev.actor] : "sys"}`}><span className="who-i" aria-hidden>{ev.actor ? initials(who) : "·"}</span><b>{who}</b></span>
            <div className="log-what"><span className="log-act">{ev.label}</span>{ev.event_description && <div>{ev.event_description}</div>}</div>
            <time className="log-when" dateTime={ev.event_timestamp}>{when(ev.event_timestamp)}</time>
          </li>);
      })}</ul>
    </div>
  );
}

/** The internal half: prepared, forwarded to a colleague, confirmed (in the application or recorded by hand), then sent -
 * with the notes that went back and forth. Only a confirmed report's text can be copied and sent. */
function Internal({ d, onNote }: { d: Detail; onNote?: () => void }) {
  const e = d.enquiry;
  const i = d.internal;
  const sent = !!e.sent_at;
  const talk = d.events.filter((ev) => ev.phase === "internal" && INTERNAL_TALK.includes(ev.event_type));
  const steps: [boolean, boolean, string][] = [
    [true, false, `Prepared by ${i.prepared_by} · ${day(i.prepared_at)}`],
    [!!i.forwarded_to || i.confirmed, e.status === "DRAFT_PREPARED",
      i.forwarded_to ? `Forwarded to ${i.forwarded_to}${i.forwarded_at ? ` · ${day(i.forwarded_at)}` : ""}` : i.confirmed ? "Not forwarded - confirmed outside the application" : "Forward it to a colleague to confirm the report"],
    [i.confirmed, e.status === "PENDING_APPROVAL",
      i.confirmed ? `Confirmed by ${i.confirmed_by}${i.method ? ` · ${i.method.toLowerCase()}` : ""}${i.confirmed_at ? ` · ${when(i.confirmed_at)}` : ""}${i.recorded_by && i.recorded_by !== i.confirmed_by ? ` · recorded by ${i.recorded_by}` : ""}${i.note ? ` - ${i.note}` : ""}`
        : `Waiting for ${i.forwarded_to ?? "a colleague"} to confirm - or record a confirmation given live or by text`],
    [sent, e.status === "APPROVED_TO_SEND", sent ? `Copied and sent to IPRS / PRS · ${day(e.sent_at)}` : "Copy the text and send it to IPRS / PRS"],
  ];
  return (
    <Card title="Internal - confirmation before sending" sub={<>A colleague confirms the report before it goes to IPRS / PRS; until then the text cannot be copied and the sending cannot be recorded.
            {onNote && <span className="line-note">{NOTE_LINE}</span>}</>}
          actions={onNote && <Button kind="ghost" className="sm" onClick={onNote}>Send a note</Button>}>
      <ol className="steps">{steps.map(([done, now, text], k) => (
        <li key={k} className={done ? "done" : now ? "now" : ""}><span className="dot">{done ? "✓" : k + 1}</span><span>{text}</span></li>))}</ol>
      {talk.length > 0 && (
        <More label={`Notes between ${i.prepared_by} and ${i.forwarded_to ?? i.confirmed_by ?? "the colleague"} (${talk.length})`}>
          <Log events={[...talk].reverse()} tints={tintsOf(d.events)} />
        </More>)}
    </Card>
  );
}

function Draft({ d, onSaved }: { d: Detail; onSaved: (x: Detail) => void }) {
  const { toast } = useApp();
  const [subject, setSubject] = useState(d.enquiry.subject);
  const [body, setBody] = useState(d.enquiry.draft_body);
  const [busy, setBusy] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const changed = subject !== d.enquiry.subject || body !== d.enquiry.draft_body;
  const songs = d.items.filter((i) => i.item_status !== "REMOVED").length;
  const rebuild = async () => {
    setRebuilding(true);
    try { onSaved(await api.patch<Detail>(`/enquiries/${d.enquiry.id}`, { rebuild: true })); toast("Text written again."); }
    catch (x) { toast((x as Error).message, true); } finally { setRebuilding(false); }
  };
  const copy = async () => { try { await navigator.clipboard.writeText(`${d.enquiry.subject}\n\n${d.enquiry.draft_body}`); toast("Copied."); } catch { toast("Copying is not available here; select the text instead.", true); } };
  return (
    <Card title="Enquiry text" sub={d.can_copy ? undefined : "Copy text opens once the report is confirmed (internal step above)."}
          actions={<Button kind="ghost" className="sm" disabled={!d.can_copy} onClick={copy}>Copy text</Button>}>
      {d.attachment && (<>
        <div className="attach">
          <span className="attach-ico" aria-hidden>📎</span>
          <div className="grow"><b className="wrap-any">{d.attachment}</b>
            <div className="muted small">Attachment · {int(songs)} songs: Internal No, song, ISRC · {d.enquiry.platform} amount, period and usage, distribution no. · IPRS royalty: amount, date, period, distribution no. · check: client revenue, received from IPRS, received %, variance %</div></div>
          <DownloadButton kind="primary" path={`/enquiries/${d.enquiry.id}/attachment`} onError={(m) => toast(m, true)}>Download attachment</DownloadButton>
        </div>
        {d.attachment_usage && (
          <div className="attach">
            <span className="attach-ico" aria-hidden>📎</span>
            <div className="grow"><b className="wrap-any">{d.attachment_usage}</b>
              <div className="muted small">Only {d.usage_months?.replace(/ - /g, " – ")}, the months with {d.enquiry.platform} usage - every figure is for these months: the songs with revenue in them, the full check (client revenue, expected value, received from IPRS, received %, variance %, variance amount), each song's usage and its revenue per usage (the song's total revenue ÷ its usage)</div></div>
            <DownloadButton kind="secondary" path={`/enquiries/${d.enquiry.id}/attachment?usage=true`} onError={(m) => toast(m, true)}>Download with usage</DownloadButton>
          </div>
        )}
      </>)}
      {d.editable && !d.text_current && (
        <Notice tone="warn">This text is not the letter for the {int(songs)} songs now in the enquiry: it lists the songs one by one (drafts from before version 1.5.2)
          or was edited. The songs are in the attachment, so the letter only gives their number and what is asked.
          {" "}Rebuilding replaces the subject and the text, edits included.
          <div className="actions"><Button kind="secondary" busy={rebuilding} onClick={rebuild}>Rebuild the text</Button></div></Notice>
      )}
      {d.editable ? (
        <form className="form full" onSubmit={async (e) => {
          e.preventDefault(); setBusy(true);
          try { onSaved(await api.patch<Detail>(`/enquiries/${d.enquiry.id}`, { subject, draft_body: body })); toast("Draft saved."); }
          catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
        }}>
          <label className="field">Subject<input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
          <label className="field">Text<textarea className="input draft" rows={16} value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <div className="actions"><Button kind="primary" type="submit" busy={busy} disabled={!changed}>Save draft</Button></div>
        </form>
      ) : (<><p><b>{d.enquiry.subject}</b></p><pre className="draft-view">{d.enquiry.draft_body}</pre></>)}
    </Card>
  );
}

function ActionDialog({ id, action, d, onClose, onDone }: { id: number; action: string; d: Detail; onClose: () => void; onDone: (x: Detail) => void }) {
  const { me } = useApp();
  const others = d.assignees.filter((p) => p.id !== me.id);
  const senior = others.find((p) => p.role !== "USER") ?? others[0];
  const [f, setF] = useState<Record<string, any>>({ sent_on: today(), date: today(), channel: "EMAIL", kind: "CORRECTION",
    assigned_to: d.enquiry.assigned_to ? String(d.enquiry.assigned_to) : "", reviewer: String(senior?.id ?? ""),
    method: "LIVE_DEMO", confirmed_by: String(senior?.id ?? ""), confirmed_by_name: "", confirmed_at: nowLocal() });
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const label = d.allowed.find((a) => a.action === action)?.label ?? action;
  const comm = <label className="field">How<Select value={f.channel} onChange={(v) => set("channel", v)} options={d.comm_types.map((c) => ({ value: c, label: c.toLowerCase() }))} /></label>;
  const note = (lbl: string, req = true) => <label className="field">{lbl}<textarea className="input" rows={3} required={req} value={f.note ?? ""} onChange={(e) => set("note", e.target.value)} /></label>;
  return (
    <FormDialog title={label} submit={label} danger={action === "withdraw"} onClose={onClose} wide={action === "resolve" || action === "partially_resolve"}
                onSubmit={async () => onDone(await api.post<Detail>(`/enquiries/${id}/act`, { action, ...f,
                  confirmed_by: f.confirmed_by === "other" ? null : f.confirmed_by, confirmed_at: f.confirmed_at ? new Date(f.confirmed_at).toISOString() : null }))}>
      {action === "record_sent" && <>
        <Notice>Record a sending you did yourself. The application does not send anything.</Notice>
        <label className="field">Sent to (IPRS recipient)<input className="input" required value={f.recipient ?? ""} onChange={(e) => set("recipient", e.target.value)} placeholder="name and email address" /></label>
        <label className="field">Sent on<input className="input" type="date" required max={today()} value={f.sent_on} onChange={(e) => set("sent_on", e.target.value)} /></label>
        {comm}
        <label className="field">Message reference (optional)<input className="input" value={f.message_reference ?? ""} onChange={(e) => set("message_reference", e.target.value)} /></label>
        <p className="hint">If IPRS / PRS does not reply within 7 days, reminder 1 is due: the same mail again. Then every 7 days, 3 times; the 4th reminder is a call, escalated to the CEO of IPRS.</p>
      </>}
      {(action === "record_response" || action === "record_follow_up") && <>
        <label className="field">Date<input className="input" type="date" required max={today()} value={f.date} onChange={(e) => set("date", e.target.value)} /></label>
        {comm}
        {action === "record_follow_up" && <p className="hint">Reminder {d.reminders.sent + 1}{d.reminders.sent + 1 > d.reminders.of ? ": the call to IPRS, escalated to the CEO (choose 'phone')" : ` of ${d.reminders.of}: the same mail again`}. The next one is scheduled 7 days later.</p>}
        <label className="field">{action === "record_response" ? "What IPRS / PRS said" : "What was sent or said"}<textarea className="input" rows={3} required value={f.summary ?? ""} onChange={(e) => set("summary", e.target.value)} /></label>
        <label className="field">{action === "record_response" ? "From" : "To"} (optional)<input className="input" value={f[action === "record_response" ? "sender" : "recipient"] ?? ""}
                                                                                                    onChange={(e) => set(action === "record_response" ? "sender" : "recipient", e.target.value)} /></label>
        <label className="field">Reference or attachment (optional)<input className="input" value={f.message_reference ?? ""} onChange={(e) => set("message_reference", e.target.value)} /></label>
        {action === "record_response" && <p className="hint">Recording a response does not resolve the enquiry: verify the explanation first.</p>}
      </>}
      {action === "submit" && <>
        <p>The colleague gets "Confirm the report" in their follow-ups and on their Home page. They read the text, download both reports and confirm them - or return them with a comment.</p>
        {others.length === 0 ? <Notice tone="warn">Nobody else has an account. Record the confirmation given outside the application instead.</Notice>
          : <label className="field">Colleague who confirms<Select value={f.reviewer} onChange={(v) => set("reviewer", v)} options={others.map((p) => ({ value: String(p.id), label: p.name, meta: p.role === "SUPER_ADMIN" ? "Super Admin" : p.role === "ADMIN" ? "Admin" : "User" }))} /></label>}
        {note("Note for them (optional)", false)}
      </>}
      {action === "approve" && <>
        <p>You confirm the text and both reports. After this the text can be copied and sent to IPRS / PRS.</p>
        {note("Comment (optional)", false)}
      </>}
      {action === "record_confirmation" && <>
        <p>The report was confirmed outside the application - for example shown live on this screen, or confirmed by a text message. Record who confirmed it, how and when.</p>
        <label className="field">How<Select value={f.method} onChange={(v) => set("method", v)} options={d.confirm_methods} /></label>
        <label className="field">Confirmed by<Select value={f.confirmed_by} onChange={(v) => set("confirmed_by", v)}
                                                    options={[...others.map((p) => ({ value: String(p.id), label: p.name })), { value: "other", label: "Someone else (type the name)" }]} /></label>
        {f.confirmed_by === "other" && <label className="field">Name<input className="input" required value={f.confirmed_by_name} onChange={(e) => set("confirmed_by_name", e.target.value)} /></label>}
        <label className="field">Date and time<input className="input" type="datetime-local" required max={nowLocal()} value={f.confirmed_at} onChange={(e) => set("confirmed_at", e.target.value)} /></label>
        {note(f.method === "OTHER" ? "How it was confirmed" : "Note (optional)", f.method === "OTHER")}
      </>}
      {action === "internal_note" && <><p className="hint">{NOTE_LINE}</p>{note("Note (the colleague and the preparer see it in the internal notes)")}</>}
      {action === "return" && note("What needs correcting")}
      {action === "note_correction" && <>
        <label className="field">What was found<Select value={f.kind} onChange={(v) => set("kind", v)} options={[{ value: "CORRECTION", label: "A correction" },
          { value: "ADDITIONAL_ROYALTY", label: "An additional royalty" }, { value: "PAYMENT", label: "A payment" }]} /></label>
        <label className="field">Amount (optional)<input className="input" inputMode="decimal" pattern={NUMBER_PATTERN} title="A number, for example 1250 or 1250.50"
                                                    value={f.amount ?? ""} onChange={(e) => set("amount", numeric(e.target.value))} /></label>
        {note("Details and evidence (for example the statement and distribution)")}
      </>}
      {(action === "resolve" || action === "partially_resolve") && <>
        {note(action === "resolve" ? "Resolution and its evidence" : "What is resolved and what is still open")}
        <More label="Outcome per item (optional)">
          {d.items.filter((i) => i.item_status !== "REMOVED").map((i) => (
            <div key={i.id} className="row-line"><span className="grow small">{i.work_title} ({i.internal_work_number})</span>
              <Select size="sm" value={(f.items ?? []).find((x: any) => x.item_id === i.id)?.status ?? i.item_status} onChange={(v) => set("items", [...(f.items ?? []).filter((x: any) => x.item_id !== i.id), { item_id: i.id, status: v }])}
                      options={[{ value: "OPEN", label: "Still open" }, { value: "PARTIALLY_RESOLVED", label: "Partly resolved" }, { value: "RESOLVED", label: "Resolved" }, { value: "NO_CHANGE", label: "No change needed" }]} /></div>))}
        </More>
      </>}
      {action === "close" && <>{note("How was the resolution verified?")}<p className="hint">Close only when the resolution has been verified (for example the later statement or payment was checked).</p></>}
      {action === "reopen" && note("Why", false)}
      {action === "withdraw" && note("Why it is withdrawn", false)}
      {action === "new_statement_reviewed" && note("What the new statement shows", false)}
      {action === "assign" && <label className="field">Assign to<Select value={f.assigned_to} onChange={(v) => set("assigned_to", v)} options={d.assignees.map((p) => ({ value: String(p.id), label: p.name }))} /></label>}
    </FormDialog>
  );
}
