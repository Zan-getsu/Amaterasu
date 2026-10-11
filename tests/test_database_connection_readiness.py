"""Exercise startup's MongoDB readiness gate without starting bot services."""

import ast
from asyncio import run
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, PyMongoError, ServerSelectionTimeoutError
from pymongo.server_api import ServerApi

ROOT = Path(__file__).resolve().parents[1]


def load_definition(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(node for node in tree.body if getattr(node, "name", None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("reachable", [False, True])
def test_database_is_ready_only_after_successful_ping(reachable):
    collection = SimpleNamespace(create_index=AsyncMock())
    db = SimpleNamespace(
        blacklisted_users=collection,
        user_stats=collection,
        google_oauth_states=collection,
    )
    client = SimpleNamespace(
        admin=SimpleNamespace(command=AsyncMock()),
        amaterasu=db,
        close=MagicMock(),
    )
    if not reachable:
        client.admin.command.side_effect = ConfigurationError("DNS resolution timed out")
    namespace = {
        "AsyncIOMotorClient": MagicMock(return_value=client),
        "Config": SimpleNamespace(DATABASE_URL="mongodb+srv://example.invalid"),
        "ServerApi": lambda version: version,
        "LOGGER": MagicMock(),
        "PyMongoError": PyMongoError,
    }
    manager = load_definition("bot/helper/ext_utils/db_handler.py", "DbManager", namespace)()
    run(manager.connect())
    client.admin.command.assert_awaited_once_with("ping")
    if reachable:
        assert manager.db is db and not manager._return
        collection.create_index.assert_awaited()
        client.close.assert_not_called()
    else:
        assert manager.db is None and manager._return and manager._conn is None
        client.close.assert_called_once()
        collection.create_index.assert_not_awaited()


def test_startup_preserves_credentials_when_database_is_unavailable():
    database = SimpleNamespace(
        connect=AsyncMock(),
        db=None,
        migrate_from_wzmlx=AsyncMock(),
    )
    remove_tree = AsyncMock()
    namespace = {
        "Config": SimpleNamespace(DATABASE_URL="mongodb+srv://example.invalid"),
        "database": database,
        "LOGGER": MagicMock(),
        "aiopath": SimpleNamespace(exists=AsyncMock(return_value=True)),
        "rmtree": remove_tree,
    }
    load_settings = load_definition("bot/core/startup.py", "load_settings", namespace)
    run(load_settings())
    database.connect.assert_awaited_once()
    database.migrate_from_wzmlx.assert_not_awaited()
    remove_tree.assert_not_awaited()


@pytest.mark.parametrize(
    "uri,selection_timeout,connect_timeout",
    [
        ("mongodb://database.example", 30, 20),
        (
            "mongodb://database.example/?serverSelectionTimeoutMS=45000&connectTimeoutMS=25000",
            45,
            25,
        ),
    ],
)
def test_cold_discovery_uses_driver_defaults_or_uri_timeouts(
    uri, selection_timeout, connect_timeout
):
    collection = SimpleNamespace(create_index=AsyncMock())
    db = SimpleNamespace(
        blacklisted_users=collection,
        user_stats=collection,
        google_oauth_states=collection,
    )
    clients = []

    def client_factory(url, **kwargs):
        # Parse effective options with the actual driver, without opening sockets.
        with MongoClient(url, connect=False, **kwargs) as parser:
            options = parser.options

        def ping(command):
            assert command == "ping"
            # Model a cold replica-set discovery that needs eight seconds.
            if options.server_selection_timeout < 8:
                raise ServerSelectionTimeoutError("Discovery exceeded selection timeout")
            return {"ok": 1}

        client = SimpleNamespace(
            options=options,
            admin=SimpleNamespace(command=AsyncMock(side_effect=ping)),
            amaterasu=db,
            close=MagicMock(),
        )
        clients.append(client)
        return client

    namespace = {
        "AsyncIOMotorClient": client_factory,
        "Config": SimpleNamespace(DATABASE_URL=uri),
        "ServerApi": ServerApi,
        "LOGGER": MagicMock(),
        "PyMongoError": PyMongoError,
    }
    manager = load_definition("bot/helper/ext_utils/db_handler.py", "DbManager", namespace)()
    run(manager.connect())
    assert manager.db is db and not manager._return
    assert clients[0].options.server_selection_timeout == selection_timeout
    assert clients[0].options.pool_options.connect_timeout == connect_timeout
    clients[0].close.assert_not_called()
