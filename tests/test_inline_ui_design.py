import ast
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from re import findall
from sys import modules
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
INLINE_UI_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "inline_ui.py"
BUTTON_BUILD_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "button_build.py"
MESSAGE_UTILS_PATH = ROOT / "bot" / "helper" / "telegram_helper" / "message_utils.py"
STATUS_UTILS_PATH = ROOT / "bot" / "helper" / "ext_utils" / "status_utils.py"
HELP_MESSAGES_PATH = ROOT / "bot" / "helper" / "ext_utils" / "help_messages.py"
STATUS_PATH = ROOT / "bot" / "modules" / "status.py"
MEGA_SDK_PATH = ROOT / "bot" / "helper" / "ext_utils" / "mega_sdk.py"
FILETOLINK_PATH = ROOT / "bot" / "modules" / "filetolink.py"
BOT_SETTINGS_PATH = ROOT / "bot" / "modules" / "bot_settings.py"
EN_LANGUAGE_PATH = ROOT / "bot" / "helper" / "languages" / "en.py"
SERVICES_PATH = ROOT / "bot" / "modules" / "services.py"
SETUP_PATH = ROOT / "bot" / "modules" / "setup.py"
SPEEDTEST_PATH = ROOT / "bot" / "modules" / "speedtest.py"
MAIN_PATH = ROOT / "bot" / "__main__.py"
README_PATH = ROOT / "README.md"

AMATERASU_ASCII_ROWS = (
    "█████╗ ███╗   ███╗ █████╗ ████████╗███████╗██████╗  █████╗ ███████╗██╗   ██╗",
    "██╔══██╗████╗ ████║██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║   ██║",
    "███████║██╔████╔██║███████║   ██║   █████╗  ██████╔╝███████║███████╗██║   ██║",
    "██╔══██║██║╚██╔╝██║██╔══██║   ██║   ██╔══╝  ██╔══██╗██╔══██║╚════██║██║   ██║",
    "██║  ██║██║ ╚═╝ ██║██║  ██║   ██║   ███████╗██║  ██║██║  ██║███████║╚██████╔╝",
    "╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝",
)


def test_runtime_and_readme_banners_spell_amaterasu():
    runtime_source = MAIN_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    for row in AMATERASU_ASCII_ROWS:
        assert row in runtime_source
        assert row in readme


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
        "Skip": "↷ SKIP",
        "⚙ Packages": "✦ PACKAGES",
        "Git Repo": "✦ GIT REPO",
        "Updates": "✦ UPDATES",
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


def test_filetolink_status_uses_main_status_design_and_essential_metrics():
    source = FILETOLINK_PATH.read_text(encoding="utf-8")
    for label in (
        "FILETOLINK STATUS",
        "TRANSFER",
        "Status",
        "Progress",
        "Processed",
        "Speed",
        "Elapsed",
        "Source",
        "SERVICE METRICS",
        "State",
        "Transfers",
        "Workers",
        "Cache",
        "Requested",
        "User ID",
        "File ID",
        "Name",
        "Size",
    ):
        assert label in source

    status_renderer = source[source.index("def build_filetolink_status") : source.index("async def send_filetolink_status")]
    for internal_label in (
        "Base URL",
        "BIN_CHANNEL",
        "Dump Chat",
        "Cache Dir",
        "TG Requests",
        "Prefetch",
    ):
        assert internal_label not in status_renderer


def test_main_status_has_filetolink_navigation_and_auto_refresh():
    status_source = STATUS_PATH.read_text(encoding="utf-8")
    status_utils_source = STATUS_UTILS_PATH.read_text(encoding="utf-8")
    message_utils_source = MESSAGE_UTILS_PATH.read_text(encoding="utf-8")

    assert '"▶ FILETOLINK"' in status_utils_source
    assert "get_idle_status_message" in status_source
    assert "not is_user and not task_dict" in message_utils_source
    assert 'data[2] in {"fl", "flp"}' in status_source
    assert 'data[2] == "home"' in status_source
    assert 'status_dict[key]["view"] = "filetolink"' in status_source
    assert "if not has_status:" in status_source
    assert 'get("view", "tasks") == "filetolink"' in message_utils_source
    assert "page_no=status_dict[sid].get(\"filetolink_page\", 1)" in message_utils_source
    assert "get_idle_status_message(sid)" in message_utils_source


