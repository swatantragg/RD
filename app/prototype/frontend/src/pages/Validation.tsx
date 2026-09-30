import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Badge, Card, Drawer, Empty, PageHead, PassBadge, Spinner } from "../components/ui";
import { dmy, money } from "../format";
import { useApp } from "../state";

export default function Validation() {
  const { batchId } = useApp();
  const q = useQuery({ queryKey: ["validation", batchId], queryFn: () => api.get<any>(`/batches/${batchId}/validation`), enabled: !!batchId });
  const [open, setOpen] = useState<any>(null);
  if (!batchId) return <Empty>No batch.</Empty>;
  if (q.isLoading) return <Spinner />;
  const v = q.data;
  return (
    <>
      <PageHead title="Validation">
        One row per statement. A statement may contribute to a build only when its money lines, its block sub-total
        lines and its own printed TOTAL ROYALTIES agree (tolerance 0.05) - and extraction must stop before that total
        row, or the grand total lands on the last work (defect D1).
      </PageHead>
      <div className="strip section">
        <div><div className="v">{v.summary.statements}</div><div className="l">statements</div></div>
        <div><div className="v" style={{ color: v.summary.failed ? "var(--crit-ink)" : "var(--good-ink)" }}>{v.summary.passed} / {v.summary.statements}</div><div className="l">reconciled (PASS)</div></div>
        <div><div className="v">{v.summary.standard} + {v.summary.overseas}</div><div className="l">standard + overseas schema</div></div>
        <div><div className="v">{v.summary.lines.toLocaleString("en-US")}</div><div className="l">royalty lines extracted</div></div>
        <div><div className="v num">{money(v.summary.extracted_total)}</div><div className="l">extracted total</div></div>
        <div><div className="v num">{money(v.summary.printed_total)}</div><div className="l">printed totals</div></div>
      </div>
      {v.summary.failed > 0 && <div className="note crit section">{v.summary.failed} statement(s) failed - a build is blocked until they are resolved (or forced).</div>}
      <Card flush>
        {v.rows.length ? (
          <div className="tbl-wrap" style={{ maxHeight: "calc(100vh - 290px)" }}>
            <table className="tbl">
              <thead><tr>
                <th>S-no</th><th>File</th><th>Section</th><th>Distribution</th><th>Schema</th><th>Period</th><th>Issued</th>
                <th className="num">Lines</th><th className="num">Extracted</th><th className="num">Sub-totals</th>
                <th className="num">Printed total</th><th className="num">Difference</th><th>Result</th>
              </tr></thead>
              <tbody>
                {v.rows.map((r: any) => (
                  <tr key={r.statement_id} className="click" onClick={() => setOpen(r)}>
                    <td className="mono">{r.sheet}</td>
                    <td style={{ maxWidth: 320 }} className="small">{r.file}</td>
                    <td className="small">{r.section}</td>
                    <td className="mono small">{r.dist_no}</td>
                    <td className="small">{r.schema}</td>
                    <td className="small">{r.period}</td>
                    <td className="small nowrap">{dmy(r.stmt_date)}</td>
                    <td className="num">{r.lines.toLocaleString("en-US")}</td>
                    <td className="num">{money(r.extracted)}</td>
                    <td className="num">{money(r.subtotal)}</td>
                    <td className="num">{money(r.printed)}</td>
                    <td className="num">{r.difference === null ? "" : r.difference.toFixed(6)}</td>
                    <td><PassBadge ok={r.result === "PASS"} />{r.anomalies.length > 0 && <Badge tone="warn">{r.anomalies.length} anomaly</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>Nothing extracted yet.</Empty>}
      </Card>
      {open && (
        <Drawer open onClose={() => setOpen(null)} title={`${open.sheet} · ${open.section}`} sub={open.file}>
          <div className="kv">
            <div>Schema</div><div>{open.schema} (amount column by header text)</div>
            <div>Distribution</div><div className="mono">{open.dist_no}</div>
            <div>Period</div><div>{open.period}</div>
            <div>Statement date</div><div>{dmy(open.stmt_date)} (max zip member timestamp)</div>
            <div>Works · blocks · lines</div><div>{open.works} · {open.blocks} · {open.lines}</div>
            <div>Σ money lines</div><div className="num" style={{ textAlign: "left" }}>{money(open.extracted)}</div>
            <div>Σ sub-total lines</div><div>{money(open.subtotal)} ({open.subtotal_lines} lines)</div>
            <div>Printed TOTAL ROYALTIES</div><div>{money(open.printed)}</div>
            <div>Checks</div>
            <div className="col" style={{ gap: 4 }}>
              <span><PassBadge ok={!!open.checks.money_vs_printed} /> money lines vs printed total</span>
              <span><PassBadge ok={open.checks.money_vs_subtotal !== false} /> money lines vs sub-total lines</span>
              <span><PassBadge ok={!!open.checks.stopped_before_total} /> stopped before the TOTAL ROYALTIES row</span>
            </div>
          </div>
          {open.footer && (
            <>
              <h3 style={{ marginTop: 18 }}>Footer summaries (independent reconciliation sources)</h3>
              <div className="small ink2" style={{ margin: "4px 0 8px" }}>
                language summary {open.footer.language_total !== null ? money(open.footer.language_total) : "-"} ·
                pool / source summary {open.footer.pool_total !== null ? money(open.footer.pool_total) : "-"}
              </div>
              <table className="tbl small">
                <thead><tr><th>Pool</th><th>Source</th><th className="num">Works</th><th className="num">Amount</th></tr></thead>
                <tbody>{open.footer.pools.map((p: any, i: number) => (
                  <tr key={i}><td>{p.pool}</td><td>{p.description || p.source}</td><td className="num">{p.works}</td><td className="num">{money(p.amount)}</td></tr>
                ))}</tbody>
              </table>
            </>
          )}
          <h3 style={{ marginTop: 18 }}>Anomalies</h3>
          {open.anomalies.length ? open.anomalies.map((a: any, i: number) => <div key={i} className="note warn small" style={{ marginTop: 6 }}>{a.kind} · row {a.sheet_row}: {a.detail}</div>)
            : <div className="muted small">None - every work id parsed, no money before a block.</div>}
        </Drawer>
      )}
    </>
  );
}
