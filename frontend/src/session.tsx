import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrf } from "./api";

export type ClientRef = { id: number; code: string; name: string };
export type Release = { version: string; date: string; summary: string; points: string[] };
export type Role = "SUPER_ADMIN" | "ADMIN" | "USER";
export type Capability = "view" | "prepare" | "draft_download" | "clients" | "manage" | "diagnostics" | "platforms"
  | "verify_mappings" | "approve_enquiries" | "assign_followups" | "close_enquiries" | "audit" | "reset_passwords"
  | "settings" | "clear_statements" | "clear_catalogue";
export type Me = {
  id: number; email: string; name: string; role: Role; role_label: string; roles: string[]; role_labels: string[];
  must_change_password: boolean; csrf: string; version: string; can: Record<Capability, boolean>;
  clients: ClientRef[]; whats_new: Release[]; member_since: string | null; last_sign_in: string | null;
};

/** 'First Last' -> 'FL', 'First' -> 'F'. */
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
  /** The client the work pages show (remembered per browser; only a convenience). */
  clientId: number | undefined; setClientId: (id: number) => void; client: ClientRef | undefined;
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
  const [picked, setPicked] = useState<number | undefined>(() => Number(local.get("client")) || undefined);
  const client = me.clients.find((c) => c.id === picked) ?? me.clients[0];
  const setClientId = useCallback((id: number) => { local.set("client", String(id)); setPicked(id); }, []);
  return (
    <C.Provider value={{ me, route, go, toast, signOut: onSignOut, refreshMe, clientId: client?.id, setClientId, client }}>
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