def test_start_message_uses_status_panel_design():
    source = SERVICES_PATH.read_text(encoding="utf-8")
    en_source = EN_LANGUAGE_PATH.read_text(encoding="utf-8")

    assert 'return f"""<b>✦ AMATERASU ONLINE</b>' in source
    assert 'START_MSG = """<b>✦ AMATERASU ONLINE</b>' in en_source
    for label in ("Status", "Sources", "Outputs", "Commands"):
        assert f"<b>{label}</b> : " in source
    assert "/{help_cmd}" in source


def test_help_message_uses_status_panel_design():
    source = HELP_MESSAGES_PATH.read_text(encoding="utf-8")

    assert "<b>✦ COMMAND DIRECTORY</b>" in source
    for label in ("Commands", "Search", "Usage"):
        assert f"<b>{label}</b> : " in source


def test_setup_wizard_uses_status_panel_design_and_fixed_callbacks():
    source = SETUP_PATH.read_text(encoding="utf-8")

    assert "<b>✦ SETUP CONTROL</b>" in source
    for label in ("Step", "Panel", "Status", "Download Dir", "Version"):
        assert f"<b>{label}</b> : " in source
    assert 'buttons.data_button("Skip", f"setup skip {user_id} {step_idx + 1}")' in source
    assert "if len(data) < 3:" in source
    assert 'if action not in {"next", "skip"} or len(data) < 4:' in source
    assert source.count("except ValueError:") >= 2
    assert "escape(str(" in source


def test_setup_buttons_generate_working_skip_and_close_callbacks():
    tree = ast.parse(SETUP_PATH.read_text(encoding="utf-8"))
    selected_nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_SETUP_STEPS"
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "_setup_buttons")
    ]

    class FakeButtonMaker:
        def __init__(self):
            self.callbacks = []

        def data_button(self, _label, data, _position=None):
            self.callbacks.append(data)

        def build_menu(self, *_args, **_kwargs):
            return self.callbacks

    namespace = {"ButtonMaker": FakeButtonMaker}
    exec(
        compile(ast.Module(selected_nodes, type_ignores=[]), str(SETUP_PATH), "exec"),
        namespace,
    )

    first_callbacks = namespace["_setup_buttons"]("download_dir", 42)
    summary_callbacks = namespace["_setup_buttons"]("summary", 42)

    assert "setup skip 42 1" in first_callbacks
    assert "setup close 42" in first_callbacks
    assert "setup close 42" in summary_callbacks


@pytest.mark.asyncio
async def test_setup_callback_rejects_malformed_numbers_and_closes_cleanly():
    tree = ast.parse(SETUP_PATH.read_text(encoding="utf-8"))
    callback_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "setup_callback"
    )
    callback_node = ast.fix_missing_locations(callback_node)
    callback_node.decorator_list = []
    delete = AsyncMock()
    namespace = {
        "delete_message": delete,
        "edit_message": AsyncMock(),
        "_SETUP_STEPS": ["download_dir"],
        "_setup_message": lambda *_args: "message",
        "_setup_buttons": lambda *_args: [],
    }
    exec(
        compile(ast.Module([callback_node], type_ignores=[]), str(SETUP_PATH), "exec"),
        namespace,
    )

    bad_user = SimpleNamespace(
        data="setup close invalid",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(),
        answer=AsyncMock(),
    )
    await namespace["setup_callback"](None, bad_user)
    bad_user.answer.assert_awaited_once_with("Invalid callback.", show_alert=True)

    bad_step = SimpleNamespace(
        data="setup next 42 invalid",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(),
        answer=AsyncMock(),
    )
    await namespace["setup_callback"](None, bad_step)
    bad_step.answer.assert_awaited_once_with("Invalid step.", show_alert=True)

    close = SimpleNamespace(
        data="setup close 42",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(),
        answer=AsyncMock(),
    )
    await namespace["setup_callback"](None, close)
    close.answer.assert_awaited_once_with()
    delete.assert_awaited_once_with(close.message)


def test_speedtest_ports_neo_result_features_in_amaterasu_style():
    source = SPEEDTEST_PATH.read_text(encoding="utf-8")

    for heading in (
        "✦ NETWORK DIAGNOSTIC",
        "✦ SPEEDTEST COMPLETE",
        "✦ TEST SERVER",
        "✦ CLIENT NETWORK",
    ):
        assert heading in source
    for label in (
        "Download",
        "Upload",
        "Ping",
        "Received",
        "Sent",
        "Provider",
        "ISP Rating",
    ):
        assert f"<b>{label}</b> : " in source

    assert "speed_results.results.share" in source
    assert "await sync_to_async(speed_results.results.share)" in source
    assert 'photo = result.get("share") or share_url' in source
    assert "IP Address" not in source
    assert "client.get('ip')" not in source
    assert "_SPEEDTEST_LOCK.locked()" in source
    assert "if not isinstance(result, dict):" in source
    assert "The test completed, but its result data was invalid" in source


