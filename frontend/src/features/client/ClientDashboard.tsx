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
import { Analytics } from "./Analytics";
import { Website } from "./Website";
import { LocalSEO, Reviews } from "./GoogleVisibility";

interface OverviewPayload {
  enabled_modules: NavModule[];
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
  if (!value) return "â€”";
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
                      <td data-label="Service request">{lead.service_request || lead.business_summary || "â€”"}</td>
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
        <span className="overview-module-card__icon" aria-hidden="true">{module.icon === "star" ? "â˜…" : module.icon === "globe" ? "â—‡" : module.icon === "search" ? "â—Ž" : module.icon === "bar-chart" ? "â–¤" : module.icon === "settings" ? "âš™" : "â—†"}</span>
        <span className="overview-module-card__label">{module.label}</span>
        <Badge tone={summary.tone}>{summary.value}</Badge>
      </div>
      <p>{summary.detail}</p>
      {module.implemented ? <Link className="table__link" to={module.key}>Open {module.label.toLowerCase()}</Link> : <span className="overview-module-card__soon">Enabled for this business</span>}
    </section>
  );
}

function Overview({ businessId, modules }: { businessId: string; modules: NavModule[] }) {
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
  const enabledModules = data?.enabled_modules ?? modules;
  const enabledKeys = new Set(enabledModules.map((module) => module.key));
  const summaryModules = enabledModules.filter((module) => module.key !== "overview").slice(0, 6);
  const showIntakeStats = ["leads", "conversations", "appointments", "ai_intake"].some((key) => enabledKeys.has(key));

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Overview
      </h1>
      <p className="page-subtitle">Your enabled business services at a glance.</p>

      {loading && <Loading rows={3} />}
      {error && <ErrorState body={error} />}
      {data && (
        <>
          <div className="overview-module-grid">
            {summaryModules.map((module) => <OverviewModuleCard key={module.key} module={module} data={data} />)}
          </div>

          {showIntakeStats && <div className="stat-grid">
            {enabledKeys.has("leads") && <Stat label="New leads" value={data.metrics.new_leads} icon="â—†" />}
            {enabledKeys.has("conversations") && <Stat label="Open conversations" value={data.metrics.open_conversations} icon="â—‰" />}
            {enabledKeys.has("appointments") && <Stat label="Pending approval" value={data.metrics.pending_approval} icon="â—·" />}
            {enabledKeys.has("ai_intake") && <Stat label="Missed calls handled" value={data.metrics.missed_calls_handled} icon="âœ†" />}
          </div>}

          {(enabledKeys.has("leads") || enabledKeys.has("appointments")) && <div className="overview-live-grid">
            {enabledKeys.has("leads") &&
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
            </Card>}

            {enabledKeys.has("appointments") &&
            <Card title="Appointment requests" action={<Link className="table__link" to="appointments">View all</Link>}>
              {data.appointment_requests.length === 0 ? (
                <EmptyState title="No pending requests" body="New scheduling preferences will appear here." />
              ) : (
                <div className="overview-appointments">
                  {data.appointment_requests.map((appointment) => (
                    <Link className="overview-appointment" to="appointments" key={appointment.id}>
                      <span className="overview-appointment__date" aria-hidden="true">â–£</span>
                      <span><strong>{appointment.customer_name || appointment.customer_phone}</strong><small>{appointment.service_request || "Service appointment"}</small><small>{appointment.requested_time_text || "Time not provided"}</small></span>
                      <span className="btn btn--primary">Review & schedule</span>
                    </Link>
                  ))}
                </div>
              )}
              <div className={data.calendar.connected ? "calendar-banner calendar-banner--ok calendar-banner--compact" : "calendar-banner calendar-banner--warn calendar-banner--compact"}>
                <span>{data.calendar.connected ? "âœ“" : "!"}</span>
                <strong>{data.calendar.connected ? `${data.calendar.calendar_name} connected` : "Calendar not connected"}</strong>
              </div>
            </Card>}
          </div>}

          {(enabl×~5âÚ$z{-®éÜj×¹•ÍÍ}¥¤(€€€€€€€€€€€€€€€€¤¹Í…±…É}½¹” ¤°(€€€€€€€€€€€ô°(€€€€€€€ô(€€€€¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á…Ñ  ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥øˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜ÕÁ‘…Ñ•}‰ÕÍ¥¹•ÍÌ¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ¤è(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€¡…¹•€ôíô((€€€¥˜€‰¹…µ”ˆ¥¸Á…å±½…è(€€€€€€€¹…µ”€ô€¡Á…å±½…¹•Ð ‰¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ð¹…µ”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰¹…µ”ˆè€‰I•ÅÕ¥É•¸‰õô¤°€ÐÀÀ(€€€€€€€¡…¹•‘l‰¹…µ”‰t€ô¹…µ”(€€€€€€€‰ÕÍ¥¹•ÍÌ¹¹…µ”€ô¹…µ”((€€€¥˜€‰ÍÑ…ÑÕÌˆ¥¸Á…å±½…è(€€€€€€€ÍÑ…ÑÕÌ€ô€¡Á…å±½…¹•Ð ‰ÍÑ…ÑÕÌˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€€€€€¥˜ÍÑ…ÑÕÌ¹½Ð¥¸ì‰…Ñ¥Ù”ˆ°€‰ÍÕÍÁ•¹‘•‰ôè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰ÍÑ…ÑÕÌˆè€‰%¹Ù…±¥¸‰õô¤°€ÐÀÀ(€€€€€€€¡…¹•‘l‰ÍÑ…ÑÕÌ‰t€ôÍÑ…ÑÕÌ(€€€€€€€‰ÕÍ¥¹•ÍÌ¹ÍÑ…ÑÕÌ€ôÍÑ…ÑÕÌ((€€€¥˜€‰Í•ÑÑ¥¹Ìˆ¥¸Á…å±½……¹¥Í¥¹ÍÑ…¹”¡Á…å±½…‘l‰Í•ÑÑ¥¹Ì‰t°‘¥Ð¤è(€€€€€€€‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì€ôÁ…å±½…‘l‰Í•ÑÑ¥¹Ì‰t(€€€€€€€¡…¹•‘l‰Í•ÑÑ¥¹Ì‰t€ô€‰ÕÁ‘…Ñ•ˆ((€€€¥˜€‰‘•™…Õ±Ñ}ÁÉ½™¥±•}­•äˆ¥¸Á…å±½…è(€€€€€€€‰ÕÍ¥¹•ÍÌ¹‘•™…Õ±Ñ}ÁÉ½™¥±•}­•ä€ôÁ…å±½…¹•Ð ‰‘•™…Õ±Ñ}ÁÉ½™¥±•}­•äˆ¤½È9½¹”(€€€€€€€¡…¹•‘l‰‘•™…Õ±Ñ}ÁÉ½™¥±•}­•ä‰t€ô‰ÕÍ¥¹•ÍÌ¹‘•™…Õ±Ñ}ÁÉ½™¥±•}­•ä((€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰‰ÕÍ¥¹•ÍÌ¹ÕÁ‘…Ñ”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÌˆ°(€€€€€€€Ñ…É•Ñ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõ¡…¹•°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤((€€€µ½‘Õ±•}­•åÌ€ôÍ½ÉÑ•¡•¹Ñ¥Ñ±•µ•¹ÑÌ¹•¹…‰±•‘}µ½‘Õ±•}­•åÌ¡œ¹‘ˆ°‰ÕÍ¥¹•ÍÍ}¥¤¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡‰ÕÍ¥¹•ÍÍ}‘Ñ¼¡‰ÕÍ¥¹•ÍÌ°µ½‘Õ±•}­•åÌõµ½‘Õ±•}­•åÌ¤¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á…Ñ  ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½Ý•‰Í¥Ñ”ˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜ÕÁ‘…Ñ•}‰ÕÍ¥¹•ÍÍ}Ý•‰Í¥Ñ”¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ¤è(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€ÑÉäè(€€€€€€€ÕÉ°€ôÝ•‰Í¥Ñ•}µ½¹¥Ñ½É¥¹œ¹¹½Éµ…±¥é•}ÕÉ°¡Á…å±½…¹•Ð ‰ÕÉ°ˆ¤½È€ˆˆ¤(€€€•á•ÁÐY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰ÕÉ°ˆèÍÑÈ¡•áŒ¥õô¤°€ÐÀÀ(€€€µ½¹¥Ñ½É}¥€ôÍÑÈ¡Á…å±½…¹•Ð ‰µ½¹¥Ñ½É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜µ½¹¥Ñ½É}¥…¹¹½Ðµ½¹¥Ñ½É}¥¹¥Í‘¥¥Ð ¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰µ½¹¥Ñ½É}¥ˆè€‰5½¹¥Ñ½È%µÕÍÐ½¹Ñ…¥¸¹Õµ‰•ÉÌ½¹±ä¸‰õô¤°€ÐÀÀ((€€€Í•ÑÑ¥¹Ì€ô‘¥Ð¡‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì½Èíô¤(€€€Í•ÑÑ¥¹Íl‰Ý•‰Í¥Ñ”‰t€ôì‰ÕÉ°ˆèÕÉ°°€‰µ½¹¥Ñ½É}¥ˆèµ½¹¥Ñ½É}¥‘ô(€€€‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì€ôÍ•ÑÑ¥¹Ì(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰‰ÕÍ¥¹•ÍÌ¹Ý•‰Í¥Ñ”¹ÕÁ‘…Ñ”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÌˆ°(€€€€€€€Ñ…É•Ñ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰ÕÉ°ˆèÕÉ°°€‰µ½¹¥Ñ½É}¥ˆèµ½¹¥Ñ½É}¥‘ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡Í•ÑÑ¥¹Íl‰Ý•‰Í¥Ñ”‰t¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á…Ñ  ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½½½±”µÙ¥Í¥‰¥±¥Ñäˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜ÕÁ‘…Ñ•}½½±•}Ù¥Í¥‰¥±¥Ñä¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ¤è(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ(€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€™¥•±‘Ì€ôíô(€€€±•…¸€ôíô(€€€™½È­•ä°Ù…±¥‘…Ñ½È¥¸€  ‰Í•…É¡}ÁÉ½Á•ÉÑäˆ°½½±•}Ù¥Í¥‰¥±¥Ñä¹Ù…±¥‘…Ñ•}ÁÉ½Á•ÉÑä¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ ‰ÁÉ½™¥±•}±½…Ñ¥½¸ˆ°½½±•}Ù¥Í¥‰¥±¥Ñä¹Ù…±¥‘…Ñ•}±½…Ñ¥½¸¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ ‰ÁÉ½™¥±•}ÕÉ°ˆ°½½±•}Ù¥Í¥‰¥±¥Ñä¹Ù…±¥‘…Ñ•}ÁÉ½™¥±•}ÕÉ°¤¤è(€€€€€€€ÑÉäè(€€€€€€€€€€€±•…¹m­•åt€ôÙ…±¥‘…Ñ½È¡ÍÑÈ¡Á…å±½…¹•Ð¡­•ä¤½È€ˆˆ¤¤(€€€€€€€•á•ÁÐY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€€€€€™¥•±‘Ím­•åt€ôÍÑÈ¡•áŒ¤(€€€¥˜™¥•±‘Ìè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆè™¥•±‘Íô¤°€ÐÀÀ(€€€Í•ÑÑ¥¹Ì€ô‘¥Ð¡‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì½Èíô¤(€€€Í•ÑÑ¥¹Íl‰½½±•}Ù¥Í¥‰¥±¥Ñä‰t€ô±•…¸(€€€‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì€ôÍ•ÑÑ¥¹Ì(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð¡œ¹‘ˆ°…Ñ¥½¸ô‰‰ÕÍ¥¹•ÍÌ¹½½±•}Ù¥Í¥‰¥±¥Ñä¹ÕÁ‘…Ñ”ˆ°(€€€€€€€€€€€€€€€€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÌˆ°Ñ…É•Ñ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€€€€€€€€€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€€€€€€€€€€€€€€€€‘•Ñ…¥±Ìõ±•…¸¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡±•…¸¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½Ý•‰Í¥Ñ•Ìˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}Ý•‰Í¥Ñ•Ì ¤è(€€€‰ÕÍ¥¹•ÍÍ•Ì€ô±¥ÍÐ¡œ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡	ÕÍ¥¹•ÍÌ¤¹½É‘•É}‰ä¡	ÕÍ¥¹•ÍÌ¹¹…µ”¤¤¹Í…±…ÉÌ ¤¤(€€€½¹™¥ÕÉ•€ôÝ•‰Í¥Ñ•}µ½¹¥Ñ½É¥¹œ¹¥Í}½¹™¥ÕÉ• ¤(€€€ÁÉ½Ù¥‘•É}•ÉÉ½È€ô9½¹”(€€€µ½¹¥Ñ½ÉÌ€ômt(€€€¥˜½¹™¥ÕÉ•è(€€€€€€€ÑÉäè(€€€€€€€€€€€µ½¹¥Ñ½ÉÌ€ôÝ•‰Í¥Ñ•}µ½¹¥Ñ½É¥¹œ¹±¥ÍÑ}µ½¹¥Ñ½ÉÌ ¤(€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì•áŒè€€ŒÁÉ½Ù¥‘•È™…¥±ÕÉ•ÌÍ¡½Õ±¹½Ð•É…Í”ÍÑ½É•Í¥Ñ”½¹™¥œ(€€€€€€€€€€€±½•È¹Ý…É¹¥¹œ ‰UÁÑ¥µ•I½‰½Ð±½½­ÕÀ™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€ÁÉ½Ù¥‘•É}•ÉÉ½È€ô€‰UÁÑ¥µ•I½‰½Ð½Õ±¹½Ð‰”É•…¡•¸QÉäÉ•™É•Í¡¥¹œ¥¸„µ½µ•¹Ð¸ˆ((€€€‰å}¥€ôí¥Ñ•µl‰¥‰tè¥Ñ•´™½È¥Ñ•´¥¸µ½¹¥Ñ½ÉÍô(€€€‰å}ÕÉ°€ôíô(€€€™½È¥Ñ•´¥¸µ½¹¥Ñ½ÉÌè(€€€€€€€ÑÉäè(€€€€€€€€€€€‰å}ÕÉ±mÝ•‰Í¥Ñ•}µ½¹¥Ñ½É¥¹œ¹¹½Éµ…±¥é•}ÕÉ°¡¥Ñ•µl‰ÕÉ°‰t¥t€ô¥Ñ•´(€€€€€€€•á•ÁÐY…±Õ•ÉÉ½Èè(€€€€€€€€€€€½¹Ñ¥¹Õ”((€€€É½ÝÌ€ômt(€€€™½È‰ÕÍ¥¹•ÍÌ¥¸‰ÕÍ¥¹•ÍÍ•Ìè(€€€€€€€½¹™¥œ€ô€¡‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì½Èíô¤¹•Ð ‰Ý•‰Í¥Ñ”ˆ¤½Èíô(€€€€€€€ÕÉ°€ô½¹™¥œ¹•Ð ‰ÕÉ°ˆ¤½È€ˆˆ(€€€€€€€µ½¹¥Ñ½È€ô‰å}¥¹•Ð¡ÍÑÈ¡½¹™¥œ¹•Ð ‰µ½¹¥Ñ½É}¥ˆ¤½È€ˆˆ¤¤(€€€€€€€¥˜µ½¹¥Ñ½È¥Ì9½¹”…¹ÕÉ°è(€€€€€€€€€€€µ½¹¥Ñ½È€ô‰å}ÕÉ°¹•Ð¡Ý•‰Í¥Ñ•}µ½¹¥Ñ½É¥¹œ¹¹½Éµ…±¥é•}ÕÉ°¡ÕÉ°¤¤(€€€€€€€É½ÝÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÌˆèì‰¥ˆè‰ÕÍ¥¹•ÍÌ¹¥°€‰¹…µ”ˆè‰ÕÍ¥¹•ÍÌ¹¹…µ”°€‰Í±Õœˆè‰ÕÍ¥¹•ÍÌ¹Í±Õô°(€€€€€€€€€€€€‰ÕÉ°ˆèÕÉ°°(€€€€€€€€€€€€‰µ½¹¥Ñ½É}¥ˆèÍÑÈ¡½¹™¥œ¹•Ð ‰µ½¹¥Ñ½É}¥ˆ¤½È€¡µ½¹¥Ñ½È½Èíô¤¹•Ð ‰¥ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€‰µ½¹¥Ñ½Èˆèµ½¹¥Ñ½È°(€€€€€€€ô¤((€€€µ…Ñ¡•‘}¥‘Ì€ôíÉ½Ýl‰µ½¹¥Ñ½È‰ul‰¥‰t™½ÈÉ½Ü¥¸É½ÝÌ¥˜É½Ýl‰µ½¹¥Ñ½È‰uô(€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€‰ÁÉ½Ù¥‘•Èˆèì(€€€€€€€€€€€€‰¹…µ”ˆè€‰UÁÑ¥µ•I½‰½Ðˆ°(€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè½¹™¥ÕÉ•°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰•ÉÉ½Èˆ¥˜ÁÉ½Ù¥‘•É}•ÉÉ½È•±Í”€ ‰½¹¹•Ñ•ˆ¥˜½¹™¥ÕÉ••±Í”€‰¹½Ñ}½¹™¥ÕÉ•ˆ¤°(€€€€€€€€€€€€‰•ÉÉ½ÈˆèÁÉ½Ù¥‘•É}•ÉÉ½È°(€€€€€€€ô°(€€€€€€€€‰µ•ÑÉ¥Ìˆèì(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÍ•Ìˆè±•¸¡‰ÕÍ¥¹•ÍÍ•Ì¤°(€€€€€€€€€€€€‰½¹™¥ÕÉ•‘}Í¥Ñ•ÌˆèÍÕ´ Ä™½ÈÉ½Ü¥¸É½ÝÌ¥˜É½Ýl‰ÕÉ°‰t¤°(€€€€€€€€€€€€‰½¹±¥¹”ˆèÍÕ´ Ä™½ÈÉ½Ü¥¸É½ÝÌ¥˜É½Ýl‰µ½¹¥Ñ½È‰t…¹É½Ýl‰µ½¹¥Ñ½È‰ul‰ÍÑ…ÑÕÌ‰t€ôô€‰ÕÀˆ¤°(€€€€€€€€€€€€‰…ÑÑ•¹Ñ¥½¸ˆèÍÕ´ Ä™½ÈÉ½Ü¥¸É½ÝÌ¥˜É½Ýl‰µ½¹¥Ñ½È‰t…¹É½Ýl‰µ½¹¥Ñ½È‰ul‰ÍÑ…ÑÕÌ‰t¥¸ì‰‘½Ý¸ˆ°€‰Í••µÍ}‘½Ý¸‰ô¤°(€€€€€€€ô°(€€€€€€€€‰Í¥Ñ•ÌˆèÉ½ÝÌ°(€€€€€€€€‰Õ¹µ…Ñ¡•‘}µ½¹¥Ñ½ÉÌˆèm¥Ñ•´™½È¥Ñ•´¥¸µ½¹¥Ñ½ÉÌ¥˜¥Ñ•µl‰¥‰t¹½Ð¥¸µ…Ñ¡•‘}¥‘Ít°(€€€ô¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½ÑÝ¥±¥¼µÕÍ…”ˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}ÑÝ¥±¥½}ÕÍ…” ¤è(€€€Á•É¥½€ô€¡É•ÅÕ•ÍÐ¹…ÉÌ¹•Ð ‰Á•É¥½ˆ¤½È€‰Ñ¡¥Í}µ½¹Ñ ˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€¥˜Á•É¥½¹½Ð¥¸ì‰Ñ¡¥Í}µ½¹Ñ ˆ°€‰±…ÍÑ}µ½¹Ñ ‰ôè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰A•É¥½µÕÍÐ‰”Ñ¡¥Í}µ½¹Ñ ½È±…ÍÑ}µ½¹Ñ ¸‰ô¤°€ÐÀÀ(€€€¥˜¹½ÐÑÝ¥±¥½}ÕÍ…”¹¥Í}½¹™¥ÕÉ• ¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¹™¥ÕÉ•ˆè…±Í”°€‰ÕÍ…”ˆè9½¹•ô¤°€ÈÀÀ(€€€ÑÉäè(€€€€€€€ÕÍ…”€ôÑÝ¥±¥½}ÕÍ…”¹™•Ñ¡}ÕÍ…”¡Á•É¥½¤(€€€•á•ÁÐá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€±½•È¹Ý…É¹¥¹œ ‰QÝ¥±¥¼ÕÍ…”±½½­ÕÀ™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆèQÉÕ”°(€€€€€€€€€€€€‰ÕÍ…”ˆè9½¹”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè€‰QÝ¥±¥¼ÕÍ…”½Õ±¹½Ð‰”±½…‘•¸¡•¬Ñ¡”…½Õ¹ÐÉ•‘•¹Ñ¥…±Ì…¹ÑÉä……¥¸¸ˆ°(€€€€€€€ô¤°€ÈÀÀ(€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¹™¥ÕÉ•ˆèQÉÕ”°€‰ÕÍ…”ˆèÕÍ…•ô¤°€ÈÀÀ(()…‘µ¥¹}‰À¹ÁÕÐ ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½µ½‘Õ±•Ì¼ñµ½‘Õ±•}­•äøˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜Í•Ñ}‰ÕÍ¥¹•ÍÍ}µ½‘Õ±”¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ°µ½‘Õ±•}­•äèÍÑÈ¤è(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ(€€€¥˜¹½Ð•¹Ñ¥Ñ±•µ•¹ÑÌ¹¥Í}Ù…±¥‘}µ½‘Õ±”¡µ½‘Õ±•}­•ä¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰U¹­¹½Ý¸µ½‘Õ±”¸‰ô¤°€ÐÀÐ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€•¹…‰±•€ô‰½½°¡Á…å±½…¹•Ð ‰•¹…‰±•ˆ°…±Í”¤¤((€€€•¹Ñ¥Ñ±•µ•¹ÑÌ¹Í•Ñ}µ½‘Õ±”¡œ¹‘ˆ°‰ÕÍ¥¹•ÍÍ}¥°µ½‘Õ±•}­•ä°•¹…‰±•¤(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰‰ÕÍ¥¹•ÍÌ¹µ½‘Õ±”¹ÕÁ‘…Ñ”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÍ}µ½‘Õ±”ˆ°(€€€€€€€Ñ…É•Ñ}¥õµ½‘Õ±•}­•ä°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰µ½‘Õ±”ˆèµ½‘Õ±•}­•ä°€‰•¹…‰±•ˆè•¹…‰±•‘ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤((€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰µ½‘Õ±•}­•äˆèµ½‘Õ±•}­•ä°€‰•¹…‰±•ˆè•¹…‰±•‘ô¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½Á¡½¹”µ¹Õµ‰•ÉÌˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜…‘‘}Á¡½¹•}¹Õµ‰•È¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ¤è(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€Á¡½¹”€ô€¡Á…å±½…¹•Ð ‰Á¡½¹”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¹½Éµ…±¥é•€ô¹½Éµ…±¥é•}Á¡½¹”¡Á¡½¹”¤(€€€‘¥¥ÑÌ€ô¹½Éµ…±¥é•¹É•µ½Ù•ÁÉ•™¥à ˆ¬ˆ¤(€€€¥˜¹½Ð¹½Éµ…±¥é•½È¹½Ð‘¥¥ÑÌ¹¥Í‘¥¥Ð ¤½È¹½Ð€ÄÀ€ðô±•¸¡‘¥¥ÑÌ¤€ðô€ÄÔè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°(€€€€€€€€€€€€€€€€‰™¥•±‘Ìˆèì‰Á¡½¹”ˆè€‰¹Ñ•È„Ù…±¥€ÄÃŠLÄÔ‘¥¥ÐÁ¡½¹”¹Õµ‰•È¸‰ô°(€€€€€€€€€€€ô(€€€€€€€€¤°€ÐÀÀ((€€€•á¥ÍÑ¥¹œ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¤¹Ý¡•É”¡	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¹Á¡½¹”€ôô¹½Éµ…±¥é•¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€¥˜•á¥ÍÑ¥¹œ¥Ì¹½Ð9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰•ÉÉ½Èˆè€‰Q¡…ÐÁ¡½¹”¹Õµ‰•È¥Ì…±É•…‘ä…ÍÍ¥¹•¸ˆ°(€€€€€€€€€€€€€€€€‰™¥•±‘Ìˆèì‰Á¡½¹”ˆè€‰±É•…‘ä…ÍÍ¥¹•Ñ¼…¹½Ñ¡•ÈÑ•¹…¹Ð¸‰ô°(€€€€€€€€€€€ô(€€€€€€€€¤°€ÐÀä((€€€¹Õµ‰•È€ô…ÍÍ¥¹}Á¡½¹•}¹Õµ‰•È (€€€€€€€œ¹‘ˆ°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€Á¡½¹”õÁ¡½¹”°(€€€€€€€±…‰•°õÁ…å±½…¹•Ð ‰±…‰•°ˆ¤°(€€€€€€€Í•ÑÑ¥¹ÌõÁ…å±½…¹•Ð ‰Í•ÑÑ¥¹Ìˆ¤½Èíô°(€€€€¤(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰‰ÕÍ¥¹•ÍÌ¹Á¡½¹•}¹Õµ‰•È¹…ÍÍ¥¸ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÍ}Á¡½¹•}¹Õµ‰•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÍÑÈ¡¹Õµ‰•È¹¥¤°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰Á¡½¹”ˆè¹Õµ‰•È¹Á¡½¹•ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡Á¡½¹•}¹Õµ‰•É}‘Ñ¼¡¹Õµ‰•È¤¤°€ÈÀÄ(()…‘µ¥¹}‰À¹Á…Ñ  ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½Á¡½¹”µ¹Õµ‰•ÉÌ¼ñ¥¹Ðé¹Õµ‰•É}¥øˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜ÕÁ‘…Ñ•}Á¡½¹•}¹Õµ‰•È¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ°¹Õµ‰•É}¥è¥¹Ð¤è(€€€¹Õµ‰•È€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¤¹Ý¡•É” (€€€€€€€€€€€	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¹¥€ôô¹Õµ‰•É}¥°(€€€€€€€€€€€	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¹‰ÕÍ¥¹•ÍÍ}¥€ôô‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€¥˜¹Õµ‰•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰A¡½¹”¹Õµ‰•È¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€¡…¹•€ôíô(€€€¥˜€‰±…‰•°ˆ¥¸Á…å±½…è(€€€€€€€¹Õµ‰•È¹±…‰•°€ô€¡Á…å±½…¹•Ð ‰±…‰•°ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”(€€€€€€€¡…¹•‘l‰±…‰•°‰t€ô¹Õµ‰•È¹±…‰•°(€€€¥˜€‰•¹…‰±•ˆ¥¸Á…å±½…è(€€€€€€€¥˜¹½Ð¥Í¥¹ÍÑ…¹”¡Á…å±½…‘l‰•¹…‰±•‰t°‰½½°¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€€€€€€€€€ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰•¹…‰±•ˆè€‰5ÕÍÐ‰”ÑÉÕ”½È™…±Í”¸‰õô(€€€€€€€€€€€€¤°€ÐÀÀ(€€€€€€€¹Õµ‰•È¹•¹…‰±•€ôÁ…å±½…‘l‰•¹…‰±•‰t(€€€€€€€¡…¹•‘l‰•¹…‰±•‰t€ô¹Õµ‰•È¹•¹…‰±•(€€€¥˜¹½Ð¡…¹•è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰9¼ÍÕÁÁ½ÉÑ•¡…¹•ÌÝ•É”ÍÕÁÁ±¥•¸‰ô¤°€ÐÀÀ((€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰‰ÕÍ¥¹•ÍÌ¹Á¡½¹•}¹Õµ‰•È¹ÕÁ‘…Ñ”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÍ}Á¡½¹•}¹Õµ‰•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÍÑÈ¡¹Õµ‰•È¹¥¤°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõ¡…¹•°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡Á¡½¹•}¹Õµ‰•É}‘Ñ¼¡¹Õµ‰•È¤¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½ÕÍ•ÉÌˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜±¥ÍÑ}ÕÍ•ÉÌ ¤è(€€€É½ÝÌ€ô±¥ÍÐ¡œ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡A±…Ñ™½ÉµUÍ•È¤¹½É‘•É}‰ä¡A±…Ñ™½ÉµUÍ•È¹•µ…¥°¤¤¹Í…±…ÉÌ ¤¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰¥Ñ•µÌˆèmÕÍ•É}‘Ñ¼¡Ô¤™½ÈÔ¥¸É½ÝÍuô¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½ÕÍ•ÉÌˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜É•…Ñ•}ÕÍ•È ¤è(€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€•µ…¥°€ô€¡Á…å±½…¹•Ð ‰•µ…¥°ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€Á…ÍÍÝ½É€ôÁ…å±½…¹•Ð ‰Á…ÍÍÝ½Éˆ¤½È€ˆˆ(€€€É½±”€ô€¡Á…å±½…¹•Ð ‰Á±…Ñ™½Éµ}É½±”ˆ¤½È€‰¹½¹”ˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€Í•ÑÕÁ}µ•Ñ¡½€ô€¡Á…å±½…¹•Ð ‰Í•ÑÕÁ}µ•Ñ¡½ˆ¤½È€‰Ñ•µÁ½É…Éäˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€‰ÕÍ¥¹•ÍÍ}¥€ô€¡Á…å±½…¹•Ð ‰‰ÕÍ¥¹•ÍÍ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€Ñ•¹…¹Ñ}É½±”€ô€¡Á…å±½…¹•Ð ‰Ñ•¹…¹Ñ}É½±”ˆ¤½È€‰½Ý¹•Èˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤((€€€•ÉÉ½ÉÌ€ôíô(€€€¥˜€‰ ˆ¹½Ð¥¸•µ…¥°è(€€€€€€€•ÉÉ½ÉÍl‰•µ…¥°‰t€ô€‰Ù…±¥•µ…¥°¥ÌÉ•ÅÕ¥É•¸ˆ(€€€¥˜Í•ÑÕÁ}µ•Ñ¡½¹½Ð¥¸ì‰Ñ•µÁ½É…Éäˆ°€‰•µ…¥°‰ôè(€€€€€€€•ÉÉ½ÉÍl‰Í•ÑÕÁ}µ•Ñ¡½‰t€ô€‰¡½½Í”•µ…¥°Í•ÑÕÀ½È„Ñ•µÁ½É…ÉäÁ…ÍÍÝ½É¸ˆ(€€€¥˜Í•ÑÕÁ}µ•Ñ¡½€ôô€‰•µ…¥°ˆè(€€€€€€€¥˜É½±”€„ô€‰¹½¹”ˆ½È¹½Ð‰ÕÍ¥¹•ÍÍ}¥è(€€€€€€€€€€€•ÉÉ½ÉÍl‰Í•ÑÕÁ}µ•Ñ¡½‰t€ô€‰µ…¥°Í•ÑÕÀ¥Ì½¹±ä…Ù…¥±…‰±”™½È„‰ÕÍ¥¹•ÍÌ±¥•¹Ð¸ˆ(€€€€€€€¥˜¹½Ðµ…¥±•È¹½¹™¥ÕÉ• ¤½È¹½Ð½Ì¹•Ñ•¹Ø ‰AU	1%}	M}UI0ˆ°€ˆˆ¤¹ÍÑÉ¥À ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰½Õ¹ÐÍ•ÑÕÀ•µ…¥°¥Ì¹½Ð½¹™¥ÕÉ•¸‰ô¤°€ÔÀÌ(€€€•±Í”è(€€€€€€€ÍÑÉ•¹Ñ¡}•ÉÉ½È€ôÁ…ÍÍÝ½É‘Ì¹Ù…±¥‘…Ñ•}Á…ÍÍÝ½É‘}ÍÑÉ•¹Ñ ¡Á…ÍÍÝ½É¤(€€€€€€€¥˜ÍÑÉ•¹Ñ¡}•ÉÉ½Èè(€€€€€€€€€€€•ÉÉ½ÉÍl‰Á…ÍÍÝ½É‰t€ôÍÑÉ•¹Ñ¡}•ÉÉ½È(€€€¥˜É½±”¹½Ð¥¸Y1%}A1Q=I5}I=1Lè(€€€€€€€•ÉÉ½ÉÍl‰Á±…Ñ™½Éµ}É½±”‰t€ô€‰%¹Ù…±¥É½±”¸ˆ(€€€¥˜‰ÕÍ¥¹•ÍÍ}¥…¹œ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤¥Ì9½¹”è(€€€€€€€•ÉÉ½ÉÍl‰‰ÕÍ¥¹•ÍÍ}¥‰t€ô€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸ˆ(€€€¥˜‰ÕÍ¥¹•ÍÍ}¥…¹€¡É½±”€„ô€‰¹½¹”ˆ½ÈÑ•¹…¹Ñ}É½±”¹½Ð¥¸Y1%}55	IM!%A}I=1L¤è(€€€€€€€•ÉÉ½ÉÍl‰Ñ•¹…¹Ñ}É½±”‰t€ô€‰¡½½Í”„Ù…±¥±¥•¹ÐÉ½±”¸ˆ(€€€¥˜•ÉÉ½ÉÌè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆè•ÉÉ½ÉÍô¤°€ÐÀÀ((€€€•á¥ÍÑ¥¹œ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡A±…Ñ™½ÉµUÍ•È¤¹Ý¡•É”¡A±…Ñ™½ÉµUÍ•È¹•µ…¥°€ôô•µ…¥°¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€¥˜•á¥ÍÑ¥¹œ¥Ì¹½Ð9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Q¡…Ð•µ…¥°¥Ì…±É•…‘äÉ•¥ÍÑ•É•¸‰ô¤°€ÐÀä((€€€ÕÍ•È€ôA±…Ñ™½ÉµUÍ•È (€€€€€€€¥õÍÑÈ¡ÕÕ¥Ð ¤¤°(€€€€€€€•µ…¥°õ•µ…¥°°(€€€€€€€‘¥ÍÁ±…å}¹…µ”ô¡Á…å±½…¹•Ð ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”°(€€€€€€€Á…ÍÍÝ½É‘}¡…Í õÁ…ÍÍÝ½É‘Ì¹¡…Í¡}Á…ÍÍÝ½É¡¹•Ý}Ñ½­•¸ ¤¥˜Í•ÑÕÁ}µ•Ñ¡½€ôô€‰•µ…¥°ˆ•±Í”Á…ÍÍÝ½É¤°(€€€€€€€Á±…Ñ™½Éµ}É½±”õÉ½±”°(€€€€€€€¥Í}Á±…Ñ™½Éµ}…‘µ¥¸ô¡É½±”€ôô€‰…‘µ¥¸ˆ¤°(€€€€€€€¥Í}…Ñ¥Ù”õQÉÕ”°(€€€€€€€µÕÍÑ}¡…¹•}Á…ÍÍÝ½Éô¡É½±”€ôô€‰¹½¹”ˆ¤°(€€€€¤(€€€œ¹‘ˆ¹…‘¡ÕÍ•È¤(€€€œ¹‘ˆ¹™±ÕÍ  ¤(€€€¥˜‰ÕÍ¥¹•ÍÍ}¥è(€€€€€€€œ¹‘ˆ¹…‘¡	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¡‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°ÕÍ•É}¥õÕÍ•È¹¥°É½±”õÑ•¹…¹Ñ}É½±”¤¤(€€€Í•ÑÕÁ}Ñ½­•¸€ô€ (€€€€€€€Á…ÍÍÝ½É‘}É•Í•Ð¹¥ÍÍÕ”¡œ¹‘ˆ°ÕÍ•É}¥õÕÍ•È¹¥°É…Ý}¥Àõ±¥•¹Ñ}¥À ¤¤(€€€€€€€¥˜Í•ÑÕÁ}µ•Ñ¡½€ôô€‰•µ…¥°ˆ•±Í”9½¹”(€€€€¤((€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰ÕÍ•È¹É•…Ñ”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰Á±…Ñ™½Éµ}ÕÍ•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÕÍ•È¹¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥½È9½¹”°(€€€€€€€‘•Ñ…¥±Ìõì‰•µ…¥°ˆè•µ…¥°°€‰Á±…Ñ™½Éµ}É½±”ˆèÉ½±”°€‰Í•ÑÕÁ}µ•Ñ¡½ˆèÍ•ÑÕÁ}µ•Ñ¡½‘ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÍÕ±Ð€ôÕÍ•É}‘Ñ¼¡ÕÍ•È¤(€€€¥˜Í•ÑÕÁ}Ñ½­•¸è(€€€€€€€É•ÍÕ±Ñl‰Í•ÑÕÁ}•µ…¥±}Í•¹Ð‰t€ôµ…¥±•È¹Í•¹‘}…½Õ¹Ñ}Í•ÑÕÀ¡É•¥Á¥•¹ÐõÕÍ•È¹•µ…¥°°Ñ½­•¸õÍ•ÑÕÁ}Ñ½­•¸¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÕ±Ð¤°€ÈÀÄ(()…‘µ¥¹}‰À¹‘•±•Ñ” ˆ½ÕÍ•ÉÌ¼ñÕÍ•É}¥øˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜‘•±•Ñ•}±¥•¹Ñ}ÕÍ•È¡ÕÍ•É}¥èÍÑÈ¤è(€€€ÕÍ•È€ôœ¹‘ˆ¹•Ð¡A±…Ñ™½ÉµUÍ•È°ÕÍ•É}¥¤(€€€¥˜ÕÍ•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰UÍ•È¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ(€€€¥˜ÕÍ•È¹¥€ôôœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥½ÈÁ±…Ñ™½Éµ}É½±”¡ÕÍ•È¤€„ô€‰¹½¹”ˆè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰=¹±ä±¥•¹Ð…½Õ¹ÑÌ…¸‰”‘•±•Ñ•¸‰ô¤°€ÐÀÌ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€¥˜€¡Á…å±½…¹•Ð ‰½¹™¥Éµ}•µ…¥°ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤€„ôÕÍ•È¹•µ…¥°è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰¹Ñ•ÈÑ¡”…½Õ¹Ð•µ…¥°Ñ¼½¹™¥É´‘•±•Ñ¥½¸¸‰ô¤°€ÐÀÀ((€€€µ•µ‰•ÉÍ¡¥Á}¥‘Ì€ô±¥ÍÐ¡œ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¹‰ÕÍ¥¹•ÍÍ}¥¤¹Ý¡•É”¡	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¹ÕÍ•É}¥€ôôÕÍ•É}¥¤(€€€€¤¹Í…±…ÉÌ ¤¤(€€€•µ…¥°€ôÕÍ•È¹•µ…¥°(€€€€Œ-••À¡¥ÍÑ½É¥…°‰ÕÍ¥¹•ÍÌÉ•½É‘Ì¸9Õ±±…‰±”…ÑÑÉ¥‰ÕÑ¥½¸™¥•±‘Ì±½Í”Ñ¡•¥È(€€€€ŒÕÍ•ÈÉ•™•É•¹”ìÑ¡”¥µµÕÑ…‰±”…Õ‘¥Ð•¹ÑÉä‰•±½ÜÉ•Ñ…¥¹ÌÑ¡”‘•±•Ñ¥½¸¸(€€€™½Èµ½‘•°°½±Õµ¸¥¸€ (€€€€€€€€¡1•…°1•…¹…É¡¥Ù•‘}‰å}ÕÍ•É}¥¤°(€€€€€€€€¡5¥ÍÍ•‘…±±Ù•¹Ð°5¥ÍÍ•‘…±±Ù•¹Ð¹…É¡¥Ù•‘}‰å}ÕÍ•É}¥¤°(€€€€€€€€¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ°ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¹Í¡•‘Õ±•‘}‰å}ÕÍ•É}¥¤°(€€€€€€€€¡Õ‘¥ÑÙ•¹Ð°Õ‘¥ÑÙ•¹Ð¹…Ñ½É}ÕÍ•É}¥¤°(€€€€¤è(€€€€€€€œ¹‘ˆ¹•á•ÕÑ”¡ÕÁ‘…Ñ”¡µ½‘•°¤¹Ý¡•É”¡½±Õµ¸€ôôÕÍ•É}¥¤¹Ù…±Õ•Ì¡í½±Õµ¸¹­•äè9½¹•ô¤¤(€€€™½Èµ½‘•°¥¸€¡	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À°UÍ•ÉM•ÍÍ¥½¸°A…ÍÍÝ½É‘I•Í•ÑQ½­•¸¤è(€€€€€€€œ¹‘ˆ¹•á•ÕÑ”¡‘•±•Ñ”¡µ½‘•°¤¹Ý¡•É”¡µ½‘•°¹ÕÍ•É}¥€ôôÕÍ•É}¥¤¤(€€€œ¹‘ˆ¹‘•±•Ñ”¡ÕÍ•È¤(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°…Ñ¥½¸ô‰ÕÍ•È¹‘•±•Ñ”ˆ°Ñ…É•Ñ}ÑåÁ”ô‰Á±…Ñ™½Éµ}ÕÍ•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÕÍ•É}¥°…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰•µ…¥°ˆè•µ…¥°°€‰‰ÕÍ¥¹•ÍÍ}¥‘Ìˆèµ•µ‰•ÉÍ¡¥Á}¥‘Íô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸€ˆˆ°€ÈÀÐ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½ÕÍ•ÉÌ¼ñÕÍ•É}¥ø½Í•¹µÍ•ÑÕÀµ•µ…¥°ˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜É•Í•¹‘}Í•ÑÕÁ}•µ…¥°¡ÕÍ•É}¥èÍÑÈ¤è(€€€ÕÍ•È€ôœ¹‘ˆ¹•Ð¡A±…Ñ™½ÉµUÍ•È°ÕÍ•É}¥¤(€€€¥˜ÕÍ•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰UÍ•È¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ(€€€¥˜Á±…Ñ™½Éµ}É½±”¡ÕÍ•È¤€„ô€‰¹½¹”ˆ½È¹½ÐÕÍ•È¹µÕÍÑ}¡…¹•}Á…ÍÍÝ½Éè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Q¡¥Ì…½Õ¹Ð¥Ì¹½Ð…Ý…¥Ñ¥¹œÁ…ÍÍÝ½ÉÍ•ÑÕÀ¸‰ô¤°€ÐÀÀ(€€€¥˜¹½Ðµ…¥±•È¹½¹™¥ÕÉ• ¤½È¹½Ð½Ì¹•Ñ•¹Ø ‰AU	1%}	M}UI0ˆ°€ˆˆ¤¹ÍÑÉ¥À ¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰½Õ¹ÐÍ•ÑÕÀ•µ…¥°¥Ì¹½Ð½¹™¥ÕÉ•¸‰ô¤°€ÔÀÌ(€€€¥˜Á…ÍÍÝ½É‘}É•Í•Ð¹É…Ñ•}±¥µ¥Ñ•¡œ¹‘ˆ°ÕÍ•É}¥õÕÍ•È¹¥°É…Ý}¥Àõ±¥•¹Ñ}¥À ¤¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Q½¼µ…¹äÍ•ÑÕÀ•µ…¥±Ì¸QÉä……¥¸±…Ñ•È¸‰ô¤°€ÐÈä(€€€Ñ½­•¸€ôÁ…ÍÍÝ½É‘}É•Í•Ð¹¥ÍÍÕ”¡œ¹‘ˆ°ÕÍ•É}¥õÕÍ•È¹¥°É…Ý}¥Àõ±¥•¹Ñ}¥À ¤¤(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°…Ñ¥½¸ô‰ÕÍ•È¹Í•ÑÕÁ}•µ…¥°¹É•ÅÕ•ÍÐˆ°Ñ…É•Ñ}ÑåÁ”ô‰Á±…Ñ™½Éµ}ÕÍ•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÕÍ•È¹¥°…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰•µ…¥°ˆèÕÍ•È¹•µ…¥±ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€Í•¹Ð€ôµ…¥±•È¹Í•¹‘}…½Õ¹Ñ}Í•ÑÕÀ¡É•¥Á¥•¹ÐõÕÍ•È¹•µ…¥°°Ñ½­•¸õÑ½­•¸¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰Í•¹ÐˆèÍ•¹Ñô¤°€ÈÀÀ¥˜Í•¹Ð•±Í”€ÔÀÈ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½ÕÍ•ÉÌ¼ñÕÍ•É}¥ø½É•Í•ÐµÁ…ÍÍÝ½Éˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜É•Í•Ñ}ÕÍ•É}Á…ÍÍÝ½É¡ÕÍ•É}¥èÍÑÈ¤è(€€€ÕÍ•È€ôœ¹‘ˆ¹•Ð¡A±…Ñ™½ÉµUÍ•È°ÕÍ•É}¥¤(€€€¥˜ÕÍ•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰UÍ•È¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ(€€€¥˜Á±…Ñ™½Éµ}É½±”¡ÕÍ•È¤€„ô€‰¹½¹”ˆè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰=¹±ä±¥•¹ÐÕÍ•ÈÁ…ÍÍÝ½É‘Ì…¸‰”É•Í•Ð¡•É”¸‰ô¤°€ÐÀÀ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€¹•Ý}Á…ÍÍÝ½É€ôÁ…å±½…¹•Ð ‰Á…ÍÍÝ½Éˆ¤½È€ˆˆ(€€€ÍÑÉ•¹Ñ¡}•ÉÉ½È€ôÁ…ÍÍÝ½É‘Ì¹Ù…±¥‘…Ñ•}Á…ÍÍÝ½É‘}ÍÑÉ•¹Ñ ¡¹•Ý}Á…ÍÍÝ½É¤(€€€¥˜ÍÑÉ•¹Ñ¡}•ÉÉ½Èè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰Á…ÍÍÝ½ÉˆèÍÑÉ•¹Ñ¡}•ÉÉ½Éõô¤°€ÐÀÀ(€€€¥˜Á…ÍÍÝ½É‘Ì¹Ù•É¥™å}Á…ÍÍÝ½É¡ÕÍ•È¹Á…ÍÍÝ½É‘}¡…Í °¹•Ý}Á…ÍÍÝ½É¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰¡½½Í”„‘¥™™•É•¹ÐÑ•µÁ½É…ÉäÁ…ÍÍÝ½É¸‰ô¤°€ÐÀÀ((€€€ÕÍ•È¹Á…ÍÍÝ½É‘}¡…Í €ôÁ…ÍÍÝ½É‘Ì¹¡…Í¡}Á…ÍÍÝ½É¡¹•Ý}Á…ÍÍÝ½É¤(€€€ÕÍ•È¹µÕÍÑ}¡…¹•}Á…ÍÍÝ½É€ôQÉÕ”(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰ÕÍ•È¹Á…ÍÍÝ½É¹É•Í•Ðˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰Á±…Ñ™½Éµ}ÕÍ•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÕÍ•È¹¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰•µ…¥°ˆèÕÍ•È¹•µ…¥±ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€Í•ÍÍ¥½¹Ì¹É•Ù½­•}…±±}™½É}ÕÍ•È¡œ¹‘ˆ°ÕÍ•È¹¥¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡ÕÍ•É}‘Ñ¼¡ÕÍ•È¤¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½µ•µ‰•ÉÍ¡¥ÁÌˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜É•…Ñ•}µ•µ‰•ÉÍ¡¥À¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ¤è(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰	ÕÍ¥¹•ÍÌ¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€Á…å±½…€ôÉ•ÅÕ•ÍÐ¹•Ñ}©Í½¸¡Í¥±•¹ÐõQÉÕ”¤½Èíô(€€€ÕÍ•É}¥€ô€¡Á…å±½…¹•Ð ‰ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É½±”€ô€¡Á…å±½…¹•Ð ‰É½±”ˆ¤½È€‰½Ý¹•Èˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤((€€€¥˜É½±”¹½Ð¥¸Y1%}55	IM!%A}I=1Lè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Y…±¥‘…Ñ¥½¸™…¥±•¸ˆ°€‰™¥•±‘Ìˆèì‰É½±”ˆè€‰%¹Ù…±¥É½±”¸‰õô¤°€ÐÀÀ((€€€ÕÍ•È€ôœ¹‘ˆ¹•Ð¡A±…Ñ™½ÉµUÍ•È°ÕÍ•É}¥¤(€€€¥˜ÕÍ•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰UÍ•È¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€•á¥ÍÑ¥¹œ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¤¹Ý¡•É” (€€€€€€€€€€€	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¹‰ÕÍ¥¹•ÍÍ}¥€ôô‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€€€€	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¹ÕÍ•É}¥€ôôÕÍ•É}¥°(€€€€€€€€¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€¥˜•á¥ÍÑ¥¹œ¥Ì¹½Ð9½¹”è(€€€€€€€•á¥ÍÑ¥¹œ¹É½±”€ôÉ½±”(€€€€€€€µ•µ‰•ÉÍ¡¥À€ô•á¥ÍÑ¥¹œ(€€€•±Í”è(€€€€€€€µ•µ‰•ÉÍ¡¥À€ô	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¡‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°ÕÍ•É}¥õÕÍ•É}¥°É½±”õÉ½±”¤(€€€€€€€œ¹‘ˆ¹…‘¡µ•µ‰•ÉÍ¡¥À¤(€€€œ¹‘ˆ¹™±ÕÍ  ¤((€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰µ•µ‰•ÉÍ¡¥À¹ÕÁÍ•ÉÐˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÍ}µ•µ‰•ÉÍ¡¥Àˆ°(€€€€€€€Ñ…É•Ñ}¥õÍÑÈ¡µ•µ‰•ÉÍ¡¥À¹¥¤°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰ÕÍ•É}¥ˆèÕÍ•É}¥°€‰É½±”ˆèÉ½±•ô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡µ•µ‰•ÉÍ¡¥Á}‘Ñ¼¡µ•µ‰•ÉÍ¡¥À°ÕÍ•ÈõÕÍ•È¤¤°€ÈÀÄ(()…‘µ¥¹}‰À¹‘•±•Ñ” ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½µ•µ‰•ÉÍ¡¥ÁÌ¼ñ¥¹Ðéµ•µ‰•ÉÍ¡¥Á}¥øˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜‘•±•Ñ•}µ•µ‰•ÉÍ¡¥À¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ°µ•µ‰•ÉÍ¡¥Á}¥è¥¹Ð¤è(€€€µ•µ‰•ÉÍ¡¥À€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¤¹Ý¡•É” (€€€€€€€€€€€	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¹¥€ôôµ•µ‰•ÉÍ¡¥Á}¥°(€€€€€€€€€€€	ÕÍ¥¹•ÍÍ5•µ‰•ÉÍ¡¥À¹‰ÕÍ¥¹•ÍÍ}¥€ôô‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€¥˜µ•µ‰•ÉÍ¡¥À¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰5•µ‰•ÉÍ¡¥À¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰µ•µ‰•ÉÍ¡¥À¹É•µ½Ù”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰‰ÕÍ¥¹•ÍÍ}µ•µ‰•ÉÍ¡¥Àˆ°(€€€€€€€Ñ…É•Ñ}¥õÍÑÈ¡µ•µ‰•ÉÍ¡¥À¹¥¤°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰ÕÍ•É}¥ˆèµ•µ‰•ÉÍ¡¥À¹ÕÍ•É}¥°€‰É½±”ˆèµ•µ‰•ÉÍ¡¥À¹É½±•ô°(€€€€¤(€€€œ¹‘ˆ¹‘•±•Ñ”¡µ•µ‰•ÉÍ¡¥À¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸€ˆˆ°€ÈÀÐ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½ÕÍ•ÉÌ¼ñÕÍ•É}¥ø½É•Ù½­”µÍ•ÍÍ¥½¹Ìˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜É•Ù½­•}ÕÍ•É}Í•ÍÍ¥½¹Ì¡ÕÍ•É}¥èÍÑÈ¤è(€€€ÕÍ•È€ôœ¹‘ˆ¹•Ð¡A±…Ñ™½ÉµUÍ•È°ÕÍ•É}¥¤(€€€¥˜ÕÍ•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰UÍ•È¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ((€€€½Õ¹Ð€ôÍ•ÍÍ¥½¹Ì¹É•Ù½­•}…±±}™½É}ÕÍ•È¡œ¹‘ˆ°ÕÍ•É}¥¤(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰ÕÍ•È¹Í•ÍÍ¥½¹Ì¹É•Ù½­”ˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰Á±…Ñ™½Éµ}ÕÍ•Èˆ°(€€€€€€€Ñ…É•Ñ}¥õÕÍ•É}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰É•Ù½­•ˆè½Õ¹Ñô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰É•Ù½­•ˆè½Õ¹Ñô¤°€ÈÀÀ(()…‘µ¥¹}‰À¹Á½ÍÐ ˆ½‰ÕÍ¥¹•ÍÍ•Ì¼ñ‰ÕÍ¥¹•ÍÍ}¥ø½µ¥ÍÍ•µ…±±Ì¼ñ¥¹Ðé•Ù•¹Ñ}¥ø½É•ÑÉäˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}…‘µ¥¸)‘•˜É•ÑÉå}µ¥ÍÍ•‘}…±°¡‰ÕÍ¥¹•ÍÍ}¥èÍÑÈ°•Ù•¹Ñ}¥è¥¹Ð¤è(€€€•Ù•¹Ð€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡5¥ÍÍ•‘…±±Ù•¹Ð¤¹Ý¡•É” (€€€€€€€€€€€5¥ÍÍ•‘…±±Ù•¹Ð¹¥€ôô•Ù•¹Ñ}¥°(€€€€€€€€€€€5¥ÍÍ•‘…±±Ù•¹Ð¹‰ÕÍ¥¹•ÍÍ}¥€ôô‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€‰ÕÍ¥¹•ÍÌ€ôœ¹‘ˆ¹•Ð¡	ÕÍ¥¹•ÍÌ°‰ÕÍ¥¹•ÍÍ}¥¤(€€€¥˜•Ù•¹Ð¥Ì9½¹”½È‰ÕÍ¥¹•ÍÌ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰5¥ÍÍ•µ…±°•Ù•¹Ð¹½Ð™½Õ¹¸‰ô¤°€ÐÀÐ(€€€¥˜•Ù•¹Ð¹‘•¥Í¥½¸€„ô€‰Í•¹‘}™…¥±•ˆè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰=¹±ä™…¥±•Í•¹…ÑÑ•µÁÑÌ…¸‰”É•ÑÉ¥•¸‰ô¤°€ÐÀä((€€€¹Õµ‰•È€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¤¹Ý¡•É” (€€€€€€€€€€€	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¹‰ÕÍ¥¹•ÍÍ}¥€ôô‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€€€€	ÕÍ¥¹•ÍÍA¡½¹•9Õµ‰•È¹Á¡½¹”€ôô•Ù•¹Ð¹ÑÝ¥±¥½}¹Õµ‰•È°(€€€€€€€€¤(€€€€¤¹Í…±…É}½¹•}½É}¹½¹” ¤(€€€¥˜¹Õµ‰•È¥Ì¹½Ð9½¹”è(€€€€€€€Í•ÑÑ¥¹Ì€ô•™™•Ñ¥Ù•}Í•ÑÑ¥¹Ì¡‰ÕÍ¥¹•ÍÌ°¹Õµ‰•È¤(€€€€€€€ÉÕ±•Ì€ôÍ•ÑÑ¥¹Ì¹•Ð ‰µ¥ÍÍ•‘}…±±Ìˆ¤½È9½¹”(€€€•±¥˜‰ÕÍ¥¹•ÍÍ}¥€ôô1e}	UM%9MM}%è(€€€€€€€ÉÕ±•Ì€ô9½¹”(€€€•±Í”è(€€€€€€€ÉÕ±•Ì€ô€¡‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì½Èíô¤¹•Ð ‰µ¥ÍÍ•‘}…±±Ìˆ¤½È9½¹”((€€€¥Í}‘•µ¼€ô‰½½°  ¡‰ÕÍ¥¹•ÍÌ¹Í•ÑÑ¥¹Ì½Èíô¤¹•Ð ‰¥¹Ñ…­”ˆ¤½Èíô¤¹•Ð ‰‘•µ½}‘¥Í±…¥µ•Èˆ¤¤(€€€½ÕÑ½µ”€ôµ¥ÍÍ•‘}…±±}Í•ÉÙ¥”¹ÁÉ½•ÍÍ}µ¥ÍÍ•‘}…±° (€€€€€€€œ¹‘ˆ°(€€€€€€€…±±•É}Á¡½¹”õ•Ù•¹Ð¹…±±•É}Á¡½¹”°(€€€€€€€ÑÝ¥±¥½}¹Õµ‰•Èõ•Ù•¹Ð¹ÑÝ¥±¥½}¹Õµ‰•È°(€€€€€€€™½ÉÝ…É‘•‘}™É½´õ•Ù•¹Ð¹™½ÉÝ…É‘•‘}™É½´½È€ˆˆ°(€€€€€€€…±±}Í¥õ•Ù•¹Ð¹…±±}Í¥°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¹…µ”õ‰ÕÍ¥¹•ÍÌ¹¹…µ”°(€€€€€€€¥Í}‘•µ¼õ¥Í}‘•µ¼°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€ÉÕ±•ÌõÉÕ±•Ì°(€€€€€€€…±±}ÍÑ…ÑÕÌõ•Ù•¹Ð¹…±±}ÍÑ…ÑÕÌ½È€ˆˆ°(€€€€€€€…±±}‘ÕÉ…Ñ¥½¹}Í•½¹‘Ìõ•Ù•¹Ð¹…±±}‘ÕÉ…Ñ¥½¹}Í•½¹‘Ì°(€€€€¤(€€€É•½É‘}…Õ‘¥Ñ}•Ù•¹Ð (€€€€€€€œ¹‘ˆ°(€€€€€€€…Ñ¥½¸ô‰µ¥ÍÍ•‘}…±°¹É•ÑÉäˆ°(€€€€€€€Ñ…É•Ñ}ÑåÁ”ô‰µ¥ÍÍ•‘}…±±}•Ù•¹Ðˆ°(€€€€€€€Ñ…É•Ñ}¥õÍÑÈ¡•Ù•¹Ð¹¥¤°(€€€€€€€‰ÕÍ¥¹•ÍÍ}¥õ‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€…Ñ½É}ÕÍ•É}¥õœ¹ÕÉÉ•¹Ñ}ÕÍ•È¹¥°(€€€€€€€‘•Ñ…¥±Ìõì‰É•ÍÕ±Ðˆè½ÕÑ½µ”¹‘•¥Í¥½¸¹É•…Í½¸°€‰Í•¹Ðˆè½ÕÑ½µ”¹µ•ÍÍ…•}Í•¹Ñô°(€€€€¤(€€€œ¹‘ˆ¹½µµ¥Ð ¤(€€€œ¹‘ˆ¹É•™É•Í ¡•Ù•¹Ð¤(€€€ÍÑ…ÑÕÌ€ô€ÈÀÀ¥˜½ÕÑ½µ”¹µ•ÍÍ…•}Í•¹Ð•±Í”€ÐÀä(€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì‰•Ù•¹Ðˆèµ¥ÍÍ•‘}…±±}‘Ñ¼¡•Ù•¹Ð¤°€‰É•ÍÕ±Ðˆè½ÕÑ½µ”¹‘•¥Í¥½¸¹É•…Í½¹ô(€€€€¤°ÍÑ…ÑÕÌ(()…‘µ¥¹}‰À¹•Ð ˆ½…Õ‘¥Ðµ•Ù•¹ÑÌˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜±¥ÍÑ}…Õ‘¥Ñ}•Ù•¹ÑÌ ¤è(€€€Á…”°Í¥é”€ô}Á…•}…ÉÌ ¤(€€€‰ÕÍ¥¹•ÍÍ}¥€ô€¡É•ÅÕ•ÍÐ¹…ÉÌ¹•Ð ‰‰ÕÍ¥¹•ÍÍ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤((€€€ÅÕ•Éä€ôÍ•±•Ð¡Õ‘¥ÑÙ•¹Ð¤(€€€¥˜‰ÕÍ¥¹•ÍÍ}¥è(€€€€€€€ÅÕ•Éä€ôÅÕ•Éä¹Ý¡•É”¡Õ‘¥ÑÙ•¹Ð¹‰ÕÍ¥¹•ÍÍ}¥€ôô‰ÕÍ¥¹•ÍÍ}¥¤((€€€Ñ½Ñ…°€ôœ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤¹Í•±•Ñ}™É½´¡ÅÕ•Éä¹ÍÕ‰ÅÕ•Éä ¤¤¤¹Í…±…É}½¹” ¤(€€€É½ÝÌ€ô±¥ÍÐ (€€€€€€€œ¹‘ˆ¹•á•ÕÑ” (€€€€€€€€€€€ÅÕ•Éä¹½É‘•É}‰ä¡Õ‘¥ÑÙ•¹Ð¹É•…Ñ•‘}…Ð¹‘•ÍŒ ¤°Õ‘¥ÑÙ•¹Ð¹¥¹‘•ÍŒ ¤¤(€€€€€€€€€€€€¹½™™Í•Ð ¡Á…”€´€Ä¤€¨Í¥é”¤(€€€€€€€€€€€€¹±¥µ¥Ð¡Í¥é”¤(€€€€€€€€¤¹Í…±…ÉÌ ¤(€€€€¤(€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì(€€€€€€€€€€€€‰¥Ñ•µÌˆèm…Õ‘¥Ñ}•Ù•¹Ñ}‘Ñ¼¡”¤™½È”¥¸É½ÝÍt°(€€€€€€€€€€€€‰Ñ½Ñ…°ˆèÑ½Ñ…°°(€€€€€€€€€€€€‰Á…”ˆèÁ…”°(€€€€€€€€€€€€‰Á…•}Í¥é”ˆèÍ¥é”°(€€€€€€€ô(€€€€¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½½Ù•ÉÙ¥•Üˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}½Ù•ÉÙ¥•Ü ¤è(€€€€ˆˆ‰=¹±äµ•ÑÉ¥Ì‰…­•‰äÉ•…°Ñ…‰±•Ì¸9¼™…‰É¥…Ñ•¹Õµ‰•ÉÌ¸ˆˆˆ(€€€…Ñ¥Ù•}‰ÕÍ¥¹•ÍÍ}É½ÝÌ€ô±¥ÍÐ (€€€€€€€œ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡	ÕÍ¥¹•ÍÌ¤¹Ý¡•É”¡	ÕÍ¥¹•ÍÌ¹ÍÑ…ÑÕÌ€ôô€‰…Ñ¥Ù”ˆ¤¤¹Í…±…ÉÌ ¤(€€€€¤(€€€Ñ½Ñ…±}‰ÕÍ¥¹•ÍÍ•Ì€ô±•¸¡…Ñ¥Ù•}‰ÕÍ¥¹•ÍÍ}É½ÝÌ¤(€€€Ñ½Ñ…±}±•…‘Ì€ôœ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤¹Í•±•Ñ}™É½´¡1•…¤¤¹Í…±…É}½¹” ¤(€€€Ñ½Ñ…±}µ¥ÍÍ•€ôœ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤¹Í•±•Ñ}™É½´¡5¥ÍÍ•‘…±±Ù•¹Ð¤¤¹Í…±…É}½¹” ¤(€€€Ñ½Ñ…±}ÕÍ•ÉÌ€ôœ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤¹Í•±•Ñ}™É½´¡A±…Ñ™½ÉµUÍ•È¤¤¹Í…±…É}½¹” ¤(€€€Á•¹‘¥¹}…ÁÁ½¥¹Ñµ•¹ÑÌ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤(€€€€€€€€¹Í•±•Ñ}™É½´¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¤(€€€€€€€€¹Ý¡•É”¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¹ÍÑ…ÑÕÌ¹¥¹|¡ì‰Á•¹‘¥¹œˆ°€‰Íå¹}™…¥±•‰ô¤¤(€€€€¤¹Í…±…É}½¹” ¤(€€€½¹¹•Ñ•‘}…±•¹‘…ÉÌ€ôÍÕ´ (€€€€€€€€Ä™½È‰ÕÍ¥¹•ÍÌ¥¸…Ñ¥Ù•}‰ÕÍ¥¹•ÍÍ}É½ÝÌ(€€€€€€€¥˜…±•¹‘…É}Í•ÉÙ¥”¹½¹¹•Ñ¥½¹}‘Ñ¼¡‰ÕÍ¥¹•ÍÌ¥l‰½¹¹•Ñ•‰t(€€€€¤(€€€…±•¹‘…É}™…¥±ÕÉ•Ì€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤(€€€€€€€€¹Í•±•Ñ}™É½´¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¤(€€€€€€€€¹Ý¡•É”¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¹ÍÑ…ÑÕÌ€ôô€‰Íå¹}™…¥±•ˆ¤(€€€€¤¹Í…±…É}½¹” ¤(€€€¥˜½¹¹•Ñ•‘}…±•¹‘…ÉÌ€ôô€Àè(€€€€€€€…±•¹‘…É}ÍÑ…ÑÕÌ€ô€‰¹½Ñ}½¹™¥ÕÉ•ˆ(€€€•±¥˜½¹¹•Ñ•‘}…±•¹‘…ÉÌ€ðÑ½Ñ…±}‰ÕÍ¥¹•ÍÍ•Ì½È…±•¹‘…É}™…¥±ÕÉ•Ìè(€€€€€€€…±•¹‘…É}ÍÑ…ÑÕÌ€ô€‰‘•É…‘•ˆ(€€€•±Í”è(€€€€€€€…±•¹‘…É}ÍÑ…ÑÕÌ€ô€‰½Á•É…Ñ¥½¹…°ˆ((€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì(€€€€€€€€€€€€‰…Ñ¥Ù•}‰ÕÍ¥¹•ÍÍ•ÌˆèÑ½Ñ…±}‰ÕÍ¥¹•ÍÍ•Ì°(€€€€€€€€€€€€‰±•…‘ÌˆèÑ½Ñ…±}±•…‘Ì°(€€€€€€€€€€€€‰µ¥ÍÍ•‘}…±±ÌˆèÑ½Ñ…±}µ¥ÍÍ•°(€€€€€€€€€€€€‰ÕÍ•ÉÌˆèÑ½Ñ…±}ÕÍ•ÉÌ°(€€€€€€€€€€€€‰…±•¹‘…Èˆèì(€€€€€€€€€€€€€€€€‰½¹¹•Ñ•‘}‰ÕÍ¥¹•ÍÍ•Ìˆè½¹¹•Ñ•‘}…±•¹‘…ÉÌ°(€€€€€€€€€€€€€€€€‰Á•¹‘¥¹}…ÁÁ½¥¹Ñµ•¹ÑÌˆèÁ•¹‘¥¹}…ÁÁ½¥¹Ñµ•¹ÑÌ°(€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè…±•¹‘…É}ÍÑ…ÑÕÌ°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰Õ¹…Ù…¥±…‰±”ˆè€ (€€€€€€€€€€€€€€€€¡mt¥˜Ý•‰Í¥Ñ•}µ½¹¥Ñ½É¥¹œ¹¥Í}½¹™¥ÕÉ• ¤•±Í”l(€€€€€€€€€€€€€€€€€€€ì‰­•äˆè€‰Ý•‰Í¥Ñ•Í}½¹±¥¹”ˆ°€‰É•…Í½¸ˆè€‰‘UAQ%5I=	=Q}A%}-d½¸I•¹‘•È¸‰ô(€€€€€€€€€€€€€€€t¤(€€€€€€€€€€€€€€€€¬€¡mt¥˜ÑÝ¥±¥½}ÕÍ…”¹¥Í}½¹™¥ÕÉ• ¤•±Í”l(€€€€€€€€€€€€€€€€€€€ì‰­•äˆè€‰ÍµÍ}ÕÍ…”ˆ°€‰É•…Í½¸ˆè€‰QÝ¥±¥¼ÕÍ…”É•‘•¹Ñ¥…±Ì…É”¹½Ð½¹™¥ÕÉ•¸‰ô(€€€€€€€€€€€€€€€t¤(€€€€€€€€€€€€€€€€¬mì‰­•äˆè€‰…Ñ¥Ù•}…±•ÉÑÌˆ°€‰É•…Í½¸ˆè€‰±•ÉÑÌ…ÉÉ¥Ù”¥¸A¡…Í”€Ì¸‰õt(€€€€€€€€€€€€¤°(€€€€€€€ô(€€€€¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½…±•¹‘…Èˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}…±•¹‘…È ¤è(€€€‰ÕÍ¥¹•ÍÍ•Ì€ô±¥ÍÐ¡œ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡	ÕÍ¥¹•ÍÌ¤¹½É‘•É}‰ä¡	ÕÍ¥¹•ÍÌ¹¹…µ”¤¤¹Í…±…ÉÌ ¤¤(€€€½¹¹•Ñ¥½¹}É½ÝÌ€ôl(€€€€€€€ì(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÌˆèì‰¥ˆè‰ÕÍ¥¹•ÍÌ¹¥°€‰¹…µ”ˆè‰ÕÍ¥¹•ÍÌ¹¹…µ”°€‰Í±Õœˆè‰ÕÍ¥¹•ÍÌ¹Í±Õô°(€€€€€€€€€€€€‰½¹¹•Ñ¥½¸ˆè…±•¹‘…É}Í•ÉÙ¥”¹½¹¹•Ñ¥½¹}‘Ñ¼¡‰ÕÍ¥¹•ÍÌ¤°(€€€€€€€ô(€€€€€€€™½È‰ÕÍ¥¹•ÍÌ¥¸‰ÕÍ¥¹•ÍÍ•Ì(€€€t(€€€É½ÝÌ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ°	ÕÍ¥¹•ÍÌ¤(€€€€€€€€¹©½¥¸¡	ÕÍ¥¹•ÍÌ°ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¹‰ÕÍ¥¹•ÍÍ}¥€ôô	ÕÍ¥¹•ÍÌ¹¥¤(€€€€€€€€¹½É‘•É}‰ä¡ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¹É•…Ñ•‘}…Ð¹‘•ÍŒ ¤°ÁÁ½¥¹Ñµ•¹ÑI•ÅÕ•ÍÐ¹¥¹‘•ÍŒ ¤¤(€€€€€€€€¹±¥µ¥Ð ÄÀÀ¤(€€€€¤¹…±° ¤(€€€¥Ñ•µÌ€ômt(€€€™½È…ÁÁ½¥¹Ñµ•¹Ð°‰ÕÍ¥¹•ÍÌ¥¸É½ÝÌè(€€€€€€€¥Ñ•´€ô…ÁÁ½¥¹Ñµ•¹Ñ}‘Ñ¼¡…ÁÁ½¥¹Ñµ•¹Ð¤(€€€€€€€¥Ñ•µl‰‰ÕÍ¥¹•ÍÌ‰t€ôì‰¥ˆè‰ÕÍ¥¹•ÍÌ¹¥°€‰¹…µ”ˆè‰ÕÍ¥¹•ÍÌ¹¹…µ”°€‰Í±Õœˆè‰ÕÍ¥¹•ÍÌ¹Í±Õô(€€€€€€€¥Ñ•µÌ¹…ÁÁ•¹¡¥Ñ•´¤(€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì(€€€€€€€€€€€€‰µ•ÑÉ¥Ìˆèì(€€€€€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÍ•Ìˆè±•¸¡‰ÕÍ¥¹•ÍÍ•Ì¤°(€€€€€€€€€€€€€€€€‰½¹¹•Ñ•ˆèÍÕ´ Ä™½ÈÉ½Ü¥¸½¹¹•Ñ¥½¹}É½ÝÌ¥˜É½Ýl‰½¹¹•Ñ¥½¸‰ul‰½¹¹•Ñ•‰t¤°(€€€€€€€€€€€€€€€€‰Á•¹‘¥¹œˆèÍÕ´ Ä™½È¥Ñ•´¥¸¥Ñ•µÌ¥˜¥Ñ•µl‰ÍÑ…ÑÕÌ‰t¥¸ì‰Á•¹‘¥¹œˆ°€‰Íå¹}™…¥±•‰ô¤°(€€€€€€€€€€€€€€€€‰Í¡•‘Õ±•ˆèÍÕ´ Ä™½È¥Ñ•´¥¸¥Ñ•µÌ¥˜¥Ñ•µl‰ÍÑ…ÑÕÌ‰t€ôô€‰Í¡•‘Õ±•ˆ¤°(€€€€€€€€€€€€€€€€‰Íå¹}™…¥±•ˆèÍÕ´ Ä™½È¥Ñ•´¥¸¥Ñ•µÌ¥˜¥Ñ•µl‰ÍÑ…ÑÕÌ‰t€ôô€‰Íå¹}™…¥±•ˆ¤°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰½¹¹•Ñ¥½¹Ìˆè½¹¹•Ñ¥½¹}É½ÝÌ°(€€€€€€€€€€€€‰¥Ñ•µÌˆè¥Ñ•µÌ°(€€€€€€€ô(€€€€¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½½¹Ù•ÉÍ…Ñ¥½¹Ìˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}½¹Ù•ÉÍ…Ñ¥½¹Ì ¤è(€€€Á…”°Í¥é”€ô}Á…•}…ÉÌ ¤(€€€Í•…É €ô€¡É•ÅÕ•ÍÐ¹…ÉÌ¹•Ð ‰Äˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€ÍÑ…Ñ”€ô€¡É•ÅÕ•ÍÐ¹…ÉÌ¹•Ð ‰ÍÑ…Ñ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€Ù…±¥‘}ÍÑ…Ñ•Ì€ôì‰…Ý…¥Ñ¥¹}ÁÉ½™¥±•}Í•±•Ñ¥½¸ˆ°€‰¥¹}ÁÉ½É•ÍÌˆ°€‰½µÁ±•Ñ•ˆ°€‰Ñ•Éµ¥¹…Ñ•‰ô(€€€¥˜ÍÑ…Ñ”…¹ÍÑ…Ñ”¹½Ð¥¸Ù…±¥‘}ÍÑ…Ñ•Ìè(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰%¹Ù…±¥½¹Ù•ÉÍ…Ñ¥½¸ÍÑ…Ñ”¸‰ô¤°€ÐÀÀ((€€€ÅÕ•Éä€ô€ (€€€€€€€Í•±•Ð¡½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸°	ÕÍ¥¹•ÍÌ¤(€€€€€€€€¹©½¥¸¡	ÕÍ¥¹•ÍÌ°½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸¹‰ÕÍ¥¹•ÍÍ}¥€ôô	ÕÍ¥¹•ÍÌ¹¥¤(€€€€¤(€€€¥˜ÍÑ…Ñ”è(€€€€€€€ÅÕ•Éä€ôÅÕ•Éä¹Ý¡•É”¡½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸¹ÍÑ…Ñ”€ôôÍÑ…Ñ”¤(€€€¥˜Í•…É è(€€€€€€€Á…ÑÑ•É¸€ô˜ˆ•íÍ•…É¡ô”ˆ(€€€€€€€ÅÕ•Éä€ôÅÕ•Éä¹Ý¡•É” (€€€€€€€€€€€½É| (€€€€€€€€€€€€€€€™Õ¹Œ¹±½Ý•È¡½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸¹Á¡½¹”¤¹±¥­”¡Á…ÑÑ•É¸¤°(€€€€€€€€€€€€€€€™Õ¹Œ¹±½Ý•È¡	ÕÍ¥¹•ÍÌ¹¹…µ”¤¹±¥­”¡Á…ÑÑ•É¸¤°(€€€€€€€€€€€€€€€™Õ¹Œ¹±½Ý•È¡…ÍÐ¡½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸¹™¥•±‘Ì°MÑÉ¥¹œ¤¤¹±¥­”¡Á…ÑÑ•É¸¤°(€€€€€€€€€€€€¤(€€€€€€€€¤((€€€Ñ½Ñ…°€ôœ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤¹Í•±•Ñ}™É½´¡ÅÕ•Éä¹ÍÕ‰ÅÕ•Éä ¤¤¤¹Í…±…É}½¹” ¤(€€€É½ÝÌ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€ÅÕ•Éä¹½É‘•É}‰ä¡½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸¹ÕÁ‘…Ñ•‘}…Ð¹‘•ÍŒ ¤°½¹Ù•ÉÍ…Ñ¥½¹M•ÍÍ¥½¸¹¥¹‘•ÍŒ ¤¤(€€€€€€€€¹½™™Í•Ð ¡Á…”€´€Ä¤€¨Í¥é”¤(€€€€€€€€¹±¥µ¥Ð¡Í¥é”¤(€€€€¤¹…±° ¤(€€€¥Ñ•µÌ€ômt(€€€™½ÈÍ•ÍÍ¥½¸°‰ÕÍ¥¹•ÍÌ¥¸É½ÝÌè(€€€€€€€¥Ñ•´€ô½¹Ù•ÉÍ…Ñ¥½¹}ÍÕµµ…Éå}‘Ñ¼¡Í•ÍÍ¥½¸¤(€€€€€€€¥Ñ•µl‰‰ÕÍ¥¹•ÍÌ‰t€ôì‰¥ˆè‰ÕÍ¥¹•ÍÌ¹¥°€‰¹…µ”ˆè‰ÕÍ¥¹•ÍÌ¹¹…µ”°€‰Í±Õœˆè‰ÕÍ¥¹•ÍÌ¹Í±Õô(€€€€€€€¥Ñ•µÌ¹…ÁÁ•¹¡¥Ñ•´¤(€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì(€€€€€€€€€€€€‰¥Ñ•µÌˆè¥Ñ•µÌ°(€€€€€€€€€€€€‰Ñ½Ñ…°ˆèÑ½Ñ…°°(€€€€€€€€€€€€‰Á…”ˆèÁ…”°(€€€€€€€€€€€€‰Á…•}Í¥é”ˆèÍ¥é”°(€€€€€€€€€€€€‰ÍÑ…Ñ•ÌˆèÍ½ÉÑ•¡Ù…±¥‘}ÍÑ…Ñ•Ì¤°(€€€€€€€ô(€€€€¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½‘•±¥Ù•Éäˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}‘•±¥Ù•Éä ¤è(€€€É½ÝÌ€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡5¥ÍÍ•‘…±±Ù•¹Ð°	ÕÍ¥¹•ÍÌ¤(€€€€€€€€¹©½¥¸¡	ÕÍ¥¹•ÍÌ°5¥ÍÍ•‘…±±Ù•¹Ð¹‰ÕÍ¥¹•ÍÍ}¥€ôô	ÕÍ¥¹•ÍÌ¹¥¤(€€€€€€€€¹½É‘•É}‰ä¡5¥ÍÍ•‘…±±Ù•¹Ð¹É•…Ñ•‘}…Ð¹‘•ÍŒ ¤°5¥ÍÍ•‘…±±Ù•¹Ð¹¥¹‘•ÍŒ ¤¤(€€€€€€€€¹±¥µ¥Ð ÄÀÀ¤(€€€€¤¹…±° ¤(€€€Ñ½Ñ…°€ôœ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤¹Í•±•Ñ}™É½´¡5¥ÍÍ•‘…±±Ù•¹Ð¤¤¹Í…±…É}½¹” ¤(€€€ÍÕ‰µ¥ÑÑ•€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤(€€€€€€€€¹Í•±•Ñ}™É½´¡5¥ÍÍ•‘…±±Ù•¹Ð¤(€€€€€€€€¹Ý¡•É”¡5¥ÍÍ•‘…±±Ù•¹Ð¹µ•ÍÍ…•}Í¥¹¥Í}¹½Ð¡9½¹”¤¤(€€€€¤¹Í…±…É}½¹” ¤(€€€‘•±¥Ù•É•€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤(€€€€€€€€¹Í•±•Ñ}™É½´¡5¥ÍÍ•‘…±±Ù•¹Ð¤(€€€€€€€€¹Ý¡•É”¡5¥ÍÍ•‘…±±Ù•¹Ð¹‘•±¥Ù•Éå}ÍÑ…ÑÕÌ€ôô€‰‘•±¥Ù•É•ˆ¤(€€€€¤¹Í…±…É}½¹” ¤(€€€™…¥±•€ôœ¹‘ˆ¹•á•ÕÑ” (€€€€€€€Í•±•Ð¡™Õ¹Œ¹½Õ¹Ð ¤¤(€€€€€€€€¹Í•±•Ñ}™É½´¡5¥ÍÍ•‘…±±Ù•¹Ð¤(€€€€€€€€¹Ý¡•É”¡5¥ÍÍ•‘…±±Ù•¹Ð¹‘•±¥Ù•Éå}ÍÑ…ÑÕÌ¹¥¹|¡ì‰™…¥±•ˆ°€‰Õ¹‘•±¥Ù•É•‰ô¤¤(€€€€¤¹Í…±…É}½¹” ¤(€€€¥Ñ•µÌ€ômt(€€€™½È•Ù•¹Ð°‰ÕÍ¥¹•ÍÌ¥¸É½ÝÌè(€€€€€€€¥Ñ•´€ôµ¥ÍÍ•‘}…±±}‘Ñ¼¡•Ù•¹Ð¤(€€€€€€€¥Ñ•µl‰‰ÕÍ¥¹•ÍÌ‰t€ôì‰¥ˆè‰ÕÍ¥¹•ÍÌ¹¥°€‰¹…µ”ˆè‰ÕÍ¥¹•ÍÌ¹¹…µ•ô(€€€€€€€¥Ñ•µl‰‘•±¥Ù•Éå}ÍÑ…ÑÕÌ‰t€ô•Ù•¹Ð¹‘•±¥Ù•Éå}ÍÑ…ÑÕÌ½È€ (€€€€€€€€€€€€‰ÅÕ•Õ•ˆ¥˜•Ù•¹Ð¹µ•ÍÍ…•}Í¥•±Í”€‰¹½Ñ}Í•¹Ðˆ(€€€€€€€€¤(€€€€€€€¥Ñ•µÌ¹…ÁÁ•¹¡¥Ñ•´¤(€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì(€€€€€€€€€€€€‰µ•ÑÉ¥Ìˆèì(€€€€€€€€€€€€€€€€‰•Ù•¹ÑÌˆèÑ½Ñ…°°(€€€€€€€€€€€€€€€€‰ÍÕ‰µ¥ÑÑ•ˆèÍÕ‰µ¥ÑÑ•°(€€€€€€€€€€€€€€€€‰‘•±¥Ù•É•ˆè‘•±¥Ù•É•°(€€€€€€€€€€€€€€€€‰™…¥±•ˆè™…¥±•°(€€€€€€€€€€€€€€€€‰¹½Ñ}Í•¹ÐˆèÑ½Ñ…°€´ÍÕ‰µ¥ÑÑ•°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰¥Ñ•µÌˆè¥Ñ•µÌ°(€€€€€€€€€€€€‰¹½Ñ¥”ˆè€ (€€€€€€€€€€€€€€€€‰EÕ•Õ•…¹Í•¹Ð…É”ÁÉ½Ù¥‘•ÈÁÉ½É•ÍÌÍÑ…Ñ•Ì¸=¹±ä‘•±¥Ù•É•½¹™¥ÉµÌÉ••¥ÁÐì€ˆ(€€€€€€€€€€€€€€€€‰½±‘•È•Ù•¹ÑÌµ…äÉ•µ…¥¸ÅÕ•Õ•¥˜¹¼…±±‰…¬Ý…Ì½¹™¥ÕÉ•¸ˆ(€€€€€€€€€€€€¤°(€€€€€€€ô(€€€€¤°€ÈÀÀ(()…‘µ¥¹}‰À¹•Ð ˆ½Ý•‰¡½½­Ìˆ¤)É•ÅÕ¥É•}Á±…Ñ™½Éµ}½Á•É…Ñ½È)‘•˜Á±…Ñ™½Éµ}Ý•‰¡½½­Ì ¤è(€€€‰ÕÍ¥¹•ÍÍ•Ì€ôì(€€€€€€€‰ÕÍ¥¹•ÍÌ¹¥è‰ÕÍ¥¹•ÍÌ¹¹…µ”(€€€€€€€™½È‰ÕÍ¥¹•ÍÌ¥¸œ¹‘ˆ¹•á•ÕÑ”¡Í•±•Ð¡	ÕÍ¥¹•ÍÌ¤¤¹Í…±…ÉÌ ¤(€€€ô(€€€ÍµÍ}É½ÝÌ€ô±¥ÍÐ (€€€€€€€œ¹‘ˆ¹•á•ÕÑ” (€€€€€€€€€€€Í•±•Ð¡AÉ½•ÍÍ•‘5•ÍÍ…”¤(€€€€€€€€€€€€¹½É‘•É}‰ä¡AÉ½•ÍÍ•‘5•ÍÍ…”¹É•…Ñ•‘}…Ð¹‘•ÍŒ ¤°AÉ½•ÍÍ•‘5•ÍÍ…”¹¥¹‘•ÍŒ ¤¤(€€€€€€€€€€€€¹±¥µ¥Ð ÄÀÀ¤(€€€€€€€€¤¹Í…±…ÉÌ ¤(€€€€¤(€€€Ù½¥•}É½ÝÌ€ô±¥ÍÐ (€€€€€€€œ¹‘ˆ¹•á•ÕÑ” (€€€€€€€€€€€Í•±•Ð¡5¥ÍÍ•‘…±±Ù•¹Ð¤(€€€€€€€€€€€€¹½É‘•É}‰ä¡5¥ÍÍ•‘…±±Ù•¹Ð¹É•…Ñ•‘}…Ð¹‘•ÍŒ ¤°5¥ÍÍ•‘…±±Ù•¹Ð¹¥¹‘•ÍŒ ¤¤(€€€€€€€€€€€€¹±¥µ¥Ð ÄÀÀ¤(€€€€€€€€¤¹Í…±…ÉÌ ¤(€€€€¤(€€€¥Ñ•µÌ€ôl(€€€€€€€ì(€€€€€€€€€€€€‰¥ˆè˜‰ÍµÌµíÉ½Ü¹¥‘ôˆ°(€€€€€€€€€€€€‰­¥¹ˆè€‰%¹‰½Õ¹M5Lˆ°(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÍ}¥ˆèÉ½Ü¹‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÍ}¹…µ”ˆè‰ÕÍ¥¹•ÍÍ•Ì¹•Ð¡É½Ü¹‰ÕÍ¥¹•ÍÍ}¥°€‰1•…ä½ÈÕ¹…ÍÍ¥¹•ˆ¤°(€€€€€€€€€€€€‰•áÑ•É¹…±}¥ˆèÉ½Ü¹µ•ÍÍ…•}Í¥°(€€€€€€€€€€€€‰Á¡½¹”ˆèÉ½Ü¹Á¡½¹”°(€€€€€€€€€€€€‰½ÕÑ½µ”ˆè€‰ÁÉ½•ÍÍ•ˆ°(€€€€€€€€€€€€‰É•…Ñ•‘}…ÐˆèÉ½Ü¹É•…Ñ•‘}…Ð¹¥Í½™½Éµ…Ð ¤¥˜É½Ü¹É•…Ñ•‘}…Ð•±Í”9½¹”°(€€€€€€€ô(€€€€€€€™½ÈÉ½Ü¥¸ÍµÍ}É½ÝÌ(€€€t€¬l(€€€€€€€ì(€€€€€€€€€€€€‰¥ˆè˜‰Ù½¥”µíÉ½Ü¹¥‘ôˆ°(€€€€€€€€€€€€‰­¥¹ˆè€‰Y½¥”Ý•‰¡½½¬ˆ°(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÍ}¥ˆèÉ½Ü¹‰ÕÍ¥¹•ÍÍ}¥°(€€€€€€€€€€€€‰‰ÕÍ¥¹•ÍÍ}¹…µ”ˆè‰ÕÍ¥¹•ÍÍ•Ì¹•Ð¡É½Ü¹‰ÕÍ¥¹•ÍÍ}¥°€‰1•…ä½ÈÕ¹…ÍÍ¥¹•ˆ¤°(€€€€€€€€€€€€‰•áÑ•É¹…±}¥ˆèÉ½Ü¹…±±}Í¥°(€€€€€€€€€€€€‰Á¡½¹”ˆèÉ½Ü¹…±±•É}Á¡½¹”°(€€€€€€€€€€€€‰½ÕÑ½µ”ˆèÉ½Ü¹‘•¥Í¥½¸°(€€€€€€€€€€€€‰É•…Ñ•‘}…ÐˆèÉ½Ü¹É•…Ñ•‘}…Ð¹¥Í½™½Éµ…Ð ¤¥˜É½Ü¹É•…Ñ•‘}…Ð•±Í”9½¹”°(€€€€€€€ô(€€€€€€€™½ÈÉ½Ü¥¸Ù½¥•}É½ÝÌ(€€€t(€€€¥Ñ•µÌ¹Í½ÉÐ¡­•äõ±…µ‰‘„¥Ñ•´è€¡¥Ñ•µl‰É•…Ñ•‘}…Ð‰t½È€ˆˆ°¥Ñ•µl‰¥‰t¤°É•Ù•ÉÍ”õQÉÕ”¤(€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€ì(€€€€€€€€€€€€‰µ•ÑÉ¥Ìˆèì(€€€€€€€€€€€€€€€€‰¥¹‰½Õ¹‘}ÍµÌˆè±•¸¡ÍµÍ}É½ÝÌ¤°(€€€€€€€€€€€€€€€€‰Ù½¥•}•Ù•¹ÑÌˆè±•¸¡Ù½¥•}É½ÝÌ¤°(€€€€€€€€€€€€€€€€‰Ñ½Ñ…±}É••¹Ðˆèµ¥¸¡±•¸¡¥Ñ•µÌ¤°€ÄÀÀ¤°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰¥Ñ•µÌˆè¥Ñ•µÍlèÄÀÁt°(€€€€€€€€€€€€‰¹½Ñ¥”ˆè€‰Q¡¥Ì¥ÌÑ¡”Á•ÉÍ¥ÍÑ•¥‘•µÁ½Ñ•¹ä±•‘•È°¹½ÐÉ…ÜÉ•ÅÕ•ÍÐÁ…å±½…‘Ì¸ˆ°(€€€€€€€ô(€€€€¤°€ÈÀÀ(