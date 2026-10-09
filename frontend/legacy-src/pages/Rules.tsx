import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { useApp } from "../state";
import { Card, Drawer, Empty, Field, PageHead, ReasonForm, Spinner, StateBadge } from "../components/ui";
import { dmy, when, words } from "../format";

type Rule = Record<string, any>;
const EMPTY: Rule = {
  name: "", method: "MRM_BENCHMARK", rate: "0.06", denominator: "", revenue_basis: "NET", share_treatment: "BENEFICIARY_SPECIFIC",
  controlled_share: "", stream_rate: "", stream_rate_basis: "", platforms: [], territories: ["IN"], use_types: ["AUDIO_STREAMING"],
  currency: "INR", effective_from: "", effective_to: "", evidence_ref: "", formula: "", tolerance: "1.00", owner_id: "",
};

export default function Rules() {
  const { clientId, can, toast, me } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["rules", clientId], queryFn: () => api.get<Rule[]>(`/rules${qs({ client_id: clientId })}`) });
  const [edit, setEdit] = useState<{ base: Rule; id?: number; status?: string } | null>(null);
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "del"; path: string; body?: unknown }) =>
      method === "del" ? api.del(path) : api.post(path, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); qc.invalidateQueries({ queryKey: ["dash"] }); toast("Rule updated"); },
    onError: (e) => toast((e as Error).message, true),
  });
  const groups = (q.data ?? []).reduce<Record<string, Rule[]>>((a, r) => ({ ...a, [`${r.client_code ?? "MRM-wide"} · ${r.rule_key}`]: [...(a[`${r.client_code ?? "MRM-wide"} · ${r.rule_key}`] ?? []), r] }), {});
  return (
    <>
      <PageHead title="Comparison rules" step="E1–E5"
                actions={can("rule_draft") && <button className="btn primary" onClick={() => setEdit({ base: { ...EMPTY, owner_id: me.id } })}>Draft a rule</button>}>
        6% is an <b>MRM screening benchmark</b> on a defined basis, not an IPRS tariff. An evidenced society/contract method
        replaces it only inside its scope and dates. Every rule is drafted by one person and approved by another; an approved
        version is frozen - a change is a new version.
      </PageHead>
      {q.isLoading ? <Spinner /> : !q.data?.length ? <Empty>No rules yet: without one, comparisons are coverage-only.</Empty> : (
        Object.entries(groups).map(([k, rs]) => (
          <Card key={k} title={k} sub={rs[0].name} className="section" flush>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead><tr><th>Ver.</th><th>Status</th><th>Method</th><th>k</th><th>q</th><th>Applies to</th><th>Basis / share</th><th>Scope</th>
                  <th>Effective</th><th>Tolerance</th><th>Drafted / approved</th><th>Reason</th><th /></tr></thead>
                <tbody>
                  {rs.map((r) => (
                    <tr key={r.id}>
                      <td>v{r.version_no}</td><td><StateBadge state={r.status} /></td>
                      <td className="small">{r.method === "MRM_BENCHMARK" ? "MRM benchmark (indicative)" : `evidenced · ${r.evidence_ref ?? ""}`}</td>
                      <td className="num">{r.rate ?? "—"}</td><td className="num">{r.stream_rate ?? <span className="muted">blank</span>}</td>
                      <td className="wrap small">{r.denominator ?? <span style={{ color: "var(--crit-ink)" }}>not stated</span>}</td>
                      <td className="small">{words(r.revenue_basis) || "—"} · {r.share_treatment === "WORK_100_TIMES_SHARE" ? `100% × s=${r.controlled_share ?? "?"}` : words(r.share_treatment) || "—"}</td>
                      <td className="small">{[r.platforms.join("/") || "any platform", r.territories.join("/") || "any territory", r.use_types.map(words).join("/") || "any use"].join(" · ")} · {r.currency}</td>
                      <td className="small nowrap">{dmy(r.effective_from) || "—"} → {dmy(r.effective_to) || "open"}</td>
                      <td className="num">{r.tolerance}</td>
                      <td className="small">{r.created_by_name}<div className="muted">{r.approved_by_name ? `${r.approved_by_name} · ${when(r.approved_at)}` : "not approved"}</div></td>
                      <td className="wrap small">{r.reason}</td>
                      <td className="nowrap">
                        {r.status === "DRAFT" && can("rule_approve") && r.created_by !== me.id &&
                          <button className="btn sm primary" onClick={() => act.mutate({ method: "post", path: `/rules/${r.id}/approve` })}>Approve</button>}
                        {r.status === "DRAFT" && can("rule_draft") && <>
                          <button className="btn sm" onClick={() => setEdit({ base: r, id: r.id, status: r.status })}>Edit</button>
                          <button className="btn sm" onClick={() => act.mutate({ method: "del", path: `/rules/${r.id}` })}>Discard</button></>}
                        {r.status === "APPROVED" && can("rule_draft") && <button className="btn sm" onClick={() => setEdit({ base: r, id: r.id, status: r.status })}>New version</button>}
                        {r.status === "APPROVED" && can("rule_approve") && <button className="btn sm" onClick={() => {
                          const reason = window.prompt("Reason for retiring this rule?");
                          if (reason) act.mutate({ method: "post", path: `/rules/${r.id}/retire`, body: { reason } });
                        }}>Retire</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))
      )}
      {edit && <RuleForm init={edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function RuleForm({ init, onClose }: { init: { base: Rule; id?: number; status?: string }; onClose: () => void }) {
  const { clientId, meta, toast } = useApp();
  const qc = useQueryClient();
  const [v, setV] = useState<Rule>(() => ({ ...EMPTY, ...Object.fromEntries(Object.entries(init.base).map(([k, x]) => [k, x ?? ""])) }));
  const [scope, setScope] = useState(init.base.client_id ? "client" : "mrm");
  const [key, setKey] = useState(init.base.rule_key ?? "MRM-6PCT");
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/users") });
  const save = useMutation({
    mutationFn: (reason: string) => init.id
      ? api.patch(`/rules/${init.id}`, { values: v, reason })
      : api.post("/rules", { client_id: scope === "client" ? clientId : null, rule_key: key, values: v, reason }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); toast(init.status === "APPROVED" ? "New draft version created - awaiting approval" : "Draft saved"); onClose(); },
    onError: (e) => toast((e as Error).message, true),
  });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setV({ ...v, [k]: e.target.value });
  const list = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) });
  return (
    <Drawer open onClose={onClose} wide title={init.id ? (init.status === "APPROVED" ? `New version of ${init.base.rule_key}` : `Edit draft ${init.base.rule_key} v${init.base.version_no}`) : "Draft a comparison rule"}
            sub="E4: the denominator and whose share it predicts must be explicit. E5: scope, dates, owner and approval are recorded.">
      <div className="form-grid">
        {!init.id && <>
          <Field label="Applies to"><select className="input" value={scope} onChange={(e) => setScope(e.target.value)}><option value="mrm">all MRM clients</option><option value="client">this client only</option></select></Field>
          <Field label="Rule key"><input className="input" value={key} onChange={(e) => setKey(e.target.value)} /></Field>
        </>}
        <Field label="Name"><input className="input" value={v.name} onChange={set("name")} /></Field>
        <Field label="Method"><select className="input" value={v.method} onChange={set("method")}>
          <option value="MRM_BENCHMARK">MRM benchmark (indicative)</option><option value="EVIDENCED">Evidenced society / contract method</option></select></Field>
        <Field label="Rate k" hint="0.06 = 6%"><input className="input" value={v.rate} onChange={set("rate")} /></Field>
        <Field label="Revenue basis"><select className="input" value={v.revenue_basis} onChange={set("revenue_basis")}><option value="" /><option>GROSS</option><option>NET</option></select></Field>
        <Field label="Share treatment"><select className="input" value={v.share_treatment} onChange={set("share_treatment")}><option value="" />
          <option value="BENEFICIARY_SPECIFIC">Beneficiary-specific (B = R × k)</option><option value="WORK_100_TIMES_SHARE">100% of work × share (B = R × k × s)</option></select></Field>
        {v.share_treatment === "WORK_100_TIMES_SHARE" && <Field label="Controlled share s" hint="evidenced - never assume 100%"><input className="input" value={v.controlled_share} onChange={set("controlled_share")} /></Field>}
        <Field label="Per-stream publishing rate q" hint="blank by default - only an approved, scoped rate"><input className="input" value={v.stream_rate} onChange={set("stream_rate")} /></Field>
        {v.stream_rate && <Field label="Basis of q"><input className="input" value={v.stream_rate_basis} onChange={set("stream_rate_basis")} /></Field>}
        <Field label="Platforms" hint="comma separated; blank = any"><input className="input" value={(v.platforms ?? []).join(", ")} onChange={list("platforms")} list="plats" /></Field>
        <Field label="Territories"><input className="input" value={(v.territories ?? []).join(", ")} onChange={list("territories")} /></Field>
        <Field label="Use types" hint={meta?.use_types.join(", ")}><input className="input" value={(v.use_types ?? []).join(", ")} onChange={list("use_types")} /></Field>
        <Field label="Currency"><input className="input" value={v.currency} onChange={set("currency")} /></Field>
        <Field label="Effective from"><input className="input" type="date" value={v.effective_from?.slice?.(0, 10) ?? ""} onChange={set("effective_from")} /></Field>
        <Field label="Effective to"><input className="input" type="date" value={v.effective_to?.slice?.(0, 10) ?? ""} onChange={set("effective_to")} /></Field>
        <Field label="Review tolerance (money)"><input className="input" value={v.tolerance} onChange={set("tolerance")} /></Field>
        <Field label="Rule owner"><select className="input" value={v.owner_id} onChange={set("owner_id")}><option value="" />
          {users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
        {v.method === "EVIDENCED" && <Field label="Society / contract reference"><input className="input" value={v.evidence_ref} onChange={set("evidence_ref")} /></Field>}
      </div>
      <datalist id="plats">{meta?.platforms.map((p) => <option key={p} value={p} />)}</datalist>
      <div style={{ marginTop: 10 }}>
        <Field label="Denominator - exactly what revenue the rate applies to">
          <textarea className="input" rows={2} value={v.denominator} onChange={set("denominator")} style={{ fontFamily: "var(--font)" }} />
        </Field>
      </div>
      <div style={{ marginTop: 12 }}>
        <ReasonForm label="Reason for this version" button={init.status === "APPROVED" ? "Create new draft version" : "Save draft"} busy={save.isPending} onSubmit={(t) => save.mutate(t)} />
      </div>
    </Drawer>
  );
}
