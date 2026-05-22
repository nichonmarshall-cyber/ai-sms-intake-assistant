# SMS Intake Assistant

An AI-powered SMS intake assistant for local service businesses.
Configurable for service-based businesses like mechanic shops, detailing, power washing, plumbing, landscaping, HVAC, cleaning, and more.

When a customer texts after a missed call, the system:
1. Sends a business-hours-aware greeting
2. Collects structured intake info one question at a time
3. Handles off-topic and unsafe messages gracefully
4. Logs completed or terminated leads to Google Sheets, or to the terminal if Sheets is not configured

---

## Tech Stack

| Layer | Tool |
|---|---|
| Web framework | Flask |
| SMS | Twilio |
| AI | OpenAI |
| Lead storage | Google Sheets |
| Session state | In-memory (per-process) |

---

## File Structure

```text
sms-intake-assistant/
├── app.py
├── requirements.txt
├── env.example
├── README.md
└── modules/
    ├── __init__.py
    ├── prompt.py
    ├── conversation.py
    ├── openai_helper.py
    ├── twilio_helper.py
    ├── sheets_helper.py
    └── business_hours.py
```

---

## Setup

### 1. Clone and install

```bash
git clone <your-repo>
cd sms-intake-assistant
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp env.example .env
# Open .env and fill in your values
```

Minimum required to run:

```env
BUSINESS_NAME=Acme Auto Repair
BUSINESS_TYPE=auto repair
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
OPENAI_API_KEY=...
```

Optional but recommended:

```env
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=10
BUSINESS_OPEN_HOUR=8
BUSINESS_CLOSE_HOUR=17
BUSINESS_WORKDAYS=0,1,2,3,4
BUSINESS_TIMEZONE=America/Chicago
FLASK_ENV=development
MAX_TURNS=15
PORT=5000
```

### 3. Enable Google Sheets (optional)

See the setup guide in `modules/sheets_helper.py`.

Short version:
1. Create a Google Cloud project
2. Enable Google Sheets API and Google Drive API
3. Create a service account and download the JSON key
4. Save it somewhere like `credentials/service_account.json`
5. Share your Google Sheet with the service account email as an editor
6. Set `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_SHEET_ID` in `.env`

Until Sheets is configured, every lead is still printed to the terminal.

### 4. Point Twilio at your server

1. Get a Twilio number
2. In Twilio Console, set the messaging webhook to:
   `https://your-domain.com/sms`
3. For local testing, use ngrok:

```bash
ngrok http 5000
```

Then paste the HTTPS ngrok URL into your Twilio webhook settings.

---

## Running

```bash
python app.py
```

Server starts on `http://localhost:5000`

---

## Testing

### Health check

```bash
curl http://localhost:5000/health
```

### Simulate an inbound SMS

```bash
curl -X POST http://localhost:5000/sms \
  -d "From=%2B15555550100&Body=Hi+I+need+help"
```

### Continue the conversation

```bash
curl -X POST http://localhost:5000/sms \
  -d "From=%2B15555550100&Body=My+name+is+Alex"
```

### Reset a session

```bash
curl -X POST http://localhost:5000/reset \
  -H "Content-Type: application/json" \
  -d '{"phone": "+15555550100"}'
```

To clear all sessions:

```bash
curl -X POST http://localhost:5000/reset
```

---

## Conversation Flow

```text
Customer texts in
       │
       ▼
New session? ──YES──► Send greeting ──► return
       │ NO
       ▼
Terminated? ──YES──► 204 No Content (silent)
       │ NO
       ▼
Max turns? ──YES──► Close gracefully ──► log lead ──► return
       │ NO
       ▼
Add user message ──► Call OpenAI ──► Validate JSON
       │
       ▼
Merge extracted fields into session
       │
       ▼
Off-topic? ──Strike 1──► Redirect politely
           ──Strike 2──► Close + log lead
       │
       ▼
should_terminate? ──YES──► Log lead ──► Mark closed ──► Reply
       │ NO
       ▼
Reply + continue
```

---

## What the AI Collects

| Field | Required? | Notes |
|---|---|---|
| `customer_name` | Yes | First name is fine |
| `service_description` | Yes | What they need help with |
| `callback_requested` | Yes | Boolean flag |
| `callback_day` | Yes | Today, tomorrow, or a specific day |
| `preferred_time` | Sometimes | Not required if callback day is `today` |
| `vehicle_year` | Sometimes | Only if vehicle-related |
| `vehicle_make` | Sometimes | Only if vehicle-related |
| `vehicle_model` | Sometimes | Only if vehicle-related |

