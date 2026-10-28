import { useState, type CSSProperties } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { NUMBER_PATTERN, int, mon, numeric } from "../format";
import { useApp } from "../session";
import { Amount, ClientSelect, Facts, FormDialog, MappingPill, NeedClient, Pager, Pct, ResetFilters, Selection, changed, monthEnd, monthStart, period, freeze } from "../parts";
import { Button, Card, Dialog, DownloadButton, Empty, Loading, Money, More, Notice, Page, Pill, ScrollX, Select, day, when, type Tone } from "../ui";
import { AddWork, WorkDialog, WorkNumberField, type FoundWork } from "./Catalogue";

const MISSING = "No corresponding IPRS entry found in the statements uploaded.";
type Setting = { id: number; benchmark_percentage: string; client_share_pct: string | null; revenue_basis: string; note: string | null; platform_id: number | null };
type StRef = { id: number; reference: string | null; filename: string; layout: string; period_start: string | null; period_end: string | null; total: string | null; usage: string | null };
type Plat = { platform_id: number; platform: string; ready: boolean; year_ready: boolean; status: "READY" | "NO_REVENUE" | "NO_IPRS" | "NO_OVERLAP" | "YEAR_ONLY";
  iprs: StRef[]; platform_reports: StRef[];
  years: { fy: number; label: string; platform_months: number; iprs_months: number; common_months: number }[];
  revenue_months: [string, string] | null; usage_months: [string, string] | null; setting: Setting | null; own_setting: boolean;
  revenue_month_list: string[]; usage_month_list: string[]; available: { iprs: string[]; revenue: string | null; usage: string | null };
  suggestions: { period_start: string; period_end: string; iprs_statement: string; revenue_months: number; months: number; complete: boolean; usage_months: number }[] };
type Options = { platforms: Plat[]; settings: Setting | null;
  others: { category: string; record_type: string; statement_source: string; statements: number }[] };

/** The server's 'Jan 2026 - Mar 2026' with the dash used on screen. */
const dash = (t: string) => t.replace(/ - /g, " – ");
/** Months (ISO dates) in words: 'Jan 2026 – Mar 2026', with a comma between runs of months that do not meet. */
function monthsText(ms: string[]): string {
  const ks = Array.from(new Set(ms.map((m) => m.slice(0, 7)))).sort();
  const n = (k: string) => Number(k.slice(0, 4)) * 12 + Number(k.slice(5, 7));
  const out: string[] = [];
  for (let i = 0; i < ks.length; ) {
    let j = i;
    while (j + 1 < ks.length && n(ks[j + 1]) === n(ks[j]) + 1) j++;
    out.push(period(ks[i], ks[j]));
    i = j + 1;
  }
  return out.join(", ");
}

/** '7 %'; the client share is 100 % while it is not set (the revenue reported is the total). */
const pct = (v: string | number | null | undefined) => `${Number(v)} %`;
const shareOf = (s: Setting | null | undefined) => (s?.client_share_pct ? Number(s.client_share_pct) : null);

const PLAT_STATUS: Record<Plat["status"], [Tone, string, string]> = {
  READY: ["good", "Ready", "The platform revenue and IPRS's statements cover the same months"],
  YEAR_ONLY: ["info", "Yearly only", "They share some months of a financial year, but no IPRS usage period is fully covered"],
  NO_REVENUE: ["warn", "No platform report", "Only IPRS statements: upload the platform's revenue report under Statements → Platform reports"],
  NO_IPRS: ["warn", "No IPRS statement", "Upload the statement received from IPRS under Statements → IPRS statements"],
  NO_OVERLAP: ["warn", "Periods do not meet", "Both are uploaded, but not for the same months"],
};
/** Only a platform with both its revenue report and an IPRS statement can be reconciled (and is offered). */
const both = (x: Plat) => !!x.revenue_months && x.iprs.length > 0;
const months = (n: number) => `${n} month${n === 1 ? "" : "s"}`;
const fyOf = (iso: string) => { const [y, m] = iso.split("-").map(Number); return m >= 4 ? y : y - 1; };
const runPeriod = (r: { run_kind?: string; usage_period_start: string; usage_period_end: string }) =>
  r.run_kind === "YEAR" ? `FY ${fyOf(r.usage_period_start)}-${String(fyOf(r.usage_period_start) + 1).slice(2)} (yearly)` : period(r.usage_period_start, r.usage_period_end);
type RunRow = { id: number; run_reference: string; run_kind: string; usage_period_start: string; usage_period_end: string; platform_name: string; started_at: string;
  started_by: string; benchmark_percentage: string; client_interest_pct: string | null; client_share_pct: string | null; summary: Summary;
  review?: { items: number; reviewed: number; needs_info: number; by?: string[] | null }; verified_by?: string | null; verified_at?: string | null };
type Summary = { items: number; works: number; calculated: number; compared: number; missing_iprs: number; unmatched_recordings: number; unmatched_works: number;
  previous_revenue?: string; previous_iprs?: string; compared_months?: number; base?: "PLATFORM" | "CLIENT";
  underpaid?: number; shortfall?: string; usage?: string | null; usage_unmatched?: string | null; client_matched?: string | null; client_differences?: number;
  iprs_compared?: string; revenue_compared?: string; total_compared?: string; no_platform_revenue?: number; eligible?: string;
  revenue_matched: string; revenue_unmatched: string; iprs_matched: string; iprs_unmatched: string; reference: string; positive_variance: string;
  exceptions: Record<string, number>; comparable: boolean; basis_ok: boolean; currency: string | null };

export default function Reconciliation({ runId }: { runId?: number }) {
  return <NeedClient>{(cid) => (runId ? <RunPage runId={runId} cid={cid} /> : <Start cid={cid} />)}</NeedClient>;
}

