import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { local, useApp } from "../session";
import type { Build, FileOut, Run } from "../types";
import { DeleteRunDialog } from "../DeleteRun";
import { Button, Card, FileStatus, Loading, Money, More, Notice, Page, Select, Steps } from "../ui";
import { ProcessStep, ReviewStep, DownloadStep } from "./Results";

export const STEPS = ["Select client", "Upload files", "Check files", "Process data", "Review results", "Download reports"];

export default function Process({ runId }: { runId?: number }) {
  if (!runId) return <SelectClient />;
  return <RunWizard runId={runId} />;
}

// ================================================================== step 1
function SelectClient() {
  const { me, go, toast } = useApp();
  const remembered = Number(local.get("client")) || undefined;
  const [cid, setCid] = useState<number | undefined>(
    me.clients.length === 1 ? me.clients[0].id : me.clients.find((c) => c.id === remembered)?.id);
  const [find, setFind] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const shown = me.clients.filter((c) => !find || `${c.code} ${c.name}`.toLowerCase().includes(find.toLowerCase()));
  if (!me.can.prepare) {
    return <Page title="Process Files"><Notice>Your role can view and download reports, but not prepare them.
      Open <a href="#/reports">Past Reports</a> to find published reports.</Notice></Page>;
  }
  return (
    <Page title="New processing run">
      <Steps steps={STEPS} current={0} done={() => false} />
      <Card title="Who are you processing reports for?">
        {me.clients.length === 0 ? (
          <Notice tone="warn">You do not have access to any client yet.
            {me.can.clients ? <> <Button kind="ghost" onClick={() => go("clients/new")}>Add a client</Button></> : " Ask your administrator to give you access."}</Notice>
        ) : (
          <form className="form" onSubmit={async (e) => {
            e.preventDefault();
            if (!cid) return;
            setBusy(true);
            try {
              local.set("client", String(cid));
              const r = await api.post<Run>("/runs", { client_id: cid, title });
              go(`process/${r.id}`);
            } catch (x) {
              toast((x as Error).message, true);
            } finally { setBusy(false); }
          }}>
            {me.clients.length > 6 && (
              <label className="field">Find a client
                <input className="input" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Type a name or code" />
              </label>
            )}
            <label className="field">Client
              <Select value={cid ? String(cid) : ""} required placeholder="Choose a client…"
                      onChange={(v) => setCid(Number(v) || undefined)}
                      options={shown.map((c) => ({ value: String(c.id), label: c.name, meta: c.code }))} />
            </label>
            <More label="Name this run (optional)">
              <label className="field">Run name
                <input className="input" value={title} onChange={(e) => setTitle(e.target.value)}
                       placeholder="For example: October statements" />
              </label>
            </More>
            <div className="actions">
              <Button kind="primary" type="submit" busy={busy} disabled={!cid}>Continue</Button>
              {me.can.clients && <Button kind="ghost" type="button" onClick={() => go("clients/new")}>Add a new client</Button>}
            </div>
          </form>
        )}
      </Card>
    </Page>
  );
}

// ================================================================== the run
function naturalStep(run: Run, build: Build | undefined): number {
  if (run.files.length === 0) return 1;
  if (!run.latest_build) return 2;
  if (build && (build.state === "QUEUED" || build.state === "RUNNING" || build.state === "FAILED")) return 3;
  if (build && build.state === "CHECKED" && build.issues.some((i) => !i.later && !i.decision && i.severity !== "INFO"))
    return 4;
  return 5;
}

