from voice_neves.themes import THEMES


def test_themes_have_light_and_dark():
    assert set(THEMES) == {"light", "dark"}


def test_themes_same_keys():
    assert set(THEMES["light"]) == set(THEMES["dark"])


def test_themes_values_are_hex():
    for palette in THEMES.values():
        for key, val in palette.items():
            assert isinstance(val, str)
            assert val.startswith("#") and len(val) == 7, f"{key}={val}"


def test_themes_specific_colors():
    assert THEMES["light"]["bg"] == "#F8FAFC"
    assert THEMES["dark"]["bg"] == "#0F172A"
