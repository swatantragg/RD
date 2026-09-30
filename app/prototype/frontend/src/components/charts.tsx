// Charts follow the data-viz method: one hue for a single series, thin columns with 4px
// rounded data-ends, hairline solid grid, values on caps, a hover tooltip per mark, and a
// table-view twin for every chart.
import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compact, money } from "../format";

export function ChartCard({ title, sub, table, children }: { title: string; sub?: string; table: ReactNode; children: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="card" style={{ margin: 0 }}>
      <div className="card-h">
        <div>
          <h3>{title}</h3>
          {sub && <div className="sub">{sub}</div>}
        </div>
        <div className="spacer" />
        <button className="btn sm ghost" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}>
          {asTable ? "Chart" : "Table"}
        </button>
      </div>
      <div className="card-b">{asTable ? table : children}</div>
    </figure>
  );
}

function Tip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="tip">
      <b className="num">{money(p.value)}</b>
      <div className="muted">{p.label}</div>
    </div>
  );
}

export interface ColumnDatum { label: string; value: number; deemph?: boolean }

export function ColumnChart({ data, height = 220 }: { data: ColumnDatum[]; height?: number }) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 22, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" tickLine={false} interval={0} height={36} tick={{ fontSize: 11.5 }} />
          <YAxis tickFormatter={(v) => compact(v)} width={52} tickLine={false} axisLine={false} />
          <Tooltip content={<Tip />} cursor={{ fill: "var(--surface-2)" }} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={24} className="chart-bar" isAnimationActive={false}>
            {data.map((d) => <Cell key={d.label} className={d.deemph ? "chart-bar-deemph" : "chart-bar"} />)}
            <LabelList dataKey="value" position="top" formatter={(v: number) => compact(v)} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal ranked bars for nominal categories: one hue, value at the tip, label on the left. */
export function BarList({ data }: { data: { label: string; value: number; sub?: string }[] }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="barlist">
      {data.map((d) => (
        <div key={d.label} style={{ display: "contents" }}>
          <span className="lbl" title={d.label}>{d.label}</span>
          <span className="b" title={`${d.label}: ${money(d.value)}${d.sub ? ` · ${d.sub}` : ""}`}>
            <i style={{ width: `${Math.max(0.5, (d.value / max) * 100)}%` }} />
          </span>
          <span className="num small">{money(d.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function DataTable({ rows, head }: { rows: (string | number)[][]; head: string[] }) {
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead><tr>{head.map((h, i) => <th key={h} className={i > 0 ? "num" : ""}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r[0])}>
              {r.map((c, i) => <td key={i} className={i > 0 ? "num" : ""}>{typeof c === "number" ? money(c) : c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
