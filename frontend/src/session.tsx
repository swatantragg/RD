import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrf } from "./api";

export type ClientRef = { id: number; code: string; name: string };
export type Release = { version: string; date: string; summary: string; points: string[] };
export type Me = {
  id: number; email: string; name: string; roles: string[]; role_labels: string[]; csrf: string; version: string;
  can: { view: boolean; prepare: boolean; approve: boolean; draft_download: boolean; clients: boolean; manage: boolean;
    diagnostics: boolean };
  clients: ClientRef[]; whats_new: Release[]; member_since: string | null; last_sign_in: string | null;
};

/** 'Asha Rao' -> 'AR', 'Swatantra' -> 'S'. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0];
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

type Ctx = {
  me: Me; route: string; go: (r: string) => void; toast: (msg: string, bad?: boolean) => void; signOut: () => void;
  refreshMe: () => Promise<void>;
};
const C = createContext<Ctx | null>(null);
export const useApp = () => useContext(C)!;

export function useRoute(): [string, (r: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "");
  const [r, setR] = useState(read);
  useEffect(() => {
    const h = () => { setR(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  return [r, (x: string) => { window.location.hash = `/${x}`; }];
}

export function AppProvider({ me, setMe, onSignOut, children }: {
  me: Me; setMe: (m: Me) => void; onSignOut: () => void; children: ReactNode;
}) {
  const [route, go] = useRoute();
  const [note, setNote] = useState<{ msg: string; bad?: boolean } | null>(null);
  const toast = useCallback((msg: string, bad?: boolean) => {
    setNote({ msg, bad });
    window.setTimeout(() => setNote(null), bad ? 8000 : 4000);
  }, []);
  const refreshMe = useCallback(async () => {
    const m = await loadMe();
    if (m) setMe(m);
  }, [setMe]);
  return (
    <C.Provider value={{ me, route, go, toast, signOut: onSignOut, refreshMe }}>
      {children}
      {note && <div className={`toast ${note.bad ? "bad" : ""}`} role="status" aria-live="polite">{note.msg}</div>}
    </C.Provider>
  );
}

export async function loadMe(): Promise<Me | null> {
  try {
    const me = await api.get<Me>("/auth/me");
    setCsrf(me.csrf);
    return me;
  } catch {
    return null;
  }
}

/** Per-person conveniences only (the guide's 'dismissed' flag, the last client). Never business data. */
export const local = {
  get(key: string): string | null {
    try { return window.localStorage.getItem(`rd.${key}`); } catch { return null; }
  },
  set(key: string, v: string) {
    try { window.localStorage.setItem(`rd.${key}`, v); } catch { /* storage may be unavailable */ }
  },
};
