import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { useApp } from "./session";
import { Button, Dialog } from "./ui";

/** Asks before deleting a run that was never published, together with its draft reports. */
export function DeleteRunDialog({ runId, title, drafts, onClose, onDone }: {
  runId: number; title: string; drafts: number; onClose: () => void; onDone?: () => void;
}) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title="Delete this run?" sub={title} onClose={onClose}>
      <p>The run{drafts > 0 && <> and its {drafts === 1 ? "draft report" : `${drafts} draft reports`}</>} will be removed
        from Home and Past Reports. This cannot be undone.</p>
      <ul className="plain small muted">
        <li>The uploaded files stay stored. Upload them to a new run and the same copies are used, so nothing is
          counted twice.</li>
        <li>Song statuses and other review decisions stay with the client and are used in the next run.</li>
      </ul>
      <div className="actions end">
        <Button onClick={onClose}>Cancel</Button>
        <Button kind="danger" className="solid" busy={busy} onClick={async () => {
          setBusy(true);
          try {
            const r = await api.del<{ message: string }>(`/runs/${runId}`);
            for (const k of ["past", "home"]) qc.invalidateQueries({ queryKey: [k] });
            qc.removeQueries({ queryKey: ["run", runId] });
            toast(r.message);
            onClose();
            onDone?.();
          } catch (e) { toast((e as Error).message, true); setBusy(false); }
        }}>Delete run</Button>
      </div>
    </Dialog>
  );
}
