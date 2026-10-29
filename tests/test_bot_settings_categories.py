import ast
import asyncio
import logging
from hashlib import sha256
from html import escape
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).parents[1]
SETTINGS_SOURCE = ROOT / "bot" / "modules" / "bot_settings.py"


def load_category_namespace(include_buttons=False):
    tree = ast.parse(SETTINGS_SOURCE.read_text(encoding="utf-8"))
    names = {
        "CONFIG_CATEGORIES",
        "DEFAULT_DESP",
        "FILETOLINK_WEB_VARS",
        "HIDDEN_VARS",
        "PROTECTED_VARS",
        "RESTART_VARS",
        "_visible_config_variables",
        "_config_category_for_key",
        "_config_keys_for_category",
        "_is_bool_variable",
        "_is_protected_variable",
        "_apply_filetolink_web_tuning",
        "_helper_bot_rows",
        "_helper_bot_summary",
        "_remove_helper_bot",
    }
    if include_buttons:
        names.add("get_buttons")
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            )
        )
    ]
    namespace = {}
    exec(
        compile(ast.Module(nodes, type_ignores=[]), str(SETTINGS_SOURCE), "exec"),
        namespace,
    )
    return namespace


def load_callback_handler(namespace):
    tree = ast.parse(SETTINGS_SOURCE.read_text(encoding="utf-8"))
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "edit_bot_settings"
    )
    handler.decorator_list = []
    exec(
        compile(ast.Module([handler], type_ignores=[]), str(SETTINGS_SOURCE), "exec"),
        namespace,
    )
    return namespace["edit_bot_settings"]


def test_split_size_is_derived_after_premium_session_detection():
    main = (ROOT / "bot" / "__main__.py").read_text(encoding="utf-8")
    common = (ROOT / "bot" / "helper" / "common.py").read_text(encoding="utf-8")
    settings = SETTINGS_SOURCE.read_text(encoding="utf-8")

    assert main.index("await TgClient.start_user()") < main.index(
        "await gather(load_configurations(), update_variables())"
    )
    assert "or TgClient.MAX_SPLIT_SIZE" in common
    assert 'get("LEECH_SPLIT_SIZE")' not in common
    assert "LEECH_SPLIT_SIZE" not in settings


def test_group_uploads_do_not_require_user_admin_privileges():
    common = (ROOT / "bot" / "helper" / "common.py").read_text(encoding="utf-8")
    user_access_check = common.split("if self.transmission_mode in (\"user\", \"both\"):", 1)[1]
    user_access_check = user_access_check.split("try:\n                    chat = await self.client.get_chat", 1)[0]

    assert "elif chat.type == ChatType.CHANNEL:" in user_access_check
    assert "can_post_messages" in user_access_check
    assert "can_manage_chat" not in user_access_check


def test_common_and_feature_variables_have_canonical_categories():
    namespace = load_category_namespace()
    category_for = namespace["_config_category_for_key"]

    assert category_for("BASE_URL") == "general"
    assert category_for("HELPER_TOKENS") == "telegram"
    assert category_for("MULTI_TOKEN7") == "telegram"
    assert category_for("FILETOLINK_GETFILE_CONCURRENCY") == "filetolink"
    assert category_for("FILETOLINK_PREFETCH_CHUNKS") == "filetolink"
    assert category_for("USE_HYPER") == "hyper"


def test_credentials_and_dynamic_stream_tokens_are_protected():
    namespace = load_category_namespace()
    is_protected = namespace["_is_protected_variable"]

    for key in (
        "BOT_TOKEN",
        "HELPER_TOKENS",
        "HELPER_STRINGS",
        "HELPER_BOT_PROXIES",
        "WEB_ACCESS_PASSWORD",
        "AMATERASU_WEB_SECRET",
        "JIODRIVE_TOKEN",
        "MULTI_TOKEN7",
    ):
        assert is_protected(key), key

    assert not is_protected("BASE_URL")