function RunWizard({ runId }: { runId: number }) {
  const { me, go } = useApp();
  const readOnly = !me.can.prepare;
  const [view, setView] = useState<number | null>(null);
  const run = useQuery({
    queryKey: ["run", runId], queryFn: () => api.get<Run>(`/runs/${runId}`),
    refetchInterval: (q) => (q.state.data?.state.code === "PROCESSING" ? 2000 : false),
  });
  const bid = run.data?.latest_build;
  const build = useQuery({
    queryKey: ["build", bid], queryFn: () => api.get<Build>(`/builds/${bid}`), enabled: !!bid,
    refetchInterval: (q) => {
      const b = q.state.data;
      return b && (b.state === "QUEUED" || b.state === "RUNNING" || b.publishing) ? 1500 : false;
    },
  });
  const qc = useQueryClient();
  const prevBuild = useRef<number | null | undefined>(bid);
  useEffect(() => {
    if (prevBuild.current !== undefined && prevBuild.current !== bid) setView(null);   // a new processing started
    prevBuild.current = bid;
  }, [bid]);
  const prevState = useRef<string | undefined>();
  useEffect(() => {
    const s = build.data?.state;
    if (prevState.current && prevState.current !== s) {
      qc.invalidateQueries({ queryKey: ["run", runId] });
      setView(null);
    }
    prevState.current = s;
  }, [build.data?.state, qc, runId]);
  if (run.isLoading) return <Loading />;
  if (run.isError || !run.data) return (
    <Page title="Process Files">
      <Notice tone="bad">{(run.error as Error)?.message ?? "Not found"}</Notice>
      {me.can.prepare && <div className="actions"><Button kind="primary" onClick={() => go("process")}>Start a new run</Button></div>}
    </Page>
  );
  const r = run.data;
  const b = bid ? build.data : undefined;
  const natural = naturalStep(r, b);
  const step = view ?? natural;
  const done = (i: number) => i < natural || (i === 5 && natural === 5);
  return (
    <Page title={r.title} intro={<>{r.client.name} · started by {r.created_by}{r.closed ? " · closed" : ""}</>}
          actions={<>
            <Button kind="ghost" onClick={() => setView(null)} disabled={view === null}>Go to current step</Button>
            {!r.closed && <CloseRun runId={r.id} />}
            {r.can_delete && <DeleteRun run={r} />}
          </>}>
      <Steps steps={STEPS} current={step} done={done} onPick={(i) => setView(i === natural ? null : i)} />
      {readOnly && <Notice>You are following this run, prepared by {r.created_by}. You can download the reports once
        they are published.</Notice>}
      {readOnly && step <= 2 && <Card title={`Files (${r.files.length})`}>{r.files.length ? <FileList run={r} /> : <p className="muted">No files yet.</p>}</Card>}
      {!readOnly && step <= 1 && <UploadStep run={r} onNext={() => setView(2)} onBusy={() => setView(1)} />}
      {!readOnly && step === 2 && <CheckStep run={r} onNext={() => setView(3)} onBack={() => setView(1)} />}
      {step === 3 && <ProcessStep run={r} build={b} onStarted={() => setView(null)} />}
      {step === 4 && b && <ReviewStep run={r} build={b} onNext={() => setView(5)} />}
      {step === 5 && b && <DownloadStep run={r} build={b} onReview={() => setView(4)} />}
      {(step === 4 || step === 5) && !b && <Loading />}
    </Page>
  );
}

function CloseRun({ runId }: { runId: number }) {
  const { me, go, toast } = useApp();
  if (!me.can.prepare) return null;
  return (
    <Button kind="ghost" title="Remove this run from your lists. Its files and reports are kept." onClick={async () => {
      try { await api.post(`/runs/${runId}/close`); toast("Run closed. Its files and reports are kept."); go(""); }
      catch (e) { toast((e as Error).message, true); }
    }}>Close this run</Button>
  );
}

function DeleteRun({ run }: { run: Run }) {
  const { go } = useApp();
  const [ask, setAsk] = useState(false);
  return (
    <>
      <Button kind="danger" onClick={() => setAsk(true)}>Delete run</Button>
      {ask && <DeleteRunDialog runId={run.id} title={run.title} onClose={() => setAsk(false)} onDone={() => go("process")}
                               drafts={run.builds.filter((b) => b.state === "CHECKED").length} />}
    </>
  );
}

