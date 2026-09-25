import { useEffect, useState } from "react";
import { Badge, Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";
import { api } from "../../lib/api";

interface WebsiteMonitor {
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
  website_url: string;
  provider: { name: string; status: string };
  monitor: WebsiteMonitor | null;
}

function uptime(value: string | null | undefined): string {
  return value ? `${value}%` : "Collecting data";
}

export function Website({ businessId }: { businessId: string }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [data, setData] = useState<WebsitePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      setData(await api.get<WebsitePayload>(`/api/dashboard/businesses/${businessId}/website`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Website health could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [businessId]);
  const monitor = data?.monitor;

  return <>
    <div className="page-heading-actions">
      <div>
        <h1 className="page-title" tabIndex={-1} ref={heading}>Website</h1>
        <p className="page-subtitle">Live status and uptime for your business website.</p>
      </div>
      <button className="btn" type="button" onClick={() => void load()} disabled={loading}>Refresh</button>
    </div>
    {loading && <Loading rows={4} />}
    {error && <ErrorState body={error} />}
    {data && data.provider.status === "unavailable" && <ErrorState title="Monitoring temporarily unavailable" body="Your website is still configured. The monitoring provider could not be reached right now." />}
    {data && !monitor && data.provider.status !== "unavailable" && <EmptyState title="Website monitoring is being connected" body="NTX Automation Co. has your website information and will finish connecting the live monitor." />}
    {monitor && <>
      <div className="stat-grid">
        <Stat label="Current status" value={monitor.status === "up" ? "Online" : monitor.status.replace("_", " ")} icon={monitor.status === "up" ? "✓" : "!"} />
        <Stat label="7-day uptime" value={uptime(monitor.uptime_7d)} icon="◇" />
        <Stat label="30-day uptime" value={uptime(monitor.uptime_30d)} icon="◇" />
        <Stat label="Response time" value={monitor.average_response_ms != null ? `${monitor.average_response_ms} ms` : "Collecting data"} icon="◉" />
      </div>
      <Card title="Website health">
        <div className={monitor.status === "up" ? "calendar-banner calendar-banner--ok" : "calendar-banner calendar-banner--warn"}>
          <span>{monitor.status === "up" ? "✓" : "!"}</span>
          <strong>{monitor.status === "up" ? "Your website is online" : "Your website needs attention"}</strong>
          <span>{monitor.name}</span>
          <Badge tone={monitor.status === "up" ? "ok" : "warn"}>{monitor.status.replace("_", " ")}</Badge>
        </div>
        <div className="management-list" style={{ marginTop: 16 }}>
          <div className="management-list__item"><span><strong>Website</strong><small>{data.website_url || monitor.url}</small></span><a className="btn" href={data.website_url || monitor.url} target="_blank" rel="noreferrer">Open website</a></div>
          <div className="management-list__item"><span><strong>90-day uptime</strong><small>Availability measured by UptimeRobot</small></span><strong>{uptime(monitor.uptime_90d)}</strong></div>
        </div>
      </Card>
      <p className="page-footnote">NTX Automation Co. monitors this website automatically. You do not need to configure a separate provider account.</p>
    </>}
  </>;
}
