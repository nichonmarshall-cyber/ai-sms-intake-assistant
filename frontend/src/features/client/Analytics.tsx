import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";

interface AnalyticsPayload {
  period: { days: number; start_date: string; end_date: string; timezone: string };
  metrics: {
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
  activity: { date: string; leads: number; appointments: number; missed_calls: number }[];
  lead_sources: Breakdown[];
  service_profiles: Breakdown[];
  workflow_statuses: Breakdown[];
}

interface Breakdown {
  key: string;
  count: number;
}

const RANGE_OPTIONS = [7, 30, 90] as const;

function readable(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function BreakdownList({ items, empty }: { items: Breakdown[]; empty: string }) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  if (!items.length) return <EmptyState title="No data yet" body={empty} />;
  return (
    <div className="analytics-breakdown">
      {items.map((item) => (
        <div className="analytics-breakdown__row" key={item.key}>
          <div className="analytics-breakdown__label">
            <span>{readable(item.key)}</span>
            <strong>{item.count}</strong>
          </div>
          <div className="analytics-breakdown__track" aria-hidden="true">
            <span style={{ width: `${total ? (item.count / total) * 100 : 0}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ActivityChart({ items }: { items: AnalyticsPayload["activity"] }) {
  const max = Math.max(1, ...items.flatMap((item) => [item.leads, item.appointments, item.missed_calls]));
  const labelEvery = items.length <= 7 ? 1 : items.length <= 30 ? 5 : 15;
  return (
    <>
      <div className="analytics-legend" aria-hidden="true">
        <span><i className="analytics-legend__lead" />Leads</span>
        <span><i className="analytics-legend__appointment" />Appointments</span>
        <span><i className="analytics-legend__missed" />Missed calls</span>
      </div>
      <div className="analytics-chart-scroll">
        <div className="analytics-chart" style={{ minWidth: Math.max(720, items.length * 24) }} role="img" aria-label="Daily leads, appointment requests, and missed calls">
          {items.map((item, index) => (
            <div className="analytics-chart__day" key={item.date} title={`${item.date}: ${item.leads} leads, ${item.appointments} appointments, ${item.missed_calls} missed calls`}>
              <div className="analytics-chart__bars">
                <span className="analytics-chart__bar analytics-chart__bar--lead" style={{ height: `${(item.leads / max) * 100}%` }} />
                <span className="analytics-chart__bar analytics-chart__bar--appointment" style={{ height: `${(item.appointments / max) * 100}%` }} />
                <span className="analytics-chart__bar analytics-chart__bar--missed" style={{ height: `${(item.missed_calls / max) * 100}%` }} />
              </div>
              <small>{index % labelEvery === 0 ? new Date(`${item.date}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : ""}</small>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

export function Analytics({ businessId }: { businessId: string }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [days, setDays] = useState<(typeof RANGE_OPTIONS)[number]>(30);
  const [data, setData] = useState<AnalyticsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<AnalyticsPayload>(`/api/dashboard/businesses/${businessId}/analytics?days=${days}`)
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [businessId, days]);

  const dateRange = useMemo(() => {
    if (!data) return "";
    const format = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    return `${format(data.period.start_date)} – ${format(data.period.end_date)}`;
  }, [data]);

  return (
    <>
      <div className="analytics-heading">
        <div>
          <h1 className="page-title" tabIndex={-1} ref={heading}>Analytics</h1>
          <p className="page-subtitle">Operational performance from your intake platform.</p>
        </div>
        <div className="analytics-range" aria-label="Analytics date range">
          {RANGE_OPTIONS.map((option) => (
            <button className={days === option ? "btn btn--primary" : "btn"} type="button" key={option} onClick={() => setDays(option)}>
              {option} days
            </button>
          ))}
        </div>
      </div>

      {loading && <Loading rows={5} label="Loading analytics" />}
      {error && <ErrorState body={error} />}
      {data && !loading && (
        <>
          <p className="analytics-period">{dateRange} · {data.period.timezone}</p>
          <div className="stat-grid analytics-stat-grid">
            <Stat label="Leads captured" value={data.metrics.leads} icon="◆" />
            <Stat label="Intake completion rate" value={`${data.metrics.completion_rate}%`} icon="✓" />
            <Stat label="Conversations started" value={data.metrics.conversations} icon="◉" />
            <Stat label="Appointments scheduled" value={`${data.metrics.scheduled_appointments}/${data.metrics.appointment_requests}`} icon="▣" />
            <Stat label="Missed calls" value={data.metrics.missed_calls} icon="✆" />
            <Stat label="Follow-up texts sent" value={data.metrics.followups_sent} icon="➤" />
          </div>

          <Card title="Activity over time">
            <ActivityChart items={data.activity} />
          </Card>

          <div className="analytics-grid">
            <Card title="Lead sources">
              <BreakdownList items={data.lead_sources} empty="Lead sources will appear as intake records are captured." />
            </Card>
            <Card title="Services requested">
              <BreakdownList items={data.service_profiles} empty="Service profile totals will appear after leads are captured." />
            </Card>
            <Card title="Lead workflow">
              <BreakdownList items={data.workflow_statuses} empty="Lead workflow totals will appear after leads are captured." />
            </Card>
          </div>

          <p className="data-boundary-note analytics-note">These numbers come from NTX intake, appointment, and missed-call records. Website traffic and Google Business Profile metrics are not included.</p>
        </>
      )}
    </>
  );
}
