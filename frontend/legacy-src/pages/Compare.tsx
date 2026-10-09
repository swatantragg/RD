import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { useApp } from "../state";
import {
  Card, Checks, Drawer, Empty, ErrorNote, Field, Int, Kv, Money, Outcome, OUTCOME_LABEL, PageHead, Pager, Spinner, Stat,
  StateBadge, Tabs, useDebounced,
} from "../components/ui";
import { compact, dmy, int, money, period, today, when, words } from "../format";

export default function Compare({ runId }: { runId?: number }) {
  return runId ? <RunView id={runId} /> : <Runs />;
}

function Runs() {
  const { clientId, can, go } = useApp();
  const runs = useQuery({ queryKey: ["runs", clientId], queryFn: () => api.get<any[]>(`/runs${qs({ client_id: clientId })}`) });
  return (
    <>
      <PageHead title="Comparison" step="D1–D5 · F1–F4 · G1–G5">
        One group per client + composition + platform + territory + usage period + use type + publishing-right scope. Recording
        income is summed across the group's masters once; the publishing amount is matched at composition level once.
      </PageHead>
      {can("run") && <NewRun />}
      <Card title="Runs" sub="completed runs are frozen; a re-run is a new version" flush>
        {runs.isLoading ? <Spinner /> : !runs.data?.length ? <Empty>No runs yet.</Empty> : (
          <table className="tbl">
            <thead><tr><th>Run</th><th>Scope</th><th>Usage period</th><th>Cutoff</th><th>Identity</th><th className="num">Groups</th>
              <th className="num">Below</th><th className="num">Positive gaps</th><th>By</th></tr></thead>
            <tbody>{runs.data.map((r) => (
              <tr key={r.id} className="click" onClick={() => go(`compare/${r.id}`)}>
                <td>v{r.version_no}</td><td>{r.platform} · {r.territory} · {words(r.use_type)} · {words(r.right_scope)}</td>
                <td>{period(r.period_from, r.period_to)}</td><td>{dmy(r.cutoff)}</td><td>v{r.identity_version}</td>
                <td className="num">{int(r.summary.groups)}</td><td className="num">{int(r.summary.outcomes?.BELOW_COMPARISON ?? 0)}</td>
                <td className="num"><Money v={r.summary.by_currency?.[0]?.positive_gaps} /></td>
                <td className="small">{r.created_by_name}<div className="muted">{when(r.created_at)}</div></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </>
  );
}

function NewRun() {
  const { clientId, meta, toast, go } = useApp();
  const qc = useQueryClient();
  const sc = useQuery({ queryKey: ["scopes", clientId], queryFn: () => api.get<any[]>(`/runs/scopes${qs({ client_id: clientId })}`) });
  const pub = sc.data?.find((f) => f.income_type === "PUBLISHING");
  const [v, setV] = useState<Record<string, string>>({});
  const val = {
    platform: v.platform ?? sc.data?.find((f) => f.platform)?.platform ?? "Spotify",
    territory: v.territory ?? sc.data?.find((f) => f.territory)?.territory ?? "IN",
    use_type: v.use_type ?? "AUDIO_STREAMING", right_scope: v.right_scope ?? "PERFORMING",
    period_from: v.period_from ?? pub?.period_from ?? "", period_to: v.period_to ?? pub?.period_to ?? "",
    cutoff: v.cutoff ?? today(), distribution_lag_months: v.distribution_lag_months ?? "6",
  };
  const run = useMutation({
    mutationFn: () => api.post<any>("/runs", { client_id: clientId, ...val }),
    onSuccess: (r) => { qc.invalidateQueries(); toast(`Run v${r.version_no}: ${r.summary.groups} groups`); go(`compare/${r.run_id}`); },
    onError: (e) => toast((e as Error).message, true),
  });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });
  return (
    <Card title="Start a comparison run" sub="uses validated files only, the approved identity version and the approved rule for the scope" className="section">
      <div className="form-grid">
        <Field label="Platform"><select className="input" value={val.platform} onChange={set("platform")}>{meta?.platforms.map((p) => <option key={p}>{p}</option>)}</select></Field>
        <Field label="Territory"><input className="input" value={val.territory} onChange={set("territory")} /></Field>
        <Field label="Use type"><select className="input" value={val.use_type} onChange={set("use_type")}>{meta?.use_types.map((u) => <option key={u} value={u}>{words(u)}</option>)}</select></Field>
        <Field label="Publishing-right scope"><select className="input" value={val.right_scope} onChange={set("right_scope")}>{meta?.right_scopes.map((u) => <option key={u} value={u}>{words(u)}</option>)}</select></Field>
        <Field label="Usage period from"><input className="input" type="date" value={val.period_from} onChange={set("period_from")} /></Field>
        <Field label="Usage period to"><input className="input" type="date" value={val.period_to} onChange={set("period_to")} /></Field>
        <Field label="Statement cutoff"><input className="input" type="date" value={val.cutoff} onChange={set("cutoff")} /></Field>
        <Field label="Distribution lag (months)" hint="no statement before this = pending, not missing"><input className="input" value={val.distribution_lag_months} onChange={set("distribution_lag_months")} /></Field>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <span className="muted small">{sc.data?.length ?? 0} validated file(s) available</span><span className="spacer" />
        <button className="btn primary" disabled={run.isPending} onClick={() => run.mutate()}>{run.isPending && <Spinner />}Run comparison</button>
      </div>
      <ErrorNote error={run.error} />
    </Card>
  );
}

function RunView({ id }: { id: number }) {
  const { can, go, toast } = useApp();
  const qc = useQueryClient();
  const r = useQuery({ queryKey: ["run", id], queryFn: () => api.get<any>(`/runs/${id}`) });
  const [tab, setTab] = useState<"groups" | "exceptions" | "inputs">("groups");
  const [outcome, setOutcome] = useState("");
  const build = useMutation({
    mutationFn: () => api.post<any>(`/runs/${id}/packs`, {}),
    onSuccess: (p) => { qc.invalidateQueries(); toast(`Report pack v${p.version_no} built - awaiting approval`); go("packs"); },
    onError: (e) => toast((e as Error).message, true),
  });
  if (r.isLoading) return <Spinner />;
  if (r.error) return <ErrorNote error={r.error} />;
  const run = r.data;
  const sm = run.summary;
  return (
    <>
      <PageHead title={`Run v${run.version_no} · ${run.platform} · ${period(run.period_from, run.period_to)}`} step="comparison run"
                actions={<>
                  <button className="btn" onClick={() => go("compare")}>All runs</button>
                  {can("pack_build") && <button className="btn primary" disabled={build.isPending} onClick={() => build.mutate()}>{build.isPending && <Spinner />}H1 · Build report pack</button>}
                </>}>
        {run.client_name} · {run.territory} · {words(run.use_type)} · {words(run.right_scope)} rights · cutoff {dmy(run.cutoff)} · identity v{run.identity_version} ·
        rule {sm.rule ? `${sm.rule.key} v${sm.rule.version}` : "none"} ({words(sm.method)}) · by {run.created_by_name} {when(run.created_at)}
      </PageHead>
      {sm.method === "MRM_BENCHMARK" && <div className="note section">The 6% figure is an <b>indicative benchmark</b> and B − P a <b>difference for clarification</b>. It is not an amount due from IPRS.</div>}
      <div className="kpis section">
        <Stat label="R in scope" value={compact(sm.r_in_scope)} meta={`mapped ${compact(sm.r_grouped)} · unmapped ${compact(sm.r_unmapped)}`} />
        <Stat label="P in scope" value={compact(sm.p_in_scope)} meta={`matched ${compact(sm.p_grouped)}`} />
        <Stat label="N in scope (streams)" value={compact(sm.n_in_scope)} meta={`${sm.n_months.length} of ${sm.r_months.length || "?"} months`} />
        <Stat label="Statement coverage" value={words(sm.coverage)} meta={sm.statements.map((s: any) => s.filename).join("; ").slice(0, 80)} />
      </div>
      <div className="grid2 section">
        <Card title="Summary control" sub="per currency and right · only comparable groups added · gaps and above-benchmark kept separate" flush>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Currency · right</th><th className="num">Comparable</th><th className="num">R</th><th className="num">B</th><th className="num">P</th>
              <th className="num">Positive gaps</th><th className="num">Above benchmark</th></tr></thead>
            <tbody>{sm.by_currency.map((t: any) => (
              <tr key={`${t.currency}${t.right_scope}`}><td>{t.currency} · {words(t.right_scope)}</td><td className="num">{int(t.comparable_groups)}</td>
                <td className="num"><Money v={t.r} /></td><td className="num"><Money v={t.b} /></td><td className="num"><Money v={t.p} /></td>
                <td className="num"><Money v={t.positive_gaps} /></td><td className="num"><Money v={t.above_benchmark} /></td></tr>
            ))}</tbody>
          </table></div>
          <div className="muted small" style={{ padding: "8px 12px" }}>
            Not added: {sm.by_currency.map((t: any) => `${int(t.provisional_groups)} no-matching-entry groups (provisional B ${money(t.provisional_b)}), ${int(t.coverage_only)} coverage-only`).join("; ")}
          </div>
        </Card>
        <Card title="Run controls"><Checks items={run.checks} /></Card>
      </div>
      <div className="flow section">
        {Object.keys(OUTCOME_LABEL).map((o) => (
          <button key={o} className={`step ${outcome === o ? "ok" : "idle"}`} onClick={() => { setOutcome(outcome === o ? "" : o); setTab("groups"); }}>
            <div className="t"><Outcome o={o} /></div><div className="s" style={{ fontSize: 20, fontWeight: 650 }}>{int(sm.outcomes[o] ?? 0)}</div>
          </button>
        ))}
      </div>
      <Tabs value={tab} onChange={setTab} items={[
        { key: "groups", label: "Groups", count: sm.groups },
        { key: "exceptions", label: "Exceptions", count: sm.exceptions },
        { key: "inputs", label: "Inputs & packs" },
      ]} />
      {tab === "groups" && <Groups runId={id} outcome={outcome} setOutcome={setOutcome} />}
      {tab === "exceptions" && <Exceptions runId={id} counts={run.exception_counts} />}
      {tab === "inputs" && (
        <div className="grid2">
          <Card title="Files used" flush><table className="tbl"><tbody>{run.files.map((f: any) => <tr key={f.id}><td>#{f.id}</td><td>{f.filename}</td><td>{words(f.income_type)}</td></tr>)}</tbody></table></Card>
          <Card title="Report packs from this run" flush>{run.packs.length ? <table className="tbl"><tbody>{run.packs.map((p: any) => <tr key={p.id} className="click" onClick={() => go("packs")}><td>v{p.version_no}</td><td><StateBadge state={p.status} /></td><td>{p.built_by_name}</td><td>{when(p.built_at)}</td></tr>)}</tbody></table> : <Empty>None yet.</Empty>}</Card>
        </div>
      )}
    </>
  );
}

function Groups({ runId, outcome, setOutcome }: { runId: number; outcome: string; setOutcome: (o: string) => void }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("gap");
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<number | null>(null);
  const dq = useDebounced(q);
  const g = useQuery({ queryKey: ["groups", runId, outcome, dq, sort, offset], queryFn: () => api.get<any>(`/runs/${runId}/groups${qs({ outcome, q: dq, sort, offset, limit: 100 })}`) });
  return (
    <Card flush>
      <div className="filters" style={{ padding: "12px 12px 0" }}>
        <select className="input sm" value={outcome} onChange={(e) => { setOutcome(e.target.value); setOffset(0); }}>
          <option value="">all outcomes</option>{Object.entries(OUTCOME_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <input className="input sm" placeholder="title, work code, ISRC, case ID" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <select className="input sm" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="gap">largest positive gap</option><option value="r">largest R</option><option value="p">largest P</option><option value="title">title</option></select>
      </div>
      {g.isLoading ? <Spinner /> : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Case ID</th><th>Work</th><th className="num">Masters</th><th className="num">R</th><th className="num">N</th><th className="num">B</th>
              <th className="num">P</th><th>P status</th><th className="num">V = B − P</th><th>Outcome</th></tr></thead>
            <tbody>{g.data.rows.map((x: any) => (
              <tr key={x.id} className="click" onClick={() => setSel(x.id)}>
                <td className="mono small nowrap">{x.case_code}</td><td className="wrap"><b>{x.title}</b><div className="muted small mono">{x.work_code}</div></td>
                <td className="num">{x.isrcs.length}</td><td className="num"><Money v={x.r_amount} /></td><td className="num"><Int v={x.n_streams} /></td>
                <td className="num"><Money v={x.b_amount} /></td><td className="num"><Money v={x.p_amount} /></td><td className="small">{words(x.p_status)}</td>
                <td className="num"><Money v={x.variance} /></td><td><Outcome o={x.outcome} reason={x.hold_reason} provisional={x.provisional} /></td>
              </tr>
            ))}</tbody>
          </table>
          <Pager total={g.data.total} offset={offset} limit={100} onChange={setOffset} />
        </div>
      )}
      {sel && <GroupDrawer id={sel} onClose={() => setSel(null)} />}
    </Card>
  );
}

function GroupDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { go } = useApp();
  const q = useQuery({ queryKey: ["group", id], queryFn: () => api.get<any>(`/groups/${id}`) });
  const [tab, setTab] = useState<"calc" | "rows">("calc");
  const g = q.data;
  const fname = (fid: number) => g?.files[String(fid)] ?? `file #${fid}`;
  return (
    <Drawer open onClose={onClose} wide title={g ? g.title : "Group"} sub={g && <><span className="mono">{g.case_code}</span> · work {g.work_code} · {g.mapping_status}</>}
            actions={g?.case && <button className="btn sm" onClick={() => go(`cases/${g.case.id}`)}>Case: {words(g.case.status)}</button>}>
      {!g ? <Spinner /> : (
        <>
          <div className="row" style={{ marginBottom: 10 }}><Outcome o={g.outcome} reason={g.hold_reason} provisional={g.provisional} /></div>
          <div className="calc section">
            {[["R recording", g.r_amount], ["B comparison", g.b_amount], ["P publishing", g.p_amount], ["V = B − P", g.variance], ["Positive gap", g.positive_gap], ["Stream cross-check", g.b_stream]].map(([l, v]) => (
              <div key={l as string}><div className="l">{l}</div><div className={`v ${v === null ? "blank" : ""}`}>{v === null ? "" : money(v)}</div></div>
            ))}
            <div><div className="l">N streams</div><div className={`v ${g.n_streams === null ? "blank" : ""}`}>{g.n_streams === null ? "" : int(g.n_streams)}</div></div>
          </div>
          <Tabs value={tab} onChange={setTab} items={[{ key: "calc", label: "Calculation & question" }, { key: "rows", label: "Source rows", count: g.evidence.r_rows.length + g.evidence.p_rows.length + g.evidence.n_rows.length }]} />
          {tab === "calc" ? (
            <div className="col" style={{ gap: 14 }}>
              {g.evidence.formula && <div className="formula">{g.evidence.formula} → B = {money(g.b_amount)}{g.variance !== null && <> ; V = {money(g.b_amount)} − {money(g.p_amount)} = {money(g.variance)} (review tolerance {money(g.evidence.tolerance)})</>}</div>}
              <Kv items={[
                ["Rule", g.rule_key ? `${g.rule_key} v${g.rule_version} - ${words(g.method)}${g.share_treatment ? ` · ${words(g.share_treatment)}` : ""}` : words(g.method)],
                ["Route", words(g.route)],
                ["Publishing status", words(g.p_status)],
                ["Currency", g.currency ?? "—"],
                ["Limitations", g.limitations ?? "—"],
              ]} />
              <Card title="Like-for-like gates"><Checks items={g.gates} /></Card>
              <div className="note"><b>Clarification requested.</b> {g.question}</div>
              <Card title="Masters in this group (R summed once)" flush>
                <table className="tbl"><thead><tr><th>ISRC</th><th>Recording</th><th className="num">R</th><th className="num">N</th><th>Allocation</th></tr></thead>
                  <tbody>{g.recordings.map((m: any) => <tr key={m.isrc}><td className="mono">{m.isrc}</td><td>{m.title}</td><td className="num"><Money v={m.r} /></td><td className="num"><Int v={m.n === null ? null : Math.round(Number(m.n))} /></td><td>{m.allocation}</td></tr>)}</tbody></table>
              </Card>
            </div>
          ) : (
            <div className="col" style={{ gap: 14 }}>
              <Card title="Publishing rows (P, once per composition)" flush>
                <table className="tbl"><thead><tr><th>File</th><th>Row</th><th>Work</th><th>Party</th><th>Pool / source</th><th className="num">Amount</th></tr></thead>
                  <tbody>{g.evidence.p_rows.map((x: any, i: number) => <tr key={i}><td className="small">{fname(x.file_id)}</td><td>{x.row}</td><td className="mono">{x.work_code}</td><td className="small">{x.party} ({x.role})</td><td className="small">{x.pool} · {x.source}</td><td className="num"><Money v={x.amount} /></td></tr>)}</tbody></table>
                {!g.evidence.p_rows.length && <Empty>No publishing row - {words(g.p_status)} (not a zero).</Empty>}
              </Card>
              <Card title="Recording rows (R)" flush>
                <table className="tbl"><thead><tr><th>File</th><th>Row</th><th>ISRC</th><th>Month</th><th className="num">Amount</th><th>Alloc.</th></tr></thead>
                  <tbody>{g.evidence.r_rows.map((x: any, i: number) => <tr key={i}><td className="small">{fname(x.file_id)}</td><td>{x.row}</td><td className="mono">{x.isrc}</td><td>{(x.month ?? "").slice(0, 7)}</td><td className="num"><Money v={x.amount} /></td><td>{x.allocation}</td></tr>)}</tbody></table>
              </Card>
              <Card title={`Usage rows (N)${g.evidence.n_rows_total > g.evidence.n_rows.length ? ` - first ${g.evidence.n_rows.length} of ${g.evidence.n_rows_total}` : ""}`} flush>
                <table className="tbl"><thead><tr><th>File</th><th>Row</th><th>ISRC</th><th>Month</th><th className="num">Streams</th></tr></thead>
                  <tbody>{g.evidence.n_rows.map((x: any, i: number) => <tr key={i}><td className="small">{fname(x.file_id)}</td><td>{x.row}</td><td className="mono">{x.isrc}</td><td>{(x.month ?? "").slice(0, 7)}</td><td className="num"><Int v={x.streams} /></td></tr>)}</tbody></table>
              </Card>
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}

function Exceptions({ runId, counts }: { runId: number; counts: any[] }) {
  const [kind, setKind] = useState("");
  const q = useQuery({ queryKey: ["exc", runId, kind], queryFn: () => api.get<any[]>(`/runs/${runId}/exceptions${qs({ kind })}`) });
  return (
    <Card flush>
      <div className="filters" style={{ padding: "12px 12px 0" }}>
        <select className="input sm" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">all kinds</option>{counts.map((c) => <option key={c.kind} value={c.kind}>{words(c.kind)} ({c.n})</option>)}</select>
        <span className="legend">Every exception stays visible - unmatched rows feed the client report; nothing is silently excluded.</span>
      </div>
      {q.isLoading ? <Spinner /> : (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Kind</th><th>Subject</th><th className="num">Amount</th><th className="num">Streams</th><th>Owner</th><th>Next action</th></tr></thead>
          <tbody>{q.data!.map((e) => <tr key={e.id}><td className="small">{words(e.kind)}</td><td className="wrap">{e.subject}</td><td className="num"><Money v={e.amount} /></td>
            <td className="num"><Int v={e.streams} /></td><td className="small">{words(e.owner)}</td><td className="small wrap">{e.next_action}</td></tr>)}</tbody>
        </table></div>
      )}
    </Card>
  );
}
