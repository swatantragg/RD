import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { local, useApp } from "../session";
import type { RunSummary } from "../types";
import { Button, Card, Empty, Loading, RunStatus, when } from "../ui";

type HomeData = {
  next: { kind: string; text: string; run_id?: number };
  runs: RunSummary[]; attention: RunSummary[];
  published: { id: number; generation: string; published_at: string; client_code: string; run_id: number }[];
  can_prepare: boolean; clients: number;
};

export function Guide({ onClose }: { onClose?: () => void }) {
  return (
    <Card title="How it works" sub="Five steps. The checks happen in the background."
          actions={onClose && <Button kind="ghost" onClick={onClose}>Got it, hide this</Button>}>
      <ol className="guide">
        <li><b>Select a client.</b> Choose whose reports you are preparing.</li>
        <li><b>Upload the files.</b> Royalty statements, platform reports and the client's song list - all at once.
          Each file is recognised automatically.</li>
        <li><b>Check for issues.</b> We check every statement's totals and tell you, in plain words, if anything needs
          your answer.</li>
        <li><b>Process the data.</b> One button. You can leave the page and come back.</li>
        <li><b>Preview, publish and download.</b> The master report, the missing-songs report and the out-of-scope
          report. Publishing saves the final version under the next report number.</li>
      </ol>
    </Card>
  );
}

export default function Home() {
  const { me, go } = useApp();
  const [guide, setGuide] = useState(local.get("guide.dismissed") !== "1");
  const q = useQuery({ queryKey: ["home"], queryFn: () => api.get<HomeData>("/home"), refetchInterval: 15000 });
  if (q.isLoading || !q.data) return <Loading />;
  const d = q.data;
  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Hello, {me.name.split(" ")[0]}</h1>
          <p className="next">{d.next.text}</p>
        </div>
        <div className="hero-actions">
          {d.next.kind === "CONTINUE" && d.next.run_id &&
            <Button kind="secondary" onClick={() => go(`process/${d.next.run_id}`)}>Continue</Button>}
          {me.can.prepare ? <Button kind="primary" className="big" onClick={() => go("process")}>New Processing Run</Button>
            : <Button kind="primary" className="big" onClick={() => go("reports")}>Open Past Reports</Button>}
        </div>
      </section>

      {guide && <Guide onClose={() => { local.set("guide.dismissed", "1"); setGuide(false); }} />}

      <div className="two">
        <Card title="Recent processing runs" actions={d.runs.length > 0 && me.can.prepare && <Button kind="ghost" onClick={() => go("process")}>Start another</Button>}>
          {d.runs.length === 0 ? (
            <Empty title="No processing runs yet">
              {me.can.prepare ? <>Start with <b>New Processing Run</b>. You will be guided through each step.</>
                : "When a report is prepared, it will appear here."}
            </Empty>
          ) : (
            <ul className="list">
              {d.runs.map((r) => (
                <li key={r.id} className="click" onClick={() => go(`process/${r.id}`)}>
                  <div>
                    <div className="li-t">{r.title}</div>
                    <div className="muted small">{r.client_name} · {r.files} file{r.files === 1 ? "" : "s"} · updated {when(r.updated_at)}</div>
                  </div>
                  <RunStatus state={r.state} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="col">
          <Card title="Needs your attention">
            {d.attention.length === 0 ? <p className="muted">Nothing is waiting for you.</p> : (
              <ul className="list">
                {d.attention.map((r) => (
                  <li key={r.id} className="click" onClick={() => go(`process/${r.id}`)}>
                    <div className="li-t">{r.title}</div><RunStatus state={r.state} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Published reports" actions={<Button kind="ghost" onClick={() => go("reports")}>All past reports</Button>}>
            {d.published.length === 0 ? <p className="muted">No report has been published yet.</p> : (
              <ul className="list">
                {d.published.map((p) => (
                  <li key={p.id} className="click" onClick={() => go("reports")}>
                    <div><div className="li-t">{p.generation}</div><div className="muted small">{p.client_code} · {when(p.published_at)}</div></div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
