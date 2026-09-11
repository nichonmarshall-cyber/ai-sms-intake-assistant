import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type {
  ConversationSummary,
  MissedCallEvent,
  UnavailableMetric,
} from "../../lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Stat,
  useFocusOnMount,
} from "../../components";

interface AIIntakePayload {
  metrics: {
    active_sessions: number;
    completed_intakes: number;
    escalations: number;
    missed_calls: number;
  };
  behavior: {
    average_turns: number;
    off_topic_strikes: number;
    opted_out_sessions: number;
  };
  recent_missed_calls: MissedCallEvent[];
  recent_sessions: ConversationSummary[];
  unavailable: UnavailableMetric[];
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function label(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function AIIntake({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<AIIntakePayload | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [working, setWorking] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const suffix = showArchived ? "?include_archived=true" : "";
      setData(
        await api.get<AIIntakePayload>(
          `/api/dashboard/businesses/${businessId}/ai-intake${suffix}`,
        ),
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load AI intake activity.");
    } finally {
      setLoading(false);
    }
  }, [businessId, showArchived]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleArchive = async (event: MissedCallEvent) => {
    const archive = !event.archived_at;
    if (!window.confirm(`${archive ? "Archive" : "Restore"} missed call from ${event.caller_phone}?`)) {
      return;
    }
    setWorking(event.id);
    try {
      await api.patch(
        `/api/dashboard/businesses/${businessId}/missed-calls/${event.id}`,
        { archive },
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the missed call.");
    } finally {
      setWorking(null);
    }
  };

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        AI Intake
      </h1>
      <p className="page-subtitle">Monitor intake outcomes, AI behavior, and missed-call follow-up.</p>

      {error && <ErrorState body={error} />}
      {loading && <Loading rows={6} label="Loading AI intake activity" />}
      {data && !loading && (
        <>
          <div className="stat-grid">
            <Stat label="Active sessions" value={data.metrics.active_sessions} icon="◍" />
            <Stat label="Completed intakes" value={data.metrics.completed_intakes} icon="✓" />
            <Stat label="Escalations" value={data.metrics.escalations} icon="!" />
            <Stat label="Missed calls" value={data.metrics.missed_calls} icon="✆" />
          </div>

          <div className="intake-overview-grid">
            <Card title="AI behavior">
              <dl className="behavior-list">
                <div><dt>Average AI responses</dt><dd>{data.behavior.average_turns}</dd></div>
                <div><dt>Off-topic strikes</dt><dd>{data.behavior.off_topic_strikes}</dd></div>
                <div><dt>Opted-out sessions</dt><dd>{data.behavior.opted_out_sessions}</dd></div>
                <div>
                  <dt>Fallback rate</dt>
                  <dd className="behavior-list__unavailable">Not measurable yet</dd>
                </div>
              </dl>
            </Card>

            <Card title="Recent sessions" action={<Link className="table__link" to="../conversations">View all</Link>}>
              {data.recent_sessions.length === 0 ? (
                <EmptyState title="No sessions yet" body="Recent customer intake sessions will appear here." />
              ) : (
                <div className="compact-activity-list">
                  {data.recent_sessions.map((session) => (
                    <Link key={session.id} to="../conversations" className="compact-activity-list__item">
                      <span>
                        <strong>{session.customer_name || session.phone}</strong>
                        <small>{session.last_message || "No stored messages"}</small>
                      </span>
                      <Badge tone={session.state === "completed" ? "ok" : "demo"}>
                        {session.state === "completed" ? "Completed" : "Active"}
                      </Badge>
                    </Link>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <div className="intake-section">
            <Card
              title="Missed-call activity"
              action={
                <label className="archive-filter">
                  <input
                    type="checkbox"
                    checked={showArchived}
                    onChange={(event) => setShowArchived(event.target.checked)}
                  />
                  Show archived
                </label>
              }
            >
              {data.recent_missed_calls.length === 0 ? (
                <EmptyState
                  title="No missed calls found"
                  body={showArchived ? "No missed-call events have been recorded." : "Handled missed calls will appear here automatically."}
                />
              ) : (
                <div className="table-scroll">
                  <table className="table table--stack">
                    <thead>
                      <tr>
                        <th>Caller</th>
                        <th>Received</th>
                        <th>Result</th>
                        <th>SMS</th>
                        <th>Retention</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_missed_calls.map((event) => (
                        <tr key={event.id}>
                          <td data-label="Caller"><a className="table__link" href={`tel:${event.caller_phone}`}>{event.caller_phone}</a></td>
                          <td data-label="Received">{formatDate(event.created_at)}</td>
                          <td data-label="Result"><Badge tone={event.decision === "message_sent" ? "ok" : "warn"}>{label(event.decision)}</Badge></td>
                          <td data-label="SMS">{label(event.delivery_status || (event.message_sid ? "queued" : "not_sent"))}</td>
                          <td data-label="Retention">
                            <button
                              className="btn"
                              type="button"
                              disabled={readOnly || working === event.id}
                              onClick={() => toggleArchive(event)}
                            >
                              {event.archived_at ? "Restore" : "Archive"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {readOnly && <p className="read-only-note">Your role has read-only access.</p>}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
