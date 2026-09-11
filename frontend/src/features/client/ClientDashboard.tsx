import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import type {
  AppointmentRequest,
  Business,
  CalendarConnection,
  ConversationSummary,
  Lead,
  LeadWorkflowStatus,
  NavModule,
  Paged,
  UnavailableMetric,
} from "../../lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LockedModule,
  Loading,
  Stat,
  useFocusOnMount,
} from "../../components";
import { Conversations } from "./Conversations";
import { AIIntake } from "./AIIntake";
import { Appointments } from "./Appointments";

interface OverviewPayload {
  metrics: {
    total_leads: number;
    new_leads: number;
    open_conversations: number;
    missed_calls_handled: number;
    pending_approval: number;
  };
  recent_leads: Lead[];
  recent_conversations: ConversationSummary[];
  appointment_requests: AppointmentRequest[];
  calendar: CalendarConnection;
  lead_sources: { source: string; count: number }[];
  lead_activity: { date: string; count: number }[];
  unavailable: UnavailableMetric[];
}

interface LeadsPayload extends Paged<Lead> {
  statuses: LeadWorkflowStatus[];
}

const LEAD_STATUS_LABELS: Record<LeadWorkflowStatus, string> = {
  new: "New",
  qualified: "Qualified",
  needs_review: "Needs review",
  scheduled: "Scheduled",
  closed: "Closed",
};

