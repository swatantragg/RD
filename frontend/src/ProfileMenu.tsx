import { useEffect, useRef, useState } from "react";
import { initials, useApp } from "./session";
import { ThemeSwitch } from "./theme";

/** The initials button (top right) and its menu: profile, role, theme, sign out. */
export function ProfileMenu() {
  const { me, go, signOut } = useApp();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="profile" ref={box}>
      <button ref={button} type="button" className="avatar" aria-haspopup="true" aria-expanded={open}
              aria-label={`Profile menu for ${me.name}`} title={me.name} onClick={() => setOpen(!open)}>
        {initials(me.name)}
      </button>
      {open && (
        <div className="profile-menu" role="menu">
          <div className="pm-head">
            <span className="avatar big" aria-hidden>{initials(me.name)}</span>
            <div>
              <div className="pm-name">{me.name}</div>
              <div className="pm-email">{me.email}</div>
            </div>
          </div>
          <div className="pm-row"><span className="pm-label">Role</span><span>{me.role_labels.join(", ")}</span></div>
          <div className="pm-row"><span className="pm-label">Theme</span><ThemeSwitch /></div>
          <button type="button" role="menuitem" className="pm-item" onClick={() => { setOpen(false); go("settings/profile"); }}>
            My profile
          </button>
          <button type="button" role="menuitem" className="pm-item danger" onClick={() => { setOpen(false); signOut(); }}>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
