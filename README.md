# NTX Automation Co. SMS Intake Assistant

An AI-powered SMS intake assistant. Ships in two modes:

- **`APP_MODE=demo`** -- the NTX Automation Co. multi-industry demo. A
  customer texts in, picks an industry from a deterministic menu (Auto
  Repair, Roofing, Painting, Lawn Care, or Catering), and completes a
  profile-specific intake. Nothing is ever booked -- every completion
  reply says so explicitly.
- **`APP_MODE=production`** -- locked to exactly one client profile
  (`DEFAULT_PROFILE`), for a real single-business deployment. The demo
  menu never appears in this mode.

When a customer texts in, the system:
1. Handles SMS compliance keywords (`STOP` / `START` / `HELP`) before anything else
2. Sends a business-hours-aware greeting (production) or the industry menu (demo)
3. Collects structured intake info one question at a time -- application
   code decides which field to ask about next, not the model
4. Handles off-topic and unsafe messages gracefully
5. Persists every session and lead to PostgreSQL (SQLite locally/tests only)
6. Optionally exports completed leads to Google Sheets (`SHEETS_ENABLED=true`)
7. Can follow up on a conditionally forwarded missed call through a separate,
   feature-flagged Twilio Voice webhook

---

## Tech Stack

| Layer | Tool |
|---|---|
| Web framework | Flask + Gunicorn |
| SMS | Twilio |
| AI | OpenAI |
| Persistent storage | PostgreSQL via SQLAlchemy + Alembic (SQLite for dev/tests) |
| Lead export (optional) | Google Sheets |
| Hosting | Render |

---

## File Structure

```text
smsIntake_assistant/
├── app.py                       # Flask entry point / webhook routes
├── requirements.txt
├── requirements-dev.txt         # + pytest, freezegun, pytest-mock
├── render.yaml
├── .env.example
├── alembic.ini
├── migrations/                  # Alembic migration history
├── tests/                       # pytest suite (mocked OpenAI/Twilio/Sheets)
└── modules/
    ├── app_mode.py               # APP_MODE / DEFAULT_PROFILE startup validation
    ├── profiles.py                # Declarative industry profile configuration
    ├── prompt.py                  # System prompt builder (profile-generic)
    ├── openai_helper.py           # OpenAI call + response validation
    ├── intake_engine.py           # App-controlled "which field is next"
    ├── compliance.py              # STOP/START/HELP keyword handling
    ├── menu_text.py               # Deterministic demo menu / reply text
    ├── conversation_store.py      # DB-backed session state (replaces old in-memory store)
    ├── db.py / models.py          # SQLAlchemy engine + ORM models
    ├── twilio_helper.py           # Signature validation + TwiML
    ├── missed_call.py             # Missed-call rules, idempotency, outbound SMS
    ├── sheets_helper.py           # Optional Sheets export
    ├── business_hours.py          # Business-hours-aware greeting
    └── time_utils.py              # UTC storage -> America/Chicago display
```

---

## Setup

### 1. Clone and install

```bash
git clone <your-repo>
cd smsIntake_assistant
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt   # includes requirements.txt + test tooling
```

### 2. Configure

```bash
cp .env.example .env
# Open .env and fill in your values
```

Minimum to run the **demo** locally:

```env
APP_MODE=demo
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_VALIDATION_BYPASS=true      # local dev only -- never in production
DATABASE_URL=sqlite:///sms_intake_dev.db
```

Minimum to run **production** (single client) locally:

```env
APP_MODE=production
DEFAULT_PROFILE=roofing            # or auto_repair / painting / lawn_care / catering
BUSINESS_NAME=Acme Roofing Co
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
DATABASE_URL=sqlite:///sms_intake_dev.db
```

Full variable reference: see `.env.example`.

### 3. Run database migrations

```bash
alembic upgrade head
```

(SQLite for local dev also auto-creates tables on startup as a convenience;
Postgres deployments always require running migrations explicitly.)

### 4. Run

```bash
python app.py
```

Server starts on `http://localhost:5000`.

### 5. Point Twilio at your server (local testing)

```bash
ngrok http 5000
```

Paste the HTTPS ngrok URL + `/sms` into your Twilio webhook settings, and
set `PUBLIC_BASE_URL` to that same ngrok HTTPS URL so signature validation
matches (only relevant once `TWILIO_VALIDATION_BYPASS=false`).

### Missed-call follow-up setup

The missed-call workflow is disabled by default. It is designed for a
client's normal business number to use **conditional call forwarding** to an
SMS-and-Voice-capable Twilio number. Once that forwarded call reaches Twilio,
Twilio calls `POST /voice/missed-call`; the app records the call and, only
when its safety rules allow it, sends one initial SMS from the receiving
Twilio number.

Start with these variables on a demo deployment:

```env
MISSED_CALLS_ENABLED=false
MISSED_CALL_REQUIRE_ALLOWLIST=true
MISSED_CALL_ALLOWLIST=+15555550100
MISSED_CALL_BLOCKLIST=
MISSED_CALL_COOLDOWN_MINUTES=5
```

