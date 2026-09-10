import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import type {
  AuditEvent,
  Business,
  Membership,
  ModuleEntitlement,
  Paged,
  PhoneNumber,
  UnavailableMetric,
  User,
} from "../../lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Loading,
  Stat,
  useFocusOnMount,
} from "../../components";

interface OverviewPayload {
  active_businesses: number;
  leads: number;
  missed_calls: number;
  users: number;
  unavailable: UnavailableMetric[];
}

/** Small helper so every screen handles loading / error / data the same way. */
function useResource<T>(path: string, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

function PlatformOverview() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading } = useResource<OverviewPayload>("/api/admin/overview");

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Control Center
      </h1>
      <p className="page-subtitle">Platform health across every client business.</p>

      {loading && <Loading rows={3} />}
      {error && <ErrorState body={error} />}
      {data && (
        <>
          <div className="stat-grid">
            <Stat label="Active businesses" value={data.active_businesses} icon="◉" />
            <Stat label="Leads captured" value={data.leads} icon="◆" />
            <Stat label="Missed calls handled" value={data.missed_calls} icon="✆" />
            <Stat label="Platform users" value={data.users} icon="◈" />
          </div>

          <Card title="Not yet measurable">
            <p style={{ color: "var(--ntx-muted)", marginTop: 0 }}>
              These metrics appear in the mockup but have no data source connected. They
              stay empty rather than showing a placeholder number.
            </p>
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

function BusinessList() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const path = `/api/admin/businesses?page=${page}&q=${encodeURIComponent(query)}`;
  const { data, error, loading, reload } = useResource<Paged<Business>>(path, [page, query]);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const createBusiness = async (event: React.FormEvent) => {
    event.preventDefault();
    setFieldErrors({});
    setFormError(null);
    try {
      await api.post("/api/admin/businesses", { name, slug });
      setName("");
      setSlug("");
      await reload();
    } catch (err) {
      const apiErr = err as { fields?: Record<string, string>; message?: string };
      setFieldErrors(apiErr.fields ?? {});
      setFormError(apiErr.message ?? "Could not create the business.");
    }
  };

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Businesses
      </h1>
      <p className="page-subtitle">Every client tenant on the platform.</p>

      <div className="toolbar">
        <label className="ntx-visually-hidden" htmlFor="business-search">
          Search businesses
        </label>
        <input
          id="business-search"
          className="input"
          type="search"
          placeholder="Search by name…"
          value={query}
          onChange={(e) => {
            setPage(1);
            setQuery(e.target.value);
          }}
        />
      </div>

      <Card title="All businesses">
        {loading && <Loading rows={4} />}
        {error && <ErrorState body={error} />}
        {data && data.items.length === 0 && (
          <EmptyState
            title="No businesses yet"
            body="Create the first client tenant using the form below. Each one gets its own isolated data and its own Twilio number."
          />
        )}
        {data && data.items.length > 0 && (
          <div className="table-scroll">
            <table className="table table--stack">
              <thead>
                <tr>
                  <th scope="col">Business</th>
                  <th scope="col">Slug</th>
                  <th scope="col">Status</th>
                  <th scope="col">Type</th>
                  <th scope="col">Modules</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((business) => (
                  <tr key={business.id}>
                    <td data-label="Business">
                      <Link className="table__link" to={`/admin/businesses/${business.id}`}>
                        {business.name}
                      </Link>
                    </td>
                    <td data-label="Slug">{business.slug}</td>
                    <td data-label="Status">
                      <Badge tone={business.status === "active" ? "ok" : "warn"}>
                        {business.status}
                      </Badge>
                    </td>
                    <td data-label="Type">
                      {business.is_demo ? <Badge tone="demo">Demo</Badge> : <Badge>Production</Badge>}
                    </td>
                    <td data-label="Modules">{business.modules.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div style={{ marginTop: 24 }}>
        <Card title="Create a business">
          <form onSubmit={createBusiness} noValidate>
            <Field label="Business name" id="new-name" error={fieldErrors.name}>
              <input
                id="new-name"
                className="input"
                value={name}
                required
                aria-invalid={Boolean(fieldErrors.name)}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Slug" id="new-slug" error={fieldErrors.slug}>
              <input
                id="new-slug"
                className="input"
                value={slug}
                required
                placeholder="miller-auto-care"
                aria-invalid={Boolean(fieldErrors.slug)}
                onChange={(e) => setSlug(e.target.value)}
              />
            </Field>
            {formError && !Object.keys(fieldErrors).length && (
              <p className="field__error" role="alert">
                {formError}
              </p>
            )}
            <button type="submit" className="btn btn--primary">
              Create business
            </button>
          </form>
        </Card>
      </div>
    </>
  );
}

interface BusinessDetailPayload {
  business: Business;
  phone_numbers: PhoneNumber[];
  memberships: Membership[];
  modules: ModuleEntitlement[];
  counts: { leads: number; missed_calls: number };
}

function BusinessDetail() {
  const { businessId = "" } = useParams();
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading, reload } = useResource<BusinessDetailPayload>(
    `/api/admin/businesses/${businessId}`,
    [businessId],
  );
  const users = useResource<{ items: User[] }>("/api/admin/users");
  const [saving, setSaving] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [phoneLabel, setPhoneLabel] = useState("");
  const [phoneErrors, setPhoneErrors] = useState<Record<string, string>>({});
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRole, setSelectedRole] = useState("staff");
  const [newUserName, setNewUserName] = useState("");
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState("owner");
  const [userErrors, setUserErrors] = useState<Record<string, string>>({});

  const runAction = async (key: string, action: () => Promise<void>) => {
    setSaving(key);
    setActionError(null);
    try {
      await action();
      await reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The change could not be saved.");
    } finally {
      setSaving(null);
    }
  };

  const toggleModule = async (key: string, enabled: boolean) => {
    await runAction(`module-${key}`, async () => {
      await api.put(`/api/admin/businesses/${businessId}/modules/${key}`, { enabled });
    });
  };

  const changeStatus = async () => {
    if (!data) return;
    const status = data.business.status === "active" ? "suspended" : "active";
    if (status === "suspended" && !window.confirm("Suspend this tenant and stop its inbound routing?")) return;
    await runAction("business-status", async () => {
      await api.patch(`/api/admin/businesses/${businessId}`, { status });
    });
  };

  const addPhone = async (event: React.FormEvent) => {
    event.preventDefault();
    setPhoneErrors({});
    setSaving("add-phone");
    setActionError(null);
    try {
      await api.post(`/api/admin/businesses/${businessId}/phone-numbers`, {
        phone,
        label: phoneLabel,
      });
      setPhone("");
      setPhoneLabel("");
      await reload();
    } catch (err) {
      const apiErr = err as { fields?: Record<string, string>; message?: string };
      setPhoneErrors(apiErr.fields ?? {});
      setActionError(apiErr.message ?? "Could not assign the phone number.");
    } finally {
      setSaving(null);
    }
  };

  const saveMembership = async (userId: string, role: string) => {
    await runAction(`membership-${userId}`, async () => {
      await api.post(`/api/admin/businesses/${businessId}/memberships`, { user_id: userId, role });
    });
  };

  const createClientUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setUserErrors({});
    setSaving("create-user");
    setActionError(null);
    try {
      const user = await api.post<User>("/api/admin/users", {
        display_name: newUserName,
        email: newUserEmail,
        password: newUserPassword,
        platform_role: "none",
      });
      await api.post(`/api/admin/businesses/${businessId}/memberships`, {
        user_id: user.id,
        role: newUserRole,
      });
      setNewUserName("");
      setNewUserEmail("");
      setNewUserPassword("");
      await Promise.all([reload(), users.reload()]);
    } catch (err) {
      const apiErr = err as { fields?: Record<string, string>; message?: string };
      setUserErrors(apiErr.fields ?? {});
      setActionError(apiErr.message ?? "Could not create the client user.");
    } finally {
      setSaving(null);
    }
  };

  if (loading) return <Loading rows={6} />;
  if (error) return <ErrorState body={error} />;
  if (!data) return null;

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        {data.business.name}
      </h1>
      <p className="page-subtitle">
        {data.business.slug} · {data.business.status}
        {data.business.is_demo ? " · demo tenant" : " · production tenant"}
      </p>

      <div className="stat-grid">
        <Stat label="Leads" value={data.counts.leads} icon="◆" />
        <Stat label="Missed calls" value={data.counts.missed_calls} icon="✆" />
        <Stat label="Phone numbers" value={data.phone_numbers.length} icon="☎" />
        <Stat label="Users" value={data.memberships.length} icon="◈" />
      </div>

      {actionError && <ErrorState body={actionError} />}

      <div className="admin-management-grid">
        <Card title="Tenant status">
          <p className="management-copy">
            Active tenants can receive routed traffic. Suspending a tenant blocks inbound
            routing without deleting its data.
          </p>
          <div className="management-action-row">
            <Badge tone={data.business.status === "active" ? "ok" : "warn"}>
              {data.business.status}
            </Badge>
            <button
              type="button"
              className={data.business.status === "active" ? "btn" : "btn btn--primary"}
              disabled={saving === "business-status"}
              onClick={changeStatus}
            >
              {data.business.status === "active" ? "Suspend tenant" : "Reactivate tenant"}
            </button>
          </div>
        </Card>

        <Card title="Access summary">
          <p className="management-copy">
            {data.memberships.length} client user{data.memberships.length === 1 ? "" : "s"} can
            access this tenant. Roles are enforced by the API on every request.
          </p>
          <div className="management-action-row">
            <strong>{data.memberships.filter((item) => item.role === "owner").length}</strong>
            <span>owners</span>
          </div>
        </Card>
      </div>

      <Card title="Module entitlements">
        <p style={{ color: "var(--ntx-muted)", marginTop: 0 }}>
          Disabled modules are hidden from this client's navigation and refused by the
          API. Modules marked “not built yet” show an honest placeholder rather than
          sample data.
        </p>
        {data.modules.map((module) => (
          <div className="module-toggle" key={module.key}>
            <div>
              <div style={{ fontWeight: 600 }}>{module.label}</div>
              <div className="module-toggle__meta">
                {module.implemented ? module.description : `Not built yet — ${module.description}`}
              </div>
            </div>
            <button
              type="button"
              className={module.enabled ? "btn btn--primary" : "btn"}
              disabled={saving === `module-${module.key}`}
              aria-pressed={module.enabled}
              onClick={() => toggleModule(module.key, !module.enabled)}
            >
              {module.enabled ? "Enabled" : "Disabled"}
            </button>
          </div>
        ))}
      </Card>

      <div style={{ marginTop: 24 }}>
        <Card title="Phone numbers">
          <form className="inline-form-grid" onSubmit={addPhone} noValidate>
            <Field label="Twilio number" id="tenant-phone" error={phoneErrors.phone}>
              <input
                id="tenant-phone"
                className="input"
                value={phone}
                placeholder="+18175550142"
                onChange={(event) => setPhone(event.target.value)}
              />
            </Field>
            <Field label="Label" id="tenant-phone-label">
              <input
                id="tenant-phone-label"
                className="input"
                value={phoneLabel}
                placeholder="Front desk"
                onChange={(event) => setPhoneLabel(event.target.value)}
              />
            </Field>
            <button className="btn btn--primary inline-form-grid__button" disabled={saving === "add-phone"}>
              Assign number
            </button>
          </form>
          {data.phone_numbers.length === 0 ? (
            <EmptyState
              title="No number assigned"
              body="Assign the Twilio number for this business before enabling tenant routing. Inbound SMS resolves the tenant from this number."
            />
          ) : (
            <div className="table-scroll">
              <table className="table table--stack">
                <thead>
                  <tr>
                    <th scope="col">Number</th>
                    <th scope="col">Label</th>
                    <th scope="col">Enabled</th>
                    <th scope="col">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.phone_numbers.map((number) => (
                    <tr key={number.id}>
                      <td data-label="Number">{number.phone}</td>
                      <td data-label="Label">{number.label ?? "—"}</td>
                      <td data-label="Enabled">
                        <Badge tone={number.enabled ? "ok" : "warn"}>
                          {number.enabled ? "Yes" : "No"}
                        </Badge>
                      </td>
                      <td data-label="Action">
                        <button
                          type="button"
                          className="btn"
                          disabled={saving === `phone-${number.id}`}
                          onClick={() => runAction(`phone-${number.id}`, async () => {
                            await api.patch(
                              `/api/admin/businesses/${businessId}/phone-numbers/${number.id}`,
                              { enabled: !number.enabled },
                            );
                          })}
                        >
                          {number.enabled ? "Disable" : "Enable"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <div className="admin-management-grid admin-management-grid--wide">
        <Card title="Tenant access">
          {data.memberships.length === 0 ? (
            <EmptyState title="No client users" body="Create or attach a user to grant dashboard access." />
          ) : (
            <div className="management-list">
              {data.memberships.map((membership) => (
                <div className="management-list__item" key={membership.id}>
                  <span>
                    <strong>{membership.user?.display_name || membership.user?.email || membership.user_id}</strong>
                    <small>{membership.user?.email}</small>
                  </span>
                  <select
                    className="input management-list__role"
                    aria-label={`Role for ${membership.user?.email || membership.user_id}`}
                    value={membership.role}
                    disabled={saving === `membership-${membership.user_id}`}
                    onChange={(event) => saveMembership(membership.user_id, event.target.value)}
                  >
                    <option value="owner">Owner</option>
                    <option value="manager">Manager</option>
                    <option value="staff">Staff</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <button
                    type="button"
                    className="btn"
                    disabled={saving === `remove-${membership.id}`}
                    onClick={() => {
                      if (!window.confirm("Remove this user's access to the tenant?")) return;
                      void runAction(`remove-${membership.id}`, async () => {
                        await api.delete(`/api/admin/businesses/${businessId}/memberships/${membership.id}`);
                      });
                    }}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}

          <form className="attach-user-form" onSubmit={(event) => {
            event.preventDefault();
            if (selectedUserId) void saveMembership(selectedUserId, selectedRole);
          }}>
            <label htmlFor="existing-user">Attach an existing user</label>
            <div className="attach-user-form__row">
              <select
                id="existing-user"
                className="input"
                value={selectedUserId}
                onChange={(event) => setSelectedUserId(event.target.value)}
              >
                <option value="">Select user…</option>
                {users.data?.items.map((user) => (
                  <option value={user.id} key={user.id}>{user.display_name || user.email} · {user.email}</option>
                ))}
              </select>
              <select className="input" aria-label="New membership role" value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>
                <option value="owner">Owner</option>
                <option value="manager">Manager</option>
                <option value="staff">Staff</option>
                <option value="viewer">Viewer</option>
              </select>
              <button className="btn btn--primary" disabled={!selectedUserId || saving === `membership-${selectedUserId}`}>
                Grant access
              </button>
            </div>
          </form>
        </Card>

        <Card title="Create client user">
          <form onSubmit={createClientUser} noValidate>
            <Field label="Display name" id="client-user-name">
              <input id="client-user-name" className="input" value={newUserName} onChange={(event) => setNewUserName(event.target.value)} />
            </Field>
            <Field label="Email" id="client-user-email" error={userErrors.email}>
              <input id="client-user-email" className="input" type="email" value={newUserEmail} onChange={(event) => setNewUserEmail(event.target.value)} />
            </Field>
            <Field label="Temporary password" id="client-user-password" error={userErrors.password}>
              <input id="client-user-password" className="input" type="password" value={newUserPassword} onChange={(event) => setNewUserPassword(event.target.value)} />
            </Field>
            <Field label="Tenant role" id="client-user-role">
              <select id="client-user-role" className="input" value={newUserRole} onChange={(event) => setNewUserRole(event.target.value)}>
                <option value="owner">Owner</option>
                <option value="manager">Manager</option>
                <option value="staff">Staff</option>
                <option value="viewer">Viewer</option>
              </select>
            </Field>
            <button className="btn btn--primary" disabled={saving === "create-user"}>Create and grant access</button>
          </form>
        </Card>
      </div>
    </>
  );
}

function AuditLog() {
  const heading = useFocusOnMount<HTMLHeadingElement>();
  const { data, error, loading } = useResource<Paged<AuditEvent>>("/api/admin/audit-events");

  return (
    <>
      <h1 className="page-title" tabIndex={-1} ref={heading}>
        Audit log
      </h1>
      <p className="page-subtitle">Append-only record of sensitive administrative actions.</p>

      <Card title="Recent events">
        {loading && <Loading rows={5} />}
        {error && <ErrorState body={error} />}
        {data && data.items.length === 0 && (
          <EmptyState title="No events yet" body="Sensitive actions are recorded here as they happen." />
        )}
        {data && data.items.length > 0 && (
          <div className="table-scroll">
            <table className="table table--stack">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Target</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((event) => (
                  <tr key={event.id}>
                    <td data-label="When">
                      {event.created_at ? new Date(event.created_at).toLocaleString() : "—"}
                    </td>
                    <td data-label="Action">{event.action}</td>
                    <td data-label="Target">
                      {event.target_type}
                      {event.target_id ? ` · ${event.target_id.slice(0, 12)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export function ControlCenterRoutes() {
  return (
    <Routes>
      <Route index element={<PlatformOverview />} />
      <Route path="businesses" element={<BusinessList />} />
      <Route path="businesses/:businessId" element={<BusinessDetail />} />
      <Route path="audit" element={<AuditLog />} />
      <Route path="*" element={<EmptyState title="Page not found" body="That Control Center page does not exist." />} />
    </Routes>
  );
}
