import { useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useApp } from "./session";
import { Button, Dialog, DownloadButton, Loading, Notice, ScrollX } from "./ui";

export type PreviewReport = { id: number; label: string };
type Preview = {
  filename: string; sheets: string[]; sheet: number; rows: string[][]; total_rows: number; total_cols: number;
  shown_rows: number;
};

const NUM = /^-?[\d,]+(\.\d+)?$/;
const FROZEN = 2;                                         // columns A and B stay in view while scrolling sideways
const frozen = (i: number) => (i === 0 ? "pv-fa" : i === FROZEN - 1 ? "pv-fb" : "");
const col = (i: number) => (i >= 26 ? String.fromCharCode(64 + Math.floor(i / 26)) : "") + String.fromCharCode(65 + (i % 26));

/** A look inside a report workbook before downloading it: its first rows, sheet by sheet. */
export function ReportPreview({ reports, start = 0, onClose }: { reports: PreviewReport[]; start?: number; onClose: () => void }) {
  const { toast } = useApp();
  const [pick, setPick] = useState(start);
  const [sheet, setSheet] = useState(0);
  const r = reports[pick];
  const q = useQuery({
    queryKey: ["preview", r.id, sheet], queryFn: () => api.get<Preview>(`/reports/${r.id}/preview?sheet=${sheet}`),
    staleTime: 60_000,
  });
  const d = q.data;
  const table = useRef<HTMLTableElement>(null);
  useLayoutEffect(() => {                                 // frozen columns sit right after the row numbers and column A
    const t = table.current;
    const th = t?.querySelectorAll<HTMLElement>("thead th");
    if (!t || !th || th.length < 2) return;
    t.style.setProperty("--pv-left-a", `${th[0].offsetWidth}px`);
    t.style.setProperty("--pv-left-b", `${th[0].offsetWidth + th[1].offsetWidth}px`);
  }, [d]);
  return (
    <Dialog title="Preview" sub={d?.filename ?? r.label} onClose={onClose} wide="xl">
      {reports.length > 1 && (
        <div className="seg pv-tabs" role="tablist" aria-label="Report">
          {reports.map((x, i) => (
            <button key={x.id} role="tab" aria-selected={i === pick} className={i === pick ? "on" : ""}
                    onClick={() => { setPick(i); setSheet(0); }}>{x.label}</button>
          ))}
        </div>
      )}
      {d && d.sheets.length > 1 && (
        <div className="pv-sheets" role="tablist" aria-label="Sheet">
          {d.sheets.map((name, i) => (
            <button key={name} role="tab" aria-selected={i === d.sheet} className={i === d.sheet ? "on" : ""}
                    onClick={() => setSheet(i)}>{name}</button>
          ))}
        </div>
      )}
      {q.isLoading ? <Loading text="Opening the workbook…" /> : q.isError ? <Notice tone="bad">{(q.error as Error).message}</Notice>
        : d && d.rows.length === 0 ? <Notice>This sheet is empty.</Notice> : d && (
        <ScrollX className="pv-wrap" label="Report preview">
          <table className="pv" ref={table}>
            <thead><tr><th className="pv-n" />{d.rows[0].map((_, i) => <th key={i} className={frozen(i)}>{col(i)}</th>)}</tr></thead>
            <tbody>
              {d.rows.map((row, ri) => (
                <tr key={ri}>
                  <th className="pv-n">{ri + 1}</th>
                  {row.map((v, ci) => <td key={ci} className={`${NUM.test(v) ? "num" : ""} ${frozen(ci)}`} title={v.length > 40 ? v : undefined}>{v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollX>
      )}
      <div className="actions spread">
        <span className="muted small">{d && (d.total_rows > d.shown_rows
          ? `Showing the first ${d.shown_rows.toLocaleString("en-IN")} of ${d.total_rows.toLocaleString("en-IN")} rows. Download the file for everything.`
          : `${d.shown_rows.toLocaleString("en-IN")} rows.`)}</span>
        <span className="row">
          <Button onClick={onClose}>Close</Button>
          <DownloadButton path={`/reports/${r.id}/download`} onError={(m) => toast(m, true)}>Download</DownloadButton>
        </span>
      </div>
    </Dialog>
  );
}
