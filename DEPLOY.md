# Deployment Guide -- Render + Twilio

This project has no Render account or Twilio account connected to this
environment, so deployment could not be executed automatically. Everything
below is the exact manual procedure using the code and config already
committed on the `demo-platform` branch (`render.yaml`, `requirements.txt`,
`migrations/`, `.env.example`).

## 1. Push the branch

```bash
git push -u origin demo-platform
```

## 2. Create the Render Blueprint

1. Go to https://dashboard.render.com -> **New** -> **Blueprint**.
2. Connect the `nichonmarshall-cyber/ai-sms-intake-assistant` repo, branch `demo-platform`.
3. Render reads `render.yaml` and proposes:
   - A **PostgreSQL** database: `ntx-sms-intake-db`
   - A **web service**: `ntx-sms-intake-assistant` (Python, Gunicorn, `/health` health check)
4. Click **Apply**.

`render.yaml` already wires `DATABASE_URL` to the database's internal
connection string automatically (`fromDatabase`). Because Render's free web
tier does not support `preDeployCommand`, the service runs
`alembic upgrade head` at the beginning of `startCommand`, immediately before
Gunicorn starts.

## 3. Set the secret environment variables

`render.yaml` marks these `sync: false` (never committed) -- set actual
values in the Render dashboard under the web service's **Environment** tab:

| Variable | Value |
|---|---|
| `OPENAI_API_KEY` | your OpenAI key |
| `TWILIO_ACCOUNT_SID` | your Twilio account SID |
| `TWILIO_AUTH_TOKEN` | your Twilio auth token |
| `TWILIO_MESSAGING_SERVICE_SID` | your Twilio Messaging Service SID (if using one) |
| `PUBLIC_BASE_URL` | `https://ntx-sms-intake-assistant.onrender.com` (or your actual Render URL once assigned) |

Optional, only if enabling Sheets export:

| Variable | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | path to a mounted service-account JSON (see note below) |
| `GOOGLE_SHEET_ID` | your sheet ID |
| `SHEETS_ENABLED` | `true` |

> Google service-account JSON is a file, not an env var. Either use
> Render's **Secret Files** feature to mount it at a fixed path and point
> `GOOGLE_SERVICE_ACCOUNT_JSON` at that path, or leave `SHEETS_ENABLED=false`
> (default) -- leads remain fully safe in Postgres either way.

Everything else (`APP_MODE=demo`, `ENABLED_PROFILES`, `SESSION_TTL_MINUTES`,
`DEFAULT_TIMEZONE`, `FLASK_ENV=production`, `TWILIO_VALIDATION_BYPASS=false`,
`SECRET_KEY` auto-generated, etc.) is already set by `render.yaml`.

**Do not set `TWILIO_VALIDATION_BYPASS=true` on Render.** A startup guard
(`modules/app_mode.py`) refuses to boot the process if that bypass is
enabled while `FLASK_ENV=production`.

## 4. Deploy and verify

1. Render builds and deploys automatically after Apply / on every push to `demo-platform`.
2. Confirm the health check:
   ```bash
   curl https://<your-render-url>.onrender.com/health
   # {"status": "ok", "service": "sms-intake-assistant", "mode": "demo"}
   ```
3. Test the webhook directly (does **not** require a real Twilio signature
   if you temporarily set `TWILIO_VALIDATION_BYPASS=true` for a single manual
   check -- **turn it back off immediately afterward**, or better, skip this
   and test through Twilio's own webhook debugger instead, which sends a
   correctly-signed request):
   ```bash
   curl -X POST https://<your-render-url>.onrender.com/sms \
     -d "From=%2B15555550100&Body=Hi&MessageSid=SMmanualtest1"
   ```
4. Check the Render service logs for errors (DB connection, OpenAI errors,
   missing env vars).
5. Confirm the migration ran: the startup log should show
   `alembic upgrade head` completing before Gunicorn starts, and the first `/sms`
   request should succeed (a missing table would surface as a 500).

## 5. Only after the server is verified healthy: point Twilio at it

**Do not change the existing Twilio webhook until step 4 above is fully
green.** The current NTX 817 demo number's existing webhook (if any) stays
untouched until this new service is proven.

Final webhook URL (fill in your actual Render service name):

```
https://<your-render-service>.onrender.com/sms
```

Where to set it:
- **Twilio Console -> Phone Numbers -> Manage -> Active Numbers -> (the NTX 817 number) -> Messaging Configuration -> "A message comes in"** -> Webhook, POST, paste the URL above.
- If using a **Messaging Service** instead: **Messaging -> Services -> (the service) -> Integration -> Incoming Messages -> Webhook** -> paste the URL above.

Save. Send a real text to the 817 number and confirm the menu arrives.

## 6. Post-cutover acceptance check

Walk the full acceptance test from the project brief against the live
number: menu -> pick an industry -> complete intake -> demo disclaimer ->
`MENU` -> pick a different industry -> complete without leakage -> confirm
the lead landed in Postgres (Render dashboard -> database -> connect with
`psql` or any Postgres client, `select * from leads order by id desc limit 5;`).

---

## Rollback procedure

Nothing about this rollback touches `main` or the `mechanic-v1` tag --
both are untouched throughout this entire project.

**If the new demo service misbehaves after the Twilio cutover:**
1. In Twilio Console, revert the number/Messaging Service webhook to
   whatever it pointed to before step 5 above (or clear it to stop
   auto-replies entirely while you investigate).
2. In Render, either roll back to the previous successful deploy
   (**Deploys** tab -> pick the prior deploy -> **Rollback**), or scale the
   service to zero to stop it entirely.
3. No customer-visible data is lost: every lead and session already lives
   in Postgres regardless of which app revision is serving traffic.

**If you need to abandon the demo-platform branch entirely and return to
the plain mechanic build:**
1. Re-point Twilio's webhook at a deployment of the `main` branch (or the
   `mechanic-v1` tag specifically: `git checkout mechanic-v1`) running the
   original single-tenant `app.py`.
2. `demo-platform` and its Render service can be left running independently
   (different code, different DB) or torn down -- neither action affects
   `main`/`mechanic-v1`, which were never modified.

**Database rollback:** to undo the last migration on a given environment:
```bash
alembic downgrade -1
```
