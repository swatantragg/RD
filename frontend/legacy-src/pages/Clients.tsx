import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useApp, type Client } from "../state";
import { Card, Drawer, Field, PageHead, StateBadge } from "../components/ui";
import { dmy } from "../format";

const BLANK = { code: "", name: "", kind: "PUBLISHER", society: "IPRS", member_id: "", beneficiary_name: "", mandate_verified: false,
  mandate_ref: "", mandate_from: "", mandate_to: "", territories: ["IN"], controlled_share: "", collection_route: "IPRS", contact_email: "", notes: "" };

export default function Clients() {
  const { clients, can } = useApp();
  const [edit, setEdit] = useState<Partial<Client> | null>(null);
  return (
    <>
      <PageHead title="Clients & mandates" step="scope · D2 · H2"
                actions={can("clients") && <button className="btn primary" onClick={() => setEdit({ ...BLANK } as any)}>Add client</button>}>
        Publisher/label clients with verified publishing authority. Label ownership alone is insufficient: until the mandate is
        verified, every group is held for a rights/registration query. The collection route decides who receives the enquiry.
      </PageHead>
      <Card flush>
        <table className="tbl">
          <thead><tr><th>Code</th><th>Name</th><th>Kind</th><th>Member ID</th><th>Beneficiary</th><th>Mandate</th><th>Territories</th><th>Route</th><th className="num">Files</th><th className="num">Open cases</th><th /></tr></thead>
          <tbody>{clients.map((c) => (
            <tr key={c.id}><td className="mono">{c.code}</td><td>{c.name}</td><td className="small">{c.kind.replace(/_/g, " ").toLowerCase()}</td><td className="mono">{c.member_id ?? "—"}</td>
              <td className="small">{c.beneficiary_name}</td>
              <td>{c.mandate_verified ? <StateBadge state="APPROVED">verified</StateBadge> : <StateBadge state="HOLD">not verified</StateBadge>}
                <div className="muted small">{c.mandate_ref} {c.mandate_from && `${dmy(c.mandate_from)} → ${dmy(c.mandate_to) || "open"}`}</div></td>
              <td>{c.territories.join(", ")}</td><td>{c.collection_route}</td><td className="num">{c.files}</td><td className="num">{c.open_cases}</td>
              <td>{can("clients") && <button className="btn sm" onClick={() => setEdit(c)}>Edit</button>}</td></tr>
          ))}</tbody>
        </table>
      </Card>
      {edit && <ClientForm init={edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function ClientForm({ init, onClose }: { init: Partial<Client>; onClose: () => void }) {
  const { toast } = useApp();
  const qc = useQueryClient();
  const [v, setV] = useState<any>({ ...init, territories: (init.territories ?? []).join(", ") });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...v, territories: String(v.territories).split(",").map((x: string) => x.trim()).filter(Boolean) };
      return init.id ? api.patch(`/clients/${init.id}`, body) : api.post("/clients", body);
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Client saved"); onClose(); },
    onError: (e) => toast((e as Error).message, true),
  });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });
  return (
    <Drawer open onClose={onClose} title={init.id ? `Edit ${init.code}` : "Add client"}>
      <div className="form-grid">
        {!init.id && <Field label="Code"><input className="input" value={v.code} onChange={set("code")} /></Field>}
        <Field label="Name"><input className="input" value={v.name ?? ""} onChange={set("name")} /></Field>
        <Field label="Kind"><select className="input" value={v.kind} onChange={set("kind")}><option value="PUBLISHER">publisher</option><option value="LABEL">label</option><option value="PUBLISHER_AND_LABEL">publisher and label</option></select></Field>
        <Field label="Society"><input className="input" value={v.society ?? ""} onChange={set("society")} /></Field>
        <Field label="Member ID"><input className="input" value={v.member_id ?? ""} onChange={set("member_id")} /></Field>
        <Field label="Beneficiary name (as on statements)"><input className="input" value={v.beneficiary_name ?? ""} onChange={set("beneficiary_name")} /></Field>
        <Field label="Mandate reference"><input className="input" value={v.mandate_ref ?? ""} onChange={set("mandate_ref")} /></Field>
        <Field label="Mandate from"><input className="input" type="date" value={v.mandate_from ?? ""} onChange={set("mandate_from")} /></Field>
        <Field label="Mandate to"><input className="input" type="date" value={v.mandate_to ?? ""} onChange={set("mandate_to")} /></Field>
        <Field label="Territories"><input className="input" value={v.territories} onChange={set("territories")} /></Field>
        <Field label="Controlled share" hint="evidenced, fraction"><input className="input" value={v.controlled_share ?? ""} onChange={set("controlled_share")} /></Field>
        <Field label="Collection route"><select className="input" value={v.collection_route} onChange={set("collection_route")}><option>IPRS</option><option>PRS</option><option>DIRECT</option></select></Field>
        <Field label="Contact email"><input className="input" value={v.contact_email ?? ""} onChange={set("contact_email")} /></Field>
      </div>
      <label className="check" style={{ margin: "14px 0" }}><input type="checkbox" checked={!!v.mandate_verified} onChange={(e) => setV({ ...v, mandate_verified: e.target.checked })} />
        Publishing authority verified (mandate, effective dates, territory)</label>
      <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</button>
    </Drawer>
  );
}
