import { useEffect, useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api";
import { int } from "../format";
import { useApp } from "../session";
import { ClearDialog } from "../ClearData";
import { DropZone, Facts, FormDialog, MappingPill, NeedClient, Pager, ResetFilters } from "../parts";
import { Button, Card, Dialog, DownloadButton, Empty, Loading, More, Notice, Page, Pill, Select, day, when, type Tone } from "../ui";

type Link = { id: number; isrc: string; status: string; title: string | null };
type WorkRow = { id: number; internal_work_number: string | null; work_title: string; album: string | null; language: string | null; catalogue_status: string;
  status_label: string; status_note: string | null; links: Link[]; mapping_state: string };
type Works = { rows: WorkRow[]; total: number; offset: number;
  counts: Record<string, number>; statuses: { value: string; label: string }[]; mappings: { value: string; label: string }[] };

const WORK_TONE: Record<string, Tone> = { ACTIVE: "good", TO_REGISTER: "warn", REVIEW: "warn", INACTIVE: "neutral" };

export default function Catalogue({ tab, id }: { tab?: string; id?: number }) {
  const { go, me } = useApp();
  const [clearing, setClearing] = useState(false);
  const tabs = [["works", "Works"], ["conflicts", "Conflicts"], ["import", "Import catalogue"], ["history", "Import history"]];
  const cur = tabs.find((t) => t[0] === tab)?.[0] ?? "works";
  return (
    <NeedClient>{(cid) => (
      <Page title="Catalogue"
            actions={<><CatalogueExport cid={cid} />{me.can.clear_catalogue && <Button kind="danger" onClick={() => setClearing(true)}>Delete catalogue</Button>}</>}>
        {clearing && <ClearDialog cid={cid} kind="catalogue" onClose={() => setClearing(false)} onDone={() => go("catalogue/works")} />}
        <div className="tabs" role="tablist">
          {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={cur === k} className={cur === k ? "on" : ""}
                                         onClick={() => go(`catalogue/${k}`)}>{l}</button>)}
        </div>
        {cur === "works" && <WorkList key={id ?? 0} cid={cid} importId={id} />}
        {cur === "conflicts" && <Conflicts cid={cid} />}
        {cur === "import" && (id ? <ImportPreview importId={id} /> : <ImportStart cid={cid} />)}
        {cur === "history" && <History cid={cid} />}
      </Page>
    )}</NeedClient>
  );
}

function CatalogueExport({ cid }: { cid: number }) {
  const { toast } = useApp();
  return <DownloadButton kind="secondary" path={`/catalogue/export${qs({ client_id: cid })}`} onError={(m) => toast(m, true)}>Export catalogue</DownloadButton>;
}