def test_every_visible_config_variable_has_one_explicit_canonical_home():
    from bot.core.config_manager import Config

    namespace = load_category_namespace()
    categories = namespace["CONFIG_CATEGORIES"]
    category_for = namespace["_config_category_for_key"]
    hidden = namespace["HIDDEN_VARS"]

    explicit_keys = [
        key
        for slug, (_, _, keys) in categories.items()
        if slug != "advanced"
        for key in keys
    ]
    assert len(explicit_keys) == len(set(explicit_keys))

    system_keys = categories["system"][2]
    assert "AUTO_UPDATE" in system_keys
    assert "AUTO_UPDATE" in namespace["RESTART_VARS"]

    visible_keys = {
        key
        for key in Config.get_all()
        if not key.startswith("DISABLE_") and key not in hidden
    }
    uncategorized = {
        key
        for key in visible_keys
        if category_for(key) == "advanced"
    }
    assert not uncategorized
    assert {
        "FQDN",
        "HAS_SSL",
        "NO_PORT",
        "BASE_URL_PORT",
    }.isdisjoint(visible_keys)


class FakeButtonMaker:
    def __init__(self):
        self.buttons = []

    def data_button(self, label, data, *args, **kwargs):
        self.buttons.append((label, data, args, kwargs))

    def build_menu(self, columns):
        return {"columns": columns, "buttons": self.buttons}


@pytest.fixture
def helper_settings(monkeypatch):
    from bot.core.config_manager import Config
    from bot.core.tg_client import TelegramClient

    tokens = ["101:SECRET_A", "202:SECRET_B", "303:SECRET_C"]
    monkeypatch.setattr(Config, "HELPER_TOKENS", " ".join(tokens))
    monkeypatch.setattr(Config, "HELPER_BOT_PROXIES", "proxy-a\n\nproxy-c")
    busy = SimpleNamespace(is_connected=True, me=SimpleNamespace(id=101, username="busy<&>"))
    cooling = SimpleNamespace(
        is_connected=lambda: True, me=SimpleNamespace(id=202, username="cooling"),
        _amaterasu_download_pacer=SimpleNamespace(flood_until=112),
    )
    pending = SimpleNamespace(is_connected=True, me=SimpleNamespace(id=404, username="pending"))
    clients = SimpleNamespace(
        helper_bot_clients={tokens[0]: busy, tokens[1]: cooling},
        helper_bots={7: busy, 9: cooling, 11: pending}, helper_loads={},
        stream_clients={2: busy}, stream_loads={2: 1},
    )
    namespace = load_category_namespace(include_buttons=True)
    namespace.update(
        Config=Config, TgClient=clients, TelegramClient=TelegramClient,
        tg_transfer=SimpleNamespace(_global_work_loads={7: 2, 9: 0}),
        monotonic=lambda: 100, ceil=ceil, sha256=sha256, escape=escape,
        ButtonMaker=FakeButtonMaker, ButtonStyle=SimpleNamespace(DANGER="danger", PRIMARY="primary"),
        environ={}, _helper_tokens_lock=asyncio.Lock(),
        database=SimpleNamespace(db=object(), update_config=AsyncMock()),
        LOGGER=logging.getLogger(__name__), handler_dict={},
    )
    return namespace, tokens, clients


def test_helper_snapshot_shows_actual_assignments_and_no_credentials(helper_settings):
    namespace, tokens, _clients = helper_settings
    rows = namespace["_helper_bot_rows"]()
    assert len(rows) == 4
    assert rows[0]["jobs"] == 3
    assert "2 Hyper / 1 stream jobs" in rows[0]["status"]
    assert rows[1]["cooldown"] == 12
    assert rows[2]["status"] == "Not connected"
    assert not rows[3]["configured"]
    assert "pending removal" in rows[3]["status"]
    assert all(token not in repr(rows) for token in tokens)
    summary = namespace["_helper_bot_summary"](rows)
    assert "<b>Configured:</b> 3" in summary
    assert "<b>Connected:</b> 3" in summary
    assert "<b>Busy:</b> 1" in summary
    assert "<b>Cooldown:</b> 1" in summary


