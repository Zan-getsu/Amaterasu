from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
INLINE_UI_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "inline_ui.py"
BUTTON_BUILD_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "button_build.py"
MESSAGE_UTILS_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "message_utils.py"
STATUS_UTILS_PATH = ROOT / "bot" / "helper" / "ext_utils" / "status_utils.py"
FILETOLINK_PATH = ROOT / "bot" / "modules" / "filetolink.py"


def _load_inline_ui():
    spec = spec_from_file_location("amaterasu_inline_ui", INLINE_UI_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inline_button_labels_use_the_amaterasu_design_language():
    inline_ui = _load_inline_ui()

    expected = {
        "❖ OPTION": "✦ OPTION",
        "Back": "↩ BACK",
        "↩ BACK": "↩ BACK",
        "Next Page": "NEXT ❯",
        "Close": "✕ CLOSE",
        "❌ Cancel": "✕ CANCEL",
        "Yes!": "✓ CONFIRM",
        "Done Selecting": "✓ DONE",
        "Edit": "✦ EDIT",
        "View": "✦ VIEW",
        "Reset": "↻ RESET",
        "⚙ Packages": "✦ PACKAGES",
    }

    for original, styled in expected.items():
        assert inline_ui.style_inline_button(original) == styled


def test_dynamic_non_string_button_labels_are_left_untouched():
    inline_ui = _load_inline_ui()
    assert inline_ui.style_inline_button(3) == 3


def test_all_buttonmaker_buttons_pass_through_the_shared_styler():
    source = BUTTON_BUILD_PATH.read_text(encoding="utf-8")
    assert source.count("text=style_inline_button(key)") == 2


def test_panel_renderer_upgrades_header_without_rewriting_code_rows():
    inline_ui = _load_inline_ui()
    legacy = (
        "<b>✦ SAMPLE PANEL</b>\n"
        "<code>┌─ Name: example.mkv\n"
        "├─ Size: 1.4 GB\n"
        "└─ State: Ready</code>"
    )

    styled = inline_ui.style_inline_text(legacy, has_buttons=True)

    assert styled.startswith("<b>✦ SAMPLE PANEL</b>")
    assert (
        "<code>┌─ Name: example.mkv\n"
        "├─ Size: 1.4 GB\n"
        "└─ State: Ready</code>"
    ) in styled


def test_button_driven_plain_titles_receive_a_panel_header():
    inline_ui = _load_inline_ui()
    styled = inline_ui.style_inline_text(
        "<b>Select a destination</b>\nChoose one below.",
        has_buttons=True,
    )
    assert styled.startswith("<b>✦ SELECT A DESTINATION</b>")


def test_message_entry_points_use_the_shared_panel_renderer():
    source = MESSAGE_UTILS_PATH.read_text(encoding="utf-8")
    assert source.count("style_inline_text(") == 3


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


def test_system_metrics_suffix_is_byte_for_byte_protected():
    inline_ui = _load_inline_ui()
    metrics = (
        "<b>✦ SYSTEM METRICS</b>\n<pre>\n"
        "┌─ CPU      : 13.3%\n"
        "├─ RAM      : 70.3%\n"
        "├─ DL       : ↓ 1.35MB/s\n"
        "├─ UP       : ↑ 14.20KB/s\n"
        "├─ Storage  : 💾 91.44GB Free\n"
        "└─ Uptime   : ◷ 8m30s\n</pre>"
    )
    message = (
        "<b>✦ ACTIVE TASKS</b>\n"
        "<code>┌─ Status: Download\n└─ Speed: 1.19MB/s</code>\n\n"
        f"{metrics}"
    )

    styled = inline_ui.style_inline_text(message, has_buttons=True)

    assert styled.endswith(metrics)
    assert "<b>✦ ACTIVE TASKS</b>" in styled
    assert (
        "<code>┌─ Status: Download\n└─ Speed: 1.19MB/s</code>"
        in styled
    )


def test_task_card_redesign_retains_all_existing_information():
    source = STATUS_UTILS_PATH.read_text(encoding="utf-8")
    assert 'msg = "<b>✦ DOWNLOAD TELEMETRY</b>\\n\\n"' in source
    for label in (
        "Subname",
        "Status",
        "Progress",
        "Processed",
        "Count",
        "Speed",
        "ETA",
        "Elapsed",
        "Peers",
        "Size",
        "Uploaded",
        "Ratio",
        "Time",
        "Engine",
        "Mode",
        "User",
        "Select",
        "Stop",
    ):
        assert f'"{label}"' in source


def test_filetolink_redesign_retains_status_logger_and_link_fields():
    source = FILETOLINK_PATH.read_text(encoding="utf-8")
    for label in (
        "Base URL",
        "BIN_CHANNEL",
        "Dump Chat",
        "Stream Bots",
        "Cache Files",
        "Cache Size",
        "File Cap",
        "Total Cap",
        "Cache Dir",
        "Requested",
        "User ID",
        "File ID",
        "Name",
        "Size",
    ):
        assert label in source


@pytest.mark.asyncio
async def test_rendered_task_card_preserves_fields_and_metrics(monkeypatch):
    from bot.helper.ext_utils import status_utils
    from bot.helper.ext_utils.status_utils import MirrorStatus

    listener = SimpleNamespace(
        message=SimpleNamespace(
            date=datetime.now(timezone.utc),
            from_user=SimpleNamespace(
                id=42,
                mention='<a href="tg://user?id=42">Example User</a>',
            ),
            sender_chat=None,
        ),
        subname=False,
        progress=True,
        is_torrent=True,
        is_qbit=True,
        is_nzb=False,
        mode=("#qBit", "#Leech"),
    )

    task = SimpleNamespace(
        listener=listener,
        engine="qBit v4.5.2",
        name=lambda: "Example Movie",
        status=lambda: MirrorStatus.STATUS_DOWNLOAD,
        progress=lambda: "27.25%",
        processed_bytes=lambda: "389.63MB",
        size=lambda: "1.40GB",
        speed=lambda: "1.19MB/s",
        eta=lambda: "17m30s",
        seeders_num=lambda: 1,
        leechers_num=lambda: 1,
        gid=lambda: "9b55a744abcdef",
    )

    async def one_task(*_args):
        return [task]

    monkeypatch.setattr(status_utils, "get_specific_tasks", one_task)
    monkeypatch.setattr(
        status_utils.system_network_rate,
        "sample",
        lambda: (1_024.0, 2_048.0),
    )
    monkeypatch.setattr(status_utils, "cpu_percent", lambda: 13.3)
    monkeypatch.setattr(
        status_utils,
        "virtual_memory",
        lambda: SimpleNamespace(percent=70.3),
    )
    monkeypatch.setattr(
        status_utils,
        "disk_usage",
        lambda _path: SimpleNamespace(free=98_180_000_000),
    )

    raw, _buttons = await status_utils.get_readable_message(123, False)
    inline_ui = _load_inline_ui()
    styled = inline_ui.style_inline_text(raw, has_buttons=True)

    assert styled.startswith("<b>✦ DOWNLOAD TELEMETRY</b>")
    assert "📥 <b>TASK 01</b> : <b>Example Movie</b>" in styled
    for value in (
        "Example Movie",
        "Download",
        "27.25%",
        "389.63MB",
        "1.40GB",
        "1.19MB/s",
        "17m30s",
        "1 seeders : 1 leechers",
        "qBit v4.5.2",
        "#qBit → #Leech",
        "Example User",
        "42",
        "/sel_9b55a744",
        "/c_9b55a744",
    ):
        assert value in styled

    raw_metrics = raw[raw.index("<b>✦ SYSTEM METRICS</b>") :]
    styled_metrics = styled[styled.index("<b>✦ SYSTEM METRICS</b>") :]
    assert styled_metrics == raw_metrics
