import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setCsrf } from "./api";

export type Me = { id: number; email: string; name: string; roles: string[]; permissions: string[]; csrf: string };
export type Meta = {
  roles: Record<string, string>; outcomes: Record<string, string>; hold_reasons: string[]; p_status: Record<string, string>;
  use_types: string[]; right_scopes: string[]; platforms: string[]; meta_fields: string[];
  required_meta: Record<string, string[]>; demo: boolean;
};
export type Client = {
  id: number; code: string; name: string; kind: string; society: string; member_id: string | null;
  beneficiary_name: string | null; mandate_verified: boolean; mandate_ref: string | null; mandate_from: string | null;
  mandate_to: string | null; territories: string[]; controlled_share: string | null; collection_route: string;
  contact_email: string | null; notes: string | null; files: number; open_cases: number;
};

type Ctx = {
  me: Me; meta: Meta | undefined; clients: Client[]; client: Client | undefined; clientId: number | undefined;
  setClientId: (id: number) => void; can: (p: string) => boolean; toast: (msg: string, bad?: boolean) => void;
  signOut: () => void; go: (route: string) => void; route: string;
};
const C = createContext<Ctx | null>(null);
export const useApp = () => useContext(C)!;

export function useRoute(): [string, (r: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "") || "overview";
  const [r, setR] = useState(read);
  useEffect(() => {
    const h = () => setR(read());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  return [r, (x: string) => { window.location.hash = `/${x}`; }];
}

export function AppProvider({ me, onSignOut, children }: { me: Me; onSignOut: () => void; children: ReactNode }) {
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/meta"), staleTime: Infinity });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.get<Client[]>("/clients") });
  const [clientId, setClient] = useState<number | undefined>(() => {
    const v = localStorage.getItem("mrm.client");
    return v ? Number(v) : undefined;
  });
  const list = clients.data ?? [];
  const cid = list.find((c) => c.id === clientId)?.id ?? list[0]?.id;
  const [note, setNote] = useState<{ msg: string; bad?: boolean } | null>(null);
  const [route, go] = useRoute();
  const toast = useCallback((msg: string, bad?: boolean) => {
    setNote({ msg, bad });
    setTimeout(() => setNote(null), bad ? 7000 : 3500);
  }, []);
  const value: Ctx = {
    me, meta: meta.data, clients: list, client: list.find((c) => c.id === cid), clientId: cid,
    setClientId: (id) => { localStorage.setItem("mrm.client", String(id)); setClient(id); qc.invalidateQueries(); },
    can: (p) => me.permissions.includes(p), toast, signOut: onSignOut, go, route,
  };
  return (
    <C.Provider value={value}>
      {children}
      {note && <div className={`toast ${note.bad ? "crit" : ""}`} role="status">{note.msg}</div>}
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
