import { useCallback, useEffect, useRef, useState } from "react";
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
import { Analytics } from "./Analytics";
import { Website } from "./Website";
import { LocalSEO, Reviews } from "./GoogleVisibility";

interface OverviewPayload {
  enabled_modules: NavModule[];
  dashboard_layout: DashboardLayout;
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
  website: {
    website_url: string;
    provider: { name: string; status: string };
    monitor: {
      id: string;
      name: string;
      url: string;
      status: string;
      uptime_7d?: string | null;
      uptime_30d?: string | null;
      uptime_90d?: string | null;
      average_response_ms?: number | null;
    } | null;
  } | null;
  unavailable: UnavailableMetric[];
}

type OverviewWidgetKey = "stats" | "recent_leads" | "appointments" | "recent_conversations" | "services";
type MainOverviewWidgetKey = Exclude<OverviewWidgetKey, "services">;
type OverviewWidgetSize = "standard" | "wide";

interface OverviewLayout {
  order: MainOverviewWidgetKey[];
  visible: Record<OverviewWidgetKey, boolean>;
  services_position: "left" | "right";
  sizes: Record<MainOverviewWidgetKey, OverviewWidgetSize>;
  available_widgets: OverviewWidgetKey[];
}

interface DashboardLayout {
  overview: OverviewLayout;
}

const MAIN_OVERVIEW_WIDGETS: { key: MainOverviewWidgetKey; label: string; description: string }[] = [
  { key: "stats", label: "Key metrics", description: "New leads, conversations, requests, and missed calls." },
  { key: "recent_leads", label: "Recent leads", description: "Newest captured opportunities." },
  { key: "appointments", label: "Appointment requests", description: "Scheduling requests waiting for review." },
  { key: "recent_conversations", label: "Recent conversations", description: "Latest active SMS intake conversations." },
];

function defaultOverviewLayout(): OverviewLayout {
  return {
    order: MAIN_OVERVIEW_WIDGETS.map((widget) => widget.key),
    visible: { stats: true, recent_leads: true, appointments: true, recent_conversations: true, services: true },
    services_position: "right",
    sizes: { stats: "wide", recent_leads: "standard", appointments: "standard", recent_conversations: "wide" },
    available_widgets: ["stats", "recent_leads", "appointments", "recent_conversations", "services"],
  };
}