// ================================================================== works
function WorkList({ cid, importId }: { cid: number; importId?: number }) {
  const { go } = useApp();
  const imp = useQuery({ queryKey: ["import", importId, "head"], enabled: !!importId,
    queryFn: () => api.get<ImportView>(`/catalogue/imports/${importId}${qs({ status: "NONE" })}`) });
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [mapping, setMapping] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const { me } = useApp();
  const data = useQuery({ queryKey: ["works", cid, q, status, mapping, offset, importId],
    queryFn: () => api.get<Works>(`/catalogue/works${qs({ client_id: cid, q, status, mapping, offset, import_id: importId })}`) });
  const d = data.data;
  return (
    <>
      {d && (
        <div className="summary">
          <div><span>Works</span><b>{int(d.counts.works)}</b></div>
          <div><span>ISRC links</span><b>{int(d.counts.links)}</b></div>
          <div><span>Verified links</span><b>{int(d.counts.verified)}</b></div>
          <div><span>Links needing verification</span><b>{int(d.counts.pending)}</b></div>
          <div><span>ISRCs in conflict</span><b>{int(d.counts.conflict_isrcs)}</b></div>
          <div><span>Works to review or register</span><b>{int((d.counts.review ?? 0) + (d.counts.to_register ?? 0))}</b></div>
        </div>
      )}
      {importId && (
        <Notice tone="good">Showing the {d ? int(d.total) : ""} songs of catalogue import #{importId}{imp.data ? ` (${imp.data.filename})` : ""}
          {imp.data?.status === "APPLIED" ? ` - applied ${when(imp.data.applied_at)}` : ""}. {" "}
          <Button kind="ghost" className="sm" onClick={() => go("catalogue/works")}>Show every work</Button>
          <Button kind="ghost" className="sm" onClick={() => go(`catalogue/import/${importId}`)}>The import's rows</Button></Notice>
      )}
      <Card>
        <div className="toolbar">
          <input className="input" placeholder="Search song title, album / film, work number or ISRC" value={q}
                 onChange={(e) => { setQ(e.target.value); setOffset(0); }} aria-label="Search" />
          <Select size="sm" label="Catalogue status" value={status} placeholder="Any status"
                  onChange={(v) => { setStatus(v); setOffset(0); }}
                  options={[{ value: "", label: "Any status" }, ...(d?.statuses ?? [])]} />
          <Select size="sm" label="Link status" value={mapping} placeholder="Any link status"
                  onChange={(v) => { setMapping(v); setOffset(0); }}
                  options={[{ value: "", label: "Any link status" }, ...(d?.mappings ?? [])]} />
          <ResetFilters active={!!(q || status || mapping)} onReset={() => { setQ(""); setStatus(""); setMapping(""); setOffset(0); }} />
          <span className="spacer" />
          {me.can.prepare && <Button kind="secondary" onClick={() => setAdding(true)}>Add a work</Button>}
        </div>
        {!d ? <Loading /> : d.rows.length === 0 ? (
          <Empty title={d.counts.works ? "No work matches" : "The catalogue is empty"}>
            {d.counts.works ? "Change the search or the filters." : <>Import the client's song list under <a href="#/catalogue/import">Import catalogue</a>.</>}
          </Empty>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Song title</th><th>Album / film</th><th>Work number</th><th>ISRCs</th><th>Links</th><th>Status</th></tr></thead>
              <tbody>
                {d.rows.map((w) => (
                  <tr key={w.id} className="click" onClick={() => setOpen(w.id)}>
                    <td><b>{w.work_title}</b>{w.language && <div className="muted small">{w.language}</div>}</td>
                    <td className="small">{w.album ?? <span className="muted">—</span>}</td>
                    <td className="mono">{w.internal_work_number ?? <i className="muted">none</i>}</td>
                    <td className="small">{w.links.slice(0, 4).map((l) => <span key={l.id} className={`code ${l.status.toLowerCase()}`}>{l.isrc}</span>)}
                      {w.links.length > 4 && <span className="muted"> +{w.links.length - 4}</span>}</td>
                    <td><MappingPill status={w.mapping_state} /></td>
                    <td><Pill tone={WORK_TONE[w.catalogue_status] ?? "neutral"}>{w.status_label}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d && <Pager total={d.total} offset={offset} size={100} onChange={setOffset} />}
      </Card>
      {open && <WorkDialog workId={open} onClose={() => setOpen(null)} />}
      {adding && <AddWork cid={cid} onClose={() => setAdding(false)} onDone={(id) => setOpen(id)} />}
    </>
  );
}

/** A work outside a catalogue import (the catalogue is a reference, not a limit). Typing the IPRS work number suggests
 *  the works already in the catalogue: picking one links the ISRCs to it (its title is filled in); a number that is not
 *  in the catalogue becomes a new work. New ISRC links need an Admin's verification. */
export function AddWork({ cid, onClose, onDone, number = "", title = "" }: { cid: number; onClose: () => void; onDone: (workId: number) => void;
  number?: string; title?: string }) {
  const qc = useQueryClient();
  const { toast } = useApp();
  const [f, setF] = useState({ internal_work_number: number, work_title: title, isrcs: "", note: "" });
  const [picked, setPicked] = useState<FoundWork | null>(null);
  const [auto, setAuto] = useState("");                              // the title filled in from the picked work
  const isrcs = f.isrcs.split("|").map((x) => x.trim()).filter(Boolean);
  const pick = (w: FoundWork | null) => {
    setPicked(w);
    if (w) { setF((x) => ({ ...x, work_title: w.work_title })); setAuto(w.work_title); }
    else if (auto) { setF((x) => ({ ...x, work_title: x.work_title === auto ? "" : x.work_title })); setAuto(""); }
  };
  return (
    <FormDialog title="Add a work to the catalogue" submit={picked ? (isrcs.length ? `Link ${isrcs.length} ISRC${isrcs.length === 1 ? "" : "s"} to this work` : "Open this work") : "Add work"}
                onClose={onClose}
                onSubmit={async () => {
                  if (picked) {
                    for (const isrc of isrcs) await api.post(`/catalogue/works/${picked.id}/links`, { isrc, recording_title: picked.work_title, note: f.note });
                    await qc.invalidateQueries({ queryKey: ["works"] });
                    if (isrcs.length) toast(`Linked to ${picked.work_title}. The new links need an Admin's verification.`);
                    onDone(picked.id);
                    return;
                  }
                  const d = await api.post<WorkDetail>("/catalogue/works", { client_id: cid, ...f });
                  await qc.invalidateQueries({ queryKey: ["works"] });
                  toast("Work added. Its ISRC links need an Admin's verification.");
                  onDone(d.work.id);
                }}>
      <WorkNumberField cid={cid} allowNew label="IPRS work number (leave empty if not registered yet)" value={f.internal_work_number} picked={picked}
                       onType={(v) => setF((x) => ({ ...x, internal_work_number: v }))} onPick={pick} />
      <label className="field">Song title<input className="input" required value={f.work_title} readOnly={!!picked}
                                                onChange={(e) => setF({ ...f, work_title: e.target.value })} />
        {picked && <span className="hint">Filled in from the catalogue. Clear the work number to add a new work instead.</span>}</label>
      <label className="field">ISRCs ({picked ? "linked to this work" : "optional"}, separated by |)<input className="input mono" value={f.isrcs}
                                                                                                         onChange={(e) => setF({ ...f, isrcs: e.target.value })} /></label>
      <label className="field">Evidence<textarea className="input" rows={2} required={!picked || isrcs.length > 0} value={f.note} placeholder="For example: confirmed as SVF's work by the client on …"
                                                 onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
    </FormDialog>
  );
}

export type FoundWork = { id: number; internal_work_number: string | null; work_title: string; catalogue_status: string; isrcs: number };

/** An IPRS work number with suggestions from the client's catalogue while typing (number or title). An exact number
 *  picks its work by itself. With allowNew, a number that is not in the catalogue is offered as a new work. */
export function WorkNumberField({ cid, label, value, picked, onType, onPick, allowNew, required }: {
  cid: number; label: string; value: string; picked: FoundWork | null; onType: (v: string) => void; onPick: (w: FoundWork | null) => void;
  allowNew?: boolean; required?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [term, setTerm] = useState(value.trim());
  useEffect(() => { const t = window.setTimeout(() => setTerm(value.trim()), 180); return () => window.clearTimeout(t); }, [value]);
  const q = useQuery({ queryKey: ["work-search", cid, term], enabled: term.length >= 2, staleTime: 30_000,
    queryFn: () => api.get<FoundWork[]>(`/catalogue/works/search${qs({ client_id: cid, q: term })}`) });
  const found = term.length >= 2 ? (q.data ?? []) : [];
  const exact = found.find((w) => w.internal_work_number === value.trim());
  useEffect(() => { if (exact && (!picked || picked.id !== exact.id)) onPick(exact); }, [exact?.id, picked?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const digits = /^\d+$/.test(value.trim());
  const items: ({ kind: "work"; w: FoundWork } | { kind: "new" })[] = [
    ...found.map((w) => ({ kind: "work" as const, w })), ...(allowNew && digits && !exact ? [{ kind: "new" as const }] : [])];
  const choose = (i: number) => {
    const it = items[i];
    setOpen(false);
    if (!it) return;
    if (it.kind === "new") onPick(null);
    else { onType(it.w.internal_work_number ?? ""); onPick(it.w); }
  };
  return (
    <div className="field wn-field">
      <label htmlFor={id}>{label}</label>
      <div className="typeahead">
        <input id={id} className="input mono" value={value} required={required} autoComplete="off" role="combobox"
               aria-expanded={open && items.length > 0} aria-controls={`${id}-list`} aria-autocomplete="list"
               aria-activedescendant={open && items.length ? `${id}-${active}` : undefined} placeholder="Type a work number or a song title"
               onChange={(e) => { onType(e.target.value); if (picked) onPick(null); setOpen(true); setActive(0); }}
               onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 120)}
               onKeyDown={(e) => {
                 if (!open || !items.length) { if (e.key === "ArrowDown") setOpen(true); return; }
                 if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(items.length - 1, active + 1)); }
                 else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, active - 1)); }
                 else if (e.key === "Enter") { e.preventDefault(); choose(active); }
                 else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
               }} />
        {open && items.length > 0 && (
          <ul id={`${id}-list`} role="listbox" className="typeahead-list">
            {items.map((it, i) => (
              <li key={it.kind === "new" ? "new" : it.w.id} id={`${id}-${i}`} role="option" aria-selected={i === active}
                  className={`select-opt ${i === active ? "active" : ""}`} onPointerDown={(e) => e.preventDefault()}
                  onPointerMove={() => i !== active && setActive(i)} onClick={() => choose(i)}>
                {it.kind === "new"
                  ? <span className="select-opt-t"><b>New work {value.trim()}</b><span className="select-opt-h">Not in the catalogue yet - add it as a new work</span></span>
                  : <span className="select-opt-t"><span><b className="mono">{it.w.internal_work_number ?? "no number"}</b> · {it.w.work_title}</span>
                      <span className="select-opt-h">Existing work · {it.w.isrcs} ISRC{it.w.isrcs === 1 ? "" : "s"} · {it.w.catalogue_status.replace("_", " ").toLowerCase()}</span></span>}
              </li>))}
          </ul>
        )}
      </div>
      {picked ? <span className="hint good-t">Existing work: {picked.work_title} ({picked.isrcs} ISRC{picked.isrcs === 1 ? "" : "s"} linked)</span>
        : allowNew && digits && term === value.trim() && !q.isFetching ? <span className="hint">New work number - not in the catalogue yet.</span> : null}
    </div>
  );
}

type WorkDetail = {
  work: WorkRow & { client_id: number; created_by_name: string | null; created_at: string; updated_at: string };
  links: { id: number; isrc: string; recording_title: string | null; status: string; status_label: string; source: string;
    note: string | null; valid_from: string; valid_to: string | null; verified_by: string | null; verified_at: string | null;
    current: boolean; other_works: { work_id: number; internal_work_number: string | null; work_title: string; mapping_status: string }[] }[];
  events: { at: string; event: string; from_status: string | null; to_status: string | null; note: string | null; actor: string | null; isrc: string }[];
  can_verify: boolean;
};

export function WorkDialog({ workId, onClose }: { workId: number; onClose: () => void }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["work", workId], queryFn: () => api.get<WorkDetail>(`/catalogue/works/${workId}`) });
  const [act, setAct] = useState<{ kind: "VERIFIED" | "REJECTED" | "move"; link: WorkDetail["links"][number] } | null>(null);
  const [adding, setAdding] = useState(false);
  const refresh = (d: WorkDetail) => {
    qc.setQueryData(["work", workId], d);
    qc.invalidateQueries({ queryKey: ["works"] });
    qc.invalidateQueries({ queryKey: ["conflicts"] });
  };
  const d = q.data;
  return (
    <Dialog title={d ? d.work.work_title : "Work"} sub={d ? `IPRS work number ${d.work.internal_work_number ?? "not registered"}` : undefined}
            onClose={onClose} wide="xl">
      {!d ? <Loading /> : (
        <div className="form full">
          <Facts items={[["Catalogue status", <><Pill tone={WORK_TONE[d.work.catalogue_status] ?? "neutral"}>{d.work.status_label}</Pill>{d.work.status_note && <div className="muted small">{d.work.status_note}</div>}</>],
            ...(d.work.album ? [["Album / film", d.work.album] as [string, string]] : []), ...(d.work.language ? [["Language", d.work.language] as [string, string]] : []),
            ["Added", `${day(d.work.created_at)}${d.work.created_by_name ? ` by ${d.work.created_by_name}` : ""}`]]} />
          <div className="queue-bar"><h2 className="grow">ISRC links</h2>
            {me.can.prepare && <Button kind="secondary" className="sm" onClick={() => setAdding(true)}>Link an ISRC</Button>}</div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>ISRC</th><th>Recording title</th><th>Status</th><th>Source</th><th>Verified</th>{d.can_verify && <th></th>}</tr></thead>
              <tbody>
                {d.links.map((l) => (
                  <tr key={l.id} className={l.current ? "" : "inactive"}>
                    <td className="mono">{l.isrc}</td>
                    <td>{l.recording_title}{l.other_works.length > 0 && <div className="bad-t small">Also linked to {l.other_works.map((o) => o.internal_work_number ?? o.work_title).join(", ")}</div>}
                      {l.note && <div className="muted small">{l.note}</div>}</td>
                    <td>{l.current ? <MappingPill status={l.status} /> : <Pill tone="neutral">Closed {day(l.valid_to)}</Pill>}</td>
                    <td className="small">{l.source.replace("_", " ").toLowerCase()}</td>
                    <td className="small">{l.verified_by ? `${l.verified_by}, ${day(l.verified_at)}` : ""}</td>
                    {d.can_verify && <td className="num nowrap">{l.current && <>
                      {l.status !== "VERIFIED" && <Button kind="ghost" className="sm" onClick={() => setAct({ kind: "VERIFIED", link: l })}>Verify</Button>}
                      <Button kind="ghost" className="sm" onClick={() => setAct({ kind: "REJECTED", link: l })}>Reject</Button>
                      <Button kind="ghost" className="sm" onClick={() => setAct({ kind: "move", link: l })}>Move</Button>
                    </>}</td>}
                  </tr>
                ))}
                {d.links.length === 0 && <tr><td colSpan={6} className="muted">No ISRC is linked to this work.</td></tr>}
              </tbody>
            </table>
          </div>
          {!d.can_verify && d.links.some((l) => l.current && l.status !== "VERIFIED") &&
            <Notice>Links that are not verified cannot support an IPRS enquiry. An Admin verifies them.</Notice>}
          <More label={`History (${d.events.length})`}>
            <ul className="plain small">{d.events.map((e, i) => <li key={i}>{when(e.at)} · <b>{e.isrc}</b> · {e.event.toLowerCase()}
              {e.to_status ? ` → ${e.to_status.toLowerCase()}` : ""}{e.actor ? ` · ${e.actor}` : ""}{e.note ? ` · ${e.note}` : ""}</li>)}</ul>
          </More>
          {d.can_verify && <EditWork d={d} onSaved={refresh} />}
          <div className="actions end"><Button onClick={onClose}>Close</Button></div>
        </div>
      )}
      {act && act.kind !== "move" && <LinkStatus link={act.link} status={act.kind} onClose={() => setAct(null)} onDone={refresh} />}
      {act && act.kind === "move" && <MoveLink link={act.link} onClose={() => setAct(null)} onDone={(x) => { refresh(x); toast("Link corrected. The old link is kept in the history."); }} />}
      {adding && <AddLink workId={workId} onClose={() => setAdding(false)} onDone={refresh} />}
    </Dialog>
  );
}

