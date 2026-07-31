from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
INLINE_UI_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "inline_ui.py"
BUTTON_BUILD_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "button_build.py"
MESSAGE_UTILS_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "message_utils.py"
STATUS_UTILS_PATH = ROOT / "bot" / "helper" / "ext_utils" / "status_utils.py"
FILETOLINK_PATH = ROOT / "bot" / "modules" / "filetolink.py"
BOT_SETTINGS_PATH = ROOT / "bot" / "modules" / "bot_settings.py"


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


def test_panel_renderer_upgrades_legacy_code_tree_rows():
    inline_ui = _load_inline_ui()
    legacy = (
        "<b>✦ SAMPLE PANEL</b>\n"
        "<code>┌─ Name: example.mkv\n"
        "├─ Size: 1.4 GB\n"
        "└─ State: Ready</code>"
    )

    styled = inline_ui.style_inline_text(legacy, has_buttons=True)

    assert styled.startswith("<b>✦ SAMPLE PANEL</b>")
    assert "╭─ <b>Name</b> : <code>example.mkv</code>" in styled
    assert "├─ <b>Size</b> : <code>1.4 GB</code>" in styled
    assert "╰─ <b>State</b> : <code>Ready</code>" in styled
    assert "<code>┌─" not in styled


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
    assert "╭─ <b>Status</b> : <code>Download</code>" in styled
    assert "╰─ <b>Speed</b> : <code>1.19MB/s</code>" in styled


def test_task_card_redesign_retains_all_existing_information():
    source = STATUS_UTILS_PATH.read_text(encoding="utf-8")
    assert 'msg = "<b>✦ ACTIVE TASKS</b>\\n\\n"' in source
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


def test_port_is_hidden_from_telegram_settings():
    """PORT remains a runtime config but is not offered in bot settings."""
    source = BOT_SETTINGS_PATH.read_text(encoding="utf-8")
    assert 'HIDDEN_VARS = {"PORT"}' in source
    assert "k not in HIDDEN_VARS" in source


def test_image_commands_are_available_to_command_sync():
    from bot.helper.ext_utils.help_messages import get_bot_commands
    from bot.helper.telegram_helper.command_sync import build_bot_command_menu

    commands = get_bot_commands()
    assert "AddImage" in commands
    assert "Images" in commands
    menu_commands = {item.command for item in build_bot_command_menu()}
    assert "addimage" in menu_commands
    assert "images" in menu_commands


def test_filetolink_caption_icons_match_buttons():
    source = FILETOLINK_PATH.read_text(encoding="utf-8")

    assert '<b>⬇️ DOWNLOAD</b>' in source
    assert '<b>▶️ STREAM</b>' in source
    assert '<b>↓ Download</b>' not in source
    assert '<b>▶ Stream</b>' not in source


@pytest.mark.asyncio
async def test_gallery_gif_uses_animation_delivery(monkeypatch):
    from pyrogram.types import InputMediaAnimation, InputMediaDocument

    from bot.core.tg_client import TgClient
    from bot.helper.telegram_helper.message_utils import (
        _resolve_gallery_media,
        edit_message,
        gallery_animation,
        gallery_document,
        send_message,
    )

    assert _resolve_gallery_media("https://example.com/banner.gif?v=1") == (
        "https://example.com/banner.gif?v=1",
        "animation",
    )
    assert _resolve_gallery_media(gallery_animation("telegram-file-id")) == (
        "telegram-file-id",
        "animation",
    )
    assert _resolve_gallery_media(gallery_document("document-file-id")) == (
        "document-file-id",
        "document",
    )

    bot = SimpleNamespace(
        send_animation=AsyncMock(),
        send_document=AsyncMock(),
        send_photo=AsyncMock(),
    )
    monkeypatch.setattr(TgClient, "bot", bot)
    await send_message(
        123,
        "Animated gallery item",
        photo=gallery_animation("telegram-file-id"),
    )
    kwargs = bot.send_animation.await_args.kwargs
    assert kwargs["chat_id"] == 123
    assert kwargs["animation"] == "telegram-file-id"

    await send_message(123, "Static gallery item", photo="photo-file-id")
    photo_kwargs = bot.send_photo.await_args.kwargs
    assert photo_kwargs["chat_id"] == 123
    assert photo_kwargs["photo"] == "photo-file-id"

    await send_message(
        123,
        "Document-backed GIF",
        photo=gallery_document("document-file-id"),
    )
    document_kwargs = bot.send_document.await_args.kwargs
    assert document_kwargs["chat_id"] == 123
    assert document_kwargs["document"] == "document-file-id"

    gallery_message = SimpleNamespace(
        media=object(),
        edit_media=AsyncMock(),
    )
    await edit_message(
        gallery_message,
        "Next animation",
        photo=gallery_animation("next-file-id"),
    )
    input_media = gallery_message.edit_media.await_args.args[0]
    assert isinstance(input_media, InputMediaAnimation)
    assert input_media.media == "next-file-id"
    assert input_media.caption == "Next animation"

    await edit_message(
        gallery_message,
        "Next photo",
        photo="next-photo-id",
    )
    photo_input_media = gallery_message.edit_media.await_args.args[0]
    assert photo_input_media.media == "next-photo-id"
    assert type(photo_input_media).__name__ == "InputMediaPhoto"

    await edit_message(
        gallery_message,
        "Next document GIF",
        photo=gallery_document("next-document-id"),
    )
    document_input_media = gallery_message.edit_media.await_args.args[0]
    assert isinstance(document_input_media, InputMediaDocument)
    assert document_input_media.media == "next-document-id"
    assert document_input_media.caption == "Next document GIF"


@pytest.mark.asyncio
async def test_legacy_gallery_animation_document_id_falls_back(monkeypatch):
    from pyrogram.types import InputMediaDocument

    from bot.core.tg_client import TgClient
    from bot.helper.telegram_helper.message_utils import (
        edit_message,
        gallery_animation,
        send_message,
    )

    mismatch = ValueError(
        "Expected ANIMATION, got DOCUMENT file id instead"
    )
    bot = SimpleNamespace(
        send_animation=AsyncMock(side_effect=mismatch),
        send_document=AsyncMock(),
    )
    monkeypatch.setattr(TgClient, "bot", bot)
    await send_message(
        123,
        "Legacy GIF",
        photo=gallery_animation("old-document-id"),
    )
    assert bot.send_document.await_args.kwargs["document"] == "old-document-id"

    gallery_message = SimpleNamespace(
        media=object(),
        edit_media=AsyncMock(side_effect=[mismatch, SimpleNamespace()]),
    )
    await edit_message(
        gallery_message,
        "Legacy GIF",
        photo=gallery_animation("old-document-id"),
    )
    fallback_media = gallery_message.edit_media.await_args_list[1].args[0]
    assert isinstance(fallback_media, InputMediaDocument)
    assert fallback_media.media == "old-document-id"
    assert fallback_media.caption == "Legacy GIF"


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

    assert styled.startswith("<b>✦ ACTIVE TASKS</b>")
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