def test_speedtest_result_formatter_handles_missing_and_unsafe_service_data():
    tree = ast.parse(SPEEDTEST_PATH.read_text(encoding="utf-8"))
    helper_names = {
        "_safe_text",
        "_readable_size",
        "_readable_rate",
        "_decimal",
        "_result_message",
    }
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]

    def readable_size(value):
        return f"{float(value):.2f}B"

    namespace = {
        "escape": lambda value: (
            str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ),
        "get_readable_file_size": readable_size,
    }
    exec(
        compile(ast.Module(selected_nodes, type_ignores=[]), str(SPEEDTEST_PATH), "exec"),
        namespace,
    )

    text = namespace["_result_message"](
        {
            "download": 80,
            "upload": 40,
            "ping": 12.345,
            "server": {"name": "<unsafe>", "country": "BD", "cc": "BD"},
            "client": {"ip": "203.0.113.1", "isp": "Example & Co"},
        }
    )

    assert "10.00B/s" in text
    assert "5.00B/s" in text
    assert "12.35 ms" in text
    assert "&lt;unsafe&gt;" in text
    assert "Example &amp; Co" in text
    assert "203.0.113.1" not in text
    assert "Unknown" in text


@pytest.mark.asyncio
async def test_speedtest_share_failure_keeps_text_result_and_never_exposes_ip():
    from asyncio import Lock
    from copy import deepcopy
    from html import escape

    tree = ast.parse(SPEEDTEST_PATH.read_text(encoding="utf-8"))
    helper_names = {
        "_safe_text",
        "_readable_size",
        "_readable_rate",
        "_decimal",
        "_progress_message",
        "_result_message",
        "_failure_message",
        "speedtest",
    }
    selected_nodes = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_SPEEDTEST_LOCK"
                for target in node.targets
            )
        ) or (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in helper_names
        ):
            copied = deepcopy(node)
            if isinstance(copied, ast.AsyncFunctionDef):
                copied.decorator_list = []
            selected_nodes.append(copied)

    public_ip = "203.0.113.55"

    class FakeResults:
        def share(self):
            raise RuntimeError("share service unavailable")

        def dict(self):
            return {
                "download": 80_000_000,
                "upload": 40_000_000,
                "ping": 9.5,
                "bytes_received": 1_000,
                "bytes_sent": 500,
                "timestamp": "2026-08-10T12:00:00Z",
                "server": {
                    "name": "Dhaka",
                    "country": "Bangladesh",
                    "cc": "BD",
                    "sponsor": "Example",
                    "latency": 9.5,
                    "d": 2.5,
                    "lat": "23.8",
                    "lon": "90.4",
                },
                "client": {
                    "ip": public_ip,
                    "isp": "Example ISP",
                    "country": "BD",
                    "lat": "23.8",
                    "lon": "90.4",
                    "isprating": "5",
                },
            }

    class FakeSpeedtest:
        results = FakeResults()

        def get_best_server(self):
            return {"name": "Dhaka"}

        def download(self):
            return 80_000_000

        def upload(self):
            return 40_000_000

    async def run_sync(function, *args):
        return function(*args)

    status_message = SimpleNamespace(id=1)
    result_message = SimpleNamespace(id=2)
    send = AsyncMock(side_effect=[status_message, result_message])
    edit = AsyncMock()
    delete = AsyncMock()
    logger = SimpleNamespace(
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )

    class FakeSpeedtestError(Exception):
        pass

    namespace = {
        "Lock": Lock,
        "escape": escape,
        "ConfigRetrievalError": FakeSpeedtestError,
        "SpeedtestException": FakeSpeedtestError,
        "Speedtest": FakeSpeedtest,
        "LOGGER": logger,
        "sync_to_async": run_sync,
        "get_readable_file_size": lambda value: f"{float(value):.2f}B",
        "send_message": send,
        "edit_message": edit,
        "delete_message": delete,
    }
    exec(
        compile(ast.Module(selected_nodes, type_ignores=[]), str(SPEEDTEST_PATH), "exec"),
        namespace,
    )

    await namespace["speedtest"](None, SimpleNamespace())

    assert send.await_count == 2
    final_text = send.await_args_list[1].args[1]
    assert "✦ SPEEDTEST COMPLETE" in final_text
    assert "Example ISP" in final_text
    assert public_ip not in final_text
    assert send.await_args_list[1].kwargs["photo"] is None
    delete.assert_awaited_once_with(status_message)


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


