import { useEffect, useState } from "react";
import { Badge, Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";
import { api } from "../../lib/api";

interface UsageCategory {
  key: string; label: string; usage: number; usage_unit: string | null;
  count: number; count_unit: string | null; price: number; price_unit: string;
}
interface Usage {
  period: string; start_date: string | null; end_date: string | null;
  total_price: number; currency: string; categories: UsageCategory[]; note: string;
}
interface UsagePayload { configured: boolean; usage: Usage | null; error?: string }

const money = (value: number, currency: string) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: currency || "USD",
}).format(value);

export function TwilioUsage() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [period, setPeriod] = useState("this_month");
  const [data, setData] = useState<UsagePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<UsagePayload>(`/api/admin/twilio-usage?period=${period}`)
      .then((payload) => { if (!cancelled) { setData(payload); setError(null); } })
      .catch((err: Error) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [period]);

  const usage = data?.usage;
  return <>
    <div className="page-heading-actions">
      <div><h1 className="page-title" tabIndex={-1} ref={heading}>Twilio usage</h1><p className="page-subtitle">Account-wide messaging, voice, phone-number, and carrier-fee costs.</p></div>
      <div className="page-heading-actions__buttons">
        <button className={period === "this_month" ? "btn btn--primary" : "btn"} onClick={() => setPeriod("this_month")}>This month</button>
        <button className={period === "last_month" ? "btn btn--primary" : "btn"} onClick={() => setPeriod("last_month")}>Last month</button>
      </div>
    </div>
    {loading && <Loading rows={4} />}
    {error && <ErrorState body={error} />}
    {data && !data.configured && <ErrorState title="Twilio usage is not connected" body="Your existing TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are enough. Confirm both are set on Render and redeploy." />}
    {data?.error && <ErrorState title="Twilio rejected the usage request" body={data.error} />}
    {usage && <>
      <div className="stat-grid">
        <Stat label="Total spend" value={money(usage.total_price, usage.currency)} icon="$" />
        <Stat label="SMS" value={money(usage.categories.find((row) => row.key === "sms")?.price ?? 0, usage.currency)} icon="➤" />
        <Stat label="Carrier fees" value={money(usage.categories.find((row) => row.key === "sms-messages-carrierfees")?.price ?? 0, usage.currency)} icon="◆" />
        <Stat label="Phone numbers" value={money(usage.categories.find((row) => row.key === "phonenumbers")?.price ?? 0, usage.currency)} icon="☎" />
      </div>
      <Card title="Usage breakdown">
        {usage.categories.length === 0 ? <EmptyState title="No usage yet" body="Twilio has not returned usage in this period." /> :
          <div className="table-scroll"><table className="table table--stack">
            <thead><tr><th>Product</th><th>Quantity</th><th>Usage</th><th>Spend</th><th>Status</th></tr></thead>
            <tbody>{usage.categories.map((row) => <tr key={row.key}>
              <td data-label="Product"><strong>{row.label}</strong></td>
              <td data-label="Quantity">{row.count.toLocaleString()} {row.count_unit ?? ""}</td>
              <td data-label="Usage">{row.usage.toLocaleString()} {row.usage_unit ?? ""}</td>
              <td data-label="Spend">{money(row.price, row.price_unit)}</td>
              <td data-label="Status"><Badge tone="ok">Live API</Badge></td>
            </tr>)}</tbody>
          </table></div>}
      </Card>
      <p className="page-footnote">{usage.note} This is the whole Twilio account; per-business attribution requires Twilio subaccounts or an internal billing ledger.</p>
    </>}
  </>;
}
