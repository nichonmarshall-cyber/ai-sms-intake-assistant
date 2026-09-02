"""
sheets_helper.py
Optional secondary export of completed/escalated leads to a Google Sheet.

Controlled entirely by SHEETS_ENABLED (default: false). PostgreSQL (see
modules/conversation_store.py) is always the source of truth — a Sheets
failure is logged and swallowed, never raised, so it can never crash the
SMS webhook or cause a lead to be lost.

Generalized for the multi-industry demo: column headers are built from
the active profile's field schema instead of a hardcoded mechanic shape.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO ENABLE GOOGLE SHEETS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Go to https://console.cloud.google.com
2. Create a project -> enable "Google Sheets API" and "Google Drive API"
3. Create a Service Account -> Actions -> Manage keys -> Add key -> JSON
4. Save the downloaded JSON to credentials/service_account.json
5. Open your Google Sheet -> Share -> paste the service account email -> Editor
6. Set in .env:
      SHEETS_ENABLED=true
      GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
      GOOGLE_SHEET_ID=your_sheet_id_here

The app will auto-create the CLIENT_SHEET_NAME and INTERNAL_SHEET_NAME
tabs if they do not already exist.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import logging
from datetime import datetime, timezone

from modules.profiles import Profile
from modules.time_utils import to_display_string

logger = logging.getLogger(__name__)

_workbook = None


def is_sheets_enabled() -> bool:
    return os.getenv("SHEETS_ENABLED", "false").strip().lower() == "true"


def _get_workbook():
    """Returns a connected gspread Workbook object, or None if unavailable."""
    global _workbook
    if _workbook is not None:
        return _workbook

    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()

    if not creds_path or not sheet_id:
        logger.warning(
            "[sheets] SHEETS_ENABLED=true but GOOGLE_SERVICE_ACCOUNT_JSON or "
            "GOOGLE_SHEET_ID is missing — leads will not be exported to Sheets."
        )
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        gc = gspread.authorize(creds)
        _workbook = gc.open_by_key(sheet_id)
        logger.info("[sheets] Connected to Google Sheets successfully.")
        return _workbook

    except Exception as e:
        logger.error(f"[sheets] Connection failed: {e}")
        return None


def _get_or_create_worksheet(workbook, name: str):
    try:
        return workbook.worksheet(name)
    except Exception:
        logger.info(f"[sheets] Creating worksheet: '{name}'")
        return workbook.add_worksheet(title=name, rows=1000, cols=25)


def _ensure_header(ws, headers: list[str]) -> None:
    if not ws.row_values(1):
        ws.append_row(headers, value_input_option="RAW")


def log_lead(phone: str, profile: Profile, fields: dict, ai_result: dict, session_meta: dict) -> None:
    """
    Writes a completed (or escalated) lead to both sheet tabs.
    Always prints to terminal first as a reliable backup.

    A Sheets failure is fully independent per-tab and NEVER raised —
    PostgreSQL already has the lead by the time this is called.
    """
    now_utc = datetime.now(timezone.utc)
    timestamp = to_display_string(now_utc)

    client_headers = ["timestamp", "customer_phone", "profile"] + [f.label for f in profile.fields] + ["business_summary"]
    client_row = [timestamp, phone, profile.display_name] + [
        str(fields.get(f.key) or "") for f in profile.fields
    ] + [ai_result.get("business_summary") or ""]

    internal_headers = client_headers + [
        "category", "topic_status", "termination_reason",
        "turn_count", "off_topic_strikes", "is_complete",
    ]
    internal_row = client_row + [
        ai_result.get("category") or "",
        ai_result.get("topic_status") or "",
        ai_result.get("termination_reason") or "",
        str(session_meta.get("turn_count", 0)),
        str(session_meta.get("off_topic_strikes", 0)),
        str(ai_result.get("is_complete", False)),
    ]

    print("\n" + "=" * 56)
    print("  LEAD CAPTURED")
    print("=" * 56)
    for header, value in zip(internal_headers, internal_row):
        print(f"  {header:<26} {value}")
    print("=" * 56 + "\n")

    if not is_sheets_enabled():
        return

    try:
        workbook = _get_workbook()
        if workbook is None:
            return

        client_tab = os.getenv("CLIENT_SHEET_NAME", "Leads")
        internal_tab = os.getenv("INTERNAL_SHEET_NAME", "Internal")

        try:
            client_ws = _get_or_create_worksheet(workbook, client_tab)
            _ensure_header(client_ws, client_headers)
            client_ws.append_row(client_row, value_input_option="RAW")
            logger.info(f"[sheets] Client lead logged for {phone}")
        except Exception as e:
            logger.error(f"[sheets] Failed to write CLIENT sheet for {phone}: {e}")

        try:
            internal_ws = _get_or_create_worksheet(workbook, internal_tab)
            _ensure_header(internal_ws, internal_headers)
            internal_ws.append_row(internal_row, value_input_option="RAW")
            logger.info(f"[sheets] Internal lead logged for {phone}")
        except Exception as e:
            logger.error(f"[sheets] Failed to write INTERNAL sheet for {phone}: {e}")

    except Exception as e:
        # Absolute last-resort guard: Sheets must never crash the webhook.
        logger.error(f"[sheets] Unexpected Sheets export failure for {phone}: {e}")
