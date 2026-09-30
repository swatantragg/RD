// Statement register + the gap lists (§14) - all derived from the same tables, never by hand.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api";
import { BarList, ChartCard, DataTable } from "../components/charts";
import { Badge, Card, Empty, IsrcChips, Money, PageHead, PassBadge, Spinner, Tabs, WorkChips } from "../components/ui";
import { dmy, money } from "../format";
import { useApp } from "../state";
import type { MatrixRow } from "../types";

export default function Statements() {
  const { buildId } = useApp();
  const [tab, setTab] = useState<"register" | "works" | "platform" | "usage">("register");
  const sts = useQuery({ queryKey: ["stmts", buildId], queryFn: () => api.get<any[]>(`/builds/${buildId}/statements`), enabled: !!buildId });
  const origin = tab === "works" ? "statement" : tab === "platform" ? "platform" : "usage";
  const gap = useQuery({
    queryKey: ["gap", buildId, origin], queryFn: () => api.get<MatrixRow[]>(`/builds/${buildId}/rows?origin=${origin}&sort=amount`),
    enabled: !!buildId && tab !== "register",
  });
  const byCat = useMemo(() => {
    const m = new Map<string, { total: number; n: number }>();
    (sts.data ?? []).forEach((s) => {
      const k = s.section;
      const v = m.get(k) ?? { total: 0, n: 0 };
      v.total += Math.round(s.extracted_total * 100) / 100;
      v.n += 1;
      m.set(k, v);
    });
    return [...m.entries()].map(([k, v]) => ({ label: k, value: Math.round(v.total * 100) / 100, n: v.n })).sort((a, b) => b.value - a.value);
  }, [sts.data]);
  if (!buildId) return <Empty>No build yet.</Empty>;
  const grand = byCat.reduce((a, x) => a + x.value, 0);
  const rows = gap.data ?? [];
  return (
    <>
      <PageHead title="Statements & Gaps">
        The statement register (what each distribution paid, reconciled to its own printed total) and the three
        companion gap lists - views of the build kept for continuity. New work should use a Coverage Audit, which carries
        the mode, the evidence flag and the accuracy contract.
      </PageHead>
      <Tabs value={tab} onChange={setTab} items={[
        { key: "register", label: "Statement register", count: sts.data?.length },
        { key: "works", label: "Works paid, not in the catalogue" },
        { key: "platform", label: "Platform revenue, not in the catalogue" },
        { key: "usage", label: "Streams only, not in the catalogue" }]} />
      {tab === "register" && (sts.isLoading ? <Spinner /> : (
        <div className="grid2" style={{ gridTemplateColumns: "1fr minmax(320px, 420px)", alignItems: "start" }}>
          <Card flush title={`${sts.data?.length ?? 0} statements`} sub={`grand total ${money(grand)}`}>
            <div className="tbl-wrap" style={{ maxHeight: "calc(100vh - 300px)" }}>
              <table className="tbl">
                <thead><tr><th>S-no</th><th>File</th><th>Distribution</th><th>Section</th><th>Period</th><th>Issued</th>
                  <th className="num">Works</th><th className="num">Lines</th><th className="num">Total</th><th className="num">%</th><th>Recon</th></tr></thead>
                <tbody>{(sts.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td className="mono">S-{s.s_no}</td><td className="small" style={{ maxWidth: 300 }}>{s.filename}</td>
                    <td className="mono small">{s.dist_no || "Not specified"}</td><td className="small">{s.section}</td>
                    <td className="small">{s.period}</td><td className="small nowrap">{dmy(s.stmt_date)}</td>
                    <td className="num">{s.work_count}</td><td className="num">{s.line_count}</td>
                    <td className="num">{money(s.extracted_total)}</td>
                    <td className="num small">{grand ? ((s.extracted_total / grand) * 100).toFixed(2) : ""}</td>
                    <td><PassBadge ok={!!s.reconciled} /></td>
                  </tr>))}</tbody>
              </table>
            </div>
          </Card>
          <ChartCard title="By source / category" sub="royalty per section, one hue"
                     table={<DataTable head={["Section", "Total"]} rows={byCat.map((x) => [x.label, x.value])} />}>
            <BarList data={byCat.map((x) => ({ label: x.label, value: x.value, sub: `${x.n} statement(s)` }))} />
          </ChartCard>
        </div>
      ))}
      {tab !== "register" && (
        <Card flush title={`${rows.length} row(s)`} sub={tab === "works" ? "statement-only works: paid by IPRS under an internal number the catalogue does not list"
          : tab === "platform" ? "ISRCs only the revenue report knows (no catalogue ISRC, no name link)" : "ISRCs with streams but no revenue and no royalty"}>
          {gap.isLoading ? <Empty><Spinner /></Empty> : rows.length ? (
            <div className="tbl-wrap" style={{ maxHeight: "calc(100vh - 300px)" }}>
              <table className="tbl">
                <thead><tr><th>Song name</th><th>Internal no</th><th>ISRC</th><th className="num">Royalty</th><th className="num">Platform revenue</th><th className="num">Streams</th><th>Status</th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td><td><WorkChips works={r.works} unreg={r.works_unreg} /></td><td><IsrcChips isrcs={r.isrcs} unreg={r.unreg} max={2} /></td>
                    <td className="num"><Money v={r.d} /></td><td className="num"><Money v={r.e} /></td>
                    <td className="num">{Math.round(r.u).toLocaleString("en-US")}</td>
                    <td>{r.b.length ? <Badge tone="neutral">{r.b.join(" · ")}</Badge> : null}</td>
                  </tr>))}</tbody>
                <tfoot><tr><td colSpan={3}>TOTAL</td><td className="num">{money(rows.reduce((a, r) => a + r.d, 0))}</td>
                  <td className="num">{money(rows.reduce((a, r) => a + r.e, 0))}</td><td className="num">{Math.round(rows.reduce((a, r) => a + r.u, 0)).toLocaleString("en-US")}</td><td /></tr></tfoot>
              </table>
            </div>
          ) : <Empty>Nothing in this list.</Empty>}
        </Card>
      )}
    </>
  );
}
