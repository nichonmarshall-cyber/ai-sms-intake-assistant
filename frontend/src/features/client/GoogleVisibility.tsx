import { useEffect, useState } from "react";
import { Card, EmptyState, ErrorState, Loading, Stat, useFocusOnMount } from "../../components";
import { api } from "../../lib/api";

interface SearchData {
  period: { start: string; end: string };
  clicks: number;
  impressions: number;
  ctr: number;
  position: number | null;
  queries: { query: string; clicks: number; impressions: number }[];
}
interface ReviewData {
  average_rating: number | null;
  total_reviews: number;
  recent: { id: string; author: string; rating: string; comment: string; updated_at: string; reply: string }[];
}
interface SearchResponse { status: string; property: string; data: SearchData | null }
interface ReviewResponse { status: string; profile_url: string; data: ReviewData | null }

function useGoogleData<T>(businessId: string, endpoint: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api.get<T>(`/api/dashboard/businesses/${businessId}/${endpoint}`)
      .then((value) => { if (active) { setData(value); setError(null); } })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [businessId, endpoint, refresh]);
  return { data, error, loading, reload: () => setRefresh((value) => value + 1) };
}

function ConnectionState({ status, label }: { status: string; label: string }) {
  return status === "unavailable"
    ? <ErrorState title="Google data temporarily unavailable" body={`The ${label} connection could not be reached. Try again later or ask NTX to check access.`} />
    : <EmptyState title={`${label} is not connected yet`} body="NTX will connect the verified Google property for this business. No estimated or sample numbers are shown." />;
}

export function LocalSEO({ businessId }: { businessId: string }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading, reload } = useGoogleData<SearchResponse>(businessId, "local-seo");
  return <>
    <div className="page-heading-actions"><div><h1 className="page-title" tabIndex={-1} ref={heading}>Local SEO</h1><p className="page-subtitle">Google Search visibility for your connected website.</p></div><button className="btn" onClick={reload} disabled={loading}>Refresh</button></div>
    {loading && <Loading rows={4} />}{error && <ErrorState body={error} />}
    {data?.status !== "connected" && data && <ConnectionState status={data.status} label="Search Console" />}
    {data?.data && <>
      <p className="page-footnote">Google Search Console · {data.data.period.start} to {data.data.period.end} · {data.property}</p>
      <div className="stat-grid"><Stat label="Search clicks" value={data.data.clicks} icon="↗" /><Stat label="Impressions" value={data.data.impressions} icon="◎" /><Stat label="Click rate" value={`${(data.data.ctr * 100).toFixed(1)}%`} icon="%" /><Stat label="Average position" value={data.data.position?.toFixed(1) ?? "—"} icon="#" /></div>
      <Card title="Search queries">{data.data.queries.length ? <div className="management-list">{data.data.queries.map((row) => <div className="management-list__item" key={row.query}><span><strong>{row.query}</strong><small>{row.impressions} impressions</small></span><strong>{row.clicks} clicks</strong></div>)}</div> : <EmptyState title="No queries in this period" body="Search Console has no query rows to report yet." />}</Card>
      <p className="page-footnote">These are website results from Google Search, not a local map ranking or a guarantee of position in Denton.</p>
    </>}
  </>;
}

export function Reviews({ businessId }: { businessId: string }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading, reload } = useGoogleData<ReviewResponse>(businessId, "reviews");
  return <>
    <div className="page-heading-actions"><div><h1 className="page-title" tabIndex={-1} ref={heading}>Reviews</h1><p className="page-subtitle">Ratings and recent feedback from your Google Business Profile.</p></div><button className="btn" onClick={reload} disabled={loading}>Refresh</button></div>
    {loading && <Loading rows={4} />}{error && <ErrorState body={error} />}
    {data?.profile_url && <p><a className="btn" href={data.profile_url} target="_blank" rel="noreferrer">Open Google listing</a></p>}
    {data?.status !== "connected" && data && <ConnectionState status={data.status} label="Google Business Profile" />}
    {data?.data && <>
      <div className="stat-grid"><Stat label="Average rating" value={data.data.average_rating?.toFixed(1) ?? "—"} icon="★" /><Stat label="Total reviews" value={data.data.total_reviews} icon="◎" /></div>
      <Card title="Recent reviews">{data.data.recent.length ? <div className="management-list">{data.data.recent.map((review) => <div className="management-list__item" key={review.id}><span><strong>{review.author} · {review.rating?.replace(/_/g, " ")}</strong><small>{review.updated_at ? new Date(review.updated_at).toLocaleDateString() : ""}</small><span>{review.comment || "No written comment"}</span>{review.reply && <small>Business reply: {review.reply}</small>}</span></div>)}</div> : <EmptyState title="No recent reviews" body="Google has no reviews to display for this location." />}</Card>
      <p className="page-footnote">Review totals come from the connected, verified Google Business Profile.</p>
    </>}
  </>;
}
