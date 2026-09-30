// Coverage Audit (§11) - "here is my song sheet; show me every song that is NOT in it but still
// earned money from a party". 1 pick the sheet · 2 tick the sources · 3 period, mode, rule · 4 run.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, qs } from "../api";
import {
  Badge, Card, Drawer, Empty, ErrorNote, Field, InvariantList, IsrcChips, Money, PageHead, Seg, Spinner, Tabs,
  WorkChips, useDebounced,
} from "../components/ui";
import { bytes, money, monthLabel } from "../format";
import { useApp, useRunJob } from "../state";
import type { CoverageRow, CoverageRun } from "../types";
import { SourcePicker } from "../components/SourcePicker";

export default function Coverage() {
  const { buildId, batchId, meta } = useApp();
  const run = useRunJob();
  const sheets = useQuery({ queryKey: ["sheets", batchId], queryFn: () => api.get<any[]>(`/sheets?batch_id=${batchId}`), enabled: !!batchId });
  const sources = useQuery({ queryKey: ["cov-sources", buildId], queryFn: () => api.get<{ sources: any[] }>(`/builds/${buildId}/coverage/sources`), enabled: !!buildId });
  const runs = useQuery({ queryKey: ["coverage-runs-batch", batchId], queryFn: () => api.get<CoverageRun[]>(`/coverage?batch_id=${batchId}`), enabled: !!batchId });
  const [sheetId, setSheetId] = useState<number | "">("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [pf, setPf] = useState("");
  const [pt, setPt] = useState("");
  const [mode, setMode] = useState<"RESOLVED" | "STRICT">("RESOLVED");
  const [policy, setPolicy] = useState<"v2" | "reference">("v2");
  const [minAmount, setMinAmount] = useState("");
  const [runId, setRunId] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const srcs = sources.data?.sources ?? [];
  useEffect(() => { if (srcs.length && !picked.size) setPicked(new Set(srcs.map((s) => s.code))); }, [srcs.length]); // eslint-disable-line
  const catalogue = (sheets.data ?? []).find((s) => s.is_catalogue);
  const effSheet = sheetId || catalogue?.id || "";
  const currentRun = runId ?? runs.data?.[0]?.id ?? null;

  if (!buildId) return <Empty>No build yet.</Empty>;
  const preset = () => {
    const ref = meta?.reference.coverage;
    if (!ref) return;
    setPicked(new Set(ref.sources));
    setPf(ref.period_from); setPt(ref.period_to); setMode("RESOLVED"); setPolicy("reference"); setSheetId(catalogue?.id ?? "");
  };
  const start = () => {
    setErr(null);
    run("Coverage audit", () => api.post(`/builds/${buildId}/coverage`, {
      sheet_id: effSheet || null, sources: [...picked], period_from: pf || null, period_to: pt || null, mode,
      l3_policy: policy, min_amount: Number(minAmount) || 0,
    }), (j) => j.status === "succeeded" && setRunId(j.result?.run_id)).catch(setErr);
  };
  return (
    <>
      <PageHead title="Coverage Audit">
        Every song a party paid or reported that is <b>not</b> in your sheet, with how much. A record is excluded -
        present in the sheet - when its own internal number (E1) or ISRC (E2) is there, or, in RESOLVED mode, when an
        exact title link supplies the missing identifier (E3 / E4). Every exclusion records the rung and the sheet entry.
      </PageHead>
      <div className="grid2" style={{ gridTemplateColumns: "minmax(300px, 380px) 1fr", alignItems: "start" }}>
        <Card title="Run an audit" actions={meta?.reference && <button className="btn sm" onClick={preset} title="Spotify statement Oct'25-Mar'26 + MRM, RESOLVED, reference title link">Reference preset</button>}>
          <div className="col" style={{ gap: 14 }}>
            <Field label="1 · Song sheet to audit">
              <select className="input" value={effSheet} onChange={(e) => setSheetId(Number(e.target.value) || "")}>
                {(sheets.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.label}{s.is_catalogue ? " (catalogue)" : ""} · {s.row_count} rows</option>)}
              </select>
            </Field>
            <div>
              <div className="small ink2" style={{ fontWeight: 550, marginBottom: 6 }}>2 · Revenue sources</div>
              <SourcePicker sources={srcs} picked={picked} onChange={setPicked} />
            </div>
            <div className="row">
              <Field label="3 · Period from"><input className="input" type="month" value={pf} onChange={(e) => setPf(e.target.value)} /></Field>
              <Field label="to"><input className="input" type="month" value={pt} onChange={(e) => setPt(e.target.value)} /></Field>
            </div>
            <Field label="Mode">
              <Seg value={mode} onChange={setMode} items={[
                { key: "RESOLVED", label: "RESOLVED", title: "which SONGS are absent - title links (E3/E4) count as present" },
                { key: "STRICT", label: "STRICT", title: "which IDENTIFIERS are absent - the registration backlog" }]} />
            </Field>
            <Field label="Title-link rule (E3 / E4)">
              <Seg value={policy} onChange={setPolicy} items={[
                { key: "v2", label: "V2 rule", title: "title must be unique on BOTH sides (architecture §8 L3, §11.2)" },
                { key: "reference", label: "Reference run", title: "as the published 93-song run: any title-linked ISRC; statement side unique" }]} />
            </Field>
            <Field label="Hide songs below (amount)"><input className="input" value={minAmount} onChange={(e) => setMinAmount(e.target.value.replace(/[^0-9.]/g, ""))} placeholder="0" /></Field>
            <button className="btn primary" onClick={start} disabled={!picked.size || !effSheet}>4 · Run the audit</button>
            <ErrorNote error={err} />
            {policy === "reference" && <div className="note small">The architecture text requires a title link to be unique on both sides; the published 93-song result was produced without that check. This rule reproduces it exactly.</div>}
          </div>
        </Card>
        <div className="col" style={{ gap: 16 }}>
          {runs.data?.length ? (
            <div className="row wrap">
              <span className="small ink2">Runs:</span>
              {runs.data.map((r) => (
                <button key={r.id} className={`btn sm ${r.id === currentRun ? "primary" : ""}`} onClick={() => setRunId(r.id)}>
                  #{r.id} · {r.mode} · {r.stats.l3_policy === "reference" ? "ref" : "V2"} · {r.finding_count} songs · {(r as any).build_label}
                </button>
              ))}
            </div>
          ) : null}
          {currentRun ? <RunView id={currentRun} /> : <Card title="No audit yet"><div className="muted">Configure and run an audit on the left.</div></Card>}
          {currentRun && runs.data?.find((r) => r.id === currentRun)?.build_id !== buildId && (
            <div className="note small">This run was made on another build of the batch. The audit recomputes every figure from the source lines, so it does not depend on which build is selected.</div>
          )}
        </div>
      </div>
    </>
  );
}

