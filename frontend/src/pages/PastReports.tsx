import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api";
import { useApp } from "../session";
import { DeleteRunDialog } from "../DeleteRun";
import { ReportPreview } from "../ReportPreview";
import { Button, Card, DownloadButton, Empty, Loading, Money, Page, Pill, Select, when } from "../ui";

type Entry = {
  build_id: number; run_id: number; run_title: string; client_code: string; client_name: string; version: number;
  state: string; state_text: string; generation: string | null; published_at: string | null; finished_at: string | null;
  published_by: string | null; royalty: string | null; can_delete: boolean;
  reports: { id: number; kind: string; final: boolean; filename: string; available: boolean; reason: string | null; rows: number | null }[];
};
const LABEL: Record<string, string> = { MASTER: "Master", MISSING: "Missing Songs", NON_CLIENT: "Out-of-scope" };

export default function PastReports() {
  const { me, go, toast } = useApp();
  const [client, setClient] = useState<number | "">("");
  const [drafts, setDrafts] = useState(false);
  const [del, setDel] = useState<Entry | null>(null);
  const [prev, setPrev] = useState<Entry | null>(null);
  const q = useQuery({ queryKey: ["past", client], queryFn: () => api.get<Entry[]>(`/past-reports${qs({ client_id: client })}`) });
  const list = (q.data ?? []).filter((e) => drafts || e.state === "PUBLISHED" || e.state === "SUPERSEDED");
  return (
    <Page title="Past Reports" intro={<>Every published report is kept. A newer version never overwrites an older one.
      {me.can.prepare && " Drafts that were never published can be deleted, to start again with the same files."}</>}>
      <div className="toolbar">
        {me.clients.length > 1 && (
          <label className="field inline">Client
            <Select value={String(client)} onChange={(v) => setClient(v ? Number(v) : "")}
                    options={[{ value: "", label: "All clients" },
                      ...me.clients.map((c) => ({ value: String(c.id), label: c.name, meta: c.code }))]} />
          </label>
        )}
        {me.can.draft_download && (
          <label className="check"><input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} /> Include drafts not yet published</label>
        )}
      </div>
      {q.isLoading ? <Loading /> : list.length === 0 ? (
        <Card><Empty title="No reports yet">Published reports appear here once they are published.</Empty></Card>
      ) : (
        <Card>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Report</th><th>Client</th><th>Status</th><th className="num">Society royalty</th><th>Downloads</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {list.map((e) => (
                  <tr key={e.build_id}>
                    <td><b>{e.generation ?? `Draft · ${e.run_title} v${e.version}`}</b>
                      <div className="muted small">{e.published_at ? `Published ${when(e.published_at)} · by ${e.published_by}` : `Made ${when(e.finished_at)}`}</div></td>
                    <td>{e.client_code}</td>
                    <td><Pill tone={e.state === "PUBLISHED" ? "good" : e.state === "SUPERSEDED" ? "neutral" : "info"}>
                      {e.state === "SUPERSEDED" ? "Published (older version)" : e.state === "PUBLISHED" ? "Published (current)" : "Draft"}</Pill></td>
                    <td className="num"><Money v={e.royalty} /></td>
                    <td>
                      <div className="row nowrap">
                        {e.reports.map((r) => r.available ? (
                          <DownloadButton key={r.id} kind={r.kind === "MASTER" ? "primary" : "secondary"} path={`/reports/${r.id}/download`}
                                          onError={(m) => toast(m, true)}>{LABEL[r.kind]}</DownloadButton>
                        ) : <span key={r.id} className="muted small" title={r.reason ?? ""}>{LABEL[r.kind]}: not available</span>)}
                        {e.reports.some((r) => r.available) && <Button kind="ghost" title="Look inside the reports before downloading"
                                                                       onClick={() => setPrev(e)}>Preview</Button>}
                      </div>
                    </td>
                    <td>
                      <div className="row nowrap end">
                        <Button kind="ghost" onClick={() => go(`process/${e.run_id}`)}>Open run</Button>
                        {e.can_delete && <Button kind="ghost" className="danger-t" title="Delete this run and its draft reports"
                                                 onClick={() => setDel(e)}>Delete</Button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {prev && <ReportPreview onClose={() => setPrev(null)}
                              reports={prev.reports.filter((r) => r.available).map((r) => ({ id: r.id, label: LABEL[r.kind] }))} />}
      {del && <DeleteRunDialog runId={del.run_id} title={del.run_title} onClose={() => setDel(null)}
                               drafts={(q.data ?? []).filter((x) => x.run_id === del.run_id).length} />}
    </Page>
  );
}