// ================================================================== step 2: upload
function UploadStep({ run, onNext, onBusy }: { run: Run; onNext: () => void; onBusy: () => void }) {
  const qc = useQueryClient();
  const [over, setOver] = useState(false);
  const [queue, setQueue] = useState<{ name: string; state: "waiting" | "uploading" | "done" | "error"; msg?: string }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const busy = queue.some((q) => q.state === "uploading" || q.state === "waiting");

  async function send(files: File[]) {
    if (!files.length) return;
    onBusy();                                       // stay on this step until the person chooses to continue
    setQueue((q) => [...q, ...files.map((f) => ({ name: f.name, state: "waiting" as const }))]);
    for (const f of files) {
      setQueue((q) => q.map((x) => (x.name === f.name ? { ...x, state: "uploading" } : x)));
      const fd = new FormData();
      fd.append("files", f, f.name);
      try {
        const [res] = await api.form<{ file?: FileOut; note?: string | null; error?: string }[]>(`/runs/${run.id}/files`, fd);
        setQueue((q) => q.map((x) => (x.name === f.name ? { ...x, state: res.error ? "error" : "done", msg: res.error ?? res.note ?? undefined } : x)));
      } catch (e) {
        setQueue((q) => q.map((x) => (x.name === f.name ? { ...x, state: "error", msg: (e as Error).message } : x)));
      }
      qc.invalidateQueries({ queryKey: ["run", run.id] });
    }
  }
  return (
    <>
      <Card title="Upload your files">
        <div className={`drop ${over ? "over" : ""}`} role="button" tabIndex={0}
             onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)); }}>
          <div className="drop-t">Drag files here or select them from your computer</div>
          <div className="muted small">Supported: Excel (.xlsx) and CSV files</div>
          <Button kind="primary" type="button" onClick={(e) => { e.stopPropagation(); input.current?.click(); }}>Choose Files</Button>
          <input ref={input} type="file" multiple accept=".xlsx,.csv" hidden
                 onChange={(e) => { send(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        </div>
        {queue.length > 0 && (
          <ul className="queue">
            {queue.map((q, i) => (
              <li key={i} className={q.state}>
                <span>{q.name}</span>
                <span className="muted small">{q.state === "waiting" ? "Waiting…" : q.state === "uploading" ? "Reading and checking…" : q.state === "error" ? q.msg : q.msg ?? "Added"}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {run.files.length > 0 && (
        <Card title={`Uploaded files (${run.files.length})`}>
          <FileList run={run} compact />
        </Card>
      )}
      <div className="actions sticky">
        <Button kind="primary" disabled={run.files.length === 0 || busy} onClick={onNext}>Check Files</Button>
        {run.files.length === 0 && <span className="muted">Upload at least one file to continue.</span>}
      </div>
    </>
  );
}

function FileList({ run, compact }: { run: Run; compact?: boolean }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  return (
    <ul className="files">
      {run.files.map((f) => (
        <li key={f.id} className={`file ${f.status}`}>
          <div className="file-main">
            <div className="file-name" title={f.filename}>{f.filename}</div>
            <div className="file-kind">{f.label ?? f.kind_label}</div>
            {!compact && f.summary.total && <div className="muted small">Total in file: <Money v={f.summary.total} /></div>}
          </div>
          <FileStatus status={f.status} text={f.status_text} />
          {me.can.prepare && (
            <Button kind="ghost" className="sm" title="Remove from this run" onClick={async () => {
              try {
                await api.del(`/runs/${run.id}/files/${f.id}`);
                qc.invalidateQueries({ queryKey: ["run", run.id] });
              } catch (e) { toast((e as Error).message, true); }
            }}>Remove</Button>
          )}
          {(f.problems.some((p) => p.severity !== "INFO") || !compact) && f.problems.length > 0 && (
            <div className="file-msgs">
              {f.problems.filter((p) => compact ? p.severity !== "INFO" : true).slice(0, compact ? 1 : 6).map((p, i) => (
                <div key={i} className={`msg ${p.severity}`}>{p.message}</div>
              ))}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

// ================================================================== step 3: check
function CheckStep({ run, onNext, onBack }: { run: Run; onNext: () => void; onBack: () => void }) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const c = run.counts;
  const attention = run.files.filter((f) => f.status === "NEEDS_REVIEW" || f.status === "ERROR" || f.status === "UNSUPPORTED");
  const notIncluded = run.files.filter((f) => f.status === "LEFT_OUT");
  const ready = run.files.filter((f) => f.status === "READY");
  async function choose(fileId: number, choice: string) {
    try {
      await api.post(`/runs/${run.id}/files/${fileId}/choice`, { choice });
      qc.invalidateQueries({ queryKey: ["run", run.id] });
    } catch (e) { toast((e as Error).message, true); }
  }
  return (
    <>
      <Card title={run.can_process ? "Your files are ready to process." : "Your files need attention before processing."}
            tone={run.can_process ? "good" : "warn"}>
        <div className="tally">
          <div><b>{c.total}</b> file{c.total === 1 ? "" : "s"} uploaded</div>
          <div><b>{c.ready}</b> ready</div>
          {c.needs_review > 0 && <div className="warn-t"><b>{c.needs_review}</b> need your answer</div>}
          {c.error > 0 && <div className="bad-t"><b>{c.error}</b> cannot be used</div>}
          {c.left_out > 0 && <div><b>{c.left_out}</b> not included</div>}
        </div>
        {run.blocked.length > 0 && <ul className="blocked">{run.blocked.map((b, i) => <li key={i}>{b}</li>)}</ul>}
      </Card>

      {run.issues.map((i, n) => (
        <Card key={n} title={i.title} tone={i.blocking ? "warn" : "info"}>
          <p>{i.message}</p>
          <div className="actions">
            {i.actions.map((a, k) => (
              <Button key={k} kind={k === 0 ? "primary" : "secondary"} onClick={() => choose(a.file_id, a.action)}>{a.label}</Button>
            ))}
          </div>
        </Card>
      ))}

      {attention.map((f) => <FileQuestions key={f.id} run={run} file={f} />)}

      {notIncluded.length > 0 && (
        <Card title="Not included" sub="These files are kept, but their money is not added to this client's reports.">
          <ul className="plain">
            {notIncluded.map((f) => (
              <li key={f.id}><b>{f.filename}</b> - {f.problems[0]?.message}
                {f.choice?.relation === "LEAVE_OUT" && <Button kind="ghost" className="sm" onClick={() => choose(f.id, "USE")}>Use it after all</Button>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title={`Ready (${ready.length})`}>
        {ready.length === 0 ? <p className="muted">No file is ready yet.</p> : ready.length <= 4 ? <FileList run={{ ...run, files: ready }} /> : (
          <>
            <p className="muted">{ready.map((f) => f.label ?? f.kind_label).slice(0, 3).join(" · ")} and {ready.length - 3} more.</p>
            <More label={`Show the ${ready.length} ready files`}><FileList run={{ ...run, files: ready }} /></More>
          </>
        )}
      </Card>

      <div className="actions sticky">
        <Button onClick={onBack}>Add more files</Button>
        <Button kind="primary" disabled={!run.can_process} onClick={onNext}>Continue to Processing</Button>
        {!run.can_process && <span className="muted">{run.blocked[0]}</span>}
      </div>
    </>
  );
}

function FileQuestions({ run, file }: { run: Run; file: FileOut }) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const questions = file.questions;
  const errors = file.problems.filter((p) => p.severity === "ERROR");
  return (
    <Card title={file.filename} sub={file.label ?? file.kind_label} tone={errors.length ? "bad" : "warn"}
          actions={<FileStatus status={file.status} text={file.status_text} />}>
      {errors.map((p, i) => <Notice key={i} tone="bad">{p.message}</Notice>)}
      {errors.length > 0 && <p className="muted small">Fix the file and upload it again, or remove it from this run.</p>}
      {questions.length > 0 && (
        <form className="form" onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api.post(`/runs/${run.id}/files/${file.id}/answer`, { answers });
            qc.invalidateQueries({ queryKey: ["run", run.id] });
            toast("Saved.");
          } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
        }}>
          {questions.map((q) => (
            <label key={q.field} className="field">{q.message}{!q.required && <span className="muted"> (optional)</span>}
              {q.options.length > 0 ? (
                <Select value={answers[q.field] ?? ""} required={q.required} options={q.options}
                        onChange={(v) => setAnswers({ ...answers, [q.field]: v })} />
              ) : q.field === "period" ? (
                <PeriodInput onChange={(v) => setAnswers({ ...answers, period: v })} />
              ) : (
                <input className="input" value={answers[q.field] ?? ""} required={q.required}
                       onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })} />
              )}
            </label>
          ))}
          <div className="actions"><Button kind="primary" type="submit" busy={busy}>Save</Button></div>
        </form>
      )}
      {file.problems.some((p) => p.detail) && (
        <More><ul className="plain small">{file.problems.filter((p) => p.detail).map((p, i) => <li key={i}><code>{p.code}</code> {p.detail}</li>)}</ul></More>
      )}
    </Card>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function PeriodInput({ onChange }: { onChange: (v: string) => void }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const fmt = (v: string) => (v ? `${MONTHS[Number(v.slice(5, 7)) - 1]} ${v.slice(0, 4)}` : "");
  useEffect(() => { if (a && b) onChange(`${fmt(a)} - ${fmt(b)}`); }, [a, b]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <span className="row">
      <input className="input" type="month" aria-label="From" value={a} onChange={(e) => setA(e.target.value)} />
      <span className="muted">to</span>
      <input className="input" type="month" aria-label="To" value={b} onChange={(e) => setB(e.target.value)} />
    </span>
  );
}

