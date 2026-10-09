import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { money } from "../format";
import { useApp } from "../session";
import type { Build, Finding, Issue, Report, Run } from "../types";
import { Button, Card, DownloadButton, Empty, Loading, Money, More, Notice, Pill, when } from "../ui";

// ================================================================== step 4: process
export function ProcessStep({ run, build, onStarted }: { run: Run; build: Build | undefined; onStarted: () => void }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const running = build && (build.state === "QUEUED" || build.state === "RUNNING");
  const start = async () => {
    setBusy(true);
    try {
      await api.post(`/runs/${run.id}/process`);
      await qc.invalidateQueries({ queryKey: ["run", run.id] });
      onStarted();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  if (running && build) {
    return (
      <Card title="Processing your files…" sub="Please keep this page open or return later - processing continues on the server.">
        <ul className="stages">
          {build.stages.map((s) => (
            <li key={s.name} className={s.state.toLowerCase()}>
              <span className="st-name">{s.name}</span>
              <span className="st-state">{s.state === "DONE" ? "Complete" : s.state === "RUNNING" ? <><span className="spin" /> In progress</> : s.state === "FAILED" ? "Failed" : "Waiting"}</span>
            </li>
          ))}
        </ul>
      </Card>
    );
  }
  return (
    <>
      {build?.state === "FAILED" && (
        <Card title="Processing did not finish" tone="bad">
          <dl className="facts">
            <dt>What failed</dt><dd>{build.stages.find((s) => s.state === "FAILED")?.name ?? "Processing"} - {build.error}</dd>
            <dt>Reports produced</dt><dd>None. No report from this attempt can be downloaded.</dd>
            <dt>What to do</dt><dd>Process the files again. If it fails again, contact your administrator and mention run {run.id}.</dd>
          </dl>
          {build.error_detail && <More label="Technical details"><pre className="tech">{build.error_detail}</pre></More>}
        </Card>
      )}
      <Card title="Process the files" tone={run.can_process ? undefined : "warn"}>
        <p>{run.counts.ready} file{run.counts.ready === 1 ? "" : "s"} will be processed
          {run.counts.left_out > 0 && <> ({run.counts.left_out} not included)</>}.
          We extract every royalty entry, check every total, match the songs and prepare the three reports.</p>
        {run.blocked.length > 0 && <Notice tone="warn">{run.blocked.join(" ")}</Notice>}
        <div className="actions">
          <Button kind="primary" className="big" busy={busy} disabled={!run.can_process || !me.can.prepare} onClick={start}>Process Files</Button>
        </div>
      </Card>
    </>
  );
}

// ================================================================== step 5: review
function Summary({ build }: { build: Build }) {
  const s = build.summary;
  const left = build.left_out;
  return (
    <Card title="Processing summary" sub={`Version ${build.version} · ${build.state_text}`}>
      <div className="summary">
        <div><span>Client</span><b>{build.client.name}</b></div>
        <div><span>Files processed</span><b>{(s.statements ?? 0) + (s.platform_reports ?? 0)}</b></div>
        <div><span>Royalty records extracted</span><b>{(s.lines ?? 0).toLocaleString("en-IN")}</b></div>
        <div><span>Song rows in the master report</span><b>{(s.rows ?? 0).toLocaleString("en-IN")}</b></div>
        <div><span>Records matched to the song list</span><b>{(s.matched_rows ?? 0).toLocaleString("en-IN")}</b></div>
        <div><span>Items requiring review</span><b>{s.review_items ?? 0}</b></div>
        <div><span>Society royalty</span><b><Money v={s.royalty} /></b></div>
        {Object.entries(s.platform ?? {}).map(([k, v]) => <div key={k}><span>{k}</span><b><Money v={v} /></b></div>)}
      </div>
      <div className="recon">
        <b>Financial checks:</b> passed for {s.statements} statement{s.statements === 1 ? "" : "s"}
        {left.length > 0 && <> · {left.length} file{left.length === 1 ? "" : "s"} not included</>}.
        {Number(s.held_rows) > 0 && <> {s.held_rows} item{s.held_rows === 1 ? "" : "s"} of money wait for a decision
          (<Money v={s.held_platform} /> platform revenue{Number(s.held_royalty) ? <>, <Money v={s.held_royalty} /> royalty</> : null}) - they are counted in every total.</>}
      </div>
      {left.length > 0 && (
        <More label="Files not included">
          <ul className="plain small">{left.map((l) => <li key={l.file_id}><b>{l.label}</b> - {l.reason}</li>)}</ul>
        </More>
      )}
      <More label="Every check that ran">
        <ul className="checks">{build.checks.map((c, i) => <li key={i} className={c.ok ? "ok" : "bad"}>{c.ok ? "✓" : "✗"} {c.text}{c.detail && !c.ok ? ` - ${c.detail}` : ""}</li>)}</ul>
        {build.notices.length > 0 && <ul className="plain small">{build.notices.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      </More>
    </Card>
  );
}

export function ReviewStep({ run, build, onNext }: { run: Run; build: Build; onNext: () => void }) {
  const open = build.issues.filter((i) => i.severity !== "INFO");
  const money = open.filter((i) => i.category === "MONEY");
  const matching = open.filter((i) => i.kind === "PROPOSAL");
  const info = build.issues.filter((i) => i.severity === "INFO");
  const todo = (xs: Issue[]) => xs.filter((i) => !i.decision && !i.later).length;
  const sections = [
    money.length > 0 && { key: "money", title: "Money waiting for a decision", n: money.length, open: todo(money),
      text: "Money is kept and counted, but a person must say which song it belongs to." },
    matching.length > 0 && { key: "match", title: "Song identities to confirm", n: matching.length, open: todo(matching),
      text: "Paid songs whose title matches a song-list entry but whose codes differ." },
    build.findings > 0 && { key: "missing", title: "Paid songs not in the song list", n: build.summary.missing ?? 0,
      open: build.summary.unreviewed ?? 0, text: "Mark each one, for example 'Not ours' or 'Confirmed missing'." },
  ].filter(Boolean) as { key: string; title: string; n: number; open: number; text: string }[];
  const [tab, setTab] = useState<string | null>(null);
  const cur = tab ?? sections.find((s) => s.open > 0)?.key ?? sections[0]?.key;
  return (
    <>
      <Summary build={build} />
      <ChangesBanner run={run} build={build} />
      <h2 className="sec">Needs your review</h2>
      {sections.length === 0 ? <Card><Empty title="Nothing needs review">You can download the reports.</Empty></Card> : (
        <div className="tiles" role="tablist">
          {sections.map((s) => (
            <button key={s.key} role="tab" aria-selected={cur === s.key} className={`tile ${cur === s.key ? "on" : ""}`} onClick={() => setTab(s.key)}>
              <span className="tile-n">{s.open}</span>
              <span className="tile-t">{s.title}</span>
              <span className="tile-s">{s.open === 0 ? `All ${s.n} answered` : `${s.open} open of ${s.n}`}</span>
            </button>
          ))}
        </div>
      )}
      {cur === "money" && <Queue items={money} render={(i) => <IssueCard build={build} issue={i} />}
                                 intro={sections.find((s) => s.key === "money")!.text} />}
      {cur === "match" && <Queue items={matching} render={(i) => <MatchCard build={build} issue={i} />}
                                 intro={sections.find((s) => s.key === "match")!.text} />}
      {cur === "missing" && <Findings build={build} />}
      {info.length > 0 && (
        <More label={`${info.length} information item${info.length === 1 ? "" : "s"} (no action needed)`}>
          <ul className="plain small">{info.slice(0, 200).map((i) => <li key={i.no}><b>{i.title}</b> - {i.message}</li>)}</ul>
        </More>
      )}
      <div className="actions sticky"><Button kind="primary" onClick={onNext}>Continue to Download</Button></div>
    </>
  );
}

/** One item at a time: answer it, and the next open item appears. */
function Queue({ items, render, intro }: { items: Issue[]; render: (i: Issue) => React.ReactNode; intro: string }) {
  const [pos, setPos] = useState(0);
  const [list, setList] = useState(false);
  const openIdx = items.findIndex((i) => !i.decision && !i.later);
  const at = Math.min(pos, items.length - 1);
  const cur = items[at];
  const remaining = items.filter((i) => !i.decision && !i.later).length;
  if (list) {
    return (
      <Card title={`All ${items.length} items`} actions={<Button kind="ghost" onClick={() => setList(false)}>One at a time</Button>}>
        <ul className="list">
          {items.map((i, k) => (
            <li key={i.no} className="click" onClick={() => { setPos(k); setList(false); }}>
              <span>{i.title}</span>
              {i.decision ? <Pill tone={i.decision.state === "ACTIVE" ? "good" : "info"}>{i.decision.state === "ACTIVE" ? "Decided" : "Waiting for approval"}</Pill>
                : i.later ? <Pill tone="neutral">Later</Pill> : <Pill tone="warn">Open</Pill>}
            </li>
          ))}
        </ul>
      </Card>
    );
  }
  return (
    <>
      <div className="queue-bar">
        <span className="muted">{intro}</span>
        <span className="spacer" />
        <span><b>{at + 1}</b> of {items.length} · {remaining} open</span>
        <Button kind="ghost" disabled={at === 0} onClick={() => setPos(at - 1)}>Previous</Button>
        <Button kind="ghost" disabled={at >= items.length - 1} onClick={() => setPos(at + 1)}>Next</Button>
        {openIdx >= 0 && openIdx !== at && <Button kind="ghost" onClick={() => setPos(openIdx)}>Next open item</Button>}
        <Button kind="ghost" onClick={() => setList(true)}>See all</Button>
      </div>
      <QueueAdvance key={cur.no} issue={cur} onAnswered={() => {
        const nxt = items.findIndex((i, k) => k > at && !i.decision && !i.later);
        if (nxt >= 0) setPos(nxt);
      }}>{render(cur)}</QueueAdvance>
    </>
  );
}

function QueueAdvance({ issue, onAnswered, children }: { issue: Issue; onAnswered: () => void; children: React.ReactNode }) {
  const answered = !!issue.decision || issue.later;
  const [was] = useState(answered);
  useEffect(() => { if (answered && !was) { const t = window.setTimeout(onAnswered, 700); return () => window.clearTimeout(t); } },
    [answered]); // eslint-disable-line react-hooks/exhaustive-deps
  return <>{children}</>;
}

function ChangesBanner({ run, build }: { run: Run; build: Build }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const waiting = build.waiting_decisions.length;
  const changed = run.changed_since_build;
  if (!waiting && !changed) return null;
  return (
    <Notice tone="info">
      {waiting > 0 && <div>{waiting} change{waiting === 1 ? " is" : "s are"} waiting for an approver. The money only moves after approval.</div>}
      {changed && me.can.prepare && (
        <div className="row">
          <span>Answers or approved changes are not in these reports yet. Process again to include them.</span>
          <Button kind="primary" onClick={async () => {
            try { await api.post(`/runs/${run.id}/process`); qc.invalidateQueries({ queryKey: ["run", run.id] }); }
            catch (e) { toast((e as Error).message, true); }
          }}>Process again</Button>
        </div>
      )}
    </Notice>
  );
}

function useAct(build: Build) {
  const { toast } = useApp();
  const qc = useQueryClient();
  return async (issue: Issue, action: string, extra: Record<string, unknown> = {}) => {
    try {
      const r = await api.post<{ message: string }>(`/builds/${build.id}/issues/${issue.no}/act`, { action, ...extra });
      toast(r.message);
      qc.invalidateQueries({ queryKey: ["build", build.id] });
      qc.invalidateQueries({ queryKey: ["run", build.run_id] });
    } catch (e) { toast((e as Error).message, true); }
  };
}

function Decided({ issue }: { issue: Issue }) {
  if (issue.decision) {
    return <Pill tone={issue.decision.state === "ACTIVE" ? "good" : "info"}>
      {issue.decision.state === "ACTIVE" ? "Decided" : "Waiting for approval"}: {issue.decision.text}</Pill>;
  }
  if (issue.later) return <Pill tone="neutral">Saved for later</Pill>;
  return null;
}

function codes(isrcs: string[] = [], works: string[] = []) {
  return [...isrcs.map((i) => `ISRC ${i}`), ...works.map((w) => `Work ${w}`)].join(" · ") || "no code";
}

function IssueCard({ build, issue }: { build: Build; issue: Issue }) {
  const act = useAct(build);
  const { me } = useApp();
  const s = issue.subject;
  const [pick, setPick] = useState<string>("");
  return (
    <Card title={issue.title} tone={issue.severity === "BLOCKING" ? "bad" : "warn"} actions={<Decided issue={issue} />}>
      <p>{issue.message}</p>
      {issue.kind === "SHARED_RECORDING" && (
        <fieldset className="choices">
          <legend>Which song does this money belong to?</legend>
          {s.candidates.map((c: any) => (
            <label key={c.row_key} className="choice">
              <input type="radio" name={`pick${issue.no}`} value={c.row_key} checked={pick === c.row_key} onChange={() => setPick(c.row_key)} />
              <span><b>{c.title}</b> <span className="muted small">{codes(c.isrcs, c.work_nos)}</span></span>
            </label>
          ))}
        </fieldset>
      )}
      {me.can.prepare && !issue.decision && (
        <div className="actions">
          {issue.actions.includes("ASSIGN_HELD") && <Button kind="primary" disabled={!pick} onClick={() => act(issue, "ASSIGN_HELD", { row_key: pick })}>Place the money on this song</Button>}
          {issue.actions.includes("ADD_AS_SEPARATE") && <Button kind="primary" onClick={() => act(issue, "ADD_AS_SEPARATE")}>Add it - it is a separate payment</Button>}
          {issue.actions.includes("LEAVE_OUT") && <Button onClick={() => act(issue, "LEAVE_OUT")}>Leave it out</Button>}
          {issue.actions.includes("LATER") && !issue.later && <Button kind="ghost" onClick={() => act(issue, "LATER")}>Review later</Button>}
        </div>
      )}
      <More label="View source details"><pre className="tech">{JSON.stringify(s, null, 2)}</pre></More>
    </Card>
  );
}

function MatchCard({ build, issue }: { build: Build; issue: Issue }) {
  const act = useAct(build);
  const { me } = useApp();
  const s = issue.subject;
  const t = s.target;
  const plat = Object.values(s.platform ?? {}).reduce((a: number, v) => a + Number(v), 0);
  return (
    <Card title="Song identity needs confirmation" actions={<Decided issue={issue} />} className="match">
      <div className="compare">
        <div>
          <div className="cmp-h">Paid in this run</div>
          <div className="cmp-t">{s.title}</div>
          <div className="muted small">{codes(s.isrcs, s.work_nos)}</div>
          <div className="small">{Number(s.royalty) ? <>Royalty <Money v={s.royalty} /> · </> : null}{plat ? <>Platform revenue ₹{money(plat)}</> : null}</div>
        </div>
        <div>
          <div className="cmp-h">In the song list</div>
          <div className="cmp-t">{t.title}</div>
          <div className="muted small">{codes(t.isrcs, t.work_nos)}</div>
        </div>
      </div>
      <p className="why"><b>Why is this flagged?</b> {t.why}</p>
      {me.can.prepare && !issue.decision && (
        <div className="actions">
          <Button kind="primary" onClick={() => act(issue, "CONFIRM_MATCH")}>Confirm Match</Button>
          <Button onClick={() => act(issue, "KEEP_SEPARATE")}>Keep Separate</Button>
          {!issue.later && <Button kind="ghost" onClick={() => act(issue, "LATER")}>Review Later</Button>}
        </div>
      )}
    </Card>
  );
}

function Findings({ build }: { build: Build }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("NEW");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number[]>([]);
  const [status, setStatus] = useState("");
  const data = useQuery({
    queryKey: ["findings", build.id, filter, q],
    queryFn: () => api.get<{ items: Finding[]; counts: Record<string, number>; statuses: { value: string; label: string }[] }>(
      `/builds/${build.id}/findings${qs({ status: filter === "ALL" ? "" : filter, q })}`),
  });
  const counts = data.data?.counts ?? {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const save = async (nos: number[], st: string) => {
    try {
      const r = await api.post<{ message: string }>(`/builds/${build.id}/findings/status`, { findings: nos, status: st });
      toast(r.message);
      setSel([]);
      qc.invalidateQueries({ queryKey: ["findings", build.id] });
      qc.invalidateQueries({ queryKey: ["run", build.run_id] });
    } catch (e) { toast((e as Error).message, true); }
  };
  return (
    <Card sub="Money was paid on these songs, but their ISRC and work number are not in the client's song list. Mark each one. Songs marked 'Not ours' go to the out-of-scope report.">
      <More label="Prefer Excel?">
        <p className="small">Download the Missing Songs report, type a status in its <b>Status Given In Review</b> column
          (for example “Not SVF work”, “Need to register”, “already linked”), and upload the file in your next run.
          The statuses are applied by ISRC and work number, and your wording is kept.</p>
      </More>
      <div className="toolbar">
        <div className="seg" role="tablist">
          {[["NEW", "Not reviewed"], ["ALL", "All"], ["NOT_OURS", "Not ours"], ["CONFIRMED_MISSING", "Confirmed missing"],
            ["IDENTIFIER_TO_UPDATE", "Identifier to update"], ["ALREADY_IN_LIST", "Already in list"], ["NEEDS_CHECK", "Needs check"]].map(([k, l]) => (
            <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => { setFilter(k); setSel([]); }}>
              {l} <span className="count">{k === "ALL" ? total : counts[k] ?? 0}</span>
            </button>
          ))}
        </div>
        <input className="input" placeholder="Find a song, ISRC or work number" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {me.can.prepare && sel.length > 0 && (
        <div className="bulk">
          <span>{sel.length} selected</span>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status for selected songs">
            <option value="">Set status…</option>
            {data.data?.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <Button kind="primary" disabled={!status} onClick={() => save(sel, status)}>Apply</Button>
        </div>
      )}
      {data.isLoading ? <Loading /> : !data.data?.items.length ? <Empty title="No songs here" /> : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr>
              {me.can.prepare && <th><input type="checkbox" aria-label="Select all" checked={sel.length === data.data.items.length}
                onChange={(e) => setSel(e.target.checked ? data.data!.items.map((x) => x.no) : [])} /></th>}
              <th>Song</th><th>Codes</th><th className="num">Royalty</th><th className="num">Platform revenue</th><th>Possible match in the song list</th><th>Status</th>
            </tr></thead>
            <tbody>
              {data.data.items.map((f) => (
                <tr key={f.no}>
                  {me.can.prepare && <td><input type="checkbox" aria-label={`Select ${f.title}`} checked={sel.includes(f.no)}
                    onChange={(e) => setSel(e.target.checked ? [...sel, f.no] : sel.filter((x) => x !== f.no))} /></td>}
                  <td><b>{f.title}</b><div className="muted small">{f.sources}</div></td>
                  <td className="small mono">{[...f.isrcs, ...f.work_nos].join(" · ")}</td>
                  <td className="num"><Money v={f.royalty} /></td>
                  <td className="num"><Money v={f.platform} /></td>
                  <td className="small">{f.proposal ? <>{f.proposal.title} <span className="muted">({[...(f.proposal.isrcs ?? []).slice(0, 1), ...(f.proposal.work_nos ?? []).slice(0, 1)].join(" · ")})</span></> : <span className="muted">none</span>}</td>
                  <td>
                    {me.can.prepare ? (
                      <select className="input sm" value={f.status === "NEW" ? "" : f.status} aria-label={`Status of ${f.title}`}
                              onChange={(e) => e.target.value && save([f.no], e.target.value)}>
                        <option value="">Not reviewed</option>
                        {data.data!.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                      </select>
                    ) : f.status_text}
                    {f.status_original && f.status_original !== f.status_text && <div className="muted small">“{f.status_original}”</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ================================================================== step 6: download
const REPORT_INFO: Record<string, { title: string; text: string; button: string }> = {
  MASTER: { title: "Master Royalty Report", text: "The complete consolidated royalty workbook, in the SKV layout.", button: "Download Master Report" },
  MISSING: { title: "Missing Songs", text: "Songs that earned money but are not in the client's song list, with their review status.", button: "Download Missing Songs" },
  NON_CLIENT: { title: "Out-of-scope works", text: "Songs a reviewer marked as not belonging to the client.", button: "Download Out-of-scope Report" },
};

export function DownloadStep({ run, build, onReview }: { run: Run; build: Build; onReview: () => void }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const isFinal = build.state === "PUBLISHED" || build.state === "SUPERSEDED";
  const post = async (path: string, body?: unknown) => {
    setBusy(path);
    try {
      const r = await api.post<{ message: string }>(path, body);
      toast(r.message);
      qc.invalidateQueries({ queryKey: ["build", build.id] });
      qc.invalidateQueries({ queryKey: ["run", run.id] });
      qc.invalidateQueries({ queryKey: ["home"] });
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  const reports = [...build.reports].sort((a, b) => ["MASTER", "MISSING", "NON_CLIENT"].indexOf(a.kind) - ["MASTER", "MISSING", "NON_CLIENT"].indexOf(b.kind));
  const canDraft = me.can.draft_download || isFinal;
  return (
    <>
      <Card title={isFinal ? "Reports are published" : "Reports are ready"}
            sub={isFinal ? `${build.generation} · approved by ${build.approved_by} · ${when(build.published_at)}` : "Draft - validated, not yet approved."}
            tone={isFinal ? "good" : undefined}>
        {build.returned_reason && !isFinal && <Notice tone="warn">Returned by the approver: {build.returned_reason}</Notice>}
        <div className="reports">
          {reports.map((r, i) => <ReportCard key={r.id} n={i + 1} r={r} canDownload={canDraft} />)}
        </div>
        {reports.filter((r) => r.available).length > 1 && canDraft && (
          <div className="actions"><DownloadButton kind="secondary" path={`/builds/${build.id}/download-all`} onError={(m) => toast(m, true)}>Download All Reports (.zip)</DownloadButton></div>
        )}
      </Card>

      {!isFinal && (
        <Card title="Approval" sub={build.state_text}>
          {build.state === "CHECKED" && (
            <>
              <p>When the reports look right, send them to an approver. A different person must approve before they are published.</p>
              {build.blocking > 0 && <Notice tone="warn">{build.blocking} item{build.blocking === 1 ? " must" : "s must"} be resolved before sending for approval.</Notice>}
              {(build.summary.unreviewed ?? 0) > 0 && <Notice>{build.summary.unreviewed} missing songs are not reviewed yet. The out-of-scope report only contains songs reviewed so far.</Notice>}
              {run.changed_since_build && <ChangesBanner run={run} build={build} />}
              <div className="actions">
                <Button kind="primary" disabled={!build.can_submit || run.changed_since_build} busy={busy.endsWith("submit")}
                        onClick={() => post(`/builds/${build.id}/submit`)}>Send for Approval</Button>
                <Button kind="ghost" onClick={onReview}>Back to review</Button>
              </div>
            </>
          )}
          {build.state === "SUBMITTED" && (
            <>
              {build.publishing ? <p><span className="spin" /> Approved - preparing the final reports…</p> : (
                <>
                  <p>Sent by {build.submitted_by} on {when(build.submitted_at)}.</p>
                  {build.why_not_approve && <Notice>{build.why_not_approve}</Notice>}
                  {me.can.approve && build.can_approve && (
                    <>
                      <ul className="plain">
                        <li>Society royalty: <b><Money v={build.summary.royalty} /></b></li>
                        {Object.entries(build.summary.platform ?? {}).map(([k, v]) => <li key={k}>{k}: <b><Money v={v} /></b></li>)}
                        <li>All {build.checks.filter((c) => c.ok).length} financial checks passed.</li>
                        {build.left_out.length > 0 && <li>{build.left_out.length} file{build.left_out.length === 1 ? "" : "s"} not included (listed in the Run Summary sheet).</li>}
                        {build.waiting_decisions.length > 0 && <li>{build.waiting_decisions.length} proposed change(s) are not in this version.</li>}
                      </ul>
                      <div className="actions">
                        <Button kind="primary" busy={busy.endsWith("approve")} onClick={() => post(`/builds/${build.id}/approve`)}>Approve and Publish</Button>
                      </div>
                      <More label="Return with a note instead">
                        <div className="row">
                          <input className="input grow" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What needs to change?" />
                          <Button disabled={!note.trim()} onClick={() => post(`/builds/${build.id}/return`, { reason: note })}>Return</Button>
                        </div>
                      </More>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </Card>
      )}
    </>
  );
}

function ReportCard({ n, r, canDownload }: { n: number; r: Report; canDownload: boolean }) {
  const { toast } = useApp();
  const info = REPORT_INFO[r.kind];
  const tone = r.state.code === "PUBLISHED" ? "good" : r.state.code === "HELD" ? "warn" : "info";
  return (
    <div className={`report ${r.available ? "" : "off"}`}>
      <div className="report-n">{n}</div>
      <div className="report-b">
        <div className="report-t">{info.title} <Pill tone={tone}>{r.state.text}</Pill></div>
        <div className="muted">{info.text}</div>
        {r.available ? <div className="small muted">{r.filename}{r.rows != null ? ` · ${r.rows.toLocaleString("en-IN")} rows` : ""}</div>
          : <Notice tone="warn">{r.reason}</Notice>}
      </div>
      <div className="report-a">
        <DownloadButton path={`/reports/${r.id}/download`} disabled={!r.available || !canDownload} onError={(m) => toast(m, true)}>{info.button}</DownloadButton>
      </div>
    </div>
  );
}
