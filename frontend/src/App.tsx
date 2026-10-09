import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setCsrf } from "./api";
import { AppProvider, loadMe, useApp, type Me } from "./session";
import { Button, Notice, PasswordField } from "./ui";
import { ThemeToggle } from "./theme";
import { ProfileMenu } from "./ProfileMenu";
import { WhatsNew } from "./WhatsNew";
import Home from "./pages/Home";
import Process from "./pages/Process";
import PastReports from "./pages/PastReports";
import Clients from "./pages/Clients";
import Settings from "./pages/Settings";

const NAV = [
  { key: "", label: "Home" },
  { key: "process", label: "Process Files" },
  { key: "reports", label: "Past Reports" },
  { key: "clients", label: "Clients" },
  { key: "settings", label: "Settings" },
];

function Shell() {
  const { me, route, go } = useApp();
  const [page, ...rest] = route.split("/");
  const body = (() => {
    switch (page) {
      case "process": return <Process runId={rest[0] ? Number(rest[0]) : undefined} />;
      case "reports": return <PastReports />;
      case "clients": return <Clients start={rest[0]} />;
      case "settings": return <Settings tab={rest[0]} />;
      default: return <Home />;
    }
  })();
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="brand" onClick={() => go("")} role="link" tabIndex={0}
             onKeyDown={(e) => e.key === "Enter" && go("")}>
          <span className="brand-mark" aria-hidden>₹</span>
          <span className="brand-name">Royalty Reports</span>
        </div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className={page === n.key ? "active" : ""}
               aria-current={page === n.key ? "page" : undefined}>{n.label}</a>
          ))}
        </nav>
        <div className="me"><ProfileMenu /></div>
      </header>
      <main id="main" className="main">{body}</main>
      <Footer />
      <WhatsNew notes={me.whats_new} />
    </div>
  );
}

function Login({ onIn }: { onIn: (m: Me) => void }) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [opts, setOpts] = useState<{ signup: boolean; version: string } | null>(null);
  useEffect(() => { api.get<{ signup: boolean; version: string }>("/auth/options").then(setOpts).catch(() => setOpts(null)); }, []);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const m = mode === "in" ? await api.post<Me>("/auth/login", { email, password })
        : await api.post<Me>("/auth/signup", { name, email, password });
      setCsrf(m.csrf);
      onIn(m);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login-wrap">
      <div className="login-top"><ThemeToggle /></div>
      <form className="card login" onSubmit={submit}>
        <div className="brand big"><span className="brand-mark" aria-hidden>₹</span><span className="brand-name">Royalty Reports</span></div>
        <p className="intro">Turn royalty statements and platform reports into checked master reports.</p>
        {opts?.signup !== false && (
          <div className="seg wide" role="tablist">
            <button type="button" role="tab" aria-selected={mode === "in"} className={mode === "in" ? "on" : ""}
                    onClick={() => { setMode("in"); setErr(null); }}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === "up"} className={mode === "up" ? "on" : ""}
                    onClick={() => { setMode("up"); setErr(null); }}>Create account</button>
          </div>
        )}
        {mode === "up" && (
          <label className="field">Your name
            <input className="input" autoComplete="name" value={name} required onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label className="field">Email
          <input className="input" type="email" autoComplete={mode === "in" ? "username" : "email"} value={email} required
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <PasswordField label="Password" value={password} onChange={setPassword}
                       autoComplete={mode === "in" ? "current-password" : "new-password"}
                       hint={mode === "up" ? "At least 10 characters." : undefined} />
        {err && <Notice tone="bad">{err}</Notice>}
        <Button kind="primary" busy={busy} type="submit">{mode === "in" ? "Sign in" : "Create account"}</Button>
        {mode === "up" && (
          <p className="hint">A new account can follow everyone's work and download published reports. An administrator can
            give it more rights. The very first account on a new installation becomes the administrator.</p>
        )}
      </form>
      <Footer />
    </div>
  );
}

function Footer() {
  return <footer className="footer">Royalty Reports · V{__APP_VERSION__}</footer>;
}

export default function Root() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const qc = useQueryClient();
  useEffect(() => {
    loadMe().then(setMe);
    const out = () => setMe(null);
    window.addEventListener("mrm:signed-out", out);
    return () => window.removeEventListener("mrm:signed-out", out);
  }, []);
  if (me === undefined) return <div className="loading full"><span className="spin" /> Loading…</div>;
  if (me === null) return <Login onIn={(m) => { qc.clear(); setMe(m); }} />;
  return (
    <AppProvider me={me} setMe={setMe} onSignOut={async () => {
      try { await api.post("/auth/logout"); } catch { /* already signed out */ }
      qc.clear();
      setMe(null);
    }}>
      <Shell />
    </AppProvider>
  );
}
