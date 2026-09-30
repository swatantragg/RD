// Merge Review (§12) - the platform proposes, the user decides, the decision is stored,
// applied into a NEW build, and reversible.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api";
import {
  Badge, BasisChips, Card, ConfBar, Empty, ErrorNote, InvariantList, PageHead, Seg, Spinner, StatusChip, useDebounced,
} from "../components/ui";
import { money, monthLabel } from "../format";
import { useApp, useRunJob } from "../state";
import type { Build, Candidate } from "../types";

const EXACT = "SAME_NAME_DIFF_ISRC,SAME_NAME_DIFF_INTERNAL_NO,SAME_NAME_NO_IDENTIFIER";
const KIND_LABEL: Record<string, string> = {
  SAME_NAME_DIFF_ISRC: "same name · different ISRC",
  SAME_NAME_DIFF_INTERNAL_NO: "same name · different internal no",
  SAME_NAME_NO_IDENTIFIER: "same name · one side lacks an identifier",
  VERSION_VARIANT: "version variant (proposal only)",
};

export default function Merge() {
  const { buildId, canDecide, setBuildId } = useApp();
  const run = useRunJob();
  const qc = useQueryClient();
  const [kind, setKind] = useState(EXACT);
  const [band, setBand] = useState("");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [err, setErr] = useState<unknown>(null);
  const [applied, setApplied] = useState<{ build_id: number } | null>(null);
  const dq = useDebounced(q);
  const build = useQuery({ queryKey: ["build", buildId], queryFn: () => api.get<Build>(`/builds/${buildId}`), enabled: !!buildId });
  const list = useQuery({
    queryKey: ["cands", buildId, kind, band, status, dq, page],
    queryFn: () => api.withTotal<Candidate[]>(`/builds/${buildId}/merge-candidates${qs({ kind, band, status, q: dq, offset: page * 25, limit: 25 })}`),
    enabled: !!buildId, placeholderData: (p) => p,
  });
  const log = useQuery({ queryKey: ["decisions", buildId], queryFn: () => api.get<any[]>(`/builds/${buildId}/merge-decisions`), enabled: !!buildId });
  if (!buildId) return <Empty>No build yet.</Empty>;
  const b = build.data;
  const active = (log.data ?? []).filter((d) => d.active);
  const merges = active.filter((d) => d.verdict === "MERGE");
  const applyAll = () => {
    setErr(null);
    run("Apply merges → new build", () => api.post(`/builds/${buildId}/apply-merges`), (j) => {
      if (j.status === "succeeded" && j.result?.build_id) { setApplied({ build_id: j.result.build_id }); setBuildId(j.result.build_id); }
      if (j.status === "failed") setErr(j.message);
    }).catch(setErr);
  };
  const revoke = async (id: number) => {
    try { await api.del(`/merge-decisions/${id}`); qc.invalidateQueries(); } catch (e) { setErr(e); }
  };
  return (
    <>
      <PageHead title="Merge Review" actions={
        <div className="row">
          <span className="small ink2">{merges.length} merge decision(s) recorded for this lineage</span>
          <button className="btn primary" onClick={applyAll} disabled={!canDecide} title={canDecide ? "fold every active decision into the next build" : "analyst or admin only"}>
            Apply merges → new build
          </button>
        </div>}>
        Rows that look like one song under two ISRCs or two internal numbers. Auto-merging is wrong (AAJ JYOTSNA RAATEY is
        two works), never merging is wrong too - so tick the rows that really are the same song, pick the surviving
        identity, and merge. Every decision is stored; applying creates a new build and asserts that no total moved.
      </PageHead>
      {!canDecide && <div className="note warn section">You are a <b>viewer</b> - switch the role to analyst or admin (top right) to record decisions.</div>}
      {applied && b && (
        <Card title={`Applied → ${b.label} (build #${b.id})`} sub="money neutrality and identifier preservation are asserted on every apply" className="section">
          <InvariantList items={b.invariants.filter((i) => ["I20", "I21", "I22", "I23", "I24", "I25"].includes(i.id))} />
        </Card>
      )}
      <ErrorNote error={err} />
      <div className="grid2" style={{ gridTemplateColumns: "1fr minmax(280px, 340px)", alignItems: "start" }}>
        <div className="col" style={{ gap: 12 }}>
          <div className="row wrap">
            <input className="input" placeholder="search song" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
            <select className="input" value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }}>
              <option value={EXACT}>exact-name kinds</option>
              <option value="SAME_NAME_DIFF_ISRC">{KIND_LABEL.SAME_NAME_DIFF_ISRC}</option>
              <option value="SAME_NAME_DIFF_INTERNAL_NO">{KIND_LABEL.SAME_NAME_DIFF_INTERNAL_NO}</option>
              <option value="SAME_NAME_NO_IDENTIFIER">{KIND_LABEL.SAME_NAME_NO_IDENTIFIER}</option>
              <option value="VERSION_VARIANT">{KIND_LABEL.VERSION_VARIANT}</option>
            </select>
            <Seg value={band} onChange={(v) => { setBand(v); setPage(0); }} items={[
              { key: "", label: "any score" }, { key: "suggested", label: "suggested" }, { key: "review", label: "review" }, { key: "unlikely", label: "unlikely" }]} />
            <Seg value={status} onChange={(v) => { setStatus(v); setPage(0); }} items={[
              { key: "open", label: "open" }, { key: "merged", label: "merged" }, { key: "not_same", label: "not the same" }, { key: "", label: "all" }]} />
            <span className="small muted">{(list.data?.total ?? 0).toLocaleString("en-US")} group(s)</span>
          </div>
          {list.isLoading ? <Spinner /> : (list.data?.items ?? []).length ? (
            <>
              {list.data!.items.map((c) => <CandidateCard key={c.id} c={c} buildId={buildId} />)}
              <div className="row">
                <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>‹ prev</button>
                <span className="small muted">page {page + 1} of {Math.max(1, Math.ceil((list.data?.total ?? 0) / 25))}</span>
                <button className="btn sm" disabled={(page + 1) * 25 >= (list.data?.total ?? 0)} onClick={() => setPage(page + 1)}>next ›</button>
              </div>
            </>
          ) : <Card><Empty>No candidate groups match.</Empty></Card>}
        </div>
        <Card title="Decision log" sub="who decided what, when - each entry reversible" flush>
          {(log.data ?? []).length ? (
            <div className="col" style={{ gap: 0 }}>
              {log.data!.map((d) => (
                <div key={d.id} style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", opacity: d.active ? 1 : 0.55 }}>
                  <div className="row">
                    <Badge tone={d.verdict === "MERGE" ? "info" : "neutral"}>{d.verdict === "MERGE" ? "MERGED" : "NOT THE SAME"}</Badge>
                    <b className="small">{d.display_name}</b>
                    <span className="spacer" />
                    {d.active ? <button className="btn ghost sm" disabled={!canDecide} onClick={() => revoke(d.id)}>undo</button> : <span className="small muted">revoked</span>}
                  </div>
                  <div className="small muted" style={{ marginTop: 3 }}>#{d.id} · {d.decided_by} · {d.decided_at}{d.revoked_at ? ` · revoked ${d.revoked_at}` : ""}</div>
                  <div className="small ink2">{d.members.length} row key(s) · confidence {d.confidence?.toFixed(2)}{d.note ? ` · “${d.note}”` : ""}</div>
                </div>
              ))}
            </div>
          ) : <Empty>No decisions yet.</Empty>}
        </Card>
      </div>
    </>
  );
}

