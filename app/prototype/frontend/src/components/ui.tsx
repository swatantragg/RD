import { useEffect, useState, type ReactNode } from "react";
import { money } from "../format";
import type { Invariant } from "../types";

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

export function PageHead({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
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

export function Money({ v, dimZero, title }: { v: number | null | undefined; dimZero?: boolean; title?: string }) {
  if (v === null || v === undefined) return <span className="blank" />;
  return (
    <span className={`num ${dimZero && v === 0 ? "zero-booked" : ""}`} title={title}>
      {money(v)}
    </span>
  );
}

export function Blank() {
  return <span className="blank" title="not in any source">&nbsp;</span>;
}

export function IsrcChips({ isrcs, unreg = [], max = 3 }: { isrcs: string[]; unreg?: string[]; max?: number }) {
  const [open, setOpen] = useState(false);
  if (!isrcs.length) return <Blank />;
  const shown = open ? isrcs : isrcs.slice(0, max);
  const u = new Set(unreg);
  return (
    <span className="chips">
      {shown.map((i) => (
        <span key={i} className={`chip ${u.has(i) ? "unreg" : ""}`}
              title={u.has(i) ? "reported by the platform - NOT registered in the catalogue" : "registered in the catalogue"}>
          {i}
        </span>
      ))}
      {isrcs.length > max && (
        <span className="chip plain btnlike" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {open ? "less" : `+${isrcs.length - max}`}
        </span>
      )}
    </span>
  );
}

export function WorkChips({ works, unreg = [] }: { works: string[]; unreg?: string[] }) {
  if (!works.length) return <Blank />;
  const u = new Set(unreg);
  return (
    <span className="chips">
      {works.map((w) => (
        <span key={w} className={`chip ${u.has(w) ? "unreg" : ""}`}
              title={u.has(w) ? "paid by a statement - NOT in the catalogue" : "IPRS work number"}>
          {w}
        </span>
      ))}
    </span>
  );
}

const STATUS_SHORT: Record<string, string> = {
  IN_RECEIVED: "In list · royalty received",
  IN_NONE: "In list · no royalty",
  NOT_PAID: "NOT in list · paid by a statement",
  IN_SIBLING: "In list · booked on another row",
  NOT_PLATFORM: "NOT in list · revenue report only",
  IN_ZERO: "In list · named, 0.00",
  NOT_ZERO: "NOT in list · named, 0.00",
  NOT_USAGE: "NOT in list · streams only",
};
export const statusShort = (code: string) => STATUS_SHORT[code] ?? code;
export const STATUS_CODES = Object.keys(STATUS_SHORT);

export function StatusChip({ code, full }: { code: string; full?: string }) {
  return (
    <span className={`status-chip s-${code}`} title={full}>
      <span className="dot" />
      {statusShort(code)}
    </span>
  );
}

const NAME_BASES = new Set(["B4", "B5", "B6"]);
export function BasisChips({ codes, labels }: { codes: string[]; labels?: Record<string, string> }) {
  if (!codes.length) return <Blank />;
  return (
    <span className="chips">
      {codes.map((c) => (
        <span key={c} className={`chip basis-chip ${NAME_BASES.has(c) ? "name" : ""}`}
              title={(labels?.[c] ?? c) + (NAME_BASES.has(c) ? " - a song name moved money" : "")}>
          {c}{NAME_BASES.has(c) ? " · name" : ""}
        </span>
      ))}
    </span>
  );
}

export function Badge({ tone, children, title }: { tone: "good" | "warn" | "crit" | "info" | "neutral"; children: ReactNode; title?: string }) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>;
}

export function PassBadge({ ok, label }: { ok: boolean; label?: string }) {
  return ok ? <Badge tone="good">✓ {label ?? "PASS"}</Badge> : <Badge tone="crit">✕ {label ?? "FAIL"}</Badge>;
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

export function Drawer({ open, onClose, title, sub, children, actions }: {
  open: boolean; onClose: () => void; title: ReactNode; sub?: ReactNode; children: ReactNode; actions?: ReactNode;
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
      <aside className="drawer" role="dialog" aria-modal="true">
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
          {i.count !== undefined && <span className="count">{i.count.toLocaleString("en-US")}</span>}
        </button>
      ))}
    </div>
  );
}

export function Seg<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { key: T; label: ReactNode; title?: string }[];
}) {
  return (
    <span className="seg">
      {items.map((i) => (
        <button key={i.key} className={value === i.key ? "on" : ""} onClick={() => onChange(i.key)} title={i.title}>
          {i.label}
        </button>
      ))}
    </span>
  );
}

export function InvariantList({ items, compact }: { items: Invariant[]; compact?: boolean }) {
  if (!items?.length) return <div className="muted small">No invariants recorded.</div>;
  return (
    <div className="inv">
      {items.map((i) => (
        <InvariantRow key={i.id} i={i} compact={compact} />
      ))}
    </div>
  );
}

function InvariantRow({ i, compact }: { i: Invariant; compact?: boolean }) {
  return (
    <>
      <span className={i.passed ? "ok" : "bad"} aria-label={i.passed ? "pass" : "fail"}>{i.passed ? "✓" : "✕"}</span>
      <span className="id">{i.id}</span>
      <span>
        {i.label}
        {i.detail && !compact && <div className="muted small">{i.detail}</div>}
      </span>
      <span className="val">{String(i.actual)}</span>
    </>
  );
}

export function ConfBar({ value, band }: { value: number; band: string }) {
  return (
    <span className="conf" title={`confidence ${value.toFixed(2)} - ${band}`}>
      <span className="track"><i style={{ width: `${Math.round(value * 100)}%` }} /></span>
      <b className="num">{value.toFixed(2)}</b>
      <Badge tone={band === "suggested" ? "good" : band === "review" ? "warn" : "neutral"}>{band}</Badge>
    </span>
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

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="field">{label}{children}</label>;
}
