import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../state";
import { Card, Field, PageHead, Spinner, StateBadge } from "../components/ui";
import { when } from "../format";

export default function People() {
  const { meta, can, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/users") });
  const [n, setN] = useState({ email: "", name: "", password: "", roles: [] as string[] });
  const save = useMutation({
    mutationFn: ({ id, body }: { id?: number; body: unknown }) => (id ? api.patch(`/users/${id}`, body) : api.post("/users", body)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast("Saved"); },
    onError: (e) => toast((e as Error).message, true),
  });
  const roles = Object.keys(meta?.roles ?? {});
  return (
    <>
      <PageHead title="People & roles" step="page 9">
        Swatantra builds and imports; Devi (or a designated rights reviewer) checks mapping and share; accounts check money;
        Sherley or another authorised approver releases the report; sending is a separate authorised action.
      </PageHead>
      <Card flush className="section">
        {q.isLoading ? <Spinner /> : (
          <table className="tbl">
            <thead><tr><th>Name</th><th>Email</th><th>Roles</th><th>Active</th><th>Last sign-in</th></tr></thead>
            <tbody>{q.data!.map((u) => (
              <tr key={u.id}><td>{u.name}</td><td className="mono small">{u.email}</td>
                <td>{can("users") ? (
                  <div className="row wrap">{roles.map((r) => (
                    <label key={r} className="check small"><input type="checkbox" checked={u.roles.includes(r)}
                      onChange={(e) => save.mutate({ id: u.id, body: { roles: e.target.checked ? [...u.roles, r] : u.roles.filter((x: string) => x !== r) } })} />{r.replace(/_/g, " ")}</label>
                  ))}</div>
                ) : u.roles.map((r: string) => <StateBadge key={r} state="NONE">{meta?.roles[r] ?? r}</StateBadge>)}</td>
                <td>{can("users") ? <input type="checkbox" checked={u.active} onChange={(e) => save.mutate({ id: u.id, body: { active: e.target.checked } })} /> : u.active ? "yes" : "no"}</td>
                <td className="small">{when(u.last_login_at)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      {can("users") && (
        <Card title="Add a person">
          <div className="form-grid">
            <Field label="Name"><input className="input" value={n.name} onChange={(e) => setN({ ...n, name: e.target.value })} /></Field>
            <Field label="Email"><input className="input" value={n.email} onChange={(e) => setN({ ...n, email: e.target.value })} /></Field>
            <Field label="Initial password" hint="at least 10 characters"><input className="input" type="password" value={n.password} onChange={(e) => setN({ ...n, password: e.target.value })} /></Field>
          </div>
          <div className="row wrap" style={{ margin: "10px 0" }}>{roles.map((r) => (
            <label key={r} className="check small"><input type="checkbox" checked={n.roles.includes(r)} onChange={(e) => setN({ ...n, roles: e.target.checked ? [...n.roles, r] : n.roles.filter((x) => x !== r) })} />{meta?.roles[r]}</label>
          ))}</div>
          <button className="btn primary" onClick={() => save.mutate({ body: n })}>Add person</button>
        </Card>
      )}
    </>
  );
}
