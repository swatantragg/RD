import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download, qs } from "../api";
import { useApp } from "../state";
import { Card, Empty, Field, Kv, PageHead, ReasonForm, Spinner, StateBadge } from "../components/ui";
import { int, period, plusDays, today, when } from "../format";

export default function Packs() {
  const { clientId } = useApp();
  const list = useQuery({ queryKey: ["packs", clientId], queryFn: () => api.get<any[]>(`/packs${qs({ client_id: clientId })}`) });
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => { if (!sel && list.data?.length) setSel(list.data[0].id); }, [list.data, sel]);
  return (
    <>
      <PageHead title="Report packs" step="H1–H4">
        The Excel evidence pack (7 sheets), the client summary and the editable email. The route is the client's evidenced
        collection path. Approval is by someone other than the builder; <b>export is not dispatch</b> - a pack counts as
        sent only when an authorised person records it.
      </PageHead>
      {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty>No packs yet - build one from a comparison run.</Empty> : (
        <div className="split" style={{ gridTemplateColumns: "minmax(0, 0.8fr) minmax(0, 1.6fr)" }}>
          <Card title="Packs" flush>
            <table className="tbl">
              <thead><tr><th>Pack</th><th>Run</th><th>Status</th><th className="num">Cases</th><th>Built</th></tr></thead>
              <tbody>{list.data.map((p) => (
                <tr key={p.id} className={`click ${sel === p.id ? "sel" : ""}`} onClick={() => setSel(p.id)}>
                  <td>v{p.version_no} · {p.route}</td><td>run v{p.run_version} · {p.platform}</td><td><StateBadge state={p.status} /></td>
                  <td className="num">{int(p.case_codes.length)}</td><td className="small">{p.built_by_name}<div className="muted">{when(p.built_at)}</div></td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
          {sel && <PackDetail id={sel} />}
        </div>
      )}
    </>
  );
}

function PackDetail({ id }: { id: number }) {
  const { can, me, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pack", id], queryFn: () => api.get<any>(`/packs/${id}`) });
  const [body, setBody] = useState<string | null>(null);
  const [sent, setSent] = useState({ reference: "", follow_up: plusDays(14), sent_on: today() });
  const act = useMutation({
    mutationFn: ({ path, b }: { path: string; b?: unknown }) => api.post<any>(path, b ?? {}),
    onSuccess: (p) => { qc.invalidateQueries(); toast(p?.status ? `Pack ${p.status.toLowerCase().replace("_", " ")}` : "Done"); },
    onError: (e) => toast((e as Error).message, true),
  });
  if (q.isLoading || !q.data) return <Spinner />;
  const p = q.data;
  const text = body ?? p.email_body;
  return (
    <div className="col" style={{ gap: 16 }}>
      <Card title={`Pack v${p.version_no} · ${p.route} · ${p.platform} ${period(p.period_from, p.period_to)}`} sub={`sha256 ${p.sha256?.slice(0, 20)}…`}
            actions={<><StateBadge state={p.status} /><button className="btn sm" onClick={() => download(`/packs/${id}/download`)}>Download Excel pack</button></>}>
        <Kv items={[
          ["Recipient", p.recipient],
          ["Built", `${p.built_by_name} · ${when(p.built_at)}`],
          ["Approved", p.approved_by_name ? `${p.approved_by_name} · ${when(p.approved_at)}` : "—"],
          ["Sent", p.sent_by_name ? `${p.sent_by_name} · ${when(p.sent_at)} · ref ${p.sent_reference} · follow up ${p.follow_up_date}` : "not recorded"],
          ["Review note", p.review_note ?? "—"],
          ["Enquiry cases", int(p.case_codes.length)],
        ]} />
        <div className="row wrap" style={{ marginTop: 12 }}>
          {p.status === "DRAFT" && can("pack_approve") && p.built_by !== me.id &&
            <button className="btn primary" disabled={act.isPending} onClick={() => act.mutate({ path: `/packs/${id}/approve` })}>H3 · Approve pack</button>}
          {p.status === "DRAFT" && p.built_by === me.id && <span className="muted small">You built this pack - another authorised reviewer must approve it.</span>}
          {p.status === "REVISION_REQUESTED" && can("pack_build") &&
            <button className="btn primary" disabled={act.isPending} onClick={() => act.mutate({ path: `/runs/${p.run_id}/packs`, b: { note: "revised after review" } })}>Build revised version</button>}
        </div>
      </Card>
      {["DRAFT", "APPROVED"].includes(p.status) && can("pack_approve") && (
        <Card title="Revise draft" sub="scope, totals, sources, confidential data or wording - no unsupported 'amount due' claim">
          <ReasonForm label="What must be corrected" button="Request revision" danger busy={act.isPending} onSubmit={(t) => act.mutate({ path: `/packs/${id}/revise`, b: { note: t } })} />
        </Card>
      )}
      {p.status === "APPROVED" && can("send") && (
        <Card title="H4 · Record dispatch" sub="send from your mail client with the Excel attached, then record it here">
          <div className="form-grid">
            <Field label="Dispatch reference"><input className="input" value={sent.reference} onChange={(e) => setSent({ ...sent, reference: e.target.value })} placeholder="email subject / message ID" /></Field>
            <Field label="Sent on"><input className="input" type="date" value={sent.sent_on} onChange={(e) => setSent({ ...sent, sent_on: e.target.value })} /></Field>
            <Field label="Follow-up date"><input className="input" type="date" value={sent.follow_up} onChange={(e) => setSent({ ...sent, follow_up: e.target.value })} /></Field>
          </div>
          <div className="row" style={{ marginTop: 10 }}><button className="btn primary" disabled={!sent.reference || act.isPending} onClick={() => act.mutate({ path: `/packs/${id}/sent`, b: sent })}>Record as sent</button></div>
        </Card>
      )}
      <Card title="Email draft" sub={p.email_subject}
            actions={<button className="btn sm" onClick={() => { navigator.clipboard?.writeText(`Subject: ${p.email_subject}\n\n${text}`); toast("Email copied"); }}>Copy</button>}>
        <textarea className="input email" style={{ width: "100%", minHeight: 420, fontFamily: "var(--font)" }} value={text} onChange={(e) => setBody(e.target.value)} />
        <div className="muted small" style={{ marginTop: 6 }}>Editable before sending; the pack keeps the generated version on record.</div>
      </Card>
    </div>
  );
}
