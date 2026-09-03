"""
compliance.py
SMS compliance keyword detection (STOP / START / HELP family).

These are evaluated on every inbound message BEFORE anything is sent to
the LLM or the demo menu logic, per carrier/TCPA convention. Twilio
Messaging Services with Advanced Opt-Out enabled may already intercept
some of these at the carrier/Twilio layer, but the application still
handles them defensively so behavior is correct even without that
feature enabled.
"""

STOP_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
START_KEYWORDS = {"start", "unstop"}
HELP_KEYWORDS = {"help", "info"}

STOP_REPLY = (
    "You have been unsubscribed from NTX Automation Co. messages. "
    "Reply START to opt back in. No further messages will be sent."
)

START_REPLY_DEMO = (
    "You're opted back in to NTX Automation Co. messages."
)

HELP_REPLY = (
    "NTX Automation Co. SMS demo. Reply MENU to see industries, "
    "STOP to unsubscribe. Msg & data rates may apply."
)


def stop_reply(business_name: str) -> str:
    return (
        f"You have been unsubscribed from {business_name} messages. "
        "Reply START to opt back in. No further messages will be sent."
    )


def start_reply(business_name: str) -> str:
    return f"You're opted back in to {business_name} messages."


def help_reply(business_name: str, *, show_profile_menu: bool) -> str:
    menu_help = " Reply MENU to see services," if show_profile_menu else ""
    return (
        f"{business_name} text assistant.{menu_help} Reply STOP to unsubscribe. "
        "Msg & data rates may apply."
    )


def classify(raw_text: str) -> str | None:
    """Returns 'stop', 'start', 'help', or None."""
    text = (raw_text or "").strip().lower()
    if text in STOP_KEYWORDS:
        return "stop"
    if text in START_KEYWORDS:
        return "start"
    if text in HELP_KEYWORDS:
        return "help"
    return None
