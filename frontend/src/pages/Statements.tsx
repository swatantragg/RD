import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { int, mon } from "../format";
import { useApp } from "../session";
import { ClearDialog } from "../ClearData";
import { Amount, ClientSelect, DropZone, Facts, MappingPill, NeedClient, Pager, ResetFilters, changed, PeriodPicker, Selection, STATEMENT_TONE, monthEnd, monthStart, period } from "../parts";
import { Button, Card, Dialog, DownloadButton, Empty, Loading, Money, More, Notice, Page, Pill, ScrollX, Select, day, when } from "../ui";

type St = { id: number; file_id: number; filename: string; source: string; source_label: string; side_label: string; record_type: string; type_label: string;
  category: string | null; platform_id: number | null; platform: string | null; reported_platform: string | null; distributor: string | null;
  reference: string | null; period_start: string | null; period_end: string | null; statement_date: string | null;
  statement_date_estimated: boolean; payment_date: string | null; currency: string | null; basis: string | null; territory: string | null;
  records: number | null; total: string | null; status: string; status_text: string; reason: string | null; relation: string | null;
  related_statement_id: number | null; superseded_by: number | null; uploaded_at: string; uploaded_by: string | null; usage: string | null };
type List = { rows: St[]; total: number; offset: number; counts: Record<string, number>; platforms: { id: number; platform_name: string }[];
  statuses: { value: string; label: string }[]; types: { value: string; label: string }[]; sources: { value: string; label: string }[];
  sides: Record<string, number> };

/** The kind of a statement: a platform report or an IPRS statement (its tab). */
export function SidePill({ source, label }: { source: string; label: string }) {
  return <Pill tone={source === "IPRS" ? "good" : source === "PLATFORM" ? "neutral" : "info"}>{label}</Pill>;
}

/** Two tabs: the platform's reports, and the IPRS statements (received from IPRS or forwarded by the client - the
 *  client's statements had a tab of their own until 1.6.0; '#/statements/client' opens the IPRS tab). */
export const STATEMENT_TABS = [
  { key: "platform", source: "PLATFORM", label: "Platform reports", one: "platform report", many: "platform reports", title: "Upload platform reports (revenue and usage)",
    drop: "Drag the platform's revenue and usage reports here", empty: "Upload the platform's revenue report and its usage report above." },
  { key: "iprs", source: "IPRS", label: "IPRS statements", one: "IPRS statement", many: "IPRS statements", title: "Upload IPRS statements (from IPRS or forwarded by the client)",
    drop: "Drag the IPRS statements here - all platforms at once", empty: "Upload the IPRS statements above - the ones received from IPRS and the ones the client forwards." },
] as const;

export default function Statements({ id, tab }: { id?: number; tab?: string }) {
  const t = tab === "client" ? "iprs" : tab;
  return <NeedClient>{(cid) => (id ? <StatementPage id={id} /> : <Library key={t ?? "platform"} cid={cid} tab={t} />)}</NeedClient>;
}

const LIB_FILTERS = { platform_id: "", status: "", q: "" };
type Batch = { id: number; batch_no: number | null; label: string; platforms: string[]; period_label: string; no_period: number; files: number; matching: number;
  statuses: Record<string, number>; lines: number | null; total: string | null; usage: string | null; types: string[]; uploaded_at: string; uploaded_by: string | null };
