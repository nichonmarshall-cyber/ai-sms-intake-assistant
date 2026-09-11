import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import type {
  AppointmentRequest,
  AppointmentStatus,
  CalendarConnection,
} from "../../lib/types";
import { Badge, Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";

interface AppointmentPayload {
  items: AppointmentRequest[];
  connection: CalendarConnection;
  statuses: AppointmentStatus[];
}

function tone(status: AppointmentStatus): "default" | "ok" | "warn" | "demo" {
  if (status === "scheduled") return "ok";
  if (status === "sync_failed") return "warn";
  if (status === "pending") return "demo";
  return "default";
}

function label(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string | null): string {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function Appointments({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<AppointmentPayload | null>(null);
  const [status, setStatus] = useState("");
  const [starts, setStarts] = useState<Record<number, string>>({});
  const [durations, setDurations] = useState<Record<number, number>>({});
  const [working, setWorking] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
      const payload = await api.get<AppointmentPayload>(
        `/api/dashboard/businesses/${businessId}/appointments${suffix}`,
      );
      setData(payload);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load appointments.");
    } finally {
      setLoading(false);
    }
  }, [businessId, status]);

  useEffect(() => { void load(); }, [load]);

  const update = async (appointment: AppointmentRequest, action: "schedule" | "decline") => {
    if (action === "decline" && !window.confirm(`Decline ${appointment.customer_name || appointment.customer_phone}'s request?`)) return;
    setWorking(appointment.id);
    setError(null);
    try {
      await api.patch(`/api/dashboard/businesses/${businessId}/appointments/${appointment.id}`, {
        action,
        scheduled_start: starts[appointment.id],
        duration_minutes: durations[appointment.id] || data?.connection.default_duration_minutes || 60,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The appointment could not be updated.");
    } finally {
      setWorking(null);
    }
  };

  const pending = data?.items.filter((item) => item.status === "pending" || item.status === "sync_failed").length ?? 0;
  const scheduled = data?.items.filter((item) => item.status === "scheduled").length ?? 0;

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>Appointments</h1>
      <p className="page-subtitle">Review customer preferences and schedule confirmed times.</p>

      {loading && <Loading rows={4} />}
      {error && <ErrorState body={error} />}
      {data && <>
        <div className="stat-grid appointment-stat-grid">
          <Stat label="Pending approval" value={pending} icon="◷" />
          <Stat label="Scheduled" value={scheduled} icon="✓" />
          <Stat label="Calendar" value={data.connection.connected ? "Connected" : "Not connected"} icon="▣" />
        </div>

        <div className={data.connection.connected ? "calendar-banner calendar-banner--ok" : "calendar-banner calendar-banner--warn"}>
          <span aria-hidden="true">{data.connection.connected ? "✓" : "!"}</span>
          <strong>{data.connection.connected ? `${data.connection.calendar_name} connected` : "Google Calendar is not connected"}</strong>
          <span>{data.connection.connected ? `Verified ${formatDate(data.connection.verified_at)}` : "Connect it in Settings before approving requests."}</span>
        </div>

        <div className="toolbar appointment-toolbar">
          <select className="input toolbar__select" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter appointments">
            <option value="">All appointments</option>
            {data.statuses.map((item) => <option value={item} key={item}>{label(item)}</option>)}
          </select>
          <button className="btn" type="button" onClick={() => void load()}>Refresh</button>
        </div>

        <Card title={`${data.items.length} appointment request${data.items.length === 1 ? "" : "s"}`}>
          {data.items.length === 0 ? <EmptyState title="No appointment requests" body="Requests appear when intake captures a preferred date or time." /> : (
            <div className="appointment-list">
              {data.items.map((appointment) => (
                <article className="appointment-row" key={appointment.id}>
                  <div className="appointment-row__date" aria-hidden="true">
                    <strong>{appointment.scheduled_start_at ? new Date(appointment.scheduled_start_at).toLocaleDateString(undefined, { month: "short" }).toUpperCase() : "REQ"}</strong>
                    <span>{appointment.scheduled_start_at ? new Date(appointment.scheduled_start_at).getDate() : appointment.id}</span>
                  </div>
                  <div className="appointment-row__details">
                    <div className="appointment-row__heading">
                      <div><strong>{appointment.customer_name || "Unknown customer"}</strong><a href={`tel:${appointment.customer_phone}`}>{appointment.customer_phone}</a></div>
                      <Badge tone={tone(appointment.status)}>{label(appointment.status)}</Badge>
                    </div>
                    <p>{appointment.service_request || "Service appointment"}</p>
                    <small>Requested: {appointment.requested_time_text || "No preference provided"}</small>
                    {appointment.scheduled_start_at && <small>Scheduled: {formatDate(appointment.scheduled_start_at)} · {appointment.duration_minutes} minutes</small>}
                    {appointment.provider_error && <p className="appointment-row__error">{appointment.provider_error}</p>}
                  </div>
                  {(appointment.status === "pending" || appointment.status === "sync_failed") && (
                    <div className="appointment-row__actions">
                      <label>Confirmed start<input className="input" type="datetime-local" value={starts[appointment.id] || ""} disabled={readOnly} onChange={(event) => setStarts({ ...starts, [appointment.id]: event.target.value })} /></label>
                      <label>Minutes<input className="input" type="number" min="15" max="480" step="15" value={durations[appointment.id] || data.connection.default_duration_minutes} disabled={readOnly} onChange={(event) => setDurations({ ...durations, [appointment.id]: Number(event.target.value) })} /></label>
                      <button className="btn btn--primary" type="button" disabled={readOnly || working === appointment.id || !data.connection.connected || !starts[appointment.id]} onClick={() => void update(appointment, "schedule")}>{working === appointment.id ? "Scheduling…" : "Approve & schedule"}</button>
                      <button className="btn" type="button" disabled={readOnly || working === appointment.id} onClick={() => void update(appointment, "decline")}>Decline</button>
                    </div>
                  )}
                  {appointment.calendar_event_link && <a className="table__link appointment-row__calendar-link" href={appointment.calendar_event_link} target="_blank" rel="noreferrer">Open in Google Calendar ↗</a>}
                </article>
              ))}
            </div>
          )}
        </Card>
      </>}
    </>
  );
}