function LinkStatus({ link, status, onClose, onDone }: { link: { id: number; isrc: string }; status: string;
  onClose: () => void; onDone: (d: WorkDetail) => void }) {
  const [note, setNote] = useState("");
  return (
    <FormDialog title={status === "VERIFIED" ? `Verify ${link.isrc}` : `Reject ${link.isrc}`} submit={status === "VERIFIED" ? "Verify link" : "Reject link"}
                danger={status === "REJECTED"} onClose={onClose}
                onSubmit={async () => onDone(await api.post<WorkDetail>(`/catalogue/links/${link.id}/status`, { status, note }))}>
      <p>{status === "VERIFIED" ? "Verifying confirms that this ISRC is a recording of this work. Verified links can support IPRS enquiries."
        : "Rejecting closes this link. It stays in the history and its revenue no longer reaches this work."}</p>
      <label className="field">Note (evidence or reason)<textarea className="input" rows={3} value={note} required={status === "REJECTED"}
                                                                  onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}

function MoveLink({ link, onClose, onDone }: { link: { id: number; isrc: string }; onClose: () => void; onDone: (d: WorkDetail) => void }) {
  const { clientId } = useApp();
  const [to, setTo] = useState("");
  const [picked, setPicked] = useState<FoundWork | null>(null);
  const [note, setNote] = useState("");
  return (
    <FormDialog title={`Move ${link.isrc} to another work`} submit="Move link" onClose={onClose}
                onSubmit={async () => onDone(await api.post<WorkDetail>(`/catalogue/links/${link.id}/move`, { to_work: picked ? (picked.internal_work_number ?? `id:${picked.id}`) : to, note }))}>
      <p>The current link is closed and kept in the history; a verified link to the right work is made.</p>
      {clientId ? <WorkNumberField cid={clientId} required label="IPRS work number of the right work" value={to} picked={picked} onType={setTo} onPick={setPicked} />
        : <label className="field">IPRS work number of the right work<input className="input" required value={to} onChange={(e) => setTo(e.target.value)} /></label>}
      <label className="field">Why<textarea className="input" rows={3} required value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}

function AddLink({ workId, onClose, onDone }: { workId: number; onClose: () => void; onDone: (d: WorkDetail) => void }) {
  const { me } = useApp();
  const [f, setF] = useState({ isrc: "", recording_title: "", note: "", verify: false });
  return (
    <FormDialog title="Link an ISRC to this work" submit="Link ISRC" onClose={onClose}
                onSubmit={async () => onDone(await api.post<WorkDetail>(`/catalogue/works/${workId}/links`, f))}>
      <label className="field">ISRC<input className="input mono" required value={f.isrc} placeholder="INS2X1400012"
                                          onChange={(e) => setF({ ...f, isrc: e.target.value })} /></label>
      <label className="field">Recording title (optional)<input className="input" value={f.recording_title}
                                                                onChange={(e) => setF({ ...f, recording_title: e.target.value })} /></label>
      <label className="field">Evidence<textarea className="input" rows={2} value={f.note} placeholder="For example: confirmed by the client by email on …"
                                                 onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
      {me.can.verify_mappings
        ? <label className="check"><input type="checkbox" checked={f.verify} onChange={(e) => setF({ ...f, verify: e.target.checked })} /> I have checked the evidence: mark the link as verified</label>
        : <p className="hint">The link starts as 'needs verification'; an Admin verifies it.</p>}
    </FormDialog>
  );
}

function EditWork({ d, onSaved }: { d: WorkDetail; onSaved: (x: WorkDetail) => void }) {
  const { toast } = useApp();
  const [f, setF] = useState({ work_title: d.work.work_title, catalogue_status: d.work.catalogue_status, status_note: d.work.status_note ?? "",
    internal_work_number: "", album: d.work.album ?? "" });
  const [busy, setBusy] = useState(false);
  return (
    <More label="Edit this work (Admin)">
      <form className="form" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          const body: Record<string, string> = { work_title: f.work_title, catalogue_status: f.catalogue_status, status_note: f.status_note, album: f.album };
          if (f.internal_work_number) body.internal_work_number = f.internal_work_number;
          onSaved(await api.patch<WorkDetail>(`/catalogue/works/${d.work.id}`, body));
          toast("Saved.");
        } catch (x) { toast((x as Error).message, true); } finally { setBusy(false); }
      }}>
        <div className="form-grid">
          <label className="field">Title<input className="input" value={f.work_title} onChange={(e) => setF({ ...f, work_title: e.target.value })} /></label>
          <label className="field">Status<Select value={f.catalogue_status} onChange={(v) => setF({ ...f, catalogue_status: v })}
                                                 options={[["ACTIVE", "Active"], ["REVIEW", "Needs review"], ["TO_REGISTER", "To register"], ["INACTIVE", "Inactive"]].map(([value, label]) => ({ value, label }))} /></label>
          {!d.work.internal_work_number && <label className="field">IPRS work number (once registered)<input className="input" value={f.internal_work_number}
                                                                                                               onChange={(e) => setF({ ...f, internal_work_number: e.target.value })} /></label>}
          <label className="field">Album / film<input className="input" value={f.album} onChange={(e) => setF({ ...f, album: e.target.value })} /></label>
          <label className="field">Note<input className="input" value={f.status_note} onChange={(e) => setF({ ...f, status_note: e.target.value })} /></label>
        </div>
        <div className="actions"><Button kind="primary" type="submit" busy={busy}>Save</Button></div>
      </form>
    </More>
  );
}

