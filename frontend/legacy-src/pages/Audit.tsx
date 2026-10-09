import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, qs } from "../api";
import { Card, PageHead, Spinner, StateBadge } from "../components/ui";
import { when } from "../format";

export default function Audit() {
  const [kind, setKind] = useState("");
  const [before, setBefore] = useState<number | undefined>();
  const q = useQuery({ queryKey: ["audit", kind, before], queryFn: () => api.get<any[]>(`/audit${qs({ kind, before })}`) });
  const verify = useMutation({ mutationFn: () => api.get<any>("/audit/verify") });
  return (
    <>
      <PageHead title="Audit log" actions={<button className="btn" onClick={() => verify.mutate()}>{verify.isPending && <Spinner />}Verify hash chain</button>}>
        Append-only: every upload, classification, decision, approval, run, pack and case change. Each event is chained to the
        one before by SHA-256 computed in the database; an edit or deletion breaks the chain.
      </PageHead>
      {verify.data && <div className={`note ${verify.data.ok ? "" : "crit"} section`}>{verify.data.ok ? `Chain intact - ${verify.data.events} events verified.` : `Chain broken at events ${verify.data.broken.join(", ")}`}</div>}
      <div className="filters">
        <select className="input sm" value={kind} onChange={(e) => { setKind(e.target.value); setBefore(undefined); }}>
          <option value="">all objects</option>{["source_file", "work_link", "identity_issue", "duplicate_candidate", "identity_version", "rule_version", "comparison_run", "report_pack", "enquiry_case", "client", "app_user"].map((k) => <option key={k}>{k}</option>)}</select>
      </div>
      <Card flush>
        {q.isLoading ? <Spinner /> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>#</th><th>When</th><th>Who</th><th>Action</th><th>Object</th><th>Detail</th><th>Hash</th></tr></thead>
            <tbody>{q.data!.map((e) => (
              <tr key={e.id}><td className="muted">{e.id}</td><td className="nowrap small">{when(e.at)}</td><td className="small">{e.actor}</td><td><StateBadge state="NONE">{e.action}</StateBadge></td>
                <td className="small">{e.object_kind} {e.object_id}</td><td className="small mono wrap" style={{ maxWidth: 520 }}>{JSON.stringify(e.detail).slice(0, 260)}</td><td className="mono small muted">{e.hash.slice(0, 10)}</td></tr>
            ))}</tbody>
          </table></div>
        )}
        {q.data && q.data.length === 200 && <div className="pager"><button className="btn sm" onClick={() => setBefore(q.data![q.data!.length - 1].id)}>Older ›</button></div>}
      </Card>
    </>
  );
}
