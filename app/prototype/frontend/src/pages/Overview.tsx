import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { BarList, ChartCard, ColumnChart, DataTable } from "../components/charts";
import { Badge, Card, Empty, ErrorNote, InvariantList, PageHead, Spinner, Stat } from "../components/ui";
import { int, money } from "../format";
import { useApp, useRunJob } from "../state";
import type { Invariant } from "../types";

interface Overview {
  batch: any;
  validation?: { statements: number; passed: number; failed: number; extracted_total: number; standard: number; overseas: number; lines: number };
  builds: any[];
  build: null | {
    id: number; label: string; status: string; stats: any; invariants: Invariant[]; row_count: number;
    total_amount: number; total_mrm: number;
    by_section: { section: string; kind: string; total: number; count: number }[];
    fy: { fy: string; label: string; total: number }[];
    months: { month: string; label: string; total: number }[];
  };
  coverage: { id: number; mode: string; finding_count: number; revenue_at_risk: number; royalty_received: number; l3_policy: string }[];
  jobs: any[];
}

export default function OverviewPage() {
  const { meta } = useApp();
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/overview") });
  const ref = useQuery({ queryKey: ["reference-check"], queryFn: () => api.get<{ rows: any[] }>("/reference-check") });
  const run = useRunJob();
  const [err, setErr] = useState<unknown>(null);
  const loadDemo = () =>
    run("Load the reference run", () => api.post("/demo/load", { skip_exports: true })).catch(setErr);

  if (q.isLoading) return <Spinner />;
  const o = q.data;
  if (!o?.batch) {
    return (
      <>
        <PageHead title="Welcome to Sangam">
          IPRS royalty statements, the SVF catalogue and Spotify's own reports flow together here into one
          reconciled matrix - every rupee traced back to the file that paid it.
        </PageHead>
        <Card title="Start">
          <div className="col" style={{ gap: 12 }}>
            <div>Either create a batch and upload your files on <a href="#/batches">Batches &amp; Upload</a>, or load the
              April-2026 reference run from <code>Docs/input</code> (46 statements, the S-46 catalogue, Spotify MRM +
              usage, and the batch-4 song sheet) - it runs extraction, the build, a coverage audit, the mismatch
              report and the five reference merges end to end.</div>
            <div className="row">
              <button className="btn primary" onClick={loadDemo} disabled={!meta?.reference.inputs_available}>
                Load the reference run
              </button>
              {!meta?.reference.inputs_available && <span className="muted small">reference inputs not found on the server</span>}
            </div>
            <ErrorNote error={err} />
          </div>
        </Card>
      </>
    );
  }
  const b = o.build;
  const v = o.validation;
  const invOk = b ? b.invariants.filter((i) => i.passed).length : 0;
  const royalty = b?.by_section.filter((s) => s.kind === "royalty").sort((x, y) => y.total - x.total) ?? [];
  const cov = o.coverage[0];
  return (
    <>
      <PageHead title="Overview" actions={b && <Badge tone={b.status === "ready" ? "good" : "crit"}>{b.label} · {b.status}</Badge>}>
        Batch #{o.batch.id} “{o.batch.label}” - {o.batch.files} files. Royalty (what IPRS distributed) and platform gross
        revenue (what Spotify reported) are different kinds of money and are never added together.
      </PageHead>
      {!b && (
        <Card title="No build yet">
          Extract the batch and start a build on <a href="#/batches">Batches &amp; Upload</a>.
        </Card>
      )}
      {b && (
        <>
          <div className="grid2 section">
            <div className="card stat" style={{ padding: "18px 20px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
              <div className="label">Royalty distributed by IPRS (col D)</div>
              <div className="hero">{money(b.total_amount)}</div>
              <div className="meta" style={{ marginTop: 6 }}>
                {v?.passed}/{v?.statements} statements reconciled to their own printed TOTAL ROYALTIES ·
                {" "}{int(v?.lines)} royalty lines · {v?.standard} standard + {v?.overseas} overseas
              </div>
            </div>
            <div className="kpis two">
              <Stat label="Platform gross revenue (col E)" value={money(b.total_mrm)} meta="Spotify MRM, gross - reported, not distributed" />
              <Stat label="Rows in the matrix" value={int(b.row_count)}
                    meta={`${int(b.stats.catalogue_rows)} catalogue · ${int(b.stats.statement_rows)} statement-only · ${int((b.stats.platform_rows ?? 0) + (b.stats.usage_rows ?? 0))} platform-only`} />
              <Stat label="Invariants" value={<span>{invOk}/{b.invariants.length} <span className="small" style={{ color: invOk === b.invariants.length ? "var(--good-ink)" : "var(--crit-ink)" }}>{invOk === b.invariants.length ? "✓ all pass" : "✕ failing"}</span></span>} meta="architecture §20" />
              <Stat label="Songs earning, not in the sheet" value={cov ? int(cov.finding_count) : "-"}
                    meta={cov ? `latest coverage run #${cov.id} · ${cov.mode} · ${cov.l3_policy === "reference" ? "reference link" : "V2 rule"} · ${money(cov.revenue_at_risk)} at stake` : "run one on Coverage Audit"} />
            </div>
          </div>
          <div className="grid3 section">
            <ChartCard title="Royalty by source" sub="IPRS distributions in this build, one bar per section"
                       table={<DataTable head={["Section", "Royalty"]} rows={royalty.map((s) => [s.section, s.total])} />}>
              <BarList data={royalty.map((s) => ({ label: s.section, value: s.total, sub: `${s.count} distribution(s)` }))} />
            </ChartCard>
            <ChartCard title="Royalty by earning year" sub="Indian FY (1 Apr - 31 Mar), month-weighted split"
                       table={<DataTable head={["Financial year", "Royalty"]} rows={b.fy.map((f) => [f.label, f.total])} />}>
              <ColumnChart data={b.fy.map((f) => ({ label: f.fy === "NA" ? "Not stated" : `FY${f.label.slice(5, 7)}-${f.label.slice(-2)}`, value: f.total, deemph: f.fy === "NA" }))} />
              <div className="muted small" style={{ marginTop: 6 }}>Grey: statements whose filename states no period.</div>
            </ChartCard>
            <ChartCard title="Spotify gross revenue by month" sub="MRM report - gross, kept apart from royalty"
                       table={<DataTable head={["Month", "Gross revenue"]} rows={b.months.map((m) => [m.label, m.total])} />}>
              <ColumnChart data={b.months.map((m) => ({ label: `${m.label.slice(0, 3)} '${m.label.slice(-2)}`, value: m.total }))} />
            </ChartCard>
          </div>
          <div className="grid2 section">
            <Card title="Build invariants" sub={`${b.label} · every build, coverage run and merge apply asserts these`}>
              <InvariantList items={b.invariants} />
            </Card>
            <Card title="Reference run check" sub="Architecture Appendix C - the numbers a rebuild must reproduce">
              {ref.data?.rows.length ? (
                <div className="col" style={{ gap: 10 }}>
                  {ref.data.rows.map((r) => (
                    <div key={r.item} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                      <div className="row">
                        {r.match === true && <Badge tone="good">✓ match</Badge>}
                        {r.match === false && <Badge tone="crit">✕ differs</Badge>}
                        {r.match === null && <Badge tone="info">ⓘ explained</Badge>}
                        <b className="small">{r.item}</b>
                      </div>
                      <div className="small ink2" style={{ marginTop: 3 }}>
                        expected <span className="mono">{r.expected}</span> · actual <span className="mono">{r.actual}</span>
                      </div>
                      {r.note && <div className="small muted" style={{ marginTop: 2 }}>{r.note}</div>}
                    </div>
                  ))}
                </div>
              ) : <div className="muted small">Load the reference run to compare against the architecture's published numbers.</div>}
            </Card>
          </div>
        </>
      )}
      <Card title="Recent jobs" flush>
        {o.jobs.length ? (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>#</th><th>Job</th><th>Status</th><th>Message</th><th>Started</th></tr></thead>
              <tbody>
                {o.jobs.map((j) => (
                  <tr key={j.id}>
                    <td className="mono">{j.id}</td><td>{j.kind}</td>
                    <td><Badge tone={j.status === "succeeded" ? "good" : j.status === "failed" ? "crit" : "info"}>{j.status}</Badge></td>
                    <td className="small ink2">{j.message}</td><td className="small muted nowrap">{j.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>No jobs yet.</Empty>}
      </Card>
    </>
  );
}
