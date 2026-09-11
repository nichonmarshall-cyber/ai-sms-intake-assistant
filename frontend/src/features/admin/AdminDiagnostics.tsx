import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type { ConversationSummary, MissedCallEvent, Paged } from "../../lib/types";
import { Badge, Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";

interface PlatformConversation extends ConversationSummary {
  business: { id: string; name: string; slug: string };
}

interface ConversationsPayload extends Paged<PlatformConversation> {
  states: string[];
}

interface DeliveryItem extends MissedCallEvent {
  business: { id: string; name: string };
  delivery_status: "queued" | "not_sent";
}

interface DeliveryPayload {
  metrics: { attempted: number; queued: number; not_sent: number };
  items: DeliveryItem[];
  notice: string;
}

interface WebhookItem {
  id: string;
  kind: string;
  business_id: string | null;
  business_name: string;
  external_id: string;
  phone: string;
  outcome: string;
  created_at: string | null;
}

interface WebhooksPayload {
  metrics: { inbound_sms: number; voice_events: number; total_recent: number };
  items: WebhookItem[];
  notice: string;
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function useLiveData<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load platform activity.");
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => { void load(); }, [load]);
  return { data, error, loading, load };
}

export function PlatformConversations() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const params = new URLSearchParams({ page_size: "100" });
  if (query) params.set("q", query);
  if (state) params.set("state", state);
  const { data, error, loading, load } = useLiveData<ConversationsPayload>(
    `/api/admin/conversations?${params.toString()}`,
  );

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>Conversations</h1>
      <p className="page-subtitle">Live SMS intake sessions across every tenant.</p>
      <form className="toolbar" onSubmit={(event) => { event.preventDefault(); setQuery(queryDraft.trim()); }}>
        <input className="input" type="search" aria-label="Search conversations" placeholder="Search business, customer, or phone…" value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} />
        <select className="input toolbar__select" aria-label="Conversation state" value={state} onChange={(event) => setState(event.target.value)}>
          <option value="">All states</option>
          {data?.states.map((value) => <option value={value} key={value}>{humanize(value)}</option>)}
        </select>
        <button className="btn" type="submit">Search</button>
        <button className="btn" type="button" onClick={() => void load()}>Refresh</button>
      </form>
      <Card title={data ? `${data.total} conversations` : "Conversations"}>
        {loading && <Loading rows={6} />}
        {error && <ErrorState body={error} />}
        {data?.items.length === 0 && <EmptyState title="No conversations found" body="Try a different search or wait for an intake session." />}
        {data && data.items.length > 0 && (
          <div className="table-scroll"><table className="table table--stack"><thead><tr><th>Business</th><th>Customer</th><th>Profile</th><th>Responses</th><th>Updated</th><th>Status</th></tr></thead><tbody>
            {data.items.map((item) => <tr key={item.id}>
              <td data-label="Business"><Link className="table__link" to={`/b/${item.business.id}/conversations`}>{item.business.name}</Link></td>
              <td data-label="Customer"><strong>{item.customer_name || item.phone}</strong><br /><small>{item.phone}</small></td>
              <td data-label="Profile">{humanize(item.profile_key || "unselected")}</td>
              <td data-label="Responses">{item.turn_count}</td>
              <td data-label="Updated">{formatDate(item.updated_at)}</td>
              <td data-label="Status"><Badge tone={item.state === "completed" ? "ok" : item.state === "terminated" ? "warn" : "demo"}>{humanize(item.state)}</Badge></td>
            </tr>)}
          </tbody></table></div>
        )}
      </Card>
    </>
  );
}

export function DeliveryDiagnostics() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading, load } = useLiveData<DeliveryPayload>("/api/admin/delivery");
  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>Delivery</h1>
      <p className="page-subtitle">Persisted missed-call follow-up attempts across all tenants.</p>
      {loading && <Loading rows={5} />}{error && <ErrorState body={error} />}
      {data && <>
        <div className="stat-grid"><Stat label="Attempted" value={data.metrics.attempted} icon="➤" /><Stat label="Queued by Twilio" value={data.metrics.queued} icon="✓" /><Stat label="Not sent" value={data.metrics.not_sent} icon="!" /></div>
        <Card title="Delivery activity" action={<button className="btn" type="button" onClick={() => void load()}>Refresh</button>}>
          <p className="data-boundary-note data-boundary-note--inside">{data.notice}</p>
          {data.items.length === 0 ? <EmptyState title="No delivery attempts" body="Missed-call follow-up activity will appear here." /> : <div className="table-scroll"><table className="table table--stack"><thead><tr><th>Business</th><th>Caller</th><th>Decision</th><th>Queue status</th><th>Message SID</th><th>When</th></tr></thead><tbody>
            {data.items.map((item) => <tr key={item.id}><td data-label="Business">{item.business.name}</td><td data-label="Caller">{item.caller_phone}</td><td data-label="Decision">{humanize(item.decision)}</td><td data-label="Queue status"><Badge tone={item.delivery_status === "queued" ? "ok" : "warn"}>{humanize(item.delivery_status)}</Badge></td><td data-label="Message SID"><code>{item.message_sid || "—"}</code></td><td data-label="When">{formatDate(item.created_at)}</td></tr>)}
          </tbody></table></div>}
        </Card>
      </>}
    </>
  );
}

export function WebhookDiagnostics() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading, load } = useLiveData<WebhooksPayload>("/api/admin/webhooks");
  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>Webhooks</h1>
      <p className="page-subtitle">Recent persisted SMS and voice webhook events.</p>
      {loading && <Loading rows={5} />}{error && <ErrorState body={error} />}
      {data && <>
        <div className="stat-grid"><Stat label="Inbound SMS" value={data.metrics.inbound_sms} icon="◍" /><Stat label="Voice events" value={data.metrics.voice_events} icon="✆" /><Stat label="Recent events" value={data.metrics.total_recent} icon="◈" /></div>
        <Card title="Webhook ledger" action={<button className="btn" type="button" onClick={() => void load()}>Refresh</button>}>
          <p className="data-boundary-note data-boundary-note--inside">{data.notice}</p>
          {data.items.length === 0 ? <EmptyState title="No webhook events" body="Processed inbound events will appear here." /> : <div className="table-scroll"><table className="table table--stack"><thead><tr><th>Type</th><th>Business</th><th>Phone</th><th>Outcome</th><th>External ID</th><th>When</th></tr></thead><tbody>
            {data.items.map((item) => <tr key={item.id}><td data-label="Type">{item.kind}</td><td data-label="Business">{item.business_name}</td><td data-label="Phone">{item.phone}</td><td data-label="Outcome"><Badge tone={item.outcome === "processed" || item.outcome === "message_sent" ? "ok" : "warn"}>{humanize(item.outcome)}</Badge></td><td data-label="External ID"><code>{item.external_id}</code></td><td data-label="When">{formatDate(item.created_at)}</td></tr>)}
          </tbody></table></div>}
        </Card>
      </>}
    </>
  );
}
