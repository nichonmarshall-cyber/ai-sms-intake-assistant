import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";
import { api } from "../../lib/api";

interface Monitor {
  id: string;
  name: string;
  url: string;
  status: string;
  uptime_7d: string | null;
  uptime_30d: string | null;
  uptime_90d: string | null;
  average_response_ms: number | null;
}

interface WebsitePayload {
  provider: { name: string; configured: boolean; status: string; error: string | null };
  metrics: { businesses: number; configured_sites: number; online: number; attention: number };
  sites: Array<{
    business: { id: string; name: string; slug: string };
    url: string;
    monitor_id: string;
    monitor: Monitor | null;
  }>;
  unmatched_monitors: Monitor[];
}

export function WebsiteMonitoring() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<WebsitePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      setData(await api.get<WebsitePayload>("/api/admin/websites"));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Website monitoring could not be loaded.");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  return <>
    <div className="page-heading-actions">
      <div>
        <h1 className="page-title" tabIndex={-1} ref={heading}>Website monitoring</h1>
        <p className="page-subtitle">Live site health from UptimeRobot across every client business.</p>
      </div>
      <button className="btn" type="button" onClick={() => void load()} disabled={loading}>Refresh</button>
    </div>
    {loading && <Loading rows={4} />}
    {error && <ErrorState body={error} />}
    {data && <>
      <div className="stat-grid">
        <Stat label="Sites configured" value={`${data.metrics.configured_sites}/${data.metrics.businesses}`} icon="◇" />
        <Stat label="Online" value={data.metrics.online} icon="✓" />
        <Stat label="Need attention" value={data.metrics.attention} icon="!" />
        <Stat label="Provider" value={data.provider.configured ? "Connected" : "Setup needed"} icon="◉" />
      </div>
      {!data.provider.configured && <ErrorState title="Connect UptimeRobot" body="Add UPTIMEROBOT_API_KEY to the Render service, then redeploy. Configure each business URL from its Business page." />}
      {data.provider.error && <ErrorState title="Provider unavailable" body={data.provider.error} />}
      <Card title="Business websites">
        {data.sites.length === 0 ? <EmptyState title="No businesses yet" body="Create a business before attaching a website monitor." /> :
          <div className="table-scroll"><table className="table table--stack">
            <thead><tr><th>Business</th><th>Website</th><th>Status</th><th>30-day uptime</th><th>Response</th><th>Manage</th></tr></thead>
            <tbody>{data.sites.map((row) => <tr key={row.business.id}>
              <td data-label="Business"><strong>{row.business.name}</strong></td>
              <td data-label="Website">{row.url ? <a className="table__link" href={row.url} target="_blank" rel="noreferrer">{row.url}</a> : "Not configured"}</td>
              <td data-label="Status"><Badge tone={row.monitor?.status === "up" ? "ok" : "warn"}>{row.monitor?.status.replace("_", " ") ?? "Not linked"}</Badge></td>
              <td data-label="30-day uptime">{row.monitor?.uptime_30d ? `${row.monitor.uptime_30d}%` : "—"}</td>
              <td data-label="Response">{row.monitor?.average_response_ms != null ? `${row.monitor.average_response_ms} ms` : "—"}</td>
              <td data-label="Manage"><Link className="table__link" to={`/admin/businesses/${row.business.id}`}>Configure</Link></td>
            </tr>)}</tbody>
          </table></div>}
      </Card>
      {data.unmatched_monitors.length > 0 && <Card title="Unmatched UptimeRobot monitors">
        <p className="management-copy">These monitors exist in UptimeRobot but are not attached to a business yet.</p>
        <div className="management-list">{data.unmatched_monitors.map((monitor) => <div className="management-list__item" key={monitor.id}><span><strong>{monitor.name}</strong><small>{monitor.url} · ID {monitor.id}</small></span></div>)}</div>
      </Card>}
    </>}
  </>;
}
