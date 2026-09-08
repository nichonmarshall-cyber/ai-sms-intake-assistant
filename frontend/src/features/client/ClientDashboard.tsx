import { useCallback, useEffect, useState } from "react";
import { Route, Routes, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import type { Business, NavModule, UnavailableMetric } from "../../lib/types";
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  LockedModule,
  Loading,
  Stat,
  useFocusOnMount,
} from "../../components";

interface OverviewPayload {
  metrics: {
    total_leads: number;
    new_leads: number;
    missed_calls_handled: number;
  };
  unavailable: UnavailableMetric[];
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
