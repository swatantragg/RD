import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setCsrf } from "./api";
import { AppProvider, loadMe, useApp, type Me } from "./session";
import { Button, Notice, PasswordField } from "./ui";
import { ThemeToggle } from "./theme";
import { ProfileMenu } from "./ProfileMenu";
import { VersionButton, WhatsNew } from "./WhatsNew";
import { Logo } from "./Logo";
import Home from "./pages/Home";
import Process from "./pages/Process";
import PastReports from "./pages/PastReports";
import Clients from "./pages/Clients";
import Settings from "./pages/Settings";
import Catalogue from "./pages/Catalogue";
import Statements from "./pages/Statements";
import Master from "./pages/Master";
import Reconciliation from "./pages/Reconciliation";
import Enquiries from "./pages/Enquiries";
import { ClientPicker } from "./parts";

const NAV = [
  { key: "", label: "Home" },
  { key: "catalogue", label: "Catalogue" },
  { key: "statements", label: "Statements" },
  { key: "master", label: "Master" },
  { key: "reconciliation", label: "Reconciliation" },
  { key: "enquiries", label: "Enquiries" },
  { key: "reports", label: "Reports", also: ["process"] },
  { key: "settings", label: "Settings", also: ["clients"] },
];

function Shell() {
  const { me, route, go } = useApp();
  const [page, ...rest] = route.split("/");
  if (me.must_change_password) return <ChangePassword />;
  const body = (() => {
    switch (page) {
      case "catalogue": return <Catalogue tab={rest[0]} id={rest[1] ? Number(rest[1]) : undefined} />;
      case "statements": return /^\d+$/.test(rest[0] ?? "") ? <Statements id={Number(rest[0])} /> : <Statements tab={rest[0]} />;
      case "master": return <Master tab={rest[0]} />;
      case "reconciliation": return <Reconciliation runId={rest[0] ? Number(rest[0]) : undefined} />;
      case "enquiries": return <Enquiries id={rest[0] ? Number(rest[0]) : undefined} />;
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
          <Logo />
          <span className="brand-name">MRM Royalty Reconciliation</span>
        </div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => {
            const on = page === n.key || (n.also ?? []).includes(page);
            return <a key={n.key} href={`#/${n.key}`} className={on ? "active" : ""} aria-current={on ? "page" : undefined}>{n.label}</a>;
          })}
        </nav>
        <div className="me"><ClientPicker /><ProfileMenu /></div>
      </header>
      <main id="main" className="main">{body}</main>
      <Footer signedIn />
      <WhatsNew notes={me.whats_new} />
    </div>
  );
}

/** A temporary password (new account or reset) must be replaced before anything else. */
function ChangePassword() {
  const { me, refreshMe, signOut, toast } = useApp();
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={async (e) => {
        e.preventDefault();
        if (nw !== again) { toast("The two new passwords are not the same.", true); return; }
        setBusy(true);
        try {
          await api.patch("/me", { current_password: cur, new_password: nw, confirm_password: again });
          await refreshMe();
          toast("Your password is set. Welcome!");
        } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
      }}>
        <div className="brand big"><Logo /><span className="brand-name">Choose your password</span></div>
        <p className="intro">Hello {me.name}. You signed in with a temporary password. Please choose your own password to continue.</p>
        <PasswordField label="Temporary password" value={cur} onChange={setCur} autoComplete="current-password" />
        <PasswordField label="New password" value={nw} onChange={setNw} autoComplete="new-password" hint="At least 10 characters." />
        <PasswordField label="Confirm new password" value={again} onChange={setAgain} autoComplete="new-password" />
        <Button kind="primary" busy={busy} type="submit" disabled={!nw || nw !== again}>Save and continue</Button>
        <Button kind="ghost" type="button" onClick={signOut}>Sign out</Button>
      </form>
      <Footer />
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
        <div className="brand big"><Logo /><span className="brand-name">MRM Royalty Reconciliation</span></div>
        <p className="intro">Catalogue, statements, reconciliation and IPRS enquiries for Music Rights Management India.</p>
        {opts?.signup === true && (
          <div className="seg wide" role="tablist">
            <button type="button" role="tab" aria-selected={mode === "in"} className={mode === "in" ? "on" : ""}
                    onClick={() => { setMode("in"); setErr(null); }}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === "up"} className={mode === "up" ? "on" : ""}
                    onClick={() => { setMode("up"); setErr(null); }}>Set up (first account)</button>
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
          <p className="hint">This sets up a new installation: the first account becomes the Super Admin. After that, Admins
            create accounts under Settings → People and access.</p>
        )}
      </form>
      <Footer />
    </div>
  );
}

/** The version, in the bottom-right corner; signed in, a click opens the notes of every version. */
function Footer({ signedIn }: { signedIn?: boolean }) {
  return <footer className="footer">{signedIn ? <VersionButton /> : <span className="ver">V{__APP_VERSION__}</span>}</footer>;
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