def test_every_registered_command_family_is_available_to_command_sync():
    from bot.helper.telegram_helper.bot_commands import BotCommands
    from bot.helper.telegram_helper.command_sync import build_bot_command_menu

    BotCommands.refresh_commands()
    menu_commands = {item.command for item in build_bot_command_menu()}
    expected = set()
    for key in ("Start", "Login", *BotCommands.get_commands()):
        configured = getattr(BotCommands, f"{key}Command")
        expected.add(configured[0] if isinstance(configured, list) else configured)

    assert expected <= menu_commands
    assert len(menu_commands) <= 100


def test_every_static_command_handler_is_exposed_in_the_telegram_menu():
    from bot.helper.telegram_helper.bot_commands import BotCommands
    from bot.helper.telegram_helper.command_sync import build_bot_command_menu

    handler_attributes = set()
    pattern = r"command\(\s*BotCommands\.(\w+Command)"
    for path in (ROOT / "bot").rglob("*.py"):
        handler_attributes.update(findall(pattern, path.read_text(encoding="utf-8")))

    menu_commands = {item.command for item in build_bot_command_menu()}
    missing = set()
    for attribute in handler_attributes:
        configured = getattr(BotCommands, attribute)
        primary = configured[0] if isinstance(configured, list) else configured
        if primary not in menu_commands:
            missing.add(primary)

    assert not missing


def test_generated_telegram_commands_meet_bot_api_limits():
    from bot.helper.telegram_helper.command_sync import build_bot_command_menu

    menu = build_bot_command_menu()
    commands = [item.command for item in menu]

    assert len(commands) == len(set(commands))
    assert len(commands) <= 100
    assert all(1 <= len(command) <= 32 for command in commands)
    assert all(3 <= len(item.description) <= 256 for item in menu)


@pytest.mark.asyncio
async def test_command_sync_sets_and_reads_back_the_complete_menu(monkeypatch):
    from bot.helper.telegram_helper import command_sync

    class FakeBot:
        def __init__(self):
            self.registered = []

        async def set_bot_commands(self, commands):
            self.registered = list(commands)
            return True

        async def get_bot_commands(self):
            return self.registered

    async def resilient(operation, *args, **_kwargs):
        return await operation(*args)

    fake_bot = FakeBot()
    monkeypatch.setattr(command_sync.TgClient, "bot", fake_bot)
    monkeypatch.setattr(command_sync, "resilient_tg_operation", resilient)

    count = await command_sync.sync_bot_commands()

    assert count == 61
    assert len(fake_bot.registered) == 61


def test_filetolink_caption_icons_match_buttons():
    source = FILETOLINK_PATH.read_text(encoding="utf-8")

    assert '<b>⬇️ DOWNLOAD</b>' in source
    assert '<b>▶️ STREAM</b>' in source
    assert '<b>↓ Download</b>' not in source
    assert '<b>▶ Stream</b>' not in source


