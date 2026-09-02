from modules.profiles import PROFILES
from modules.prompt import build_system_prompt


def test_prompt_requires_natural_pricing_handoff():
    profile = PROFILES["painting"]
    prompt = build_system_prompt(
        profile,
        is_demo=True,
        is_business_hours=True,
        business_name="NTX Automation Co.",
        next_field=profile.fields[-1],
    )

    assert "Never state, invent, estimate, imply, or confirm a price" in prompt
    assert "preferences only" in prompt
    assert "warm, professional, conversational voice" in prompt
    assert "stiff or scripted phrases" in prompt
    assert "Do not repeat or summarize the customer's entire answer" in prompt
