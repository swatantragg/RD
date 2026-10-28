import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api";
import { dmy, int, mon, money } from "../format";
import { useApp } from "../session";
import { Amount, ClientSelect, MappingPill, NeedClient, Pager, PeriodPicker, ResetFilters, Selection, changed, freeze, monthEnd, monthStart, period } from "../parts";
import { Button, Card, Dialog, DownloadButton, Empty, Loading, Money, Notice, Page, Pill, ScrollX, Select, day } from "../ui";
import { WorkDialog } from "./Catalogue";

type Kind = "revenue" | "usage" | "client" | "royalty";
type Row = { id: number; internal_work_number: string | null; work_title: string; catalogue_status: string; isrcs: { isrc: string; status: string }[];
  mapping_state: string; open_exceptions: number; last_updated: string } & { [K in Kind]: Record<string, string | null> | null } & { [K in `${Kind}_total`]: string | null };
type View = { rows: Row[]; total: number; offset: number; columns: Record<Kind, { id: string; name: string }[]>;
  totals: Record<Kind, Record<string, string>>;
  unmatched: { kind: string; platform: string; status: string; lines: number; amount: string | null }[]; partial_statements: number;
  statements: { id: number; original_filename: string; record_type: string; statement_source: string; statement_reference: string | null }[]; platforms: { id: number; name: string }[] };

const MONEY_OPTS = [{ value: "", label: "Every work" }, { value: "any", label: "Works with money" },
  { value: "usage", label: "Works with plays" }, { value: "revenue_no_iprs", label: "Platform revenue but nothing from IPRS" }, { value: "none", label: "Works without money or plays" }];
const KINDS: [Kind, string, string][] = [["revenue", "Platform revenue", "rev"], ["usage", "Usage (plays)", "use"], ["client", "Client statements", "cli"], ["royalty", "IPRS paid", "roy"]];
const SORT_OPTS = [{ value: "title", label: "Song title, A → Z" }, { value: "title_desc", label: "Song title, Z → A" },
  { value: "revenue", label: "Platform revenue, high → low" }, { value: "revenue_asc", label: "Platform revenue, low → high" }, { value: "usage", label: "Most plays first" }, { value: "royalty", label: "Most paid by IPRS first" },
  { value: "work", label: "Work number" }, { value: "updated", label: "Recently updated" }];

export default function Master({ tab }: { tab?: string }) {
  const { go } = useApp();
  const cur = tab === "unmatched" ? "unmatched" : tab === "works" ? "works" : "sheet";
  const [f, setF] = useState<F>(MASTER_FILTERS);
  return (
    <NeedClient>{(cid) => (
      <Page title="Master" intro="Every work with its platform revenue, plays and what IPRS paid, for any period - the master statement to export.">
        <Card><ClientSelect label="Client" /></Card>
        <div className="tabs" role="tablist">
          {[["sheet", "Master sheet"], ["works", "Works by platform"], ["unmatched", "Unmatched money"]].map(([k, l]) => (
            <button key={k} role="tab" aria-selected={cur === k} className={cur === k ? "on" : ""} onClick={() => go(`master/${k}`)}>{l}</button>))}
        </div>
        {cur === "sheet" ? <MasterSheet key={cid} cid={cid} f={f} setF={setF} /> : cur === "works" ? <Works cid={cid} f={f} setF={setF} /> : <Unmatched cid={cid} f={f} setF={setF} />}
      </Page>
    )}</NeedClient>
  );
}

// ================================================================== the master sheet (SKV layout)
type SortKey = "title" | "amount" | "platform";
type SheetCol = { h: string; t: "text" | "money" | "date"; sep?: boolean; sort?: SortKey };
type SheetGroup = { label: string; kind: "IDENT" | "ROYALTY" | "PLATFORM" | "FY" | "AUDIT"; fill?: string; tint?: string; start: number; span: number; distributions?: number };
type Sheet = { columns: SheetCol[]; groups: SheetGroup[]; rows: (string | null)[][]; total_row: (string | null)[]; total: number; all_rows: number;
  offset: number; statements: number; built_at: string; sort: string; platform_revenue: boolean };
const SHEET_PAGE = 100;
const FIRST: Record<SortKey, string> = { title: "title_asc", amount: "amount_desc", platform: "platform_desc" };   // a header's first click
const FLIP: Record<string, string> = { title_asc: "title_desc", title_desc: "title_asc", amount_desc: "amount_asc", amount_asc: "amount_desc",
  platform_desc: "platform_asc", platform_asc: "platform_desc" };
