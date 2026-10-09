import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { useApp } from "../state";
import { Card, Drawer, Empty, Field, Kv, Money, Outcome, PageHead, Pager, ReasonForm, Spinner, StateBadge, useDebounced } from "../components/ui";
import { dmy, plusDays, when, words } from "../format";

const STATUSES = ["OPEN", "AWAITING_REPLY", "REPLIED", "ADJUSTMENT_PROMISED", "CLOSED_EXPLAINED", "CLOSED_CORRECTED"];

export default function Cases({ caseId }: { caseId?: number }) {
  const { clientId, go } = useApp();
  const [status, setStatus] = useState("");
  const [due, setDue] = useState(false);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const dq = useDebounced(q);
  const list = useQuery({ queryKey: ["cases", clientId, status, due, dq, offset], queryFn: () => api.get<any>(`/cases${qs({ client_id: clientId, status, due, q: dq, offset, limit: 100 })}`) });
  const counts = Object.fromEntries((list.data?.counts ?? []).map((c: any) => [c.status, c.n]));
  return (
    <>
      <PageHead title="Enquiry cases" step="H4–H5">
        One case per comparison group, tracked across runs. Replies, promised adjustments and payments (pending / credited /
        received, kept separate) are logged as events; closing needs a reason and evidence, and the history is never removed.
      </PageHead>
      <div className="filters">
        <select className="input sm" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">all statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{words(s)} ({counts[s] ?? 0})</option>)}</select>
        <label className="check small"><input type="checkbox" checked={due} onChange={(e) => setDue(e.target.checked)} />follow-up due</label>
        <input className="input sm" placeholder="title, work code, case ID" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
      </div>
      <Card flush>
        {list.isLoading ? <Spinner /> : !list.data.rows.length ? <Empty>No cases.</Empty> : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Case ID</th><th>Work</th><th>Query</th><th className="num">B</th><th className="num">P</th><th className="num">V</th>
                <th>Status</th><th>Payment</th><th>Follow up</th><th>Next action</th></tr></thead>
              <tbody>{list.data.rows.map((c: any) => (
                <tr key={c.id} className="click" onClick={() => go(`cases/${c.id}`)}>
                  <td className="mono small nowrap">{c.case_code}</td><td className="wrap">{c.title}<div className="muted small mono">{c.work_code}</div></td>
                  <td>{c.outcome && <Outcome o={c.outcome} />}</td><td className="num"><Money v={c.b_amount} /></td><td className="num"><Money v={c.p_amount} /></td>
                  <td className="num"><Money v={c.variance} /></td><td><StateBadge state={c.status} /></td><td><StateBadge state={c.payment_status} /></td>
                  <td className="nowrap small">{dmy(c.follow_up_date)}</td><td className="small wrap">{c.next_action}</td>
                </tr>
              ))}</tbody>
            </table>
            <Pager total={list.data.total} offset={offset} limit={100} onChange={setOffset} />
          </div>
        )}
      </Card>
      {caseId && <CaseDrawer id={caseId} onClose={() => go("cases")} />}
    </>
  );
}

function CaseDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { can, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["case", id], queryFn: () => api.get<any>(`/cases/${id}`) });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/users") });
  const [reply, setReply] = useState<Record<string, string>>({ society_status: "", amount: "", period: "", correction_requested: "", expected_distribution: "", received_on: "", reference: "" });
  const [pay, setPay] = useState({ status: "PENDING", amount: "", reference: "" });
  const [keep, setKeep] = useState({ follow_up: plusDays(14), owner_id: "", requested: "" });
  const [closeAs, setCloseAs] = useState("CLOSED_EXPLAINED");
  const [evidence, setEvidence] = useState("");
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) => api.post<any>(`/cases/${id}/${path}`, body),
    onSuccess: (c) => { qc.setQueryData(["case", id], c); qc.invalidateQueries({ queryKey: ["cases"] }); toast(`Case ${words(c.status)}`); },
    onError: (e) => toast((e as Error).message, true),
  });
  const c = q.data;
  const open = c && !c.status.startsWith("CLOSED");
  return (
    <Drawer open onClose={onClose} wide title={c ? c.title : "Case"} sub={c && <><span className="mono">{c.case_code}</span> · work {c.work_code}</>}
            actions={c && <><StateBadge state={c.status} /><StateBadge state={c.payment_status}>payment {words(c.payment_status)}</StateBadge></>}>
      {!c ? <Spinner /> : (
        <div className="col" style={{ gap: 16 }}>
          <div className="split">
            <Card title="Latest comparison">
              {c.group && <Kv items={[
                ["Outcome", <Outcome o={c.group.outcome} reason={c.group.hold_reason} />],
                ["R / N", <><Money v={c.group.r_amount} /> · {c.group.n_streams ?? "—"} streams</>],
                ["B / P / V", <><Money v={c.group.b_amount} /> / <Money v={c.group.p_amount} /> / <Money v={c.group.variance} /></>],
                ["Publishing status", words(c.group.p_status)],
                ["Question", c.group.question],
              ]} />}
              {c.runs.length > 1 && <div className="muted small" style={{ marginTop: 8 }}>Seen in runs: {c.runs.map((r: any) => `v${r.version_no} (${words(r.outcome)})`).join(", ")}</div>}
            </Card>
            <Card title="History" sub="append-only">
              <div className="timeline">
                {c.history.map((e: any) => (
                  <div key={e.id} className="ev"><b>{words(e.kind)}</b> <span className="muted small">{when(e.at)} · {e.actor_name ?? "system"}</span>
                    <div className="small ink2">{Object.entries(e.detail).filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${words(k)}: ${v}`).join(" · ")}</div></div>
                ))}
              </div>
            </Card>
          </div>
          {c.reply?.reference && <Card title="Reply on record"><Kv items={Object.entries(c.reply).filter(([, v]) => v).map(([k, v]) => [words(k), String(v)])} /></Card>}
          {open && can("send") && (
            <Card title="H4 · Log the reply" sub="against this case ID; an expected distribution makes it a promised adjustment">
              <div className="form-grid">
                {Object.keys(reply).map((k) => <Field key={k} label={words(k)}><input className="input" type={k === "received_on" ? "date" : "text"} value={reply[k]} onChange={(e) => setReply({ ...reply, [k]: e.target.value })} /></Field>)}
              </div>
              <div style={{ marginTop: 10 }}><ReasonForm label="Reason given in the reply" button="Log reply" busy={act.isPending} onSubmit={(t) => act.mutate({ path: "reply", body: { ...reply, reason: t } })} /></div>
            </Card>
          )}
          {open && can("case_update") && (
            <Card title="Keep open" sub="record the reason, requested data and the next owner/date">
              <div className="form-grid">
                <Field label="Next follow-up"><input className="input" type="date" value={keep.follow_up} onChange={(e) => setKeep({ ...keep, follow_up: e.target.value })} /></Field>
                <Field label="Owner"><select className="input" value={keep.owner_id} onChange={(e) => setKeep({ ...keep, owner_id: e.target.value })}><option value="" />{users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
                <Field label="Requested data / next action"><input className="input" value={keep.requested} onChange={(e) => setKeep({ ...keep, requested: e.target.value })} /></Field>
              </div>
              <div style={{ marginTop: 10 }}><ReasonForm label="Why it stays open" button="Keep open" busy={act.isPending} onSubmit={(t) => act.mutate({ path: "keep-open", body: { ...keep, reason: t } })} /></div>
            </Card>
          )}
          {can("payment") && (
            <Card title="Payment tracking" sub="pending, credited and received are separate; link the later statement or receipt">
              <div className="form-grid">
                <Field label="Status"><select className="input" value={pay.status} onChange={(e) => setPay({ ...pay, status: e.target.value })}><option>PENDING</option><option>CREDITED</option><option>RECEIVED</option></select></Field>
                <Field label="Amount"><input className="input" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
                <Field label="Statement / receipt reference"><input className="input" value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field>
              </div>
              <div className="row" style={{ marginTop: 10 }}><button className="btn" disabled={act.isPending} onClick={() => act.mutate({ path: "payment", body: pay })}>Record payment status</button></div>
              {c.linked_refs?.length > 0 && <div className="muted small" style={{ marginTop: 8 }}>{c.linked_refs.map((r: any) => `${words(r.kind)} ${r.amount ?? ""} ${r.reference} (${r.by})`).join(" · ")}</div>}
            </Card>
          )}
          {open && can("case_update") && (
            <Card title="H5 · Close with reason + evidence" sub="promised adjustments stay open until credited or received">
              <div className="form-grid">
                <Field label="Resolution"><select className="input" value={closeAs} onChange={(e) => setCloseAs(e.target.value)}><option value="CLOSED_EXPLAINED">Explained / no adjustment</option><option value="CLOSED_CORRECTED">Correction completed</option></select></Field>
                <Field label="Evidence"><input className="input" value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="reply / statement / receipt reference" /></Field>
              </div>
              <div style={{ marginTop: 10 }}><ReasonForm label="Reason" button="Close case" busy={act.isPending} onSubmit={(t) => act.mutate({ path: "close", body: { outcome: closeAs, reason: t, evidence } })} /></div>
            </Card>
          )}
          {!open && <div className="note">Closed: {c.close_reason} · evidence: {c.close_evidence}. A later run that still flags this work re-opens it.</div>}
        </div>
      )}
    </Drawer>
  );
}
