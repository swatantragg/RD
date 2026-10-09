import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../state";
import { Card, Empty, ErrorNote, Kv, Money, PageHead, Spinner, Stat, StateBadge } from "../components/ui";
import { compact, int, period, when, words } from "../format";

type Dash = {
  files: { status: string; income_type: string | null; n: number }[];
  run: any; packs: { status: string; n: number }[]; cases: { status: string; payment_status: string; n: number }[];
  follow_ups_due: number; rules_draft: number; pack_draft: { id: number; version_no: number; built_by: number } | null;
  identity: { compositions: number; recordings: number; links_approved: number; links_proposed: number; issues_open: number;
    candidates_pending: number; version: { version_no: number; approved_at: string } | null };
  recent: { id: number; at: string; actor: string; action: string; object_kind: string; object_id: string }[];
};

export default function Overview() {
  const { clientId, client, go, me, can } = useApp();
  const q = useQuery({ queryKey: ["dash", clientId], queryFn: () => api.get<Dash>(`/dashboard/${clientId}`), enabled: !!clientId });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const nFiles = d.files.reduce((a, f) => a + f.n, 0);
  const held = d.files.filter((f) => !["VALIDATED", "SUPERSEDED", "EXCLUDED"].includes(f.status)).reduce((a, f) => a + f.n, 0);
  const valid = d.files.filter((f) => f.status === "VALIDATED").reduce((a, f) => a + f.n, 0);
  const sm = d.run?.summary;
  const cur = sm?.by_currency?.[0];
  const openCases = d.cases.filter((c) => !c.status.startsWith("CLOSED")).reduce((a, c) => a + c.n, 0);
  const packStatus = (s: string) => d.packs.find((p) => p.status === s)?.n ?? 0;
  const steps = [
    { k: "A–B", t: "Intake & validation", route: "intake", cls: nFiles === 0 ? "idle" : held ? "wait" : "ok",
      s: nFiles ? `${valid} validated · ${held} held at a gate` : "upload statements, reports, catalogue" },
    { k: "C", t: "Identities", route: "identity", cls: d.identity.version ? (d.identity.candidates_pending ? "wait" : "ok") : "block",
      s: d.identity.version ? `version v${d.identity.version.version_no} · ${d.identity.issues_open} open issues` : "no approved identity version" },
    { k: "E", t: "Rules", route: "rules", cls: d.rules_draft ? "wait" : "ok", s: d.rules_draft ? `${d.rules_draft} draft(s) awaiting approval` : "rule versions frozen" },
    { k: "D·F·G", t: "Comparison", route: d.run ? `compare/${d.run.id}` : "compare", cls: d.run ? "ok" : "idle",
      s: d.run ? `run v${d.run.version_no} · ${int(sm.groups)} groups` : "no run yet" },
    { k: "H1–H4", t: "Report pack", route: "packs", cls: d.pack_draft ? "wait" : packStatus("SENT") ? "ok" : "idle",
      s: d.pack_draft ? `pack v${d.pack_draft.version_no} awaiting approval` : packStatus("SENT") ? `${packStatus("SENT")} sent` : "not built" },
    { k: "H5", t: "Cases", route: "cases", cls: d.follow_ups_due ? "block" : openCases ? "wait" : "idle",
      s: `${openCases} open · ${d.follow_ups_due} follow-up(s) due` },
  ];
  const todo: [string, string][] = [];
  if (can("upload") && held) todo.push([`${held} file(s) held at a validation gate`, "intake"]);
  if (can("identity") && d.identity.candidates_pending) todo.push([`${d.identity.candidates_pending} duplicate candidate(s) to decide`, "identity"]);
  if (can("identity") && d.identity.issues_open) todo.push([`${d.identity.issues_open} identity issue(s) open`, "identity"]);
  if (can("rule_approve") && d.rules_draft) todo.push([`${d.rules_draft} rule draft(s) to approve`, "rules"]);
  if (can("pack_approve") && d.pack_draft && d.pack_draft.built_by !== me.id) todo.push([`Report pack v${d.pack_draft.version_no} awaits your approval`, "packs"]);
  if (can("send") && packStatus("APPROVED")) todo.push(["Approved pack ready to send - record the dispatch", "packs"]);
  if (d.follow_ups_due) todo.push([`${d.follow_ups_due} case follow-up(s) due`, "cases"]);
  return (
    <>
      <PageHead title={client?.name ?? "Overview"}>
        Member {client?.member_id ?? "—"} · {client?.society} · route {client?.collection_route} · mandate{" "}
        {client?.mandate_verified ? <StateBadge state="APPROVED">verified</StateBadge> : <StateBadge state="HOLD">not verified</StateBadge>}
      </PageHead>
      <div className="flow section">
        {steps.map((s) => (
          <button key={s.k} className={`step ${s.cls}`} onClick={() => go(s.route)}>
            <div className="k">{s.k}</div>
            <div className="t">{s.t}</div>
            <div className="s">{s.s}</div>
          </button>
        ))}
      </div>
      {sm ? (
        <div className="kpis section">
          <Stat label="Recording revenue R (in scope)" value={compact(sm.r_in_scope)} meta={`${compact(sm.r_unmapped)} unmapped - listed as exceptions`} />
          <Stat label="Publishing P (in scope)" value={compact(sm.p_in_scope)} meta="counted once per composition" />
          <Stat label="Indicative benchmark B" value={compact(cur?.b)} meta={`${int(cur?.comparable_groups)} comparable groups`} />
          <Stat label="Positive gaps (for clarification)" value={compact(cur?.positive_gaps)} meta={`above benchmark ${compact(cur?.above_benchmark)} - shown separately`} />
          <Stat label="No matching entry (provisional)" value={int(cur?.provisional_groups)} meta={`provisional B ${compact(cur?.provisional_b)}`} />
          <Stat label="Held / status enquiry" value={int((sm.outcomes.HOLD ?? 0) + (sm.outcomes.STATUS_ENQUIRY ?? 0))} meta="no monetary comparison" />
        </div>
      ) : null}
      <div className="grid2">
        <Card title="Next actions for you" sub={me.roles.join(", ").replace(/_/g, " ")}>
          {todo.length ? (
            <div className="col">
              {todo.map(([t, r]) => (
                <div key={t} className="row"><span className="dot" style={{ background: "var(--warn)" }} />{t}<span className="spacer" />
                  <button className="btn sm" onClick={() => go(r)}>Open</button></div>
              ))}
            </div>
          ) : <Empty>Nothing waiting on you.</Empty>}
        </Card>
        <Card title="Latest comparison" sub={d.run ? `run v${d.run.version_no} · ${when(d.run.created_at)}` : undefined}
              actions={d.run && <button className="btn sm" onClick={() => go(`compare/${d.run.id}`)}>Open run</button>}>
          {d.run ? (
            <Kv items={[
              ["Scope", `${d.run.platform} · ${d.run.territory} · ${words(d.run.use_type)} · ${words(d.run.right_scope)}`],
              ["Usage period", period(d.run.period_from, d.run.period_to)],
              ["Statement cutoff", d.run.cutoff],
              ["Rule", sm.rule ? `${sm.rule.key} v${sm.rule.version} (${words(sm.method)})` : words(sm.method)],
              ["Below comparison", int(sm.outcomes.BELOW_COMPARISON ?? 0)],
              ["Within / above", int(sm.outcomes.WITHIN_OR_ABOVE ?? 0)],
              ["Positive gaps", <Money v={cur?.positive_gaps} />],
              ["Controls", d.run.checks.map((c: any) => <div key={c.check}><StateBadge state={c.result} /> {c.check}</div>)],
            ]} />
          ) : <Empty>No comparison run yet.</Empty>}
        </Card>
        <Card title="Recent activity" flush>
          <div className="tbl-wrap"><table className="tbl">
            <tbody>
              {d.recent.map((e) => (
                <tr key={e.id}><td className="nowrap muted small">{when(e.at)}</td><td className="small">{e.actor.split("@")[0]}</td><td className="small">{e.action}</td>
                  <td className="muted small">{e.object_kind} {e.object_id}</td></tr>
              ))}
            </tbody>
          </table></div>
        </Card>
        <Card title="How a figure becomes a question" sub="Approval draft v1.0 flow">
          <ol className="small ink2" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            <li><b>A</b> classify each file by the right paid for (publishing / recording / usage).</li>
            <li><b>B</b> validate: usable, fields valid, reconciled to totals, duplicates decided.</li>
            <li><b>C</b> map works ↔ recordings; fuzzy candidates need a human; freeze an identity version.</li>
            <li><b>D</b> compare like-for-like: rights, scope, timing and basis must align.</li>
            <li><b>E</b> rule: evidenced method, or 6% MRM <i>indicative benchmark</i>; frozen versions.</li>
            <li><b>F</b> route: money B = R × k, streams B = N × q only with an approved q.</li>
            <li><b>G</b> outcome: hold, no matching entry, coverage-only, below, within/above.</li>
            <li><b>H</b> pack + email, approval by someone else, logged dispatch, reply tracking.</li>
          </ol>
        </Card>
      </div>
    </>
  );
}
