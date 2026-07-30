from pathlib import Path

import pytest

from bot.helper.ext_utils.leech_font import (
    LEECH_FONT_STYLES,
    apply_leech_font,
    normalize_leech_font,
    resolve_leech_font,
)


@pytest.mark.parametrize("style", LEECH_FONT_STYLES)
def test_supported_leech_fonts_are_normalized_and_applied(style):
    assert normalize_leech_font(f" {style.upper()} ") == style
    assert apply_leech_font("file.mkv", style) == f"<{style}>file.mkv</{style}>"


@pytest.mark.parametrize("style", ("", None, "bold", "script", "<b>"))
def test_unsupported_leech_fonts_are_ignored(style):
    assert normalize_leech_font(style) == ""
    assert apply_leech_font("file.mkv", style) == "file.mkv"


def test_user_font_overrides_global_font_with_safe_fallback():
    assert resolve_leech_font({"LEECH_FONT": "i"}, "b") == "i"
    assert resolve_leech_font({}, "b") == "b"
    assert resolve_leech_font({"LEECH_FONT": "invalid"}, "code") == "code"
    assert resolve_leech_font({"LEECH_FONT": "invalid"}, "invalid") == ""


def test_user_settings_exposes_leech_font_and_uploader_uses_user_value():
    project_root = Path(__file__).parents[1]
    settings_source = (project_root / "bot/modules/users_settings.py").read_text(
        encoding="utf-8"
    )
    uploader_source = (
        project_root
        / "bot/helper/mirror_leech_utils/upload_utils/telegram_uploader.py"
    ).read_text(encoding="utf-8")

    assert '"LEECH_FONT",' in settings_source
    assert "menu LEECH_FONT" in settings_source
    assert "apply_leech_font(cap_file_, self._lfont)" in uploader_source
    assert "resolve_leech_font(" in uploader_source
