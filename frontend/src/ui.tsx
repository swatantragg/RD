import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent as KeyEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
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
  FAILED: "bad", NEEDS_REVIEW: "warn", READY: "good", PUBLISHING: "info", PUBLISHED: "good" };
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
  title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean | "xl";
}) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>("input:not([disabled]):not([tabindex='-1']), textarea, button");
    first?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    document.body.classList.add("no-scroll");
    return () => { document.removeEventListener("keydown", esc); document.body.classList.remove("no-scroll"); prev?.focus(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="modal-back">
      <div ref={box} className={`modal ${wide === "xl" ? "xl" : wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={id}>
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

export type Option = { value: string; label: string; hint?: string; meta?: string; tone?: Tone };

/** The app's own drop-down list (a select-only combobox): styled in both themes, a tick on the current choice, keyboard
 *  support (arrows, Home/End, Enter, Esc, first letters). Focus stays on the button while the list is open. */
export function Select({ value, options, onChange, placeholder = "Choose…", label, size, required, disabled, className }: {
  value: string; options: Option[]; onChange: (v: string) => void; placeholder?: string; label?: string;
  size?: "sm"; required?: boolean; disabled?: boolean; className?: string;
}) {
  const id = useId();
  const btn = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: "", at: 0 });
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<CSSProperties>({});
  const current = options.findIndex((o) => o.value === value);
  const shown = current >= 0 ? options[current] : undefined;
  const last = options.length - 1;

  function place() {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.min(Math.max(r.width, 280), window.innerWidth - 16);
    const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
    const below = window.innerHeight - r.bottom - 14, above = r.top - 14;
    const want = Math.min(options.length * 46 + 14, 360);
    setPos(below < want && above > below
      ? { left, width, bottom: window.innerHeight - r.top + 6, maxHeight: Math.min(360, above) }
      : { left, width, top: r.bottom + 6, maxHeight: Math.min(360, below) });
  }
  function show(at = current) {
    if (disabled || !options.length) return;
    place();
    setActive(Math.max(0, Math.min(at, last)));
    setOpen(true);
  }
  function pick(i: number) {
    setOpen(false);
    btn.current?.focus();
    const o = options[i];
    if (o && o.value !== value) onChange(o.value);
  }
  function seek(ch: string): number {
    const t = typed.current, now = Date.now();
    t.text = now - t.at < 700 ? t.text + ch.toLowerCase() : ch.toLowerCase();
    t.at = now;
    const from = open ? active : Math.max(current, 0);
    const start = t.text.length === 1 ? from + 1 : from;
    for (let k = 0; k < options.length; k++) {
      const i = (start + k) % options.length;
      if (options[i].label.toLowerCase().startsWith(t.text)) return i;
    }
    return -1;
  }
  function key(e: KeyEvent) {
    if (e.key.length === 1 && e.key !== " " && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const i = seek(e.key);
      if (i >= 0) { if (open) setActive(i); else show(i); }
      return;
    }
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); show(); }
      return;
    }
    const to = { ArrowDown: Math.min(last, active + 1), ArrowUp: Math.max(0, active - 1), Home: 0, End: last,
      PageDown: Math.min(last, active + 8), PageUp: Math.max(0, active - 8) }[e.key];
    if (to !== undefined) { e.preventDefault(); setActive(to); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }     // not the pop-up
    else if (e.key === "Tab") setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!btn.current?.contains(t) && !list.current?.contains(t)) setOpen(false);
    };
    const move = (e: Event) => { if (!(e.target instanceof Node && list.current?.contains(e.target))) place(); };
    document.addEventListener("pointerdown", away, true);
    window.addEventListener("scroll", move, true);
    window.addEventListener("resize", move);
    return () => {
      document.removeEventListener("pointerdown", away, true);
      window.removeEventListener("scroll", move, true);
      window.removeEventListener("resize", move);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (open) list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  return (
    <span className={`select ${size ?? ""} ${className ?? ""}`}>
      <button ref={btn} type="button" role="combobox" className={`input select-btn ${size ?? ""} ${open ? "open" : ""}`}
              aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-list`} aria-label={label}
              aria-activedescendant={open ? `${id}-${active}` : undefined} aria-required={required || undefined}
              disabled={disabled} onClick={() => (open ? setOpen(false) : show())} onKeyDown={key}>
        {shown?.tone && <span className={`dot ${shown.tone}`} aria-hidden />}
        <span className={`select-val ${shown ? "" : "placeholder"}`}>{shown ? shown.label : placeholder}</span>
        {shown?.meta && <span className="select-meta">{shown.meta}</span>}
        <span className="select-chev" aria-hidden />
      </button>
      {required && <input className="select-req" tabIndex={-1} aria-hidden required value={value} onChange={() => undefined}
                          onFocus={() => btn.current?.focus()} />}
      {open && createPortal(
        <ul ref={list} id={`${id}-list`} role="listbox" aria-label={label} className="select-list" style={pos}>
          {options.map((o, i) => (
            <li key={o.value} id={`${id}-${i}`} role="option" aria-selected={o.value === value}
                className={`select-opt ${i === active ? "active" : ""} ${o.value === value ? "on" : ""}`}
                onPointerMove={() => i !== active && setActive(i)} onPointerDown={(e) => e.preventDefault()}
                onClick={() => pick(i)}>
              {o.tone && <span className={`dot ${o.tone}`} aria-hidden />}
              <span className="select-opt-t">{o.label}{o.hint && <span className="select-opt-h">{o.hint}</span>}</span>
              {o.meta && <span className="select-meta">{o.meta}</span>}
              <span className="select-tick" aria-hidden />
            </li>
          ))}
        </ul>,
        btn.current?.closest(".modal") ?? document.body)}
    </span>
  );
}

