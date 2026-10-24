import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { NUMBER_PATTERN, int, numeric } from "../format";
import { ClientSelect, FormDialog, ResetFilters } from "../parts";
import { initials, useApp } from "../session";
import { ThemeSwitch } from "../theme";
import { Button, Card, Dialog, Loading, More, Notice, Page, PasswordField, Pill, Select, day, when } from "../ui";
import { Guide } from "./Home";

export default function Settings({ tab }: { tab?: string }) {
  const { me, go } = useApp();
  const tabs = [
    ["profile", "My profile"],
    me.can.manage ? ["people", "People and access"] : null,
    ["reconciliation", "Reconciliation"],
    ["platforms", "Platforms"],
    ["clients", "Clients"],
    me.can.audit ? ["activity", "Activity log"] : null,
    me.can.diagnostics ? ["technical", "Technical details"] : null,
    ["help", "Help"],
  ].filter(Boolean) as string[][];
  const cur = tabs.find((t) => t[0] === tab)?.[0] ?? tabs[0][0];
  return (
    <Page title="Settings">
      <div className="tabs" role="tablist">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={cur === k} className={cur === k ? "on" : ""}
                                       onClick={() => go(k === "clients" ? "clients" : `settings/${k}`)}>{l}</button>)}
      </div>
      {cur === "profile" && <Profile />}
      {cur === "people" && <People />}
      {cur === "reconciliation" && <ReconSettings />}
      {cur === "platforms" && <Platforms />}
      {cur === "activity" && <Activity />}
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
  const allClients = me.role !== "USER";
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
          <dt>Role</dt><dd>{me.role_label}</dd>
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

type Person = { id: number; email: string; name: string; role: string; role_label: string; active: boolean; deleted: boolean;
  must_change_password: boolean; last_login_at: string | null; created_at: string; created_by_name: string | null; clients: number[];
  can_edit: boolean; can_switch: boolean; can_delete: boolean; can_reset_password: boolean; can_revoke_sessions: boolean };
type PeopleData = { people: Person[]; roles: { value: string; label: string }[]; can_reset_passwords: boolean };

const ROLE_HELP: Record<string, string> = {
  USER: "Catalogue, statements, master view, reconciliation, exports and enquiry drafts. Cannot manage accounts.",
  ADMIN: "Everything a User does, plus accounts (Users and Admins), follow-up assignment, link verification, enquiry approval and closure.",
  SUPER_ADMIN: "Everything an Admin does, plus password resets, the activity log and application settings. There is only one.",
};

