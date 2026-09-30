// Song-ID-Mismatch report (§13) - where the sheet, IPRS and the platform disagree about a song
// they all know. Conflicting values render as chips, never pipe strings.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorNote, Field, InvariantList, IsrcChips, PageHead, Spinner, Tabs } from "../components/ui";
import { bytes, money } from "../format";
import { useApp, useRunJob } from "../state";
import { SourcePicker } from "../components/SourcePicker";

const KINDS = ["Different ISRC", "Different Internal Number", "Different Song Name"] as const;

export default function Mismatch() {
  const { buildId, batchId, meta } = useApp();
  const run = useRunJob();
  const runs = useQuery({ queryKey: ["mm-runs-batch", batchId], queryFn: () => api.get<any[]>(`/mismatch?batch_id=${batchId}`), enabled: !!batchId });
  const sheets = useQuery({ queryKey: ["sheets", batchId], queryFn: () => api.get<any[]>(`/sheets?batch_id=${batchId}`), enabled: !!batchId });
  const sources = useQuery({ queryKey: ["cov-sources", buildId], queryFn: () => api.get<{ sources: any[] }>(`/builds/${buildId}/coverage/sources`), enabled: !!buildId });
  const [runId, setRunId] = useState<number | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [pf, setPf] = useState("");
  const [pt, setPt] = useState("");
  const [sheetId, setSheetId] = useState<number | "">("");
  const [err, setErr] = useState<unknown>(null);
  const srcs = sources.data?.sources ?? [];
  useEffect(() => { if (srcs.length && !picked.size) setPicked(new Set(srcs.map((s) => s.code))); }, [srcs.length]); // eslint-disable-line
  if (!buildId) return <Empty>No build yet.</Empty>;
  const cat = (sheets.data ?? []).find((s) => s.is_catalogue);
  const current = runId ?? runs.data?.[0]?.id ?? null;
  const preset = () => {
    const r = meta?.reference.mismatch;
    if (!r) return;
    setPicked(new Set(r.sources)); setPf(r.period_from); setPt(r.period_to); setSheetId(cat?.id ?? "");
  };
  const start = () => run("Mismatch report", () => api.post(`/builds/${buildId}/mismatch`, {
    sheet_id: sheetId || cat?.id || null, sources: [...picked], period_from: pf || null, period_to: pt || null,
  }), (j) => j.status === "succeeded" && setRunId(j.result?.run_id)).catch(setErr);
  return (
    <>
      <PageHead title="Song-ID-Mismatch Report">
        Two fields agree, so the third disagreeing is the finding - A: name + ISRC agree → different internal no;
        B: name + internal no agree → different ISRC; C: internal no + ISRC agree → different name. A field a source
        does not carry is a wildcard: it never disagrees and never blocks the match.
      </PageHead>
      <Card title="Run" className="section" actions={<button className="btn sm" onClick={preset}>Reference preset</button>}>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <Field label="Sheet">
            <select className="input" value={sheetId || cat?.id || ""} onChange={(e) => setSheetId(Number(e.target.value) || "")}>
              {(sheets.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Sources">
            <details className="picker">
              <summary className="input" style={{ minWidth: 220 }}>{picked.size} of {srcs.length} sources ▾</summary>
              <div className="pop"><SourcePicker sources={srcs} picked={picked} onChange={setPicked} /></div>
            </details>
          </Field>
          <Field label="From"><input className="input" type="month" value={pf} onChange={(e) => setPf(e.target.value)} /></Field>
          <Field label="To"><input className="input" type="month" value={pt} onChange={(e) => setPt(e.target.value)} /></Field>
          <button className="btn primary" onClick={start}>Run</button>
          {(runs.data ?? []).map((r) => (
            <button key={r.id} className={`btn sm ${r.id === current ? "primary" : ""}`} onClick={() => setRunId(r.id)}>#{r.id} · {r.row_count} rows · {r.build_label}</button>
          ))}
        </div>
        <ErrorNote error={err} />
      </Card>
      {current ? <MismatchRun id={current} /> : <Card><Empty>No mismatch run yet.</Empty></Card>}
    </>
  );
}

function MismatchRun({ id }: { id: number }) {
  const run = useRunJob();
  const q = useQuery({ queryKey: ["mm", id], queryFn: () => api.get<any>(`/mismatch/${id}`) });
  const rows = useQuery({ queryKey: ["mm-rows", id], queryFn: () => api.get<any[]>(`/mismatch/${id}/rows`) });
  const [tab, setTab] = useState<string>("All");
  const [v2, setV2] = useState(true);
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const shown = useMemo(() => (rows.data ?? []).filter((d) => (tab === "All" || d.kind === tab) &&
    (!filter || `${d.main_name} ${d.main_no} ${d.isrcs.join(" ")} ${d.values.join(" ")}`.toLowerCase().includes(filter.toLowerCase()))), [rows.data, tab, filter]);
  const m = q.data;
  if (!m) return <Spinner />;
  const labels = m.counts.labels ?? {};
  const t = m.totals;
  return (
    <Card title={`Run #${m.id} · ${m.row_count} rows`} sub={`records: sheet ${m.counts.records?.S2} · statement works ${m.counts.records?.S3} · platform name+ISRC ${m.counts.records?.S4} · ${m.counts.raw_groups} raw groups`}
          actions={<div className="row">
            {m.invariants.every((i: any) => i.passed) ? <Badge tone="good">✓ invariants</Badge> : <Badge tone="crit">✕ invariant failed</Badge>}
            <label className="check small"><input type="checkbox" checked={v2} onChange={(e) => setV2(e.target.checked)} /> V2 revenue columns</label>
            <button className="btn sm primary" onClick={() => run("Export mismatch V1 + V2", () => api.post(`/builds/${m.build_id}/exports/mismatch?ref_id=${m.id}`)).catch(setErr)}>Generate workbooks</button>
          </div>} flush>
      <div style={{ padding: "8px 16px 0" }}>
        {m.exports.length > 0 && <div className="row wrap" style={{ marginBottom: 8 }}>{m.exports.slice(0, 2).map((e: any) => (
          <a key={e.id} className="btn sm" href={`/api/exports/${e.id}/download`}>↓ {e.filename} <span className="muted">{bytes(e.size)}</span></a>))}</div>}
        <ErrorNote error={err} />
        <Tabs value={tab} onChange={setTab} items={[{ key: "All", label: "All", count: m.row_count },
          ...KINDS.map((k) => ({ key: k, label: k, count: m.counts.by_kind?.[k] ?? 0 }))]} />
        <div className="row" style={{ marginBottom: 10 }}>
          <input className="input sm" placeholder="filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <span className="small muted">{shown.length} shown · S2 = {labels.S2} · S3 = {labels.S3} · S4 = {labels.S4}</span>
        </div>
      </div>
      <div className="tbl-wrap" style={{ maxHeight: "calc(100vh - 420px)", minHeight: 300 }}>
        <table className="tbl">
          <thead><tr>
            <th>#</th><th>ISRC (sheet)</th><th>Song name</th><th>Internal no</th><th>Type</th><th>Conflicting value(s)</th><th>Found in</th>
            {v2 && <><th className="num">Royalty</th><th className="num">Gross revenue</th><th className="num">Both</th></>}
          </tr></thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.id}>
                <td className="mono small">{d.ordinal + 1}</td>
                <td><IsrcChips isrcs={d.isrcs} max={2} /></td>
                <td>{d.main_name}</td>
                <td className="mono small">{d.main_no}</td>
                <td><Badge tone={d.kind === "Different ISRC" ? "info" : d.kind === "Different Song Name" ? "neutral" : "warn"}>{d.kind}</Badge></td>
                <td><span className="chips">{d.values.map((v: string) => <span key={v} className={`chip ${d.kind === "Different Song Name" ? "plain" : ""}`}>{v}</span>)}</span></td>
                <td className="small">{d.sources.join(", ")}</td>
                {v2 && <><td className="num">{money(d.royalty)}</td><td className="num">{money(d.gross)}</td><td className="num"><b>{money(d.royalty + d.gross)}</b></td></>}
              </tr>
            ))}
          </tbody>
          {v2 && <tfoot><tr><td colSpan={7}>TOTAL (booked once per IPRS work / per ISRC) - of {money(t.iprs_file)} royalty and {money(t.mrm_file)} gross in the selection</td>
            <td className="num">{money(t.royalty)}</td><td className="num">{money(t.gross)}</td><td className="num">{money(t.both)}</td></tr></tfoot>}
        </table>
      </div>
      <div style={{ padding: 16 }}><InvariantList items={m.invariants} compact /></div>
    </Card>
  );
}
