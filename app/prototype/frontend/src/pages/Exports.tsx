// Exports (§19) - one card per artefact: generate, progress, size, sha256, download, history.
// The same build always produces the same bytes (no timestamps inside, fixed zip dates).
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorNote, PageHead } from "../components/ui";
import { bytes } from "../format";
import { useApp, useRunJob } from "../state";

export default function Exports() {
  const { buildId, batchId, meta, builds } = useApp();
  const run = useRunJob();
  const [err, setErr] = useState<unknown>(null);
  const list = useQuery({ queryKey: ["exports", buildId], queryFn: () => api.get<any[]>(`/exports?build_id=${buildId}`), enabled: !!buildId });
  const cov = useQuery({ queryKey: ["coverage-runs-batch", batchId], queryFn: () => api.get<any[]>(`/coverage?batch_id=${batchId}`), enabled: !!batchId });
  const mm = useQuery({ queryKey: ["mm-runs-batch", batchId], queryFn: () => api.get<any[]>(`/mismatch?batch_id=${batchId}`), enabled: !!batchId });
  const [covRun, setCovRun] = useState<number | "">("");
  const [mmRun, setMmRun] = useState<number | "">("");
  if (!buildId) return <Empty>No build yet.</Empty>;
  const build = builds.find((b) => b.id === buildId);
  const arts = meta?.artifacts ?? {};
  const runExports = [...(cov.data ?? []).flatMap((r: any) => r.exports.map((e: any) => ({ ...e, kind: "coverage", ref_id: r.id }))),
                      ...(mm.data ?? []).flatMap((r: any) => r.exports.map((e: any) => ({ ...e, kind: "mismatch", ref_id: r.id })))];
  const history = [...(list.data ?? []), ...runExports.filter((e) => !(list.data ?? []).some((h) => h.id === e.id))]
    .sort((x, y) => y.id - x.id);
  // a coverage / mismatch artefact belongs to the build its run was made on
  const ownerBuild = (kind: string, ref?: number | "") =>
    (kind === "coverage" ? cov.data : kind === "mismatch" ? mm.data : null)?.find((r: any) => r.id === ref)?.build_id ?? buildId;
  const gen = (kind: string, ref?: number | "") =>
    run(`Export ${arts[kind]?.label ?? kind}`, () => api.post(`/builds/${ownerBuild(kind, ref)}/exports/${kind}${ref ? `?ref_id=${ref}` : ""}`)).catch(setErr);
  const latest = (kind: string, ref?: number | "") => history.filter((h) => h.kind === kind && (!ref || h.ref_id === ref));
  return (
    <>
      <PageHead title={`Exports · ${build?.label ?? ""}`}>
        Every deliverable as a formatted .xlsx in the SKV colour system. Pipes exist only here, inside the workbook -
        never in the database. Generating the same artefact twice gives a byte-identical file (compare the sha256).
      </PageHead>
      <ErrorNote error={err} />
      <div className="grid3 section">
        {Object.entries(arts).map(([kind, a]) => {
          const needs = a.scope === "coverage" ? cov.data : a.scope === "mismatch" ? mm.data : null;
          const ref = a.scope === "coverage" ? (covRun || cov.data?.[0]?.id || "") : a.scope === "mismatch" ? (mmRun || mm.data?.[0]?.id || "") : "";
          const done = latest(kind, ref);
          return (
            <Card key={kind} title={a.label} sub={`architecture ${a.section}`}>
              <div className="col" style={{ gap: 10 }}>
                {needs !== null && (
                  needs?.length ? (
                    <select className="input sm" value={ref} onChange={(e) => (a.scope === "coverage" ? setCovRun : setMmRun)(Number(e.target.value) || "")}>
                      {needs.map((r: any) => <option key={r.id} value={r.id}>run #{r.id}{r.mode ? ` · ${r.mode} · ${r.stats?.l3_policy === "reference" ? "ref" : "V2"} · ${r.finding_count} songs` : ` · ${r.row_count} rows`} · {r.build_label}</option>)}
                    </select>
                  ) : <div className="small muted">Run a {a.scope} first.</div>
                )}
                <div className="row">
                  <button className="btn primary sm" disabled={needs !== null && !ref} onClick={() => gen(kind, ref)}>Generate</button>
                  {done[0] && <a className="btn sm" href={`/api/exports/${done[0].id}/download`}>↓ latest</a>}
                </div>
                {done.slice(0, 2).map((h) => (
                  <div key={h.id} className="small">
                    <div className="row"><b style={{ wordBreak: "break-all" }}>{h.filename}</b></div>
                    <div className="muted mono">{bytes(h.size)} · {h.rows ?? "-"} rows · sha256 {h.sha256.slice(0, 16)}…</div>
                  </div>
                ))}
              </div>
            </Card>
          );
        })}
      </div>
      <Card title="History" flush sub="per build; the sha256 column shows determinism at a glance">
        {history.length ? (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>#</th><th>Artefact</th><th>File</th><th className="num">Size</th><th className="num">Rows</th><th>sha256</th><th>Created</th><th></th></tr></thead>
              <tbody>{history.map((h) => {
                const twins = history.filter((x) => x.filename === h.filename && x.kind === h.kind && x.ref_id === h.ref_id);
                const same = twins.length > 1 && twins.every((x) => x.sha256 === h.sha256);
                return (
                  <tr key={h.id}>
                    <td className="mono small">{h.id}</td><td className="small">{arts[h.kind]?.label ?? h.kind}{h.ref_id ? ` · run #${h.ref_id}` : ""}</td>
                    <td className="small">{h.filename}</td><td className="num small">{bytes(h.size)}</td><td className="num small">{h.rows ?? ""}</td>
                    <td className="mono small">{h.sha256.slice(0, 20)}… {same && <Badge tone="good" title="identical bytes across regenerations">identical</Badge>}</td>
                    <td className="small muted nowrap">{h.created_at}</td>
                    <td><a className="btn sm" href={`/api/exports/${h.id}/download`}>Download</a></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        ) : <Empty>Nothing generated for this build yet.</Empty>}
      </Card>
    </>
  );
}