def test_megasdk_version_comes_from_the_base_image(monkeypatch):
    mega = ModuleType("mega")
    for name in (
        "MegaApi",
        "MegaCancelToken",
        "MegaError",
        "MegaListener",
        "MegaRequest",
        "MegaTransfer",
        "MegaUploadOptions",
    ):
        setattr(mega, name, type(name, (), {}))
    monkeypatch.setitem(modules, "mega", mega)
    monkeypatch.setenv("MEGA_SDK_VERSION", "v7.0.0")
    spec = spec_from_file_location("amaterasu_mega_sdk_version", MEGA_SDK_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.MEGA_SDK_VERSION == "7.0.0"


def test_megasdk_version_has_a_transition_fallback(monkeypatch):
    mega = ModuleType("mega")
    for name in (
        "MegaApi",
        "MegaCancelToken",
        "MegaError",
        "MegaListener",
        "MegaRequest",
        "MegaTransfer",
        "MegaUploadOptions",
    ):
        setattr(mega, name, type(name, (), {}))
    monkeypatch.setitem(modules, "mega", mega)
    monkeypatch.delenv("MEGA_SDK_VERSION", raising=False)
    spec = spec_from_file_location("amaterasu_mega_sdk_fallback", MEGA_SDK_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.MEGA_SDK_VERSION == "7.0.0"


def test_megasdk_version_is_na_when_bindings_are_missing(monkeypatch):
    mega = ModuleType("mega")
    monkeypatch.setitem(modules, "mega", mega)
    monkeypatch.setenv("MEGA_SDK_VERSION", "v7.0.0")
    spec = spec_from_file_location("amaterasu_mega_sdk_missing", MEGA_SDK_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.MEGA_SDK_AVAILABLE is False
    assert module.MEGA_SDK_VERSION == "N/A"


def test_base_image_uses_megasdk_without_megacmd():
    dockerfile = (ROOT / "Dockerfile.base").read_text(encoding="utf-8")
    build_script = (ROOT / "build.sh").read_text(encoding="utf-8")
    stats_source = (ROOT / "bot" / "modules" / "stats.py").read_text(
        encoding="utf-8"
    )

    assert "ENV MEGA_SDK_VERSION=${MEGA_SDK_VERSION}" in dockerfile
    assert "from mega import MegaApi" in dockerfile
    assert "from mega import MegaApi" in build_script
    assert "mega-version" not in stats_source

    combined = "\n".join((dockerfile, build_script))
    for obsolete_reference in (
        "apt-get install -y --no-install-recommends megacmd",
        "mega-cmd",
        "mega-get",
        "mega-ls",
        "mega-put",
        "mega-version",
    ):
        assert obsolete_reference not in combined


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
async def test_send_message_does_not_retry_an_unknown_peer(monkeypatch):
    from pyrogram.errors import PeerIdInvalid

    from bot.core.tg_client import TgClient
    from bot.helper.telegram_helper.message_utils import send_message

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=PeerIdInvalid()))
    monkeypatch.setattr(TgClient, "bot", bot)

    result = await send_message(3766303560, "This peer is not in the session cache")

    assert bot.send_message.await_count == 1
    assert "PEER_ID_INVALID" in result


@pytest.mark.asyncio
async def test_send_message_bounds_persistent_length_failures(monkeypatch):
    from pyrogram.errors import MessageTooLong

    from bot.core.tg_client import TgClient
    from bot.helper.telegram_helper.message_utils import send_message

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=MessageTooLong()))
    monkeypatch.setattr(TgClient, "bot", bot)

    result = await send_message(123, "x" * 5000)

    assert bot.send_message.await_count == 3
    assert "MESSAGE_TOO_LONG" in result


@pytest.mark.asyncio
async def test_send_message_entity_fallback_reaches_integer_chat_target(monkeypatch):
    from pyrogram.enums import ParseMode
    from pyrogram.errors import EntityBoundsInvalid

    from bot.core.tg_client import TgClient
    from bot.helper.telegram_helper.message_utils import send_message

    delivered = SimpleNamespace(id=99)
    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=[EntityBoundsInvalid(), delivered])
    )
    monkeypatch.setattr(TgClient, "bot", bot)

    result = await send_message(123, "broken <b>entities</b>")

    assert result is delivered
    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args_list[1].kwargs["parse_mode"] == ParseMode.DISABLED


@pytest.mark.asyncio
async def test_edit_message_bounds_persistent_markup_failures():
    from pyrogram.errors import ReplyMarkupInvalid

    from bot.helper.telegram_helper.message_utils import edit_message

    message = SimpleNamespace(
        media=None,
        edit=AsyncMock(side_effect=ReplyMarkupInvalid()),
    )

    result = await edit_message(message, "status", buttons=object())

    assert message.edit.await_count == 3
    assert "REPLY_MARKUP_INVALID" in result


@pytest.mark.asyncio
async def test_other_message_helpers_bound_flood_retries_and_keep_buttons(
    monkeypatch,
):
    from bot.core.tg_client import TgClient
    from bot.helper.telegram_helper import message_utils

    class RetryFlood(Exception):
        value = 0

    pause = AsyncMock()
    monkeypatch.setattr(message_utils, "FloodWait", RetryFlood)
    monkeypatch.setattr(message_utils, "sleep", pause)

    markup_message = SimpleNamespace(
        edit_reply_markup=AsyncMock(side_effect=RetryFlood())
    )
    await message_utils.edit_reply_markup(markup_message, object())
    assert markup_message.edit_reply_markup.await_count == 3

    buttons = object()
    file_message = SimpleNamespace(
        id=42,
        reply_document=AsyncMock(side_effect=RetryFlood()),
    )
    await message_utils.send_file(
        file_message,
        "report.txt",
        "Report",
        buttons,
    )
    assert file_message.reply_document.await_count == 3
    assert all(
        call.kwargs["reply_markup"] is buttons
        for call in file_message.reply_document.await_args_list
    )

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RetryFlood()))
    monkeypatch.setattr(TgClient, "user", None)
    monkeypatch.setattr(TgClient, "bot", bot)
    await message_utils.send_rss("RSS update", 123, 7)
    assert bot.send_message.await_count == 3

    assert pause.await_count == 6


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