function People() {
  const { me } = useApp();
  const [deleted, setDeleted] = useState(false);
  const q = useQuery({ queryKey: ["people", deleted], queryFn: () => api.get<PeopleData>(`/people${deleted ? "?include_deleted=true" : ""}`) });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.get<{ id: number; code: string; name: string }[]>("/clients") });
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [shown, setShown] = useState<{ title: string; text: string } | null>(null);
  if (!q.data) return <Loading />;
  const clientText = (p: Person) => p.role !== "USER" ? "All clients"
    : (clients.data ?? []).filter((c) => p.clients.includes(c.id)).map((c) => c.code).join(", ") || "none";
  return (
    <>
      <Card title="People"
            actions={<Button kind="primary" onClick={() => setEditing("new")}>Add a person</Button>}>
        <dl className="facts small">{Object.entries(ROLE_HELP).map(([k, v]) => <span key={k} style={{ display: "contents" }}><dt>{k === "SUPER_ADMIN" ? "Super Admin" : k === "ADMIN" ? "Admin" : "User"}</dt><dd>{v}</dd></span>)}</dl>
        <div className="toolbar"><label className="check"><input type="checkbox" checked={deleted} onChange={(e) => setDeleted(e.target.checked)} /> Show deleted accounts</label>
          <ResetFilters active={deleted} onReset={() => setDeleted(false)} /></div>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Person</th><th>Role</th><th>Clients</th><th>Last sign-in</th><th></th></tr></thead>
            <tbody>
              {q.data.people.map((p) => (
                <tr key={p.id} className={p.active ? "" : "inactive"}>
                  <td><span className="who"><span className="avatar sm" aria-hidden>{initials(p.name)}</span>
                    <span><b>{p.name}</b>{p.id === me.id && <span className="muted"> (you)</span>}<div className="muted small">{p.email}</div></span></span></td>
                  <td><Pill tone={p.role === "SUPER_ADMIN" ? "info" : p.role === "ADMIN" ? "good" : "neutral"}>{p.role_label}</Pill>
                    {p.deleted ? <div><Pill tone="neutral">Deleted</Pill></div> : !p.active && <div><Pill tone="neutral">Switched off</Pill></div>}
                    {p.must_change_password && !p.deleted && <div className="muted small">temporary password</div>}</td>
                  <td>{clientText(p)}</td>
                  <td className="small">{p.last_login_at ? when(p.last_login_at) : "never"}</td>
                  <td className="num">{p.can_edit && <Button kind="secondary" className="sm" onClick={() => setEditing(p)}>Manage</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {editing && <PersonDialog key={editing === "new" ? "new" : editing.id} person={editing === "new" ? null : editing} data={q.data}
                                clients={clients.data ?? []} onDone={() => setEditing(null)} onSecret={setShown} />}
      {shown && (
        <Dialog title={shown.title} onClose={() => setShown(null)}>
          <div className="form full">
            <Notice tone="warn">Shown once. Share it with the person privately; they must change it at their first sign-in. It is not stored anywhere readable.</Notice>
            <p className="secret mono">{shown.text}</p>
            <div className="actions end"><Button kind="primary" onClick={() => setShown(null)}>I have noted it</Button></div>
          </div>
        </Dialog>
      )}
    </>
  );
}

function PersonDialog({ person, data, clients, onDone, onSecret }: {
  person: Person | null; data: PeopleData; clients: { id: number; code: string; name: string }[]; onDone: () => void;
  onSecret: (s: { title: string; text: string }) => void;
}) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const [f, setF] = useState({ name: person?.name ?? "", email: "", password: "" });
  const [role, setRole] = useState(person?.role ?? "USER");
  const [cs, setCs] = useState<number[]>(person?.clients ?? clients.map((c) => c.id));
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState<"delete" | "reset" | null>(null);
  const run = async (what: string, fn: () => Promise<any>, msg?: string) => {
    setBusy(what);
    try {
      const r = await fn();
      await qc.invalidateQueries({ queryKey: ["people"] });
      if (r?.temporary_password) onSecret({ title: what === "reset" ? `Temporary password for ${person?.name}` : `First password for ${f.name}`, text: r.temporary_password });
      toast(r?.message ?? msg ?? "Saved.");
      onDone();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  return (
    <Dialog title={person ? person.name : "Add a person"} sub={person?.email} onClose={onDone}>
      <form className="form full" onSubmit={(e) => {
        e.preventDefault();
        if (person) run("save", () => api.patch(`/people/${person.id}`, { name: f.name, role, clients: role === "USER" ? cs : [] }));
        else run("save", () => api.post("/people", { ...f, role, clients: role === "USER" ? cs : [] }));
      }}>
        <div className="form-grid">
          <label className="field">Name<input className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          {!person && <label className="field">Email<input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>}
        </div>
        {!person && <PasswordField label="First password (optional)" value={f.password} onChange={(v) => setF({ ...f, password: v })} autoComplete="new-password"
                                   hint="Leave empty to generate a temporary password. Either way it must be changed at the first sign-in." />}
        <fieldset className="box"><legend>Role</legend>
          {data.roles.map((r) => (
            <label key={r.value} className="check"><input type="radio" name="role" checked={role === r.value} onChange={() => setRole(r.value)} /> <b>{r.label}</b>
              <span className="muted small"> — {ROLE_HELP[r.value]}</span></label>))}
        </fieldset>
        {role === "USER" ? <ClientPicker clients={clients} value={cs} onChange={setCs} /> : <p className="hint">Admins see all clients.</p>}
        <div className="actions spread">
          {person ? (
            <span className="row">
              {person.can_switch && <Button type="button" busy={busy === "active"} onClick={() => run("active", () => api.patch(`/people/${person.id}`, { active: !person.active }),
                person.active ? "Switched off. Their sessions were ended." : "Switched on.")}>{person.active ? "Switch off" : "Switch on"}</Button>}
              {person.can_reset_password && <Button type="button" onClick={() => setConfirm("reset")}>Reset password</Button>}
              {person.can_revoke_sessions && <Button type="button" busy={busy === "revoke"} onClick={() => run("revoke", () => api.post(`/people/${person.id}/revoke-sessions`))}>Sign out everywhere</Button>}
              {person.can_delete && <Button type="button" kind="danger" onClick={() => setConfirm("delete")}>Delete</Button>}
            </span>
          ) : <span />}
          <span className="row">
            <Button type="button" onClick={onDone}>Cancel</Button>
            <Button kind="primary" type="submit" busy={busy === "save"}>{person ? "Save changes" : "Add person"}</Button>
          </span>
        </div>
      </form>
      {confirm === "delete" && person && (
        <FormDialog title={`Delete ${person.name}?`} submit="Delete account" danger onClose={() => setConfirm(null)}
                    onSubmit={() => run("delete", () => api.del(`/people/${person.id}`))}>
          <p>The account can no longer sign in and disappears from the lists. Everything they did keeps their name in the history.</p>
        </FormDialog>
      )}
      {confirm === "reset" && person && (
        <FormDialog title={`Reset ${person.name}'s password?`} submit="Issue a temporary password" onClose={() => setConfirm(null)}
                    onSubmit={() => run("reset", () => api.post(`/people/${person.id}/reset-password`, {}))}>
          <p>A temporary password is generated and shown to you once. {person.name} is signed out everywhere and must choose a new password at the next sign-in.
            Existing passwords are never shown: only a one-way fingerprint of each password is stored.</p>
        </FormDialog>
      )}
    </Dialog>
  );
}

function ClientPicker({ clients, value, onChange }: { clients: { id: number; code: string; name: string }[]; value: number[]; onChange: (v: number[]) => void }) {
  return (
    <fieldset className="box"><legend>Clients this User may see</legend>
      {clients.map((c) => (
        <label key={c.id} className="check"><input type="checkbox" checked={value.includes(c.id)}
          onChange={(e) => onChange(e.target.checked ? [...value, c.id] : value.filter((x) => x !== c.id))} /> {c.name}</label>
      ))}
    </fieldset>
  );
}

// ================================================================== reconciliation settings
type PlatSetting = { platform_id: number; platform: string; iprs: number; platform_reports: number; own: boolean; setting_id: number | null;
  benchmark_percentage: string | null; client_share_pct: string | null; revenue_basis: string | null };
type RS = { current: any[]; default: any | null; platforms: PlatSetting[]; history: any[]; iprs_currency: string | null; can_change: boolean };
const pc = (v: string | null | undefined) => (v == null ? null : `${Number(v)} %`);

/** The two percentages of a reconciliation: what IPRS is expected to pay (the IPRS %) of a song's total revenue, and
 *  the client's share of that total that the platform pays (the platform report shows that share). */
function ReconSettings() {
  const { clientId, client, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["recon-settings", clientId], queryFn: () => api.get<RS>(`/reconciliation/settings?client_id=${clientId}`), enabled: !!clientId });
  const [edit, setEdit] = useState(false);
  if (!clientId) return <Notice tone="warn">No client.</Notice>;
  const d = q.data;
  const def = d?.default;
  const oldInterest = d?.history.some((h) => h.client_interest_pct) || def?.client_interest_pct;
  return (
    <>
      <Card><ClientSelect label="Client" /></Card>
      {!d ? <Loading /> : <>
      <Card title={`Reconciliation basis for ${client?.name}`}
            actions={d.can_change && <Button kind="primary" onClick={() => setEdit(true)}>Change</Button>}>
        {!def ? <Notice tone="warn">No IPRS % is set for this client yet. {d.can_change ? "Change starts at 4 %." : "The Super Admin sets it."}</Notice> : (
          <dl className="facts">
            <dt>IPRS % (expected from IPRS)</dt><dd><b>{Number(def.benchmark_percentage)} %</b> of each song's total revenue (client-wide; a platform can have its own value). A work is underpaid when IPRS paid less.</dd>
            <dt>Client share of the revenue</dt><dd>{!def.client_share_pct ? "Not set - the revenue the platform reports counts as the total (100 %)"
              : Number(def.client_share_pct) === 100 ? <><b>100 %</b> - the revenue the platform reports is the song's total revenue</>
                : <><b>{Number(def.client_share_pct)} %</b> - the platform pays the client this share of a song's total revenue, so the total revenue = revenue ÷ {Number(def.client_share_pct)} %</>}
              {def.client_interest_pct && <div className="muted small">The client interest of {Number(def.client_interest_pct)} % set before version 1.6.0 is not used any more; saving new values clears it.</div>}</dd>
            <dt>Revenue basis compared</dt><dd>{def.revenue_basis.toLowerCase()}</dd>
            <dt>IPRS statement currency</dt><dd>{d.iprs_currency ?? "not set"} <span className="muted small">(IPRS statements do not print a currency)</span></dd>
            <dt>Set by</dt><dd>{def.created_by_name ?? "set-up"} on {day(def.effective_from)}{def.note && <div className="muted small">{def.note}</div>}</dd>
          </dl>)}
        <h3 className="sub-h">Per platform</h3>
        {d.platforms.length === 0 ? <p className="muted">No platform in this client's statements yet. Upload statements first; each platform found appears here.</p> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Platform</th><th>Statements uploaded</th><th className="num">IPRS %</th><th className="num">Client share</th><th>Comes from</th></tr></thead>
            <tbody>{d.platforms.map((p) => (
              <tr key={p.platform_id}><td><b>{p.platform}</b></td>
                <td className="small">{int(p.platform_reports ?? 0)} platform · {int(p.iprs)} IPRS</td>
                <td className="num">{pc(p.benchmark_percentage) ?? "—"}</td>
                <td className="num">{pc(p.client_share_pct) ?? <span className="muted small">not set (100 %)</span>}</td>
                <td className="small">{p.own ? <Pill tone="info">Own values</Pill> : "Client-wide values"}</td></tr>))}</tbody>
          </table></div>
        )}
        {!d.can_change && <p className="hint">Only the Super Admin changes these values.</p>}
      </Card>
      {d.history.length > 0 && (
        <Card title="Earlier values">
          <div className="tbl-wrap short"><table className="tbl">
            <thead><tr><th>Platform</th><th>IPRS %</th><th>Client share</th>{oldInterest && <th>Client interest (before 1.6.0)</th>}<th>Basis</th><th>From</th><th>Replaced</th><th>Note</th></tr></thead>
            <tbody>{d.history.map((h) => <tr key={h.id}><td>{h.platform_name ?? "Every platform"}</td><td>{Number(h.benchmark_percentage)} %</td>
              <td>{pc(h.client_share_pct) ?? <span className="muted">not set</span>}</td>
              {oldInterest && <td>{h.client_interest_pct ? `${Number(h.client_interest_pct)} %` : "—"}</td>}<td>{h.revenue_basis.toLowerCase()}</td>
              <td className="small">{day(h.effective_from)} · {h.created_by_name ?? "set-up"}</td><td className="small">{day(h.replaced_at)} · {h.replaced_by_name}</td><td className="small">{h.note}</td></tr>)}</tbody>
          </table></div>
        </Card>
      )}
      {edit && <ReconEdit d={d} cid={clientId} name={client?.name ?? ""} onClose={() => setEdit(false)}
                          onSaved={(x) => { qc.setQueryData(["recon-settings", clientId], x); qc.invalidateQueries({ queryKey: ["recon-options"] }); toast("Saved. New reconciliations use these values."); }} />}
      </>}
    </>
  );
}

/** Two client-wide values - the IPRS % and the client share - apply to the ticked platforms ('Select all' ticks every
 *  one); an unticked platform gets an IPRS % and a client share of its own, starting from the client-wide values. */
function ReconEdit({ d, cid, name, onClose, onSaved }: { d: RS; cid: number; name: string; onClose: () => void; onSaved: (d: RS) => void }) {
  const def = d.default;
  const [f, setF] = useState({ benchmark_percentage: def ? String(Number(def.benchmark_percentage)) : "4",
    client_share_pct: def?.client_share_pct ? String(Number(def.client_share_pct)) : "100", revenue_basis: def?.revenue_basis ?? "GROSS",
    iprs_currency: d.iprs_currency ?? "INR", note: "" });
  const [use, setUse] = useState<Record<number, boolean>>(() => Object.fromEntries(d.platforms.map((p) => [p.platform_id, !p.own])));
  const [own, setOwn] = useState<Record<number, { b: string; s: string }>>(() => Object.fromEntries(d.platforms.map((p) => [p.platform_id, {
    b: p.own && p.benchmark_percentage ? String(Number(p.benchmark_percentage)) : "", s: p.own && p.client_share_pct ? String(Number(p.client_share_pct)) : "" }])));
  const all = d.platforms.length > 0 && d.platforms.every((p) => use[p.platform_id]);
  const bench = f.benchmark_percentage || "…";
  const share = f.client_share_pct || "…";
  const tick = (ids: number[], on: boolean) => {       // an unticked platform starts from the client-wide values
    setUse((u) => ({ ...u, ...Object.fromEntries(ids.map((id) => [id, on])) }));
    if (!on) setOwn((o) => ({ ...o, ...Object.fromEntries(ids.map((id) => [id, { b: o[id]?.b || f.benchmark_percentage, s: o[id]?.s || f.client_share_pct }])) }));
  };
  const setOne = (id: number, k: "b" | "s", v: string) => setOwn((o) => ({ ...o, [id]: { ...(o[id] ?? { b: "", s: "" }), [k]: numeric(v, 4) } }));
  return (
    <FormDialog title="Change the reconciliation basis" sub={name} submit="Save new values" wide onClose={onClose}
                onSubmit={async () => onSaved(await api.post<RS>("/reconciliation/settings/platforms", { client_id: cid, ...f,
                  platforms: d.platforms.map((p) => ({ platform_id: p.platform_id, use_default: !!use[p.platform_id],
                    benchmark_percentage: use[p.platform_id] ? null : own[p.platform_id]?.b, client_share_pct: use[p.platform_id] ? null : own[p.platform_id]?.s })) }))}>
      <div className="form-grid">
        <label className="field">IPRS % (of a song's total revenue)
          <input className="input" inputMode="decimal" required pattern={NUMBER_PATTERN} title="A number, for example 7 or 4.5"
                 value={f.benchmark_percentage} onChange={(e) => setF({ ...f, benchmark_percentage: numeric(e.target.value, 4) })} />
          <span className="hint">What IPRS is expected to pay, for example 7 % of what the song earned.</span></label>
        <label className="field">Client share (% of a song's total revenue)
          <input className="input" inputMode="decimal" required pattern={NUMBER_PATTERN} title="A number, for example 52 or 100"
                 value={f.client_share_pct} onChange={(e) => setF({ ...f, client_share_pct: numeric(e.target.value, 4) })} />
          <span className="hint">What the platform pays the client, for example 52 %: the platform report shows that share, so the total = revenue ÷ 52 %. 100 = the report shows the total.</span></label>
      </div>
      <fieldset className="box plat-pick"><legend>Apply {bench} % and {share} % to these platforms</legend>
        {d.platforms.length === 0 ? <p className="muted small">No platform in {name}'s statements yet. The values apply to every platform found later.</p> : <>
          <p className="hint">Platforms found in {name}'s uploaded statements. Untick a platform to give it an IPRS % and a client share of its own.</p>
          <label className="check all"><input type="checkbox" checked={all} onChange={(e) => tick(d.platforms.map((p) => p.platform_id), e.target.checked)} /> <b>Select all</b></label>
          {d.platforms.map((p) => (
            <div key={p.platform_id} className="plat-row">
              <label className="check"><input type="checkbox" checked={!!use[p.platform_id]} onChange={(e) => tick([p.platform_id], e.target.checked)} />
                {" "}<b>{p.platform}</b> <span className="muted small">{int(p.platform_reports ?? 0)} platform · {int(p.iprs)} IPRS</span></label>
              {use[p.platform_id] ? <span className="muted small">IPRS {bench} % · client share {share} %</span> : (
                <span className="plat-vals">
                  <label className="field inline">IPRS %
                    <input className="input sm" inputMode="decimal" required pattern={NUMBER_PATTERN} title="A number, for example 7 or 4.5" value={own[p.platform_id]?.b ?? ""} placeholder="e.g. 7"
                           aria-label={`IPRS % for ${p.platform}`} onChange={(e) => setOne(p.platform_id, "b", e.target.value)} /></label>
                  <label className="field inline">Client share %
                    <input className="input sm" inputMode="decimal" required pattern={NUMBER_PATTERN} title="A number, for example 52 or 100" value={own[p.platform_id]?.s ?? ""} placeholder="e.g. 52"
                           aria-label={`Client share for ${p.platform}`} onChange={(e) => setOne(p.platform_id, "s", e.target.value)} /></label>
                </span>)}
            </div>))}
        </>}
      </fieldset>
      <div className="form-grid">
        <label className="field">Revenue basis compared<Select value={f.revenue_basis} onChange={(v) => setF({ ...f, revenue_basis: v })} options={[{ value: "GROSS", label: "Gross" }, { value: "NET", label: "Net" }]} /></label>
        <label className="field">IPRS statement currency<input className="input" value={f.iprs_currency} onChange={(e) => setF({ ...f, iprs_currency: e.target.value })} /></label>
      </div>
      <label className="field">Why (who approved it)<textarea className="input" rows={2} required value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
    </FormDialog>
  );
}

// ================================================================== platforms
function Platforms() {
  const { toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["platforms"], queryFn: () => api.get<{ platforms: { id: number; platform_code: string; platform_name: string; note: string | null; aliases: string[] }[]; can_change: boolean }>("/platforms") });
  const [alias, setAlias] = useState<Record<number, string>>({});
  const [add, setAdd] = useState(false);
  if (!q.data) return <Loading />;
  return (
    <Card title="Platforms"
          actions={q.data.can_change && <Button kind="secondary" onClick={() => setAdd(true)}>Add a platform</Button>}>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Platform</th><th>Spellings that mean it</th>{q.data.can_change && <th>Add a spelling</th>}</tr></thead>
        <tbody>{q.data.platforms.map((p) => (
          <tr key={p.id}><td><b>{p.platform_name}</b><div className="muted small mono">{p.platform_code}</div>{p.note && <div className="muted small">{p.note}</div>}</td>
            <td className="small">{p.aliases.join(" · ")}</td>
            {q.data!.can_change && <td><form className="row nowrap" onSubmit={async (e) => {
              e.preventDefault();
              try { await api.post(`/platforms/${p.id}/aliases`, { alias: alias[p.id] }); setAlias({ ...alias, [p.id]: "" }); qc.invalidateQueries({ queryKey: ["platforms"] }); toast("Added."); }
              catch (x) { toast((x as Error).message, true); }
            }}><input className="input sm" value={alias[p.id] ?? ""} onChange={(e) => setAlias({ ...alias, [p.id]: e.target.value })} placeholder="as written in a file" />
              <Button className="sm" type="submit" disabled={!alias[p.id]}>Add</Button></form></td>}
          </tr>))}</tbody>
      </table></div>
      {add && <AddPlatform onClose={() => setAdd(false)} onDone={async () => { await qc.invalidateQueries({ queryKey: ["platforms"] }); toast("Added."); }} />}
    </Card>
  );
}

function AddPlatform({ onClose, onDone }: { onClose: () => void; onDone: () => Promise<void> }) {
  const [name, setName] = useState("");
  return (
    <FormDialog title="Add a platform" submit="Add" onClose={onClose} onSubmit={async () => { await api.post("/platforms", { name }); await onDone(); }}>
      <label className="field">Name<input className="input" required value={name} onChange={(e) => setName(e.target.value)} /></label>
    </FormDialog>
  );
}

// ================================================================== activity log (Super Admin)
const AREAS: [string, string][] = [["", "Everything"], ["accounts", "Accounts and security"], ["catalogue", "Catalogue"], ["statements", "Statements"],
  ["reconciliation", "Reconciliation"], ["enquiries", "Enquiries"], ["settings", "Settings"], ["exports", "Exports"], ["reports", "Reports"]];

function Activity() {
  const [area, setArea] = useState("");
  const [qq, setQq] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["audit", area, qq, before], queryFn: () => api.get<{ events: any[]; chain: { ok: boolean; events: number } | null; people: Record<string, string> }>(
    `/audit${qs({ area, q: qq, before: before ?? undefined })}`) });
  return (
    <Card title="Activity log" sub={q.data?.chain ? (q.data.chain.ok ? `Intact: ${int(q.data.chain.events)} events, each linked to the one before - an edit or deletion would show here.` : "BROKEN: the log was changed.") : undefined}
          tone={q.data?.chain && !q.data.chain.ok ? "bad" : undefined}>
      <div className="toolbar">
        <Select size="sm" label="Area" value={area} onChange={(v) => { setArea(v); setBefore(null); }} options={AREAS.map(([value, label]) => ({ value, label }))} />
        <input className="input" placeholder="Find a person or action" value={qq} onChange={(e) => { setQq(e.target.value); setBefore(null); }} />
        <ResetFilters active={!!(area || qq || before)} onReset={() => { setArea(""); setQq(""); setBefore(null); }} />
      </div>
      {!q.data ? <Loading /> : (
        <>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
            <tbody>{q.data.events.map((e) => (
              <tr key={e.id}><td className="small nowrap">{when(e.at)}</td>
                <td>{e.actor}{e.detail?.actor_role && <div className="muted small">{e.detail.actor_role.replace("_", " ").toLowerCase()}</div>}</td>
                <td><code>{e.action}</code><div className="muted small">{e.object_kind} {e.object_id}</div></td>
                <td className="small audit-detail">{Object.entries(e.detail ?? {}).filter(([k]) => k !== "actor_role").map(([k, v]) => (
                  <div key={k}><b>{k.replace(/_/g, " ")}:</b> {typeof v === "object" ? JSON.stringify(v) : String(v)}</div>))}</td></tr>))}</tbody>
          </table></div>
          <div className="pager">{q.data.events.length >= 200 && <Button kind="ghost" className="sm" onClick={() => setBefore(q.data!.events[q.data!.events.length - 1].id)}>Older events</Button>}
            {before && <Button kind="ghost" className="sm" onClick={() => setBefore(null)}>Newest</Button>}</div>
        </>
      )}
    </Card>
  );
}

function Technical() {
  const q = useQuery({ queryKey: ["diag"], queryFn: () => api.get<any>("/diagnostics") });
  if (q.isLoading || !q.data) return <Loading />;
  const d = q.data;
  return (
    <>
      <Notice>This page is for Admins: processing problems and the rule set. The activity log is under its own tab for the Super Admin.</Notice>
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
          <dt>Platform report</dt><dd>The platform's report (for example MRM's Spotify report): revenue and usage (plays) per ISRC and month. Revenue and usage may come in two files; they are combined by ISRC and song name. The revenue is the client's share of what the song earned.</dd>
          <dt>IPRS statement</dt><dd>What IPRS paid for each work, platform and period - received from IPRS, or forwarded by the client in the same layout.</dd>
          <dt>Client share, total revenue</dt><dd>The share of a song's revenue the platform pays the client (for example Spotify 52 %). The song's total revenue = the revenue reported ÷ the client share: Rs. 52 at 52 % is Rs. 100.</dd>
          <dt>Work and ISRC</dt><dd>A work is the composition (IPRS work number); an ISRC identifies one recording of it. One work can have many ISRCs.</dd>
          <dt>IPRS %, expected royalty</dt><dd>The IPRS % (for example 7 %) of the song's total revenue: Rs. 7 of Rs. 100. A reference for review, not an amount payable. Received % = what IPRS paid ÷ the total revenue.</dd>
          <dt>Underpaid, shortfall</dt><dd>IPRS paid less than expected; the shortfall is expected minus paid. It says where to ask IPRS a question; it does not establish that anything is owed.</dd>
          <dt>No corresponding IPRS entry</dt><dd>The uploaded IPRS statements contain no line for the work. It does not mean the royalty is zero.</dd>
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