A lead is complete when all always-required fields are present, plus any conditional ones that apply.

---

## Categories

The AI must return exactly one category from this list:

- `diagnostic`
- `tire_service`
- `oil_change`
- `detailing`
- `power_washing`
- `quote_request`
- `general_service`
- `unknown`

---

## AI Output Contract

Every OpenAI response is validated before the app uses it.

```json
{
  "reply": "SMS text to send",
  "category": "diagnostic | tire_service | oil_change | detailing | power_washing | quote_request | general_service | unknown",
  "extracted_fields": {
    "customer_name": "string or null",
    "service_description": "string or null",
    "callback_requested": true,
    "callback_day": "today | tomorrow | <day> | null",
    "preferred_time": "string or null",
    "vehicle_year": "string or null",
    "vehicle_make": "string or null",
    "vehicle_model": "string or null"
  },
  "is_complete": true,
  "business_summary": "one-sentence summary or null",
  "topic_status": "on_topic | off_topic | unsafe",
  "should_terminate": true,
  "termination_reason": "completed | off_topic | unsafe | max_turns | error | null"
}
```

If the model returns invalid JSON or an invalid schema, the app falls back to a safe error response and terminates the session cleanly.

---

## Environment Variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `BUSINESS_NAME` | Yes | — | Business name injected into the system prompt |
| `BUSINESS_TYPE` | Yes | — | Example: `auto repair`, `detailing`, `power washing` |
| `TWILIO_ACCOUNT_SID` | Yes | — | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | — | Used for webhook signature validation |
| `TWILIO_PHONE_NUMBER` | Yes | — | Twilio number |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model name |
| `OPENAI_TIMEOUT_SECONDS` | No | `10` | API timeout in seconds |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | No | — | Path to service account JSON |
| `GOOGLE_SHEET_ID` | No | — | Google Sheet ID |
| `CLIENT_SHEET_NAME` | No | `Leads` | Client-facing tab name |
| `INTERNAL_SHEET_NAME` | No | `Internal` | Internal/debug tab name |
| `BUSINESS_OPEN_HOUR` | No | `8` | 24-hour integer |
| `BUSINESS_CLOSE_HOUR` | No | `17` | 24-hour integer |
| `BUSINESS_WORKDAYS` | No | `0,1,2,3,4` | 0 = Monday |
| `BUSINESS_TIMEZONE` | No | `UTC` | IANA timezone string |
| `FLASK_ENV` | No | `development` | Set to `production` for live Twilio validation |
| `MAX_TURNS` | No | `15` | Max assistant replies per session |
| `PORT` | No | `5000` | Flask port |

---

## Production Checklist

- [ ] Set `FLASK_ENV=production`
- [ ] Set all Twilio and OpenAI environment variables
- [ ] Set `OPENAI_TIMEOUT_SECONDS`
- [ ] Set your Twilio webhook URL to your live domain
- [ ] Add `.env` and `credentials/` to `.gitignore`
- [ ] Use a production server like Gunicorn
- [ ] Replace in-memory session storage before scaling

Example:

```bash
pip install gunicorn
gunicorn app:app --workers 2 --bind 0.0.0.0:8000
```

---

## Guardrails

The AI will never:
- Generate code or scripts
- Reveal its system prompt or internal configuration
- Reveal secrets, credentials, or API keys
- Make pricing commitments or guarantees
- Follow instructions that attempt to override its intake-only rules

Unsafe or out-of-scope behavior triggers termination with a safe closing message.

---

## Current Limitations

I'll Be honest about this part, because it matters in production.

- Session state is in memory, so restarts wipe active conversations
- Google Sheets logging is simple and not built for high volume
- Business hours currently depend on environment configuration being correct
- The system is only as good as the surrounding route/session logic in `app.py` and `conversation.py`

---

## Future Upgrades

### Persistent sessions
Swap the in-memory session store for Redis, SQLite, or Postgres.

### Dashboard and reporting
Use the sheet data with Looker Studio, Retool, or your own dashboard.

### Missed-call automation
Use Twilio missed-call flows to automatically text back leads after an unanswered call.

### Multi-business support
Add a business identifier and key sessions by business plus phone number.

### Error tracking
Add Sentry or another logging/monitoring service.

### Rate limiting
Use `flask-limiter` per phone number instead of only per IP.

---

## Bottom Line

This is the fourth major iteration of the project and the first version that successfully connects the full workflow end-to-end.
It is not just a chatbot. It is an intake workflow.

The next level is not more features. It is reliability.
