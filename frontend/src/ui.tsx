import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { download as dl } from "./api";
import { money, type Num, isBlank } from "./format";

export function Page({ title, intro, actions, children }: {
  title: ReactNode; intro?: ReactNode; actions?: ReactNode; children: ReactNode;
}) {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          {intro && <p className="intro">{intro}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Card({ title, sub, actions, children, tone, className }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children?: ReactNode; tone?: Tone; className?: string;
}) {
  return (
    <section className={`card ${tone ? `tone-${tone}` : ""} ${className ?? ""}`}>
      {(title || actions) && (
        <header className="card-h">
          <div className="card-titles">
            {title && <h2>{title}</h2>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children !== undefined && <div className="card-b">{children}</div>}
    </section>
  );
}

export type Tone = "good" | "warn" | "bad" | "info" | "neutral";

export function Pill({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return <span className={`pill ${tone}`} title={title}>{children}</span>;
}

const FILE_TONE: Record<string, Tone> = { READY: "good", NEEDS_REVIEW: "warn", UNSUPPORTED: "bad", ERROR: "bad",
  LEFT_OUT: "neutral" };
export function FileStatus({ status, text }: { status: string; text: string }) {
  return <Pill tone={FILE_TONE[status] ?? "neutral"}>{text}</Pill>;
}

const RUN_TONE: Record<string, Tone> = { ADDING_FILES: "info", FILES_NEED_ATTENTION: "warn", PROCESSING: "info",
  FAILED: "bad", NEEDS_REVIEW: "warn", READY: "good", WAITING_APPROVAL: "info", PUBLISHED: "good" };
export function RunStatus({ state }: { state: { code: string; text: string } }) {
  return <Pill tone={RUN_TONE[state.code] ?? "neutral"}>{state.text}</Pill>;
}

/** Money as exact text from the server; a blank stays blank (never shown as 0.00). */
export function Money({ v, rupee = true }: { v: Num; rupee?: boolean }) {
  if (isBlank(v)) return <span className="blank" title="no amount">—</span>;
  return <span className="num">{rupee ? "₹" : ""}{money(v)}</span>;
}

export function Button({ kind = "secondary", busy, children, ...p }: {
  kind?: "primary" | "secondary" | "ghost" | "danger"; busy?: boolean; children: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...p} className={`btn ${kind} ${p.className ?? ""}`} disabled={p.disabled || busy} aria-busy={busy}>
      {busy && <span className="spin" aria-hidden />}
      {children}
    </button>
  );
}

export function DownloadButton({ path, children, kind = "primary", disabled, onError }: {
  path: string; children: ReactNode; kind?: "primary" | "secondary"; disabled?: boolean; onError: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Button kind={kind} busy={busy} disabled={disabled} onClick={async () => {
      setBusy(true);
      try { await dl(path); } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
    }}>{children}</Button>
  );
}

/** Progressive disclosure: technical detail only when someone asks for it. */
export function More({ label = "More details", children }: { label?: string; children: ReactNode }) {
  return (
    <details className="more">
      <summary>{label}</summary>
      <div className="more-b">{children}</div>
    </details>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-t">{title}</div>
      {children && <div className="empty-b">{children}</div>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return <div className={`notice ${tone}`} role={tone === "bad" ? "alert" : undefined}>{children}</div>;
}

export function Loading({ text = "Loading…" }: { text?: string }) {
  return <div className="loading"><span className="spin" aria-hidden /> {text}</div>;
}

export function Steps({ steps, current, done, onPick }: {
  steps: string[]; current: number; done: (i: number) => boolean; onPick?: (i: number) => void;
}) {
  return (
    <ol className="steps" aria-label="Progress">
      {steps.map((s, i) => {
        const state = i === current ? "current" : done(i) ? "done" : "todo";
        const can = onPick && (state === "done" || i < current);
        return (
          <li key={s} className={`step ${state}`} aria-current={i === current ? "step" : undefined}>
            <button type="button" disabled={!can} onClick={() => can && onPick!(i)}>
              <span className="n">{state === "done" ? "✓" : i + 1}</span>
              <span className="t">{s}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function PasswordField({ label, value, onChange, autoComplete, hint }: {
  label: string; value: string; onChange: (v: string) => void; autoComplete: string; hint?: string;
}) {
  const [show, setShow] = useState(false);
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <span className="pw">
        <input id={id} className="input" type={show ? "text" : "password"} autoComplete={autoComplete} value={value} required
               minLength={autoComplete === "new-password" ? 10 : undefined} aria-describedby={hint ? `${id}-hint` : undefined}
               onChange={(e) => onChange(e.target.value)} />
        <button type="button" className="pw-toggle" aria-pressed={show} aria-label={show ? "Hide password" : "Show password"}
                onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button>
      </span>
      {hint && <span id={`${id}-hint`} className="hint">{hint}</span>}
    </div>
  );
}

/** A small pop-up window. Esc or Cancel closes it; a click outside does not (so typing is never lost). */
export function Dialog({ title, sub, onClose, children, wide }: {
  title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>("input:not([disabled]), select, textarea, button");
    first?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    document.body.classList.add("no-scroll");
    return () => { document.removeEventListener("keydown", esc); document.body.classList.remove("no-scroll"); prev?.focus(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="modal-back">
      <div ref={box} className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="modal-h">
          <div>
            <h2 id={id}>{title}</h2>
            {sub && <div className="sub">{sub}</div>}
          </div>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Small round '×' used to remove a row. */
export function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" className="icon-btn row-x" aria-label={label} title={label} onClick={onClick}>×</button>;
}
