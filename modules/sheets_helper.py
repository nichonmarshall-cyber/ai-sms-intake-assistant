"""
sheets_helper.py
Writes completed leads to two tabs in a Google Sheet.

  CLIENT tab   — clean fields, safe to share with the client
  INTERNAL tab — all fields + debug info for your own records

Sheets integration is OPTIONAL. If credentials are not configured,
leads are printed to the terminal and the app continues normally.

Fixes applied:
  - CLIENT and INTERNAL sheet writes are now independent try/except blocks.
    A failure on one tab never prevents the other from being written.
  - Column schemas updated to include vehicle_year, vehicle_make, vehicle_model.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO ENABLE GOOGLE SHEETS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Go to https://console.cloud.google.com
2. Create a project → enable "Google Sheets API" and "Google Drive API"
3. Create a Service Account → Actions → Manage keys → Add key → JSON
4. Save the downloaded JSON to credentials/service_account.json
5. Open your Google Sheet → Share → paste the service account email → Editor
6. Copy the Sheet ID from the URL and set it in .env:
      GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
      GOOGLE_SHEET_ID=your_sheet_id_here

The app will auto-create the CLIENT_SHEET_NAME and INTERNAL_SHEET_NAME
tabs if they do not already exist.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Lazily initialised — avoids crashing on startup when Sheets isn't configured
_workbook = None


def _get_workbook():
    """
    Returns a connected gspread Workbook object, or None if not configured.
    Result is cached after first successful connection.

    TODO: Once you have your service account JSON, set these two env vars:
          GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
          GOOGLE_SHEET_ID=<id from your sheet URL>
    """
    global _workbook
    if _workbook is not None:
        return _workbook

    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_id   = os.getenv("GOOGLE_SHEET_ID", "").strip()

    if not creds_path or not sheet_id:
        logger.warning(
            "[sheets] Sheets not configured — leads will print to terminal only. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID in .env to enable."
        )
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds     = Credentials.from_service_account_file(creds_path, scopes=scopes)
        gc        = gspread.authorize(creds)
        _workbook = gc.open_by_key(sheet_id)
        logger.info("[sheets] Connected to Google Sheets successfully.")
        return _workbook

    except Exception as e:
        logger.error(f"[sheets] Connection failed: {e}")
        return None


def _get_or_create_worksheet(workbook, name: str):
    """Returns the named worksheet, creating it if it doesn't exist yet."""
    try:
        return workbook.worksheet(name)
    except Exception:
        logger.info(f"[sheets] Creating worksheet: '{name}'")
        return workbook.add_worksheet(title=name, rows=1000, cols=25)


def _ensure_header(ws, headers: list[str]) -> None:
    """Writes the header row if the sheet is empty."""
    if not ws.row_values(1):
        ws.append_row(headers, value_input_option="RAW")


# ─── Column schemas ───────────────────────────────────────────────────────────

CLIENT_HEADERS = [
    "timestamp",
    "customer_phone",
    "customer_name",
    "service_description",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "callback_requested",
    "callback_day",
    "preferred_time",
    "business_summary",
]

INTERNAL_HEADERS = CLIENT_HEADERS + [
    "category",
    "topic_status",
    "termination_reason",
    "turn_count",
    "off_topic_strikes",
    "is_complete",
]


# ─── Public API ───────────────────────────────────────────────────────────────

def log_lead(phone: str, session: dict, ai_result: dict) -> None:
    """
    Writes a completed (or terminated) lead to both sheet tabs.
    Always prints to terminal first as a reliable backup.

    CLIENT and INTERNAL writes are fully independent — a failure on one
    tab does not prevent the other from being written.

    Args:
        phone      : Customer phone number (the session key)
        session    : Full session dict from conversation.py
        ai_result  : Final validated AI response dict
    """
    fields    = session.get("fields", {})
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    client_row = [
        timestamp,
        phone,
        fields.get("customer_name")       or "",
        fields.get("service_description") or "",
        fields.get("vehicle_year")        or "",
        fields.get("vehicle_make")        or "",
        fields.get("vehicle_model")       or "",
        str(fields.get("callback_requested", False)),
        fields.get("callback_day")        or "",
        fields.get("preferred_time")      or "",
        ai_result.get("business_summary") or "",
    ]

    internal_row = client_row + [
        ai_result.get("category")          or "",
        ai_result.get("topic_status")      or "",
        ai_result.get("termination_reason") or "",
        str(session.get("turn_count", 0)),
        str(session.get("off_topic_strikes", 0)),
        str(ai_result.get("is_complete", False)),
    ]

    # ── Terminal output (always runs) ──────────────────────────────────────
    print("\n" + "═" * 56)
    print("  LEAD CAPTURED")
    print("═" * 56)
    for header, value in zip(INTERNAL_HEADERS, internal_row):
        print(f"  {header:<26} {value}")
    print("═" * 56 + "\n")

    # ── Google Sheets output (runs only if configured) ─────────────────────
    workbook = _get_workbook()
    if workbook is None:
        return  # graceful — terminal output already done above

    client_tab   = os.getenv("CLIENT_SHEET_NAME",   "Leads")
    internal_tab = os.getenv("INTERNAL_SHEET_NAME", "Internal")

    # CLIENT sheet — independent try/except
    try:
        client_ws = _get_or_create_worksheet(workbook, client_tab)
        _ensure_header(client_ws, CLIENT_HEADERS)
        client_ws.append_row(client_row, value_input_option="RAW")
        logger.info(f"[sheets] Client lead logged for {phone}")
    except Exception as e:
        logger.error(
            f"[sheets] Failed to write CLIENT sheet for {phone}: {e}. "
            "Lead is in terminal output above."
        )

    # INTERNAL sheet — independent try/except
    try:
        internal_ws = _get_or_create_worksheet(workbook, internal_tab)
        _ensure_header(internal_ws, INTERNAL_HEADERS)
        internal_ws.append_row(internal_row, value_input_option="RAW")
        logger.info(f"[sheets] Internal lead logged for {phone}")
    except Exception as e:
        logger.error(
            f"[sheets] Failed to write INTERNAL sheet for {phone}: {e}. "
            "Lead is in terminal output above."
        )
