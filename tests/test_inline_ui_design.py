from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INLINE_UI_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "inline_ui.py"
BUTTON_BUILD_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "button_build.py"
STATUS_UTILS_PATH = ROOT / "bot" / "helper" / "ext_utils" / "status_utils.py"


def _load_inline_ui():
    spec = spec_from_file_location("amaterasu_inline_ui", INLINE_UI_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inline_button_labels_use_the_amaterasu_design_language():
    inline_ui = _load_inline_ui()

    expected = {
        "❖ OPTION": "✦ OPTION",
        "Back": "‹ BACK",
        "↩ BACK": "‹ BACK",
        "Next Page": "NEXT ›",
        "Close": "✕ CLOSE",
        "❌ Cancel": "✕ CANCEL",
        "Yes!": "✓ CONFIRM",
        "Done Selecting": "✓ DONE",
        "Edit": "✎ EDIT",
        "View": "◉ VIEW",
        "Reset": "↻ RESET",
    }

    for original, styled in expected.items():
        assert inline_ui.style_inline_button(original) == styled


def test_dynamic_non_string_button_labels_are_left_untouched():
    inline_ui = _load_inline_ui()
    assert inline_ui.style_inline_button(3) == 3


def test_all_buttonmaker_buttons_pass_through_the_shared_styler():
    source = BUTTON_BUILD_PATH.read_text(encoding="utf-8")
    assert source.count("text=style_inline_button(key)") == 2


def test_legacy_diamond_is_not_rendered_by_bot_sources():
    legacy_mark = "\u2756"
    offenders = []
    for path in (ROOT / "bot").rglob("*.py"):
        if legacy_mark in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_system_metrics_keeps_its_preformatted_layout():
    source = STATUS_UTILS_PATH.read_text(encoding="utf-8")
    assert '"<b>✦ SYSTEM METRICS</b>\\n<pre>\\n"' in source
    assert 'msg += f"└─ {m}\\n</pre>"' in source
    assert "{'DL':<9}" in source
    assert "{'UP':<9}" in source