// ================================================================== start a run
function Start({ cid }: { cid: number }) {
  const { me, go, toast } = useApp();
  const opt = useQuery({ queryKey: ["recon-options", cid], queryFn: () => api.get<Options>(`/reconciliation/options${qs({ client_id: cid })}`) });
  const runs = useQuery({ queryKey: ["recon-runs", cid], queryFn: () => api.get<RunRow[]>(`/reconciliation/runs${qs({ client_id: cid })}`) });
  const [pid, setPid] = useState("");
  const [mode, setMode] = useState<"PERIOD" | "YEAR">("PERIOD");
  const [fy, setFy] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const o = opt.data;
  const choices = o?.platforms.filter(both) ?? [];
  const p = choices.find((x) => String(x.platform_id) === pid) ?? choices.find((x) => x.ready) ?? choices[0];
  const shown = p?.suggestions.filter((g) => g.revenue_months > 0) ?? [];      // IPRS periods the platform revenue meets
  const hidden = (p?.suggestions.length ?? 0) - shown.length;
  const s = p?.setting ?? o?.settings;
  const share = shareOf(s);
  return (
    <Page title="Reconciliation" intro={<>Compares the platform's revenue (e.g. Spotify) with what IPRS paid for the same period, song by song. Each enquiry number has a distinct set of data:
      if a work's data for a period is covered in one report, it is not repeated in another report for the same period - a single source of data for every work.</>}>
      <Card><ClientSelect label="Client to reconcile" /></Card>
      <div id="run-recon" className="anchor" />
      <Card title="Run a reconciliation">
        {!o ? <Loading /> : choices.length === 0 ? (
          <Empty title="Nothing to reconcile yet">A platform is offered here once both its revenue report and an IPRS statement are uploaded under <a href="#/statements/platform">Statements</a> (one tab each), in any order.</Empty>
        ) : (
          <form className="form" onSubmit={async (e) => {
            e.preventDefault();
            if (!p || (mode === "PERIOD" ? !from || !to : !fy)) return;
            setBusy(true);
            try {
              const r = await api.post<{ run: { id: number } }>("/reconciliation/runs", mode === "YEAR"
                ? { client_id: cid, platform_id: p.platform_id, mode, fy: Number(fy) }
                : { client_id: cid, platform_id: p.platform_id, mode, period_from: monthStart(from), period_to: monthEnd(to) });
              go(`reconciliation/${r.run.id}`);
            } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
          }}>
            <label className="field">Platform
              <Select value={p ? String(p.platform_id) : ""} onChange={(v) => { setPid(v); setFrom(""); setTo(""); setFy(""); }}
                      options={choices.map((x) => ({ value: String(x.platform_id), label: x.platform, tone: PLAT_STATUS[x.status][0],
                        meta: `${x.platform_reports.length} platform · ${x.iprs.length} IPRS`, hint: PLAT_STATUS[x.status][2] }))} />
            </label>
            {p && <div className="box small">
              <b>Available for {p.platform}</b>
              <Facts items={[["Statements from IPRS", p.available.iprs.length ? p.available.iprs.map(dash).join(", ") : "none"],
                [`Revenue from ${p.platform}`, p.available.revenue ? dash(p.available.revenue) : "none"],
                [`Usage from ${p.platform}`, p.available.usage ? dash(p.available.usage) : "no usage report"]]} />
            </div>}
            <div className="field"><span>Compare by</span>
              <div className="seg" role="radiogroup" aria-label="Compare by">
                {([["PERIOD", "Months"], ["YEAR", "A financial year (with the year before)"]] as const).map(([k, l]) => (
                  <button key={k} type="button" role="radio" aria-checked={mode === k} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>{l}</button>))}
              </div>
            </div>
            {p && mode === "YEAR" && (
              <div className="field"><span>Financial year (1 Apr – 31 Mar)</span>
                {p.years.length === 0 ? <p className="muted small">No statement of this platform states a usage period yet.</p> : (
                  <div className="chips">
                    {p.years.map((y) => (
                      <button key={y.fy} type="button" className={`chip ${fy === String(y.fy) ? "on" : ""}`} onClick={() => setFy(String(y.fy))}>
                        <b>{y.label}</b>
                        <span className="small">{p.platform} revenue: {y.platform_months} of 12 months</span>
                        <span className="small">IPRS statements: {y.iprs_months} of 12 months</span>
                        <span className={`small ${y.common_months ? "good-t" : "warn-t"}`}>{y.common_months ? `${months(y.common_months)} in both - these are compared` : "no month in both yet"}</span>
                      </button>))}
                  </div>)}
                {fy && <p className="compare-line">Compares <b>{p.platform} revenue</b> with <b>what IPRS paid</b> for the months of FY {fy}-{String(Number(fy) + 1).slice(2)} that both cover, beside the same months a year before.</p>}
              </div>
            )}
            {p && mode === "PERIOD" && (
              <div className="field"><span>Which months to compare?</span>
                <span className="muted small">{p.platform}'s revenue for the months the songs were played is compared with what IPRS paid for the same months.
                  Pick the months of an IPRS statement below, or choose the months yourself.</span>
                {shown.length > 0 && <div className="chips">
                  {shown.map((g) => (
                    <button key={g.period_start + g.period_end} type="button" className={`chip ${from === g.period_start.slice(0, 7) && to === g.period_end.slice(0, 7) ? "on" : ""}`}
                            onClick={() => { setFrom(g.period_start.slice(0, 7)); setTo(g.period_end.slice(0, 7)); }}>
                      <b>{period(g.period_start, g.period_end)} <span className="muted small">({months(g.months)})</span></b>
                      <span className="small">IPRS statement: {g.iprs_statement}</span>
                      <span className={`small ${g.complete ? "good-t" : "warn-t"}`}>{p.platform} revenue: {g.complete ? `all ${months(g.months)}` : `only ${g.revenue_months} of ${g.months} months`}</span>
                      <span className="small muted">{p.platform} plays: {g.usage_months === g.months ? `all ${months(g.months)}` : g.usage_months ? `${g.usage_months} of ${g.months} months` : "none"}</span>
                    </button>))}
                </div>}
                {hidden > 0 && <span className="muted small">{hidden === 1 ? "One IPRS statement period is" : `${hidden} IPRS statement periods are`} not shown: no {p.platform} revenue is uploaded for {hidden === 1 ? "its" : "their"} months
                  ({p.suggestions.filter((g) => !g.revenue_months).map((g) => period(g.period_start, g.period_end)).join(", ")}).</span>}
                <span className="period-pick">
                  <label className="field inline">From month<input className="input sm" type="month" required value={from} onChange={(e) => setFrom(e.target.value)} /></label>
                  <label className="field inline">To month<input className="input sm" type="month" required value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label>
                </span>
                {from && to && to >= from && (() => {
                  const um = p.usage_month_list.filter((m) => m.slice(0, 7) >= from && m.slice(0, 7) <= to);
                  return <p className="compare-line">Works: compares <b>{p.platform} revenue for {period(from, to)}</b> with <b>what IPRS paid for the same months</b>.
                    <br />Usage: {um.length ? <>compares <b>{monthsText(um)}</b> only - the months with {p.platform} usage.</> : <>no {p.platform} usage report for these months.</>}</p>;
                })()}
              </div>
            )}
            <div className="box small">
              <b>Calculation basis{p ? ` for ${p.platform}` : ""}</b> (Settings → Reconciliation)
              <Facts items={[["IPRS % (expected from IPRS)", s ? `${pct(s.benchmark_percentage)} of each song's total revenue${p?.own_setting ? ` (set for ${p.platform})` : " (client-wide value)"}` : "not set"],
                ["Client share", share ? `${pct(share)} - the ${p?.platform ?? "platform"} revenue is the client's share, so the total revenue = revenue ÷ ${pct(share)}`
                  : "not set - the revenue reported counts as the total (100 %)"],
                ["Revenue basis", s ? s.revenue_basis.toLowerCase() : ""]]} />
            </div>
            <div className="actions"><Button kind="primary" className="big" type="submit" busy={busy} disabled={!me.can.prepare || (mode === "PERIOD" ? !from || !to : !fy)}>Run reconciliation</Button></div>
          </form>
        )}
      </Card>
      <Card title="Earlier reconciliations">
        {!runs.data ? <Loading /> : runs.data.length === 0 ? <p className="muted">None yet.</p> : (
          <ScrollX label="Earlier reconciliations"><table className="tbl">
            <thead><tr><th>Reference</th><th>Platform</th><th>Months compared</th><th className="num">Works compared</th><th className="num">Underpaid</th><th className="num">Shortfall</th><th className="num">No IPRS entry</th><th className="num">Unmatched</th><th>IPRS % · client share</th><th>Review</th><th>Run</th></tr></thead>
            <tbody>{runs.data.map((r) => (
              <tr key={r.id} className="click" onClick={() => go(`reconciliation/${r.id}`)}>
                <td><b>{r.run_reference}</b></td><td>{r.platform_name}</td><td className="nowrap">{runPeriod(r)}</td>
                <td className="num">{int(r.summary.compared)}</td>
                <td className="num">{r.summary.underpaid != null ? <span className={r.summary.underpaid ? "under-t" : ""}>{int(r.summary.underpaid)}</span> : <span className="blank">—</span>}</td>
                <td className="num">{r.summary.shortfall != null && Number(r.summary.shortfall) > 0 ? <Money v={r.summary.shortfall} /> : <span className="blank">—</span>}</td>
                <td className="num">{int(r.summary.missing_iprs)}</td>
                <td className="num">{int(r.summary.unmatched_recordings + r.summary.unmatched_works)}</td>
                <td className="small nowrap">{pct(r.benchmark_percentage)}{r.client_share_pct ? ` · ${pct(r.client_share_pct)}` : r.client_interest_pct ? ` × ${pct(r.client_interest_pct)} interest` : ""}</td>
                <td className="small nowrap"><ReviewProgress v={r.review} />
                  <div>{r.verified_by ? <span className="good-t">✓ Verified by {r.verified_by} · {day(r.verified_at!)}</span> : <span className="muted">Not verified</span>}</div></td>
                <td className="small nowrap">{when(r.started_at)} · {r.started_by}</td>
              </tr>))}</tbody>
          </table></ScrollX>
        )}
      </Card>
      {o && <Platforms o={o} onPick={(id) => { setPid(String(id)); setFrom(""); setTo(""); setFy(""); document.getElementById("run-recon")?.scrollIntoView({ behavior: "smooth", block: "start" }); }} />}
    </Page>
  );
}

/** How far the review of a run's items has got: complete once every item is marked reviewed. */
function ReviewProgress({ v }: { v?: { items: number; reviewed: number; needs_info: number; by?: string[] | null } }) {
  if (!v || !v.items) return <span className="muted">—</span>;
  if (!v.reviewed && !v.needs_info) return <span className="muted">Not reviewed</span>;
  const done = v.reviewed >= v.items;
  return <>{done ? <Pill tone="good">✓ Reviewed</Pill> : <>{int(v.reviewed)} of {int(v.items)} reviewed</>}
    {v.by && v.by.length > 0 && <div>by {v.by.join(", ")}</div>}
    {v.needs_info > 0 && <div className="warn-t">{int(v.needs_info)} need{v.needs_info === 1 ? "s" : ""} information</div>}</>;
}

/** The second check: whoever ran the reconciliation, another person verifies it once (recorded with name and time). */
function Verification({ runId, v, onDone }: { runId: number; v: RunView["verification"]; onDone: (x: RunView) => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  return (
    <div className={`verify-line ${v.by ? "ok" : ""}`}>
      <span>Reconciled by <b>{v.ran_by}</b> · {when(v.ran_at)}</span>
      {v.by ? <span className="good-t">✓ Verified by <b>{v.by}</b> · {when(v.at!)}{v.note ? ` - ${v.note}` : ""}</span>
        : <span className="muted">Not verified yet: a second person (not {v.ran_by}) checks it once before the verified works are emailed to IPRS.</span>}
      {v.can_verify && <Button kind="primary" className="sm" onClick={() => setOpen(true)}>Verify this reconciliation</Button>}
      {open && <FormDialog title="Verify this reconciliation" submit="Verify" onClose={() => setOpen(false)}
                           onSubmit={async () => { onDone(await api.post<RunView>(`/reconciliation/runs/${runId}/verify`, { note })); }}>
        <p>You checked the reconciliation {v.ran_by} ran. Your name and the time are recorded on it and in the activity log; the figures do not change.</p>
        <label className="field">Note (optional)<textarea className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
      </FormDialog>}
    </div>
  );
}

/** Every platform in the client's statements, with what each kind covers, so it is clear what can be reconciled. */
function Platforms({ o, onPick }: { o: Options; onPick: (platformId: number) => void }) {
  const span = (xs: { period_start: string | null; period_end: string | null }[]) => {
    const a = xs.map((x) => x.period_start).filter(Boolean).sort()[0];
    const b = xs.map((x) => x.period_end).filter(Boolean).sort().slice(-1)[0];
    return a && b ? period(a, b) : xs.length ? "period not stated" : "";
  };
  const side = (xs: StRef[]) => xs.length ? <>{int(xs.length)} · {span(xs)}{xs.some((i) => !i.period_start) && <div className="muted">{xs.filter((i) => !i.period_start).length} without a usage period (never used)</div>}</> : <span className="muted">—</span>;
  return (
    <Card title={`Platforms in this client's statements (${o.platforms.length})`}>
      {o.platforms.length === 0 ? <Empty title="No platform yet">Upload statements under <a href="#/statements/platform">Statements</a>.</Empty> : (
        <ScrollX label="Platforms"><table className="tbl">
          <thead><tr><th>Platform</th><th>Platform reports</th><th>IPRS statements</th>
            <th>IPRS % · client share</th><th>Can it be reconciled?</th><th></th></tr></thead>
          <tbody>{o.platforms.map((x) => {
            const [tone, text, why] = PLAT_STATUS[x.status];
            return (
              <tr key={x.platform_id}>
                <td><b>{x.platform}</b></td>
                <td className="small">{x.platform_reports.length ? <>{x.revenue_months ? <>revenue {period(x.revenue_months[0], x.revenue_months[1])}</> : <span className="muted">no revenue</span>}
                  <div className="muted">{x.usage_months ? `usage ${period(x.usage_months[0], x.usage_months[1])}` : "no usage report"}</div></> : <span className="muted">—</span>}</td>
                <td className="small">{side(x.iprs)}</td>
                <td className="small nowrap">{x.setting ? `${pct(x.setting.benchmark_percentage)} · ${shareOf(x.setting) ? pct(shareOf(x.setting)) : "100 % (not set)"}` : "not set"}{x.own_setting && <div className="muted">own values</div>}</td>
                <td><Pill tone={tone}>{text}</Pill><div className="muted small">{why}</div></td>
                <td className="num">{both(x) && <Button kind={x.ready || x.year_ready ? "primary" : "ghost"} className="sm" onClick={() => onPick(x.platform_id)}>Choose</Button>}</td>
              </tr>);
          })}</tbody>
        </table></ScrollX>
      )}
      {o.others.length > 0 && (
        <More label={`Statements without a platform (${o.others.reduce((a, x) => a + x.statements, 0)}) - not reconciled`}>
          <ul className="plain small">{o.others.map((x) => <li key={x.category + x.statement_source + x.record_type}>{x.category}: {int(x.statements)} {x.statement_source === "IPRS" ? "IPRS statement" : x.statement_source === "PLATFORM" ? "platform report" : "client statement"}{x.statements === 1 ? "" : "s"}</li>)}</ul>
        </More>
      )}
    </Card>
  );
}

// ================================================================== one run
type PCol = { key: string; start: string; end: string; label: string; refs: string[] };
type Snap = { id: number; file: string };
type RunView = { run: RunRow & { notes: string[]; status: string; revenue_basis: string; client_name: string; client_code: string; started_by_name: string;
  compared_months: string[] | null; previous_period_start: string | null; previous_period_end: string | null;
  source_snapshot: { revenue_statements: Snap[]; iprs_statements: Snap[]; platform_reports?: Snap[]; client_statements?: Snap[]; base?: string }; source_snapshot_sha256: string };
  exceptions: { type: string; label: string; open: number; reviewed: number; closed: number; items: number }[]; later_statements: { statements: [number, string][]; items: number };
  reviewed: { reviewed: number; needs_info: number; items: number; by: string[] | null };
  verification: { ran_by: string; ran_at: string; by: string | null; at: string | null; note: string | null; can_verify: boolean }; labels: { exceptions: Record<string, string>; calc: Record<string, string>; kinds: Record<string, string>;
    review: Record<string, string>; mapping: Record<string, string>; run_kind: Record<string, string> };
  periods: { source: PCol[]; iprs: PCol[]; usage?: PCol[]; client?: PCol[] }; blocks?: Block[];
  usage: { months: string[]; start: string; end: string; label: string; all_months: boolean; split_text: string | null } | null;
  available: { iprs: string[]; revenue: string | null; usage: string | null; works: string } };
/** The Usage tab's figures for the works listed (the months with platform usage only). */
type UsageTotals = { songs: number; compared: number; revenue: string; total: string; expected: string; received: string; received_pct: string | null;
  variance_pct: string | null; underpaid: number; shortfall: string; plays: string | null };
type Block = { key: string; side: "PLATFORM" | "CLIENT" | "IPRS"; statement_id: number; file: string; reference: string; date: string;
  period_start: string | null; period_end: string | null; period_label: string; usage_label: string };

/** The run's bands, as in the master and the Excel report: [header fill, row tint]. */
const BAND: Record<string, [string, string]> = { SOURCE: ["#D8E9A8", "#F4F9E6"], USAGE: ["#D6E4DA", "#F1F6F2"], CLIENT: ["#E8DDC8", "#FAF6EE"],
  IPRS: ["#CFDCCB", "#EFF4EE"], CALC: ["#E6E1D3", "#F8F6F0"], YOY: ["#D3E0E6", "#EEF3F6"], STATUS: ["#DCD6CC", "#F6F4F0"] };
const fill = (k: string) => ({ "--fill": BAND[k][0] }) as CSSProperties;
const tint = (k: string) => ({ "--tint": BAND[k][1] }) as CSSProperties;
type Item = { id: number; item_no: number; item_kind: string; work_id: number | null; internal_work_number: string | null; work_title: string | null; isrcs: string[];
  sound_recording_revenue: string | null; revenue_lines: number; eligible_revenue_basis: string | null; client_interest_share: string | null; client_share_pct: string | null;
  iprs_client_share: string | null; benchmark_percentage: string | null; reference_benchmark_amount: string | null; iprs_royalty_amount: string | null;
  iprs_lines: number; observed_percentage: string | null; indicative_variance: string | null; mapping_status: string; data_validation_status: string;
  calculation_status: string; exception_status: string; later_statement_status: string; review_status: string; recommended_action: string;
  reviewed_by_name?: string | null; reviewed_at?: string | null;
  open_exceptions: string[]; later_statements: { id: number; filename: string }[]; enquiry: { id: number; reference: string; status: string } | null;
  platform_id: number; previous_revenue: string | null; previous_iprs_royalty: string | null;
  usage_plays: string | null; usage_lines: number; client_statement_amount: string | null; client_statement_lines: number; client_iprs_difference: string | null;
  periods: { source: Record<string, string>; iprs: Record<string, string>; usage?: Record<string, string>; client?: Record<string, string> };
  blocks?: Record<string, { amount: string | null; lines: number; usage: string | null }>; variance_pct?: string | null; iprs_split?: boolean;
  held?: string | null };

/** Year-on-year change in per cent; blank when either year has no amount. */
function Change({ cur, old }: { cur: string | null; old: string | null }) {
  if (cur === null || old === null || Number(old) === 0) return <span className="blank">—</span>;
  const c = (Number(cur) - Number(old)) / Number(old) * 100;
  return <span className={`num ${c < 0 ? "bad-t" : "good-t"}`}>{c > 0 ? "+" : ""}{c.toFixed(1)} %</span>;
}

/** Plays: a whole number; blank (never 0) when there is no usage report. */
function Plays({ v }: { v: string | null | undefined }) {
  return v == null ? <span className="blank">—</span> : <span className="num">{int(Number(v))}</span>;
}

const CALC_TONE: Record<string, Tone> = { CALCULATED: "good", NOT_CALCULATED: "warn", NOT_COMPARABLE: "neutral" };
const REVIEW_TONE: Record<string, Tone> = { UNREVIEWED: "neutral", REVIEWED: "good", NEEDS_INFO: "warn" };
const under = (i: Item) => i.indicative_variance !== null && Number(i.indicative_variance) > 0.005;

/** Can this item go into a query to IPRS (same rule as the server's why_not_query)? Every properly matched work of the
 *  Works tab: link verified and work active in the Catalogue (held = why not, judged on the catalogue now). */
function eligible(i: Item): boolean {
  return i.item_kind === "WORK" && !i.enquiry && !i.held;
}

const RUN_FILTERS = { kind: "WORK", view: "", exception: "", mapping: "", calc: "", review: "", q: "", sort: "title", variance: "" };
const VARIANCE = [{ value: "", label: "Any result" }, { value: "underpaid", label: "Underpaid by IPRS" },
  { value: "client_diff", label: "Client statement ≠ IPRS paid" }];

function RunPage({ runId, cid }: { runId: number; cid: number }) {
  const { me, go, toast } = useApp();
  const qc = useQueryClient();
  const [f, setF] = useState(RUN_FILTERS);
  const [offset, setOffset] = useState(0);
  // ticked items by id (they can span pages); 'elig' = ticked ids that can go into an enquiry; 'known' = rows seen
  const [ticked, setTicked] = useState<Set<number>>(() => new Set());
  const [elig, setElig] = useState<Set<number>>(() => new Set());
  const [known, setKnown] = useState<Record<number, Item>>({});
  const [allBusy, setAllBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [draft, setDraft] = useState(false);
  const [left, setLeft] = useState(0);                   // works of the Works tab left out of the query (not properly matched)
  const [bulk, setBulk] = useState<string | null>(null);
  const rv = useQuery({ queryKey: ["recon-run", runId], queryFn: () => api.get<RunView>(`/reconciliation/runs/${runId}`) });
  const items = useQuery({ queryKey: ["recon-items", runId, f, offset], placeholderData: (x) => x,
    queryFn: () => api.get<{ rows: Item[]; total: number; blocks?: Block[]; usage?: UsageTotals }>(`/reconciliation/runs/${runId}/items${qs({ ...f, offset })}`) });
  if (rv.isError) return <Page title="Reconciliation"><Notice tone="bad">{(rv.error as Error).message}</Notice></Page>;
  if (!rv.data) return <Loading />;
  const r = rv.data.run;
  const s = r.summary;
  const yearly = r.run_kind === "YEAR";
  const L = rv.data.labels;
  const bench = Number(r.benchmark_percentage);
  const share = r.client_share_pct === null ? null : Number(r.client_share_pct);   // null: a run before 1.6.0
  const platformRun = (s.base ?? r.source_snapshot.base ?? "PLATFORM") === "PLATFORM" && !!r.source_snapshot.platform_reports;
  const hasCli = (rv.data.blocks ?? []).some((b) => b.side === "CLIENT");            // runs before 1.6.0 only
  const clearSel = () => { setTicked(new Set()); setElig(new Set()); };
  const set = (k: string, v: string) => { setF({ ...f, [k]: v }); setOffset(0); if (k !== "sort") clearSel(); };
  const tab = (kind: string, view: string) => { setF({ ...f, kind, view }); setOffset(0); clearSel(); };
  const uv = rv.data.usage;                                 // the Usage tab: the months with platform usage
  const av = rv.data.available;
  const rows = items.data?.rows ?? [];
  const total = items.data?.total ?? 0;
  const pageAll = rows.length > 0 && rows.every((i) => ticked.has(i.id));
  const pageSome = rows.some((i) => ticked.has(i.id));
  const mark = (list: Item[], on: boolean) => {
    setKnown((k) => { const n = { ...k }; list.forEach((i) => { n[i.id] = i; }); return n; });
    setTicked((t) => { const n = new Set(t); list.forEach((i) => (on ? n.add(i.id) : n.delete(i.id))); return n; });
    setElig((t) => { const n = new Set(t); list.forEach((i) => (on && eligible(i) ? n.add(i.id) : n.delete(i.id))); return n; });
  };
  const togglePage = (on: boolean) => mark(rows, on);
  const toggle = (i: Item, on: boolean) => mark([i], on);
  const tickAll = async () => {                            // every item that matches the filters, on every page
    setAllBusy(true);
    try {
      const x = await api.get<{ ids: number[]; eligible: number[]; total: number }>(`/reconciliation/runs/${runId}/item-ids${qs({ ...f, sort: undefined })}`);
      setTicked(new Set(x.ids));
      setElig(new Set(x.eligible));
    } catch (e) { toast((e as Error).message, true); } finally { setAllBusy(false); }
  };
  const raiseQuery = async () => {                         // every work that can go into a query, whatever the filters
    setAllBusy(true);
    try {
      const x = await api.get<{ ids: number[]; eligible: number[]; held: number; enquired: number }>(`/reconciliation/runs/${runId}/item-ids${qs({ kind: "WORK" })}`);
      if (!x.eligible.length) {
        toast(`No work in this run can go into a query: ${[x.enquired && `${int(x.enquired)} already in an enquiry`, x.held && `${int(x.held)} wait for the Catalogue check (link not verified or work to review)`].filter(Boolean).join(", ") || "the Works tab is empty"}.`, true);
        return;
      }
      setLeft(x.held);
      const top = await api.get<{ rows: Item[] }>(`/reconciliation/runs/${runId}/items${qs({ kind: "WORK", variance: "underpaid", sort: "variance" })}`);
      setKnown((k) => { const n = { ...k }; top.rows.forEach((i) => { n[i.id] = i; }); return n; });
      setTicked(new Set(x.eligible));
      setElig(new Set(x.eligible));
      setDraft(true);
    } catch (e) { toast((e as Error).message, true); } finally { setAllBusy(false); }
  };
  const sel = Array.from(ticked);
  const selEnq = sel.filter((id) => elig.has(id));
  const allTicked = total > 0 && sel.length >= total;
  const exportParams = { kind: f.kind, view: f.view, exception: f.exception, mapping: f.mapping, calc: f.calc, review: f.review, q: f.q, variance: f.variance, sort: f.sort };
  const snapList = (xs: Snap[] | undefined, what: string) => (xs ?? []).map((x) => <li key={what + x.id}>{what}: <a href={`#/statements/${x.id}`}>#{x.id} {x.file}</a></li>);
  // received % of the total revenue of the works compared, and the variance % = IPRS % - received % (7 % - 1 % = 6 %)
  const base = Number(s.total_compared ?? s.revenue_compared ?? 0);
  const got = base > 0 && s.iprs_compared != null ? Math.round(Number(s.iprs_compared) / base * 10000) / 100 : null;
  const cm = r.compared_months?.length ?? 0;
  return (
    <Page title={`${r.platform_name} · ${runPeriod(r)}`}
          intro={yearly ? <>Compares <b>{r.platform_name} revenue</b> with <b>what IPRS paid</b> for the {cm} month{cm === 1 ? "" : "s"} of {runPeriod(r).replace(" (yearly)", "")} that both cover{r.previous_period_start ? `, beside the same months a year before (${period(r.previous_period_start, r.previous_period_end)})` : ""}.</>
            : <>Compares <b>{r.platform_name} revenue for {period(r.usage_period_start, r.usage_period_end)}</b> with <b>what IPRS paid for the same months</b>.</>}
          actions={<>
            <Button kind="ghost" onClick={() => go("reconciliation")}>All reconciliations</Button>
            {me.can.prepare && <Button busy={allBusy} onClick={raiseQuery}>Raise a query to IPRS</Button>}
            <DownloadButton kind="primary" path={`/reconciliation/runs/${runId}/report${qs(exportParams)}`} onError={(m) => toast(m, true)}>Export report</DownloadButton>
          </>}>
      <Verification runId={runId} v={rv.data.verification} onDone={(x) => { qc.setQueryData(["recon-run", runId], x); qc.invalidateQueries({ queryKey: ["recon-runs"] }); qc.invalidateQueries({ queryKey: ["overview"] }); toast("Verified."); }} />
      {r.notes.length > 0 && <Card tone="warn" title="Comparability notes"><ul className="plain">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></Card>}
      {rv.data.later_statements.statements.length > 0 && (
        <Notice tone="warn">Later IPRS statements were uploaded after this run and concern {rv.data.later_statements.items} item(s):
          {" "}{rv.data.later_statements.statements.map(([id, fn]) => <a key={id} href={`#/statements/${id}`}>{fn} </a>)}. Review them before preparing an enquiry, or run the reconciliation again.</Notice>
      )}
      <Card>
        {av && platformRun && <div className="box small avail">
          <Facts items={[["Statements from IPRS", av.iprs.length ? av.iprs.map(dash).join(", ") : "none"],
            [`Revenue from ${r.platform_name}`, av.revenue ? dash(av.revenue) : "none"],
            [`Usage from ${r.platform_name}`, av.usage ? dash(av.usage) : "no usage report for these months"]]} />
          <p className="compare-line">Works: <b>{dash(av.works)}</b> - {r.platform_name} revenue and IPRS{uv ? <> · Usage: <b>{dash(uv.label)}</b> - the months with {r.platform_name} usage</> : ""}</p>
        </div>}
        <div className="summary">
          <div><span>Works compared with IPRS</span><b>{int(s.compared)}</b></div>
          {platformRun ? <>
            <div><span>[Platform] Revenue on catalogue works{share !== null && share !== 100 ? ` (the client's ${share} % share)` : ""}</span><b><Money v={s.revenue_matched} /></b></div>
            {share !== null && share !== 100 && <div><span>[Calculated] Total revenue (100 %) of the calculated works</span><b>{s.calculated ? <Money v={s.eligible ?? null} /> : <span className="muted">not calculated</span>}</b></div>}
            <div><span>[Calculated] Expected ({bench} % of the {share !== null && share !== 100 ? "total " : ""}revenue)</span><b>{s.calculated ? <Money v={s.reference} /> : <span className="muted">not calculated</span>}</b></div>
            <div><span>[IPRS] Received on catalogue works</span><b><Money v={s.iprs_matched} /></b>
              {got !== null && <span className="muted small">{got.toFixed(2)} % of the {s.total_compared ? "total " : ""}revenue of the works compared</span>}</div>
            <div><span>[Calculated] Variance % ({bench} % − received %)</span><b className={got !== null && bench - got > 0.005 ? "under-t" : ""}>{got !== null ? `${(bench - got).toFixed(2)} %` : <span className="muted">not calculated</span>}</b>
              {got !== null && <span className="muted small">{bench} % expected − {got.toFixed(2)} % received</span>}</div>
            <div><span>[Calculated] Shortfall (variance amount) of the underpaid works</span><b className={Number(s.shortfall ?? 0) > 0 ? "under-t" : ""}><Money v={s.shortfall ?? null} /></b></div>
            <div><span>[Platform] Plays on catalogue works</span><b>{s.usage ? int(Number(s.usage)) : <span className="muted">no usage report</span>}</b></div>
            {s.client_matched != null && <div><span>[Client] Client statements on catalogue works</span><b><Money v={s.client_matched} /></b></div>}
            <div><span>Revenue not linked to a catalogue work</span><b><Money v={s.revenue_unmatched} /></b></div>
          </> : <>
            <div><span>[Client] Statements on catalogue works</span><b><Money v={s.client_matched ?? s.revenue_matched} /></b></div>
            <div><span>[IPRS] Paid on catalogue works</span><b><Money v={s.iprs_matched} /></b></div>
            <div><span>Client statement ≠ IPRS paid</span><b>{int(s.client_differences ?? 0)}</b></div>
          </>}
          <div><span>IPRS money not linked to a catalogue work</span><b><Money v={s.iprs_unmatched} /></b></div>
          {yearly && <div><span>Year before: revenue · IPRS paid</span><b>{s.previous_revenue == null && s.previous_iprs == null ? <span className="muted">no statements for those months</span> : <><Money v={s.previous_revenue ?? null} /> · <Money v={s.previous_iprs ?? null} /></>}</b></div>}
          <div><span>Items reviewed</span><b>{int(rv.data.reviewed.reviewed)} of {int(rv.data.reviewed.items)}{rv.data.reviewed.items > 0 && rv.data.reviewed.reviewed >= rv.data.reviewed.items && <span className="good-t"> ✓ all reviewed</span>}</b>
            {rv.data.reviewed.by && rv.data.reviewed.by.length > 0 && <span className="muted small">by {rv.data.reviewed.by.join(", ")}</span>}
            {rv.data.reviewed.needs_info > 0 && <span className="warn-t small">{int(rv.data.reviewed.needs_info)} need{rv.data.reviewed.needs_info === 1 ? "s" : ""} information</span>}</div>
        </div>
        {rv.data.exceptions.length > 0 && <>
          <h3 className="tiles-h">To review <span className="muted small">- click one to list its items</span></h3>
          <div className="tiles small-tiles">
            {rv.data.exceptions.map((e) => (
              <button key={e.type} className={`tile ${f.exception === e.type ? "on" : ""}`} onClick={() => { setF({ ...f, exception: f.exception === e.type ? "" : e.type, kind: "" }); setOffset(0); clearSel(); }}>
                <span className="tile-n">{int(e.open)}</span><span className="tile-t">{e.label}</span>
                <span className="tile-s">{e.open ? "to review" : <span className="good-t">✓ all reviewed</span>}{e.reviewed ? ` · ${int(e.reviewed)} reviewed` : ""}{e.closed ? ` · ${int(e.closed)} closed` : ""}</span>
              </button>))}
          </div></>}
      </Card>
      <Card>
        <div className="toolbar">
          <div className="seg" role="radiogroup" aria-label="Item type">
            {[["WORK", "", "Works"], ...(uv ? [["WORK", "usage", `Usage · ${dash(uv.label)}`]] : []), ["UNMATCHED_RECORDING", "", "Unmatched recordings"],
              ["UNMATCHED_WORK", "", "Works not in catalogue"], ["", "", "All"]].map(([k, v, l]) => (
              <button key={k + v} type="button" className={(v ? f.view === v : f.view !== "usage" && f.kind === k) ? "on" : ""} onClick={() => tab(k, v)}>{l}</button>))}
          </div>
          <input className="input" placeholder="Find a title, work number or ISRC" value={f.q} onChange={(e) => set("q", e.target.value)} />
          <Select size="sm" label="Result" value={f.variance} placeholder="Any result" onChange={(v) => set("variance", v)} options={VARIANCE.filter((x) => hasCli || x.value !== "client_diff")} />
          <Select size="sm" label="Calculation" value={f.calc} placeholder="Any calculation" onChange={(v) => set("calc", v)}
                  options={[{ value: "", label: "Any calculation" }, ...Object.entries(L.calc).map(([value, label]) => ({ value, label }))]} />
          <Select size="sm" label="Review" value={f.review} placeholder="Any review status" onChange={(v) => set("review", v)}
                  options={[{ value: "", label: "Any review status" }, ...Object.entries(L.review).map(([value, label]) => ({ value, label }))]} />
          <Select size="sm" label="Sort" value={f.sort} onChange={(v) => set("sort", v)}
                  options={[{ value: "title", label: "Song name, A → Z" }, { value: "revenue", label: "Most revenue first" }, { value: "variance", label: "Largest shortfall first" },
                    { value: "observed", label: "Lowest % received first" }, { value: "iprs", label: "Most received from IPRS first" }, { value: "no", label: "Item number" }]} />
          <ResetFilters active={changed(f, RUN_FILTERS)} onReset={() => { setF(RUN_FILTERS); setOffset(0); clearSel(); }} />
        </div>
        <p className="tab-note">{f.view === "usage" ? `${r.platform_name} usage reports cover 3 or 6 months: this tab maps the revenue of the same months as the usage (e.g. 3 months of usage → 3 months of revenue).`
          : f.kind === "UNMATCHED_RECORDING" || f.kind === "UNMATCHED_WORK" ? "Work for Durga verification: these are mailed to Durga to verify and correct; her corrections come back in the updated catalogue (Catalogue → Import catalogue)."
            : f.kind === "WORK" ? "Works compared with IPRS. Raise a query to IPRS sends every work of this tab that is properly matched (link verified, work active in the Catalogue); unmatched recordings and works not in the catalogue never go."
              : "Every item of the reconciliation."}</p>
        {me.can.prepare && (sel.length === 0 ? (
          <span />
        ) : (
          <div className="bulk-bar" role="region" aria-label="Ticked items">
            <b>{allTicked ? `All ${int(total)} items that match are ticked` : `${int(sel.length)} ticked`}</b>
            {!allTicked && total > rows.length && pageAll && (
              <Button kind="ghost" className="sm" busy={allBusy} onClick={tickAll}>Tick all {int(total)} items that match</Button>)}
            {allTicked && total > rows.length && <span className="muted small">on every page</span>}
            <span className="muted small">{sel.length - selEnq.length > 0 && selEnq.length > 0 ? `${int(selEnq.length)} can go into a query` : ""}</span>
            <span className="spacer" />
            <Button kind="primary" className="sm" onClick={() => setBulk("REVIEWED")}>Mark reviewed</Button>
            <Button className="sm" onClick={() => setBulk("NEEDS_INFO")}>Needs information</Button>
            <Button className="sm" onClick={() => setBulk("UNREVIEWED")}>Mark not reviewed</Button>
            <Button className="sm" disabled={!selEnq.length} title={selEnq.length ? undefined : "Only properly matched works go into a query: works of the Works tab whose link is verified and that are active in the Catalogue, not already in an enquiry"}
                    onClick={() => { setLeft(0); setDraft(true); }}>Prepare query draft ({int(selEnq.length)})</Button>
            <Button kind="ghost" className="sm" onClick={clearSel}>Clear selection</Button>
          </div>
        ))}
        <div className="queue-bar"><Selection parts={[f.view === "usage" && uv ? `Usage tab (${dash(uv.label)} only)` : f.kind ? L.kinds[f.kind] : "all items", f.exception && L.exceptions[f.exception], f.calc && L.calc[f.calc],
          f.variance && VARIANCE.find((x) => x.value === f.variance)?.label.toLowerCase(), f.review && L.review[f.review], f.q && `search '${f.q}'`]} /></div>
        {items.data?.usage && uv && (() => {
          const u = items.data.usage;
          return (
            <div className="box small usage-box">
              <b>Usage tab: {dash(uv.label)} only - the months with {r.platform_name} usage. Every figure below is for these months.</b>
              {uv.split_text && <span className="muted">{dash(uv.split_text)}</span>}
              <div className="summary">
                <div><span>Works with revenue in these months</span><b>{int(u.songs)}</b></div>
                <div><span>[Platform] Client revenue</span><b><Money v={u.revenue} /></b></div>
                {share !== null && share !== 100 && <div><span>[Calculated] Total revenue (100 %)</span><b><Money v={u.total} /></b></div>}
                <div><span>[Calculated] Expected ({bench} %)</span><b><Money v={u.expected} /></b></div>
                <div><span>[IPRS] Received</span><b><Money v={u.received} /></b>{u.received_pct != null && <span className="muted small">{Number(u.received_pct).toFixed(2)} % of the {share !== null && share !== 100 ? "total " : ""}revenue of the {int(u.compared)} works compared</span>}</div>
                <div><span>[Calculated] Variance %</span><b className={u.variance_pct != null && Number(u.variance_pct) > 0.005 ? "under-t" : ""}>{u.variance_pct != null ? `${Number(u.variance_pct).toFixed(2)} %` : <span className="muted">not calculated</span>}</b></div>
                <div><span>[Calculated] Shortfall of the {int(u.underpaid)} underpaid works</span><b className={Number(u.shortfall) > 0 ? "under-t" : ""}><Money v={u.shortfall} /></b></div>
                <div><span>[Platform] Plays</span><b>{u.plays != null ? int(Number(u.plays)) : <span className="muted">none</span>}</b></div>
              </div>
            </div>);
        })()}
        {!items.data ? <Loading /> : items.data.rows.length === 0 ? <Empty title="No item matches" /> : (() => {
          const ut = items.data.usage;                         // the Usage tab: its own blocks (usage months only)
          const blocks = items.data.blocks ?? rv.data!.blocks ?? [];
          const cli = hasCli && !ut;
          const yoy = yearly && !ut;
          const sides = (["PLATFORM", "CLIENT", "IPRS"] as const).map((k) => [k, blocks.filter((b) => b.side === k)] as const).filter(([, bs]) => bs.length > 0);
          const band: Record<string, [string, string]> = { PLATFORM: ["SOURCE", r.platform_name], CLIENT: ["CLIENT", `Client statement (${r.client_code})`], IPRS: ["IPRS", "IPRS royalty"] };
          // the check: total revenue (100 %), client revenue (the client's share as reported), expected, received, received %, variance
          const split = share !== null;                       // runs before 1.6.0 have no client share column
          const calc = platformRun ? 6 + (split ? 1 : 0) + (cli ? 1 : 0) : 2;
          const interest = r.client_interest_pct ? Number(r.client_interest_pct) : null;     // runs before 1.6.0 only
          const cell = (i: Item, b: Block) => i.blocks?.[b.key];
          return (
            <ScrollX className="sheet-wrap" label="Reconciliation items">
              <table className="skv recon-skv blocks" ref={(t) => freeze(t)}>
                <colgroup><col span={3} />{sides.map(([k, bs]) => <col key={k} span={bs.length * 4} style={tint(band[k][0])} />)}
                  <col span={calc} style={tint("CALC")} />{yoy && <col span={4} style={tint("YOY")} />}<col span={3} style={tint("STATUS")} /></colgroup>
                <thead>
                  <tr className="h1">
                    <th rowSpan={3} className="fz fz0 band-id"><span className="w-h">{me.can.prepare &&
                      <input type="checkbox" aria-label="Tick every item on this page" checked={pageAll} ref={(el) => { if (el) el.indeterminate = pageSome && !pageAll; }}
                             onChange={(e) => togglePage(e.target.checked)} />}Internal No</span></th>
                    <th rowSpan={3} className="fz fz1 band-id">Song name</th>
                    <th rowSpan={3} className="fz fz2 band-id">ISRC</th>
                    {sides.map(([k, bs]) => <th key={k} colSpan={bs.length * 4} className="band" style={fill(band[k][0])}>{band[k][1]}</th>)}
                    <th colSpan={calc} className="band" style={fill("CALC")}>{platformRun ? `Check: expected (${bench} %${split && share !== 100 ? " of total revenue" : ""}) vs paid` : "Check"}</th>
                    {yoy && <th colSpan={4} className="band" style={fill("YOY")}>{r.previous_period_start ? `Year before (${period(r.previous_period_start, r.previous_period_end)})` : "Year before"}</th>}
                    <th colSpan={3} className="band" style={fill("STATUS")}>Status and review</th>
                  </tr>
                  <tr className="h2">
                    {sides.map(([k, bs]) => bs.map((b) => [
                      <th key={b.key + "a"} rowSpan={2} className="num band" style={fill(band[k][0])}>Amount</th>,
                      k === "PLATFORM" ? <th key={b.key + "p"} colSpan={2} className="band" style={fill(band[k][0])}>Period</th>
                        : [<th key={b.key + "d"} rowSpan={2} className="band" style={fill(band[k][0])}>Date</th>,
                          <th key={b.key + "p"} rowSpan={2} className="band" style={fill(band[k][0])}>Period</th>],
                      <th key={b.key + "n"} rowSpan={2} className="band sep" style={fill(band[k][0])}>Distribution No</th>]))}
                    {platformRun && <><th rowSpan={2} className="num band" style={fill("CALC")}>{split ? "Total revenue (100 %)" : interest === null ? "Total revenue" : `Revenue counted (${interest} % client interest)`}</th>
                      {split && <th rowSpan={2} className="num band" style={fill("CALC")} title={`The revenue the platform reported: the client's ${share} % share of the total`}>Client revenue</th>}
                      <th rowSpan={2} className="num band" style={fill("CALC")}>Expected value ({bench} %)</th></>}
                    <th rowSpan={2} className="num band" style={fill("CALC")}>Received from IPRS</th>
                    {platformRun && <><th rowSpan={2} className="num band" style={fill("CALC")} title={`Received from IPRS ÷ ${split && share !== 100 ? "total revenue" : "revenue"}`}>Received %</th>
                      <th rowSpan={2} className="num band" style={fill("CALC")} title={`The difference in percentage points: ${bench} % expected − the % received`}>Variance %</th>
                      <th rowSpan={2} className={`num band ${cli ? "" : "sep"}`} style={fill("CALC")}>Variance amount</th></>}
                    {(cli || !platformRun) && <th rowSpan={2} className="num band sep" style={fill("CALC")}>Client − IPRS</th>}
                    {yoy && <><th rowSpan={2} className="num band" style={fill("YOY")}>Revenue</th><th rowSpan={2} className="num band" style={fill("YOY")}>Change</th>
                      <th rowSpan={2} className="num band" style={fill("YOY")}>IPRS paid</th><th rowSpan={2} className="num band sep" style={fill("YOY")}>Change</th></>}
                    <th rowSpan={2} className="band" style={fill("STATUS")}>Links</th><th rowSpan={2} className="band" style={fill("STATUS")}>Exceptions</th><th rowSpan={2} className="band" style={fill("STATUS")}>Review</th>
                  </tr>
                  <tr className="h3">
                    {sides.filter(([k]) => k === "PLATFORM").map(([k, bs]) => bs.map((b) => [
                      <th key={b.key + "pp"} className="band" style={fill(band[k][0])}>Period</th>,
                      <th key={b.key + "pu"} className="num band" style={fill(band[k][0])} title={`Plays the platform reported for the song in ${b.period_label}`}>Usage
                        {b.usage_label !== "plays" && <div className="muted small">{b.usage_label}</div>}</th>]))}
                  </tr>
                </thead>
                <tbody>{items.data.rows.map((i) => (
                  <tr key={i.id} className={`click ${ticked.has(i.id) ? "picked" : ""}`} onClick={() => setOpen(i.id)}>
                    <td className="fz fz0"><div className="w-t">{me.can.prepare &&
                      <input type="checkbox" aria-label={`Tick item ${i.item_no}`} checked={ticked.has(i.id)} onClick={(e) => e.stopPropagation()}
                             onChange={(e) => toggle(i, e.target.checked)} />}
                      <span className="mono">{i.internal_work_number ?? <span className="muted">{L.kinds[i.item_kind]}</span>}</span></div></td>
                    <td className="fz fz1"><div className="clip"><b title={i.work_title ?? undefined}>{i.work_title ?? (i.isrcs[0] || "No ISRC")}</b>
                      {i.enquiry && <div className="small"><a href={`#/enquiries/${i.enquiry.id}`} onClick={(e) => e.stopPropagation()}>{i.enquiry.reference}</a></div>}</div></td>
                    <td className="fz fz2 small mono" title={i.isrcs.join(", ")}>{i.isrcs.slice(0, 2).join(", ")}{i.isrcs.length > 2 && <span className="muted"> +{i.isrcs.length - 2}</span>}</td>
                    {sides.map(([k, bs]) => bs.map((b) => {
                      const v = cell(i, b);
                      return [
                        <td key={b.key + "a"} className="num b"><Amount v={v?.amount ?? null} /></td>,
                        k === "PLATFORM" ? [<td key={b.key + "p"} className="small">{v ? b.period_label : ""}</td>,
                          <td key={b.key + "u"} className="num"><Plays v={v?.usage} /></td>]
                          : [<td key={b.key + "d"} className="small">{v ? day(b.date) : ""}</td>,
                            <td key={b.key + "p"} className="small">{v ? b.period_label : ""}</td>],
                        <td key={b.key + "n"} className="small sep">{v ? b.reference : ""}</td>];
                    }))}
                    {platformRun && <><td className="num"><Amount v={split || interest !== null ? i.eligible_revenue_basis : i.sound_recording_revenue} /></td>
                      {split && <td className="num"><Amount v={i.sound_recording_revenue} /></td>}
                      <td className="num"><Amount v={i.reference_benchmark_amount} /></td></>}
                    <td className="num b">{i.iprs_royalty_amount === null && i.item_kind === "WORK" && i.open_exceptions.includes("MISSING_IPRS_ENTRY")
                      ? <span className="bad-t small" title={MISSING}>No IPRS entry</span> : <Amount v={i.iprs_royalty_amount} />}</td>
                    {platformRun && <><td className="num"><Pct v={i.observed_percentage} /></td>
                      <td className="num">{i.variance_pct == null ? <span className="blank">—</span> : <span className={Number(i.variance_pct) > 0 ? "under-t" : "good-t"}>{Number(i.variance_pct).toFixed(2)} %</span>}</td>
                      <td className={`num ${cli ? "" : "sep"}`}>{i.indicative_variance === null ? <span className="blank">—</span> :
                        <span className={under(i) ? "under-t" : "good-t"} title={under(i) ? "IPRS paid less than expected" : "IPRS paid at least the expected amount"}><Money v={i.indicative_variance} /></span>}</td></>}
                    {(cli || !platformRun) && <td className="num sep">{i.client_iprs_difference === null ? <span className="blank">—</span> :
                      <span className={Math.abs(Number(i.client_iprs_difference)) > 0.005 ? "warn-t" : ""}><Money v={i.client_iprs_difference} /></span>}</td>}
                    {yoy && <><td className="num"><Amount v={i.previous_revenue} /></td><td className="num"><Change cur={i.sound_recording_revenue ?? i.client_statement_amount} old={i.previous_revenue} /></td>
                      <td className="num"><Amount v={i.previous_iprs_royalty} /></td><td className="num sep"><Change cur={i.iprs_royalty_amount} old={i.previous_iprs_royalty} /></td></>}
                    <td><MappingPill status={i.mapping_status} /></td>
                    <td className="small wrap-cell">{i.open_exceptions.map((x) => L.exceptions[x]).join(", ")}{i.later_statements.length > 0 && <div className="warn-t">later statement to review</div>}</td>
                    <td>{i.review_status === "UNREVIEWED" ? <span className="muted small">Not reviewed</span> : <><Pill tone={REVIEW_TONE[i.review_status]}>{L.review[i.review_status]}</Pill>
                      {i.reviewed_by_name && <div className="muted small nowrap">by {i.reviewed_by_name}{i.reviewed_at ? ` · ${day(i.reviewed_at)}` : ""}</div>}</>}</td>
                  </tr>))}</tbody>
              </table>
            </ScrollX>
          );
        })()}
        {items.data && <Pager total={items.data.total} offset={offset} size={100} onChange={setOffset} />}
      </Card>
      <div className="run-meta small muted">
        <p>{r.run_reference} · run {when(r.started_at)} by {r.started_by_name} · expected = {bench} % of the {share !== null ? `total revenue${share !== 100 ? ` (revenue ÷ ${share} % client share)` : ""}` : r.client_interest_pct ? `eligible revenue (client interest ${Number(r.client_interest_pct)} %)` : "platform revenue"} · {r.revenue_basis.toLowerCase()} revenue
          {yearly && <> · {cm} month{cm === 1 ? "" : "s"} compared{r.previous_period_start ? `, year before ${period(r.previous_period_start, r.previous_period_end)}` : ""}</>}</p>
        <p>Indicative figures - not amounts payable by IPRS.</p>
        <More label="Statements used in this run">
          <ul className="plain small">
            {r.source_snapshot.platform_reports ? <>{snapList(r.source_snapshot.platform_reports, "Platform report")}{snapList(r.source_snapshot.client_statements, "Client statement")}</>
              : snapList(r.source_snapshot.revenue_statements, "Client (source revenue)")}
            {snapList(r.source_snapshot.iprs_statements, "IPRS")}
            <li className="muted">Snapshot fingerprint {r.source_snapshot_sha256.slice(0, 16)}…</li></ul>
        </More>
      </div>
      {open && <ItemDialog itemId={open} labels={L} onClose={() => setOpen(null)}
                           usage={items.data?.usage && uv ? { label: uv.label, row: rows.find((x) => x.id === open) } : undefined} />}
      {draft && <DraftDialog cid={cid} runId={runId} ids={selEnq} known={known} laterInRun={rv.data.later_statements.items > 0} left={left}
                             onClose={() => setDraft(false)} onDone={(id) => go(`enquiries/${id}`)} />}
      {bulk && <BulkReview runId={runId} status={bulk} label={L.review[bulk]} count={sel.length} ids={sel} onClose={() => setBulk(null)}
                           onDone={(n) => { clearSel(); qc.invalidateQueries({ queryKey: ["recon-items", runId] }); qc.invalidateQueries({ queryKey: ["recon-run", runId] });
                             toast(`${int(n)} item${n === 1 ? "" : "s"} marked '${L.review[bulk]}'.`); }} />}
    </Page>
  );
}

function BulkReview({ runId, status, label, count, ids, onClose, onDone }: { runId: number; status: string; label: string; count: number; ids: number[];
  onClose: () => void; onDone: (n: number) => void }) {
  const [note, setNote] = useState("");
  return (
    <FormDialog title={`Mark ${int(count)} item${count === 1 ? "" : "s"} '${label}'`} submit={`Mark ${label.toLowerCase()}`} onClose={onClose}
                onSubmit={async () => { const r = await api.post<{ updated: number }>(`/reconciliation/runs/${runId}/review`, { item_ids: ids, status, note }); onDone(r.updated); }}>
      <p>{status === "UNREVIEWED" ? "The review of these items is undone; their earlier review note is replaced by the note below (if any)."
        : status === "NEEDS_INFO" ? "These items wait for information. Say what is needed, so the next person knows." : "These items are marked reviewed by you, now."}
        {" "}The calculated figures never change.</p>
      <label className="field">Note {status === "NEEDS_INFO" ? "(what information is needed)" : "(optional)"}
        <textarea className="input" rows={3} required={status === "NEEDS_INFO"} value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}

function DraftDialog({ cid, runId, ids, known, laterInRun, left, onClose, onDone }: { cid: number; runId: number; ids: number[]; known: Record<number, Item>;
  laterInRun: boolean; left: number; onClose: () => void; onDone: (id: number) => void }) {
  const items = ids.map((id) => known[id]).filter(Boolean);
  const unseen = ids.length - items.length;
  const later = items.filter((i) => i.later_statements.length > 0);
  const ask = later.length > 0 || (unseen > 0 && laterInRun);
  const [reviewed, setReviewed] = useState(false);
  return (
    <FormDialog title={`Prepare a query to IPRS (${int(ids.length)} work${ids.length === 1 ? "" : "s"})`} submit="Prepare draft" onClose={onClose}
                onSubmit={async () => { const r = await api.post<{ enquiry: { id: number } }>("/enquiries", { client_id: cid, run_id: runId, item_ids: ids, later_reviewed: reviewed }); onDone(r.enquiry.id); }}>
      <p>A draft letter to IPRS with the attached list of these works - the properly matched works of the Works tab - with the platform revenue, the plays, what IPRS paid {""}
        and its percentage for each. It is confirmed inside the company first and is <b>never sent</b> from the application: a person sends it and records that here.</p>
      {left > 0 && <Notice tone="warn">{int(left)} work{left === 1 ? " is" : "s are"} left out: the ISRC link is not verified or the work needs review in the Catalogue. {""}
        Check {left === 1 ? "it" : "them"} in the Catalogue, then put {left === 1 ? "it" : "them"} in a later query.</Notice>}
      <ul className="plain small">{items.slice(0, 12).map((i) => <li key={i.id}>{i.work_title} ({i.internal_work_number}) — {i.iprs_royalty_amount === null ? "no IPRS entry"
        : i.indicative_variance !== null && Number(i.indicative_variance) > 0.005 ? <>paid <Money v={i.iprs_royalty_amount} />, expected <Money v={i.reference_benchmark_amount} /></>
          : i.sound_recording_revenue === null ? <>paid <Money v={i.iprs_royalty_amount} />, no platform revenue to compare</> : <>paid <Money v={i.iprs_royalty_amount} />, at or above expected</>}</li>)}
        {ids.length > Math.min(12, items.length) && <li>… and {int(ids.length - Math.min(12, items.length))} more</li>}</ul>
      {ask && <label className="check"><input type="checkbox" checked={reviewed} required onChange={(e) => setReviewed(e.target.checked)} />
        I reviewed the later IPRS statement(s){later.length ? ` for ${later.map((i) => i.internal_work_number).join(", ")}` : " that concern these items"}; they do not already address these items.</label>}
    </FormDialog>
  );
}

type ItemDetail = { item: Item & { review_note: string | null; reviewed_by_name: string | null; reviewed_at: string | null; usage_period_start: string; usage_period_end: string; currency: string | null; territory: string | null };
  sources: { source_type: string; statement_id: number; original_filename: string; source_row_number: number; isrc: string | null; internal_work_number: string | null; usage_month: string | null; contribution_amount: string | null }[];
  exceptions: { id: number; exception_type: string; label: string; severity: string; description: string; status: string; assigned_to_name: string | null; reviewed_by_name: string | null; resolution_note: string | null }[];
  later_statements: { id: number; filename: string }[]; enquiries: { id: number; enquiry_reference: string; status: string }[];
  isrc_breakdown: { isrc: string; lines: number; amount: string; blank: number; plays: string | null }[] };

const SOURCE_TYPE: Record<string, string> = { CLIENT_REVENUE: "Client (source revenue)", PLATFORM_REVENUE: "Platform revenue", PLATFORM_USAGE: "Platform usage",
  CLIENT_STATEMENT: "Client statement", IPRS_ROYALTY: "IPRS paid" };

/** usage: opened from the Usage tab - the row's figures for the usage months, shown above the run's own. */
function ItemDialog({ itemId, labels, onClose, usage }: { itemId: number; labels: RunView["labels"]; onClose: () => void;
  usage?: { label: string; row?: Item } }) {
  const { me } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["recon-item", itemId], queryFn: () => api.get<ItemDetail>(`/reconciliation/items/${itemId}`) });
  const [rev, setRev] = useState<string | null>(null);
  const [exc, setExc] = useState<{ id: number; status: string } | null>(null);
  const [fix, setFix] = useState<"link" | "work" | "addressed" | null>(null);
  const [work, setWork] = useState<number | null>(null);
  const { clientId } = useApp();
  const update = (d: ItemDetail) => { qc.setQueryData(["recon-item", itemId], d); qc.invalidateQueries({ queryKey: ["recon-items"] }); qc.invalidateQueries({ queryKey: ["recon-run"] }); };
  const d = q.data;
  const i = d?.item;
  return (
    <Dialog title={i ? (i.work_title ?? i.isrcs[0] ?? "Item") : "Item"} sub={i ? `${labels.kinds[i.item_kind]} · item ${i.item_no} · ${period(i.usage_period_start, i.usage_period_end)}` : undefined} onClose={onClose} wide="xl">
      {!d || !i ? <Loading /> : (
        <div className="form full">
          {usage?.row && (() => {
            const u = usage.row;
            const split = u.client_share_pct && Number(u.client_share_pct) !== 100;
            return (
              <div className="box small">
                <b>Usage tab: {dash(usage.label)} only</b>
                <Facts items={[["Client revenue", <Amount v={u.sound_recording_revenue} />],
                  ...(split ? [["Total revenue (100 %)", <Amount v={u.eligible_revenue_basis} />] as [string, React.ReactNode]] : []),
                  ["Usage (plays)", u.usage_plays != null ? `${int(Number(u.usage_plays))} plays` : <span className="muted">none</span>],
                  ["Expected from IPRS", <Amount v={u.reference_benchmark_amount} />],
                  ["Received from IPRS", u.iprs_royalty_amount === null ? <span className="muted">no IPRS entry</span> : <><Amount v={u.iprs_royalty_amount} />{u.iprs_split && <span className="muted small"> part of the IPRS amount, by the song's revenue in these months</span>}</>],
                  ["Received %", <Pct v={u.observed_percentage} />],
                  ["Variance %", u.variance_pct == null ? <span className="muted">—</span> : <Pct v={u.variance_pct} />],
                  ["Variance (expected − received)", u.indicative_variance == null ? <span className="muted">—</span> : Number(u.indicative_variance) > 0.005
                    ? <span className="under-t"><Money v={u.indicative_variance} /> underpaid</span> : <span className="good-t">paid in full (<Money v={u.indicative_variance} />)</span>]]} />
                <span className="muted">Below: the whole run ({period(i.usage_period_start, i.usage_period_end)}).</span>
              </div>);
          })()}
          <div className="two">
            <div>
              <h2>Source values</h2>
              <Facts items={[["IPRS work number", i.internal_work_number ?? "—"], ["ISRCs", i.isrcs.join(", ") || "—"],
                ["Platform revenue (platform reports)", <><Amount v={i.sound_recording_revenue} missing="none found" /> <span className="muted small">{int(i.revenue_lines)} lines{i.client_share_pct && Number(i.client_share_pct) !== 100 ? ` · the client's ${Number(i.client_share_pct)} % share` : ""}</span></>],
                ...(i.client_share_pct && Number(i.client_share_pct) !== 100 ? [["Total revenue (100 %)", i.eligible_revenue_basis != null ? <><Amount v={i.eligible_revenue_basis} /> <span className="muted small">= revenue ÷ {Number(i.client_share_pct)} %</span></> : <span className="muted">not calculated</span>] as [string, React.ReactNode]] : []),
                ["Usage (plays)", i.usage_plays != null ? `${int(Number(i.usage_plays))} plays` : <span className="muted">no usage report for these months</span>],
                ...(i.client_statement_lines > 0 ? [["Client statement", <Amount v={i.client_statement_amount} />] as [string, React.ReactNode]] : []),
                ["Received from IPRS (IPRS statements)", i.iprs_royalty_amount === null && i.item_kind === "WORK" ? <span className="bad-t">{MISSING}</span> : <Amount v={i.iprs_royalty_amount} />],
                ...(i.previous_revenue !== null || i.previous_iprs_royalty !== null ? [["Year before: revenue · IPRS royalty", <><Amount v={i.previous_revenue} /> · <Amount v={i.previous_iprs_royalty} /></>] as [string, React.ReactNode]] : []),
                ["Client share on the IPRS statement", i.iprs_client_share ? `${Number(i.iprs_client_share)} %` : "—"], ["Currency", i.currency ?? "not established"], ["Territory", i.territory ?? "not stated"]]} />
            </div>
            <div>
              <h2>Check: expected vs paid</h2>
              <Facts items={[["Calculation", <Pill tone={CALC_TONE[i.calculation_status]}>{labels.calc[i.calculation_status]}</Pill>],
                ["Expected from IPRS", i.reference_benchmark_amount != null ? <><Amount v={i.reference_benchmark_amount} /> <span className="muted small">{Number(i.benchmark_percentage)} % of <Money v={i.eligible_revenue_basis} />{i.client_share_pct && Number(i.client_share_pct) !== 100 ? " (the total revenue)" : i.client_interest_share ? ` (client interest ${Number(i.client_interest_share)} %)` : ""}</span></> : <span className="muted">not calculated</span>],
                [i.client_share_pct && Number(i.client_share_pct) !== 100 ? "Received, % of the total revenue" : "Received, % of the revenue", <Pct v={i.observed_percentage} />],
                [`Variance % (${Number(i.benchmark_percentage)} % − received %)`, i.indicative_variance == null || i.observed_percentage == null || i.benchmark_percentage == null ? <span className="muted">—</span>
                  : <Pct v={Number(i.benchmark_percentage) - Number(i.observed_percentage)} />],
                ["Variance (expected − received)", i.indicative_variance == null ? <span className="muted">—</span> : Number(i.indicative_variance) > 0.005
                  ? <span className="under-t"><Money v={i.indicative_variance} /> underpaid</span> : <span className="good-t">paid in full (<Money v={i.indicative_variance} />)</span>],
                ...(i.client_iprs_difference != null ? [["Client statement − IPRS paid", <Amount v={i.client_iprs_difference} />] as [string, React.ReactNode]] : []),
                ["Links", <MappingPill status={i.mapping_status} />]]} />
            </div>
          </div>
          <Notice>{i.recommended_action}</Notice>
          {me.can.prepare && (
            <div className="actions">
              {i.item_kind === "UNMATCHED_RECORDING" && i.mapping_status === "UNKNOWN" && <Button onClick={() => setFix("link")}>Link this ISRC to a work</Button>}
              {i.item_kind === "UNMATCHED_WORK" && i.internal_work_number && <Button onClick={() => setFix("work")}>Add this work to the catalogue</Button>}
              {i.item_kind === "WORK" && i.work_id && <Button kind="ghost" onClick={() => setWork(i.work_id)}>Open the work</Button>}
              {i.review_status !== "REVIEWED" && <Button onClick={() => setFix("addressed")}>Already addressed (later statement, payment or adjustment)</Button>}
            </div>
          )}
          {d.later_statements.length > 0 && <Notice tone="warn">A later IPRS statement may concern this work: {d.later_statements.map((s) => <a key={s.id} href={`#/statements/${s.id}`}>{s.filename} </a>)}</Notice>}
          {d.enquiries.length > 0 && <p>Enquiries: {d.enquiries.map((e) => <a key={e.id} href={`#/enquiries/${e.id}`}>{e.enquiry_reference} ({e.status.replace(/_/g, " ").toLowerCase()}) </a>)}</p>}
          <h2>Exceptions</h2>
          {d.exceptions.length === 0 ? <p className="muted">None.</p> : (
            <ul className="plain">{d.exceptions.map((e) => (
              <li key={e.id} className="exc">
                <Pill tone={e.status === "OPEN" || e.status === "IN_REVIEW" ? (e.severity === "HIGH" ? "bad" : "warn") : "neutral"}>{e.label} · {e.status.replace("_", " ").toLowerCase()}</Pill>
                <span>{e.description}{e.resolution_note && <span className="muted"> — {e.resolution_note} ({e.reviewed_by_name})</span>}</span>
                {me.can.prepare && (e.status === "OPEN" || e.status === "IN_REVIEW") && <span className="row nowrap">
                  <Button kind="ghost" className="sm" onClick={() => setExc({ id: e.id, status: "RESOLVED" })}>Resolved</Button>
                  <Button kind="ghost" className="sm" onClick={() => setExc({ id: e.id, status: "DISMISSED" })}>Dismiss</Button></span>}
              </li>))}</ul>
          )}
          {d.isrc_breakdown.length > 0 && (<>
            <h2>Revenue and plays by ISRC</h2>
            <div className="tbl-wrap short"><table className="tbl"><thead><tr><th>ISRC</th><th className="num">Revenue lines</th><th className="num">Revenue</th><th className="num">Plays</th></tr></thead>
              <tbody>{d.isrc_breakdown.map((b) => <tr key={b.isrc}><td className="mono">{b.isrc || "no ISRC"}</td><td className="num">{int(b.lines)}{b.blank ? ` (${b.blank} blank)` : ""}</td>
                <td className="num">{b.lines ? <Money v={b.amount} /> : <span className="blank">—</span>}</td><td className="num"><Plays v={b.plays} /></td></tr>)}</tbody></table></div>
          </>)}
          <More label={`Source lines (${d.sources.length})`}>
            <div className="tbl-wrap short"><table className="tbl"><thead><tr><th>Type</th><th>Statement</th><th>Row</th><th>ISRC / work</th><th>Month</th><th className="num">Amount</th></tr></thead>
              <tbody>{d.sources.slice(0, 500).map((x, k) => <tr key={k}><td className="small">{SOURCE_TYPE[x.source_type] ?? x.source_type}</td>
                <td className="small"><a href={`#/statements/${x.statement_id}`}>#{x.statement_id}</a></td><td className="num">{x.source_row_number}</td>
                <td className="mono small">{x.isrc ?? x.internal_work_number}</td><td className="small">{x.usage_month ? mon(x.usage_month) : ""}</td>
                <td className="num">{x.source_type === "PLATFORM_USAGE" ? <>{int(Number(x.contribution_amount))} plays</> : <Amount v={x.contribution_amount} missing="blank" />}</td></tr>)}</tbody></table></div>
          </More>
          <div className="actions spread">
            <span className="small muted">Review: <Pill tone={REVIEW_TONE[i.review_status]}>{labels.review[i.review_status]}</Pill>{i.reviewed_by_name && ` by ${i.reviewed_by_name} ${day(i.reviewed_at)}`}{i.review_note && ` — ${i.review_note}`}</span>
            <span className="row">{me.can.prepare && <>
              <Button onClick={() => setRev("NEEDS_INFO")}>Needs information</Button>
              <Button kind="primary" onClick={() => setRev("REVIEWED")}>Mark reviewed</Button></>}
              <Button onClick={onClose}>Close</Button></span>
          </div>
        </div>
      )}
      {rev && <ReviewDialog itemId={itemId} status={rev} onClose={() => setRev(null)} onDone={update} />}
      {fix === "link" && i && clientId && <LinkIsrc cid={clientId} isrc={i.isrcs[0]} title={i.work_title ?? ""} onClose={() => setFix(null)} />}
      {fix === "work" && i && clientId && <AddWork cid={clientId} number={i.internal_work_number ?? ""} title={i.work_title ?? ""} onClose={() => setFix(null)} onDone={(id) => setWork(id)} />}
      {fix === "addressed" && <Addressed itemId={itemId} onClose={() => setFix(null)} onDone={update} />}
      {work && <WorkDialog workId={work} onClose={() => setWork(null)} />}
      {exc && <ExceptionDialog id={exc.id} status={exc.status} onClose={() => setExc(null)} onDone={update} />}
    </Dialog>
  );
}

function LinkIsrc({ cid, isrc, title, onClose }: { cid: number; isrc: string; title: string; onClose: () => void }) {
  const { toast } = useApp();
  const [f, setF] = useState({ work_number: "", note: "" });
  const [picked, setPicked] = useState<FoundWork | null>(null);
  return (
    <FormDialog title={`Link ${isrc} to a work`} submit="Link ISRC" onClose={onClose}
                onSubmit={async () => {
                  if (picked) await api.post(`/catalogue/works/${picked.id}/links`, { isrc, recording_title: title, note: f.note });
                  else await api.post("/catalogue/link-isrc", { client_id: cid, isrc, recording_title: title, ...f });
                  toast("Linked. An Admin verifies the link; run the reconciliation again to include it.");
                }}>
      <p>The link starts as 'needs verification'. A title match alone is never enough: say what shows that this recording belongs to the work.</p>
      <WorkNumberField cid={cid} required label="IPRS work number" value={f.work_number} picked={picked}
                       onType={(v) => setF((x) => ({ ...x, work_number: v }))} onPick={setPicked} />
      <label className="field">Evidence<textarea className="input" rows={2} required value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
    </FormDialog>
  );
}

function Addressed({ itemId, onClose, onDone }: { itemId: number; onClose: () => void; onDone: (d: ItemDetail) => void }) {
  const [f, setF] = useState({ kind: "LATER_STATEMENT", statement_id: "", amount: "", note: "" });
  return (
    <FormDialog title="The difference was already addressed" submit="Record and mark reviewed" onClose={onClose}
                onSubmit={async () => onDone(await api.post<ItemDetail>(`/reconciliation/items/${itemId}/addressed`, f))}>
      <p>Record the verified evidence. The item's exceptions are closed with it and the item is marked reviewed; the calculated figures stay as they were.</p>
      <label className="field">By<Select value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={[{ value: "LATER_STATEMENT", label: "A later statement" },
        { value: "PAYMENT", label: "A payment" }, { value: "ADJUSTMENT", label: "An adjustment" }]} /></label>
      <label className="field">Statement number (optional, as shown under Statements)<input className="input" inputMode="numeric" value={f.statement_id} onChange={(e) => setF({ ...f, statement_id: numeric(e.target.value, 0) })} /></label>
      <label className="field">Amount (optional)<input className="input" inputMode="decimal" pattern={NUMBER_PATTERN} title="A number, for example 1250 or 1250.50"
                                                    value={f.amount} onChange={(e) => setF({ ...f, amount: numeric(e.target.value) })} /></label>
      <label className="field">Evidence<textarea className="input" rows={3} required value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
    </FormDialog>
  );
}

function ReviewDialog({ itemId, status, onClose, onDone }: { itemId: number; status: string; onClose: () => void; onDone: (d: ItemDetail) => void }) {
  const [note, setNote] = useState("");
  return (
    <FormDialog title={status === "REVIEWED" ? "Mark this item reviewed" : "This item needs information"} submit="Save" onClose={onClose}
                onSubmit={async () => onDone(await api.post<ItemDetail>(`/reconciliation/items/${itemId}/review`, { status, note }))}>
      <label className="field">Note<textarea className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}

function ExceptionDialog({ id, status, onClose, onDone }: { id: number; status: string; onClose: () => void; onDone: (d: ItemDetail) => void }) {
  const [note, setNote] = useState("");
  return (
    <FormDialog title={status === "RESOLVED" ? "Mark the exception resolved" : "Dismiss the exception"} submit="Save" onClose={onClose}
                onSubmit={async () => onDone(await api.post<ItemDetail>(`/reconciliation/exceptions/${id}`, { status, note }))}>
      <label className="field">{status === "RESOLVED" ? "How was it resolved?" : "Why is it dismissed?"}<textarea className="input" rows={3} required value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}