const FROZEN = 3;                                          // ISRC, Song Name and Internal No stay in view while scrolling sideways

function cell(v: string | null, t: SheetCol["t"]): string {
  if (v === null || v === "") return "";
  return t === "money" ? money(v) : t === "date" ? dmy(v) : v;
}

function MasterSheet({ cid, f, setF }: { cid: number; f: F; setF: (f: F) => void }) {
  const { toast } = useApp();
  const [offset, setOffset] = useState(0);
  const [side, setSide] = useState<"CLIENT" | "IPRS">("CLIENT");
  const [sort, setSort] = useState("title_asc");
  const p = { client_id: cid, side, q: f.q, platform_id: f.platform_id, period_from: monthStart(f.from), period_to: monthEnd(f.to), statement_id: f.statement_id, sort };
  const q = useQuery({ queryKey: ["master-sheet", p, offset], placeholderData: (x) => x, staleTime: 60_000, retry: false,
    queryFn: () => api.get<Sheet>(`/master/sheet${qs({ ...p, offset, limit: SHEET_PAGE })}`) });
  const opts = useQuery({ queryKey: ["master", { client_id: cid }, "opts"], staleTime: 60_000,
    queryFn: () => api.get<View>(`/master${qs({ client_id: cid, offset: 0 })}`) });
  const set = (k: keyof F, val: string) => { setF({ ...f, [k]: val }); setOffset(0); if (k === "platform_id" && sort.startsWith("platform")) setSort("title_asc"); };
  const order = (s: string) => { setSort(s); setOffset(0); };
  const v = q.data;
  const shown = v?.sort ?? sort;                            // the server falls back to Song name A → Z when a platform sort no longer applies
  const table = useRef<HTMLTableElement>(null);
  useLayoutEffect(() => freeze(table.current), [v]);         // each frozen column starts where the ones before it end
  const plat = opts.data?.platforms.find((x) => String(x.id) === f.platform_id)?.name;
  const stmt = opts.data?.statements.find((x) => String(x.id) === f.statement_id);
  const sorts = [{ value: "title_asc", label: "Song name, A → Z" }, { value: "title_desc", label: "Song name, Z → A" },
    { value: "amount_desc", label: "Total amount, high → low" }, { value: "amount_asc", label: "Total amount, low → high" },
    ...(plat && v?.platform_revenue ? [{ value: "platform_desc", label: `${plat} revenue, high → low` }, { value: "platform_asc", label: `${plat} revenue, low → high` }] : [])];
  const head = (c: SheetCol) => {
    if (!c.sort) return c.h;
    const on = shown.startsWith(c.sort);
    return <button type="button" className="th-sort" title={`Sort by ${c.h}`} onClick={() => order(on ? FLIP[shown] : FIRST[c.sort!])}>
      {c.h}<span className={on ? "on" : ""} aria-hidden>{on ? (shown.endsWith("_asc") ? " ▲" : " ▼") : " ↕"}</span></button>;
  };
  const dir = (c: SheetCol) => c.sort && shown.startsWith(c.sort) ? (shown.endsWith("_asc") ? "ascending" : "descending") : undefined;
  return (
    <>
      <Card>
        <div className="queue-bar">
          <span>Statements:</span>
          <div className="seg" role="radiogroup" aria-label="Statements">
            {([["CLIENT", "Platform revenue reports"], ["IPRS", "IPRS statements"]] as const).map(([k, l]) => (
              <button key={k} type="button" role="radio" aria-checked={side === k} className={side === k ? "on" : ""}
                      onClick={() => { setSide(k); setOffset(0); setF({ ...f, statement_id: "" }); }}>{l}</button>))}
          </div>
        </div>
        <div className="toolbar">
          <input className="input" placeholder="Search song name, ISRC or work number" value={f.q} onChange={(e) => set("q", e.target.value)} />
          <Select size="sm" label="Platform" value={f.platform_id} placeholder="All platforms" onChange={(x) => set("platform_id", x)}
                  options={[{ value: "", label: "All platforms" }, ...(opts.data?.platforms ?? []).map((x) => ({ value: String(x.id), label: x.name }))]} />
          <PeriodPicker from={f.from} to={f.to} onChange={(a, b) => { setF({ ...f, from: a, to: b }); setOffset(0); }} />
          <Select size="sm" label="Statement" value={f.statement_id} placeholder="Every statement" onChange={(x) => set("statement_id", x)}
                  options={[{ value: "", label: "Every statement" }, ...(opts.data?.statements ?? []).filter((x) => side === "IPRS" ? x.statement_source === "IPRS" : x.statement_source !== "IPRS" && x.record_type !== "RECORDING_USAGE").map((x) => ({ value: String(x.id), label: x.original_filename, meta: `#${x.id}` }))]} />
          <Select size="sm" label="Sort" value={shown} onChange={order} options={sorts} />
          <ResetFilters active={side !== "CLIENT" || sort !== "title_asc" || !!(f.q || f.platform_id || f.from || f.to || f.statement_id)}
                        onReset={() => { setSide("CLIENT"); setSort("title_asc"); setF({ ...f, q: "", platform_id: "", from: "", to: "", statement_id: "" }); setOffset(0); }} />
        </div>
        <div className="actions">
          <DownloadButton kind="primary" path={`/master/export-statement${qs({ client_id: cid, side, platform_id: f.platform_id, period_from: monthStart(f.from), period_to: monthEnd(f.to), statement_id: f.statement_id, sort: shown })}`}
                          onError={(m) => toast(m, true)}>Export master statement (.xlsx)</DownloadButton>
          <Selection parts={[side === "CLIENT" ? "the platform revenue reports" : "the IPRS statements", plat ?? "all platforms", f.from && f.to ? `${mon(f.from)} – ${mon(f.to)}` : "all periods", stmt && `statement #${stmt.id}`, f.q && `search '${f.q}'`]} />
        </div>
      </Card>
      <Card>
        {q.isError ? <Notice tone="bad">{(q.error as Error).message}</Notice> : !v ? <Loading text="Building the master sheet from the statements and the catalogue…" /> : (
          <>
            {plat && side === "CLIENT" && !v.platform_revenue && <Notice>No {plat} revenue report is imported for this selection, so there is no Total {plat} Revenue column.
              It appears once a {plat} revenue report is uploaded under Statements → Platform reports.</Notice>}
            <div className="queue-bar"><span className="muted small">{int(v.total)} song row{v.total === 1 ? "" : "s"}{v.total !== v.all_rows ? ` of ${int(v.all_rows)}` : ""} ·
              {" "}{int(v.statements)} statement{v.statements === 1 ? "" : "s"} · {int(v.groups.filter((g) => g.kind === "ROYALTY" || g.kind === "PLATFORM").length)} sections</span>
              {q.isFetching && <span className="muted small"><span className="spin" /> updating…</span>}</div>
            {v.rows.length === 0 ? <Empty title="No song matches">Change the search.</Empty> : (
              <ScrollX className="sheet-wrap" label="Master sheet">
                <table className="skv" ref={table}>
                  <colgroup>{v.groups.map((g, i) => <col key={i} span={g.span} className={`g-${g.kind.toLowerCase()}`}
                                                          style={g.tint ? ({ "--tint": `#${g.tint}` } as CSSProperties) : undefined} />)}</colgroup>
                  <thead>
                    <tr className="h1">{v.groups.map((g, i) => g.kind === "IDENT"
                      ? [<th key={`${i}a`} colSpan={FROZEN} className="fz fz0 band-id" />, <th key={`${i}b`} colSpan={g.span - FROZEN} className="band-id" />]
                      : <th key={i} colSpan={g.span} className="band" style={g.fill ? ({ "--fill": `#${g.fill}` } as CSSProperties) : undefined}>{g.label}</th>)}</tr>
                    <tr className="h2">{v.columns.map((c, i) => {
                      const g = v.groups.find((x) => i >= x.start && i < x.start + x.span)!;
                      return <th key={i} className={`${i < FROZEN ? `fz fz${i}` : ""} ${c.t === "money" ? "num" : ""} ${c.sep ? "sep" : ""} ${g.kind === "IDENT" ? "band-id" : "band"}`}
                                 aria-sort={dir(c)} style={g.kind !== "IDENT" && g.fill ? ({ "--fill": `#${g.fill}` } as CSSProperties) : undefined}>{head(c)}</th>;
                    })}</tr>
                  </thead>
                  <tbody>{v.rows.map((r, ri) => (
                    <tr key={v.offset + ri}>{r.map((x, ci) => {
                      const c = v.columns[ci];
                      const text = cell(x, c.t);
                      return ci < FROZEN
                        ? <td key={ci} className={`fz fz${ci}`} title={x ?? undefined}><div className="clip">{text}</div></td>
                        : <td key={ci} className={`${c.t === "money" ? "num" : ""} ${c.sep ? "sep" : ""} ${ci === 3 ? "b" : ""}`}>{text}</td>;
                    })}</tr>))}</tbody>
                  <tfoot><tr>{v.total_row.map((x, ci) => {
                    const c = v.columns[ci];
                    return <td key={ci} className={`${ci < FROZEN ? `fz fz${ci}` : ""} ${c.t === "money" ? "num" : ""} ${c.sep ? "sep" : ""}`}>{ci < FROZEN ? <div className="clip"><b>{x}</b></div> : <b>{cell(x, c.t === "date" ? "text" : c.t)}</b>}</td>;
                  })}</tr></tfoot>
                </table>
              </ScrollX>
            )}
            <Pager total={v.total} offset={offset} size={SHEET_PAGE} onChange={setOffset} />
          </>
        )}
      </Card>
    </>
  );
}

