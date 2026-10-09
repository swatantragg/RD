import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { useApp } from "../state";
import {
  Card, Checks, Empty, ErrorNote, Field, Int, Money, PageHead, Pager, ReasonForm, Spinner, Stat, StateBadge, Tabs, useDebounced,
} from "../components/ui";
import { int, money, when, words } from "../format";

type Tab = "issues" | "candidates" | "links" | "versions";

export default function Identity() {
  const { clientId, can, toast } = useApp();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("issues");
  const sum = useQuery({ queryKey: ["idsum", clientId], queryFn: () => api.get<any>(`/identity/${clientId}/summary`) });
  const refresh = useMutation({
    mutationFn: () => api.post<any>(`/identity/${clientId}/refresh`),
    onSuccess: (r) => { qc.invalidateQueries(); toast(`Registers rebuilt: ${r.issues} open issue(s), ${r.candidates} candidate pair(s)`); },
    onError: (e) => toast((e as Error).message, true),
  });
  const s = sum.data;
  return (
    <>
      <PageHead title="Works & recordings" step="C1–C5"
                actions={can("identity") && <button className="btn" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
                  {refresh.isPending && <Spinner />}C1 · Load catalogue & validated files</button>}>
        A composition register (work codes), a recording register (ISRCs) and an approved link table. A work can have many
        recordings; a medley links to several works with an allocation. Fuzzy spellings only <i>propose</i> candidates - no
        title-only merge, no automatic deletion.
      </PageHead>
      {s && (
        <div className="kpis section">
          <Stat label="Works (register)" value={int(s.compositions)} />
          <Stat label="Recordings (register)" value={int(s.recordings)} />
          <Stat label="Approved links" value={int(s.links_approved)} meta={`${int(s.links_proposed)} proposed (conflicts)`} />
          <Stat label="Open identity issues" value={int(s.issues_open)} />
          <Stat label="Duplicate candidates pending" value={int(s.candidates_pending)} />
          <Stat label="Approved identity version" value={s.version ? `v${s.version.version_no}` : "none"} meta={s.version ? when(s.version.approved_at) : "C5 needed before any comparison"} />
        </div>
      )}
      <Tabs value={tab} onChange={setTab} items={[
        { key: "issues", label: "C2/C3 · Identity & mapping review", count: s?.issues_open },
        { key: "candidates", label: "C4 · Duplicate decisions", count: s?.candidates_pending },
        { key: "links", label: "Link table", count: s?.links_approved },
        { key: "versions", label: "C5 · Approved versions" },
      ]} />
      {tab === "issues" && <Issues />}
      {tab === "candidates" && <Candidates />}
      {tab === "links" && <Links />}
      {tab === "versions" && <Versions />}
    </>
  );
}

const KIND_LABEL: Record<string, string> = {
  UNMAPPED_RECORDING: "Recording with income, no approved work link", ISRC_CONFLICT: "ISRC listed under several works",
  WORK_NOT_IN_CATALOGUE: "Paid work not in client catalogue", WORK_WITHOUT_RECORDING: "Catalogue work without a linked recording",
  TITLE_MISMATCH: "Statement vs catalogue title differ",
};

