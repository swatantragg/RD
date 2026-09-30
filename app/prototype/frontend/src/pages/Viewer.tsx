// RD Viewer - the SKV matrix, virtualised in both directions (3,000+ rows x 225 columns),
// with a sticky two-row header (section bands + column headers), sticky identity columns,
// section collapse / expand, server-side search and filters, and a provenance drawer.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { api, qs } from "../api";
import {
  Badge, BasisChips, Card, Drawer, Empty, ErrorNote, IsrcChips, Money, PageHead, Spinner, STATUS_CODES, StatusChip,
  WorkChips, statusShort, useDebounced,
} from "../components/ui";
import { dmy, fyLabel, money } from "../format";
import { useApp, useRunJob } from "../state";
import type { Build, MatrixRow } from "../types";

interface Col {
  key: string;
  header: string;
  width: number;
  num?: boolean;
  tint?: string;
  hdr?: string;
  edge?: boolean;
  render: (r: MatrixRow) => ReactNode;
}
interface BandSpan { key: string; title: string; left: number; width: number; colour: string; collapsible: boolean; collapsed: boolean }

const ROW_H = 30;
const BAND_H = 26;
const HDR_H = 36;

export default function Viewer() {
  const { buildId } = useApp();
  const build = useQuery({ queryKey: ["build", buildId], queryFn: () => api.get<Build>(`/builds/${buildId}`), enabled: !!buildId });
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [origin, setOrigin] = useState("");
  const [basis, setBasis] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [mergedOnly, setMergedOnly] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [freeze, setFreeze] = useState(true);
  const [sel, setSel] = useState<number | null>(null);
  const dq = useDebounced(search);
  const rows = useQuery({
    queryKey: ["rows", buildId, dq, status, origin, basis, minAmount, mergedOnly],
    queryFn: () => api.withTotal<MatrixRow[]>(`/builds/${buildId}/rows${qs({
      q: dq, status, origin, basis: basis.startsWith("B") ? basis : undefined,
      min_amount: minAmount, merged: mergedOnly ? "true" : undefined,
    })}`),
    enabled: !!buildId,
    placeholderData: (prev) => prev,
  });
  if (!buildId) return <Empty>No build yet - extract a batch and start a build on Batches &amp; Upload.</Empty>;
  if (!build.data) return <Spinner />;
  const b = build.data;
  let data = rows.data?.items ?? [];
  if (basis === "name") data = data.filter((r) => r.b.some((c) => c === "B4" || c === "B5" || c === "B6"));
  const sumD = data.reduce((a, r) => a + r.d, 0);
  const sumE = data.reduce((a, r) => a + r.e, 0);
  const toggle = (k: string) => setExpanded((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  return (
    <>
      <PageHead title={`RD Viewer · ${b.label}`} actions={
        <div className="row">
          <button className="btn sm" onClick={() => setExpanded(new Set(b.layout.sections.map((s) => s.key)))}>Expand all</button>
          <button className="btn sm" onClick={() => setExpanded(new Set())}>Amounts only</button>
          <label className="check small"><input type="checkbox" checked={freeze} onChange={(e) => setFreeze(e.target.checked)} /> freeze identity</label>
        </div>}>
        One row per catalogue recording plus everything a statement paid or a platform reported that the catalogue
        does not list. Click a section band to expand its Date · Amount · Period · Distribution blocks; click a row for its
        full provenance. Chips in amber are identifiers a source reported but the catalogue does not register.
      </PageHead>
      <div className="row wrap section" style={{ gap: 10 }}>
        <input className="input" placeholder="search song, ISRC or internal no" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">all catalogue statuses</option>
          {STATUS_CODES.map((c) => <option key={c} value={c}>{statusShort(c)} ({b.stats.by_status?.[c] ?? 0})</option>)}
        </select>
        <select className="input" value={origin} onChange={(e) => setOrigin(e.target.value)}>
          <option value="">all origins</option>
          <option value="catalogue">catalogue rows</option>
          <option value="statement">statement-only works</option>
          <option value="platform">revenue-report-only ISRCs</option>
          <option value="usage">usage-report-only ISRCs</option>
        </select>
        <select className="input" value={basis} onChange={(e) => setBasis(e.target.value)}>
          <option value="">any revenue match basis</option>
          <option value="name">a song name moved money (B4-B6)</option>
          {Object.entries(b.layout.basis_labels).map(([k, v]) => <option key={k} value={k}>{k} · {v}</option>)}
        </select>
        <input className="input" placeholder="min amount" value={minAmount} onChange={(e) => setMinAmount(e.target.value.replace(/[^0-9.]/g, ""))} style={{ width: 110 }} />
        <label className="check small"><input type="checkbox" checked={mergedOnly} onChange={(e) => setMergedOnly(e.target.checked)} /> merged rows</label>
        <span className="spacer" />
        <span className="small ink2">
          {rows.isFetching && <Spinner />} {data.length.toLocaleString("en-US")} of {b.row_count.toLocaleString("en-US")} rows ·
          Σ D <b className="num">{money(sumD)}</b> · Σ E <b className="num">{money(sumE)}</b>
        </span>
      </div>
      <Matrix build={b} rows={data} expanded={expanded} toggle={toggle} freeze={freeze} onRow={setSel} selected={sel}
              dim={rows.isFetching} />
      {sel !== null && <RowDrawer buildId={b.id} rowId={sel} onClose={() => setSel(null)} />}
    </>
  );
}

function useColumns(b: Build, expanded: Set<string>, freeze: boolean) {
  return useMemo(() => {
    const L = b.layout;
    const identity: Col[] = [
      { key: "name", header: "Song Name", width: 210, render: (r) => (
        <><span style={{ overflow: "hidden", textOverflow: "ellipsis" }} title={r.name}>{r.name}</span>
          {r.merged > 0 && <span className="mx-merged" title={`${r.merged} row(s) merged into this one`}>⤧{r.merged}</span>}</>) },
      { key: "isrc", header: "ISRC", width: 170, render: (r) => <IsrcChips isrcs={r.isrcs} unreg={r.unreg} max={1} /> },
      { key: "no", header: "Internal No", width: 104, render: (r) => <WorkChips works={r.works} unreg={r.works_unreg} /> },
      { key: "d", header: "Total Amount", width: 110, num: true, render: (r) => (
        <Money v={r.d} dimZero={r.booked} title={r.booked ? r.bn ?? "" : undefined} />) },
      { key: "e", header: `Total ${L.client} Revenue (MRM)`, width: 120, num: true, render: (r) => <Money v={r.e} /> },
    ];
    const cols: Col[] = [];
    const bands: BandSpan[] = [];
    let x = 0;
    const push = (c: Col) => { cols.push(c); x += c.width; };
    for (const sec of L.sections) {
      const start = x;
      const open = expanded.has(sec.key);
      const band = `#${sec.band}`;
      const tint = `#${sec.tint}`;
      let first = true;
      if (sec.kind === "statement") {
        for (const st of sec.statements ?? []) {
          const id = String(st.id);
          const edge = first;
          first = false;
          if (open) {
            push({ key: `${id}:date`, header: `Date`, width: 92, tint, hdr: band, edge, render: (r) => (id in r.a ? dmy(st.date) : null) });
            push({ key: `${id}:amt`, header: `Amount`, width: 100, num: true, tint, hdr: band, render: (r) => (id in r.a ? money(r.a[id]) : null) });
            push({ key: `${id}:per`, header: "Period", width: 170, tint, hdr: band, render: (r) => (id in r.a ? st.period : null) });
            push({ key: `${id}:dist`, header: "Distribution Number", width: 108, tint, hdr: band, render: (r) => (id in r.a ? st.dist_no : null) });
          } else {
            push({ key: `${id}:amt`, header: `${st.sheet} · ${st.dist_no}`, width: 104, num: true, tint, hdr: band, edge,
                   render: (r) => (id in r.a ? money(r.a[id]) : null) });
          }
        }
      } else {
        for (const m of sec.months ?? []) {
          const edge = first;
          first = false;
          if (open) {
            push({ key: `${m.month}:date`, header: "Date", width: 92, tint, hdr: band, edge, render: (r) => (m.month in r.m ? dmy(m.date) : null) });
            push({ key: `${m.month}:amt`, header: "Amount", width: 100, num: true, tint, hdr: band, render: (r) => (m.month in r.m ? money(r.m[m.month]) : null) });
            push({ key: `${m.month}:per`, header: "Period", width: 84, tint, hdr: band, render: (r) => (m.month in r.m ? m.label : null) });
            push({ key: `${m.month}:dist`, header: "Distribution Number", width: 160, tint, hdr: band, render: (r) => (m.month in r.m ? m.dist : null) });
          } else {
            push({ key: `${m.month}:amt`, header: m.label, width: 96, num: true, tint, hdr: band, edge,
                   render: (r) => (m.month in r.m ? money(r.m[m.month]) : null) });
          }
        }
      }
      bands.push({ key: sec.key, title: sec.title, left: start, width: x - start, colour: band, collapsible: true, collapsed: !open });
    }
    const fyStart = x;
    L.fy_keys.forEach((k, i) => push({ key: `fy:${k}`, header: fyLabel(k), width: 108, num: true, tint: "#E8F2E8", hdr: "#D8CBB3",
                                         edge: i === 0, render: (r) => money(r.f[k] ?? 0) }));
    push({ key: "fy:total", header: "Total Revenue", width: 112, num: true, tint: "#E8F2E8", hdr: "#C9B99B", render: (r) => <b>{money(r.d)}</b> });
    bands.push({ key: "fy", title: "TOTAL REVENUE (Indian FY, 1 Apr - 31 Mar)", left: fyStart, width: x - fyStart, colour: "#C9B99B", collapsible: false, collapsed: false });
    const auStart = x;
    push({ key: "status", header: "Catalogue Status", width: 250, tint: "#F0E9DC", hdr: "#D8CBB7", edge: true, render: (r) => (
      <><StatusChip code={r.s} />{r.notes > 0 && <span className="mx-merged" title="provenance notes - open the row">+{r.notes} note{r.notes > 1 ? "s" : ""}</span>}</>) });
    push({ key: "booked", header: "Royalty Booked On", width: 250, tint: "#F0E9DC", hdr: "#D8CBB7", render: (r) => <span title={r.bn ?? ""} style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{r.bn}</span> });
    push({ key: "basis", header: `${L.client} (MRM) Match Basis`, width: 170, tint: "#F0E9DC", hdr: "#D8CBB7", render: (r) => <BasisChips codes={r.b} labels={L.basis_labels} /> });
    bands.push({ key: "audit", title: "AUDIT / TRACEABILITY", left: auStart, width: x - auStart, colour: "#D8CBB7", collapsible: false, collapsed: false });
    const frozen = freeze ? identity : [];
    const scrolling = freeze ? cols : [...identity, ...cols];
    if (!freeze) {
      // identity columns scroll with the rest; shift the bands right by their width
      const w = identity.reduce((a, c) => a + c.width, 0);
      bands.forEach((bd) => { bd.left += w; });
    }
    return { frozen, cols: scrolling, bands, frozenW: frozen.reduce((a, c) => a + c.width, 0) };
  }, [b, expanded, freeze]);
}

function Matrix({ build, rows, expanded, toggle, freeze, onRow, selected, dim }: {
  build: Build; rows: MatrixRow[]; expanded: Set<string>; toggle: (k: string) => void; freeze: boolean;
  onRow: (id: number) => void; selected: number | null; dim: boolean;
}) {
  const { frozen, cols, bands, frozenW } = useColumns(build, expanded, freeze);
  const ref = useRef<HTMLDivElement>(null);
  const headH = BAND_H + HDR_H;
  const rv = useVirtualizer({ count: rows.length, getScrollElement: () => ref.current, estimateSize: () => ROW_H,
                              overscan: 10, paddingStart: headH });
  const cv = useVirtualizer({ horizontal: true, count: cols.length, getScrollElement: () => ref.current,
                              estimateSize: (i) => cols[i].width, overscan: 3, paddingStart: frozenW });
  const totalW = cv.getTotalSize();
  const vcols = cv.getVirtualItems();
  if (!rows.length) return <Card><Empty>No rows match these filters.</Empty></Card>;
  return (
    <div ref={ref} className="mx" style={{ height: "calc(100vh - 262px)", minHeight: 360, opacity: dim ? 0.7 : 1 }}>
      <div className="mx-inner" style={{ width: totalW, height: rv.getTotalSize() }}>
        <div className="mx-head" style={{ height: headH, width: totalW }}>
          <div className="mx-bandrow" style={{ height: BAND_H, width: totalW }}>
            {bands.map((bd) => (
              <div key={bd.key} className="mx-cell mx-band" onClick={() => bd.collapsible && toggle(bd.key)}
                   title={bd.collapsible ? (bd.collapsed ? "click to expand the 4-column blocks" : "click to show amounts only") : bd.title}
                   style={{ left: bd.left + frozenW, width: bd.width, background: bd.colour }}>
                {bd.collapsible && <span>{bd.collapsed ? "▸" : "▾"}</span>}
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{bd.title}</span>
              </div>
            ))}
            {freeze && <div className="mx-frozen" style={{ width: frozenW, height: BAND_H }}>
              <div className="mx-cell mx-band" style={{ left: 0, width: frozenW, background: "#D9D9D9", cursor: "default" }} />
            </div>}
          </div>
          <div className="mx-hdrrow" style={{ height: HDR_H, width: totalW }}>
            {vcols.map((vc) => {
              const c = cols[vc.index];
              return (
                <div key={c.key} className={`mx-cell mx-hdr ${c.edge ? "mx-edge" : ""}`}
                     style={{ left: vc.start, width: vc.size, background: c.hdr ?? "#D9D9D9" }}>{c.header}</div>
              );
            })}
            {freeze && <div className="mx-frozen" style={{ width: frozenW, height: HDR_H }}>
              {frozen.map((c, i) => (
                <div key={c.key} className="mx-cell mx-hdr" style={{ left: frozen.slice(0, i).reduce((a, x) => a + x.width, 0), width: c.width }}>{c.header}</div>
              ))}
            </div>}
          </div>
        </div>
        {rv.getVirtualItems().map((vr) => {
          const r = rows[vr.index];
          return (
            <div key={r.id} className={`mx-row ${vr.index % 2 ? "odd" : ""} ${selected === r.id ? "sel" : ""}`}
                 style={{ top: vr.start, height: ROW_H, width: totalW, cursor: "pointer" }} onClick={() => onRow(r.id)}>
              {vcols.map((vc) => {
                const c = cols[vc.index];
                return (
                  <div key={c.key} className={`mx-cell ${c.num ? "num" : ""} ${c.tint ? "t" : ""} ${c.edge ? "mx-edge" : ""}`}
                       style={{ left: vc.start, width: vc.size, ...(c.tint ? { ["--tint" as any]: c.tint } : {}) }}>
                    {c.render(r)}
                  </div>
                );
              })}
              {freeze && <div className="mx-frozen" style={{ width: frozenW }}>
                {frozen.map((c, i) => (
                  <div key={c.key} className={`mx-cell ${c.num ? "num" : ""}`}
                       style={{ left: frozen.slice(0, i).reduce((a, x) => a + x.width, 0), width: c.width }}>{c.render(r)}</div>
                ))}
              </div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RowDrawer({ buildId, rowId, onClose }: { buildId: number; rowId: number; onClose: () => void }) {
  const { canDecide, setBuildId } = useApp();
  const qc = useQueryClient();
  const run = useRunJob();
  const [err, setErr] = useState<unknown>(null);
  const q = useQuery({ queryKey: ["row", buildId, rowId], queryFn: () => api.get<any>(`/builds/${buildId}/rows/${rowId}`) });
  const r = q.data;
  const undo = async () => {
    if (!r?.decision) return;
    setErr(null);
    try {
      await api.del(`/merge-decisions/${r.decision.id}`);
      await run("Undo merge → next build", () => api.post(`/builds/${buildId}/apply-merges`), (j) => {
        if (j.status === "succeeded" && j.result?.build_id) setBuildId(j.result.build_id);
      });
      qc.invalidateQueries();
      onClose();
    } catch (e) { setErr(e); }
  };
  return (
    <Drawer open onClose={onClose} title={r?.name ?? "…"} sub={r && <span className="row wrap"><StatusChip code={r.status_code} full={r.status} />
      <Badge tone="neutral">{r.origin}</Badge><span className="mono">{r.row_key}</span></span>}>
      {!r ? <Spinner /> : (
        <div className="col" style={{ gap: 18 }}>
          <div className="kv">
            <div>ISRC</div>
            <div className="chips">{r.isrcs.length ? r.isrcs.map((i: any) => (
              <span key={i.isrc} className={`chip ${i.registered ? "" : "unreg"}`} title={i.registered ? "registered in the catalogue" : `NOT registered - attached via ${i.via}`}>{i.isrc}{!i.registered && ` · ${i.via}`}</span>)) : <span className="muted">none in any source</span>}</div>
            <div>Internal No</div>
            <div className="chips">{r.works.length ? r.works.map((w: any) => (
              <span key={w.work_no} className={`chip ${w.registered ? "" : "unreg"}`}>{w.work_no}{!w.registered && " · not in catalogue"}</span>)) : <span className="muted">none in any source</span>}</div>
            <div>Total Amount (royalty)</div><div><b className="num">{money(r.total_amount)}</b></div>
            <div>Platform gross (MRM)</div><div><b className="num">{money(r.total_mrm)}</b></div>
            <div>Streams (usage report)</div><div className="num" style={{ textAlign: "left" }}>{Math.round(r.total_usage).toLocaleString("en-US")}</div>
            <div>Catalogue status</div><div>{r.status}</div>
            {r.booked_note && <><div>Royalty booked on</div><div>{r.booked_note}</div></>}
          </div>
          {r.notes.length > 0 && (
            <div className="col" style={{ gap: 6 }}>
              <h3>Provenance</h3>
              {r.notes.map((n: string, i: number) => <div key={i} className="note small">{n}</div>)}
            </div>
          )}
          {r.decision && (
            <div className="note warn">
              <b>Produced by merge decision #{r.decision.id}</b> - {r.decision.verdict} by {r.decision.decided_by} on {r.decision.decided_at}
              <div className="small" style={{ marginTop: 4 }}>members: {r.decision.members.join(", ")}</div>
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn sm danger" disabled={!canDecide} onClick={undo}
                        title={canDecide ? "revoke the decision and build the next generation without it" : "analyst or admin only"}>
                  Undo this merge
                </button>
                <span className="small muted">revokes the decision and applies the remaining ones into a new build</span>
              </div>
              <ErrorNote error={err} />
            </div>
          )}
          <div>
            <h3>Royalty distributions</h3>
            {r.distributions.length ? (
              <table className="tbl" style={{ marginTop: 6 }}>
                <thead><tr><th>Statement</th><th>Section</th><th>Distribution</th><th>Period</th><th>Issued</th><th className="num">Amount</th></tr></thead>
                <tbody>{r.distributions.map((d: any) => (
                  <tr key={d.statement_id}>
                    <td className="mono small" title={d.filename}>S-{d.s_no}</td><td className="small">{d.section}</td>
                    <td className="mono small">{d.dist_no || "Not specified"}</td><td className="small">{d.period}</td>
                    <td className="small nowrap">{dmy(d.stmt_date)}</td><td className="num">{money(d.amount)}</td>
                  </tr>))}</tbody>
              </table>
            ) : <div className="muted small">{r.booked_note ? "Money for this work is booked on another row (book-once rule)." : "No statement paid this row."}</div>}
          </div>
          {r.fy.length > 0 && (
            <div>
              <h3>Financial-year split</h3>
              <div className="row wrap" style={{ marginTop: 6 }}>{r.fy.map((f: any) => <span key={f.fy} className="chip plain">{f.label} · {money(f.amount)}</span>)}</div>
            </div>
          )}
          {(r.platform_isrcs.length > 0 || r.months.length > 0) && (
            <div>
              <h3>Platform revenue</h3>
              <table className="tbl" style={{ marginTop: 6 }}>
                <thead><tr><th>ISRC</th><th>Title as reported</th><th>Album</th><th>Match basis</th><th className="num">Revenue</th></tr></thead>
                <tbody>{r.platform_isrcs.map((p: any) => (
                  <tr key={p.isrc}><td className="mono small">{p.isrc}</td><td className="small">{p.title}</td><td className="small">{p.album}</td>
                    <td><BasisChips codes={[p.basis]} labels={{ [p.basis]: p.basis_label }} /></td><td className="num">{money(p.revenue)}</td></tr>))}</tbody>
              </table>
              <div className="row wrap" style={{ marginTop: 8 }}>{r.months.map((m: any) => <span key={m.month} className="chip plain">{m.label} · {money(m.amount)}</span>)}</div>
            </div>
          )}
          {r.candidates.length > 0 && (
            <div>
              <h3>Merge review</h3>
              {r.candidates.map((c: any) => (
                <div key={c.id} className="small" style={{ marginTop: 4 }}>
                  <a href="#/merge">{c.kind}</a> · confidence {c.confidence.toFixed(2)} ({c.band}) · {c.status}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}
