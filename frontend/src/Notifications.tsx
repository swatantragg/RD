import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { useApp } from "./session";
import { Button, when } from "./ui";

type Note = { id: number; kind: string; title: string; body: string | null; link: string | null; client_id: number; created_at: string; from_name: string | null };
type Notes = { rows: Note[]; total: number };
const SHOWN = 3;
const FOLD_MS = 20_000;                                  // then a small "N new" button, so the page is not covered

/** Work someone else handed you - an enquiry, a report to confirm, a follow-up, an exception, a report returned or
 *  confirmed - as pop-ups in the top-right corner, asked for every 30 seconds. Opening or dismissing one marks it read.
 *  After 20 seconds they fold into a small "N new" button; new work opens them again. */
export function Notifications() {
  const { go, clientId, setClientId } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<Notes>("/notifications"), refetchInterval: 30_000 });
  const read = async (body: { ids?: number[]; all?: boolean }) => {
    try { qc.setQueryData(["notifications"], await api.post<Notes>("/notifications/read", body)); }
    catch { /* shown again at the next check */ }
  };
  const open = (n: Note) => {
    read({ ids: [n.id] });
    if (n.client_id !== clientId) setClientId(n.client_id);
    ["enquiry", "enq-dash", "enq-list", "overview", "recon-run", "recon-items"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    if (n.link) go(n.link);
  };
  const rows = q.data?.rows ?? [];
  const top = rows[0]?.id ?? 0;
  const [folded, setFolded] = useState(0);              // folded up to this notification (the newest when it folded)
  useEffect(() => {
    if (!top || folded >= top) return;
    const t = window.setTimeout(() => setFolded(top), FOLD_MS);
    return () => window.clearTimeout(t);
  }, [top, folded]);
  if (!rows.length) return null;
  const total = q.data?.total ?? rows.length;
  if (folded >= top) return (
    <div className="notif-stack"><button type="button" className="notif-pill" onClick={() => setFolded(-1)} aria-label={`${total} notification${total === 1 ? "" : "s"}: show`}>
      <span className="notif-dot" aria-hidden />{total} new</button></div>);
  const more = total - Math.min(SHOWN, rows.length);
  return (
    <div className="notif-stack" role="region" aria-label="Notifications" aria-live="polite">
      {rows.slice(0, SHOWN).map((n) => (
        <aside key={n.id} className="notif">
          <div className="notif-h"><b>{n.title}</b>
            <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => read({ ids: [n.id] })}>×</button></div>
          {n.body && <p className="notif-t">{n.body}</p>}
          <div className="notif-f"><span className="muted small">{n.from_name ? `${n.from_name} · ` : ""}{when(n.created_at)}</span>
            {n.link && <Button kind="primary" className="sm" onClick={() => open(n)}>Open</Button>}</div>
        </aside>))}
      {more > 0 && <div className="notif-more"><span className="muted small">{more} more</span>
        <Button kind="ghost" className="sm" onClick={() => read({ all: true })}>Dismiss all</Button></div>}
    </div>
  );
}