@pytest.mark.asyncio
async def test_helper_page_and_variable_details_expose_management_without_tokens(helper_settings):
    namespace, tokens, _clients = helper_settings
    _, root_menu = await namespace["get_buttons"]()
    assert any(data == "botset helpers 0" for _, data, _, _ in root_menu["buttons"])
    text, menu = await namespace["get_buttons"]("HELPER_TOKENS", "editvar")
    assert "<b>Configured:</b> 3" in text
    assert any(data == "botset helpers 0" for _, data, _, _ in menu["buttons"])
    text, menu = await namespace["get_buttons"]("helpers_0")
    assert "busy&lt;&amp;&gt;" in text
    callbacks = [data for _, data, _, _ in menu["buttons"]]
    assert sum(data.startswith("botset helper_remove ") for data in callbacks) == 3
    assert all(len(data.encode()) <= 64 for data in callbacks)
    assert all(token not in text + repr(menu) and token.split(":")[1] not in text + repr(menu) for token in tokens)

    reference = namespace["_helper_bot_rows"]()[0]["ref"]
    namespace["environ"]["HELPER_TOKENS"] = "external-setting"
    text, menu = await namespace["get_buttons"](reference, "helper_remove")
    assert "Restart" in text and "Deployment environment override" in text
    assert any(data == f"botset helper_confirm {reference}" for _, data, _, _ in menu["buttons"])
    namespace["database"].update_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_helper_page_pagination_and_empty_pool(helper_settings):
    namespace, _tokens, _clients = helper_settings
    namespace["Config"].set("HELPER_TOKENS", " ".join(f"{i}:SECRET" for i in range(10)))
    _, menu = await namespace["get_buttons"]("helpers_0")
    assert any(data == "botset helpers 1" for _, data, _, _ in menu["buttons"])
    assert sum(data.startswith("botset helper_remove ") for _, data, _, _ in menu["buttons"]) == 6
    _, menu = await namespace["get_buttons"]("helpers_999")
    assert any(data == "botset helpers 1" for _, data, _, _ in menu["buttons"])  # Clamped refresh.
    namespace["Config"].set("HELPER_TOKENS", "")
    namespace["TgClient"].helper_bots = {}
    text, menu = await namespace["get_buttons"]("helpers_0")
    assert "No helper bots configured" in text
    assert not any(data.startswith("botset helper_remove ") for _, data, _, _ in menu["buttons"])


@pytest.mark.asyncio
async def test_helper_removal_keeps_proxy_alignment_and_running_clients(helper_settings):
    namespace, tokens, clients = helper_settings
    reference = sha256(tokens[1].encode()).hexdigest()[:16]
    before = dict(clients.helper_bots)
    assert await namespace["_remove_helper_bot"](reference)
    assert namespace["Config"].HELPER_TOKENS.split() == [tokens[0], tokens[2]]
    assert namespace["Config"].HELPER_BOT_PROXIES == "proxy-a\nproxy-c"
    namespace["database"].update_config.assert_awaited_once_with({
        "HELPER_TOKENS": f"{tokens[0]} {tokens[2]}", "HELPER_BOT_PROXIES": "proxy-a\nproxy-c",
    })
    assert clients.helper_bots == before
    assert not await namespace["_remove_helper_bot"](reference)
    namespace["database"].update_config.assert_awaited_once()
    assert any(not row["configured"] and row["name"] == "@cooling" for row in namespace["_helper_bot_rows"]())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["offline", "save-error"])
async def test_helper_removal_never_reports_an_unsaved_config_change(helper_settings, failure):
    namespace, tokens, _clients = helper_settings
    config = namespace["Config"]
    previous = config.HELPER_TOKENS, config.HELPER_BOT_PROXIES
    if failure == "offline":
        namespace["database"].db = None
    else:
        namespace["database"].update_config.side_effect = OSError("database down")
    with pytest.raises((ValueError, OSError)):
        await namespace["_remove_helper_bot"](sha256(tokens[0].encode()).hexdigest()[:16])
    assert (config.HELPER_TOKENS, config.HELPER_BOT_PROXIES) == previous


@pytest.mark.asyncio
async def test_helper_removal_uses_stable_references_across_concurrent_clicks(helper_settings):
    namespace, tokens, _clients = helper_settings
    await asyncio.gather(*(
        namespace["_remove_helper_bot"](sha256(token.encode()).hexdigest()[:16]) for token in tokens[:2]
    ))
    assert namespace["Config"].HELPER_TOKENS == tokens[2]
    assert namespace["Config"].HELPER_BOT_PROXIES == "proxy-c"
    assert namespace["database"].update_config.await_count == 2


