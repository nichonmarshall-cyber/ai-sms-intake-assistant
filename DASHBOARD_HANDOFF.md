# NTX Dashboard Backend Contract

This document is the implementation boundary between the SMS platform backend
and the dashboard UI. The dashboard must use these tenant and permission rules;
client-side filtering alone is never an authorization control.

## Product concepts

- **Platform:** NTX Automation Co. owns and operates the system.
- **Business:** one isolated client tenant.
- **Profile:** an intake template such as `auto_repair` or `roofing`.
- **Business phone number:** the Twilio destination that selects the business
  and may add location/number-specific rule exceptions.
- **Platform admin:** an NTX operator with cross-business administrative access.
- **Business membership:** a user's role inside one business (`owner`,
  `manager`, `staff`, or `viewer`).

## Routing and rule precedence

Inbound SMS and Voice requests resolve the tenant from Twilio's signed `To`
number. The customer never submits or chooses a business ID.

Rules merge in this order:

1. Safe platform defaults in `modules/tenancy.py`
2. `Business.settings`
3. `BusinessPhoneNumber.settings`

Nested rule objects merge recursively. A phone/location exception replaces only
the value it specifies, not the whole business configuration.

`intake.selection_mode` and `intake.demo_disclaimer` are separate:

- `single`: start the configured default profile immediately.
- `menu`: let the customer choose from the business's enabled profiles.
- `demo_disclaimer`: controls demo-only language and must be false for real
  client businesses regardless of selection mode.

## Existing tenant tables

- `businesses`
- `business_phone_numbers`
- `platform_users`
- `business_memberships`
- `audit_events`

The following operational tables carry `business_id`:

- `conversation_sessions`
- `leads`
- `processed_messages`
- `missed_call_events`

The migration preserves historical demo records under `legacy-demo`.

## Non-negotiable authorization rules

Every client query must include an authorized `business_id` on the server.
Never accept a business ID from the browser without verifying the signed-in
user's membership for that exact business.

Only `PlatformUser.is_platform_admin == true` may:

- create, suspend, or permanently delete a business;
- assign or move a Twilio phone number;
- set/change a business's ID or slug;
- grant platform-admin access;
- view records across tenants;
- permanently delete operational records;
- view platform-wide audit and diagnostic events.

Business members may:

- view leads, call events, and conversations for their own business;
- update lead workflow status and notes when their membership role allows it;
- archive records from their normal view.

Client archive is a reversible state change, not a database delete. Every
sensitive change writes an `AuditEvent` containing actor, business, action,
target, timestamp, and safe metadata. Audit events are append-only.

## Recommended dashboard API

Client endpoints:

- `GET /api/dashboard/me`
- `GET /api/dashboard/overview?business_id=...`
- `GET /api/dashboard/leads?business_id=...`
- `GET /api/dashboard/leads/<lead_id>`
- `PATCH /api/dashboard/leads/<lead_id>` for status, notes, and archive
- `GET /api/dashboard/missed-calls?business_id=...`

Platform-admin endpoints:

- `GET|POST /api/admin/businesses`
- `GET|PATCH /api/admin/businesses/<business_id>`
- `POST /api/admin/businesses/<business_id>/phone-numbers`
- `GET|POST /api/admin/users`
- `POST /api/admin/businesses/<business_id>/memberships`
- `GET /api/admin/audit-events`
- `DELETE /api/admin/<resource>/<id>` with confirmation and an audit event

Responses must never include password hashes, Twilio auth tokens, OpenAI keys,
or secrets stored in Render. Store authentication passwords using Werkzeug's
password hashing utilities or a managed identity provider; never store plain
text passwords.

## Initial dashboard screens

Client:

1. Overview metrics
2. Leads table
3. Lead/conversation detail
4. Missed-call activity
5. Archived records

Platform admin:

1. All businesses
2. Business setup and phone-number mapping
3. User/membership management
4. Cross-tenant lead and call diagnostics
5. Audit log and controlled data retention

## Deployment cutover

`TENANT_ROUTING_ENABLED` remains `false` until the live NTX demo business and
its Twilio number are present in `business_phone_numbers`. The existing demo
continues using its current environment configuration while false. After the
tenant data is verified, enable routing and run both SMS and missed-call smoke
tests before onboarding the first real client.