type F = { q: string; platform_id: string; from: string; to: string; status: string; mapping: string; money: string; statement_id: string; sort: string };
const MASTER_FILTERS: F = { q: "", platform_id: "", from: "", to: "", status: "", mapping: "", money: "", statement_id: "", sort: "title" };

function Filters({ f, set, v, full, onReset }: { f: F; set: (k: keyof F, val: string) => void; v?: View; full?: boolean; onReset: () => void }) {
  return (
    <div className="toolbar">
      {full && <input className="input" placeholder="Search song title, work number or ISRC" value={f.q} onChange={(e) => set("q", e.target.value)} />}
      <Select size="sm" label="Platform" value={f.platform_id} placeholder="All platforms" onChange={(x) => set("platform_id", x)}
              options={[{ value: "", label: "All platforms" }, ...(v?.platforms ?? []).map((p) => ({ value: String(p.id), label: p.name }))]} />
      <PeriodPicker from={f.from} to={f.to} onChange={(a, b) => { set("from", a); set("to", b); }} />
      {full && <>
        <Select size="sm" label="Catalogue status" value={f.status} placeholder="Any status" onChange={(x) => set("status", x)}
                options={[{ value: "", label: "Any status" }, { value: "ACTIVE", label: "Active" }, { value: "REVIEW", label: "Needs review" },
                  { value: "TO_REGISTER", label: "To register" }, { value: "INACTIVE", label: "Inactive" }]} />
        <Select size="sm" label="Links" value={f.mapping} placeholder="Any links" onChange={(x) => set("mapping", x)}
                options={[{ value: "", label: "Any links" }, { value: "VERIFIED", label: "Has verified links" }, { value: "PENDING", label: "Has links to verify" },
                  { value: "CONFLICT", label: "Has conflicting links" }, { value: "NONE", label: "No ISRC" }]} />
        <Select size="sm" label="Money" value={f.money} onChange={(x) => set("money", x)} options={MONEY_OPTS} />
        <Select size="sm" label="Statement" value={f.statement_id} placeholder="Every statement" onChange={(x) => set("statement_id", x)}
                options={[{ value: "", label: "Every statement" }, ...(v?.statements ?? []).map((s) => ({ value: String(s.id), label: s.original_filename, meta: `#${s.id}` }))]} />
        <Select size="sm" label="Sort" value={f.sort} onChange={(x) => set("sort", x)} options={SORT_OPTS} />
      </>}
      <ResetFilters active={full ? changed(f, MASTER_FILTERS) : !!(f.platform_id || f.from || f.to)} onReset={onReset} />
    </div>
  );
}

