import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setIdentity, type Role } from "./api";
import type { Batch, BuildListItem, Job, Meta } from "./types";

type Theme = "system" | "light" | "dark";
interface Tracked {
  id: number;
  label: string;
  onDone?: (job: Job) => void;
}

interface Ctx {
  batchId: number | null;
  setBatchId: (id: number | null) => void;
  buildId: number | null;
  setBuildId: (id: number | null) => void;
  role: Role;
  setRole: (r: Role) => void;
  user: string;
  theme: Theme;
  setTheme: (t: Theme) => void;
  track: (jobId: number, label: string, onDone?: (job: Job) => void) => void;
  tracked: Tracked[];
  dismiss: (id: number) => void;
  meta: Meta | undefined;
  batches: Batch[];
  builds: BuildListItem[];
  canDecide: boolean;
}

const AppCtx = createContext<Ctx | null>(null);

function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function store(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage unavailable - the value simply is not remembered */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [batchId, setBatchIdS] = useState<number | null>(() => stored("sangam.batch", null));
  const [buildId, setBuildIdS] = useState<number | null>(() => stored("sangam.build", null));
  const [role, setRoleS] = useState<Role>(() => stored("sangam.role", "analyst"));
  const [theme, setThemeS] = useState<Theme>(() => stored("sangam.theme", "system"));
  const [tracked, setTracked] = useState<Tracked[]>([]);
  const user = `${role}@svf`;
  setIdentity(user, role);

  useEffect(() => {
    const el = document.documentElement;
    if (theme === "system") el.removeAttribute("data-theme");
    else el.setAttribute("data-theme", theme);
  }, [theme]);

  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/meta"), staleTime: 60_000 });
  const batchesQ = useQuery({ queryKey: ["batches"], queryFn: () => api.get<Batch[]>("/batches") });
  const batches = batchesQ.data ?? [];
  const effectiveBatch = batchId && batches.some((b) => b.id === batchId) ? batchId : batches[0]?.id ?? null;
  const buildsQ = useQuery({
    queryKey: ["builds", effectiveBatch],
    queryFn: () => api.get<BuildListItem[]>(`/builds?batch_id=${effectiveBatch}`),
    enabled: !!effectiveBatch,
  });
  const builds = buildsQ.data ?? [];
  const effectiveBuild = buildId && builds.some((b) => b.id === buildId) ? buildId : builds[0]?.id ?? null;

  const setBatchId = useCallback((id: number | null) => {
    setBatchIdS(id);
    store("sangam.batch", id);
    setBuildIdS(null);
    store("sangam.build", null);
  }, []);
  const setBuildId = useCallback((id: number | null) => {
    setBuildIdS(id);
    store("sangam.build", id);
  }, []);
  const setRole = useCallback((r: Role) => {
    setRoleS(r);
    store("sangam.role", r);
    setIdentity(`${r}@svf`, r);
  }, []);
  const setTheme = useCallback((t: Theme) => {
    setThemeS(t);
    store("sangam.theme", t);
  }, []);

  const callbacks = useRef(new Map<number, (job: Job) => void>());
  const finished = useRef(new Set<number>());
  const track = useCallback((id: number, label: string, onDone?: (job: Job) => void) => {
    if (onDone) callbacks.current.set(id, onDone);
    setTracked((t) => [...t.filter((x) => x.id !== id), { id, label }]);
  }, []);
  const dismiss = useCallback((id: number) => setTracked((t) => t.filter((x) => x.id !== id)), []);

  // poll every tracked job until it finishes, then refresh everything it may have changed
  useEffect(() => {
    if (!tracked.length) return;
    const timer = setInterval(async () => {
      for (const t of tracked) {
        try {
          const j = await api.get<Job>(`/jobs/${t.id}`);
          qc.setQueryData(["job", t.id], j);
          if ((j.status === "succeeded" || j.status === "failed") && !finished.current.has(t.id)) {
            finished.current.add(t.id);
            const cb = callbacks.current.get(t.id);
            callbacks.current.delete(t.id);
            cb?.(j);
            qc.invalidateQueries();
            if (j.status === "succeeded") setTimeout(() => dismiss(t.id), 6000);
          }
        } catch {
          /* transient - keep polling */
        }
      }
    }, 700);
    return () => clearInterval(timer);
  }, [tracked, qc, dismiss]);

  const value = useMemo<Ctx>(
    () => ({
      batchId: effectiveBatch, setBatchId, buildId: effectiveBuild, setBuildId, role, setRole, user, theme,
      setTheme, track, tracked, dismiss, meta: meta.data, batches, builds,
      canDecide: role === "analyst" || role === "admin",
    }),
    [effectiveBatch, setBatchId, effectiveBuild, setBuildId, role, setRole, user, theme, setTheme, track, tracked,
      dismiss, meta.data, batches, builds],
  );
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}

/** Start a job-returning POST and track it; the callback fires when the job finishes. */
export function useRunJob() {
  const { track } = useApp();
  return useCallback(
    async (label: string, start: () => Promise<{ job_id: number }>, onDone?: (job: Job) => void) => {
      const { job_id } = await start();
      track(job_id, label, onDone);
      return job_id;
    },
    [track],
  );
}