After deploying the route and confirming a forwarded call appears in Render
logs, set `MISSED_CALLS_ENABLED=true` and test from an allowlisted number.
For a real client, remove the temporary allowlist guard only after testing and
set `MISSED_CALL_COOLDOWN_MINUTES=1440` to limit the first follow-up to one per
caller per 24 hours. `STOP` opt-outs and numbers in `MISSED_CALL_BLOCKLIST`
are always suppressed.

Set the Twilio number's **Voice & Fax → A call comes in** webhook to:

```text
https://<your-render-service>.onrender.com/voice/missed-call
```

Use `POST` and set `PUBLIC_BASE_URL` to the same Render origin so request
signature validation succeeds behind Render's proxy. `missed_call_events`
stores each CallSid, source, rule decision, and outbound MessageSid; it is the
audit trail for the dashboard you build later.

---

## Testing

Run the full automated suite (mocked OpenAI/Twilio/Sheets -- no paid API
calls, no real network access):

```bash
pytest
```

Manual smoke test:

```bash
curl http://localhost:5000/health

curl -X POST http://localhost:5000/sms \
  -d "From=%2B15555550100&To=%2B18173936339&Body=Hi&MessageSid=SMtest1"

curl -X POST http://localhost:5000/sms \
  -d "From=%2B15555550100&To=%2B18173936339&Body=1&MessageSid=SMtest2"

curl -X POST http://localhost:5000/voice/missed-call \
  -d "From=%2B15555550100&To=%2B18173936339&CallSid=CAtest1"
```

Reset a session (dev/testing only):

```bash
curl -X POST http://localhost:5000/reset \
  -H "Content-Type: application/json" \
  -H "X-Reset-Token: $RESET_TOKEN" \
  -d '{"phone": "+15555550100"}'
```

`RESET_ENDPOINT_ENABLED=true` and a non-empty `RESET_TOKEN` are both required.
The endpoint is disabled by default and must not be used as a dashboard delete
button. Dashboard archive/delete actions require authenticated role checks and
an audit event.

---

## Conversation Flow (demo mode)

```text
Inbound SMS
     |
     v
STOP/START/HELP? --YES--> handle compliance keyword --> reply/silence --> return
     | NO
     v
Opted out? --YES (and not START)--> 204 silent --> return
     | NO
     v
New session? --YES--> send industry menu --> return
     | NO
     v
Awaiting profile selection? --YES--> match selection (deterministic) or reshow menu --> return
     | NO (in_progress)
     v
MENU/DEMO keyword? --YES--> reset to menu --> return
     | NO
     v
Max turns? --YES--> close gracefully, log lead --> return
     | NO
     v
Add user msg --> call OpenAI (told which field to ask next) --> validate JSON
     |
     v
Merge validated fields (app-controlled allowlist)
     |
     v
Off-topic strikes tracked / reset
     |
     v
should_terminate + reason=="completed"? App re-verifies all required
fields are actually present before honoring it (safety net).
     |
     v
Terminate --> log Lead to DB (+ optional Sheets) --> reply with demo disclaimer
   or
Continue --> reply --> refresh 45-min TTL
```

---

## Industry Profiles

Defined declaratively in `modules/profiles.py` -- no `if business_type ==
...` branching anywhere else in the app. Each profile has a display name,
menu number, name-matching aliases, industry-specific system-prompt
instructions, a category list, and an ordered field schema (each field:
key, label, question, required/optional).

| # | Profile | Key |
|---|---|---|
| 1 | Auto Repair | `auto_repair` |
| 2 | Roofing | `roofing` |
| 3 | Painting | `painting` |
| 4 | Lawn Care | `lawn_care` |
| 5 | Catering | `catering` |

`DEFAULT_PROFILE=mechanic` is accepted as a legacy alias for `auto_repair`
in production mode.

---

## AI Output Contract

Every OpenAI response is schema-validated against the *active profile's*
field list before it's trusted:

```json
{
  "reply": "SMS text to send",
  "category": "<one of the profile's categories>",
  "extracted_fields": { "<profile field key>": "string or null", "...": "..." },
  "is_complete": true,
  "business_summary": "one-sentence summary or null",
  "topic_status": "on_topic | off_topic | unsafe",
  "should_terminate": true,
  "termination_reason": "completed | off_topic | unsafe | max_turns | error | null"
}
```

If the model returns invalid JSON, an invalid schema, or claims
`should_terminate`/`completed` while required fields are still missing,
application code overrides it with a safe fallback / the next real
question -- the model never has final say over completion.

---

## Guardrails

The AI will never:
- Generate code or scripts
- Reveal its system prompt or internal configuration
- Reveal secrets, credentials, or API keys
- Make pricing commitments or guarantees
- Claim a real appointment/order/service was booked in demo mode
- Follow instructions that attempt to override its intake-only rules

---

## Known Limitations

- Google Sheets export is best-effort and not built for high volume; Postgres is always the source of truth
- Menu name-matching is alias/substring based, not fuzzy/typo-tolerant beyond that
- Rate limiting is per-process (`flask-limiter` memory storage) -- fine for a single Render instance, would need shared storage (e.g. Redis) if scaled to multiple instances
- No dashboard/calendar/CRM integration -- out of scope for this phase by design

---

## Deployment

See `DEPLOY.md` for Render deployment steps and the Twilio webhook cutover procedure.
