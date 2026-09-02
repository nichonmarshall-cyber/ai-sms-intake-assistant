"""Shared business rules enforced outside the language model.

The model can choose natural wording, but it cannot authorize pricing or
appointments. These helpers provide deterministic fallbacks whenever a
customer asks about price or a generated reply oversteps those boundaries.
"""

import re

from modules.profiles import FieldSpec


_PRICING_QUESTION = re.compile(
    r"(?:\bprice\b|\bpricing\b|\bcost\b|\bquote\b|\bestimate\b|how much)",
    re.IGNORECASE,
)
_PRICE_DISCLOSURE = re.compile(
    r"(?:\$\s*\d|\b\d+(?:\.\d{1,2})?\s*(?:dollars?|bucks?)\b)",
    re.IGNORECASE,
)
_CONFIRMATION_CLAIM = re.compile(
    r"(?:you're|you are|is|has been)\s+(?:booked|scheduled|confirmed)|"
    r"appointment\s+(?:is|has been)\s+(?:booked|scheduled|confirmed)|"
    r"\bsee you (?:on|at)\b",
    re.IGNORECASE,
)


def is_pricing_question(text: str) -> bool:
    return bool(_PRICING_QUESTION.search(text or ""))


def contains_price_disclosure(text: str) -> bool:
    return bool(_PRICE_DISCLOSURE.search(text or ""))


def contains_confirmation_claim(text: str) -> bool:
    return bool(_CONFIRMATION_CLAIM.search(text or ""))


def _continue_with(next_field: FieldSpec | None) -> str:
    return f" {next_field.question}" if next_field is not None else ""


def pricing_handoff(next_field: FieldSpec | None) -> str:
    return (
        "Pricing depends on the job, so a team member will confirm that with you."
        f"{_continue_with(next_field)}"
    )


def unconfirmed_schedule_reply(next_field: FieldSpec | None) -> str:
    return (
        "I've noted that as a preference, but it isn't a confirmed appointment yet."
        f"{_continue_with(next_field)}"
    )


def enforce_reply_boundaries(
    *, customer_message: str, model_reply: str, next_field: FieldSpec | None
) -> str:
    """Replace model wording that violates pricing or scheduling authority."""
    if is_pricing_question(customer_message) or contains_price_disclosure(model_reply):
        return pricing_handoff(next_field)
    if contains_confirmation_claim(model_reply):
        return unconfirmed_schedule_reply(next_field)
    return model_reply
