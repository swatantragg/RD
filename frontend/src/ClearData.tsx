import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { int } from "./format";
import { useApp } from "./session";
import { Button, Dialog, Loading, Notice } from "./ui";

type Counts = Record<string, number>;
const n = (x: number | undefined, one: string, many = `${one}s`) => <><b>{int(x ?? 0)}</b> {x === 1 ? one : many}</>;

/** What each Super Admin clean-up removes and keeps (the server does the work: /clients/{id}/clear-…). */
const KINDS: Record<"statements" | "catalogue", { title: string; button: string; reason: string; intro: string;
  empty: (c: Counts) => boolean; deleted: (c: Counts) => ReactNode; kept: (c: Counts) => ReactNode; done: (c: Counts) => string }> = {
  statements: {
    title: "Delete all statements?", button: "Delete all statements", reason: "Start fresh",
    intro: "Everything made from this client's uploaded statements is removed, so the work can start fresh.",
    empty: (c) => !c.statements && !c.statement_files && !c.reconciliation_runs && !c.enquiries && !c.processing_runs,
    deleted: (c) => <>{n(c.statements, "statement")} ({n(c.statement_files, "file")}) with their lines, {n(c.reconciliation_runs, "reconciliation")}, {n(c.enquiries, "enquiry", "enquiries")} and {n(c.processing_runs, "processing run")}.</>,
    kept: () => "the catalogue (works, ISRCs, links and the song-list file), the reconciliation settings, platforms, people and the activity log, which records this deletion.",
    done: (c) => `${int(c.statements)} statement${c.statements === 1 ? "" : "s"} deleted. The catalogue is kept; upload statements to start fresh.`,
  },
  catalogue: {
    title: "Delete the catalogue?", button: "Delete the catalogue", reason: "Start the catalogue fresh",
    intro: "The client's catalogue is removed, so a new song list can be imported from nothing.",
    empty: (c) => !c.works && !c.isrc_links && !c.catalogue_imports && !c.song_list_files,
    deleted: (c) => <>{n(c.works, "work")} with {n(c.isrc_links, "ISRC link")} and their history, {n(c.catalogue_imports, "catalogue import")}, {n(c.song_list_files, "uploaded song list")}
      {c.reconciliation_runs || c.enquiries ? <> - and, because they are built on these works, {n(c.reconciliation_runs, "reconciliation")} and {n(c.enquiries, "enquiry", "enquiries")}</> : null}.</>,
    kept: (c) => <>the {int(c.statements_kept)} statements and the reports (they find the new catalogue's works as soon as it is imported){c.song_lists_kept_for_runs ? `, ${int(c.song_lists_kept_for_runs)} song list(s) a processing run used` : ""}, the reconciliation settings, platforms, people and the activity log, which records this deletion.</>,
    done: (c) => `The catalogue is deleted (${int(c.works)} works, ${int(c.isrc_links)} ISRC links). Import a song list to start again.`,
  },
};

/** Super Admin only: delete every statement, or the catalogue, of a client to start fresh. The client code is typed to confirm. */
export function ClearDialog({ cid, kind, onClose, onDone }: { cid: number; kind: "statements" | "catalogue"; onClose: () => void; onDone?: () => void }) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const k = KINDS[kind];
  const path = `/clients/${cid}/clear-${kind}`;
  const pre = useQuery({ queryKey: ["clear-preview", kind, cid], gcTime: 0, queryFn: () => api.get<{ client: { code: string; name: string }; counts: Counts }>(path) });
  const [code, setCode] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const c = pre.data?.client;
  const cnt = pre.data?.counts;
  const ok = !!c && code.trim().toUpperCase() === c.code.toUpperCase();
  return (
    <Dialog title={k.title} sub={c ? `${c.name} (${c.code})` : undefined} onClose={onClose}>
      {pre.isError ? <Notice tone="bad">{(pre.error as Error).message}</Notice> : !cnt || !c ? <Loading /> : k.empty(cnt) ? (<>
        <p>{c.name} has nothing to delete here.</p>
        <div className="actions end"><Button onClick={onClose}>Close</Button></div></>
      ) : (
        <form className="form full" onSubmit={async (e) => {
          e.preventDefault();
          if (!ok) return;
          setBusy(true);
          try {
            const r = await api.post<{ counts: Counts }>(path, { confirm: code, reason });
            qc.invalidateQueries();
            toast(k.done(r.counts));
            onDone?.();
            onClose();
          } catch (x) { toast((x as Error).message, true); setBusy(false); }
        }}>
          <p>{k.intro} <b>This cannot be undone.</b></p>
          <ul className="plain small">
            <li>Deleted: {k.deleted(cnt)}</li>
            <li className="muted">Kept: {k.kept(cnt)}</li>
          </ul>
          <label className="field">Reason (optional, kept in the activity log)<input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={k.reason} /></label>
          <label className="field"><span>Type <b className="mono">{c.code}</b> to confirm</span><input className="input" autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} /></label>
          <div className="actions end">
            <Button type="button" onClick={onClose}>Cancel</Button>
            <Button kind="danger" className="solid" type="submit" busy={busy} disabled={!ok}>{k.button}</Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