function sum(xs: { amount: string | null }[]): number {
  return xs.reduce((a, u) => a + Number(u.amount ?? 0), 0);
}

function params(cid: number, f: F) {
  return { client_id: cid, q: f.q, platform_id: f.platform_id, period_from: monthStart(f.from), period_to: monthEnd(f.to), status: f.status,
    mapping: f.mapping, money: f.money, statement_id: f.statement_id, sort: f.sort };
}

function Works({ cid, f, setF }: { cid: number; f: F; setF: (f: F) => void }) {
  const { toast } = useApp();
  const [offset, setOffset] = useState(0);
  const [src, setSrc] = useState<Row | null>(null);
  const [work, setWork] = useState<number | null>(null);
  const p = params(cid, f);
  const q = useQuery({ queryKey: ["master", p, offset], queryFn: () => api.get<View>(`/master${qs({ ...p, offset })}`), placeholderData: (x) => x });
  const v = q.data;
  const set = (k: keyof F, val: string) => { setF({ ...f, [k]: val }); setOffset(0); };
  const plat = v?.platforms.find((x) => String(x.id) === f.platform_id)?.name;
  const stmt = v?.statements.find((x) => String(x.id) === f.statement_id);
  const sel = [plat ?? "all platforms", f.from && f.to ? `${mon(f.from)} – ${mon(f.to)}` : "all periods", stmt && `statement #${stmt.id}`,
    f.q && `search '${f.q}'`, f.status && `status ${f.status.toLowerCase()}`, f.mapping && `links ${f.mapping.toLowerCase()}`,
    f.money && MONEY_OPTS.find((m) => m.value === f.money)?.label.toLowerCase()];
  const kinds = KINDS.filter(([k]) => (v?.columns[k] ?? []).length > 0);
  const unm = (v?.unmatched ?? []).filter((u) => u.kind === "revenue");
  const unc = (v?.unmatched ?? []).filter((u) => u.kind === "client");
  const unr = (v?.unmatched ?? []).filter((u) => u.kind === "royalty");
  const val = (k: Kind, x: string | null | undefined) => k === "usage" ? (x == null ? <span className="blank">—</span> : int(Number(x))) : <Amount v={x ?? null} />;
  const tot = (k: Kind, x: string | number | null | undefined) => k === "usage" ? (x == null ? "" : int(Number(x))) : <Money v={x ?? null} />;
  return (
    <>
      <Card>
        <Filters f={f} set={set} v={v} full onReset={() => { setF(MASTER_FILTERS); setOffset(0); }} />
        {v && (unm.length > 0 || unc.length > 0 || unr.length > 0) && (
          <Notice tone="warn">Kept but not counted below, because it reaches no catalogue work:
            {[[unm, "platform revenue"], [unc, "client statements"], [unr, "statements from IPRS"]].filter(([xs]) => (xs as typeof unm).length > 0).map(([xs, l], n) => (
              <span key={l as string}>{n > 0 && ";"} {l as string} <Money v={sum(xs as typeof unm)} /> ({int((xs as typeof unm).reduce((a, u) => a + u.lines, 0))} lines)</span>))}
            {" "}- their ISRC or work number reaches no catalogue work.
            {" "}<a href="#/master/unmatched">See the list</a></Notice>
        )}
        {v && v.partial_statements > 0 && <Notice>{v.partial_statements} IPRS statement{v.partial_statements === 1 ? "" : "s"} with a usage period only partly inside (or not stated for) the selected period {v.partial_statements === 1 ? "is" : "are"} not included.</Notice>}
        <div className="actions">
          <DownloadButton kind="secondary" path={`/master/export${qs(p)}`} onError={(m) => toast(m, true)}>Export this view</DownloadButton>
          <DownloadButton kind="primary" path={`/master/export-statement${qs({ client_id: cid, platform_id: f.platform_id, period_from: monthStart(f.from), period_to: monthEnd(f.to), statement_id: f.statement_id })}`}
                          onError={(m) => toast(m, true)}>Export master statement</DownloadButton>
          <Selection parts={sel} />
        </div>
      </Card>
      <Card>
        {!v ? <Loading /> : v.rows.length === 0 ? <Empty title="No work matches">Change the filters, or import the catalogue first.</Empty> : (
          <ScrollX label="Works by platform">
            <table className="tbl master" ref={(t) => freeze(t)}>
              <thead>
                <tr><th rowSpan={2} className="fz fz0">Internal No</th><th rowSpan={2} className="fz fz1">Song</th><th rowSpan={2} className="fz fz2">ISRCs</th><th rowSpan={2}>Links</th>
                  {kinds.map(([k, l, cls]) => <th key={k} colSpan={v.columns[k].length + 1} className={`grp ${cls === "roy" ? "roy" : "rev"}`}>{l}</th>)}
                  <th rowSpan={2}>Exceptions</th><th rowSpan={2}>Updated</th></tr>
                <tr>{kinds.map(([k]) => [...v.columns[k].map((c) => <th key={k + c.id} className="num">{c.name}</th>), <th key={k + "t"} className="num">Total</th>])}</tr>
              </thead>
              <tbody>{v.rows.map((r) => (
                <tr key={r.id} className="click" onClick={() => setSrc(r)}>
                  <td className="fz fz0 mono nowrap">{r.internal_work_number ?? <span className="muted small">no work number</span>}</td>
                  <td className="fz fz1"><b>{r.work_title}</b></td>
                  <td className="fz fz2 small mono nowrap" title={r.isrcs.map((x) => x.isrc).join(", ")}>{r.isrcs.length ? <>{r.isrcs.slice(0, 2).map((x) => x.isrc).join(", ")}
                    {r.isrcs.length > 2 && <span className="muted"> +{r.isrcs.length - 2}</span>}</> : "—"}</td>
                  <td><MappingPill status={r.mapping_state} /></td>
                  {kinds.map(([k]) => [...v.columns[k].map((c) => <td key={k + c.id} className="num">{val(k, r[k]?.[String(c.id)])}</td>),
                    <td key={k + "t"} className="num"><b>{val(k, r[`${k}_total`])}</b></td>])}
                  <td>{r.open_exceptions ? <Pill tone="warn">{r.open_exceptions} open</Pill> : ""}</td>
                  <td className="small nowrap">{day(r.last_updated)}</td>
                </tr>))}</tbody>
              <tfoot><tr><td colSpan={3} className="fz fz0"><b>Total ({int(v.total)} works, all pages)</b></td><td />
                {kinds.map(([k]) => [...v.columns[k].map((c) => <td key={k + c.id} className="num">{tot(k, v.totals[k][String(c.id)])}</td>),
                  <td key={k + "t"} className="num"><b>{tot(k, Object.values(v.totals[k]).reduce((a, b) => a + Number(b || 0), 0))}</b></td>])}
                <td colSpan={2} /></tr></tfoot>
            </table>
          </ScrollX>
        )}
        {v && <Pager total={v.total} offset={offset} size={100} onChange={setOffset} />}
      </Card>
      {src && <Sources row={src} f={f} onClose={() => setSrc(null)} onWork={() => { setWork(src.id); setSrc(null); }} />}
      {work && <WorkDialog workId={work} onClose={() => setWork(null)} />}
    </>
  );
}