/** A wide table: a second scroll bar on top, kept in step with the one at the bottom, and hold-and-drag to scroll
 *  (sideways and down). A press that does not move is still a normal click. */
export function ScrollX({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const top = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [over, setOver] = useState(false);
  const [dragging, setDragging] = useState(false);
  useLayoutEffect(() => {
    const b = box.current;
    if (!b) return;
    const measure = () => { setWidth(b.scrollWidth); setOver(b.scrollWidth > b.clientWidth + 1); };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(b);
    Array.from(b.children).forEach((c) => ro.observe(c));
    const mo = new MutationObserver(() => { Array.from(b.children).forEach((c) => ro.observe(c)); measure(); });
    mo.observe(b, { childList: true });
    return () => { ro.disconnect(); mo.disconnect(); };
  }, []);
  const sync = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (from && to && Math.abs(to.scrollLeft - from.scrollLeft) > 0.5) to.scrollLeft = from.scrollLeft;
  };
  const press = (e: React.PointerEvent<HTMLDivElement>) => {
    const b = box.current;
    if (!b || e.button !== 0 || e.pointerType !== "mouse") return;
    if ((e.target as HTMLElement).closest("input, textarea, select, button, a, label, [role='combobox'], [contenteditable]")) return;
    e.preventDefault();                                   // a drag scrolls; it does not select text
    const x0 = e.clientX, y0 = e.clientY, l0 = b.scrollLeft, t0 = b.scrollTop;
    let moved = false;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0, dy = ev.clientY - y0;
      if (!moved && Math.abs(dx) < 5 && Math.abs(dy) < 5) return;
      if (!moved) { moved = true; setDragging(true); window.getSelection()?.removeAllRanges(); }
      b.scrollLeft = l0 - dx;
      b.scrollTop = t0 - dy;
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (moved) {
        setDragging(false);
        const stop = (ev: MouseEvent) => { ev.stopPropagation(); ev.preventDefault(); };
        window.addEventListener("click", stop, { capture: true, once: true });
        window.setTimeout(() => window.removeEventListener("click", stop, { capture: true }), 0);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div className="scrollx">
      <div ref={top} className={`scrollx-top ${over ? "" : "off"}`} aria-hidden onScroll={() => sync(top.current, box.current)}>
        <div style={{ width }} />
      </div>
      <div ref={box} className={`tbl-wrap ${className ?? ""} ${over ? "grab" : ""} ${dragging ? "dragging" : ""}`}
           tabIndex={over ? 0 : undefined} role={over ? "region" : undefined} aria-label={over ? label ?? "Table (scrolls sideways)" : undefined}
           onScroll={() => sync(box.current, top.current)} onPointerDown={press}>
        {children}
      </div>
    </div>
  );
}
