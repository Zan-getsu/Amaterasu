import ast
from html import escape
from pathlib import Path
from types import SimpleNamespace

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