function Sources({ row, f, onClose, onWork }: { row: Row; f: F; onClose: () => void; onWork: () => void }) {
  const q = useQuery({ queryKey: ["sources", row.id, f], queryFn: () => api.get<{ revenue: any[]; royalty: any[] }>(
    `/master/works/${row.id}/sources${qs({ platform_id: f.platform_id, period_from: monthStart(f.from), period_to: monthEnd(f.to), statement_id: f.statement_id })}`) });
  return (
    <Dialog title={row.work_title} sub={`Work ${row.internal_work_number ?? "without a number"} · the statement lines behind the amounts`} onClose={onClose} wide="xl">
      {!q.data ? <Loading /> : <div className="form full">
        <h2>Platform report lines ({q.data.revenue.length})</h2>
        {q.data.revenue.length === 0 ? <p className="muted">No platform revenue or usage line in this selection.</p> : (
          <div className="tbl-wrap short"><table className="tbl">
            <thead><tr><th>Report</th><th>Statement</th><th>Row</th><th>Platform</th><th>Month</th><th>ISRC</th><th>Title</th><th>Link</th><th className="num">Revenue</th><th className="num">Plays</th></tr></thead>
            <tbody>{q.data.revenue.map((x, i) => <tr key={i}><td className="small">{x.record_type === "RECORDING_USAGE" ? "Usage" : "Revenue"}</td><td className="small"><a href={`#/statements/${x.statement_id}`}>#{x.statement_id}</a></td><td className="num">{x.source_row_number}</td>
              <td>{x.platform_name}</td><td className="nowrap">{mon(x.month)}</td><td className="mono">{x.isrc}</td><td className="small">{x.reported_title}</td>
              <td><MappingPill status={x.mapping_status} /></td><td className="num">{x.record_type === "RECORDING_USAGE" ? <span className="blank">—</span> : <Amount v={x.amount} missing="blank" />}</td>
              <td className="num">{x.plays != null ? int(Number(x.plays)) : <span className="blank">—</span>}</td></tr>)}</tbody>
          </table></div>)}
        <h2>Per-work lines ({q.data.royalty.length})</h2>
        {q.data.royalty.length === 0 ? <p className="muted">No per-work line in this selection.</p> : (
          <div className="tbl-wrap short"><table className="tbl">
            <thead><tr><th>Side</th><th>Statement</th><th>Row</th><th>Category</th><th>Distribution</th><th>Period</th><th>Party</th><th className="num">Coll %</th><th className="num">Amount</th></tr></thead>
            <tbody>{q.data.royalty.map((x, i) => <tr key={i}><td className="small">{x.statement_source === "IPRS" ? "IPRS paid" : "Client statement"}</td><td className="small"><a href={`#/statements/${x.statement_id}`}>#{x.statement_id}</a></td><td className="num">{x.source_row_number}</td>
              <td className="small">{x.category}</td><td>{x.statement_reference}</td><td className="small nowrap">{period(x.usage_period_start, x.usage_period_end)}</td>
              <td className="small">{x.party_name} ({x.role})</td><td className="num">{x.collection_share}</td><td className="num"><Money v={x.amount} /></td></tr>)}</tbody>
          </table></div>)}
        <div className="actions end"><Button onClick={onWork}>Open the work in the catalogue</Button><Button onClick={onClose}>Close</Button></div>
      </div>}
    </Dialog>
  );
}

