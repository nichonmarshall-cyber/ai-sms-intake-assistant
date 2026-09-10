import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import type {
  ConversationDetail,
  ConversationState,
  ConversationSummary,
  Paged,
} from "../../lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  useFocusOnMount,
} from "../../components";

interface ConversationsPayload extends Paged<ConversationSummary> {
  states: ConversationState[];
}

const STATE_LABELS: Record<ConversationState, string> = {
  awaiting_profile_selection: "Selecting service",
  in_progress: "Active",
  completed: "Completed",
  terminated: "Ended",
};

function stateTone(state: ConversationState): "default" | "ok" | "warn" | "demo" {
  if (state === "completed") return "ok";
  if (state === "in_progress") return "demo";
  if (state === "awaiting_profile_selection") return "warn";
  return "default";
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function initials(name: string | null, phone: string): string {
  if (!name) return phone.slice(-2);
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join("")
    .toUpperCase();
}

function displayFieldName(key: string): string {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function displayFieldValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return JSON.stringify(value);
}

export function Conversations({ businessId }: { businessId: string }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<ConversationsPayload | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (search) params.set("q", search);
    if (state) params.set("state", state);
    try {
      const payload = await api.get<ConversationsPayload>(
        `/api/dashboard/businesses/${businessId}/conversations?${params.toString()}`,
      );
      setData(payload);
      setError(null);
      setSelectedId((current) => {
        if (current && payload.items.some((item) => item.id === current)) return current;
        return payload.items[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversations.");
    } finally {
      setLoading(false);
    }
  }, [businessId, page, search, state]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setConversation(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setConversation(null);
    api
      .get<{ conversation: ConversationDetail }>(
        `/api/dashboard/businesses/${businessId}/conversations/${selectedId}`,
      )
      .then((payload) => {
        if (!cancelled) {
          setConversation(payload.conversation);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setDetailLoading(false));
    return () => {
      cancelled = true;
    };
  }, [businessId, selectedId]);

  const applySearch = (event: React.FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearch(searchDraft.trim());
  };

  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const fields = conversation ? Object.entries(conversation.collected_fields) : [];

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Conversations
      </h1>
      <p className="page-subtitle">Review recent SMS intake sessions and the details AI collected.</p>

      <form className="toolbar" onSubmit={applySearch} role="search">
        <input
          className="input"
          aria-label="Search conversations"
          placeholder="Search customer or phone..."
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
        />
        <select
          className="input toolbar__select"
          aria-label="Filter by conversation state"
          value={state}
          onChange={(event) => {
            setPage(1);
            setState(event.target.value);
          }}
        >
          <option value="">All conversations</option>
          {Object.entries(STATE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      {error && <ErrorState body={error} />}
      {loading && <Loading rows={6} label="Loading conversations" />}
      {!loading && data && data.items.length === 0 && (
        <Card>
          <EmptyState
            title="No conversations found"
            body={search || state ? "Try a broader search or another state." : "SMS intake sessions will appear here after a customer starts a conversation."}
          />
        </Card>
      )}
      {!loading && data && data.items.length > 0 && (
        <div className="conversation-workspace">
          <Card
            title={`${data.total} conversation${data.total === 1 ? "" : "s"}`}
            action={<span className="lead-page-count">Page {data.page} of {pageCount}</span>}
          >
            <div className="conversation-list" aria-label="Conversations">
              {data.items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`conversation-list__item${selectedId === item.id ? " conversation-list__item--selected" : ""}`}
                  onClick={() => setSelectedId(item.id)}
                >
                  <span className="conversation-avatar" aria-hidden="true">
                    {initials(item.customer_name, item.phone)}
                  </span>
                  <span className="conversation-list__body">
                    <span className="conversation-list__topline">
                      <strong>{item.customer_name || "Unknown customer"}</strong>
                      <time>{formatDate(item.updated_at)}</time>
                    </span>
                    <span className="conversation-list__phone">{item.phone}</span>
                    <span className="conversation-list__preview">{item.last_message || "No stored messages"}</span>
                  </span>
                  <Badge tone={stateTone(item.state)}>{STATE_LABELS[item.state]}</Badge>
                </button>
              ))}
            </div>
            {pageCount > 1 && (
              <div className="pagination">
                <button className="btn" type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>
                  Previous
                </button>
                <button className="btn" type="button" disabled={page === pageCount} onClick={() => setPage(page + 1)}>
                  Next
                </button>
              </div>
            )}
          </Card>

          <Card title={conversation?.customer_name || "Conversation timeline"}>
            {detailLoading && <Loading rows={6} label="Loading conversation timeline" />}
            {!detailLoading && conversation && (
              <>
                <div className="conversation-header">
                  <div>
                    <a href={`tel:${conversation.phone}`}>{conversation.phone}</a>
                    <p>
                      {conversation.profile_key?.split("_").join(" ") || "No profile"}
                      {" · "}{conversation.turn_count} AI response{conversation.turn_count === 1 ? "" : "s"}
                    </p>
                  </div>
                  <Badge tone={stateTone(conversation.state)}>{STATE_LABELS[conversation.state]}</Badge>
                </div>

                <div className="message-timeline" aria-label="Stored SMS messages">
                  {conversation.messages.length === 0 ? (
                    <EmptyState title="No stored messages" body="This session exists, but its retained history is empty." />
                  ) : (
                    conversation.messages.map((message, index) => (
                      <div key={`${message.role}-${index}`} className={`message-row message-row--${message.role}`}>
                        <div className="message-bubble">
                          <span className="message-sender">
                            {message.role === "user" ? conversation.customer_name || "Customer" : "NTX AI"}
                          </span>
                          <p>{message.content}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
                <p className="timeline-note">
                  Stored transcript only. Individual message timestamps are not captured yet.
                </p>

                {fields.length > 0 && (
                  <section className="collected-fields">
                    <h3>Collected intake details</h3>
                    <dl>
                      {fields.map(([key, value]) => (
                        <div key={key}>
                          <dt>{displayFieldName(key)}</dt>
                          <dd>{displayFieldValue(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                )}
              </>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