function RunView({ id }: { id: number }) {
  const run = useRunJob();
  const q = useQuery({ queryKey: ["coverage", id], queryFn: () => api.get<CoverageRun>(`/coverage/${id}`) });
  const rows = useQuery({ queryKey: ["coverage-rows", id], queryFn: () => api.get<CoverageRow[]>(`/coverage/${id}/rows`) });
  const [tab, setTab] = useState<"findings" | "excluded" | "checks">("findings");
  const [filter, setFilter] = useState("");
  const [evidence, setEvidence] = useState("");
  const [explain, setExplain] = useState<CoverageRow | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const c = q.data;
  const shown = useMemo(() => (rows.data ?? []).filter((r) =>
    (!evidence || r.evidence === evidence) &&
    (!filter || `${r.song_name} ${r.isrcs.join(" ")} ${r.work_nos.join(" ")}`.toLowerCase().includes(filter.toLowerCase()))), [rows.data, filter, evidence]);
  if (!c) return <Spinner />;
  const s = c.stats;
  const months: string[] = s.months ?? [];
  const exportIt = () => run("Export coverage workbooks", () => api.post(`/builds/${c.build_id}/exports/coverage?ref_id=${c.id}`)).catch(setErr);
  const ok = c.invariants.every((i) => i.passed);
  return (
    <>
      <div className="strip">
        <div><div className="v">{c.finding_count}</div><div className="l">songs not in “{c.sheet?.label}”</div></div>
        <div><div className="v num">{money(c.revenue_at_risk)}</div><div className="l">platform revenue at stake</div></div>
        <div><div className="v num">{money(c.royalty_received)}</div><div className="l">IPRS royalty already received</div></div>
        <div><div className="v">{c.name_present_count}</div><div className="l">title in the sheet, identifiers not</div></div>
        <div><div className="v">{s.statement_only} · {s.platform_only} · {s.both}</div><div className="l">statement · platform · both</div></div>
        <div><div className="v">{s.strict_works} + {s.strict_isrcs}</div><div className="l">STRICT: works + ISRCs absent</div></div>
        <div><div className="v">{s.resolved_songs}</div><div className="l">RESOLVED songs</div></div>
      </div>
      <Card title={`Run #${c.id} · ${c.mode} · ${s.l3_policy === "reference" ? "reference-run title link" : "V2 title-link rule"}`}
            sub={`sources ${c.sources.join(", ")} · ${c.period_from || c.period_to ? `${c.period_from ?? "…"} to ${c.period_to ?? "…"}` : "all periods"} · ${s.statements} statement(s), ${s.reports} report(s) · exclusions ${Object.entries(s.exclusions ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}`}
            actions={<div className="row">{ok ? <Badge tone="good">✓ accuracy contract</Badge> : <Badge tone="crit">✕ invariant failed</Badge>}
              <button className="btn sm primary" onClick={exportIt}>Generate workbooks</button></div>} flush>
        <div style={{ padding: "8px 16px 0" }}>
          {c.exports.length > 0 && (
            <div className="row wrap small" style={{ marginBottom: 8 }}>
              {c.exports.slice(0, 2).map((e) => (
                <a key={e.id} className="btn sm" href={`/api/exports/${e.id}/download`}>↓ {e.filename} <span className="muted">{bytes(e.size)}</span></a>
              ))}
            </div>
          )}
          <ErrorNote error={err} />
          <Tabs value={tab} onChange={setTab} items={[
            { key: "findings", label: "Findings", count: c.finding_count },
            { key: "excluded", label: "Why excluded?" },
            { key: "checks", label: "Accuracy contract", count: c.invariants.length }]} />
        </div>
        {tab === "findings" && (
          <>
            <div className="row" style={{ padding: "0 16px 10px" }}>
              <input className="input sm" placeholder="filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
              <select className="input sm" value={evidence} onChange={(e) => setEvidence(e.target.value)}>
                <option value="">all evidence</option>
                <option value="IDENTIFIERS ABSENT">identifiers absent</option>
                <option value="NAME PRESENT, IDENTIFIERS DIFFER">name present, identifiers differ</option>
              </select>
              <span className="small muted">{shown.length} shown</span>
            </div>
            <div className="tbl-wrap" style={{ maxHeight: "calc(100vh - 420px)", minHeight: 300 }}>
              <table className="tbl">
                <thead><tr>
                  <th>ISRC</th><th>Song name</th><th>Internal no</th><th>Present in</th><th>Evidence</th>
                  <th className="num">Royalty</th><th className="num">Platform revenue</th>
                  {months.map((m) => <th key={m} className="num">{monthLabel(m)}</th>)}
                </tr></thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.id} className="click" onClick={() => setExplain(r)}>
                      <td><IsrcChips isrcs={r.isrcs} max={2} /></td>
                      <td>{r.song_name}</td>
                      <td><WorkChips works={r.work_nos} /></td>
                      <td className="small">{r.present_in}</td>
                      <td>{r.evidence.startsWith("NAME") ? <Badge tone="warn">name present</Badge> : <Badge tone="neutral">absent</Badge>}</td>
                      <td className="num"><Money v={r.royalty} /></td>
                      <td className="num"><b>{money(r.platform_rev)}</b></td>
                      {months.map((m) => <td key={m} className="num small">{r.months[m] !== undefined ? money(r.months[m]) : ""}</td>)}
                    </tr>
                  ))}
                </tbody>
                <tfoot><tr>
                  <td colSpan={5}>TOTAL · {shown.length} songs</td>
                  <td className="num">{money(shown.reduce((a, r) => a + r.royalty, 0))}</td>
                  <td className="num">{money(shown.reduce((a, r) => a + r.platform_rev, 0))}</td>
                  {months.map((m) => <td key={m} className="num small">{money(shown.reduce((a, r) => a + (r.months[m] ?? 0), 0))}</td>)}
                </tr></tfoot>
              </table>
            </div>
          </>
        )}
        {tab === "excluded" && <Exclusions runId={c.id} />}
        {tab === "checks" && <div style={{ padding: 16 }}><InvariantList items={c.invariants} /></div>}
      </Card>
      {explain && <Explain runId={c.id} row={explain} onClose={() => setExplain(null)} />}
    </>
  );
}

