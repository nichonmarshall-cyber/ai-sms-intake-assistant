import { useCallback, useEffect, useState } from "react";
import { Route, Routes, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import type {
  Business,
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

interface OverviewPayload {
  metrics: {
    total_leads: number;
    new_leads: number;
    open_conversations: number;
    missed_calls_handled: number;
  };
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
            <Stat label="Total leads" value={data.metrics.total_leads} icon="◈" />
            <Stat label="Missed calls handled" value={data.metrics.missed_calls_handled} icon="✆" />
          </div>

          <Card title="Coming with the next release">
            <ul style={{ color: "var(--ntx-muted)", paddingLeft: 18, margin: 0 }}>
              {data.unavailable.map((item) => (
                <li key={item.key} style={{ marginBottom: 6 }}>
                  <strong style={{ color: "var(--ntx-body)" }}>{item.key}</strong> — {item.reason}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}

function Settings({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [business, setBusiness] = useState<Business | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await api.get<{ business: Business }>(
        `/api/dashboard/businesses/${businessId}/settings`,
      );
      setBusiness(payload.business);
      setName(payload.business.name);
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