// ================================================================== conflicts
type Conflict = { isrc: string; claims: { link_id: number; work_id: number; work_number: string | null; work_title: string; status: string; recording_title: string | null }[] };

function Conflicts({ cid }: { cid: number }) {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["conflicts", cid], queryFn: () => api.get<Conflict[]>(`/catalogue/conflicts${qs({ client_id: cid })}`) });
  const [keep, setKeep] = useState<{ c: Conflict; link_id: number } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [find, setFind] = useState("");
  if (!q.data) return <Loading />;
  const rows = q.data.filter((c) => !find || c.isrc.includes(find.toUpperCase()) || c.claims.some((x) => (x.work_title + (x.work_number ?? "")).toLowerCase().includes(find.toLowerCase())));
  return (
    <Card title={`ISRCs linked to more than one work (${q.data.length})`}>
      {q.data.length === 0 ? <Empty title="No conflicts">Every ISRC belongs to one work.</Empty> : (
        <>
          <div className="toolbar"><input className="input" placeholder="Find an ISRC, title or work number" value={find} onChange={(e) => setFind(e.target.value)} />
            <ResetFilters active={!!find} onReset={() => setFind("")} /></div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>ISRC</th><th>Claimed by</th></tr></thead>
              <tbody>{rows.slice(0, 300).map((c) => (
                <tr key={c.isrc}>
                  <td className="mono">{c.isrc}</td>
                  <td>{c.claims.map((x) => (
                    <div key={x.link_id} className="row nowrap claim">
                      <button className="linkish" onClick={() => setOpen(x.work_id)}>{x.work_number ?? "no number"} · {x.work_title}</button>
                      {x.recording_title && x.recording_title !== x.work_title && <span className="muted small">({x.recording_title})</span>}
                      <MappingPill status={x.status} />
                      {me.can.verify_mappings && <Button kind="ghost" className="sm" onClick={() => setKeep({ c, link_id: x.link_id })}>Keep this one</Button>}
                    </div>))}</td>
                </tr>))}</tbody>
            </table>
          </div>
          {rows.length > 300 && <p className="muted small">Showing 300 of {rows.length}. Search to narrow the list.</p>}
        </>
      )}
      {keep && <KeepDialog c={keep.c} linkId={keep.link_id} onClose={() => setKeep(null)} onDone={async () => {
        await qc.invalidateQueries({ queryKey: ["conflicts"] });
        qc.invalidateQueries({ queryKey: ["works"] });
        toast("Conflict resolved. The other links are closed and kept in the history.");
      }} />}
      {open && <WorkDialog workId={open} onClose={() => setOpen(null)} />}
    </Card>
  );
}