function cloneOverviewLayout(layout: OverviewLayout): OverviewLayout {
  return {
    ...layout,
    order: [...layout.order],
    visible: { ...layout.visible },
    sizes: { ...layout.sizes },
    available_widgets: [...layout.available_widgets],
  };
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

function moduleSummary(module: NavModule, data: OverviewPayload) {
  const monitor = data.website?.monitor;
  switch (module.key) {
    case "website":
      if (!monitor) return { value: "Connecting", detail: "Website monitoring setup is in progress.", tone: "warn" as const };
      return {
        value: monitor.status === "up" ? "Online" : "Needs attention",
        detail: monitor.uptime_30d ? `${monitor.uptime_30d}% uptime over 30 days` : "Uptime data is being collected.",
        tone: monitor.status === "up" ? "ok" as const : "warn" as const,
      };
    case "local_seo":
      return { value: "Coming soon", detail: "Google search visibility and rankings will appear here.", tone: "default" as const };
    case "reviews":
      return { value: "Coming soon", detail: "Google rating and review activity will appear here.", tone: "default" as const };
    case "analytics":
      return { value: "Reporting ready", detail: `${data.metrics.total_leads} lead${data.metrics.total_leads === 1 ? "" : "s"} tracked`, tone: "ok" as const };
    case "leads":
      return { value: `${data.metrics.new_leads} new`, detail: `${data.metrics.total_leads} total leads captured`, tone: "demo" as const };
    case "conversations":
      return { value: `${data.metrics.open_conversations} open`, detail: "SMS conversations awaiting completion", tone: "demo" as const };
    case "appointments":
      return { value: `${data.metrics.pending_approval} pending`, detail: "Appointment requests ready for review", tone: "demo" as const };
    case "ai_intake":
      return { value: `${data.metrics.missed_calls_handled} calls handled`, detail: `${data.metrics.total_leads} leads captured by intake`, tone: "ok" as const };
    case "settings":
      return { value: "Profile active", detail: "Business preferences and integrations", tone: "ok" as const };
    default:
      return module.implemented
        ? { value: "Enabled", detail: module.description, tone: "ok" as const }
        : { value: "Coming soon", detail: module.description, tone: "default" as const };
  }
}

function OverviewModuleCard({ module, data }: { module: NavModule; data: OverviewPayload }) {
  const summary = moduleSummary(module, data);
  return (
    <section className="overview-module-card">
      <div className="overview-module-card__topline">
        <span className="overview-module-card__icon" aria-hidden="true">{module.icon === "star" ? "★" : module.icon === "globe" ? "◇" : module.icon === "search" ? "◎" : module.icon === "bar-chart" ? "▤" : module.icon === "settings" ? "⚙" : "◆"}</span>
        <span className="overview-module-card__label">{module.label}</span>
        <Badge tone={summary.tone}>{summary.value}</Badge>
      </div>
      <p>{summary.detail}</p>
      {module.implemented ? <Link className="table__link" to={module.key}>Open {module.label.toLowerCase()}</Link> : <span className="overview-module-card__soon">Enabled for this business</span>}
    </section>
  );
}

function Overview({ businessId, modules, readOnly }: { businessId: string; modules: NavModule[]; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editingLayout, setEditingLayout] = useState(false);
  const [draftLayout, setDraftLayout] = useState<OverviewLayout | null>(null);
  const [savingLayout, setSavingLayout] = useState(false);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [layoutStatus, setLayoutStatus] = useState<string | null>(null);
  const [draggingWidget, setDraggingWidget] = useState<MainOverviewWidgetKey | null>(null);
  const [dropTarget, setDropTarget] = useState<MainOverviewWidgetKey | null>(null);
  const [resizingWidget, setResizingWidget] = useState<MainOverviewWidgetKey | null>(null);
  const resizeStart = useRef<{
    widget: MainOverviewWidgetKey;
    startX: number;
    startSize: OverviewWidgetSize;
    threshold: number;
  } | null>(null);

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

  const enabledModules = data?.enabled_modules ?? modules;
  const enabledKeys = new Set(enabledModules.map((module) => module.key));
  const summaryModules = enabledModules.filter((module) => module.key !== "overview").slice(0, 6);
  const savedLayout = data?.dashboard_layout.overview ?? defaultOverviewLayout();
  const layout = editingLayout && draftLayout ? draftLayout : savedLayout;
  const availableWidgets = new Set(layout.available_widgets);
  const widgetVisible = (key: OverviewWidgetKey) => availableWidgets.has(key) && layout.visible[key];
  const mainWidgets = layout.order.filter((key) => widgetVisible(key));

  const beginLayoutEdit = () => {
    setDraftLayout(cloneOverviewLayout(savedLayout));
    setLayoutError(null);
    setLayoutStatus(null);
    setEditingLayout(true);
  };

  const cancelLayoutEdit = () => {
    setEditingLayout(false);
    setDraftLayout(null);
    setDraggingWidget(null);
    setDropTarget(null);
    setResizingWidget(null);
    resizeStart.current = null;
    setLayoutError(null);
  };

  const moveDraftWidget = (source: MainOverviewWidgetKey, target: MainOverviewWidgetKey) => {
    if (source === target) return;
    setDraftLayout((current) => {
      if (!current) return current;
      const sourceIndex = current.order.indexOf(source);
      const targetIndex = current.order.indexOf(target);
      if (sourceIndex < 0 || targetIndex < 0) return current;
      const nextOrder = [...current.order];
      nextOrder.splice(sourceIndex, 1);
      nextOrder.splice(targetIndex, 0, source);
      return { ...current, order: nextOrder };
    });
  };

  const moveServicesRail = () => {
    setDraftLayout((current) => current ? {
      ...current,
      services_position: current.services_position === "left" ? "right" : "left",
    } : current);
  };

  const resizeDraftWidget = (widget: MainOverviewWidgetKey, size: OverviewWidgetSize) => {
    setDraftLayout((current) => current ? {
      ...current,
      sizes: { ...current.sizes, [widget]: size },
    } : current);
  };

  const beginResize = (event: React.PointerEvent<HTMLButtonElement>, widget: MainOverviewWidgetKey) => {
    if (savingLayout) return;
    const gridWidth = event.currentTarget.closest(".overview-widget-grid")?.getBoundingClientRect().width ?? 600;
    resizeStart.current = {
      widget,
      startX: event.clientX,
      startSize: layout.sizes[widget],
      threshold: Math.max(72, gridWidth * 0.12),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setResizingWidget(widget);
  };

  const updateResize = (event: React.PointerEvent<HTMLButtonElement>, widget: MainOverviewWidgetKey) => {
    const start = resizeStart.current;
    if (!start || start.widget !== widget) return;
    const deltaX = event.clientX - start.startX;
    const nextSize: OverviewWidgetSize = deltaX >= start.threshold
      ? "wide"
      : deltaX <= -start.threshold
        ? "standard"
        : start.startSize;
    resizeDraftWidget(widget, nextSize);
  };

  const finishResize = () => {
    resizeStart.current = null;
    setResizingWidget(null);
  };

  const saveLayout = async () => {
    if (!draftLayout) return;
    setLayoutError(null);
    setLayoutStatus(null);
    setSavingLayout(true);
    try {
      const payload = await api.patch<{ dashboard_layout: DashboardLayout }>(
        `/api/dashboard/businesses/${businessId}/settings`,
        { dashboard_layout: { overview: draftLayout } },
      );
      setData((current) => current ? { ...current, dashboard_layout: payload.dashboard_layout } : current);
      setEditingLayout(false);
      setDraftLayout(null);
      setLayoutStatus("Overview layout saved for everyone at this business.");
    } catch (err) {
      setLayoutError(err instanceof Error ? err.message : "Could not save the Overview layout.");
    } finally {
      setSavingLayout(false);
    }
  };

  const renderMainWidget = (widget: MainOverviewWidgetKey) => {
    if (!data) return null;
    switch (widget) {
      case "stats":
        return (
          <div className="stat-grid overview-stat-grid">
            {enabledKeys.has("leads") && <Stat label="New leads" value={data.metrics.new_leads} icon="♙" />}
            {enabledKeys.has("conversations") && <Stat label="Open conversations" value={data.metrics.open_conversations} icon="◌" />}
            {enabledKeys.has("appointments") && <Stat label="Pending approval" value={data.metrics.pending_approval} icon="◷" />}
            {enabledKeys.has("ai_intake") && <Stat label="Missed calls handled" value={data.metrics.missed_calls_handled} icon="↗" />}
          </div>
        );
      case "recent_leads":
        return (
          <Card title="Recent leads" action={<Link className="table__link" to="leads">View all</Link>}>
            {data.recent_leads.length === 0 ? (
              <EmptyState title="No leads yet" body="Captured leads will appear here." />
            ) : (
              <div className="table-scroll">
                <table className="table overview-leads-table">
                  <thead><tr><th>Customer</th><th>Service request</th><th>Source</th><th>Received</th><th>Status</th></tr></thead>
                  <tbody>{data.recent_leads.slice(0, 4).map((lead) => (
                    <tr key={lead.id}>
                      <td><Link className="table__link" to="leads">{lead.customer_name || lead.phone}</Link></td>
                      <td>{lead.service_request || lead.business_summary || "No service summary"}</td>
                      <td><span className="lead-source"><span aria-hidden="true">●</span>{(lead.source || "SMS").replace(/_/g, " ")}</span></td>
                      <td>{formatDate(lead.created_at)}</td>
                      <td><Badge tone={leadTone(lead.workflow_status)}>{LEAD_STATUS_LABELS[lead.workflow_status]}</Badge></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </Card>
        );
      case "appointments":
        return (
          <Card title="Appointment requests" action={<Link className="table__link" to="appointments">View all</Link>}>
            {data.appointment_requests.length === 0 ? (
              <EmptyState title="No pending requests" body="New scheduling preferences will appear here." />
            ) : (
              <div className="overview-appointments">
                {data.appointment_requests.map((appointment) => (
                  <Link className="overview-appointment" to="appointments" key={appointment.id}>
                    <span className="overview-appointment__date" aria-hidden="true">
                      <small>{new Date(appointment.scheduled_start_at || appointment.created_at || Date.now()).toLocaleDateString(undefined, { month: "short" })}</small>
                      <strong>{new Date(appointment.scheduled_start_at || appointment.created_at || Date.now()).getDate()}</strong>
                      <small>{new Date(appointment.scheduled_start_at || appointment.created_at || Date.now()).toLocaleDateString(undefined, { weekday: "short" })}</small>
                    </span>
                    <span><strong>{appointment.customer_name || appointment.customer_phone}</strong><small>{appointment.service_request || "Service appointment"}</small><small>{appointment.requested_time_text || "Time not provided"}</small></span>
                    <span className="btn btn--primary overview-appointment__action">Review &amp; schedule</span>
                  </Link>
                ))}
              </div>
            )}
            <div className={data.calendar.connected ? "calendar-banner calendar-banner--ok calendar-banner--compact" : "calendar-banner calendar-banner--warn calendar-banner--compact"}>
              <span>{data.calendar.connected ? "✓" : "!"}</span>
              <strong>{data.calendar.connected ? `${data.calendar.calendar_name} connected` : "Calendar not connected"}</strong>
            </div>
          </Card>
        );
      case "recent_conversations":
        return (
          <Card title="Recent conversations" action={<Link className="table__link" to="conversations">View all</Link>}>
            {data.recent_conversations.length === 0 ? (
              <EmptyState title="No conversations yet" body="SMS intake conversations will appear here." />
            ) : (
              <div className="overview-list">
                {data.recent_conversations.slice(0, 3).map((conversation) => (
                  <Link className="overview-list__item" to="conversations" key={conversation.id}>
                    <span className="conversation-avatar" aria-hidden="true">{(conversation.customer_name || conversation.phone).slice(0, 2).toUpperCase()}</span>
                    <span className="overview-list__copy"><strong>{conversation.customer_name || conversation.phone}</strong><small>{conversation.last_message || "No stored message"}</small></span>
                    <span className="conversation-time">{formatDate(conversation.updated_at)}</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        );
    }
  };

  const servicesOnLeft = layout.services_position === "left";
  const services = data && widgetVisible("services") && summaryModules.length > 0 ? (
    <aside className="overview-services overview-dashboard__services" aria-labelledby="your-services">
      <div className="overview-section-heading">
        <div><h2 id="your-services">Your services</h2><p>Only the modules enabled for this business appear here.</p></div>
        {editingLayout && (
          <button className="btn btn--small" type="button" onClick={moveServicesRail} disabled={savingLayout}>
            Move {servicesOnLeft ? "right" : "left"}
          </button>
        )}
      </div>
      <div className="overview-module-grid overview-module-grid--rail">
        {summaryModules.map((module) => <OverviewModuleCard key={module.key} module={module} data={data} />)}
      </div>
    </aside>
  ) : null;

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Overview
      </h1>
      <p className="page-subtitle">Your intake assistant at a glance.</p>

      {loading && <Loading rows={3} />}
      {error && <ErrorState body={error} />}
      {data && (
        <div className={`overview-dashboard${services ? "" : " overview-dashboard--no-services"}${servicesOnLeft ? " overview-dashboard--services-left" : ""}`}>
          {servicesOnLeft && services}
          <main className="overview-dashboard__main">
            <section className="overview-live-feed" aria-labelledby="live-business-feed">
              <div className="overview-section-heading">
                <div>
                  <h2 id="live-business-feed">Live business feed</h2>
                  <p>{editingLayout ? "Drag cards by the dotted handle. Drag a card’s lower-right corner to snap it between half and full width, then save." : "Recent leads, conversations, and appointment requests."}</p>
                </div>
                {!readOnly && (
                  <div className="overview-layout-actions">
                    {editingLayout ? (
                      <>
                        <button className="btn" type="button" onClick={cancelLayoutEdit} disabled={savingLayout}>Cancel</button>
                        <button className="btn btn--primary" type="button" onClick={() => void saveLayout()} disabled={savingLayout}>
                          {savingLayout ? "Saving..." : "Save layout"}
                        </button>
                      </>
                    ) : (
                      <button className="btn" type="button" onClick={beginLayoutEdit}>Customize layout</button>
                    )}
                  </div>
                )}
              </div>
              {layoutError && <p className="field__error overview-layout-feedback" role="alert">{layoutError}</p>}
              {layoutStatus && <p className="calendar-success overview-layout-feedback" role="status">{layoutStatus}</p>}
              {mainWidgets.length > 0 ? (
                <div className="overview-widget-grid">
                  {mainWidgets.map((widget) => {
                    const widgetMeta = MAIN_OVERVIEW_WIDGETS.find((item) => item.key === widget);
                    const isDragging = draggingWidget === widget;
                    const isDropTarget = dropTarget === widget && draggingWidget !== widget;
                    return (
                      <div
                        className={`overview-widget overview-widget--${widget} overview-widget--size-${layout.sizes[widget]}${editingLayout ? " overview-widget--editing" : ""}${isDragging ? " overview-widget--dragging" : ""}${isDropTarget ? " overview-widget--drop-target" : ""}${resizingWidget === widget ? " overview-widget--resizing" : ""}`}
                        key={widget}
                        onDragOver={(event) => {
                          if (!editingLayout || !draggingWidget || draggingWidget === widget) return;
                          event.preventDefault();
                          event.dataTransfer.dropEffect = "move";
                        }}
                        onDragEnter={() => {
                          if (editingLayout && draggingWidget && draggingWidget !== widget) setDropTarget(widget);
                        }}
                        onDrop={(event) => {
                          if (!editingLayout || !draggingWidget) return;
                          event.preventDefault();
                          moveDraftWidget(draggingWidget, widget);
                          setDraggingWidget(null);
                          setDropTarget(null);
                        }}
                      >
                        {editingLayout && widgetMeta && (
                          <button
                            className="overview-widget__drag-handle"
                            type="button"
                            draggable={!savingLayout}
                            aria-label={`Drag ${widgetMeta.label} to reposition`}
                            title={`Drag ${widgetMeta.label} to reposition`}
                            onDragStart={(event) => {
                              event.dataTransfer.effectAllowed = "move";
                              event.dataTransfer.setData("text/plain", widget);
                              setDraggingWidget(widget);
                              setDropTarget(null);
                            }}
                            onDragEnd={() => {
                              setDraggingWidget(null);
                              setDropTarget(null);
                            }}
                          >
                            <span aria-hidden="true">⠿</span>
                            <span>Move {widgetMeta.label}</span>
                          </button>
                        )}
                        {editingLayout && widgetMeta && (
                          <button
                            className="overview-widget__resize-handle"
                            type="button"
                            aria-label={`Resize ${widgetMeta.label}`}
                            title="Drag left for half width or right for full width"
                            onPointerDown={(event) => beginResize(event, widget)}
                            onPointerMove={(event) => updateResize(event, widget)}
                            onPointerUp={finishResize}
                            onPointerCancel={finishResize}
                          >
                            <span aria-hidden="true">◢</span>
                          </button>
                        )}
                        {renderMainWidget(widget)}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <Card><EmptyState title="No Overview widgets are showing" body="Open Settings to choose the widgets this business wants to see." /></Card>
              )}
            </section>
          </main>
          {!servicesOnLeft && services}
        </div>
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
  const [overviewLayout, setOverviewLayout] = useState<OverviewLayout>(defaultOverviewLayout);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [layoutStatus, setLayoutStatus] = useState<string | null>(null);
  const [savingLayout, setSavingLayout] = useState(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarStatus, setCalendarStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await api.get<{ business: Business; calendar: CalendarConnection; dashboard_layout: DashboardLayout }>(
        `/api/dashboard/businesses/${businessId}/settings`,
      );
      setBusiness(payload.business);
      setName(payload.business.name);
      setCalendar(payload.calendar);
      setCalendarId(payload.calendar.calendar_id);
      setTimezone(payload.calendar.timezone);
      setDuration(payload.calendar.default_duration_minutes);
      setOverviewLayout(payload.dashboard_layout.overview);
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

  const updateOverviewVisibility = (key: OverviewWidgetKey, visible: boolean) => {
    setOverviewLayout((current) => ({
      ...current,
      visible: { ...current.visible, [key]: visible },
    }));
  };

  const saveOverviewLayout = async (event: React.FormEvent) => {
    event.preventDefault();
    setLayoutError(null);
    setLayoutStatus(null);
    setSavingLayout(true);
    try {
      const payload = await api.patch<{ dashboard_layout: DashboardLayout }>(
        `/api/dashboard/businesses/${businessId}/settings`,
        { dashboard_layout: { overview: overviewLayout } },
      );
      setOverviewLayout(payload.dashboard_layout.overview);
      setLayoutStatus("Overview layout saved for everyone at this business.");
    } catch (err) {
      setLayoutError(err instanceof Error ? err.message : "Could not save the Overview layout.");
    } finally {
      setSavingLayout(false);
    }
  };

  const availableOverviewWidgets = new Set(overviewLayout.available_widgets);

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
        <Card
          title="Dashboard layout"
          action={<Link className="table__link" to={`/b/${businessId}`}>Preview Overview</Link>}
        >
          <p className="settings-card-copy">Choose what appears on this business’s Overview. Rearrange the actual widgets directly on the Overview page with Customize layout. These changes are shared with everyone who can access this business—not saved only on one person’s computer.</p>
          <form onSubmit={saveOverviewLayout} noValidate>
            <div className="dashboard-layout-list" aria-label="Overview widgets">
              {overviewLayout.order.filter((key) => availableOverviewWidgets.has(key)).map((key) => {
                const widget = MAIN_OVERVIEW_WIDGETS.find((item) => item.key === key);
                if (!widget || !availableOverviewWidgets.has(key)) return null;
                return (
                  <div className="dashboard-layout-row" key={key}>
                    <label className="dashboard-layout-row__toggle">
                      <input
                        type="checkbox"
                        checked={overviewLayout.visible[key]}
                        disabled={readOnly || savingLayout}
                        onChange={(event) => updateOverviewVisibility(key, event.target.checked)}
                      />
                      <span><strong>{widget.label}</strong><small>{widget.description}</small></span>
                    </label>
                  </div>
                );
              })}
              {availableOverviewWidgets.has("services") && (
                <div className="dashboard-layout-row dashboard-layout-row--services">
                  <label className="dashboard-layout-row__toggle">
                    <input
                      type="checkbox"
                      checked={overviewLayout.visible.services}
                      disabled={readOnly || savingLayout}
                      onChange={(event) => updateOverviewVisibility("services", event.target.checked)}
                    />
                    <span><strong>Your services rail</strong><small>Enabled services and their current status.</small></span>
                  </label>
                  <select
                    className="input dashboard-layout-row__select"
                    aria-label="Services rail position"
                    value={overviewLayout.services_position}
                    disabled={readOnly || savingLayout || !overviewLayout.visible.services}
                    onChange={(event) => setOverviewLayout((current) => ({ ...current, services_position: event.target.value as "left" | "right" }))}
                  >
                    <option value="right">Right side</option>
                    <option value="left">Left side</option>
                  </select>
                </div>
              )}
            </div>
            {readOnly && <p className="read-only-note">Your role has read-only access. Ask a business owner to change the dashboard layout.</p>}
            {layoutError && <p className="field__error" role="alert">{layoutError}</p>}
            {layoutStatus && <p className="calendar-success" role="status">{layoutStatus}</p>}
            <div className="dashboard-layout-footer">
              <button className="btn" type="button" disabled={readOnly || savingLayout} onClick={() => { setOverviewLayout(defaultOverviewLayout()); setLayoutStatus(null); setLayoutError(null); }}>
                Restore default
              </button>
              <button className="btn btn--primary" type="submit" disabled={readOnly || savingLayout}>
                {savingLayout ? "Saving layout..." : "Save Overview layout"}
              </button>
            </div>
          </form>
        </Card>

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
      <Route index element={<Overview businessId={businessId} modules={modules} readOnly={readOnly} />} />
      <Route path="leads" element={<Leads businessId={businessId} readOnly={readOnly} />} />
      <Route path="conversations" element={<Conversations businessId={businessId} />} />
      <Route path="appointments" element={<Appointments businessId={businessId} readOnly={readOnly} />} />
      <Route path="ai_intake" element={<AIIntake businessId={businessId} readOnly={readOnly} />} />
      <Route path="analytics" element={<Analytics businessId={businessId} />} />
      <Route path="website" element={<Website businessId={businessId} />} />
      <Route path="local_seo" element={<LocalSEO businessId={businessId} />} />
      <Route path="reviews" element={<Reviews businessId={businessId} />} />
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
