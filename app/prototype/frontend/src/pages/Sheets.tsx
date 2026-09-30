import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, qs } from "../api";
import { Badge, Card, Empty, ErrorNote, IsrcChips, PageHead, Spinner, WorkChips, useDebounced } from "../components/ui";
import { useApp } from "../state";

const FIELDS = [
  ["", "-"], ["song_name", "Song name"], ["internal_no", "Internal no"], ["isrc", "ISRC"], ["amount", "Amount"], ["period", "Period"],
] as const;

export default function Sheets() {
  const { batchId } = useApp();
  const list = useQuery({ queryKey: ["sheets", batchId], queryFn: () => api.get<any[]>(`/sheets?batch_id=${batchId}`), enabled: !!batchId });
  const [sel, setSel] = useState<number | null>(null);
  const sheets = list.data ?? [];
  const current = sel && sheets.some((s) => s.id === sel) ? sel : sheets[0]?.id ?? null;
  return (
    <>
      <PageHead title="My Sheets">
        Every song sheet you have uploaded (TYPE F), with its column map. The catalogue is simply the sheet flagged
        <i> catalogue</i>. A sheet is mapped by header text and cell fingerprints; a field below the threshold stays
        unmapped - never guessed - and a confirmed map is reused automatically for the next sheet with the same header.
      </PageHead>
      {list.isLoading ? <Spinner /> : !sheets.length ? <Card title="No sheets"><div className="muted">Upload a catalogue or a song sheet on Batches &amp; Upload, then Extract.</div></Card> : (
        <div className="grid2" style={{ gridTemplateColumns: "minmax(260px, 340px) 1fr" }}>
          <div className="col" style={{ gap: 10 }}>
            {sheets.map((s) => (
              <button key={s.id} className={`card`} onClick={() => setSel(s.id)}
                      style={{ textAlign: "left", padding: 12, cursor: "pointer", outline: s.id === current ? "2px solid var(--accent)" : undefined }}>
                <div className="row">
                  <b>{s.label}</b>
                  <span className="spacer" />
                  {s.is_catalogue ? <Badge tone="good">catalogue</Badge> : <Badge tone="neutral">sheet</Badge>}
                </div>
                <div className="small ink2" style={{ marginTop: 4 }}>
                  {s.row_count.toLocaleString("en-US")} rows · {s.counts.works.toLocaleString("en-US")} internal nos ·
                  {" "}{s.counts.isrcs.toLocaleString("en-US")} ISRCs · {s.counts.names.toLocaleString("en-US")} names
                </div>
                <div className="row small" style={{ marginTop: 6 }}>
                  {s.mapping_status === "confirmed" ? <Badge tone="good">✓ map confirmed</Badge> : <Badge tone="warn">map proposed - confirm</Badge>}
                  <span className="muted">{s.coverage_runs.length} coverage run(s)</span>
                </div>
              </button>
            ))}
          </div>
          {current && <SheetDetail id={current} />}
        </div>
      )}
    </>
  );
}

function SheetDetail({ id }: { id: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sheet", id], queryFn: () => api.get<any>(`/sheets/${id}`) });
  const [map, setMap] = useState<Record<number, string>>({});
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [search, setSearch] = useState("");
  const dq = useDebounced(search);
  const entries = useQuery({
    queryKey: ["entries", id, dq], queryFn: () => api.withTotal<any[]>(`/sheets/${id}/entries${qs({ q: dq, limit: 200 })}`),
  });
  const s = q.data;
  useEffect(() => {
    if (!s) return;
    const m: Record<number, string> = {};
    Object.entries<any>(s.mapping).forEach(([f, v]) => { m[v.col_index] = f; });
    setMap(m);
    setSaved(false);
  }, [s]);
  if (!s) return <Spinner />;
  const cols = s.proposal?.columns?.length ? s.proposal.columns : s.header.map((h: string, i: number) => ({ index: i, header: h, candidates: {} }));
  const confirm = async () => {
    setErr(null);
    const body: Record<string, number | null> = {};
    Object.entries(map).forEach(([c, f]) => { if (f) body[f] = Number(c); });
    try {
      await api.patch(`/sheets/${id}/mapping`, { mapping: body });
      await qc.invalidateQueries();
      setSaved(true);
    } catch (e) { setErr(e); }
  };
  const flag = async (v: boolean) => {
    try { await api.patch(`/sheets/${id}`, { is_catalogue: v }); await qc.invalidateQueries(); } catch (e) { setErr(e); }
  };
  return (
    <div className="col" style={{ gap: 16 }}>
      <Card title={s.label} sub={`${s.filename} · header row ${s.header_row + 1} · fingerprint ${s.header_fp.slice(0, 12)}…`}
            actions={<label className="check small"><input type="checkbox" checked={!!s.is_catalogue} onChange={(e) => flag(e.target.checked)} /> use as the catalogue</label>}>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Col</th><th>Header text</th><th>Proposed</th><th>Field</th></tr></thead>
            <tbody>
              {cols.map((c: any) => {
                const best = Object.entries<any>(c.candidates ?? {}).sort((a, b) => b[1].confidence - a[1].confidence)[0];
                return (
                  <tr key={c.index}>
                    <td className="mono">{String.fromCharCode(65 + (c.index % 26))}</td>
                    <td>{c.header || <span className="muted">(blank)</span>}</td>
                    <td className="small ink2">{best ? `${best[0]} · ${best[1].confidence.toFixed(2)}${best[1].header_hit ? " header" : ""}${best[1].value_ratio ? ` · values ${(best[1].value_ratio * 100).toFixed(0)}%` : ""}` : "-"}</td>
                    <td>
                      <select className="input sm" value={map[c.index] ?? ""} onChange={(e) => {
                        const f = e.target.value;
                        const next: Record<number, string> = {};
                        Object.entries(map).forEach(([k, v]) => { if (v !== f) next[Number(k)] = v; });
                        if (f) next[c.index] = f;
                        setMap(next);
                      }}>
                        {FIELDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={confirm}>Confirm column map</button>
          {s.mapping_status === "confirmed" ? <Badge tone="good">✓ confirmed</Badge> : <Badge tone="warn">proposed</Badge>}
          {saved && <span className="small muted">saved - entries reloaded</span>}
        </div>
        <ErrorNote error={err} />
      </Card>
      <Card title="Entries" sub={`${(entries.data?.total ?? 0).toLocaleString("en-US")} matching`} flush
            actions={<input className="input sm" placeholder="search name, internal no, ISRC" value={search} onChange={(e) => setSearch(e.target.value)} />}>
        {entries.data?.items.length ? (
          <div className="tbl-wrap" style={{ maxHeight: 480 }}>
            <table className="tbl">
              <thead><tr><th>Row</th><th>Song name</th><th>Internal no</th><th>ISRC</th></tr></thead>
              <tbody>
                {entries.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="mono small">{e.sheet_row}</td>
                    <td>{e.name}</td>
                    <td><WorkChips works={e.work_nos} /></td>
                    <td><IsrcChips isrcs={e.isrcs} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>No entries.</Empty>}
      </Card>
    </div>
  );
}
