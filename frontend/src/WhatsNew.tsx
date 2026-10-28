import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Release } from "./session";
import { Button, Dialog, Loading } from "./ui";

/** After an update: a small one-time note in the bottom-right corner. 'See what's new' opens the notes of that version.
 *  Opening or dismissing it is remembered on the server (every browser), so it is shown only once. */
export function WhatsNew({ notes }: { notes: Release[] }) {
  const [state, setState] = useState<"note" | "open" | "done">(notes.length ? "note" : "done");
  const see = useRef<HTMLButtonElement>(null);
  const seen = () => { api.post("/me/seen").catch(() => { /* shown again next time if this did not reach the server */ }); };
  useEffect(() => {
    if (state !== "note") return;
    see.current?.focus({ preventScroll: true });
  }, [state]);
  if (state === "done" || !notes.length) return null;
  const latest = notes[0];
  if (state === "open") return <ReleaseNotes releases={notes} onClose={() => setState("done")} />;
  return (
    <aside className="update-note" role="status" aria-label={`Updated to version ${latest.version}`}>
      <div className="update-note-h">
        <span className="wn-badge">Updated to V{latest.version}</span>
        <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => { seen(); setState("done"); }}>×</button>
      </div>
      <p className="update-note-t">{latest.summary}</p>
      <div className="actions end">
        <button ref={see} type="button" className="btn primary sm" onClick={() => { seen(); setState("open"); }}>See what's new</button>
      </div>
    </aside>
  );
}

/** The notes of one or more versions, newest first. */
export function ReleaseNotes({ releases, current, onClose }: { releases: Release[]; current?: string; onClose: () => void }) {
  const latest = releases[0];
  return (
    <Dialog title={releases.length === 1 ? `What's new in V${latest.version}` : "What's new"}
            sub={releases.length === 1 ? latest.date : current ? `You are on V${current}` : undefined} onClose={onClose} wide>
      <div className="form full">
        {releases.map((r, i) => (
          <section key={r.version} className="wn-release">
            {releases.length > 1 && <h3>V{r.version} <span className="muted small">· {r.date}{i === 0 && current === r.version ? " · current" : ""}</span></h3>}
            <p className={i === 0 ? "wn-summary" : ""}>{r.summary}</p>
            {r.points.length > 0 && <ul>{r.points.map((p, k) => <li key={k}>{p}</li>)}</ul>}
            {(r.sections ?? []).map((sec) => (
              <div key={sec.title} className="wn-section"><h4>{sec.title}</h4><ul>{sec.points.map((p, k) => <li key={k}>{p}</li>)}</ul></div>))}
          </section>
        ))}
        <div className="actions end"><Button kind="primary" onClick={onClose}>Got it</Button></div>
      </div>
    </Dialog>
  );
}

/** The version in the footer; signed in, it opens every version's notes. */
export function VersionButton() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ version: string; releases: Release[] } | null>(null);
  useEffect(() => {
    if (open && !data) api.get<{ version: string; releases: Release[] }>("/releases").then(setData).catch(() => setOpen(false));
  }, [open, data]);
  return (
    <>
      <button type="button" className="ver" title="What's new in each version" onClick={() => setOpen(true)}>V{__APP_VERSION__}</button>
      {open && (data ? <ReleaseNotes releases={data.releases} current={data.version} onClose={() => setOpen(false)} />
        : <Dialog title="What's new" onClose={() => setOpen(false)}><Loading /></Dialog>)}
    </>
  );
}