@pytest.mark.asyncio
async def test_helper_callbacks_open_confirmation_and_persist_only_after_confirm(helper_settings):
    namespace, tokens, _clients = helper_settings
    namespace.update(update_buttons=AsyncMock(), send_message=AsyncMock())
    handler = load_callback_handler(namespace)
    message = SimpleNamespace(chat=SimpleNamespace(id=99))

    def query(data):
        return SimpleNamespace(data=data, message=message, answer=AsyncMock())

    await handler(None, query("botset helpers 1"))
    namespace["update_buttons"].assert_awaited_with(message, "helpers_1")
    reference = sha256(tokens[0].encode()).hexdigest()[:16]
    await handler(None, query(f"botset helper_remove {reference}"))
    namespace["update_buttons"].assert_awaited_with(message, reference, "helper_remove")
    namespace["database"].update_config.assert_not_awaited()
    await handler(None, query(f"botset helper_confirm {reference}"))
    assert namespace["Config"].HELPER_TOKENS.split() == tokens[1:]
    namespace["update_buttons"].assert_awaited_with(message, "helpers_0")
    namespace["send_message"].assert_not_awaited()


@pytest.mark.asyncio
async def test_helper_callback_failure_and_stale_confirmation_keep_config_safe(helper_settings):
    namespace, tokens, _clients = helper_settings
    namespace.update(update_buttons=AsyncMock(), send_message=AsyncMock())
    handler = load_callback_handler(namespace)
    message = SimpleNamespace(chat=SimpleNamespace(id=99))
    namespace["database"].update_config.side_effect = OSError(tokens[0])
    reference = sha256(tokens[0].encode()).hexdigest()[:16]
    await handler(None, SimpleNamespace(data=f"botset helper_confirm {reference}", message=message, answer=AsyncMock()))
    assert namespace["Config"].HELPER_TOKENS.split() == tokens
    assert tokens[0] not in repr(namespace["send_message"].call_args)
    namespace["database"].update_config.reset_mock()
    await handler(None, SimpleNamespace(data="botset helper_confirm bogus", message=message, answer=AsyncMock()))
    namespace["database"].update_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_removing_all_helpers_saves_empty_lists_without_stopping_clients(helper_settings):
    namespace, tokens, clients = helper_settings
    for token in tokens:
        assert await namespace["_remove_helper_bot"](sha256(token.encode()).hexdigest()[:16])
    assert namespace["Config"].HELPER_TOKENS == ""
    assert namespace["Config"].HELPER_BOT_PROXIES == ""
    assert len(clients.helper_bots) == 3
    assert all(not row["configured"] for row in namespace["_helper_bot_rows"]())