function Exclusions({ runId }: { runId: number }) {
  const [rung, setRung] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const list = useQuery({ queryKey: ["excl", runId, rung, dq], queryFn: () => api.withTotal<any[]>(`/coverage/${runId}/exclusions${qs({ rung, q: dq, limit: 300 })}`) });
  return (
    <>
      <div className="row" style={{ padding: "0 16px 10px" }}>
        <input className="input sm" placeholder="ISRC, internal no or title" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input sm" value={rung} onChange={(e) => setRung(e.target.value)}>
          <option value="">all rungs</option>
          <option value="E1">E1 · internal no in the sheet</option>
          <option value="E2">E2 · ISRC in the sheet</option>
          <option value="E3">E3 · title link → ISRC in the sheet</option>
          <option value="E4">E4 · title link → internal no in the sheet</option>
        </select>
        <span className="small muted">{(list.data?.total ?? 0).toLocaleString("en-US")} excluded records</span>
      </div>
      <div className="tbl-wrap" style={{ maxHeight: "calc(100vh - 420px)", minHeight: 300 }}>
        <table className="tbl">
          <thead><tr><th>Record</th><th>Title as the source spells it</th><th>Rung</th><th>Matched sheet entry</th><th>Via</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {(list.data?.items ?? []).map((x) => (
              <tr key={`${x.src_kind}:${x.src_ref}`}>
                <td className="mono small">{x.src_ref}</td><td className="small">{x.src_name}</td>
                <td><Badge tone={x.rung === "E3" || x.rung === "E4" ? "warn" : "good"}>{x.rung}</Badge></td>
                <td className="small">{x.entry_name}</td><td className="small ink2">{x.via}</td><td className="num">{money(x.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Explain({ runId, row, onClose }: { runId: number; row: CoverageRow; onClose: () => void }) {
  const q = useQuery({ queryKey: ["explain", runId, row.id], queryFn: () => api.get<any>(`/coverage/${runId}/explain?row_id=${row.id}`) });
  const e = q.data;
  return (
    <Drawer open onClose={onClose} title={row.song_name} sub={`${row.evidence} · present in ${row.present_in}`}>
      {!e ? <Spinner /> : (
        <div className="col" style={{ gap: 16 }}>
          <div className="kv">
            <div>ISRC</div><div><IsrcChips isrcs={row.isrcs} max={8} /></div>
            <div>Internal no</div><div><WorkChips works={row.work_nos} /></div>
            <div>Spellings</div><div>{row.spellings.join(" · ")}</div>
            {row.albums.length > 0 && <><div>Album</div><div>{row.albums.join(" · ")}</div></>}
            <div>Royalty</div><div className="num" style={{ textAlign: "left" }}>{money(row.royalty)}</div>
            <div>Platform revenue</div><div className="num" style={{ textAlign: "left" }}>{money(row.platform_rev)}</div>
          </div>
          <div>
            <h3>Why it is a finding - every rung that was tried</h3>
            {e.trace.map((t: any) => (
              <div key={t.record} className="card" style={{ padding: 10, marginTop: 8 }}>
                <div className="row"><span className="mono small">{t.record}</span><Badge tone="neutral">{t.kind === "platform_isrc" ? "platform ISRC" : "statement work"}</Badge><span className="small ink2">{t.name}</span></div>
                {t.tests.map((x: any) => <div key={x.rung} className="small" style={{ marginTop: 4 }}><Badge tone="crit">✕ {x.rung}</Badge> {x.why}</div>)}
              </div>
            ))}
          </div>
          {e.name_in_sheet.length > 0 && (
            <div>
              <h3>The title IS in the sheet - under other identifiers</h3>
              {e.name_in_sheet.map((n: any) => (
                <div key={n.entry_id} className="note warn small" style={{ marginTop: 6 }}>
                  “{n.name}” · internal no {n.work_nos.join(" | ") || "-"} · ISRC {n.isrcs.join(" | ") || "-"}
                </div>
              ))}
              <div className="small muted" style={{ marginTop: 6 }}>A cover, a male/female version, a re-recording, or an unregistered recording of a registered work - the Merge Review is where that call is made.</div>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}
