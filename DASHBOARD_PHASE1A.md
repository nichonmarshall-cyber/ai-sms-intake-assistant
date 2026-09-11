# Phase 1a — Dashboard Foundation

Authentication, tenant authorization, module entitlements, and the React shell
for both dashboards. No Website Health, Local SEO, Analytics, Reviews, or
Restaurant CRM functionality is implemented in this phase; their entitlement
keys exist and their screens show honest "not available yet" states.

## Phase 2 progress

The client **Leads** module is now functional. It lists real tenant-scoped lead
rows with search, workflow-status filtering, pagination, detail review, internal
notes, status updates, and reversible archive/restore actions. Owners, managers,
and staff may update leads; viewers and platform staff remain read-only. Every
mutation writes a tenant-scoped audit event.

The client **Conversations** module now provides a searchable, filterable list
of stored SMS sessions and a sanitized message timeline with collected intake
fields. It displays only messages retained by the conversation engine (the most
recent `MAX_HISTORY`, currently 12 by default); because individual messages do
not yet carry timestamps, the UI does not invent per-message times.

The client **AI Intake** module now reports real tenant-scoped session outcomes,
AI response counts, off-topic strikes, opt-outs, and missed-call follow-up. Its
missed-call archive is reversible and audited. Metrics without a connected data
source remain explicitly unavailable rather than displaying sample values.

The Control Center now supports day-to-day tenant administration: suspend or
reactivate a business, assign and enable or disable Twilio numbers, create client
users, grant or change tenant roles, and remove access. These actions are
platform-admin-only and recorded in the append-only audit log.

The dashboard-completion batch adds live cross-tenant Conversations, Delivery,
and Webhooks diagnostics to the Control Center. Platform staff receive read-only
operations access while platform admins retain every mutation. The client
Overview now shows recent leads, recent conversations, seven-day lead activity,
and source attribution from stored tenant data.

The dashboard-completion batch deliberately did not change missed-call processing or connect a
calendar. Delivery status reflects the persisted Twilio queue result only; it
does not claim carrier delivery until provider receipts are stored. Calendar
metrics remain unavailable until the separate calendar integration batch.

## Missed-call processing hardening

The following isolated batch now records call disposition and duration, send
attempt counts, sanitized Twilio error codes, and signed delivery-status
callbacks. Failed API sends can be retried by a platform admin from the
Delivery screen; the retry is bounded, atomically claimed, and rechecks current
feature, allowlist/blocklist, opt-out, and cooldown rules before sending.

This change does not enable missed-call automation. `MISSED_CALLS_ENABLED`
remains false in `render.yaml`, tenant routing remains false, and the calendar
is untouched. Production activation still requires a real conditional-forwarding
smoke test from an allowlisted number.

## What is deliberately NOT deployed

Render deployment behavior is unchanged apart from the safe retry-count default.
It still runs `pip install -r requirements.txt` and has no Node toolchain, so it
cannot build the React bundle. `static/dist` is
gitignored and not committed. On Render the dashboard routes therefore return a
controlled **503**, while `/sms`, `/voice/missed-call`, `/health`, and `/reset`
continue to work exactly as before. Wiring the build into Render is the first
item of Phase 1b.

## Local setup

Backend (PowerShell, Windows). SQLite is the fastest safe local setup; Render
continues to use PostgreSQL:

```powershell
cd "E:\.Projects\smsIntake_assistant V4"
py -m pip install -r requirements-dev.txt

# Phase 1a needs SECRET_KEY: it keys the HMAC used to hash client IPs.
$env:SECRET_KEY = "a-long-random-local-value"
$env:DATABASE_URL = "sqlite:///sms_intake_dev.db"
$env:FLASK_ENV = "development"          # allows the session cookie over local HTTP
$env:APP_MODE = "demo"

py -m alembic upgrade head
py -m scripts.create_admin --email you@ntxautomationco.com
py app.py                                # serves on http://127.0.0.1:5000
```

To preview the client-facing dashboard with repeatable sample activity, stop
Flask once after the migration and run:

```powershell
py -m scripts.seed_local_demo --email client@ntx.local
```

The command prompts for a client password, repairs the `legacy-demo` settings,
creates a separate local `Miller Auto Care` client tenant, grants that client an
owner membership, and adds idempotent sample leads/missed calls. It refuses to
run against PostgreSQL or when `FLASK_ENV=production`.

If you prefer a local PostgreSQL server, replace `DATABASE_URL` with its local
connection string. Never use the live Render connection string for dashboard
development.

Frontend, in a second terminal:

```powershell
cd "E:\.Projects\smsIntake_assistant V4\frontend"
npm install
npm run dev                              # http://localhost:5173, proxies /api to Flask
```

Vite proxies `/api` to Flask, so the session cookie is same-origin in development
too — no CORS, no separate token store.

To exercise the production path instead:

```powershell
cd frontend
npm run build                            # writes ../static/dist
cd ..
py app.py                                # Flask now serves the SPA at http://127.0.0.1:5000
```

## Verification

```powershell
py -m pytest -q                          # backend suite
cd frontend; npm run typecheck; npm run build
```

Migrations, up and back down:

```powershell
py -m alembic upgrade head
py -m alembic downgrade -1
py -m alembic upgrade head
```

## Environment variables added in this phase

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Yes | Keys the HMAC used to hash client IP addresses. Already generated by `render.yaml`. |
| `IP_HASH_KEY` | No | Dedicated IP-hash key. Falls back to `SECRET_KEY`. |
| `SESSION_COOKIE_SECURE` | No | Forces the Secure flag on or off. Defaults to on when `FLASK_ENV=production`. |

No new third-party credentials are needed for Phase 1a.

## Security model

* **Sessions** are opaque 32-byte tokens in an HttpOnly, SameSite=Lax cookie.
  Only a SHA-256 of the token is stored. Fast hashing is correct here: the token
  has ~256 bits of entropy, so there is no dictionary to slow down, and a KDF
  would run on every authenticated request. Passwords use scrypt, because
  passwords are low-entropy.
* **Revocation** is immediate — every request re-reads the row and rejects a
  revoked, expired, or idle session. Absolute lifetime 7 days, idle timeout
  12 hours. `last_activity_at` is refreshed at most once per 5 minutes so normal
  browsing does not write on every GET.
* **CSRF** is bound to the session row: the presented `X-CSRF-Token` is hashed
  and compared in constant time against `user_sessions.csrf_hash`. A token from
  a different session is rejected. Twilio webhooks are exempt and rely on
  X-Twilio-Signature validation instead.
* **Throttle** lives in Postgres, not process memory, because Gunicorn runs
  multiple workers. 5 failures per email and 20 per IP in 15 minutes.
* **IP addresses** are never stored raw — only a keyed HMAC digest.
* **Authorization** — platform admins bypass membership; platform staff have
  explicit read-only cross-tenant access and no admin routes; everyone else is
  limited to their `business_memberships` rows. A `business_id` from the browser
  only selects among businesses the caller already has.
* **Module entitlements** are enforced server-side. Hiding a nav link is not
  authorization.