@pytest.mark.asyncio
async def test_category_menu_and_filetolink_page_render_related_variables():
    namespace = load_category_namespace(include_buttons=True)
    config_values = {
        "BASE_URL": "https://example.com",
        "BIN_CHANNEL": -1001,
        "FILETOLINK_GETFILE_CONCURRENCY": 8,
        "FILETOLINK_PREFETCH_CHUNKS": 4,
        "USE_HELPER_BOTS_FOR_FILETOLINK": True,
        "USE_HYPER": True,
    }
    namespace.update(
        {
            "ButtonMaker": FakeButtonMaker,
            "ButtonStyle": SimpleNamespace(DANGER="danger", PRIMARY="primary"),
            "Config": SimpleNamespace(
                get=lambda key: config_values.get(key),
                get_all=lambda: config_values,
            ),
            "escape": escape,
            "start": 0,
        }
    )
    get_buttons = namespace["get_buttons"]

    category_text, category_menu = await get_buttons("var")
    category_callbacks = {
        data for _, data, _, _ in category_menu["buttons"]
    }
    assert "CONFIG CATEGORIES" in category_text
    assert "botset category general" in category_callbacks
    assert "botset category filetolink" in category_callbacks
    assert "botset category hyper" in category_callbacks
    assert "botset category all" in category_callbacks

    filetolink_text, filetolink_menu = await get_buttons("varcat_filetolink")
    filetolink_callbacks = {
        data for _, data, _, _ in filetolink_menu["buttons"]
    }
    assert "FILETOLINK" in filetolink_text
    assert "botset editvar BIN_CHANNEL" in filetolink_callbacks
    assert (
        "botset editvar FILETOLINK_GETFILE_CONCURRENCY"
        in filetolink_callbacks
    )
    assert "botset editvar USE_HYPER" not in filetolink_callbacks
    assert "botset editvar BASE_URL" not in filetolink_callbacks

    _, bool_menu = await get_buttons(
        "USE_HELPER_BOTS_FOR_FILETOLINK",
        "editvar",
    )
    bool_callbacks = {data for _, data, _, _ in bool_menu["buttons"]}
    assert "botset boolvar USE_HELPER_BOTS_FOR_FILETOLINK on" in bool_callbacks
    assert "botset boolvar USE_HELPER_BOTS_FOR_FILETOLINK off" in bool_callbacks
    assert (
        "botset editvar USE_HELPER_BOTS_FOR_FILETOLINK edit"
        not in bool_callbacks
    )


def test_all_generated_variable_callbacks_fit_telegram_limit():
    from bot.core.config_manager import Config

    namespace = load_category_namespace()
    hidden = namespace["HIDDEN_VARS"]
    visible_keys = {
        key
        for key in Config.get_all()
        if not key.startswith("DISABLE_") and key not in hidden
    }
    callback_templates = (
        "botset editvar {key}",
        "botset editvar {key} edit",
        "botset showvar {key}",
        "botset resetvar {key}",
        "botset boolvar {key} off",
    )

    for key in visible_keys:
        for template in callback_templates:
            callback = template.format(key=key)
            assert len(callback.encode("utf-8")) <= 64, callback


@pytest.mark.asyncio
async def test_filetolink_tuning_exports_values_and_restarts_web_worker():
    namespace = load_category_namespace()
    environment = {}
    calls = []

    class Process:
        async def wait(self):
            calls.append("waited")
            return 0

    async def create_subprocess_exec(*args):
        calls.append(args)
        return Process()

    async def start_web_server():
        calls.append("started")

    values = {
        "FILETOLINK_ADAPTIVE_STREAMING": True,
        "FILETOLINK_GETFILE_CONCURRENCY": 8,
        "FILETOLINK_PREFETCH_CHUNKS": 4,
    }
    namespace.update(
        {
            "Config": SimpleNamespace(get=values.get),
            "create_subprocess_exec": create_subprocess_exec,
            "environ": environment,
            "start_web_server": start_web_server,
        }
    )

    await namespace["_apply_filetolink_web_tuning"]()

    assert environment == {
        "FILETOLINK_ADAPTIVE_STREAMING": "True",
        "FILETOLINK_GETFILE_CONCURRENCY": "8",
        "FILETOLINK_PREFETCH_CHUNKS": "4",
    }
    assert ("pkill", "-9", "-f", "gunicorn") in calls
    assert calls[-2:] == ["waited", "started"]


@pytest.mark.asyncio
async def test_category_and_pagination_callbacks_reach_expected_pages():
    namespace = load_category_namespace()
    rendered = []

    async def update_buttons(_message, key, *_args):
        rendered.append(key)

    class Query:
        def __init__(self, data):
            self.data = data
            self.message = SimpleNamespace(chat=SimpleNamespace(id=99))

        async def answer(self, *_args, **_kwargs):
            return None

    namespace.update(
        {
            "handler_dict": {},
            "start": 30,
            "state": "view",
            "update_buttons": update_buttons,
        }
    )
    edit_bot_settings = load_callback_handler(namespace)

    await edit_bot_settings(None, Query("botset category filetolink"))
    assert namespace["start"] == 0
    assert rendered[-1] == "varcat_filetolink"

    await edit_bot_settings(None, Query("botset start varcat_filetolink 10"))
    assert namespace["start"] == 10
    assert rendered[-1] == "varcat_filetolink"
