import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api";
import { useApp } from "../session";
import { Button, Card, DownloadButton, Empty, Loading, Money, Page, Pill, when } from "../ui";

type Entry = {
  build_id: number; run_id: number; run_title: string; client_code: string; client_name: string; version: number;
  state: string; state_text: string; generation: string | null; published_at: string | null; finished_at: string | null;
  approved_by: string | null; royalty: string | null;
  reports: { id: number; kind: string; final: boolean; filename: string; available: boolean; reason: string | null; rows: number | null }[];
};
const LABEL: Record<string, string> = { MASTER: "Master", MISSING: "Missing Songs", NON_CLIENT: "Out-of-scope" };

export default function PastReports() {
  const { me, go, toast } = useApp();
  const [client, setClient] = useState<number | "">("");
  const [drafts, setDrafts] = useState(false);
  const q = useQuery({ queryKey: ["past", client], queryFn: () => api.get<Entry[]>(`/past-reports${qs({ client_id: client })}`) });
  const list = (q.data ?? []).filter((e) => drafts || e.state === "PUBLISHED" || e.state === "SUPERSEDED");
  return (
    <Page title="Past Reports" intro="Every published report is kept. A newer version never overwrites an older one.">
      <div className="toolbar">
        {me.clients.length > 1 && (
          <label className="field inline">Client
            <select className="input" value={client} onChange={(e) => setClient(e.target.value ? Number(e.target.value) : "")}>
              <option value="">All clients</option>
              {me.clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        )}
        {me.can.draft_download && (
          <label className="check"><input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} /> Include drafts not yet approved</label>
        )}
      </div>
      {q.isLoading ? <Loading /> : list.length === 0 ? (
        <Card><Empty title="No reports yet">Published reports appear here after an approver publishes them.</Empty></Card>
      ) : (
        <Card>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Report</th><th>Client</th><th>Status</th><th className="num">Society royalty</th><th>Downloads</th></tr></thead>
              <tbody>
                {list.map((e) => (
                  <tr key={e.build_id}>
                    <td><b>{e.generation ?? `Draft · ${e.run_title} v${e.version}`}</b>
                      <div className="muted small">{e.published_at ? `Published ${when(e.published_at)} · approved by ${e.approved_by}` : `Made ${when(e.finished_at)}`}</div></td>
                    <td>{e.client_code}</td>
                    <td><Pill tone={e.state === "PUBLISHED" ? "good" : e.state === "SUPERSEDED" ? "neutral" : "info"}>
                      {e.state === "SUPERSEDED" ? "Published (older version)" : e.state === "PUBLISHED" ? "Published (current)" : "Draft"}</Pill></td>
                    <td className="num"><Money v={e.royalty} /></td>
                    <td>
                      <div className="row wrap">
                        {e.reports.map((r) => r.available ? (
                          <DownloadButton key={r.id} kind={r.kind === "MASTER" ? "primary" : "secondary"} path={`/reports/${r.id}/download`}
                                          onError={(m) => toast(m, true)}>{LABEL[r.kind]}</DownloadButton>
                        ) : <span key={r.id} className="muted small" title={r.reason ?? ""}>{LABEL[r.kind]}: not available</span>)}
                        <Button kind="ghost" onClick={() => go(`process/${e.run_id}`)}>Open run</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </Page>
  );
}
