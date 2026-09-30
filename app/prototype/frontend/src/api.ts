// Thin fetch wrapper for the Sangam REST API. The user / role travel as headers
// (the prototype's stand-in for OIDC + RBAC - only analyst+ may decide a merge).

export type Role = "viewer" | "analyst" | "admin";

let identity: { user: string; role: Role } = { user: "analyst@svf", role: "analyst" };
export function setIdentity(user: string, role: Role) {
  identity = { user, role };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = { "X-User": identity.user, "X-Role": identity.role };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (raw) return res as unknown as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(path: string) => call<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => call<T>("POST", path, body ?? {}),
  patch: <T,>(path: string, body?: unknown) => call<T>("PATCH", path, body ?? {}),
  del: <T,>(path: string) => call<T>("DELETE", path),
  upload: <T,>(path: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return call<T>("POST", path, fd);
  },
  withTotal: async <T,>(path: string): Promise<{ items: T; total: number }> => {
    const res = await call<Response>("GET", path, undefined, true);
    return { items: (await res.json()) as T, total: Number(res.headers.get("X-Total-Count") ?? 0) };
  },
};

export function qs(params: Record<string, unknown>): string {
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) return;
    u.set(k, Array.isArray(v) ? v.join(",") : String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}