function Issues() {
  const { clientId, can, toast } = useApp();
  const qc = useQueryClient();
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("OPEN");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const dq = useDebounced(q);
  const list = useQuery({ queryKey: ["issues", clientId, kind, status, dq, offset],
    queryFn: () => api.get<any>(`/identity/${clientId}/issues${qs({ kind, status, q: dq, offset, limit: 50 })}`) });
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) => api.post(path, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["issues"] }); qc.invalidateQueries({ queryKey: ["idsum"] }); setOpen(null); toast("Decision recorded"); },
    onError: (e) => toast((e as Error).message, true),
  });
  return (
    <Card flush>
      <div className="filters" style={{ padding: "12px 12px 0" }}>
        <select className="input sm" value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }}>
          <option value="">all kinds</option>{Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select className="input sm" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="OPEN">open</option><option value="RESOLVED">resolved</option><option value="DEFERRED">deferred</option><option value="">all</option></select>
        <input className="input sm" placeholder="search title / code" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
      </div>
      {list.isLoading ? <Spinner /> : list.error ? <ErrorNote error={list.error} /> : !list.data.rows.length ? <Empty>No issues here.</Empty> : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Kind</th><th>Subject</th><th>Title</th><th className="num">Amount</th><th className="num">Streams</th><th>Status</th><th /></tr></thead>
            <tbody>
              {list.data.rows.map((i: any) => (
                <Fragment key={i.id}>
                  <tr className="click" onClick={() => setOpen(open === i.id ? null : i.id)}>
                    <td className="small">{KIND_LABEL[i.kind] ?? i.kind}</td><td className="mono">{i.subject_key}</td><td className="wrap">{i.title}</td>
                    <td className="num"><Money v={i.amount} /></td><td className="num"><Int v={i.detail.streams} /></td>
                    <td><StateBadge state={i.status} />{i.resolution && <div className="muted small">{i.resolution}</div>}</td>
                    <td><button className="btn sm">{open === i.id ? "Close" : "Review"}</button></td>
                  </tr>
                  {open === i.id && (
                    <tr><td colSpan={7} style={{ background: "var(--surface-2)" }}>
                      <IssueReview i={i} can={can("identity")} busy={act.isPending} run={(path, body) => act.mutate({ path, body })} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <Pager total={list.data.total} offset={offset} limit={50} onChange={setOffset} />
        </div>
      )}
    </Card>
  );
}

function IssueReview({ i, can, busy, run }: { i: any; can: boolean; busy: boolean; run: (p: string, b: unknown) => void }) {
  const { clientId } = useApp();
  const [work, setWork] = useState<number | null>(i.detail.candidates?.[0]?.composition_id ?? null);
  const [search, setSearch] = useState("");
  const [isrc, setIsrc] = useState("");
  const [choice, setChoice] = useState<Record<number, { keep: boolean; allocation: string }>>({});
  const ds = useDebounced(search);
  const works = useQuery({ queryKey: ["works", clientId, ds], queryFn: () => api.get<any[]>(`/identity/${clientId}/works${qs({ q: ds })}`), enabled: ds.length > 1 });
  return (
    <div className="col" style={{ gap: 10, padding: 6 }}>
      <div className="ink2">{i.detail.why}</div>
      {i.kind === "UNMAPPED_RECORDING" && (
        <>
          <div className="small"><b>Candidates</b> (title evidence only - confirm film, composer, performer and version):</div>
          {(i.detail.candidates ?? []).map((c: any) => (
            <label key={c.composition_id} className="check"><input type="radio" checked={work === c.composition_id} onChange={() => setWork(c.composition_id)} />
              <span className="mono">{c.work_code}</span> {c.title} <span className="muted small">score {c.score}</span></label>
          ))}
          <div className="row"><input className="input sm" placeholder="search another work…" value={search} onChange={(e) => setSearch(e.target.value)} />
            {works.data?.map((w) => <button key={w.id} className={`btn sm ${work === w.id ? "primary" : ""}`} onClick={() => setWork(w.id)}>{w.work_code} {w.title}</button>)}</div>
        </>
      )}
      {["WORK_NOT_IN_CATALOGUE", "WORK_WITHOUT_RECORDING"].includes(i.kind) && (
        <Field label="Link a recording to this work (ISRC)"><input className="input sm" value={isrc} onChange={(e) => setIsrc(e.target.value)} placeholder="e.g. INS2X1400012" /></Field>
      )}
      {i.kind === "TITLE_MISMATCH" && <div>Statement: <b>{i.detail.statement_title}</b> · Catalogue: <b>{i.detail.catalogue_title}</b></div>}
      {i.kind === "ISRC_CONFLICT" && (
        <table className="tbl"><thead><tr><th>Keep</th><th>Work</th><th>Title</th><th>Allocation (medley)</th></tr></thead>
          <tbody>{i.detail.works.map((w: any) => (
            <tr key={w.link_id}><td><input type="checkbox" checked={!!choice[w.link_id]?.keep} onChange={(e) => setChoice({ ...choice, [w.link_id]: { keep: e.target.checked, allocation: choice[w.link_id]?.allocation ?? "" } })} /></td>
              <td className="mono">{w.work_code}</td><td>{w.title}</td>
              <td><input className="input sm" style={{ width: 90 }} placeholder="e.g. 0.5" value={choice[w.link_id]?.allocation ?? ""} onChange={(e) => setChoice({ ...choice, [w.link_id]: { keep: choice[w.link_id]?.keep ?? true, allocation: e.target.value } })} /></td></tr>
          ))}</tbody></table>
      )}
      {can && i.status !== "RESOLVED" && (
        <div className="split">
          {i.kind === "UNMAPPED_RECORDING" && <ReasonForm label="Evidence for the link (film, composer, performer, version)" button="Approve link" busy={busy}
            onSubmit={(t) => work && run(`/identity/issues/${i.id}/link`, { composition_id: work, reason: t })} />}
          {["WORK_NOT_IN_CATALOGUE", "WORK_WITHOUT_RECORDING"].includes(i.kind) && <ReasonForm label="Evidence for the link" button="Approve link" busy={busy}
            onSubmit={(t) => isrc && run(`/identity/issues/${i.id}/link`, { isrc, reason: t })} />}
          {i.kind === "ISRC_CONFLICT" && <ReasonForm label="Evidence for the decision" button="Resolve conflict" busy={busy}
            onSubmit={(t) => run(`/identity/issues/${i.id}/conflict`, { reason: t, choices: i.detail.works.map((w: any) => ({ link_id: w.link_id, keep: !!choice[w.link_id]?.keep, allocation: choice[w.link_id]?.allocation || null })) })} />}
          <ReasonForm label="Or record a resolution without a link (e.g. not the client's work, wrong code confirmed)" button="Resolve" busy={busy}
            onSubmit={(t) => run(`/identity/issues/${i.id}/resolve`, { resolution: t, status: "RESOLVED" })}
            extra={<button className="btn sm" onClick={() => run(`/identity/issues/${i.id}/resolve`, { resolution: "deferred for evidence", status: "DEFERRED" })}>Defer</button>} />
        </div>
      )}
    </div>
  );
}

function Candidates() {
  const { clientId, can, toast } = useApp();
  const qc = useQueryClient();
  const [status, setStatus] = useState("PENDING");
  const [offset, setOffset] = useState(0);
  const list = useQuery({ queryKey: ["cands", clientId, status, offset], queryFn: () => api.get<any>(`/identity/${clientId}/candidates${qs({ status, offset, limit: 30 })}`) });
  const act = useMutation({
    mutationFn: ({ id, decision, reason }: { id: number; decision: string; reason: string }) => api.post(`/identity/candidates/${id}`, { decision, reason }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["cands"] }); qc.invalidateQueries({ queryKey: ["idsum"] }); toast("Decision recorded"); },
    onError: (e) => toast((e as Error).message, true),
  });
  return (
    <>
      <div className="filters">
        <select className="input sm" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          {["PENDING", "SAME", "SEPARATE", "DEFERRED", ""].map((s) => <option key={s} value={s}>{s ? words(s) : "all"}</option>)}</select>
        <span className="legend">Candidates are works with the same title after transliteration folding. Covers, lo-fi and other versions are never paired with the original.</span>
      </div>
      {list.isLoading ? <Spinner /> : !list.data.rows.length ? <Empty>No candidates here.</Empty> : (
        <div className="col">
          {list.data.rows.map((c: any) => (
            <Card key={c.id} title={c.differences.titles.join("  ↔  ")} sub={`score ${c.score} · ${c.basis}`}
                  actions={<StateBadge state={c.status} />}>
              <table className="cmp"><tbody>
                <tr><th>Work code</th><td className="mono">{c.differences.work_codes[0]}</td><td className="mono">{c.differences.work_codes[1]}</td></tr>
                <tr><th>Title</th><td>{c.differences.titles[0]}</td><td>{c.differences.titles[1]}</td></tr>
                <tr><th>Film</th><td>{c.differences.films[0] ?? "—"}</td><td>{c.differences.films[1] ?? "—"}</td></tr>
                <tr><th>Linked ISRCs</th><td className="mono small">{c.differences.isrcs_a.join(", ") || "—"}</td><td className="mono small">{c.differences.isrcs_b.join(", ") || "—"}</td></tr>
                <tr><th>Shared ISRCs</th><td colSpan={2} className="mono small">{c.differences.shared_isrcs.join(", ") || "none"}</td></tr>
              </tbody></table>
              {c.reason && <div className="muted small" style={{ marginTop: 8 }}>{c.decided_by_name}: {c.reason}</div>}
              {can("identity") && <CandForm busy={act.isPending} onSubmit={(decision, reason) => act.mutate({ id: c.id, decision, reason })} />}
            </Card>
          ))}
          <Pager total={list.data.total} offset={offset} limit={30} onChange={setOffset} />
        </div>
      )}
    </>
  );
}

function CandForm({ onSubmit, busy }: { onSubmit: (d: string, r: string) => void; busy: boolean }) {
  const [d, setD] = useState("SEPARATE");
  return (
    <div style={{ marginTop: 10 }}>
      <ReasonForm label="Reason" button="Record decision" busy={busy} onSubmit={(t) => onSubmit(d, t)}
        extra={<select className="input sm" value={d} onChange={(e) => setD(e.target.value)}>
          <option value="SAME">Same entity (second points to first; nothing deleted)</option>
          <option value="SEPARATE">Keep separate</option>
          <option value="DEFERRED">Defer (kept separate, listed for review)</option></select>} />
    </div>
  );
}

function Links() {
  const { clientId, can, toast } = useApp();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const dq = useDebounced(q);
  const list = useQuery({ queryKey: ["links", clientId, dq, status, offset], queryFn: () => api.get<any>(`/identity/${clientId}/links${qs({ q: dq, status, offset, limit: 50 })}`) });
  const act = useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: string }) => api.post(`/identity/links/${id}`, { decision, reason: window.prompt("Reason for this decision?") ?? "" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["links"] }); toast("Link decision recorded"); },
    onError: (e) => toast((e as Error).message, true),
  });
  return (
    <Card flush>
      <div className="filters" style={{ padding: "12px 12px 0" }}>
        <input className="input sm" placeholder="title, work code or ISRC" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <select className="input sm" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">all</option><option value="APPROVED">approved</option><option value="PROPOSED">proposed</option><option value="REJECTED">rejected</option></select>
      </div>
      {list.isLoading ? <Spinner /> : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Work</th><th>Work title</th><th>ISRC</th><th>Recording title</th><th>Basis</th><th>Allocation</th><th>Status</th><th>Decided</th><th /></tr></thead>
            <tbody>{list.data.rows.map((l: any) => (
              <tr key={l.id}><td className="mono">{l.work_code}</td><td>{l.work_title}</td><td className="mono">{l.isrc}</td><td>{l.recording_title}</td>
                <td className="small">{words(l.basis)}{l.evidence?.row ? <span className="muted"> · row {l.evidence.row}</span> : null}</td>
                <td>{l.allocation ?? "—"}</td><td><StateBadge state={l.status} /></td>
                <td className="small">{l.decided_by_name}{l.reason && <div className="muted">{l.reason}</div>}</td>
                <td>{can("identity") && l.status !== "REJECTED" && <button className="btn sm" onClick={() => act.mutate({ id: l.id, decision: "REJECTED" })}>Reject</button>}
                  {can("identity") && l.status !== "APPROVED" && <button className="btn sm" onClick={() => act.mutate({ id: l.id, decision: "APPROVED" })}>Approve</button>}</td></tr>
            ))}</tbody>
          </table>
          <Pager total={list.data.total} offset={offset} limit={50} onChange={setOffset} />
        </div>
      )}
    </Card>
  );
}