const newKey = () => (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`);

function Library({ cid, tab }: { cid: number; tab?: string }) {
  const { me, go } = useApp();
  const qc = useQueryClient();
  const t = STATEMENT_TABS.find((x) => x.key === tab) ?? STATEMENT_TABS[0];
  const [f, setF] = useState(LIB_FILTERS);
  const [offset, setOffset] = useState(0);
  const [queue, setQueue] = useState<{ name: string; state: string; msg?: string; st?: St }[]>([]);
  const [lastBatch, setLastBatch] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);
  const [openBatch, setOpenBatch] = useState<number | null>(null);
  const list = useQuery({ queryKey: ["statements", cid, t.source, "facets"], queryFn: () => api.get<List>(`/statements${qs({ client_id: cid, source: t.source, offset: 1000000 })}`) });
  const bl = useQuery({ queryKey: ["statements", cid, t.source, "batches", f, offset], placeholderData: (x) => x,
    queryFn: () => api.get<{ rows: Batch[]; total: number; files: number }>(`/statement-batches${qs({ client_id: cid, source: t.source, ...f, offset })}`) });
  const send = async (files: File[]) => {
    const key = newKey();                                  // the files dropped together form one batch
    setQueue(files.map((x) => ({ name: x.name, state: "waiting" })));
    setLastBatch(null);
    for (const file of files) {
      setQueue((q) => q.map((x) => (x.name === file.name ? { ...x, state: "uploading" } : x)));
      const fd = new FormData();
      fd.append("client_id", String(cid));
      fd.append("source", t.source);
      fd.append("batch_key", key);
      fd.append("files", file, file.name);
      try {
        const [r] = await api.form<{ statement?: St; note?: string; error?: string; enquiries_flagged?: number; batch_no?: number | null }[]>("/statements", fd);
        if (r.batch_no) setLastBatch(r.batch_no);
        const msg = r.error ?? [r.note, r.enquiries_flagged ? `${r.enquiries_flagged} open enquir${r.enquiries_flagged === 1 ? "y" : "ies"} flagged for review` : ""].filter(Boolean).join(" ");
        setQueue((q) => q.map((x) => (x.name === file.name ? { ...x, state: r.error ? "error" : "done", msg, st: r.statement } : x)));
      } catch (e) {
        setQueue((q) => q.map((x) => (x.name === file.name ? { ...x, state: "error", msg: (e as Error).message } : x)));
      }
      qc.invalidateQueries({ queryKey: ["statements", cid] });
      qc.invalidateQueries({ queryKey: ["platform-data", cid] });
    }
  };
  const d = list.data;
  const b = bl.data;
  const sides = d?.sides ?? {};
  const set = (k: string, v: string) => { setF({ ...f, [k]: v }); setOffset(0); };
  const isrc = t.source === "PLATFORM";
  return (
    <Page title="Statements" intro="Upload what came in: the platforms' revenue and usage reports, and the IPRS statements. Each file is checked and counted once."
          actions={me.can.clear_statements && <Button kind="danger" onClick={() => setClearing(true)}>Delete all statements</Button>}>
      {clearing && <ClearDialog cid={cid} kind="statements" onClose={() => setClearing(false)} onDone={() => setQueue([])} />}
      <div className="tabs" role="tablist">
        {STATEMENT_TABS.map((x, n) => (
          <button key={x.key} role="tab" aria-selected={x.key === t.key} className={x.key === t.key ? "on" : ""} onClick={() => go(`statements/${x.key}`)}>
            <span className="muted small">{n + 1}</span> {x.label}{sides[x.source] ? <span className="tab-n">{int(sides[x.source])}</span> : null}</button>))}
      </div>
      {me.can.prepare && (
        <Card title={t.title}>
          <ClientSelect label="Client" />
          <DropZone multiple label={t.drop} hint="Excel (.xlsx) or CSV, several at once" onFiles={send} />
          {queue.length > 0 && (<>
            {lastBatch && <p className="small"><b>Batch {lastBatch}</b> · {int(queue.filter((x) => x.state === "done").length)} of {int(queue.length)} file{queue.length === 1 ? "" : "s"} uploaded</p>}
            <ul className="queue">{queue.map((x, i) => (
              <li key={i} className={x.state}>
                <span>{x.st ? <a href={`#/statements/${x.st.id}`}>{x.name}</a> : x.name}</span>
                <span className="small">{x.state === "uploading" ? <><span className="spin" /> Reading and checking…</> : x.state === "waiting" ? "Waiting…" :
                  x.st ? <><Pill tone={STATEMENT_TONE[x.st.status] ?? "neutral"}>{x.st.status_text}</Pill> {x.st.type_label}{x.st.platform ? ` · ${x.st.platform}` : ""} · {period(x.st.period_start, x.st.period_end)}{x.msg ? ` · ${x.msg}` : ""}</> : x.msg}</span>
              </li>))}</ul></>
          )}
        </Card>
      )}
      <Card title={t.label}>
        <div className="toolbar">
          <input className="input" placeholder="Search a file name, distribution or category" value={f.q} onChange={(e) => set("q", e.target.value)} />
          <Select size="sm" label="Platform" value={f.platform_id} placeholder="All platforms" onChange={(v) => set("platform_id", v)}
                  options={[{ value: "", label: "All platforms" }, ...(d?.platforms ?? []).map((p) => ({ value: String(p.id), label: p.platform_name }))]} />
          <Select size="sm" label="Status" value={f.status} placeholder="Any status" onChange={(v) => set("status", v)}
                  options={[{ value: "", label: "Any status" }, ...(d?.statuses ?? []).map((s) => ({ ...s, meta: d?.counts[s.value] ? int(d.counts[s.value]) : undefined }))]} />
          <ResetFilters active={changed(f, LIB_FILTERS)} onReset={() => { setF(LIB_FILTERS); setOffset(0); }} />
        </div>
        {d && d.counts.NEEDS_REVIEW > 0 && <Notice tone="warn">{d.counts.NEEDS_REVIEW} {d.counts.NEEDS_REVIEW === 1 ? `${t.one} needs` : `${t.many} need`} an answer before {d.counts.NEEDS_REVIEW === 1 ? "it counts" : "they count"}.
          <Button kind="ghost" className="sm" onClick={() => set("status", "NEEDS_REVIEW")}>Show them</Button></Notice>}
        {!b ? <Loading /> : b.rows.length === 0 ? <Empty title={changed(f, LIB_FILTERS) ? "No batch matches" : `No ${t.many} yet`}>{changed(f, LIB_FILTERS) ? "" : t.empty}</Empty> : (
          <ScrollX label={t.label}>
            <table className="tbl">
              <thead><tr><th>Batch</th><th>{isrc ? "Platform" : "Platforms"}</th><th>Usage period</th><th className="num">Files</th><th>Status</th>
                <th className="num">Lines</th><th className="num">{isrc ? "Revenue" : "Total"}</th>{isrc && <th className="num">Plays</th>}<th>Uploaded</th></tr></thead>
              <tbody>{b.rows.map((x) => (
                <tr key={x.id} className="click" onClick={() => setOpenBatch(x.id)}>
                  <td><b>{x.label}</b>{changed(f, LIB_FILTERS) && x.matching < x.files && <div className="muted small">{int(x.matching)} of {int(x.files)} files match</div>}</td>
                  <td className="small">{x.platforms.length === 0 ? <span className="muted">—</span> : x.platforms.length <= 3 ? x.platforms.join(", ") : <span title={x.platforms.join(", ")}>{x.platforms.slice(0, 3).join(", ")} +{x.platforms.length - 3}</span>}</td>
                  <td className="small nowrap">{x.period_label}{x.no_period > 0 && x.no_period < x.files && <div className="muted">{int(x.no_period)} without a period</div>}</td>
                  <td className="num">{int(x.files)}</td>
                  <td className="small">{Object.entries(x.statuses).map(([k, n]) => <Pill key={k} tone={STATEMENT_TONE[k] ?? "neutral"}>{int(n)} {(d?.statuses.find((y) => y.value === k)?.label ?? k).toLowerCase()}</Pill>)}</td>
                  <td className="num">{int(x.lines)}</td>
                  <td className="num">{x.types.length === 1 && x.types[0] === "RECORDING_USAGE" ? <span className="muted small">no money</span> : <Amount v={x.total} />}</td>
                  {isrc && <td className="num">{x.usage ? int(Number(x.usage)) : <span className="blank">—</span>}</td>}
                  <td className="small nowrap">{day(x.uploaded_at)}{x.uploaded_by ? ` · ${x.uploaded_by}` : ""}</td>
                </tr>))}</tbody>
            </table>
          </ScrollX>
        )}
        {b && <Pager total={b.total} offset={offset} size={50} onChange={setOffset} />}
      </Card>
      {openBatch !== null && <BatchDialog id={openBatch} onClose={() => setOpenBatch(null)} />}
      {isrc && <PlatformData cid={cid} />}
      {d && <RecordsExport cid={cid} source={t.source} platforms={d.platforms} />}
    </Page>
  );
}

