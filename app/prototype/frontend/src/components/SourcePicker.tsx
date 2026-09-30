import { useState } from "react";
import { money } from "../format";

export interface Source { code: string; label: string; kind: string; statements?: number; reports?: number; total: number }

const GROUPS: [string, (s: Source) => boolean][] = [
  ["IPRS statements", (s) => s.kind === "statement" && !s.code.startsWith("overseas:")],
  ["Overseas societies", (s) => s.code.startsWith("overseas:")],
  ["Platform reports", (s) => s.kind.startsWith("platform")],
];

/** Revenue-source checklist, grouped; a group can be ticked or folded as a whole. */
export function SourcePicker({ sources, picked, onChange }: { sources: Source[]; picked: Set<string>; onChange: (s: Set<string>) => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ "IPRS statements": true, "Platform reports": true });
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row small">
        <button className="btn ghost sm" onClick={() => onChange(new Set(sources.map((s) => s.code)))}>all</button>
        <button className="btn ghost sm" onClick={() => onChange(new Set())}>none</button>
        <span className="muted">{picked.size} of {sources.length} ticked</span>
      </div>
      {GROUPS.map(([g, f]) => {
        const items = sources.filter(f);
        if (!items.length) return null;
        const on = items.filter((s) => picked.has(s.code)).length;
        const setGroup = (v: boolean) => {
          const n = new Set(picked);
          items.forEach((s) => (v ? n.add(s.code) : n.delete(s.code)));
          onChange(n);
        };
        return (
          <div key={g}>
            <div className="row small">
              <label className="check">
                <input type="checkbox" checked={on === items.length} ref={(el) => { if (el) el.indeterminate = on > 0 && on < items.length; }}
                       onChange={(e) => setGroup(e.target.checked)} />
                <b>{g}</b>
              </label>
              <span className="muted">{on}/{items.length}</span>
              <span className="spacer" />
              <button className="btn ghost sm" onClick={() => setOpen({ ...open, [g]: !open[g] })}>{open[g] ? "hide" : "show"}</button>
            </div>
            {open[g] && (
              <div className="col" style={{ gap: 3, margin: "4px 0 0 22px" }}>
                {items.map((s) => (
                  <label key={s.code} className="check small">
                    <input type="checkbox" checked={picked.has(s.code)} onChange={(e) => {
                      const n = new Set(picked);
                      e.target.checked ? n.add(s.code) : n.delete(s.code);
                      onChange(n);
                    }} />
                    {s.label.replace(/^Overseas - /, "")}
                    <span className="muted">· {s.statements ? `${s.statements} stmt` : `${s.reports} report`} · {money(s.total)}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
