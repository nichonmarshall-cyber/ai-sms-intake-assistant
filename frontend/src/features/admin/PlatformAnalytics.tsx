import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { Badge, Card, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";

interface BusinessAnalytics {
  id: string;
  name: string;
  slug: string;
  status: string;
  is_demo: boolean;
  leads: number;
  completed_intakes: number;
  completion_rate: number;
  conversations: number;
  appointment_requests: number;
  scheduled_appointments: number;
  schedule_rate: number;
  missed_calls: number;
  followups_sent: number;
}

interface PlatformAnalyticsPayload {
  period: { days: number; start_date: string; end_date: string; timezone: string };
  metrics: {
    businesses: number;
    active_businesses: number;
    leads: number;
    completed_intakes: number;
    completion_rate: number;
    conversations: number;
    appointment_requests: number;
    scheduled_appointments: number;
    schedule_rate: number;
    missed_calls: number;
    followups_sent: number;
  };
  businesses: BusinessAnalytics[];
}

const RANGE_OPTIONS = [7, 30, 90] as const;

export function PlatformAnalytics() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [days, setDays] = useState<(typeof RANGE_OPTIONS)[number]>(30);
  const [data, setData] = useState<PlatformAnalyticsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<PlatformAnalyticsPayload>(`/api/admin/analytics?days=${days}`)
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [days]);

  const dateRange = useMemo(() => {
    if (!data) return "";
    const format = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(
      undefined,
      { month: "short", day: "numeric", year: "numeric" },
    );
    return `${format(data.period.start_date)} – ${format(data.period.end_date)}`;
  }, [data]);

  return (
    <>
      <div className="analytics-heading">
        <div>
          <h1 className="page-title" tabIndex={-1} ref={heading}>Business analytics</h1>
          <p className="page-subtitle">Compare operational results across every NTX client tenant.</p>
        </div>
        <div className="analytics-range" aria-label="Analytics date range">
          {RANGE_OPTIONS.map((option) => (
            <button className={days === option ? "btn btn--primary" : "btn"} type="button" key={option} onClick={() => setDays(option)}>
              {option} days
            </button>
          ))}
        </div>
      </div>

      {loading && <Loading rows={5} label="Loading business analytics" />}
      {error && <ErrorState body={error} />}
      {data && !loading && (
        <>
          <p className="analytics-period">{dateRange} · {data.period.timezone}</p>
          <div className="stat-grid analytics-stat-grid">
            <Stat label="Active businesses" value={`${data.metrics.active_businesses}/${data.metrics.businesses}`} icon="▦" />
            <Stat label="Leads captured" value={data.metrics.leads} icon="◆" />
            <Stat label="Intake completion" value={`${data.metrics.completion_rate}%`} icon="✓" />
            <Stat label="Conversations" value={data.metrics.conversations} icon="◉" />
            <Stat label="Appointments scheduled" value={`${data.metrics.scheduled_appointments}/${data.metrics.appointment_requests}`} icon="▣" />
            <Stat label="Missed calls / texts" value={`${data.metrics.missed_calls} / ${data.metrics.followups_sent}`} icon="✆" />
          </div>

          <Card title="Business performance">
            <div className="table-scroll">
              <table className="table table--stack">
                <thead>
                  <tr>
                    <th scope="col">Business</th>
                    <th scope="col">Leads</th>
                    <th scope="col">Completed</th>
                    <th scope="col">Conversations</th>
                    <th scope="col">Appointments</th>
                    <th scope="col">Missed calls</th>
                    <th scope="col">Texts sent</th>
                    <th scope="col">View</th>
                  </tr>
                </thead>
                <tbody>
                  {data.businesses.map((business) => (
                    <tr key={business.id}>
                      <td data-label="Business">
                        <Link className="table__link" to={`/admin/businesses/${business.id}`}>{business.name}</Link>
                        <div className="business-analytics__badges">
                          <Badge tone={business.status === "active" ? "ok" : "warn"}>{business.status}</Badge>
                          {business.is_demo && <Badge tone="demo">Demo</Badge>}
                        </div>
                      </td>
                      <td data-label="Leads">{business.leads}</td>
                      <td data-label="Completed">{business.completed_intakes}/{business.leads} · {business.completion_rate}%</td>
                      <td data-label="Conversations">{business.conversations}</td>
                      <td data-label="Appointments">{business.scheduled_appointments}/{business.appointment_requests}</td>
                      <td data-label="Missed calls">{business.missed_calls}</td>
                      <td data-label="Texts sent">{business.followups_sent}</td>
                      <td data-label="View">
                        <Link className="btn" to={`/b/${business.id}/analytics`}>Client analytics</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <p className="data-boundary-note analytics-note">Missed calls and follow-up texts are reported separately so intentionally disabled or cooldown-blocked messages remain visible instead of being mistaken for failures.</p>
        </>
      )}
    </>
  );
}
