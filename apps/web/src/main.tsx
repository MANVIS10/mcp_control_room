import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Connection = { id: string; name: string; source: string; status: string; tool_count: number };
type Approval = { id: string; server_name: string; action_summary: string; risk: string; rationale: string; status: string };
type Audit = { id: string; event_type: string; summary: string; created_at: string };
type Dashboard = { connections: Connection[]; pending_approvals: Approval[]; events: Audit[] };

const api = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function App() {
  const [data, setData] = useState<Dashboard>({ connections: [], pending_approvals: [], events: [] });
  const [streamState, setStreamState] = useState("Connecting");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const response = await fetch(`${api}/api/dashboard`);
    if (!response.ok) throw new Error("Dashboard unavailable");
    setData(await response.json());
  }, []);

  useEffect(() => {
    load().catch(() => setMessage("Start the API to see live data."));
    const source = new EventSource(`${api}/api/events`);
    source.onopen = () => setStreamState("Live");
    source.onerror = () => setStreamState("Reconnecting");
    source.onmessage = () => load().catch(() => undefined);
    ["connection.created", "connection.imported", "approval.requested", "approval.approved", "approval.denied"].forEach((name) =>
      source.addEventListener(name, () => load().catch(() => undefined)),
    );
    return () => source.close();
  }, [load]);

  async function decide(id: string, decision: "approved" | "denied") {
    const response = await fetch(`${api}/api/approvals/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) });
    if (!response.ok) setMessage("That decision could not be saved.");
    else { setMessage(`Action ${decision}.`); await load(); }
  }

  return <main>
    <header><div><p className="eyebrow">LOCAL-FIRST MCP GOVERNANCE</p><h1>Control Room</h1></div><span className={`live ${streamState === "Live" ? "connected" : ""}`}>● {streamState}</span></header>
    {message && <p className="notice" aria-live="polite">{message}</p>}
    <section className="metrics" aria-label="Overview">
      <Metric label="Connected servers" value={data.connections.filter(c => c.status === "active").length} detail="Selected local configurations" />
      <Metric label="Pending approvals" value={data.pending_approvals.length} detail="Nothing runs without you" warn={data.pending_approvals.length > 0} />
      <Metric label="Audit entries" value={data.events.length} detail="Redacted event history" />
    </section>
    <section className="grid">
      <article className="panel approvals"><div className="panel-title"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h2>Approval queue</h2></div><span>{data.pending_approvals.length}</span></div>
        {data.pending_approvals.length === 0 ? <Empty text="No actions are waiting for a decision." /> : data.pending_approvals.map(item => <div className="approval" key={item.id}>
          <div><span className="risk">{item.risk}</span><h3>{item.action_summary}</h3><p>{item.server_name} · {item.rationale}</p></div>
          <div className="actions"><button className="deny" onClick={() => decide(item.id, "denied")}>Deny</button><button className="approve" onClick={() => decide(item.id, "approved")}>Approve</button></div>
        </div>)}
      </article>
      <article className="panel"><p className="eyebrow">PROJECT ADVICE</p><h2>Judge & cost analyst</h2><div className="advice"><strong>Not yet evaluated</strong><p>Connect a selected configuration and project context to receive explainable fit and token-cost recommendations.</p><small>Advisory only — it cannot approve or execute actions.</small></div></article>
    </section>
    <section className="grid lower">
      <article className="panel"><p className="eyebrow">INVENTORY</p><h2>Connections</h2>{data.connections.length === 0 ? <Empty text="No configurations have been imported." /> : data.connections.map(c => <div className="row" key={c.id}><div><strong>{c.name}</strong><p>{c.source} · {c.tool_count} tools</p></div><span className="status">{c.status}</span></div>)}</article>
      <article className="panel"><p className="eyebrow">SANITIZED ACTIVITY</p><h2>Audit trail</h2>{data.events.length === 0 ? <Empty text="Events will appear here after a policy decision." /> : data.events.map(e => <div className="row audit" key={e.id}><div><strong>{e.summary}</strong><p>{new Date(e.created_at).toLocaleString()}</p></div><code>{e.event_type}</code></div>)}</article>
    </section>
  </main>;
}

function Metric({ label, value, detail, warn = false }: { label: string; value: number; detail: string; warn?: boolean }) { return <article className={`metric ${warn ? "warn" : ""}`}><p>{label}</p><strong>{value}</strong><small>{detail}</small></article>; }
function Empty({ text }: { text: string }) { return <p className="empty">{text}</p>; }

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
