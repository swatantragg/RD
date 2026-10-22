// Small building blocks shared by the reconciliation pages: pager, filters, labelled amounts, form pop-ups.
import { useEffect, useState, type ReactNode } from "react";
import { useApp } from "./session";
import { int, isBlank, mon, type Num } from "./format";
import { Button, Dialog, Money, Notice, Pill, Select, type Option, type Tone } from "./ui";
import { ClientDialog } from "./pages/Clients";

/** Every work page needs a client; with one client there is nothing to choose. */
export function ClientPicker() {
  const { me, clientId, setClientId } = useApp();
  if (me.clients.length < 2) return null;
  return (
    <span className="client-pick">
      <Select size="sm" label="Client" value={clientId ? String(clientId) : ""}
              onChange={(v) => setClientId(Number(v))}
              options={me.clients.map((c) => ({ value: String(c.id), label: c.name, meta: c.code }))} />
    </span>
  );
}

/** The client a work page shows, chosen on the page itself (the choice is shared by every page and remembered in
 *  this browser). Whoever may add clients finds '+ Add a client' at the end of the list. */
export function ClientSelect({ label = "Client", hint }: { label?: string; hint?: ReactNode }) {
  const { me, clientId, setClientId } = useApp();
  const [adding, setAdding] = useState(false);
  const options: Option[] = me.clients.map((c) => ({ value: String(c.id), label: c.name, meta: c.code }));
  if (me.can.clients) options.push({ value: "__add", label: "+ Add a client", hint: "Its statements and catalogue are kept apart" });
  return (
    <div className="client-select">
      <span className="client-select-l">{label}</span>
      <Select label={label} value={clientId ? String(clientId) : ""} placeholder="Choose a client" options={options}
              onChange={(v) => (v === "__add" ? setAdding(true) : setClientId(Number(v)))} />
      {hint && <span className="muted small">{hint}</span>}
      {adding && <ClientDialog client={null} onDone={(_created, id) => { setAdding(false); if (id) setClientId(id); }} />}
    </div>
  );
}

/** 'Clear filters': puts every filter of a list back to its starting value. Greyed out while nothing is filtered. */
export function ResetFilters({ active, onReset }: { active: boolean; onReset: () => void }) {
  return (
    <Button kind="ghost" className="sm reset-filters" disabled={!active} onClick={onReset} title="Put every filter back to its starting value">
      <span aria-hidden>↺</span> Clear filters
    </Button>
  );
}

/** True when any value differs from the starting values (keys in `ignore` are not filters, e.g. paging). */
export function changed<T extends object>(cur: T, start: T): boolean {
  return (Object.keys(start) as (keyof T)[]).some((k) => cur[k] !== start[k]);
}

export function NeedClient({ children }: { children: (clientId: number) => ReactNode }) {
  const { clientId } = useApp();
  if (!clientId) return <Notice tone="warn">You do not have access to a client yet. Ask an Admin to give you access.</Notice>;
  return <>{children(clientId)}</>;
}

export function Pager({ total, offset, size, onChange }: { total: number; offset: number; size: number;
  onChange: (o: number) => void }) {
  // the list shrank under the page shown (items reviewed out of a filter, rows deleted): go to its last page
  useEffect(() => { if (offset > 0 && offset >= total) onChange(Math.max(0, Math.ceil(total / size) - 1) * size); }, [offset, total, size]); // eslint-disable-line react-hooks/exhaustive-deps
  if (total <= size) return total ? <div className="pager muted small">{int(total)} shown</div> : null;
  return (
    <div className="pager">
      <span className="muted small">{int(offset + 1)}–{int(Math.min(total, offset + size))} of {int(total)}</span>
      <Button kind="ghost" className="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>Previous</Button>
      <Button kind="ghost" className="sm" disabled={offset + size >= total} onClick={() => onChange(offset + size)}>Next</Button>
    </div>
  );
}

/** A percentage given as exact text; blank stays blank. */
export function Pct({ v, digits = 2 }: { v: Num; digits?: number }) {
  if (isBlank(v)) return <span className="blank" title="not calculated">—</span>;
  return <span className="num">{Number(v).toFixed(digits)} %</span>;
}

/** An amount that may be missing for a reason the reader must see (never shown as 0.00). */
export function Amount({ v, missing }: { v: Num; missing?: string }) {
  if (isBlank(v)) return <span className="blank" title={missing ?? "no amount"}>{missing ? <i className="muted small">{missing}</i> : "—"}</span>;
  return <Money v={v} />;
}

export const MAPPING_TONE: Record<string, Tone> = { VERIFIED: "good", PENDING: "warn", CONFLICT: "bad", UNKNOWN: "bad",
  NO_ISRC: "bad", NONE: "neutral", REJECTED: "neutral", WORK_NOT_FOUND: "bad", NO_WORK_NUMBER: "bad", MATCHED: "good" };
