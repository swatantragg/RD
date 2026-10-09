import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { local, useApp } from "../session";
import type { Client } from "../types";
import { Button, Card, Dialog, Empty, Loading, More, Notice, Page, RemoveButton, day } from "../ui";

export default function Clients({ start }: { start?: string }) {
  const { me, go } = useApp();
  const q = useQuery({ queryKey: ["clients"], queryFn: () => api.get<Client[]>("/clients") });
  const [editing, setEditing] = useState<Client | "new" | null>(start === "new" && me.can.clients ? "new" : null);
  if (q.isLoading) return <Loading />;
  const list = q.data ?? [];
  const close = (created?: boolean) => {
    setEditing(null);
    if (created && start === "new") go("process");
    else if (start === "new") go("clients");
  };
  return (
    <Page title="Clients" intro="Each client has its own rights holders, report names and settings. Their data is never mixed."
          actions={me.can.clients && <Button kind="primary" onClick={() => setEditing("new")}>Add a client</Button>}>
      {editing && <ClientDialog key={editing === "new" ? "new" : editing.id} client={editing === "new" ? null : editing} onDone={close} />}
      {list.length === 0 ? <Card><Empty title="No clients">{me.can.clients ? "Add the first client." : "Ask your administrator for access."}</Empty></Card> : (
        <div className="grid">
          {list.map((c) => (
            <Card key={c.id} title={c.name} sub={<>{c.code}{!c.active && " · switched off"}</>}
                  actions={me.can.clients && <Button kind="ghost" onClick={() => setEditing(c)}>Edit</Button>}>
              <dl className="facts">
                <dt>Rights holders</dt>
                <dd>{c.holders.length ? c.holders.map((h) => <div key={h.id}>{h.name} <span className="muted">· {h.society} member {h.member_no}</span></div>)
                  : <span className="warn-t">None yet - statements cannot be checked against a rights holder.</span>}</dd>
                <dt>Next report name</dt><dd>{c.output_prefix}{c.next_generation}</dd>
                <dt>Last published</dt><dd>{c.last_published ? `${c.last_published} (${day(c.last_published_at)})` : "none yet"}</dd>
                <dt>Platform reports</dt>
                <dd>{c.distributors.length ? c.distributors.map((d) => <div key={d.name}>{d.name}: {d.currency}, {d.basis === "GROSS" ? "gross" : "net"} revenue</div>) : "none set up"}</dd>
              </dl>
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}

type Holder = { member_no: string; name: string };
type Distributor = Client["distributors"][number];

/** Add a client, or edit one, in a pop-up. Rows can be added and removed; nothing is saved until 'Save'. */
function ClientDialog({ client, onDone }: { client: Client | null; onDone: (created?: boolean) => void }) {
  const { me, toast, refreshMe } = useApp();
  const qc = useQueryClient();
  const [f, setF] = useState({
    code: client?.code ?? "", name: client?.name ?? "", output_prefix: client?.output_prefix ?? "",
    next_generation: String(client?.next_generation ?? 1), song_list_name: client?.song_list_name ?? "",
  });
  const [holders, setHolders] = useState<Holder[]>(client ? [] : [{ member_no: "", name: "" }]);
  const [remove, setRemove] = useState<number[]>([]);
  const [dists, setDists] = useState<Distributor[]>(client?.distributors ?? []);
  const [active, setActive] = useState(client?.active ?? true);
  const [busy, setBusy] = useState(false);
  const setHolder = (i: number, v: Partial<Holder>) => setHolders(holders.map((x, k) => (k === i ? { ...x, ...v } : x)));
  const setDist = (i: number, v: Partial<Distributor>) => setDists(dists.map((x, k) => (k === i ? { ...x, ...v } : x)));
  const half = holders.filter((h) => (h.member_no.trim() === "") !== (h.name.trim() === ""));
  return (
    <Dialog title={client ? `Edit ${client.name}` : "Add a client"} wide onClose={() => onDone()}
            sub={client ? `Code ${client.code} (the code cannot change: it is part of the report names)` : "SVF and the other clients stay as they are."}>
      <form className="form full" onSubmit={async (e) => {
        e.preventDefault();
        if (half.length) { toast("Each rights holder needs both a member number and a name (or remove the row).", true); return; }
        setBusy(true);
        try {
          const body: Record<string, unknown> = { ...f, holders: holders.filter((h) => h.member_no.trim() && h.name.trim()),
            remove_holders: remove, distributors: dists.filter((d) => d.name.trim()) };
          if (client && me.can.manage && active !== client.active) body.active = active;
          if (client) await api.patch(`/clients/${client.id}`, body);
          else local.set("client", String((await api.post<Client>("/clients", body)).id));   // preselected in step 1
          await qc.invalidateQueries({ queryKey: ["clients"] });
          await refreshMe();
          toast(client ? "Saved." : `Client ${f.code} added. You can now process files for it.`);
          onDone(!client);
        } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
      }}>
        <div className="form-grid">
          {!client && (
            <label className="field">Short code (used in report names, e.g. SVF-RD-SKV9)
              <input className="input" value={f.code} required maxLength={12} placeholder="ACME"
                     onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} />
            </label>
          )}
          <label className="field">Name
            <input className="input" value={f.name} required onChange={(e) => setF({ ...f, name: e.target.value })} />
          </label>
        </div>

        <fieldset className="box">
          <legend>Rights holders (society members whose statements belong to this client)</legend>
          {client?.holders.map((h) => (
            <div key={h.id} className={`row-line ${remove.includes(h.id) ? "removed" : ""}`}>
              <span className="grow">{h.name} <span className="muted">· {h.society} member {h.member_no}</span>
                {remove.includes(h.id) && <span className="warn-t"> - will be removed</span>}</span>
              {remove.includes(h.id)
                ? <Button kind="ghost" className="sm" type="button" onClick={() => setRemove(remove.filter((x) => x !== h.id))}>Keep</Button>
                : <RemoveButton label={`Remove ${h.name}`} onClick={() => setRemove([...remove, h.id])} />}
            </div>
          ))}
          {holders.map((h, i) => (
            <div key={i} className="row-line">
              <input className="input mem" placeholder="Member number" aria-label="Member number" value={h.member_no}
                     onChange={(e) => setHolder(i, { member_no: e.target.value })} />
              <input className="input grow" placeholder="Name as on the statement" aria-label="Name as on the statement"
                     value={h.name} onChange={(e) => setHolder(i, { name: e.target.value })} />
              <RemoveButton label="Remove this row" onClick={() => setHolders(holders.filter((_, k) => k !== i))} />
            </div>
          ))}
          <Button kind="ghost" type="button" onClick={() => setHolders([...holders, { member_no: "", name: "" }])}>+ Add a rights holder</Button>
        </fieldset>

        <More label="Report naming and platform reports">
          <div className="form-grid">
            <label className="field">Report name prefix
              <input className="input" value={f.output_prefix} placeholder={`${f.code || client?.code || "CODE"}-RD-SKV`} onChange={(e) => setF({ ...f, output_prefix: e.target.value })} />
            </label>
            <label className="field">Next report number
              <input className="input" type="number" min={1} value={f.next_generation} onChange={(e) => setF({ ...f, next_generation: e.target.value })} />
            </label>
            <label className="field">Song list name (in reports)
              <input className="input" value={f.song_list_name} placeholder={`${f.code || client?.code || "CODE"} list`} onChange={(e) => setF({ ...f, song_list_name: e.target.value })} />
            </label>
          </div>
          <fieldset className="box">
            <legend>Distributors of platform reports</legend>
            {dists.map((d, i) => (
              <div key={i} className="row-line">
                <input className="input grow" value={d.name} placeholder="Distributor (e.g. MRM)" aria-label="Distributor" onChange={(e) => setDist(i, { name: e.target.value })} />
                <select className="input" value={d.currency} aria-label="Currency" onChange={(e) => setDist(i, { currency: e.target.value })}>
                  <option>INR</option><option>USD</option><option>EUR</option><option>GBP</option>
                </select>
                <select className="input" value={d.basis} aria-label="Revenue basis" onChange={(e) => setDist(i, { basis: e.target.value })}>
                  <option value="GROSS">Gross revenue</option><option value="NET">Net revenue</option>
                </select>
                <RemoveButton label="Remove this distributor" onClick={() => setDists(dists.filter((_, k) => k !== i))} />
              </div>
            ))}
            <Button kind="ghost" type="button" onClick={() => setDists([...dists, { name: "", currency: "INR", basis: "GROSS", platforms: [] }])}>+ Add a distributor</Button>
          </fieldset>
          <Notice>Classification rules are not copied between clients. A new client starts with the standard checks only.</Notice>
        </More>

        {client && me.can.manage && (
          <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Client is active (a switched-off client is hidden from new runs; its reports are kept)</label>
        )}
        <div className="actions end">
          <Button type="button" onClick={() => onDone()}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>{client ? "Save changes" : "Add client"}</Button>
        </div>
      </form>
    </Dialog>
  );
}