function Unmatched({ cid, f, setF }: { cid: number; f: F; setF: (f: F) => void }) {
  const p = params(cid, f);
  const q = useQuery({ queryKey: ["unmatched", p], queryFn: () => api.get<{ revenue: any[]; royalty: any[] }>(`/master/unmatched${qs({ client_id: cid, platform_id: f.platform_id, period_from: p.period_from, period_to: p.period_to })}`) });
  const pl = useQuery({ queryKey: ["platforms"], queryFn: () => api.get<{ platforms: { id: number; platform_name: string }[] }>("/platforms") });
  const v = pl.data ? ({ platforms: pl.data.platforms.map((x) => ({ id: x.id, name: x.platform_name })) } as unknown as View) : undefined;
  const set = (k: keyof F, val: string) => setF({ ...f, [k]: val });
  return (
    <>
      <Card><Filters f={f} set={set} v={v} onReset={() => setF(MASTER_FILTERS)} /></Card>
      <Card title="Per-ISRC lines whose ISRC reaches no work">
        {!q.data ? <Loading /> : q.data.revenue.length === 0 ? <Empty title="Nothing unmatched" /> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Side</th><th>ISRC</th><th>Title in the report</th><th>Platform</th><th>Why</th><th>Months</th><th className="num">Lines</th><th className="num">Amount</th></tr></thead>
            <tbody>{q.data.revenue.map((x, i) => <tr key={i}><td className="small">{x.statement_source === "PLATFORM" ? "Platform report" : x.statement_source === "IPRS" ? "IPRS" : "Client"}</td><td className="mono">{x.isrc ?? "—"}</td><td>{x.title}</td><td>{x.platform_name}</td>
              <td><MappingPill status={x.mapping_status} />{x.claimed_by?.length > 0 && <div className="muted small">claimed by {x.claimed_by.join(", ")}</div>}</td>
              <td className="small nowrap">{period(x.first_month, x.last_month)}</td><td className="num">{int(x.lines)}</td><td className="num"><Amount v={x.amount} /></td></tr>)}</tbody>
          </table></div>)}
      </Card>
      <Card title="Per-work lines for works not in the catalogue">
        {!q.data ? <Loading /> : q.data.royalty.length === 0 ? <Empty title="Nothing unmatched" /> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Side</th><th>Work number</th><th>Title</th><th>Platform / category</th><th className="num">Lines</th><th className="num">Amount</th></tr></thead>
            <tbody>{q.data.royalty.map((x, i) => <tr key={i}><td className="small">{x.statement_source === "IPRS" ? "IPRS statement" : "Client statement"}</td><td className="mono">{x.internal_work_number ?? "none"}</td><td>{x.title}</td><td>{x.platform_name}</td>
              <td className="num">{int(x.lines)}</td><td className="num"><Money v={x.amount} /></td></tr>)}</tbody>
          </table></div>)}
      </Card>
    </>
  );
}
