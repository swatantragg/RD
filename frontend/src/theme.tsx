import { useState } from "react";
import { local } from "./session";

export type Theme = "light" | "dark";

function system(): Theme {
  try { return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; } catch { return "light"; }
}

/** The person's choice wins; until they choose, the computer's setting is followed. */
export function currentTheme(): Theme {
  const t = local.get("theme");
  return t === "dark" || t === "light" ? t : system();
}

export function applyTheme(t: Theme, remember = false) {
  document.documentElement.dataset.theme = t;
  if (remember) local.set("theme", t);
}

export function ThemeToggle() {
  const [t, setT] = useState<Theme>(currentTheme());
  const next: Theme = t === "dark" ? "light" : "dark";
  return (
    <button type="button" className="btn ghost theme-toggle" aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}
            onClick={() => { applyTheme(next, true); setT(next); }}>
      <span aria-hidden>{t === "dark" ? "☀" : "☾"}</span> {t === "dark" ? "Light" : "Dark"}
    </button>
  );
}

/** Light / Dark choice as two buttons (profile menu and My profile). */
export function ThemeSwitch() {
  const [t, setT] = useState<Theme>(currentTheme());
  const pick = (x: Theme) => { applyTheme(x, true); setT(x); };
  return (
    <div className="seg theme-seg" role="radiogroup" aria-label="Theme">
      {(["light", "dark"] as Theme[]).map((x) => (
        <button key={x} type="button" role="radio" aria-checked={t === x} className={t === x ? "on" : ""} onClick={() => pick(x)}>
          <span aria-hidden>{x === "dark" ? "☾" : "☀"}</span> {x === "dark" ? "Dark" : "Light"}
        </button>
      ))}
    </div>
  );
}
