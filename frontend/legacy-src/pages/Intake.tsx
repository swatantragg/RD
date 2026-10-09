import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download, qs } from "../api";
import { useApp } from "../state";
import {
  Card, Checks, Drawer, Empty, ErrorNote, Field, Int, Kv, Money, PageHead, Pager, ReasonForm, Spinner, StateBadge, Tabs,
} from "../components/ui";
import { bytes, int, money, period, when, words } from "../format";

type FileRow = {
  id: number; filename: string; income_type: string | null; format: string; status: string; gate: string | null;
  hold_reason: string | null; meta: Record<string, string>; printed_total: string | null; lines_total: string | null;
  control_total: string | null; rows_total: number; rows_invalid: number; uploaded_at: string; batch: string;
  uploaded_by_name: string; bytes: number; supersedes_id: number | null;
};

const TYPES = ["PUBLISHING", "RECORDING", "USAGE", "IDENTITY", "OTHER"];
const TYPE_LABEL: Record<string, string> = {
  PUBLISHING: "Publishing record", RECORDING: "Recording record", USAGE: "Usage evidence", IDENTITY: "Catalogue / links", OTHER: "Other / unclear",
};

export default function Intake() {
  const { clientId, can } = useApp();
  const [sel, setSel] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const q = useQuery({ queryKey: ["files", clientId, status], queryFn: () => api.get<FileRow[]>(`/files${qs({ client_id: clientId, status })}`) });
  const counts = (q.data ?? []).reduce<Record<string, number>>((a, f) => ({ ...a, [f.status]: (a[f.status] ?? 0) + 1 }), {});
  return (
    <>
      <PageHead title="Intake & validation" step="A1–A5 · B1–B5">
        Every original is kept. A file's figures are used only once it is <b>validated</b>: classified by the right paid
        for, required fields confirmed, reconciled to its total, and overlaps decided. Blank money stays unknown.
      </PageHead>
      {can("upload") && <Upload />}
      <Card title="Files" sub="click a file to see its gates and act on holds" flush
            actions={
              <select className="input sm" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="status filter">
                <option value="">all statuses</option>
                {["VALIDATED", "CLASSIFICATION_HOLD", "FILE_EXCEPTION", "DATA_EXCEPTION", "RECONCILIATION_HOLD", "DUPLICATE_REVIEW",
                  "SUPERSEDED", "EXCLUDED"].map((s) => <option key={s} value={s}>{words(s)}{counts[s] ? ` (${counts[s]})` : ""}</option>)}
              </select>
            }>
        {q.isLoading ? <Spinner /> : q.error ? <ErrorNote error={q.error} /> : !q.data?.length ? <Empty>No files yet.</Empty> : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>#</th><th>File</th><th>Type</th><th>Status</th><th>Platform</th><th>Period</th>
                <th className="num">Lines total</th><th className="num">Printed / control</th><th className="num">Rows</th><th>Uploaded</th></tr></thead>
              <tbody>
                {q.data.map((f) => (
                  <tr key={f.id} className="click" onClick={() => setSel(f.id)}>
                    <td className="muted">{f.id}</td>
                    <td className="wrap"><b>{f.filename}</b><div className="muted small">{f.batch} · {bytes(f.bytes)}</div></td>
                    <td className="nowrap">{f.income_type ? TYPE_LABEL[f.income_type] : "—"}</td>
                    <td className="wrap"><StateBadge state={f.status} />{f.gate && <span className="muted small"> {f.gate}</span>}
                      {f.hold_reason && f.status !== "VALIDATED" && <div className="muted small">{f.hold_reason}</div>}</td>
                    <td>{f.meta.platform ?? "—"}</td>
                    <td className="nowrap">{f.meta.period_from ? period(f.meta.period_from, f.meta.period_to) : "—"}</td>
                    <td className="num">{f.income_type === "USAGE" ? int(f.lines_total) : <Money v={f.lines_total} />}</td>
                    <td className="num">{f.income_type === "USAGE" ? int(f.control_total) : <Money v={f.printed_total ?? f.control_total} />}</td>
                    <td className="num">{int(f.rows_total)}{f.rows_invalid ? <div className="small" style={{ color: "var(--warn-ink)" }}>{f.rows_invalid} invalid</div> : null}</td>
                    <td className="nowrap small">{when(f.uploaded_at)}<div className="muted">{f.uploaded_by_name}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {sel && <FileDrawer id={sel} onClose={() => setSel(null)} />}
    </>
  );
}

function Upload() {
  const { clientId, toast, meta } = useApp();
  const qc = useQueryClient();
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [batch, setBatch] = useState("");
  const [type, setType] = useState("");
  const [m, setM] = useState<Record<string, string>>({});
  const [result, setResult] = useState<any[] | null>(null);
  const up = useMutation({
    mutationFn: (files: File[]) => {
      const fd = new FormData();
      fd.append("client_id", String(clientId));
      if (batch) fd.append("batch", batch);
      if (type) fd.append("declared_type", type);
      Object.entries(m).forEach(([k, v]) => v && fd.append(k, v));
      files.forEach((f) => fd.append("files", f, f.name));
      return api.form<any[]>("/files", fd);
    },
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ["files"] }); qc.invalidateQueries({ queryKey: ["dash"] }); toast(`${r.length} file(s) received`); },
    onError: (e) => toast(String((e as Error).message), true),
  });
  const pick = (fl: FileList | null) => fl && fl.length && up.mutate(Array.from(fl));
  return (
    <Card title="A1 · Upload originals" sub="the type is read from the content; state only what the file does not" className="section">
      <div className="form-grid" style={{ marginBottom: 12 }}>
        <Field label="Batch ID"><input className="input" value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="auto: today's date" /></Field>
        <Field label="Income type"><select className="input" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">detect from content</option>{TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select></Field>
        <Field label="Platform (if not in file)"><select className="input" value={m.platform ?? ""} onChange={(e) => setM({ ...m, platform: e.target.value })}>
          <option value="" />{meta?.platforms.map((p) => <option key={p}>{p}</option>)}</select></Field>
        <Field label="Territory"><input className="input" value={m.territory ?? ""} onChange={(e) => setM({ ...m, territory: e.target.value })} placeholder="e.g. IN" /></Field>
        <Field label="Currency"><input className="input" value={m.currency ?? ""} onChange={(e) => setM({ ...m, currency: e.target.value })} placeholder="e.g. INR" /></Field>
        <Field label="Revenue basis"><select className="input" value={m.basis ?? ""} onChange={(e) => setM({ ...m, basis: e.target.value })}>
          <option value="" /><option>GROSS</option><option>NET</option></select></Field>
      </div>
      <div className={`drop ${over ? "over" : ""}`} onClick={() => ref.current?.click()}
           onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}>
        {up.isPending ? <><Spinner /> reading, classifying and validating…</> : <>Drop .xlsx / .csv files here, or click to choose</>}
        <input ref={ref} type="file" multiple accept=".xlsx,.csv" hidden onChange={(e) => pick(e.target.files)} />
      </div>
      {result && (
        <div className="col" style={{ marginTop: 10 }}>
          {result.map((r, i) => (
            <div key={i} className={`note ${r.repeat ? "warn" : r.status === "VALIDATED" ? "" : "warn"}`}>
              <b>{r.filename}</b> → {r.repeat ? r.message : <><StateBadge state={r.status} /> {r.hold_reason ?? ""}</>}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function FileDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { can, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["file", id], queryFn: () => api.get<any>(`/files/${id}`) });
  const [tab, setTab] = useState<"gates" | "rows">("gates");
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) => api.post<any>(`/files/${id}/${path}`, body),
    onSuccess: (f) => {
      qc.setQueryData(["file", id], f);
      qc.invalidateQueries({ queryKey: ["files"] });
      qc.invalidateQueries({ queryKey: ["dash"] });
      toast(`File #${id}: ${words(f.status)}`);
    },
    onError: (e) => toast((e as Error).message, true),
  });
  const f = q.data;
  return (
    <Drawer open onClose={onClose} wide title={f ? f.filename : "File"} sub={f && <>#{f.id} · {f.batch} · uploaded {when(f.uploaded_at)} by {f.uploaded_by_name} · sha256 <span className="mono">{f.sha256.slice(0, 16)}…</span></>}
            actions={f && <button className="btn sm" onClick={() => download(`/files/${id}/original`)}>Original</button>}>
      {!f ? <Spinner /> : (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <StateBadge state={f.status} />{f.gate && <span className="mono small">{f.gate}</span>}
            <span className="ink2">{f.hold_reason}</span>
          </div>
          <Tabs value={tab} onChange={setTab} items={[{ key: "gates", label: "Gates & actions" }, { key: "rows", label: "Source rows", count: f.rows_total }]} />
          {tab === "rows" ? <Rows id={id} type={f.income_type} /> : (
            <div className="col" style={{ gap: 16 }}>
              <div className="split">
                <Card title="What the file is">
                  <Kv items={[
                    ["Income type", f.income_type ? `${TYPE_LABEL[f.income_type]} (${f.classified_by})` : "—"],
                    ["Format", words(f.format)],
                    ...Object.entries(f.meta as Record<string, string>).map(([k, v]) => [words(k), <>{v}<span className="src">{f.meta_source[k]}</span></>] as [string, any]),
                    ["Rows", `${int(f.rows_total)} (${int(f.rows_invalid)} invalid)`],
                    ["Lines total", f.income_type === "USAGE" ? `${int(f.lines_total)} streams` : <Money v={f.lines_total} />],
                    ["Printed total", <Money v={f.printed_total} title="blank = no printed total" />],
                    ["Alternative control", f.control_total ? <>{f.income_type === "USAGE" ? int(f.control_total) : money(f.control_total)} <span className="muted small">{f.control_ref} · {f.control_by_name}</span></> : "—"],
                    ...(f.superseded_by ? [["Superseded by", `#${f.superseded_by.id} ${f.superseded_by.filename}`] as [string, string]] : []),
                    ...(f.supersedes_id ? [["Supersedes", `#${f.supersedes_id}`] as [string, string]] : []),
                  ]} />
                </Card>
                <Card title="Validation gates"><Checks items={f.checks} /></Card>
              </div>
              {f.months?.length ? (
                <Card title="By usage month" flush>
                  <table className="tbl"><thead><tr><th>Month</th><th className="num">Rows</th><th className="num">{f.income_type === "USAGE" ? "Streams" : "Amount"}</th></tr></thead>
                    <tbody>{f.months.map((m: any) => <tr key={m.month ?? "none"}><td>{m.month ? period(m.month, m.month).split(" – ")[0] : "no month"}</td><td className="num">{int(m.rows)}</td>
                      <td className="num">{f.income_type === "USAGE" ? int(m.total) : money(m.total)}</td></tr>)}</tbody></table>
                </Card>
              ) : null}
              <Actions f={f} busy={act.isPending} run={(path, body) => act.mutate({ path, body })} can={can} />
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}

function Actions({ f, run, busy, can }: { f: any; run: (p: string, b: unknown) => void; busy: boolean; can: (p: string) => boolean }) {
  const { meta } = useApp();
  const [type, setType] = useState(f.income_type ?? "PUBLISHING");
  const required: string[] = meta?.required_meta[f.income_type ?? "OTHER"] ?? [];
  const [m, setM] = useState<Record<string, string>>(() => Object.fromEntries(
    Array.from(new Set([...required, "sender", "payer", "use_type", "distribution_ref"])).map((k) => [k, f.meta[k] ?? ""])));
  const [ctl, setCtl] = useState({ total: "", reference: "" });
  const [bridge, setBridge] = useState<{ label: string; amount: string; evidence: string }[]>([]);
  const final = ["SUPERSEDED", "EXCLUDED"].includes(f.status);
  if (final) return <div className="note">This file no longer counts in any total: {f.hold_reason}</div>;
  return (
    <div className="col" style={{ gap: 16 }}>
      {can("upload") && (
        <Card title="A2 · Classification" sub="what right does this file pay for? (re-reads the original)">
          <div className="row wrap">
            <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select>
            <button className="btn" disabled={busy} onClick={() => run("classify", { income_type: type })}>Re-classify</button>
            <span className="muted small">A DSP can generate both rights - classify by the statement line, not the platform name.</span>
          </div>
        </Card>
      )}
      {can("upload") && f.income_type && f.income_type !== "OTHER" && (
        <Card title="B3 · Required fields" sub="state only what is evidenced; blank stays unknown">
          <div className="form-grid">
            {Object.keys(m).map((k) => (
              <Field key={k} label={words(k) + (required.includes(k) ? " *" : "")} hint={k === "share" ? "fraction, e.g. 1 = 100%" : k.startsWith("period") ? "YYYY-MM-DD" : undefined}>
                {k === "basis" ? (
                  <select className="input" value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })}><option value="" /><option>GROSS</option><option>NET</option></select>
                ) : k === "use_type" ? (
                  <select className="input" value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })}><option value="" />{meta?.use_types.map((u) => <option key={u} value={u}>{words(u)}</option>)}</select>
                ) : (
                  <input className="input" value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })} />
                )}
              </Field>
            ))}
          </div>
          <div className="row" style={{ marginTop: 10 }}><button className="btn primary" disabled={busy} onClick={() => run("meta", m)}>Save & re-check</button></div>
        </Card>
      )}
      {f.rows_invalid > 0 && (
        <Card title={`B3 · ${int(f.rows_invalid)} invalid row(s)`} sub="held out of every total; they stay listed">
          <table className="tbl" style={{ marginBottom: 10 }}><tbody>{f.invalid_reasons?.map((r: any) => <tr key={r.invalid_reason}><td>{r.invalid_reason}</td><td className="num">{int(r.n)}</td></tr>)}</tbody></table>
          {can("intake_review") && !(f.decisions?.rows_accepted?.count === f.rows_invalid) && (
            <ReasonForm label="Why can these rows be excluded?" button="Accept exclusion" busy={busy} onSubmit={(t) => run("accept-rows", { note: t })} />
          )}
          {f.decisions?.rows_accepted && <div className="muted small">Accepted by {f.decisions.rows_accepted.by}: {f.decisions.rows_accepted.note}</div>}
        </Card>
      )}
      {can("intake_review") && ["PUBLISHING", "RECORDING", "USAGE"].includes(f.income_type) && (
        <Card title="B4 · Reconciliation control" sub={f.printed_total ? "printed total found - add an evidenced bridge only if lines differ" : "no printed total: an approved alternative control is required (not by the uploader)"}>
          <div className="form-grid">
            {!f.printed_total && <Field label={f.income_type === "USAGE" ? "Control total (streams)" : "Control total"}><input className="input" value={ctl.total} onChange={(e) => setCtl({ ...ctl, total: e.target.value })} /></Field>}
            <Field label="Evidence reference"><input className="input" value={ctl.reference} onChange={(e) => setCtl({ ...ctl, reference: e.target.value })} placeholder="supplier confirmation / portal total" /></Field>
          </div>
          {bridge.map((b, i) => (
            <div key={i} className="form-grid" style={{ marginTop: 8 }}>
              {(["label", "amount", "evidence"] as const).map((k) => (
                <Field key={k} label={`Bridge ${k}`}><input className="input" value={b[k]} onChange={(e) => setBridge(bridge.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x))} /></Field>
              ))}
            </div>
          ))}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn sm" onClick={() => setBridge([...bridge, { label: "", amount: "", evidence: "" }])}>+ bridge item (fee, tax, rounding…)</button>
            <span className="spacer" />
            <button className="btn primary" disabled={busy || (!f.printed_total && !ctl.total)} onClick={() => run("control", { control_total: ctl.total, reference: ctl.reference, bridge })}>Approve control</button>
          </div>
        </Card>
      )}
      {(f.overlaps?.length > 0 || f.row_counts?.duplicate_candidates > 0) && can("intake_review") && (
        <Card title="B5 · Overlaps and copied rows" sub="retain legitimate repeated earnings; suppress only an evidenced duplicate">
          {f.overlaps.map((o: any) => (
            <div key={o.file_id} className="note warn" style={{ marginBottom: 10 }}>
              Overlaps file #{o.file_id} <b>{o.filename}</b> ({words(o.status)}) · {int(o.shared_rows)} identical rows ({Math.round(o.share * 100)}%) · period overlap {o.period_overlap ? "yes" : "no"}
              {f.decisions?.overlaps?.[o.file_id] ? <div className="small">Decided: {words(f.decisions.overlaps[o.file_id].decision)} by {f.decisions.overlaps[o.file_id].by}</div> : (
                <OverlapForm busy={busy} onSubmit={(decision, note) => run("overlap", { other_id: o.file_id, decision, note })} />
              )}
            </div>
          ))}
          {f.row_counts?.duplicate_candidates > 0 && (
            <div className="col">
              <div>{int(f.row_counts.duplicate_candidates)} identical row(s) in this file (see Source rows › duplicates).</div>
              <DupForm busy={busy} onSubmit={(decision, note) => run("row-duplicates", { decision, note })} />
            </div>
          )}
        </Card>
      )}
      {can("intake_review") && (
        <details><summary className="muted small" style={{ cursor: "pointer" }}>Exclude this file…</summary>
          <ReasonForm label="Reason (kept on record)" button="Exclude file" danger busy={busy} onSubmit={(t) => run("exclude", { note: t })} />
        </details>
      )}
    </div>
  );
}

