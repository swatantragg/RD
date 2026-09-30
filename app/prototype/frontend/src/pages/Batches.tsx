import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../api";
import { Badge, Card, Drawer, Empty, ErrorNote, Field, PageHead, Spinner } from "../components/ui";
import { bytes, dmy, money } from "../format";
import { useApp, useRunJob } from "../state";
import type { SourceFile } from "../types";

const KIND_TONE: Record<string, "good" | "info" | "warn" | "crit" | "neutral"> = {
  STATEMENT_STANDARD: "info", STATEMENT_OVERSEAS: "info", CATALOGUE: "good", USER_SHEET: "good",
  PLATFORM_REVENUE: "warn", PLATFORM_USAGE: "warn", UNKNOWN: "crit",
};
const SHORT: Record<string, string> = {
  STATEMENT_STANDARD: "A · statement", STATEMENT_OVERSEAS: "B · overseas", CATALOGUE: "C · catalogue",
  PLATFORM_REVENUE: "D · MRM revenue", PLATFORM_USAGE: "E · usage", USER_SHEET: "F · song sheet", UNKNOWN: "unknown",
};

export default function Batches() {
  const { batches, batchId, setBatchId, meta } = useApp();
  const qc = useQueryClient();
  const run = useRunJob();
  const [label, setLabel] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<SourceFile | null>(null);
  const [fallback, setFallback] = useState("exact");
  const [force, setForce] = useState(false);
  const [catSheet, setCatSheet] = useState<number | "">("");
  const input = useRef<HTMLInputElement>(null);
  const files = useQuery({
    queryKey: ["files", batchId], queryFn: () => api.get<SourceFile[]>(`/batches/${batchId}/files`), enabled: !!batchId,
  });
  const batch = batches.find((b) => b.id === batchId);

  const create = async () => {
    setErr(null);
    try {
      const b = await api.post<{ id: number }>("/batches", { label: label || `Batch ${new Date().toISOString().slice(0, 10)}` });
      setLabel("");
      await qc.invalidateQueries({ queryKey: ["batches"] });
      setBatchId(b.id);
    } catch (e) { setErr(e); }
  };
  const upload = async (list: FileList | File[]) => {
    if (!batchId || !list.length) return;
    setBusy(true); setErr(null);
    try {
      const res = await api.upload<any[]>(`/batches/${batchId}/files`, Array.from(list));
      const dup = res.filter((r) => r.duplicate).length;
      const bad = res.filter((r) => r.error).length;
      setUploadMsg(`${res.length - dup - bad} new file(s)${dup ? `, ${dup} duplicate(s) - same sha256, kept once` : ""}${bad ? `, ${bad} rejected` : ""}.`);
      qc.invalidateQueries();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const extract = () => run("Extract (S2-S4)", () => api.post(`/batches/${batchId}/extract`)).catch(setErr);
  const build = () =>
    run("Build (S5-S8)", () => api.post(`/batches/${batchId}/builds`, {
      name_fallback: fallback, force, catalogue_sheet_id: catSheet || null,
    })).catch(setErr);
  const demo = () => run("Load the reference run", () => api.post("/demo/load", { skip_exports: true })).catch(setErr);

  const fl = files.data ?? [];
  const sheets = fl.filter((f) => f.sheet);
  const counts = fl.reduce<Record<string, number>>((a, f) => ({ ...a, [f.status]: (a[f.status] ?? 0) + 1 }), {});
  return (
    <>
      <PageHead title="Batches & Upload">
        Drop statements, the catalogue, platform reports or any song sheet. The shape of every file is detected from
        its header text (never its folder, sheet name or column position); statement metadata comes from the filename
        and the issue date hidden in the .xlsx zip. Re-uploading the same bytes is a no-op.
      </PageHead>
      <Card className="section" title="Batch" sub="a batch is one set of uploads that is built together">
        <div className="row wrap" style={{ gap: 8 }}>
          {batches.map((b) => (
            <button key={b.id} className={`btn sm ${b.id === batchId ? "primary" : ""}`} onClick={() => setBatchId(b.id)}>
              #{b.id} {b.label} · {b.files} files
            </button>
          ))}
          {!batches.length && <span className="muted small">No batches yet.</span>}
          <span className="spacer" />
          <input className="input sm" placeholder="new batch label" value={label} onChange={(e) => setLabel(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && create()} style={{ width: 220 }} />
          <button className="btn sm" onClick={create}>Create batch</button>
          {meta?.reference.inputs_available && (
            <button className="btn sm" onClick={demo} title="Creates a batch from Docs/input and runs the whole pipeline end to end">
              Load the April-2026 reference run
            </button>
          )}
        </div>
      </Card>
      {batch ? (
        <div className="col" style={{ gap: 16 }}>
          <div className={`drop ${over ? "over" : ""}`} onClick={() => input.current?.click()}
               onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
               onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
            <input ref={input} type="file" multiple accept=".xlsx,.xlsm" hidden onChange={(e) => e.target.files && upload(e.target.files)} />
            {busy ? <Spinner /> : <b>Drop .xlsx files here or click to choose</b>}
            <div className="small" style={{ marginTop: 4 }}>into batch #{batch.id} “{batch.label}” - statements, catalogue, platform reports, song sheets</div>
          </div>
          {uploadMsg && <div className="note">{uploadMsg}</div>}
          <Card title="Process" sub={`${fl.length} files · ${counts.uploaded ?? 0} waiting · ${counts.extracted ?? 0} extracted · ${counts.quarantined ?? 0} quarantined · ${counts.failed ?? 0} failed`}>
            <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
              <button className="btn primary" onClick={extract} disabled={!fl.length}>1 · Extract &amp; reconcile</button>
              <Field label="Catalogue for the build">
                <select className="input sm" value={catSheet} onChange={(e) => setCatSheet(Number(e.target.value) || "")}>
                  <option value="">latest catalogue in the batch</option>
                  {sheets.map((f) => <option key={f.sheet.id} value={f.sheet.id}>{f.sheet.label}{f.sheet.is_catalogue ? " (catalogue)" : ""}</option>)}
                </select>
              </Field>
              <Field label="Song-name fallback for platform revenue">
                <select className="input sm" value={fallback} onChange={(e) => setFallback(e.target.value)}>
                  <option value="exact">B4 + B5 exact name (default, stamped)</option>
                  <option value="exact+stripped">+ B6 version-stripped (SKV7 behaviour)</option>
                  <option value="off">off - names never move money</option>
                </select>
              </Field>
              <label className="check small" title="Build even though a statement failed reconciliation (recorded in the build config)">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> force
              </label>
              <button className="btn primary" onClick={build} disabled={!counts.extracted}>2 · Build the matrix</button>
            </div>
            <ErrorNote error={err} />
          </Card>
          <Card title="Files" flush>
            {files.isLoading ? <Empty><Spinner /></Empty> : fl.length ? (
              <div className="tbl-wrap" style={{ maxHeight: 620 }}>
                <table className="tbl">
                  <thead><tr>
                    <th>#</th><th style={{ minWidth: 320 }}>File</th><th>Shape</th><th>S-no</th><th>Category / section</th><th>Distribution</th>
                    <th>Period</th><th>Issued</th><th className="num">Total</th><th>Status</th><th></th>
                  </tr></thead>
                  <tbody>
                    {fl.map((f) => (
                      <tr key={f.id}>
                        <td className="mono small">{f.upload_seq}</td>
                        <td>
                          <div style={{ wordBreak: "break-word" }}>{f.filename}</div>
                          <div className="muted small mono">{f.sha256.slice(0, 12)}… · {bytes(f.size)}</div>
                        </td>
                        <td><Badge tone={KIND_TONE[f.kind] ?? "neutral"} title={f.kind_label}>{SHORT[f.kind] ?? f.kind}</Badge>
                          {f.kind !== f.detected_kind && <div className="small muted">override</div>}</td>
                        <td className="mono small nowrap">{f.statement ? `S-${f.statement.s_no}` : f.meta?.s_no ? `S-${f.meta.s_no}` : ""}</td>
                        <td className="small">{f.statement?.section ?? f.meta?.section ?? (f.sheet ? `${f.sheet.row_count} rows${f.sheet.is_catalogue ? " · catalogue" : ""}` : f.report ? `${f.report.line_count} lines · ${f.report.isrc_count} ISRCs` : "")}</td>
                        <td className="mono small nowrap">{f.statement?.dist_no ?? f.meta?.dist_no ?? ""}</td>
                        <td className="small">{f.statement?.period ?? f.meta?.period ?? (f.report ? `${f.report.month_from} … ${f.report.month_to}` : "")}</td>
                        <td className="small nowrap">{dmy(f.statement?.stmt_date ?? f.meta?.stmt_date)}</td>
                        <td className="num small">{f.statement ? money(f.statement.extracted_total) : f.report ? money(f.report.total) : ""}</td>
                        <td>
                          {f.status === "extracted" && (f.statement ? (f.statement.reconciled ? <Badge tone="good">✓ reconciled</Badge> : <Badge tone="crit">✕ recon FAIL</Badge>) : <Badge tone="good">✓ extracted</Badge>)}
                          {f.status === "uploaded" && <Badge tone="info">waiting</Badge>}
                          {f.status === "quarantined" && <Badge tone="crit" title={f.error ?? ""}>quarantined</Badge>}
                          {f.status === "failed" && <Badge tone="crit" title={f.error ?? ""}>failed</Badge>}
                          {f.sheet && f.sheet.mapping_status === "proposed" && <div><a href="#/sheets" className="small">confirm column map</a></div>}
                        </td>
                        <td><button className="btn sm" onClick={() => setEdit(f)}>Edit</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>No files in this batch yet.</Empty>}
          </Card>
        </div>
      ) : <Card title="No batch selected"><div className="muted">Create a batch above, or load the reference run.</div></Card>}
      {edit && <FileEditor file={edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function FileEditor({ file, onClose }: { file: SourceFile; onClose: () => void }) {
  const { meta } = useApp();
  const qc = useQueryClient();
  const [kind, setKind] = useState(file.kind);
  const [cat, setCat] = useState(file.override.category_code ?? file.meta.category_code ?? "");
  const [dist, setDist] = useState(file.override.dist_no ?? file.meta.dist_no ?? "");
  const [pf, setPf] = useState(file.override.period_from ?? (file.meta.p_start ?? "").slice(0, 7));
  const [pt, setPt] = useState(file.override.period_to ?? (file.meta.p_end ?? "").slice(0, 7));
  const [soc, setSoc] = useState(file.override.society_code ?? file.meta.society_code ?? "");
  const [err, setErr] = useState<unknown>(null);
  const isStmt = kind.startsWith("STATEMENT");
  const save = async () => {
    setErr(null);
    try {
      const body: Record<string, unknown> = { kind };
      if (isStmt) Object.assign(body, { category_code: cat, dist_no: dist, society_code: soc || null,
        ...(pf && pt ? { period_from: pf, period_to: pt } : {}) });
      await api.patch(`/files/${file.id}`, body);
      await qc.invalidateQueries();
      onClose();
    } catch (e) { setErr(e); }
  };
  const remove = async () => {
    try { await api.del(`/files/${file.id}`); await qc.invalidateQueries(); onClose(); } catch (e) { setErr(e); }
  };
  return (
    <Drawer open onClose={onClose} title={file.filename} sub={`detected: ${file.kind_label} · sha256 ${file.sha256.slice(0, 16)}…`}>
      <div className="col" style={{ gap: 12 }}>
        {file.error && <div className="note warn">{file.error}</div>}
        <Field label="Shape (operator override)">
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(meta?.kinds ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        {isStmt && (
          <>
            <Field label="Category">
              <select className="input" value={cat} onChange={(e) => setCat(e.target.value)}>
                {meta?.categories.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
              </select>
            </Field>
            {cat === "overseas" && (
              <Field label="Society">
                <select className="input" value={soc} onChange={(e) => setSoc(e.target.value)}>
                  <option value="">(none)</option>
                  {meta?.societies.map((s) => <option key={s.code} value={s.code}>{s.code} {s.name} ({s.country})</option>)}
                </select>
              </Field>
            )}
            <Field label="Distribution number"><input className="input" value={dist} onChange={(e) => setDist(e.target.value)} /></Field>
            <div className="row">
              <Field label="Period from"><input className="input" type="month" value={pf} onChange={(e) => setPf(e.target.value)} /></Field>
              <Field label="Period to"><input className="input" type="month" value={pt} onChange={(e) => setPt(e.target.value)} /></Field>
            </div>
            <div className="muted small">Changing the period moves this statement's money between FY columns on the next build; a statement without a period lands in "Period Not Stated".</div>
          </>
        )}
        <div className="row">
          <button className="btn primary" onClick={save}>Save override</button>
          <button className="btn danger" onClick={remove}>Remove file</button>
        </div>
        <ErrorNote error={err} />
        <h3 style={{ marginTop: 8 }}>First rows (as sniffed)</h3>
        <div className="tbl-wrap" style={{ maxHeight: 300 }}>
          <table className="tbl small">
            <tbody>
              {file.sniff.map((r, i) => (
                <tr key={i}>{r.slice(0, 12).map((c, j) => <td key={j} className="small">{c === null ? "" : String(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Drawer>
  );
}
