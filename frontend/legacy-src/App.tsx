import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { AppProvider, loadMe, useApp, type Me } from "./state";
import { Spinner } from "./components/ui";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Intake from "./pages/Intake";
import Identity from "./pages/Identity";
import Rules from "./pages/Rules";
import Compare from "./pages/Compare";
import Packs from "./pages/Packs";
import Cases from "./pages/Cases";
import Clients from "./pages/Clients";
import Audit from "./pages/Audit";
import People from "./pages/People";

const NAV: { group: string; items: { key: string; label: string; tag?: string; perm?: string }[] }[] = [
  { group: "Workflow", items: [
    { key: "overview", label: "Overview" },
    { key: "intake", label: "Intake & validation", tag: "A–B" },
    { key: "identity", label: "Works & recordings", tag: "C" },
    { key: "rules", label: "Comparison rules", tag: "E" },
    { key: "compare", label: "Comparison", tag: "D·F·G" },
    { key: "packs", label: "Report packs", tag: "H1–H4" },
    { key: "cases", label: "Enquiry cases", tag: "H5" },
  ] },
  { group: "Setup", items: [
    { key: "clients", label: "Clients & mandates" },
    { key: "audit", label: "Audit log", perm: "audit" },
    { key: "people", label: "People & roles" },
  ] },
];

function Shell() {
  const { me, clients, clientId, setClientId, signOut, route, go, can } = useApp();
  const [page, ...rest] = route.split("/");
  const body = (() => {
    switch (page) {
      case "intake": return <Intake />;
      case "identity": return <Identity />;
      case "rules": return <Rules />;
      case "compare": return <Compare runId={rest[0] ? Number(rest[0]) : undefined} />;
      case "packs": return <Packs />;
      case "cases": return <Cases caseId={rest[0] ? Number(rest[0]) : undefined} />;
      case "clients": return <Clients />;
      case "audit": return <Audit />;
      case "people": return <People />;
      default: return <Overview />;
    }
  })();
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 32 32"><path d="M5 24V8l6 9 5-9 5 9 6-9v16" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
          <div>
            <div className="brand-name">MRM Royalty Comparison</div>
            <div className="brand-sub">Recording vs publishing · Music Rights Management India</div>
          </div>
        </div>
        <div className="ctx">
          <label className="row small ink2">Client
            <select className="input" value={clientId ?? ""} onChange={(e) => setClientId(Number(e.target.value))} aria-label="client">
              {clients.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}
            </select>
          </label>
          <div className="who">
            <span className="avatar">{me.name.slice(0, 1)}</span>
            <div>
              <div style={{ fontWeight: 600 }}>{me.name}</div>
              <div className="muted small">{me.roles.join(", ").replace(/_/g, " ")}</div>
            </div>
          </div>
          <button className="btn sm" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <div className="body">
        <nav className="nav" aria-label="main">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              {g.items.filter((i) => !i.perm || can(i.perm)).map((i) => (
                <a key={i.key} className={page === i.key || (page === "" && i.key === "overview") ? "active" : ""}
                   onClick={() => go(i.key)} href={`#/${i.key}`}>
                  {i.label}{i.tag && <span className="tag">{i.tag}</span>}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <main className="main">{clientId || page === "clients" || page === "people" ? body : <div className="empty">No client yet - add one under Clients & mandates.</div>}</main>
      </div>
    </div>
  );
}

export default function Root() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const qc = useQueryClient();
  useEffect(() => {
    loadMe().then(setMe);
    const h = () => { setMe(null); qc.clear(); };
    window.addEventListener("mrm:signed-out", h);
    return () => window.removeEventListener("mrm:signed-out", h);
  }, [qc]);
  if (me === undefined) return <div className="login-wrap"><Spinner /></div>;
  if (!me) return <Login onIn={(m) => setMe(m)} />;
  return (
    <AppProvider me={me} onSignOut={async () => { await api.post("/auth/logout").catch(() => null); qc.clear(); setMe(null); }}>
      <Shell />
    </AppProvider>
  );
}
