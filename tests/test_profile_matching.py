"""Deterministic profile-selection matching (modules/profiles.py) -- no LLM involved."""

from modules.profiles import match_menu_selection, PROFILES


def test_matches_by_number():
    assert match_menu_selection("1") == "auto_repair"
    assert match_menu_selection("2") == "roofing"
    assert match_menu_selection("3") == "painting"
    assert match_menu_selection("4") == "lawn_care"
    assert match_menu_selection("5") == "catering"


def test_matches_by_display_name_and_variations():
    assert match_menu_selection("Auto Repair") == "auto_repair"
    assert match_menu_selection("auto repair") == "auto_repair"
    assert match_menu_selection("mechanic") == "auto_repair"
    assert match_menu_selection("Roofing") == "roofing"
    assert match_menu_selection("roof") == "roofing"
    assert match_menu_selection("Painting") == "painting"
    assert match_menu_selection("painter") == "painting"
    assert match_menu_selection("Lawn Care") == "lawn_care"
    assert match_menu_selection("landscaping") == "lawn_care"
    assert match_menu_selection("Catering") == "catering"
    assert match_menu_selection("caterer") == "catering"


def test_invalid_selection_returns_none():
    assert match_menu_selection("banana") is None
    assert match_menu_selection("99") is None
    assert match_menu_selection("") is None
    assert match_menu_selection(None) is None


def test_all_five_profiles_registered():
    assert set(PROFILES.keys()) == {
        "auto_repair", "roofing", "painting", "lawn_care", "catering",
    }
    numbers = sorted(p.menu_number for p in PROFILES.values())
    assert numbers == [1, 2, 3, 4, 5]
