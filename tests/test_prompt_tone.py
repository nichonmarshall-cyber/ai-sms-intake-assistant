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

    assert "cannot give an accurate quote over text" in prompt
    assert "What's the best time to call?" in prompt
    assert "avoid stiff or scripted phrases" in prompt
    assert "Do not repeat or summarize the customer's entire answer" in prompt