function KeepDialog({ c, linkId, onClose, onDone }: { c: Conflict; linkId: number; onClose: () => void; onDone: () => Promise<void> }) {
  const [note, setNote] = useState("");
  const others = c.claims.filter((x) => x.link_id !== linkId);
  const kept = c.claims.find((x) => x.link_id === linkId)!;
  return (
    <FormDialog title={`Keep ${c.isrc} on work ${kept.work_number ?? kept.work_title}`} submit="Keep and verify" onClose={onClose}
                onSubmit={async () => {
                  for (const o of others) await api.post(`/catalogue/links/${o.link_id}/status`, { status: "REJECTED", note: `${note} (kept on work ${kept.work_number ?? kept.work_title})` });
                  await api.post(`/catalogue/links/${linkId}/status`, { status: "VERIFIED", note });
                  await onDone();
                }}>
      <p>The link{others.length > 1 ? "s" : ""} to {others.map((o) => o.work_number ?? o.work_title).join(", ")} will be rejected (kept in the history), and this link verified.</p>
      <label className="field">Evidence<textarea className="input" rows={3} required value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </FormDialog>
  );
}

// ================================================================== import
type ImportView = {
  id: number; filename: string; status: string; sheet: string; header_row: number; uploaded_by: string; uploaded_at: string;
  reviewed_by: string | null; applied_at: string | null; stale: boolean; note: string | null; total: number; offset: number;
  counts: { total_rows: number; new_works: number; new_recordings: number; new_mappings: number; existing_mappings: number;
    conflicts: number; conflict_links: number; duplicate_rows: number; invalid_rows: number; warning_rows: number; by_action: Record<string, number> };
  rows: { row: number; title: string; work: string | null; isrcs: string[]; invalid: string[]; action: string; action_label: string;
    status: string; status_label: string; message: string | null; sheet?: string | null; raw: { title: string; work: string; isrc: string; album?: string; language?: string } }[];
  statuses: { value: string; label: string }[]; actions: { value: string; label: string }[];
  applied?: { works_created: number; links_created: number; conflicts: number; older_links_flagged: number; verified: boolean; albums_filled?: number };
};
const ROW_TONE: Record<string, Tone> = { OK: "good", WARNING: "warn", CONFLICT: "bad", DUPLICATE: "neutral", INVALID: "bad" };