function CandidateCard({ c, buildId }: { c: Candidate; buildId: number }) {
  const { canDecide } = useApp();
  const qc = useQueryClient();
  const [ticked, setTicked] = useState<Set<number>>(() => new Set(c.members.map((m) => m.id)));
  const [survivor, setSurvivor] = useState<number>(c.default_survivor);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const decide = async (verdict: "MERGE" | "NOT_THE_SAME") => {
    setErr(null); setBusy(true);
    try {
      await api.post(`/builds/${buildId}/merge-decisions`, [{
        candidate_id: c.id, verdict, members: [...ticked], survivor_row: ticked.has(survivor) ? survivor : [...ticked][0],
      }]);
      await qc.invalidateQueries();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const months = [...new Set(c.members.flatMap((m) => Object.keys(m.months)))].sort();
  const sections = [...new Set(c.members.flatMap((m) => Object.keys(m.by_section)))];
  const dTotal = c.members.filter((m) => ticked.has(m.id)).reduce((a, m) => a + m.d, 0);
  const eTotal = c.members.filter((m) => ticked.has(m.id)).reduce((a, m) => a + m.e, 0);
  return (
    <Card title={<span className="row wrap">{c.display_name} <Badge tone="neutral">{KIND_LABEL[c.kind]}</Badge></span>}
          sub={<span className="row wrap" style={{ marginTop: 4 }}>
            {c.signals.map((s) => <span key={s.code} className={`signal ${s.weight > 0 ? "pos" : "neg"}`} title={s.label}>{s.weight > 0 ? "+" : ""}{s.weight.toFixed(2)} {s.label}</span>)}
          </span>}
          actions={<div className="col" style={{ alignItems: "flex-end", gap: 4 }}>
            <ConfBar value={c.confidence} band={c.band} />
            {c.decision && <Badge tone={c.decision.verdict === "MERGE" ? "info" : "neutral"}>{c.decision.verdict === "MERGE" ? "merged" : "not the same"} · {c.decision.decided_by}</Badge>}
          </div>} flush>
      <div className="tbl-wrap">
        <table className="cmp">
          <tbody>
            <tr><th>Same song?</th>{c.members.map((m) => (
              <td key={m.id} className={survivor === m.id ? "survivor" : ""}>
                <label className="check"><input type="checkbox" checked={ticked.has(m.id)} onChange={(e) => {
                  const n = new Set(ticked); e.target.checked ? n.add(m.id) : n.delete(m.id); setTicked(n);
                }} /> include</label>
                <label className="check small" style={{ marginLeft: 10 }}><input type="radio" name={`surv-${c.id}`} checked={survivor === m.id} onChange={() => setSurvivor(m.id)} /> survivor</label>
              </td>))}</tr>
            <tr><th>Row</th>{c.members.map((m) => <td key={m.id} className={survivor === m.id ? "survivor" : ""}><b>{m.name}</b><div className="small muted mono">{m.key} · {m.origin}</div></td>)}</tr>
            <tr><th>Status</th>{c.members.map((m) => <td key={m.id}><StatusChip code={m.status} /></td>)}</tr>
            <tr><th>ISRC</th>{c.members.map((m) => (
              <td key={m.id}><span className="chips">{m.isrcs.length ? m.isrcs.map((i) => <span key={i.isrc} className={`chip ${i.registered ? "" : "unreg"}`} title={i.registered ? "registered" : `NOT registered · ${i.via}`}>{i.isrc}</span>) : <span className="muted">none</span>}</span></td>))}</tr>
            <tr><th>Internal no</th>{c.members.map((m) => (
              <td key={m.id}><span className="chips">{m.works.length ? m.works.map((w) => <span key={w.work_no} className={`chip ${w.registered ? "" : "unreg"}`}>{w.work_no}</span>) : <span className="muted">none</span>}</span></td>))}</tr>
            <tr><th>Title as reported</th>{c.members.map((m) => <td key={m.id} className="small">{m.titles.join(" · ") || <span className="muted">-</span>}</td>)}</tr>
            <tr><th>Album</th>{c.members.map((m) => <td key={m.id} className="small">{m.albums.join(" · ") || <span className="muted">-</span>}</td>)}</tr>
            <tr><th>Royalty (D)</th>{c.members.map((m) => <td key={m.id} className="num" style={{ textAlign: "left" }}><b>{money(m.d)}</b>{sections.length > 0 && <div className="small muted">{Object.entries(m.by_section).map(([k, v]) => `${k} ${money(v)}`).join(" · ")}</div>}</td>)}</tr>
            <tr><th>Platform gross (E)</th>{c.members.map((m) => <td key={m.id}><b className="num">{money(m.e)}</b>{months.length > 0 && <div className="small muted">{months.filter((mo) => m.months[mo]).map((mo) => `${monthLabel(mo)} ${money(m.months[mo])}`).join(" · ")}</div>}</td>)}</tr>
            <tr><th>Match basis</th>{c.members.map((m) => <td key={m.id}><BasisChips codes={m.basis} /></td>)}</tr>
          </tbody>
        </table>
      </div>
      <div className="row wrap" style={{ padding: "10px 14px" }}>
        <span className="small ink2">After merge: royalty <b className="num">{money(dTotal)}</b> · gross <b className="num">{money(eTotal)}</b> (added, never moved)</span>
        <span className="spacer" />
        <button className="btn" disabled={!canDecide || busy} onClick={() => decide("NOT_THE_SAME")}>Not the same</button>
        <button className="btn primary" disabled={!canDecide || busy || ticked.size < 2} onClick={() => decide("MERGE")}>Merge {ticked.size} rows</button>
      </div>
      <div style={{ padding: "0 14px 10px" }}><ErrorNote error={err} /></div>
    </Card>
  );
}
