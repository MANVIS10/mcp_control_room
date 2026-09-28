import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Connection = { id: string; name: string; source: string; status: string; tool_count: number };
type Approval = { id: string; server_name: string; tool_name: string | null; action_summary: string; arguments_preview: string | null; risk: string; rationale: string; status: string; expires_at: string | null };
type Audit = { id: string; event_type: string; summary: string; created_at: string };
type Dashboard = { connections: Connection[]; pending_approvals: Approval[]; events: Audit[] };

const api = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const liveEvents = ["connection.created", "connection.imported", "tool_call.allowed", "approval.requested", "approval.approved", "approval.denied", "approval.expired"];

function App() {
  const [data, setData] = useState<Dashboard>({ connections: [], pending_approvals: [], events: [] });
  const [streamState, setStreamState] = useState("Connecting");
  const [message, setMessage] = useState("");
  const [clock, setClock] = useState(Date.now());
  const [announcement, setAnnouncement] = useState("");
  const seenApprovalIds = useRef<Set<string> | null>(null);
  const focusApprovalId = useRef<string | null>(null);

  const load = useCallback(async () => {
    const response = await fetch(`${api}/api/dashboard`);
    if (!response.ok) throw new Error("Dashboard unavailable");
    const next: Dashboard = await response.json();
    const currentIds = next.pending_approvals.map((item) => item.id);
    const previouslySeen = seenApprovalIds.current;
    const newIds = previouslySeen ? currentIds.filter((id) => !previouslySeen.has(id)) : [];
    if (newIds.length > 0) {
      // The API lists pending_approvals newest first, so the first new id is the newest.
      const newest = next.pending_approvals.find((item) => item.id === newIds[0])!;
      const text = `New approval request: ${newest.server_name} · ${newest.tool_name ?? newest.action_summary}`;
      setAnnouncement("");
      setTimeout(() => setAnnouncement(text), 50);
      focusApprovalId.current = newest.id;
    }
    seenApprovalIds.current = new Set(currentIds);
    setData(next);
  }, []);

  useEffect(() => {
    load().catch(() => setMessage("Start the API to see live data."));
    const source = new EventSource(`${api}/api/events`);
    source.onopen = () => setStreamState("Live");
    source.onerror = () => setStreamState("Reconnecting");
    liveEvents.forEach((name) => source.addEventListener(name, () => load().catch(() => undefined)));
    return () => source.close();
  }, [load]);

  useEffect(() => {
    // Runs after React has rendered the new card, so its Deny button exists.
    const id = focusApprovalId.current;
    focusApprovalId.current = null;
    if (id && document.activeElement === document.body) {
      document.querySelector<HTMLButtonElement>(`[data-approval-id="${id}"] .deny`)?.focus();
    }
  }, [data]);

  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  async function decide(id: string, decision: "approved" | "denied") {
    const response = await fetch(`${api}/api/approvals/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) });
    if (!response.ok) setMessage("That decision could not be saved. It may have expired.");
    else { setMessage(`Action ${decision}.`); }
    await load();
  }

  function secondsLeft(expiresAt: string | null) {
    return expiresAt ? Math.max(0, Math.round((Date.parse(expiresAt) - clock) / 1000)) : null;
  }

  return <main>
    <header><div><p className="eyebrow">LOCAL-FIRST MCP GOVERNANCE</p><h1>Control Room</h1></div><span className={`live ${streamState === "Live" ? "connected" : ""}`}>● {streamState}</span></header>
    {message && <p className="notice" aria-live="polite">{message}</p>}
    <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
    <section className="metrics" aria-label="Overview">
      <Metric label="Connected servers" value={data.connections.filter(c => c.status === "active").length} detail="Selected local configurations" />
      <Metric label="Pending approvals" value={data.pending_approvals.length} detail="Risky calls wait for a decision" warn={data.pending_approvals.length > 0} />
      <Metric label="Audit entries" value={data.events.length} detail="Redacted event history" />
    </section>
    <section className="grid">
      <article className="panel approvals"><div className="panel-title"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h2>Approval queue</h2></div><span>{data.pending_approvals.length}</span></div>
        {data.pending_approvals.length === 0 ? <Empty text="No actions are waiting for a decision." /> : data.pending_approvals.map(item => <div className="approval" key={item.id} data-approval-id={item.id}>
          <div>
            <span className="risk">{item.risk}</span>
            <h3>{item.server_name} · {item.tool_name ?? item.action_summary}</h3>
            {item.arguments_preview && <code className="args">{item.arguments_preview}</code>}
            <p>{item.rationale}{secondsLeft(item.expires_at) !== null && ` · expires in ${secondsLeft(item.expires_at)}s`}</p>
          </div>
          <div className="actions"><button className="deny" onClick={() => decide(item.id, "denied")}>Deny</button><button className="approve" onClick={() => decide(item.id, "approved")}>Approve</button></div>
        </div>)}
      </article>
      <article className="panel"><p className="eyebrow">POLICY</p><h2>How decisions are made</h2><div className="advice">
        <p>Delete, credential, execute, network and write calls always wait for you. A call runs straight away only when its name reads like a read <em>and</em> the server marks it read-only, or you listed it in <code>MCP_CONTROL_TRUSTED_READ_TOOLS</code>.</p>
        <small>Rules are plain code. Server text can raise risk but never lower it. Unanswered requests expire and are blocked.</small>
      </div></article>
    </section>
    <section className="grid lower">
      <article className="panel"><p className="eyebrow">INVENTORY</p><h2>Connections</h2>{data.connections.length === 0 ? <Empty text="No configurations have been imported." /> : data.connections.map(c => <div className="row" key={c.id}><div><strong>{c.name}</strong><p>{c.source}</p></div><span className="status">{c.status}</span></div>)}</article>
      <article className="panel"><p className="eyebrow">SANITIZED ACTIVITY</p><h2>Audit trail</h2>{data.events.length === 0 ? <Empty text="Events will appear here after a policy decision." /> : data.events.map(e => <div className="row audit" key={e.id}><div><strong>{e.summary}</strong><p>{new Date(e.created_at).toLocaleString()}</p></div><code>{e.event_type}</code></div>)}</article>
    </section>
  </main>;
}

function Metric({ label, value, detail, warn = false }: { label: string; value: number; detail: string; warn?: boolean }) { return <article className={`metric ${warn ? "warn" : ""}`}><p>{label}</p><strong>{value}</strong><small>{detail}</small></article>; }
function Empty({ text }: { text: string }) { return <p className="empty">{text}</p>; }

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
