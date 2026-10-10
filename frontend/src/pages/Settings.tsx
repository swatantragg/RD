import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { initials, useApp } from "../session";
import { ThemeSwitch } from "../theme";
import { Button, Card, Dialog, Loading, More, Notice, Page, PasswordField, Pill, day, when } from "../ui";
import { Guide } from "./Home";

export default function Settings({ tab }: { tab?: string }) {
  const { me, go } = useApp();
  const tabs = [
    ["profile", "My profile"],
    me.can.manage ? ["people", "People and access"] : null,
    me.can.diagnostics ? ["technical", "Technical details"] : null,
    ["help", "Help"],
  ].filter(Boolean) as string[][];
  const cur = tabs.find((t) => t[0] === tab)?.[0] ?? tabs[0][0];
  return (
    <Page title="Settings">
      <div className="tabs" role="tablist">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={cur === k} className={cur === k ? "on" : ""} onClick={() => go(`settings/${k}`)}>{l}</button>)}
      </div>
      {cur === "profile" && <Profile />}
      {cur === "people" && <People />}
      {cur === "technical" && <Technical />}
      {cur === "help" && <Help />}
    </Page>
  );
}

function Profile() {
  const { me, toast, refreshMe } = useApp();
  const [name, setName] = useState(me.name);
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [again, setAgain] = useState("");
  const mismatch = again.length > 0 && again !== nw;
  const [busy, setBusy] = useState("");
  const save = async (body: object, what: string) => {
    setBusy(what);
    try {
      await api.patch("/me", body);
      await refreshMe();
      toast(what === "password" ? "Password changed. Other browsers were signed out." : "Saved.");
      if (what === "password") { setCur(""); setNw(""); setAgain(""); }
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  const allClients = me.roles.includes("admin") || me.roles.includes("viewer");
  return (
    <div className="two">
      <Card title="My profile">
        <div className="profile-head">
          <span className="avatar huge" aria-hidden>{initials(me.name)}</span>
          <div>
            <div className="pm-name big">{me.name}</div>
            <div className="muted">{me.email}</div>
          </div>
        </div>
        <dl className="facts">
          <dt>Role</dt><dd>{me.role_labels.join(", ")}</dd>
          <dt>Clients</dt><dd>{allClients ? "All clients" : me.clients.map((c) => c.name).join(", ") || "none yet - ask your administrator"}</dd>
          {me.member_since && <><dt>Member since</dt><dd>{day(me.member_since)}</dd></>}
          {me.last_sign_in && <><dt>Last sign-in</dt><dd>{when(me.last_sign_in)}</dd></>}
          <dt>Theme</dt><dd><ThemeSwitch /></dd>
        </dl>
        <form className="form" onSubmit={(e) => { e.preventDefault(); save({ name }, "name"); }}>
          <label className="field">Name shown in the application and on your downloads
            <input className="input" value={name} required onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="actions"><Button kind="primary" type="submit" busy={busy === "name"} disabled={name.trim() === me.name}>Save name</Button></div>
        </form>
      </Card>
      <Card title="Change password">
        <form className="form" onSubmit={(e) => {
          e.preventDefault();
          if (nw !== again) { toast("The two new passwords are not the same.", true); return; }
          save({ current_password: cur, new_password: nw, confirm_password: again }, "password");
        }}>
          <PasswordField label="Current password" value={cur} onChange={setCur} autoComplete="current-password" />
          <PasswordField label="New password" value={nw} onChange={setNw} autoComplete="new-password" hint="At least 10 characters." />
          <PasswordField label="Confirm new password" value={again} onChange={setAgain} autoComplete="new-password"
                         hint={mismatch ? "The two new passwords are not the same yet." : "Type the new password again."} />
          <div className="actions"><Button kind="primary" type="submit" busy={busy === "password"} disabled={!nw || nw !== again}>Change password</Button></div>
        </form>
      </Card>
    </div>
  );
}

type Person = { id: number; email: string; name: string; active: boolean; last_login_at: string | null; roles: string[]; clients: number[] };

function People() {
  const { me } = useApp();
  const q = useQuery({ queryKey: ["people"], queryFn: () => api.get<{ people: Person[]; roles: { value: string; label: string }[] }>("/people") });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.get<{ id: number; code: string; name: string }[]>("/clients") });
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [showOff, setShowOff] = useState(false);
  if (q.isLoading || !q.data) return <Loading />;
  const roleLabel = Object.fromEntries(q.data.roles.map((r) => [r.value, r.label]));
  const off = q.data.people.filter((p) => !p.active).length;
  const shown = q.data.people.filter((p) => p.active || showOff);
  const clientText = (p: Person) => p.roles.includes("admin") || p.roles.includes("viewer") ? "All clients"
    : (clients.data ?? []).filter((c) => p.clients.includes(c.id)).map((c) => c.code).join(", ") || "none";
  return (
    <Card title="People" sub="New accounts start as Viewers: they follow everyone's work and download published reports. Give Preparer to the people who upload, process and publish."
          actions={<Button kind="primary" onClick={() => setEditing("new")}>Add a person</Button>}>
      {editing && <PersonDialog key={editing === "new" ? "new" : editing.id} person={editing === "new" ? null : editing}
                                roles={q.data.roles} clients={clients.data ?? []} onDone={() => setEditing(null)} />}
      {off > 0 && <label className="check"><input type="checkbox" checked={showOff} onChange={(e) => setShowOff(e.target.checked)} /> Show switched-off accounts ({off})</label>}
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Person</th><th>Role</th><th>Clients</th><th>Last sign-in</th><th></th></tr></thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.id} className={p.active ? "" : "inactive"}>
                <td><span className="who"><span className="avatar sm" aria-hidden>{initials(p.name)}</span>
                  <span><b>{p.name}</b>{p.id === me.id && <span className="muted"> (you)</span>}<div className="muted small">{p.email}</div></span></span></td>
                <td>{p.roles.map((r) => roleLabel[r] ?? r).join(", ")}{!p.active && <div><Pill tone="neutral">Switched off</Pill></div>}</td>
                <td>{clientText(p)}</td>
                <td className="small">{p.last_login_at ? when(p.last_login_at) : "never"}</td>
                <td className="num"><Button kind="secondary" className="sm" onClick={() => setEditing(p)}>Edit</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function PersonDialog({ person, roles, clients, onDone }: {
  person: Person | null; roles: { value: string; label: string }[]; clients: { id: number; code: string; name: string }[];
  onDone: () => void;
}) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", email: "", password: "" });
  const [rs, setRs] = useState<string[]>(person?.roles ?? ["viewer"]);
  const [cs, setCs] = useState<number[]>(person?.clients ?? []);
  const [busy, setBusy] = useState("");
  const self = person?.id === me.id;
  const allClients = rs.includes("admin") || rs.includes("viewer");
  const run = async (what: string, fn: () => Promise<unknown>, msg: string) => {
    setBusy(what);
    try {
      await fn();
      await qc.invalidateQueries({ queryKey: ["people"] });
      toast(msg);
      onDone();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  return (
    <Dialog title={person ? `Edit ${person.name}` : "Add a person"} sub={person?.email} onClose={onDone}>
      <form className="form full" onSubmit={(e) => {
        e.preventDefault();
        if (person) run("save", () => api.patch(`/people/${person.id}`, { roles: rs, clients: cs }), "Saved.");
        else run("save", () => api.post("/people", { ...f, roles: rs, clients: cs }), `${f.name} can now sign in.`);
      }}>
        {!person && (
          <div className="form-grid">
            <label className="field">Name<input className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label className="field">Email<input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
            <PasswordField label="First password" value={f.password} onChange={(v) => setF({ ...f, password: v })} autoComplete="new-password" hint="At least 10 characters. Share it with the person privately." />
          </div>
        )}
        <RolePicker roles={roles} value={rs} onChange={setRs} />
        {allClients ? <p className="hint">Administrators and Viewers see all clients.</p>
          : <ClientPicker clients={clients} value={cs} onChange={setCs} />}
        {self && <Notice>This is your own account. You cannot remove your administrator role, switch yourself off or delete yourself.</Notice>}
        <div className="actions spread">
          {person && !self ? (
            <span className="row">
              <Button type="button" busy={busy === "active"} onClick={() => run("active", () => api.patch(`/people/${person.id}`, { active: !person.active }),
                person.active ? "Switched off." : "Switched on.")}>{person.active ? "Switch off" : "Switch on"}</Button>
              <Button type="button" kind="danger" busy={busy === "delete"} onClick={() => run("delete", () => api.del(`/people/${person.id}`), "Deleted.")}>Delete</Button>
            </span>
          ) : <span />}
          <span className="row">
            <Button type="button" onClick={onDone}>Cancel</Button>
            <Button kind="primary" type="submit" busy={busy === "save"}>{person ? "Save changes" : "Add person"}</Button>
          </span>
        </div>
      </form>
    </Dialog>
  );
}

function RolePicker({ roles, value, onChange }: { roles: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="box"><legend>Role</legend>
      {roles.map((r) => (
        <label key={r.value} className="check"><input type="checkbox" checked={value.includes(r.value)}
          onChange={(e) => onChange(e.target.checked ? [...value, r.value] : value.filter((x) => x !== r.value))} /> {r.label}</label>
      ))}
    </fieldset>
  );
}

function ClientPicker({ clients, value, onChange }: { clients: { id: number; code: string; name: string }[]; value: number[]; onChange: (v: number[]) => void }) {
  return (
    <fieldset className="box"><legend>Clients this person may see</legend>
      {clients.map((c) => (
        <label key={c.id} className="check"><input type="checkbox" checked={value.includes(c.id)}
          onChange={(e) => onChange(e.target.checked ? [...value, c.id] : value.filter((x) => x !== c.id))} /> {c.name}</label>
      ))}
    </fieldset>
  );
}

function Technical() {
  const q = useQuery({ queryKey: ["diag"], queryFn: () => api.get<any>("/diagnostics") });
  if (q.isLoading || !q.data) return <Loading />;
  const d = q.data;
  return (
    <>
      <Notice>This page is for administrators. Everyday work never needs it.</Notice>
      <Card title="Audit record" sub={d.chain.ok ? `Intact - ${d.chain.events} events, each linked to the one before.` : "BROKEN - the audit record was changed."}
            tone={d.chain.ok ? "good" : "bad"}>
        <div className="tbl-wrap short">
          <table className="tbl">
            <thead><tr><th>When</th><th>Who</th><th>What</th><th>Object</th></tr></thead>
            <tbody>{d.events.map((e: any) => <tr key={e.id}><td className="small">{when(e.at)}</td><td>{e.actor}</td><td><code>{e.action}</code></td><td className="small">{e.object_kind} {e.object_id}</td></tr>)}</tbody>
          </table>
        </div>
      </Card>
      <Card title="Failed processing">
        {d.failed_builds.length === 0 ? <p className="muted">None.</p> : d.failed_builds.map((b: any) => (
          <More key={b.id} label={`${b.code} run ${b.run_id} version ${b.version} - ${b.error}`}><pre className="tech">{b.error_detail}</pre></More>
        ))}
      </Card>
      <Card title="Rule set and software">
        <p>{d.software}</p>
        <More label="Rule set v1 (everything that can change a number)"><pre className="tech">{JSON.stringify(d.ruleset, null, 2)}</pre></More>
      </Card>
    </>
  );
}

function Help() {
  return (
    <>
      <Guide />
      <Card title="Words used in this application">
        <dl className="facts">
          <dt>Royalty statement</dt><dd>A payout file from IPRS for one rights holder (for example a YouTube or an overseas distribution).</dd>
          <dt>Platform report</dt><dd>A distributor's report of what a platform such as Spotify earned per recording.</dd>
          <dt>Song list</dt><dd>The client's own list of songs with their ISRCs and IPRS work numbers.</dd>
          <dt>Missing song</dt><dd>A song that earned money but whose codes are not in the song list.</dd>
          <dt>Out-of-scope (Not ours)</dt><dd>A song a reviewer marked as belonging to someone else.</dd>
          <dt>Held money</dt><dd>Money that is counted in every total but waits for a person to say which song it belongs to.</dd>
          <dt>Draft and published</dt><dd>Reports are drafts until the preparer publishes them under the next report number. Published reports never change and cannot be deleted.</dd>
        </dl>
      </Card>
    </>
  );
}
