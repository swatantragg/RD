import { useState } from "react";
import { api, setCsrf } from "../api";
import type { Me } from "../state";
import { ErrorNote, Spinner } from "../components/ui";

const DEMO = [
  ["swatantra@mrm.local", "Swatantra", "import, build, run"],
  ["devi@mrm.local", "Devi", "rights & identity review"],
  ["accounts@mrm.local", "Accounts", "rules, controls, payments"],
  ["sherley@mrm.local", "Sherley Singh", "approve & send"],
  ["admin@mrm.local", "Administrator", "everything + people"],
  ["viewer@mrm.local", "Viewer", "read only"],
];

export default function Login({ onIn }: { onIn: (m: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const me = await api.post<Me>("/auth/login", { email, password });
      setCsrf(me.csrf);
      onIn(me);
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login-wrap">
      <form className="card login col" onSubmit={submit} style={{ gap: 14 }}>
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 32 32"><path d="M5 24V8l6 9 5-9 5 9 6-9v16" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
          <div>
            <div className="brand-name">MRM Royalty Comparison</div>
            <div className="brand-sub">Recording vs publishing royalty review</div>
          </div>
        </div>
        <label className="field">Email
          <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">Password
          <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <ErrorNote error={err} />
        <button className="btn primary" disabled={busy} type="submit" style={{ justifyContent: "center" }}>
          {busy && <Spinner />} Sign in
        </button>
        <details className="small">
          <summary className="muted" style={{ cursor: "pointer" }}>Demo accounts (password: mrm-demo-2026)</summary>
          <div className="col" style={{ gap: 4, marginTop: 8 }}>
            {DEMO.map(([e, n, r]) => (
              <button type="button" key={e} className="btn sm ghost" style={{ justifyContent: "flex-start" }}
                      onClick={() => { setEmail(e); setPassword("mrm-demo-2026"); }}>
                <b>{n}</b><span className="muted">{r}</span>
              </button>
            ))}
          </div>
        </details>
      </form>
    </div>
  );
}