function leadTone(status: LeadWorkflowStatus): "default" | "ok" | "warn" | "demo" {
  if (status === "qualified" || status === "scheduled") return "ok";
  if (status === "needs_review") return "warn";
  if (status === "new") return "demo";
  return "default";
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

function Leads({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<LeadsPayload | null>(null);
  const [selected, setSelected] = useState<Lead | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [notes, setNotes] = useState("");
  const [workflowStatus, setWorkflowStatus] = useState<LeadWorkflowStatus>("new");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (search) params.set("q", search);
    if (status) params.set("status", status);
    if (showArchived) params.set("include_archived", "true");
    try {
      const payload = await api.get<LeadsPayload>(
        `/api/dashboard/businesses/${businessId}/leads?${params.toString()}`,
      );
      setData(payload);
      setError(null);
      setSelected((current) => {
        if (!current) return payload.items[0] ?? null;
        return payload.items.find((lead) => lead.id === current.id) ?? payload.items[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load leads.");
    } finally {
      setLoading(false);
    }
  }, [businessId, page, search, showArchived, status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (selected) {
      setNotes(selected.client_notes ?? "");
      setWorkflowStatus(selected.workflow_status);
    }
  }, [selected]);

  const applySearch = (event: React.FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearch(searchDraft.trim());
  };

  const saveLead = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setSaving(true);
    try {
      const payload = await api.patch<{ lead: Lead }>(
        `/api/dashboard/businesses/${businessId}/leads/${selected.id}`,
        { workflow_status: workflowStatus, client_notes: notes },
      );
      setSelected(payload.lead);
      setError(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the lead.");
    } finally {
      setSaving(false);
    }
  };

  const toggleArchive = async () => {
    if (!selected) return;
    const willArchive = !selected.archived_at;
    const verb = willArchive ? "Archive" : "Restore";
    if (!window.confirm(`${verb} ${selected.customer_name || selected.phone}?`)) return;
    setSaving(true);
    try {
      await api.patch(`/api/dashboard/businesses/${businessId}/leads/${selected.id}`, {
        archive: willArchive,
      });
      setSelected(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not archive the lead.");
    } finally {
      setSaving(false);
    }
  };

  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Leads
      </h1>
      <p className="page-subtitle">Review every captured opportunity and keep follow-up moving.</p>

      <form className="toolbar" onSubmit={applySearch} role="search">
        <input
          className="input"
          aria-label="Search leads"
          placeholder="Search name, phone, or service..."
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
        />
        <select
          className="input toolbar__select"
          aria-label="Filter by status"
          value={status}
          onChange={(event) => {
            setPage(1);
            setStatus(event.target.value);
          }}
        >
          <option value="">All statuses</option>
          {Object.entries(LEAD_STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button className="btn" type="submit">
          Search
        </button>
        <label className="archive-filter">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => {
              setPage(1);
              setShowArchived(event.target.checked);
            }}
          />
          Show archived
        </label>
      </form>

      {error && <ErrorState body={error} />}
      {loading && <Loading rows={6} label="Loading leads" />}
      {!loading && data && data.items.length === 0 && (
        <Card>
          <EmptyState
            title="No leads found"
            body={search || status ? "Try a broader search or a different status." : "New intake leads will appear here automatically."}
          />
        </Card>
      )}
      {!loading && data && data.items.length > 0 && (
        <div className="lead-workspace">
          <Card
            title={`${data.total} lead${data.total === 1 ? "" : "s"}`}
            action={
              <span className="lead-page-count">
                Page {data.page} of {pageCount}
              </span>
            }
          >
            <div className="table-scroll">
              <table className="table table--stack lead-table">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Service request</th>
                    <th>Received</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((lead) => (
                    <tr key={lead.id} className={selected?.id === lead.id ? "lead-row--selected" : ""}>
                      <td data-label="Customer">
                        <button className="lead-cell-button" type="button" onClick={() => setSelected(lead)}>
                          <strong>{lead.customer_name || "Unknown customer"}</strong>
                          <span>{lead.phone}</span>
                        </button>
                      </td>
                      <td data-label="Service request">{lead.service_request || lead.business_summary || "—"}</td>
                      <td data-label="Received">{formatDate(lead.created_at)}</td>
                      <td data-label="Status">
                        <Badge tone={leadTone(lead.workflow_status)}>
                          {LEAD_STATUS_LABELS[lead.workflow_status]}
                        </Badge>
                        {lead.archived_at && <span className="lead-archived-label">Archived</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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

          {selected && (
            <Card title="Lead details">
              <div className="lead-detail__summary">
                <h3>{selected.customer_name || "Unknown customer"}</h3>
                <a href={`tel:${selected.phone}`}>{selected.phone}</a>
                <p>{selected.business_summary || selected.service_request || "No intake summary available."}</p>
              </div>
              <dl className="lead-detail__facts">
                <div><dt>Received</dt><dd>{formatDate(selected.created_at)}</dd></div>
                <div><dt>Source</dt><dd>{selected.source || "SMS intake"}</dd></div>
                <div><dt>Profile</dt><dd>{selected.profile_key.split("_").join(" ")}</dd></div>
                <div><dt>Intake</dt><dd>{selected.is_complete ? "Complete" : selected.intake_status}</dd></div>
              </dl>
              <form onSubmit={saveLead}>
                <Field label="Follow-up status" id="lead-status">
                  <select
                    id="lead-status"
                    className="input"
                    value={workflowStatus}
                    disabled={readOnly || saving}
                    onChange={(event) => setWorkflowStatus(event.target.value as LeadWorkflowStatus)}
                  >
                    {Object.entries(LEAD_STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Internal notes" id="lead-notes">
                  <textarea
                    id="lead-notes"
                    className="input lead-notes"
                    rows={5}
                    maxLength={4000}
                    value={notes}
                    disabled={readOnly || saving}
                    onChange={(event) => setNotes(event.target.value)}
                  />
                </Field>
                {readOnly && <p className="read-only-note">Your role has read-only access.</p>}
                <div className="lead-detail__actions">
                  <button className="btn btn--primary" type="submit" disabled={readOnly || saving}>
                    {saving ? "Saving..." : "Save lead"}
                  </button>
                  <button className="btn" type="button" disabled={readOnly || saving} onClick={toggleArchive}>
                    {selected.archived_at ? "Restore" : "Archive"}
                  </button>
                </div>
              </form>
            </Card>
          )}
        </div>
      )}
    </>
  );
}

function Overview({ businessId }: { businessId: string }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<OverviewPayload>(`/api/dashboard/businesses/${businessId}/overview`)
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [businessId]);

  const maxActivity = Math.max(1, ...(data?.lead_activity.map((item) => item.count) ?? [1]));

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Overview
      </h1>
      <p className="page-subtitle">Your intake assistant at a glance.</p>

      {loading && <Loading rows={3} />}
      {error && <ErrorState body={error} />}
      {data && (
        <>
          <div className="stat-grid">
            <Stat label="New leads" value={data.metrics.new_leads} icon="◆" />
            <Stat label="Open conversations" value={data.metrics.open_conversations} icon="◉" />
            <Stat label="Pending approval" value={data.metrics.pending_approval} icon="◷" />
            <Stat label="Missed calls handled" value={data.metrics.missed_calls_handled} icon="✆" />
          </div>

          <div className="overview-live-grid">
            <Card title="Recent leads" action={<Link className="table__link" to="leads">View all</Link>}>
              {data.recent_leads.length === 0 ? (
                <EmptyState title="No leads yet" body="Captured leads will appear here." />
              ) : (
                <div className="overview-list">
                  {data.recent_leads.map((lead) => (
                    <Link className="overview-list__item" to="leads" key={lead.id}>
                      <span>
                        <strong>{lead.customer_name || lead.phone}</strong>
                        <small>{lead.service_request || lead.business_summary || "No service summary"}</small>
                      </span>
                      <Badge tone={leadTone(lead.workflow_status)}>{LEAD_STATUS_LABELS[lead.workflow_status]}</Badge>
                    </Link>
                  ))}
                </div>
              )}
            </Card>

            <Card title="Appointment requests" action={<Link className="table__link" to="appointments">View all</Link>}>
              {data.appointment_requests.length === 0 ? (
                <EmptyState title="No pending requests" body="New scheduling preferences will appear here." />
              ) : (
                <div className="overview-appointments">
                  {data.appointment_requests.map((appointment) => (
                    <Link className="overview-appointment" to="appointments" key={appointment.id}>
                      <span className="overview-appointment__date" aria-hidden="true">▣</span>
                      <span><strong>{appointment.customer_name || appointment.customer_phone}</strong><small>{appointment.service_request || "Service appointment"}</small><small>{appointment.requested_time_text || "Time not provided"}</small></span>
                      <span className="btn btn--primary">Review & schedule</span>
                    </Link>
                  ))}
                </div>
              )}
              <div className={data.calendar.connected ? "calendar-banner calendar-banner--ok calendar-banner--compact" : "calendar-banner calendar-banner--warn calendar-banner--compact"}>
                <span>{data.calendar.connected ? "✓" : "!"}</span>
                <strong>{data.calendar.connected ? `${data.calendar.calendar_name} connected` : "Calendar not connected"}</strong>
              </div>
            </Card>
          </div>

          <div className="overview-live-grid overview-live-grid--activity">
            <Card title="Recent conversations" action={<Link className="table__link" to="conversations">View all</Link>}>
              {data.recent_conversations.length === 0 ? (
                <EmptyState title="No conversations yet" body="SMS intake conversations will appear here." />
              ) : (
                <div className="overview-list">
                  {data.recent_conversations.map((conversation) => (
                    <Link className="overview-list__item" to="conversations" key={conversation.id}>
                      <span><strong>{conversation.customer_name || conversation.phone}</strong><small>{conversation.last_message || "No stored message"}</small></span>
                      <Badge tone={conversation.state === "completed" ? "ok" : "demo"}>{conversation.state === "completed" ? "Completed" : "Active"}</Badge>
                    </Link>
                  ))}
                </div>
              )}
            </Card>
            <Card title="Lead activity · last 7 days">
              <div className="activity-chart" role="img" aria-label="New leads per day for the last seven days">
                {data.lead_activity.map((item) => (
                  <div className="activity-chart__day" key={item.date}>
                    <span className="activity-chart__count">{item.count}</span>
                    <div className="activity-chart__track">
                      <span style={{ height: `${Math.max(4, (item.count / maxActivity) * 100)}%` }} />
                    </div>
                    <small>{new Date(`${item.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short" })}</small>
                  </div>
                ))}
              </div>
            </Card>

          </div>
          <Card title="Lead sources">
            {data.lead_sources.length === 0 ? <EmptyState title="No source data" body="Lead attribution will appear as intake records are captured." /> : <div className="source-list">{data.lead_sources.map((item) => <div key={item.source}><span>{item.source.replace(/_/g, " ")}</span><strong>{item.count}</strong></div>)}</div>}
          </Card>
        </>
      )}
    </>
  );
}

function Settings({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [business, setBusiness] = useState<Business | null>(null);
  const [calendar, setCalendar] = useState<CalendarConnection | null>(null);
  const [name, setName] = useState("");
  const [calendarId, setCalendarId] = useState("");
  const [timezone, setTimezone] = useState("America/Chicago");
  const [duration, setDuration] = useState(60);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarStatus, setCalendarStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await api.get<{ business: Business; calendar: CalendarConnection }>(
        `/api/dashboard/businesses/${businessId}/settings`,
      );
      setBusiness(payload.business);
      setName(payload.business.name);
      setCalendar(payload.calendar);
      setCalendarId(payload.calendar.calendar_id);
      setTimezone(payload.calendar.timezone);
      setDuration(payload.calendar.default_duration_minutes);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load settings.");
    } finally {
      setLoading(false);
    }
  }, [businessId]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setStatus(null);
    try {
      await api.patch(`/api/dashboard/businesses/${businessId}/settings`, { name });
      setStatus("Saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    }
  };

  const connectCalendar = async (event: React.FormEvent) => {
    event.preventDefault();
    setCalendarStatus(null);
    setCalendarError(null);
    try {
      const payload = await api.post<{ connection: CalendarConnection }>(
        `/api/dashboard/businesses/${businessId}/calendar/verify`,
        { calendar_id: calendarId, timezone, default_duration_minutes: duration },
      );
      setCalendar(payload.connection);
      setCalendarStatus("Google Calendar connected and verified.");
    } catch (err) {
      setCalendarError(err instanceof Error ? err.message : "Could not verify Google Calendar.");
    }
  };

  const disconnectCalendar = async () => {
    if (!window.confirm("Disconnect Google Calendar from this business?")) return;
    try {
      const payload = await api.post<{ connection: CalendarConnection }>(
        `/api/dashboard/businesses/${businessId}/calendar/disconnect`,
      );
      setCalendar(payload.connection);
      setCalendarId("");
      setCalendarStatus("Calendar disconnected.");
    } catch (err) {
      setCalendarError(err instanceof Error ? err.message : "Could not disconnect the calendar.");
    }
  };

  if (loading) return <Loading rows={4} />;
  if (error && !business) return <ErrorState body={error} />;

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Settings
      </h1>
      <p className="page-subtitle">Business details you can safely change yourself.</p>

      <Card title="Business profile">
        <form onSubmit={save} noValidate>
          <Field label="Business name" id="business-name">
            <input
              id="business-name"
              className="input"
              value={name}
              disabled={readOnly}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          {readOnly && (
            <p style={{ color: "var(--ntx-muted)", fontSize: 12 }}>
              Your role has read-only access. Ask a business owner to make changes.
            </p>
          )}
          {error && (
            <p className="field__error" role="alert">
              {error}
            </p>
          )}
          {status && (
            <p style={{ color: "var(--ntx-green)", fontSize: 12 }} role="status">
              {status}
            </p>
          )}
          <button type="submit" className="btn btn--primary" disabled={readOnly}>
            Save changes
          </button>
        </form>
      </Card>

      <div className="settings-section">
        <Card title="Google Calendar">
          <div className={calendar?.connected ? "calendar-banner calendar-banner--ok" : "calendar-banner calendar-banner--warn"}>
            <span>{calendar?.connected ? "✓" : "!"}</span>
            <strong>{calendar?.connected ? `${calendar.calendar_name} connected` : "Not connected"}</strong>
            <span>{calendar?.connected ? "Approved requests create real Google Calendar events." : "A platform service account is required before this can be verified."}</span>
          </div>
          <form onSubmit={connectCalendar} noValidate>
            <Field label="Calendar ID" id="calendar-id">
              <input id="calendar-id" className="input" value={calendarId} disabled={readOnly} placeholder="your-calendar@group.calendar.google.com" onChange={(event) => setCalendarId(event.target.value)} />
            </Field>
            <div className="calendar-settings-grid">
              <Field label="Timezone" id="calendar-timezone">
                <input id="calendar-timezone" className="input" value={timezone} disabled={readOnly} placeholder="America/Chicago" onChange={(event) => setTimezone(event.target.value)} />
              </Field>
              <Field label="Default appointment length" id="calendar-duration">
                <select id="calendar-duration" className="input" value={duration} disabled={readOnly} onChange={(event) => setDuration(Number(event.target.value))}>
                  {[30, 45, 60, 90, 120].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}
                </select>
              </Field>
            </div>
            {!calendar?.credentials_configured && <p className="data-boundary-note data-boundary-note--inside">NTX must configure the Google service-account credential on the server first.</p>}
            {calendar?.service_account_email && <p className="data-boundary-note data-boundary-note--inside">Share the Google Calendar with <strong>{calendar.service_account_email}</strong> and give it permission to make changes to events.</p>}
            {calendarError && <p className="field__error" role="alert">{calendarError}</p>}
            {calendarStatus && <p className="calendar-success" role="status">{calendarStatus}</p>}
            <div className="lead-detail__actions">
              <button className="btn btn--primary" type="submit" disabled={readOnly || !calendar?.credentials_configured}>Verify & connect</button>
              {calendar?.connected && <button className="btn" type="button" disabled={readOnly} onClick={() => void disconnectCalendar()}>Disconnect</button>}
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}

export function ClientDashboardRoutes({
  modules,
  readOnly,
}: {
  modules: NavModule[];
  readOnly: boolean;
}) {
  const { businessId = "" } = useParams();

  return (
    <Routes>
      <Route index element={<Overview businessId={businessId} />} />
      <Route path="leads" element={<Leads businessId={businessId} readOnly={readOnly} />} />
      <Route path="conversations" element={<Conversations businessId={businessId} />} />
      <Route path="appointments" element={<Appointments businessId={businessId} readOnly={readOnly} />} />
      <Route path="ai_intake" element={<AIIntake businessId={businessId} readOnly={readOnly} />} />
      <Route path="settings" element={<Settings businessId={businessId} readOnly={readOnly} />} />
      {modules
        .filter((module) => !module.implemented)
        .map((module) => (
          <Route
            key={module.key}
            path={module.key}
            element={<LockedModule label={module.label} description={module.description} />}
          />
        ))}
      <Route
        path="*"
        element={
          <EmptyState
            title="Page not found"
            body="That page is not part of your dashboard, or is not enabled for your business."
          />
        }
      />
    </Routes>
  );
}