function ImportStart({ cid }: { cid: number }) {
  const { go, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const stored = useQuery({ queryKey: ["song-lists", cid], queryFn: () => api.get<{ id: number; filename: string; uploaded_at: string; entries: number; applied_at: string | null }[]>(`/catalogue/song-lists${qs({ client_id: cid })}`) });
  const upload = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("client_id", String(cid));
    fd.append("file", files[0], files[0].name);
    try {
      const v = await api.form<ImportView>("/catalogue/imports", fd);
      go(`catalogue/import/${v.id}`);
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  return (
    <>
      <Card title="Import a catalogue workbook">
        {busy ? <Loading text="Reading the workbook and comparing it with the catalogue…" /> :
          <DropZone label="Drag the catalogue workbook here" hint="Excel (.xlsx) or CSV - song name, IPRS work number / song code, ISRCs (one cell or ISRC 1, ISRC 2 …), album" onFiles={upload} />}
      </Card>
      {stored.data && stored.data.length > 0 && (
        <Card title="Or use a song list that was already uploaded">
          <ul className="list">{stored.data.map((f) => (
            <li key={f.id}>
              <div><div className="li-t">{f.filename}</div><div className="muted small">{int(f.entries)} rows · uploaded {day(f.uploaded_at)}{f.applied_at ? ` · applied ${day(f.applied_at)}` : ""}</div></div>
              <Button kind="secondary" disabled={busy} onClick={async () => {
                setBusy(true);
                try { const v = await api.post<ImportView>("/catalogue/imports/from-file", { client_id: cid, file_id: f.id }); go(`catalogue/import/${v.id}`); }
                catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
              }}>Preview</Button>
            </li>))}</ul>
        </Card>
      )}
    </>
  );
}

function ImportPreview({ importId }: { importId: number }) {
  const { go, toast } = useApp();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [verify, setVerify] = useState(true);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<ImportView | null>(null);
  const v = useQuery({ queryKey: ["import", importId, status, q, offset],
    queryFn: () => api.get<ImportView>(`/catalogue/imports/${importId}${qs({ status, q, offset })}`) });
  if (!v.data) return <Loading />;
  const d = v.data;
  const c = d.counts;
  const tiles: [string, number, string, string][] = [
    ["New works", c.new_works, "", "Work numbers not yet in the catalogue"],
    ["New ISRC links", c.new_mappings, "", `${int(c.new_recordings)} ISRCs never seen before`],
    ["Links already known", c.existing_mappings, "", "Nothing changes for these"],
    ["ISRCs in conflict", c.conflicts, "CONFLICT", "Claimed by more than one work"],
    ["Rows to check", c.warning_rows, "WARNING", "Different titles, no work number, …"],
    ["Duplicate rows", c.duplicate_rows, "DUPLICATE", "Same as an earlier row"],
    ["Invalid rows", c.invalid_rows, "INVALID", "Not applied (see the report)"],
  ];
  const run = async (what: string, fn: () => Promise<ImportView | unknown>, msg: string) => {
    setBusy(what);
    try {
      const r = await fn();
      if (what === "apply") setResult(r as ImportView);
      if (what === "apply" && (r as ImportView).applied) {         // done: show the songs in the catalogue
        const a = (r as ImportView).applied!;
        qc.invalidateQueries({ queryKey: ["works"] });
        toast(`Applied: ${int(a.works_created)} new works and ${int(a.links_created)} ISRC links are in the catalogue${a.conflicts ? `; ${int(a.conflicts)} ISRCs recorded as conflicts` : ""}.`);
        setBusy("");
        go(`catalogue/works/${importId}`);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["import", importId] });
      qc.invalidateQueries({ queryKey: ["works"] });
      qc.invalidateQueries({ queryKey: ["conflicts"] });
      toast((r as ImportView)?.note ?? msg);
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  const applied = d.status === "APPLIED";
  const multi = d.sheet.includes(" + ");
  return (
    <>
      <Card title={`${d.filename}`} sub={`Sheet '${d.sheet}', heading row ${d.header_row} · ${int(c.total_rows)} rows · uploaded by ${d.uploaded_by} ${when(d.uploaded_at)}`}
            actions={<Pill tone={applied ? "good" : d.status === "PREVIEW" ? "info" : "neutral"}>{applied ? "Applied" : d.status === "PREVIEW" ? "Preview - not applied yet" : d.status.toLowerCase()}</Pill>}>
        {d.note && <Notice>{d.note}</Notice>}
        {d.stale && <Notice tone="warn">The catalogue changed after this preview was made. Applying will refresh the preview first.</Notice>}
        {(result?.applied || applied) && <Notice tone="good">Applied{d.reviewed_by ? ` by ${d.reviewed_by}` : ""}{d.applied_at ? ` on ${when(d.applied_at)}` : ""}.
          {result?.applied && <> {int(result.applied.works_created)} works and {int(result.applied.links_created)} links added; {int(result.applied.conflicts)} ISRCs recorded as conflicts
            {result.applied.older_links_flagged ? `; ${result.applied.older_links_flagged} older links flagged as conflicts` : ""}.</>}</Notice>}
        <div className="tiles">
          {tiles.map(([t, n, st, s]) => (
            <button key={t} className={`tile ${st && status === st ? "on" : ""}`} disabled={!st} onClick={() => { setStatus(status === st ? "" : st); setOffset(0); }}>
              <span className="tile-n">{int(n)}</span><span className="tile-t">{t}</span><span className="tile-s">{s}</span>
            </button>))}
        </div>
        <div className="actions">
          {d.status === "PREVIEW" && <>
            <label className="check"><input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} /> Mark clean links from this catalogue as verified (the client's catalogue is the evidence)</label>
            <span className="spacer" />
            <Button kind="primary" busy={busy === "apply"} onClick={() => run("apply", () => api.post(`/catalogue/imports/${importId}/apply`, { verify_mappings: verify }), "Applied.")}>
              Apply {int(c.total_rows - c.invalid_rows - c.duplicate_rows)} rows</Button>
            <Button kind="ghost" busy={busy === "discard"} onClick={() => run("discard", () => api.post(`/catalogue/imports/${importId}/discard`), "Preview discarded.")}>Discard</Button>
          </>}
          <DownloadButton kind="secondary" path={`/catalogue/imports/${importId}/report`} onError={(m) => toast(m, true)}>Download rows to check</DownloadButton>
          {applied && <Button kind="primary" onClick={() => go(`catalogue/works/${importId}`)}>See these songs in the catalogue</Button>}
        </div>
      </Card>
      <Card>
        <div className="toolbar">
          <input className="input" placeholder="Find a title, work number or ISRC" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
          <Select size="sm" label="Result" value={status} placeholder="Every row" onChange={(x) => { setStatus(x); setOffset(0); }}
                  options={[{ value: "", label: "Every row" }, ...d.statuses]} />
          <ResetFilters active={!!(q || status)} onReset={() => { setQ(""); setStatus(""); setOffset(0); }} />
        </div>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Row</th><th>Track name</th><th>Album / film</th><th>Work number</th><th>ISRCs</th><th>Result</th><th>What happens</th></tr></thead>
            <tbody>{d.rows.map((r) => (
              <tr key={`${r.sheet ?? ""}${r.row}`}>
                <td className="num">{r.row}{multi && r.sheet && <div className="muted small">{r.sheet}</div>}</td><td>{r.title}</td><td className="small">{r.raw.album ?? <span className="muted">—</span>}</td><td className="mono">{r.work ?? r.raw.work}</td>
                <td className="small mono">{r.isrcs.join(" | ")}{r.invalid.length > 0 && <div className="bad-t">Unreadable: {r.invalid.join(", ")}</div>}</td>
                <td><Pill tone={ROW_TONE[r.status] ?? "neutral"}>{r.status_label}</Pill></td>
                <td className="small"><b>{r.action_label}</b>{r.message && <div className="muted">{r.message}</div>}</td>
              </tr>))}</tbody>
          </table>
        </div>
        <Pager total={d.total} offset={offset} size={200} onChange={setOffset} />
      </Card>
    </>
  );
}

function History({ cid }: { cid: number }) {
  const { go } = useApp();
  const q = useQuery({ queryKey: ["imports", cid], queryFn: () => api.get<{ id: number; filename: string; status: string; uploaded_at: string; applied_at: string | null;
    total_rows: number; new_works_count: number; new_mappings_count: number; conflict_count: number; invalid_rows_count: number; uploaded_by: string }[]>(`/catalogue/imports${qs({ client_id: cid })}`) });
  if (!q.data) return <Loading />;
  return (
    <Card title="Catalogue imports">
      {q.data.length === 0 ? <Empty title="No imports yet" /> : (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>#</th><th>File</th><th>Status</th><th className="num">Rows</th><th className="num">New works</th><th className="num">New links</th><th className="num">Conflicts</th><th className="num">Invalid</th><th>Uploaded</th></tr></thead>
          <tbody>{q.data.map((i) => (
            <tr key={i.id} className="click" onClick={() => go(`catalogue/import/${i.id}`)}>
              <td>{i.id}</td><td>{i.filename}</td>
              <td><Pill tone={i.status === "APPLIED" ? "good" : i.status === "PREVIEW" ? "info" : "neutral"}>{i.status.toLowerCase()}</Pill></td>
              <td className="num">{int(i.total_rows)}</td><td className="num">{int(i.new_works_count)}</td><td className="num">{int(i.new_mappings_count)}</td>
              <td className="num">{int(i.conflict_count)}</td><td className="num">{int(i.invalid_rows_count)}</td>
              <td className="small">{when(i.uploaded_at)} · {i.uploaded_by}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </Card>
  );
}