/** Every file of one upload batch; each opens its statement. */
function BatchDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const { go } = useApp();
  const q = useQuery({ queryKey: ["statement-batch", id], queryFn: () => api.get<{ batch: Batch; source: string; statements: St[] }>(`/statement-batches/${id}`) });
  const x = q.data;
  const isrc = x?.source === "PLATFORM";
  return (
    <Dialog title={x ? x.batch.label : "Batch"} sub={x ? `${int(x.batch.files)} file${x.batch.files === 1 ? "" : "s"} · uploaded ${when(x.batch.uploaded_at)}${x.batch.uploaded_by ? ` by ${x.batch.uploaded_by}` : ""}` : undefined}
            onClose={onClose} wide="xl">
      {q.isError ? <Notice tone="bad">{(q.error as Error).message}</Notice> : !x ? <Loading /> : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>#</th><th>File</th><th>Platform</th><th>Usage period</th><th>Status</th><th className="num">Lines</th>
              <th className="num">{isrc ? "Revenue" : "Total"}</th>{isrc && <th className="num">Plays</th>}</tr></thead>
            <tbody>{x.statements.map((s) => (
              <tr key={s.id} className="click" onClick={() => go(`statements/${s.id}`)}>
                <td className="muted">{s.id}</td>
                <td><b className="wrap-any">{s.filename}</b><div className="muted small">{[s.type_label, s.reference].filter(Boolean).join(" · ")}</div>
                  {s.reason && s.status !== "IMPORTED" && <div className="warn-t small">{s.reason}</div>}</td>
                <td>{s.platform ?? <span className="muted small">{s.reported_platform ?? "—"}</span>}</td>
                <td className="small nowrap">{period(s.period_start, s.period_end)}</td>
                <td><Pill tone={STATEMENT_TONE[s.status] ?? "neutral"}>{s.status_text}</Pill></td>
                <td className="num">{int(s.records)}</td>
                <td className="num">{s.record_type === "RECORDING_USAGE" ? <span className="muted small">no money</span> : <Amount v={s.total} />}</td>
                {isrc && <td className="num">{s.usage ? int(Number(s.usage)) : <span className="blank">—</span>}</td>}
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <div className="actions end"><Button onClick={onClose}>Close</Button></div>
    </Dialog>
  );
}

// ================================================================== platform reports: revenue and usage combined
type Combined = { rows: { platform: string; isrc: string | null; title: string | null; album: string | null; revenue: string | null; usage: string | null;
  revenue_months: string[] | null; usage_months: string[] | null; names_differ: boolean; work_number: string | null; work_title: string | null; mapping_status: string }[];
  total: number; totals: { n: number; revenue: string | null; usage: string | null; both: number; revenue_only: number; usage_only: number; names_differ: number };
  months: { platform: string; month: string; revenue: string | null; usage: string | null; revenue_songs: number; usage_songs: number; both_songs: number }[];
  platforms: { id: number; platform_name: string }[] };
const COMB_FILTERS = { platform_id: "", from: "", to: "", q: "", only: "" };
const COMB_PAGE = 25;
const ONLY = [{ value: "", label: "Every song" }, { value: "both", label: "Revenue and usage" }, { value: "revenue_only", label: "Revenue, no usage" },
  { value: "usage_only", label: "Usage, no revenue" }, { value: "names_differ", label: "Song names differ" }];

/** The platform reports combined by ISRC and song name: revenue and plays per song for any period. */
function PlatformData({ cid }: { cid: number }) {
  const { toast } = useApp();
  const [f, setF] = useState(COMB_FILTERS);
  const [offset, setOffset] = useState(0);
  const p = { client_id: cid, platform_id: f.platform_id, period_from: monthStart(f.from), period_to: monthEnd(f.to), q: f.q, only: f.only };
  const q = useQuery({ queryKey: ["platform-data", cid, p, offset], placeholderData: (x) => x, queryFn: () => api.get<Combined>(`/platform-data${qs({ ...p, offset, limit: COMB_PAGE })}`) });
  const d = q.data;
  const set = (k: keyof typeof COMB_FILTERS, v: string) => { setF({ ...f, [k]: v }); setOffset(0); };
  if (d && d.months.length === 0 && !changed(f, COMB_FILTERS)) return null;
  return (
    <Card title="Revenue and usage, combined">
      {d && d.months.length > 0 && (
        <ScrollX label="Months covered"><table className="tbl compact">
          <thead><tr><th>Platform</th><th>Month</th><th className="num">Revenue</th><th className="num">Plays</th><th className="num">Songs with revenue</th><th className="num">Songs with plays</th><th>Combined</th></tr></thead>
          <tbody>{d.months.map((m) => (
            <tr key={m.platform + m.month}><td>{m.platform}</td><td className="nowrap">{mon(m.month)}</td><td className="num"><Amount v={m.revenue} /></td>
              <td className="num">{m.usage ? int(Number(m.usage)) : <span className="blank">—</span>}</td><td className="num">{int(m.revenue_songs)}</td><td className="num">{int(m.usage_songs)}</td>
              <td className="small">{m.revenue && m.usage ? <span className="good-t">revenue + usage ({int(m.both_songs)} songs on both)</span> : m.revenue ? <span className="warn-t">revenue only</span> : <span className="warn-t">usage only</span>}</td></tr>))}</tbody>
        </table></ScrollX>
      )}
      <div className="toolbar">
        <input className="input" placeholder="Find an ISRC, song name or work number" value={f.q} onChange={(e) => set("q", e.target.value)} />
        {(d?.platforms.length ?? 0) > 1 && <Select size="sm" label="Platform" value={f.platform_id} placeholder="All platforms" onChange={(v) => set("platform_id", v)}
                options={[{ value: "", label: "All platforms" }, ...(d?.platforms ?? []).map((x) => ({ value: String(x.id), label: x.platform_name }))]} />}
        <PeriodPicker from={f.from} to={f.to} onChange={(a, b) => { setF({ ...f, from: a, to: b }); setOffset(0); }} />
        <Select size="sm" label="Show" value={f.only} onChange={(v) => set("only", v)}
                options={ONLY.map((o) => ({ ...o, meta: d && o.value ? int(d.totals[o.value as "both"]) : undefined }))} />
        <ResetFilters active={changed(f, COMB_FILTERS)} onReset={() => { setF(COMB_FILTERS); setOffset(0); }} />
      </div>
      <div className="actions">
        <DownloadButton kind="secondary" path={`/platform-data/export${qs(p)}`} onError={(m) => toast(m, true)}>Export revenue and usage</DownloadButton>
        {d && <span className="muted small">{int(d.totals.n)} songs · revenue <Money v={d.totals.revenue} /> · {d.totals.usage ? int(Number(d.totals.usage)) : 0} plays</span>}
      </div>
      {!d ? <Loading /> : d.rows.length === 0 ? <Empty title="No song matches" /> : (
        <ScrollX label="Songs"><table className="tbl">
          <thead><tr><th>ISRC</th><th>Song</th><th>Work</th><th className="num">Revenue</th><th className="num">Plays</th><th>Months with revenue</th><th>Months with plays</th></tr></thead>
          <tbody>{d.rows.map((r, i) => (
            <tr key={i}>
              <td className="mono small">{r.isrc ?? <span className="muted">no ISRC</span>}</td>
              <td><b>{r.title}</b><div className="muted small">{r.album}{r.names_differ && <span className="warn-t"> · the two reports name it differently</span>}</div></td>
              <td className="small">{r.work_number ? <>{r.work_number}<div className="muted">{r.work_title}</div></> : <MappingPill status={r.mapping_status} />}</td>
              <td className="num"><Amount v={r.revenue} /></td>
              <td className="num">{r.usage ? int(Number(r.usage)) : <span className="blank">—</span>}</td>
              <td className="small nowrap">{r.revenue_months?.length ? period(r.revenue_months[0], r.revenue_months[r.revenue_months.length - 1]) : <span className="blank">—</span>}</td>
              <td className="small nowrap">{r.usage_months?.length ? period(r.usage_months[0], r.usage_months[r.usage_months.length - 1]) : <span className="blank">—</span>}</td>
            </tr>))}</tbody>
        </table></ScrollX>
      )}
      {d && <Pager total={d.total} offset={offset} size={COMB_PAGE} onChange={setOffset} />}
    </Card>
  );
}

function RecordsExport({ cid, source, platforms }: { cid: number; source: string; platforms: { id: number; platform_name: string }[] }) {
  const { toast } = useApp();
  const t = source === "PLATFORM" ? "RECORDING_REVENUE" : "WORK_ROYALTY";
  const [p, setP] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const plat = platforms.find((x) => String(x.id) === p)?.platform_name;
  return (
    <Card title="Export records">
      <div className="toolbar">
        <Select size="sm" label="Platform" value={p} placeholder="All platforms" onChange={setP}
                options={[{ value: "", label: "All platforms" }, ...platforms.map((x) => ({ value: String(x.id), label: x.platform_name }))]} />
        <PeriodPicker from={from} to={to} onChange={(a, b) => { setFrom(a); setTo(b); }} />
        <ResetFilters active={!!(p || from || to)} onReset={() => { setP(""); setFrom(""); setTo(""); }} />
      </div>
      <div className="actions">
        <DownloadButton kind="secondary" onError={(m) => toast(m, true)}
                        path={`/records/export${qs({ client_id: cid, record_type: t, source, platform_id: p, period_from: monthStart(from), period_to: monthEnd(to) })}`}>Export records</DownloadButton>
        <Selection parts={[source === "PLATFORM" ? "platform revenue lines" : "IPRS statement lines", plat ?? "all platforms",
          from && to ? `${mon(from)} – ${mon(to)}` : "all periods"]} />
      </div>
    </Card>
  );
}

// ================================================================== one statement
type Detail = { statement: St; problems: { severity: string; message: string; detail?: string }[];
  questions: { field: string; message: string; options: { value: string; label: string }[]; required: boolean }[];
  meta: Record<string, string>; meta_source: Record<string, string>; layout: string; kind_label: string; sha256: string; bytes: number;
  mapping: { status: string; lines: number; amount: string | null; works?: number; blank?: number; plays?: string | null }[];
  months: { month: string; lines: number; amount: string | null; plays?: string | null }[]; related: St[] };

const FIELD_LABEL: Record<string, string> = { category: "Royalty category", dist_no: "Distribution number", overseas_society: "Overseas society",
  period: "Usage period (for example Oct 2025 - Mar 2026)", date: "Distribution date (YYYY-MM-DD)", platform: "Platform", distributor: "Distributor",
  currency: "Currency", basis: "Revenue basis", relation: "How does it relate to the earlier statement?", accept_edited: "Use it anyway?" };

function StatementPage({ id }: { id: number }) {
  const { me, go, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["statement", id], queryFn: () => api.get<Detail>(`/statements/${id}`) });
  if (q.isError) return <Page title="Statement"><Notice tone="bad">{(q.error as Error).message}</Notice></Page>;
  if (!q.data) return <Loading />;
  const d = q.data;
  const s = d.statement;
  const save = async (body: object) => {
    try { qc.setQueryData(["statement", id], await api.patch<Detail>(`/statements/${id}`, body)); toast("Saved."); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <Page title={s.filename} intro={<>{s.type_label} · statement #{s.id} · uploaded {when(s.uploaded_at)}{s.uploaded_by ? ` by ${s.uploaded_by}` : ""}</>}
          actions={<>
            <Button kind="ghost" onClick={() => go(`statements/${STATEMENT_TABS.find((x) => x.source === s.source)?.key ?? "iprs"}`)}>{STATEMENT_TABS.find((x) => x.source === s.source)?.label ?? "All statements"}</Button>
            <DownloadButton kind="secondary" path={`/statements/${id}/original`} onError={(m) => toast(m, true)}>Original file</DownloadButton>
            <DownloadButton kind="secondary" path={`/statements/${id}/error-report`} onError={(m) => toast(m, true)}>Error report</DownloadButton>
          </>}>
      <Card title={<><Pill tone={STATEMENT_TONE[s.status] ?? "neutral"}>{s.status_text}</Pill></>} sub={s.reason}>
        {d.questions.length > 0 && me.can.prepare && <Questions id={id} questions={d.questions} />}
        <div className="two">
          <Facts items={[
            ["Kind", <>{s.side_label}
              <div className="muted small">{s.source === "PLATFORM" ? "Revenue (the client's share) and usage per ISRC: the basis of the expected royalty"
                : s.source === "IPRS" ? "What IPRS paid, compared with the IPRS % of each song's total revenue" : "Left out: the same file is under IPRS statements"}</div></>],
            ["Layout", s.type_label],
            ["Platform", s.platform ? `${s.platform}${s.reported_platform && s.reported_platform !== s.platform ? ` (written '${s.reported_platform}')` : ""}`
              : <span className="muted">{s.reported_platform ? `'${s.reported_platform}' - not a platform` : "not a platform statement"}</span>],
            ["Category", s.category], ["Distributor", s.distributor],
            ["Distribution / reference", s.reference],
            ["Usage period", period(s.period_start, s.period_end)],
            ["Statement date", s.statement_date ? `${day(s.statement_date)}${s.statement_date_estimated ? " (date the file was saved)" : ""}` : "Not stated"],
          ]} />
          <Facts items={[
            ["Payment date", me.can.prepare ? <input className="input sm" type="date" value={s.payment_date ?? ""} onChange={(e) => save({ payment_date: e.target.value || null })} />
              : (s.payment_date ? day(s.payment_date) : "Not known")],
            ["Currency", s.record_type === "RECORDING_USAGE" ? "Not applicable (plays)" : s.currency ? `${s.currency}${d.meta_source.currency ? ` (${d.meta_source.currency})` : ""}` : "Not established"],
            ["Revenue basis", s.basis ? s.basis.toLowerCase() : (s.record_type === "RECORDING_REVENUE" ? "Not established" : "Not applicable")],
            ["Territory", s.territory ?? "Not stated"],
            ["Lines", int(s.records)], ["Total", s.record_type === "RECORDING_USAGE" ? <span className="muted">no money (usage report)</span> : <Amount v={s.total} />],
            ...(s.usage ? [["Plays", int(Number(s.usage))] as [string, React.ReactNode]] : []),
            ["File fingerprint", <span className="mono small">{d.sha256.slice(0, 16)}…</span>],
          ]} />
        </div>
        {d.problems.length > 0 && (
          <More label={`Checks and notes (${d.problems.length})`}>
            <ul className="plain">{d.problems.map((p, i) => <li key={i} className={`msg ${p.severity}`}><b>{p.severity.toLowerCase()}</b> · {p.message}</li>)}</ul>
          </More>
        )}
        {d.related.length > 0 && (
          <More label="Related statements">
            <ul className="plain">{d.related.map((r) => <li key={r.id}><a href={`#/statements/${r.id}`}>#{r.id} {r.filename}</a> · {r.status_text}</li>)}</ul>
          </More>
        )}
      </Card>
      <Card title="Matching to the catalogue" sub={s.record_type !== "WORK_ROYALTY" ? "Lines by catalogue link of their ISRC. Unmatched lines are kept, never discarded." : "Lines by whether their work number is in the catalogue."}>
        <div className="tbl-wrap short"><table className="tbl">
          <thead><tr><th>Catalogue</th><th className="num">Lines</th>{s.record_type === "WORK_ROYALTY" && <th className="num">Works</th>}
            {s.record_type !== "RECORDING_USAGE" && <th className="num">Amount</th>}{s.record_type !== "WORK_ROYALTY" && <th className="num">Plays</th>}</tr></thead>
          <tbody>{d.mapping.map((m) => <tr key={m.status}><td><MappingPill status={m.status} /></td><td className="num">{int(m.lines)}</td>
            {s.record_type === "WORK_ROYALTY" && <td className="num">{int(m.works)}</td>}{s.record_type !== "RECORDING_USAGE" && <td className="num"><Amount v={m.amount} /></td>}
            {s.record_type !== "WORK_ROYALTY" && <td className="num">{m.plays ? int(Number(m.plays)) : <span className="blank">—</span>}</td>}</tr>)}</tbody>
        </table></div>
        {d.months.length > 0 && <More label="By usage month"><ul className="plain small">{d.months.map((m) => <li key={m.month}>{mon(m.month)}: {int(m.lines)} lines{m.amount != null && <>, <Money v={m.amount} /></>}{m.plays ? `, ${int(Number(m.plays))} plays` : ""}</li>)}</ul></More>}
      </Card>
      <Records id={id} type={s.record_type} />
    </Page>
  );
}

function Questions({ id, questions }: { id: number; questions: Detail["questions"] }) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const [ans, setAns] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  return (
    <form className="form box" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      try {
        const answers = Object.fromEntries(Object.entries(ans).filter(([, v]) => v !== ""));
        qc.setQueryData(["statement", id], await api.post<Detail>(`/statements/${id}/answer`, { answers }));
        qc.invalidateQueries({ queryKey: ["statements"] });
        setAns({});
        toast("Saved.");
      } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
    }}>
      <b>Please answer before this statement counts</b>
      {questions.map((q) => (
        <label key={q.field} className="field">{q.message}{!q.required && <span className="muted small"> (optional)</span>}
          {q.options.length ? <Select value={ans[q.field] ?? ""} label={FIELD_LABEL[q.field] ?? q.field} placeholder="Choose…" onChange={(v) => setAns({ ...ans, [q.field]: v })} options={q.options} />
            : <input className="input" placeholder={FIELD_LABEL[q.field] ?? q.field} value={ans[q.field] ?? ""} onChange={(e) => setAns({ ...ans, [q.field]: e.target.value })} />}
        </label>
      ))}
      <div className="actions"><Button kind="primary" type="submit" busy={busy} disabled={!Object.values(ans).some(Boolean)}>Save answers</Button></div>
    </form>
  );
}

function Records({ id, type }: { id: number; type: string }) {
  const [q, setQ] = useState("");
  const [mapping, setMapping] = useState("");
  const [offset, setOffset] = useState(0);
  const r = useQuery({ queryKey: ["records", id, q, mapping, offset], queryFn: () => api.get<{ rows: any[]; total: number }>(`/statements/${id}/records${qs({ q, mapping, offset })}`) });
  const isrc = type !== "WORK_ROYALTY";
  const opts = isrc ? ["VERIFIED", "PENDING", "CONFLICT", "UNKNOWN", "NO_ISRC"] : ["MATCHED", "WORK_NOT_FOUND", "NO_WORK_NUMBER"];
  return (
    <Card title="Records">
      <div className="toolbar">
        <input className="input" placeholder={isrc ? "Find an ISRC or title" : "Find a work number, title or party"} value={q}
               onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <Select size="sm" label="Catalogue" value={mapping} placeholder="Any" onChange={(v) => { setMapping(v); setOffset(0); }}
                options={[{ value: "", label: "Any" }, ...opts.map((o) => ({ value: o, label: o.replace(/_/g, " ").toLowerCase() }))]} />
        <ResetFilters active={!!(q || mapping)} onReset={() => { setQ(""); setMapping(""); setOffset(0); }} />
      </div>
      {!r.data ? <Loading /> : (
        <ScrollX label="Records"><table className="tbl">
          {isrc ? <>
            <thead><tr><th>Row</th><th>Month</th><th>ISRC</th><th>Title</th><th>Work</th><th>Catalogue</th>{type === "RECORDING_REVENUE" && <th className="num">Amount</th>}<th className="num">Plays</th></tr></thead>
            <tbody>{r.data.rows.map((x) => <tr key={x.row}><td className="num">{x.row}</td><td className="nowrap">{mon(x.month)}</td><td className="mono">{x.isrc}</td>
              <td>{x.title}<div className="muted small">{x.album}</div></td><td className="small">{x.work_number}{x.work_title ? ` · ${x.work_title}` : ""}</td>
              <td><MappingPill status={x.mapping_status} /></td>{type === "RECORDING_REVENUE" && <td className="num"><Amount v={x.amount} missing="blank" /></td>}
              <td className="num">{x.plays != null ? int(Number(x.plays)) : <span className="blank">—</span>}</td></tr>)}</tbody>
          </> : <>
            <thead><tr><th>Row</th><th>Work</th><th>Title</th><th>Party</th><th>Role</th><th className="num">Coll %</th><th>Source</th><th>Catalogue</th><th className="num">Royalty</th></tr></thead>
            <tbody>{r.data.rows.map((x) => <tr key={x.row}><td className="num">{x.row}</td><td className="mono">{x.work_number}</td><td>{x.title}</td>
              <td className="small">{x.party}</td><td>{x.role}</td><td className="num">{x.coll ?? ""}</td><td className="small">{x.source || x.pool}</td>
              <td><MappingPill status={x.mapping_status} /></td><td className="num"><Money v={x.amount} /></td></tr>)}</tbody>
          </>}
        </table></ScrollX>
      )}
      {r.data && <Pager total={r.data.total} offset={offset} size={200} onChange={setOffset} />}
    </Card>
  );
}