function OverlapForm({ onSubmit, busy }: { onSubmit: (d: string, n: string) => void; busy: boolean }) {
  const [d, setD] = useState("SUPERSEDES");
  return (
    <ReasonForm label="Evidence for the decision" button="Record decision" busy={busy} onSubmit={(t) => onSubmit(d, t)}
      extra={<select className="input" value={d} onChange={(e) => setD(e.target.value)}>
        <option value="SUPERSEDES">This file corrects the other (supersede - old totals stop counting)</option>
        <option value="SEPARATE">Both are separate legitimate reports</option></select>} />
  );
}

function DupForm({ onSubmit, busy }: { onSubmit: (d: string, n: string) => void; busy: boolean }) {
  const [d, setD] = useState("RETAIN");
  return (
    <ReasonForm label="Evidence for the decision" button="Record decision" busy={busy} onSubmit={(t) => onSubmit(d, t)}
      extra={<select className="input" value={d} onChange={(e) => setD(e.target.value)}>
        <option value="RETAIN">Retain - legitimate repeated earnings</option>
        <option value="SUPPRESS">Suppress copies - evidenced duplicate (first row kept)</option></select>} />
  );
}

function Rows({ id, type }: { id: number; type: string }) {
  const [only, setOnly] = useState("all");
  const [offset, setOffset] = useState(0);
  const q = useQuery({ queryKey: ["rows", id, only, offset], queryFn: () => api.get<any>(`/files/${id}/rows${qs({ only, offset, limit: 100 })}`) });
  const cols: Record<string, string[]> = {
    PUBLISHING: ["row_no", "work_code", "title", "party", "role", "pool", "source", "platform", "right_scope", "amount"],
    RECORDING: ["row_no", "month", "isrc", "title", "album", "platform", "territory", "currency", "amount", "duplicate_state"],
    USAGE: ["row_no", "month", "isrc", "title", "album", "platform", "streams", "duplicate_state"],
    IDENTITY: ["row_no", "title", "work_codes", "isrcs", "film", "note"],
  };
  const c = cols[type] ?? ["row_no"];
  return (
    <>
      <div className="row" style={{ marginBottom: 8 }}>
        <select className="input sm" value={only} onChange={(e) => { setOnly(e.target.value); setOffset(0); }}>
          <option value="all">all rows</option><option value="invalid">invalid only</option><option value="duplicates">duplicate decisions</option></select>
        <span className="muted small">Sheet row numbers refer to the original file.</span>
      </div>
      {q.isLoading ? <Spinner /> : (
        <div className="tbl-wrap card">
          <table className="tbl">
            <thead><tr>{c.map((k) => <th key={k} className={["amount", "streams"].includes(k) ? "num" : ""}>{words(k)}</th>)}<th>valid</th></tr></thead>
            <tbody>{q.data.rows.map((r: any) => (
              <tr key={r.id}>{c.map((k) => <td key={k} className={["amount", "streams"].includes(k) ? "num" : ""}>
                {k === "amount" ? <Money v={r[k]} /> : k === "streams" ? <Int v={r[k]} /> : Array.isArray(r[k]) ? r[k].join(", ") : k === "month" ? (r[k] ?? "").slice(0, 7) : String(r[k] ?? "")}</td>)}
                <td>{r.is_valid ? "✓" : <span style={{ color: "var(--crit-ink)" }}>{r.invalid_reason}</span>}</td></tr>
            ))}</tbody>
          </table>
          <Pager total={q.data.total} offset={offset} limit={100} onChange={setOffset} />
        </div>
      )}
    </>
  );
}
