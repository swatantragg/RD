import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Role } from "./api";
import { useApp } from "./state";
import type { Job } from "./types";
import Overview from "./pages/Overview";
import Batches from "./pages/Batches";
import Sheets from "./pages/Sheets";
import Validation from "./pages/Validation";
import Viewer from "./pages/Viewer";
import Coverage from "./pages/Coverage";
import Merge from "./pages/Merge";
import Mismatch from "./pages/Mismatch";
import Statements from "./pages/Statements";
import Exports from "./pages/Exports";

const PAGES: { key: string; label: string; group: string; tag?: string; el: () => ReactNode }[] = [
  { key: "overview", label: "Overview", group: "Workspace", el: () => <Overview /> },
  { key: "batches", label: "Batches & Upload", group: "Ingest", tag: "§5-6", el: () => <Batches /> },
  { key: "sheets", label: "My Sheets", group: "Ingest", tag: "§5.6", el: () => <Sheets /> },
  { key: "validation", label: "Validation", group: "Ingest", tag: "§9 S2", el: () => <Validation /> },
  { key: "viewer", label: "RD Viewer (SKV)", group: "Analyse", tag: "§10", el: () => <Viewer /> },
  { key: "coverage", label: "Coverage Audit", group: "Analyse", tag: "§11", el: () => <Coverage /> },
  { key: "merge", label: "Merge Review", group: "Analyse", tag: "§12", el: () => <Merge /> },
  { key: "mismatch", label: "Mismatch Report", group: "Analyse", tag: "§13", el: () => <Mismatch /> },
  { key: "statements", label: "Statements & Gaps", group: "Analyse", tag: "§14", el: () => <Statements /> },
  { key: "exports", label: "Exports", group: "Deliver", tag: "§19", el: () => <Exports /> },
];

function useHashRoute(): [string, (k: string) => void] {
  const read = () => (window.location.hash.replace(/^#\/?/, "").split("?")[0] || "overview");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const h = () => setRoute(read());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  return [route, (k: string) => { window.location.hash = `/${k}`; }];
}

export default function App() {
  const [route, go] = useHashRoute();
  const page = PAGES.find((p) => p.key === route) ?? PAGES[0];
  const groups = [...new Set(PAGES.map((p) => p.group))];
  return (
    <div className="shell">
      <TopBar />
      <div className="body">
        <nav className="nav" aria-label="sections">
          {groups.map((g) => (
            <div key={g}>
              <div className="nav-group">{g}</div>
              {PAGES.filter((p) => p.group === g).map((p) => (
                <a key={p.key} className={p.key === page.key ? "active" : ""} onClick={() => go(p.key)}
                   href={`#/${p.key}`}>
                  {p.label}
                  {p.tag && <span className="tag">{p.tag}</span>}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <main className="main" key={page.key}>{page.el()}</main>
      </div>
      <JobTray />
    </div>
  );
}

function TopBar() {
  const { batches, batchId, setBatchId, builds, buildId, setBuildId, role, setRole, theme, setTheme } = useApp();
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden>
          <svg width="20" height="20" viewBox="0 0 32 32"><path d="M4 10c6 0 8 6 12 6s6-6 12-6M4 16c6 0 8 6 12 6s6-6 12-6M4 22c6 0 8 0 12 0" stroke="#fff" strokeWidth="2.6" fill="none" strokeLinecap="round" /></svg>
        </div>
        <div>
          <div className="brand-name">Sangam</div>
          <div className="brand-sub">IPRS royalty intelligence · SVF Entertainment</div>
        </div>
      </div>
      <div className="ctx">
        <label className="row small ink2">Batch
          <select className="input sm" value={batchId ?? ""} onChange={(e) => setBatchId(Number(e.target.value) || null)}>
            {!batches.length && <option value="">none yet</option>}
            {batches.map((b) => <option key={b.id} value={b.id}>#{b.id} {b.label}</option>)}
          </select>
        </label>
        <label className="row small ink2">Build
          <select className="input sm" value={buildId ?? ""} onChange={(e) => setBuildId(Number(e.target.value) || null)}>
            {!builds.length && <option value="">none yet</option>}
            {builds.map((b) => (
              <option key={b.id} value={b.id}>#{b.id} {b.label}{b.decisions ? ` · ${b.decisions} merges` : ""}</option>
            ))}
          </select>
        </label>
        <label className="row small ink2" title="Prototype RBAC - only analyst or admin may record merge decisions">Role
          <select className="input sm" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="viewer">viewer</option>
            <option value="analyst">analyst</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <select className="input sm" value={theme} onChange={(e) => setTheme(e.target.value as any)} aria-label="theme">
          <option value="system">theme: system</option>
          <option value="light">theme: light</option>
          <option value="dark">theme: dark</option>
        </select>
      </div>
    </header>
  );
}

function JobTray() {
  const { tracked, dismiss } = useApp();
  if (!tracked.length) return null;
  return (
    <div className="jobs" aria-live="polite">
      {tracked.map((t) => <JobCard key={t.id} id={t.id} label={t.label} onClose={() => dismiss(t.id)} />)}
    </div>
  );
}

function JobCard({ id, label, onClose }: { id: number; label: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["job", id], queryFn: () => api.get<Job>(`/jobs/${id}`), refetchInterval: false });
  const j = q.data;
  const done = j?.status === "succeeded" || j?.status === "failed";
  return (
    <div className="job">
      <div className="row">
        {!done && <span className="spin" />}
        {j?.status === "succeeded" && <span className="badge good">✓ done</span>}
        {j?.status === "failed" && <span className="badge crit">✕ failed</span>}
        <b className="small">{label}</b>
        <span className="spacer" />
        <button className="btn ghost sm" onClick={onClose} aria-label="dismiss">✕</button>
      </div>
      <div className="small ink2" style={{ marginTop: 4, wordBreak: "break-word" }}>{j?.message ?? "queued"}</div>
      {!done && <div className="bar"><i style={{ width: `${Math.round((j?.progress ?? 0) * 100)}%` }} /></div>}
    </div>
  );
}
