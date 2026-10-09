import { useEffect, useState, type ReactNode } from "react";
import { int, isBlank, money, words, type Num } from "../format";

export function Card({ title, sub, actions, children, flush, className }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string;
}) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <div className="card-h">
          <div>
            {title && <h3>{title}</h3>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          <div className="spacer" />
          {actions}
        </div>
      )}
      <div className={`card-b ${flush ? "flush" : ""}`}>{children}</div>
    </section>
  );
}

export function PageHead({ title, step, children, actions }: {
  title: ReactNode; step?: string; children?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        {step && <div className="muted small mono">{step}</div>}
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      <div className="spacer" />
      {actions}
    </div>
  );
}

export function Stat({ label, value, meta }: { label: string; value: ReactNode; meta?: ReactNode }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {meta && <div className="meta">{meta}</div>}
    </div>
  );
}

/** Blank stays blank: a missing amount is never shown as 0.00. */
export function Money({ v, title }: { v: Num; title?: string }) {
  if (isBlank(v)) return <span className="blank" title={title ?? "unknown - not zero"}>—</span>;
  return <span className="num" title={title}>{money(v)}</span>;
}

export function Int({ v }: { v: Num }) {
  if (isBlank(v)) return <span className="blank" title="unknown - not zero">—</span>;
  return <span className="num">{int(v)}</span>;
}

type Tone = "good" | "warn" | "crit" | "info" | "neutral";
export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>;
}

const STATE_TONE: Record<string, Tone> = {
  VALIDATED: "good", UPLOADED: "info", CLASSIFICATION_HOLD: "warn", FILE_EXCEPTION: "crit", DATA_EXCEPTION: "warn",
  RECONCILIATION_HOLD: "warn", DUPLICATE_REVIEW: "warn", SUPERSEDED: "neutral", EXCLUDED: "neutral",
  APPROVED: "good", DRAFT: "info", RETIRED: "neutral", PROPOSED: "warn", REJECTED: "neutral", SENT: "good",
  REVISION_REQUESTED: "crit", OPEN: "warn", AWAITING_REPLY: "info", REPLIED: "info", ADJUSTMENT_PROMISED: "warn",
  CLOSED_EXPLAINED: "good", CLOSED_CORRECTED: "good", RESOLVED: "good", DEFERRED: "neutral", PENDING: "warn",
  SAME: "info", SEPARATE: "neutral", PASS: "good", HOLD: "warn", FAIL: "crit", SKIPPED: "neutral", COMPLETE: "good",
  RUNNING: "warn", CREDITED: "info", RECEIVED: "good", NONE: "neutral", SUPERSEDED_V: "neutral",
};
export function StateBadge({ state, children }: { state: string; children?: ReactNode }) {
  return <Badge tone={STATE_TONE[state] ?? "neutral"}>{children ?? words(state)}</Badge>;
}

export const OUTCOME_LABEL: Record<string, string> = {
  BELOW_COMPARISON: "Below comparison amount", NO_MATCHING_ENTRY: "No matching entry", STATUS_ENQUIRY: "Status enquiry",
  HOLD: "Hold", COVERAGE_ONLY: "Coverage-only", WITHIN_OR_ABOVE: "Within / above",
};
export function Outcome({ o, reason, provisional }: { o: string; reason?: string | null; provisional?: boolean }) {
  return (
    <span className={`pill-o o-${o}`}>
      <span className="dot" />
      {OUTCOME_LABEL[o] ?? o}
      {provisional && <span className="muted small">(provisional)</span>}
      {reason && <span className="muted small">· {words(reason)}</span>}
    </span>
  );
}

export function Checks({ items }: { items: { gate?: string; check: string; result: string; detail?: string }[] | null | undefined }) {
  if (!items?.length) return <div className="muted small">No checks recorded yet.</div>;
  return (
    <div className="gates">
      {items.map((c, i) => (
        <div key={i} style={{ display: "contents" }}>
          <span className="g">{c.gate ?? ""}</span>
          <span><StateBadge state={c.result} /></span>
          <span>
            <b style={{ fontWeight: 600 }}>{c.check}</b>
            {c.detail && <div className="muted small">{c.detail}</div>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Spinner() {
  return <span className="spin" aria-label="loading" />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="note crit">{error instanceof Error ? error.message : String(error)}</div>;
}

export function Drawer({ open, onClose, title, sub, children, actions, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; sub?: ReactNode; children: ReactNode; actions?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" style={wide ? { width: "min(1040px, 96vw)" } : undefined}>
        <div className="drawer-h">
          <div style={{ minWidth: 0 }}>
            <h2 style={{ wordBreak: "break-word" }}>{title}</h2>
            {sub && <div className="muted small" style={{ marginTop: 4 }}>{sub}</div>}
          </div>
          <div className="spacer" />
          {actions}
          <button className="btn ghost" onClick={onClose} aria-label="close">✕</button>
        </div>
        <div className="drawer-b">{children}</div>
      </aside>
    </>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { key: T; label: ReactNode; count?: number }[];
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((i) => (
        <button key={i.key} role="tab" aria-selected={value === i.key} className={value === i.key ? "on" : ""}
                onClick={() => onChange(i.key)}>
          {i.label}
          {i.count !== undefined && <span className="count">{i.count.toLocaleString("en-IN")}</span>}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return <label className="field">{label}{children}{hint && <span className="muted small" style={{ fontWeight: 400 }}>{hint}</span>}</label>;
}

export function Kv({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <div className="kv">
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <div>{k}</div>
          <div>{v}</div>
        </div>
      ))}
    </div>
  );
}

export function useDebounced<T>(v: T, ms = 300): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function Pager({ total, offset, limit, onChange }: {
  total: number; offset: number; limit: number; onChange: (o: number) => void;
}) {
  if (total <= limit) return <div className="pager">{total.toLocaleString("en-IN")} row(s)</div>;
  return (
    <div className="pager">
      {offset + 1}–{Math.min(total, offset + limit)} of {total.toLocaleString("en-IN")}
      <button className="btn sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>‹ Prev</button>
      <button className="btn sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next ›</button>
    </div>
  );
}

/** A small inline form: one reason/evidence text plus optional extra fields, then a submit. */
export function ReasonForm({ label, placeholder, button, onSubmit, busy, danger, extra }: {
  label: string; placeholder?: string; button: string; onSubmit: (text: string) => void; busy?: boolean;
  danger?: boolean; extra?: ReactNode;
}) {
  const [t, setT] = useState("");
  return (
    <div className="col" style={{ gap: 6 }}>
      <Field label={label}>
        <textarea className="input" rows={2} value={t} placeholder={placeholder} onChange={(e) => setT(e.target.value)}
                  style={{ fontFamily: "var(--font)" }} />
      </Field>
      {extra}
      <div className="row">
        <button className={`btn ${danger ? "danger" : "primary"}`} disabled={!t.trim() || busy} onClick={() => onSubmit(t.trim())}>
          {busy ? <Spinner /> : null}{button}
        </button>
      </div>
    </div>
  );
}

export function Who({ name, at }: { name?: string | null; at?: string | null }) {
  if (!name) return null;
  return <span className="who-badge">{name}{at ? ` · ${at.replace("T", " ").slice(0, 16)}` : ""}</span>;
}
