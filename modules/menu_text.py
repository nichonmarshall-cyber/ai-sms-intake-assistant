"""
menu_text.py
Deterministic (non-LLM) text builders for the demo industry menu and
related fixed replies. Menu selection itself is handled in
modules/profiles.py (match_menu_selection); this module only builds the
outbound text.
"""

from modules.profiles import Profile, FieldSpec

DEMO_DISCLAIMER = (
    "This is a demo — no appointment, service, or order was actually placed."
)

MAX_TURNS_REPLY_PRODUCTION = (
    "We've reached the limit of what we can collect over text. "
    "The team will follow up with you directly — thanks!"
)

MAX_TURNS_REPLY_DEMO = (
    "We've reached the limit of what we can collect over text for this demo. "
    f"{DEMO_DISCLAIMER}"
)


def build_menu_text(profiles: list[Profile]) -> str:
    ordered = sorted(profiles, key=lambda p: p.menu_number)
    parts = [f"{p.menu_number} {p.display_name}" for p in ordered]
    if len(parts) > 1:
        options = ", ".join(parts[:-1]) + f", or {parts[-1]}"
    else:
        options = parts[0] if parts else ""
    return (
        f"NTX Automation Co. demo. Choose: {options}. Reply MENU anytime. "
        "Demo only—nothing is booked."
    )


def build_invalid_selection_text(profiles: list[Profile]) -> str:
    return "Sorry, we didn't catch that. " + build_menu_text(profiles)


def build_profile_intro(profile: Profile, first_field: FieldSpec) -> str:
    return f"Great, let's get some quick details for {profile.display_name}. {first_field.question}"


def ensure_demo_disclaimer(reply: str, is_demo: bool) -> str:
    """
    Safety net: guarantees the demo-only disclaimer is present on a
    completion reply even if the model's phrasing didn't clearly include
    it, so we never accidentally imply a real booking happened.
    """
    if not is_demo:
        return reply
    if "demo" in reply.lower():
        return reply
    return f"{reply} {DEMO_DISCLAIMER}"


def build_completion_text(fields: dict, is_demo: bool) -> str:
    """Build a consistent, human closing once application state is complete."""
    name = str((fields or {}).get("customer_name") or "").strip()
    callback_time = str((fields or {}).get("preferred_callback_time") or "").strip()

    thanks = f"Thanks, {name}" if name else "Thanks"
    if callback_time:
        reply = (
            f"{thanks} — that's everything we need. Someone from the team will "
            f"reach out around {callback_time}."
        )
    else:
        reply = f"{thanks} — that's everything we need. The team will follow up with you soon."

    return ensure_demo_disclaimer(reply, is_demo)