function Versions() {
  const { clientId, can, toast } = useApp();
  const qc = useQueryClient();
  const v = useQuery({ queryKey: ["versions", clientId], queryFn: () => api.get<any[]>(`/identity/${clientId}/versions`) });
  const chk = useQuery({ queryKey: ["vcheck", clientId], queryFn: () => api.get<any>(`/identity/${clientId}/version-check`) });
  const approve = useMutation({
    mutationFn: (note: string) => api.post<any>(`/identity/${clientId}/versions`, { note }),
    onSuccess: (r) => { qc.invalidateQueries(); r.ok ? toast(`Identity version v${r.version_no} approved`) : toast("Rebuild hold - see the failed checks", true); },
    onError: (e) => toast((e as Error).message, true),
  });
  return (
    <div className="split">
      <Card title="C5 · Does the new version preserve totals?" sub="checks run on the current approved links">
        {chk.isLoading ? <Spinner /> : <>
          <Checks items={chk.data.checks} />
          <div className="muted small" style={{ marginTop: 8 }}>Links {int(chk.data.counts.links)} · recording income mapped {money(chk.data.counts.r_mapped)} · unmapped {money(chk.data.counts.r_unmapped)}</div>
        </>}
        {can("identity_approve") && <div style={{ marginTop: 12 }}><ReasonForm label="Note for this version" button="Approve identity version" busy={approve.isPending} onSubmit={(t) => approve.mutate(t)} /></div>}
        {approve.data && !approve.data.ok && <div className="note crit" style={{ marginTop: 10 }}>REBUILD HOLD - repair the links or revert the decision, then re-run C5.</div>}
      </Card>
      <Card title="Approved versions" sub="frozen snapshots; runs record the version they used" flush>
        {v.data?.length ? (
          <table className="tbl"><thead><tr><th>Version</th><th>Status</th><th>Links</th><th>Approved</th><th>Note</th></tr></thead>
            <tbody>{v.data.map((x) => <tr key={x.id}><td>v{x.version_no}</td><td><StateBadge state={x.status} /></td><td className="num">{int(x.counts.links)}</td>
              <td className="small">{x.approved_by_name}<div className="muted">{when(x.approved_at)}</div></td><td className="small">{x.note}</td></tr>)}</tbody></table>
        ) : <Empty>No approved version yet.</Empty>}
      </Card>
    </div>
  );
}