export const MAPPING_TEXT: Record<string, string> = { VERIFIED: "Verified", PENDING: "Needs verification",
  CONFLICT: "Conflict", UNKNOWN: "Not in catalogue", NO_ISRC: "No ISRC", NONE: "No ISRC", REJECTED: "Rejected",
  WORK_NOT_FOUND: "Work not in catalogue", NO_WORK_NUMBER: "No work number", MATCHED: "Matched" };
export function MappingPill({ status }: { status: string }) {
  return <Pill tone={MAPPING_TONE[status] ?? "neutral"}>{MAPPING_TEXT[status] ?? status}</Pill>;
}

export const STATEMENT_TONE: Record<string, Tone> = { IMPORTED: "good", NEEDS_REVIEW: "warn", REJECTED: "bad",
  DUPLICATE: "neutral", SUPERSEDED: "neutral", EXCLUDED: "neutral" };

export function period(a?: string | null, b?: string | null): string {
  return a && b ? (a.slice(0, 7) === b.slice(0, 7) ? mon(a) : `${mon(a)} – ${mon(b)}`) : "Period not stated";
}

/** Month inputs for a usage period, plus quick Indian financial-year choices. */
export function PeriodPicker({ from, to, onChange }: { from: string; to: string;
  onChange: (from: string, to: string) => void }) {
  const now = new Date();
  const fyNow = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  const fys: Option[] = [{ value: "", label: "Any period" }, ...[0, 1, 2, 3].map((k) => {
    const y = fyNow - k;
    return { value: String(y), label: `FY ${y}-${String(y + 1).slice(2)}`, hint: `Apr ${y} – Mar ${y + 1}` };
  })];
  const fy = fys.find((f) => f.value && from === `${f.value}-04` && to === `${Number(f.value) + 1}-03`)?.value ?? "";
  return (
    <span className="period-pick">
      <label className="field inline">From<input className="input sm" type="month" value={from} max={to || undefined}
                                                 onChange={(e) => onChange(e.target.value, to)} /></label>
      <label className="field inline">To<input className="input sm" type="month" value={to} min={from || undefined}
                                               onChange={(e) => onChange(from, e.target.value)} /></label>
      <Select size="sm" label="Financial year" value={fy} placeholder="Financial year"
              onChange={(v) => (v ? onChange(`${v}-04`, `${Number(v) + 1}-03`) : onChange("", ""))} options={fys} />
    </span>
  );
}

/** 'YYYY-MM' month inputs -> API dates (first day / last day of the month). */
export function monthStart(m: string): string | undefined { return m ? `${m}-01` : undefined; }
export function monthEnd(m: string): string | undefined {
  if (!m) return undefined;
  const [y, mm] = m.split("-").map(Number);
  return new Date(Date.UTC(y, mm, 0)).toISOString().slice(0, 10);
}

/** A pop-up with a small form; the action runs on submit and the pop-up closes when it succeeds. */
export function FormDialog({ title, sub, submit, onClose, onSubmit, children, danger, wide }: {
  title: ReactNode; sub?: ReactNode; submit: string; onClose: () => void; onSubmit: () => Promise<unknown>;
  children?: ReactNode; danger?: boolean; wide?: boolean;
}) {
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={title} sub={sub} onClose={onClose} wide={wide}>
      <form className="form full" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try { await onSubmit(); onClose(); } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
      }}>
        {children}
        <div className="actions end">
          <Button type="button" onClick={onClose}>Cancel</Button>
          <Button kind={danger ? "danger" : "primary"} type="submit" busy={busy}>{submit}</Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Upload one or more files to an endpoint; shows each file's result. */
export function DropZone({ label, hint, multiple, onFiles }: { label: string; hint: string; multiple?: boolean;
  onFiles: (files: File[]) => void }) {
  const [over, setOver] = useState(false);
  let input: HTMLInputElement | null = null;
  return (
    <div className={`drop ${over ? "over" : ""}`} role="button" tabIndex={0}
         onClick={() => input?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input?.click()}
         onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
         onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(Array.from(e.dataTransfer.files)); }}>
      <div className="drop-t">{label}</div>
      <div className="muted small">{hint}</div>
      <Button kind="primary" type="button" onClick={(e) => { e.stopPropagation(); input?.click(); }}>Choose file{multiple ? "s" : ""}</Button>
      <input ref={(el) => { input = el; }} type="file" multiple={multiple} accept=".xlsx,.csv" hidden
             onChange={(e) => { onFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
    </div>
  );
}

/** Text that states the selection an export will contain, shown next to the export button. */
export function Selection({ parts }: { parts: (string | false | null | undefined)[] }) {
  const shown = parts.filter(Boolean) as string[];
  return <span className="muted small">Export contains: {shown.length ? shown.join(" · ") : "everything"}</span>;
}

export function Facts({ items }: { items: [ReactNode, ReactNode][] }) {
  return <dl className="facts">{items.filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v], i) =>
    <span key={i} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></span>)}</dl>;
}
