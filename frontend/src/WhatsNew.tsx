import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Release } from "./session";

/** Shown once per person after an update; closing it is remembered on the server (every browser). */
export function WhatsNew({ notes }: { notes: Release[] }) {
  const [open, setOpen] = useState(notes.length > 0);
  const ok = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    api.post("/me/seen").catch(() => { /* shown again next time if this did not reach the server */ });
  };
  useEffect(() => {
    if (!open) return;
    ok.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!open || !notes.length) return null;
  const latest = notes[0];
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="wn-title">
        <div className="wn-badge">Updated to version {latest.version}</div>
        <h2 id="wn-title">What's new</h2>
        <p className="wn-summary">{latest.summary}</p>
        {notes.map((r) => (
          <section key={r.version} className="wn-release">
            {notes.length > 1 && <h3>Version {r.version}</h3>}
            <ul>{r.points.map((p, i) => <li key={i}>{p}</li>)}</ul>
          </section>
        ))}
        <div className="actions"><button ref={ok} type="button" className="btn primary" onClick={close}>Got it</button></div>
      </div>
    </div>
  );
}
