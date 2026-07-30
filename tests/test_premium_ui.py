from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"


def test_panel_header_style_is_non_destructive():
    from bot.helper.telegram_helper.ui_style import style_panel_text

    body = (
        "<b>Download Paused!</b>\n"
        "<code>┌─ CPU: 13.3%\n└─ RAM: 70.3%</code>\n"
        "/c_cf33f0ed"
    )
    styled = style_panel_text(body)

    assert styled.startswith("<b>✦ DOWNLOAD PAUSED!</b>")
    assert "<code>┌─ CPU: 13.3%\n└─ RAM: 70.3%</code>" in styled
    assert "/c_cf33f0ed" in styled


def test_existing_premium_header_and_system_metrics_are_unchanged():
    from bot.helper.telegram_helper.ui_style import style_panel_text

    message = (
        "<b>✦ DOWNLOAD TELEMETRY</b>\n\n"
        "<b>✦ SYSTEM METRICS</b>\n<pre>\n"
        "┌─ CPU      : 13.3%\n"
        "├─ RAM      : 70.3%\n"
        "├─ DL       : ↓ 5.08MB/s\n"
        "├─ UP       : ↑ 14.20KB/s\n"
        "└─ Uptime   : ◷ 8m30s\n</pre>"
    )

    assert style_panel_text(message) == message


def test_random_header_symbols_collapse_to_the_single_panel_mark():
    from bot.helper.telegram_helper.ui_style import style_panel_text

    assert (
        style_panel_text("🗂 <b>Target Drive Information</b>")
        == "<b>✦ TARGET DRIVE INFORMATION</b>"
    )
    assert (
        style_panel_text("<b>⚑ ERROR:</b> <i>Timed out</i>")
        == "<b>✦ ERROR:</b> <i>Timed out</i>"
    )


def test_common_button_actions_share_one_design_language():
    from bot.helper.telegram_helper.button_build import _premium_label

    expected = {
        "❖ OPTION": "✦ OPTION",
        "Back": "↩ BACK",
        "Previous": "❮ PREV",
        "Next Page": "NEXT ❯",
        "Close": "✕ CLOSE",
        "Cancel": "✕ CANCEL",
        "Yes!": "✓ CONFIRM",
        "Done Selecting": "✓ DONE",
        "Check Again": "↻ CHECK AGAIN",
        "Edit": "✦ EDIT",
        "View": "✦ VIEW",
        "Reset": "↻ RESET",
        "✦ Leech Split Size": "✦ LEECH SPLIT SIZE",
        "⚙ Gofile Tools": "✦ GOFILE TOOLS",
        "✕ Stop": "✕ STOP",
        "◉ BOT HEALTH": "✦ BOT HEALTH",
        "▣ PRIVATE FILES": "✦ PRIVATE FILES",
        "◆ PACKAGES": "✦ PACKAGES",
    }
    for original, styled in expected.items():
        assert _premium_label(original) == styled


def test_status_card_keeps_clickable_commands_and_all_core_fields():
    source = (
        BOT / "helper" / "ext_utils" / "status_utils.py"
    ).read_text(encoding="utf-8")

    assert 'msg = "<b>✦ DOWNLOAD TELEMETRY</b>\\n\\n"' in source
    assert 'f" : <b>{task_name}</b>\\n"' in source
    for label in (
        "Status",
        "Progress",
        "Processed",
        "Speed",
        "ETA",
        "Elapsed",
        "Engine",
        "Mode",
        "User",
        "Select",
        "Stop",
    ):
        assert f'"{label}"' in source
    assert '"📊 TASK STATS"' in source
    assert '"↻ REFRESH"' in source
    assert "code=False" in source


def test_premium_fields_use_colons_instead_of_middle_dots():
    status_source = (
        BOT / "helper" / "ext_utils" / "status_utils.py"
    ).read_text(encoding="utf-8")

    assert 'f"{branch} <b>{label}</b> : {rendered}\\n"' in status_source
    offenders = []
    for path in BOT.rglob("*.py"):
        if " · " in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_stats_panels_use_system_metrics_style_code_view():
    source = (BOT / "modules" / "stats.py").read_text(encoding="utf-8")

    assert "<b>✦ SYSTEM DASHBOARD</b>" in source
    assert "<pre>┌─ BOT HEALTH" in source
    for title in (
        "BOT STATISTICS",
        "SYSTEM OS",
        "REPO METRICS",
        "PACKAGES",
        "TASK LIMITS",
        "SYSTEM TASKS",
    ):
        title_index = source.index(f"<b>✦ {title}</b>")
        assert "<pre>" in source[title_index : title_index + 120]


def test_every_message_entry_point_uses_header_only_styling():
    source = (
        BOT / "helper" / "telegram_helper" / "message_utils.py"
    ).read_text(encoding="utf-8")

    assert source.count("style_inline_text(") == 3


def test_legacy_diamond_is_not_rendered_by_bot_sources():
    legacy_mark = "\u2756"
    offenders = []
    for path in BOT.rglob("*.py"):
        if legacy_mark in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
