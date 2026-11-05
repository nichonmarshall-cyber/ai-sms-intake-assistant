import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { Badge, Card, EmptyState, ErrorState, Field, Loading, useFocusOnMount } from "../../components";

interface ModuleConfiguration<T> { version: number; configuration: T }
interface MemoryCustomer {
  id: number; phone: string; customer_name: string | null; rolling_summary: string;
  summary_source_count: number; summary_updated_at: string | null; pending_proposals: number;
}
interface MemoryRecord { id: number; record_type: string; label: string; values: Record<string, unknown>; status: string | null; version: number }
interface MemoryProposal { id: number; record_type: string; proposed_values: Record<string, unknown>; proposed_status: string | null; reason: string | null; status: string }
interface CustomerDetail { customer: MemoryCustomer; records: MemoryRecord[]; proposals: MemoryProposal[]; context_packet: unknown }
interface RecordType { key: string; label: string; fields: { key: string; label: string; type: string; choices: string[]; required: boolean }[] }

export function AIMemory({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [customers, setCustomers] = useState<MemoryCustomer[]>([]);
  const [selected, setSelected] = useState<CustomerDetail | null>(null);
  const [recordTypes, setRecordTypes] = useState<RecordType[]>([]);
  const [recordType, setRecordType] = useState("");
  const [recordLabel, setRecordLabel] = useState("");
  const [recordValues, setRecordValues] = useState("{}");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, types] = await Promise.all([
        api.get<{ items: MemoryCustomer[] }>(`/api/dashboard/businesses/${businessId}/ai-memory/customers${search ? `?q=${encodeURIComponent(search)}` : ""}`),
        api.get<{ items: RecordType[] }>(`/api/dashboard/businesses/${businessId}/ai-memory/record-types`),
      ]);
      setCustomers(list.items); setError(null);
      setRecordTypes(types.items); setRecordType((current) => current || types.items[0]?.key || "");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load AI Memory."); }
    finally { setLoading(false); }
  }, [businessId, search]);
  useEffect(() => { void load(); }, [load]);

  const openCustomer = async (id: number) => {
    try { setSelected(await api.get<CustomerDetail>(`/api/dashboard/businesses/${businessId}/ai-memory/customers/${id}`)); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load customer memory."); }
  };
  const resolve = async (proposal: MemoryProposal, action: "approve" | "reject") => {
    if (!selected) return;
    await api.patch(`/api/dashboard/businesses/${businessId}/ai-memory/proposals/${proposal.id}`, { action });
    await openCustomer(selected.customer.id); await load();
  };
  const addRecord = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    try {
      await api.post(`/api/dashboard/businesses/${businessId}/ai-memory/customers/${selected.customer.id}/records`, { record_type: recordType, label: recordLabel, values: JSON.parse(recordValues) });
      setRecordLabel(""); setRecordValues("{}"); await openCustomer(selected.customer.id); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the customer record."); }
  };

  return <>
    <h1 className="page-title" tabIndex={-1} ref={heading}>AI Memory</h1>
    <p className="page-subtitle">Customer context, service history, and employee-approved AI suggestions. NTX manages the memory rules for this business.</p>
    {loading && <Loading rows={4} />}{error && <ErrorState body={error} />}
    <Card title="Customer memories">
      <form className="toolbar" onSubmit={(e) => { e.preventDefault(); void load(); }}><input className="input" placeholder="Search name or phone" value={search} onChange={(e) => setSearch(e.target.value)} /><button className="btn">Search</button></form>
      {!customers.length ? <EmptyState title="No customer memories yet" body="A memory is created automatically after a completed intake while this module is enabled." /> : <div className="management-list">{customers.map((customer) => <button type="button" className="management-list__item" key={customer.id} onClick={() => void openCustomer(customer.id)}><span><strong>{customer.customer_name || customer.phone}</strong><small>{customer.phone} · {customer.summary_source_count} summarized items</small></span>{customer.pending_proposals > 0 && <Badge tone="warn">{customer.pending_proposals} pending</Badge>}</button>)}</div>}
    </Card>
    {selected && <Card title={selected.customer.customer_name || selected.customer.phone}>
      <p>{selected.customer.rolling_summary || "No rolling summary yet."}</p>
      <h3>Structured records</h3>
      {!readOnly && (recordTypes.length ? <form className="inline-form-grid" onSubmit={addRecord}>
        <Field label="Record type" id="memory-record-type"><select id="memory-record-type" className="input" value={recordType} onChange={(e) => setRecordType(e.target.value)}>{recordTypes.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></Field>
        <Field label="Record label" id="memory-record-label"><input id="memory-record-label" className="input" value={recordLabel} placeholder="Example: 2017 Honda Civic" onChange={(e) => setRecordLabel(e.target.value)} /></Field>
        <Field label="Record values" id="memory-record-values"><textarea id="memory-record-values" className="input" rows={3} value={recordValues} placeholder='{"field_key":"value"}' onChange={(e) => setRecordValues(e.target.value)} /></Field>
        <button className="btn btn--primary inline-form-grid__button">Add customer record</button>
      </form> : <p className="form-hint">NTX has not configured custom record types for this business yet.</p>)}
      {!selected.records.length ? <p className="form-hint">No structured records yet.</p> : selected.records.map((record) => <div className="management-list__item" key={record.id}><span><strong>{record.label}</strong><small>{record.record_type}{record.status ? ` · ${record.status}` : ""}</small><code>{JSON.stringify(record.values)}</code></span></div>)}
      <h3>AI update proposals</h3>
      {!selected.proposals.filter((item) => item.status === "pending").length ? <p className="form-hint">No changes waiting for approval.</p> : selected.proposals.filter((item) => item.status === "pending").map((proposal) => <div className="management-list__item" key={proposal.id}><span><strong>{proposal.record_type}</strong><small>{proposal.reason || "Proposed from customer context"}</small><code>{JSON.stringify(proposal.proposed_values)}</code></span><span><button className="btn btn--primary" disabled={readOnly} onClick={() => void resolve(proposal, "approve")}>Approve</button><button className="btn" disabled={readOnly} onClick={() => void resolve(proposal, "reject")}>Reject</button></span></div>)}
    </Card>}
  </>;
}

interface DayRule { enabled: boolean; start: string; end: string }
interface SchedulingConfig {
  booking_mode: "approval_required" | "automatic"; approval_notification_enabled: boolean; approval_message_template: string;
  buffer_before_minutes: number; buffer_after_minutes: number; minimum_notice_minutes: number; maximum_advance_days: number;
  slot_interval_minutes: number; max_bookings_per_day: number | null; working_hours: Record<string, DayRule>; services: unknown[];
}
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function AIScheduling({ businessId, readOnly }: { businessId: string; readOnly: boolean }) {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [config, setConfig] = useState<ModuleConfiguration<SchedulingConfig> | null>(null);
  const [slots, setSlots] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState("");
  useEffect(() => { api.get<ModuleConfiguration<SchedulingConfig>>(`/api/dashboard/businesses/${businessId}/ai-scheduling/configuration`).then(setConfig).catch((e: Error) => setError(e.message)); }, [businessId]);
  const update = (patch: Partial<SchedulingConfig>) => { setSavedNotice(""); if (config) setConfig({ ...config, configuration: { ...config.configuration, ...patch } }); };
  const save = async () => {
    if (!config) return; setSaving(true);
    try { setConfig(await api.put(`/api/dashboard/businesses/${businessId}/ai-scheduling/configuration`, { expected_version: config.version, configuration: config.configuration })); setError(null); setSavedNotice("Scheduling rules saved. New SMS requests will use these settings."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save scheduling rules."); }
    finally { setSaving(false); }
  };
  const preview = async () => {
    try { const result = await api.get<{ slots: string[] }>(`/api/dashboard/businesses/${businessId}/ai-scheduling/availability?days=7`); setSlots(result.slots); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load availability."); }
  };
  const upcoming = useMemo(() => slots.slice(0, 20), [slots]);
  return <>
    <h1 className="page-title" tabIndex={-1} ref={heading}>AI Scheduling</h1><p className="page-subtitle">Live Google Calendar availability with buffers, notice rules, and conflict-safe booking.</p>
    {error && <ErrorState body={error} />}{!config && !error && <Loading rows={5} />}
    {config && <>
      <Card title="Booking rules"><div className="inline-form-grid">
        <Field label="Booking mode" id="booking-mode"><select id="booking-mode" className="input" disabled={readOnly} value={config.configuration.booking_mode} onChange={(e) => update({ booking_mode: e.target.value as SchedulingConfig["booking_mode"] })}><option value="approval_required">Employee approval required</option><option value="automatic">Automatic booking</option></select></Field>
        {(["buffer_before_minutes", "buffer_after_minutes", "minimum_notice_minutes", "maximum_advance_days", "slot_interval_minutes"] as const).map((key) => <Field key={key} label={key.replace(/_/g, " ")} id={key}><input id={key} className="input" type="number" min="0" disabled={readOnly} value={config.configuration[key]} onChange={(e) => update({ [key]: Number(e.target.value) })} /></Field>)}
        <Field label="Maximum bookings per day (optional)" id="max-bookings"><input id="max-bookings" className="input" type="number" min="1" disabled={readOnly} value={config.configuration.max_bookings_per_day ?? ""} onChange={(e) => update({ max_bookings_per_day: e.target.value ? Math.max(1, Number(e.target.value)) : null })} /></Field>
      </div>
      <p className="form-hint">{config.configuration.booking_mode === "automatic"
        ? "Automatic SMS booking: complete requests with an exact date and time are checked against Google Calendar, working hours, buffers and notice limits. Unavailable times trigger SMS alternatives. Click Save scheduling rules to activate changes."
        : "Employee approval required: SMS captures the preferred time, but no appointment is booked until staff approves it."}</p>
      </Card>
      <Card title="Working hours"><div className="management-list">{DAY_NAMES.map((name, day) => { const rule = config.configuration.working_hours[String(day)]; return <div className="management-list__item" key={name}><label><input type="checkbox" checked={rule.enabled} disabled={readOnly} onChange={(e) => update({ working_hours: { ...config.configuration.working_hours, [String(day)]: { ...rule, enabled: e.target.checked } } })} /> <strong>{name}</strong></label><span><input className="input" type="time" value={rule.start} disabled={readOnly || !rule.enabled} onChange={(e) => update({ working_hours: { ...config.configuration.working_hours, [String(day)]: { ...rule, start: e.target.value } } })} /><input className="input" type="time" value={rule.end} disabled={readOnly || !rule.enabled} onChange={(e) => update({ working_hours: { ...config.configuration.working_hours, [String(day)]: { ...rule, end: e.target.value } } })} /></span></div>; })}</div></Card>
      <Card title="Approval message"><Field label={config.configuration.booking_mode === "automatic" ? "Manual approval SMS (automatic booking replies are separate)" : "SMS sent after manual approval"} id="approval-template"><textarea id="approval-template" className="input" rows={4} disabled={readOnly} value={config.configuration.approval_message_template} onChange={(e) => update({ approval_message_template: e.target.value })} /></Field><p className="form-hint">Available fields: {"{business_name}"}, {"{customer_name}"}, {"{date}"}, {"{time}"}.</p></Card>
      <div className="page-heading-actions"><button className="btn btn--primary" disabled={readOnly || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save scheduling rules"}</button><button className="btn" onClick={() => void preview()}>Preview next 7 days</button></div>
      {savedNotice && <p className="calendar-success" role="status">{savedNotice}</p>}
      {slots.length > 0 && <Card title="Live available slots"><div className="management-list">{upcoming.map((slot) => <div className="management-list__item" key={slot}><strong>{new Date(slot).toLocaleString()}</strong></div>)}</div></Card>}
    </>}
  </>;
}
