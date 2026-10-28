"""Premium leech routing with fresh session-string peer caches."""

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOT_LIMIT = 2097152000
PREMIUM_LIMIT = 4194304000
CHANNEL_ID = -1001234567890
CHAT_TYPES = SimpleNamespace(
    CHANNEL="channel", SUPERGROUP="supergroup", GROUP="group", FORUM="forum"
)


class PeerIdInvalid(Exception):
    pass


class ChannelInvalid(Exception):
    pass


def load_method(path, class_name, method_name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    node = next(node for node in cls.body if getattr(node, "name", "") == method_name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[method_name]


def make_clients(error=None, premium=True, can_post=True, dialogs=None, timeout=asyncio.timeout):
    member = SimpleNamespace(
        privileges=SimpleNamespace(
            can_post_messages=can_post,
            can_manage_chat=True,
            can_delete_messages=True,
        )
    )
    chat = SimpleNamespace(
        id=CHANNEL_ID, type=CHAT_TYPES.CHANNEL, get_member=AsyncMock(return_value=member)
    )

    async def get_dialogs():
        for item in dialogs if dialogs is not None else [chat]:
            await asyncio.sleep(0)
            yield SimpleNamespace(chat=item)

    user = SimpleNamespace(
        me=SimpleNamespace(id=200, is_premium=premium),
        get_chat=AsyncMock(side_effect=error, return_value=chat),
        get_dialogs=Mock(side_effect=get_dialogs),
    )
    method = load_method(
        "bot/core/tg_client.py",
        "TgClient",
        "get_user_chat",
        {
            "PeerIdInvalid": PeerIdInvalid,
            "ChannelInvalid": ChannelInvalid,
            "_asyncio": SimpleNamespace(timeout=timeout),
            "LOGGER": logging.getLogger(__name__),
        },
    )
    clients = type(
        "Clients",
        (),
        {
            "user": user,
            "IS_PREMIUM_USER": premium,
            "MAX_SPLIT_SIZE": PREMIUM_LIMIT if premium else BOT_LIMIT,
            "get_user_chat": method,
        },
    )
    bot = SimpleNamespace(me=SimpleNamespace(id=100), get_chat=AsyncMock(return_value=chat))
    return clients, bot, chat


def make_task(clients, bot, dump=CHANNEL_ID, bot_trans=False, split_size=0):
    config = SimpleNamespace(
        NAME_SWAP="",
        RCLONE_FLAGS="",
        TRANSMISSION_MODE="both",
        UPLOAD_PATHS={},
        FFMPEG_CMDS={},
        LEECH_DUMP_CHAT=dump,
        EQUAL_SPLITS=False,
        AS_DOCUMENT=True,
        THUMBNAIL_LAYOUT="",
    )
    task = SimpleNamespace(
        _prepare_leech_dumps=AsyncMock(),
        _normalize_command_leech_destination=AsyncMock(),
        name_swap="",
        user_dict={},
        rc_flags="",
        link="https://example.com/file.mkv",
        is_jd=True,
        user_id=1,
        up_dest="",
        category="",
        ffmpeg_cmds=None,
        is_leech=True,
        bot_trans=bot_trans,
        user_trans=False,
        hybrid_leech=False,
        client=bot,
        is_super_chat=False,
        split_size=split_size,
        as_doc=True,
        thumbnail_layout="",
        thumb="",
    )
    before_start = load_method(
        "bot/helper/common.py",
        "TaskConfig",
        "before_start",
        {
            "Config": config,
            "TgClient": clients,
            "ChatType": CHAT_TYPES,
            "LOGGER": logging.getLogger(__name__),
            "excluded_extensions": [],
        },
    )
    return task, before_start


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [PeerIdInvalid("unknown peer"), ChannelInvalid("missing access hash")]
)
async def test_fresh_session_recovers_admin_channel_and_retains_premium_limit(error, caplog):
    clients, bot, chat = make_clients(error=error)
    task, before_start = make_task(clients, bot)
    with caplog.at_level(logging.INFO):
        await before_start(task)
    assert task.transmission_mode == "both"
    assert task.split_size == task.max_split_size == PREMIUM_LIMIT
    clients.user.get_dialogs.assert_called_once()
    assert "resolved Telegram chat" in caplog.text
    assert "requested=both effective=both" in caplog.text
    assert "user_premium=True" in caplog.text
    assert "split_size=4194304000" in caplog.text
    assert chat.get_member.await_count == 2


@pytest.mark.asyncio
async def test_known_channel_does_not_scan_dialogs():
    clients, bot, _ = make_clients()
    task, before_start = make_task(clients, bot)
    await before_start(task)
    assert task.max_split_size == PREMIUM_LIMIT
    clients.user.get_dialogs.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_searches_past_unrelated_dialogs():
    clients, _, chat = make_clients(error=PeerIdInvalid(), dialogs=[])

    async def dialogs():
        yield SimpleNamespace(chat=SimpleNamespace(id=123))
        yield SimpleNamespace(chat=chat)

    clients.user.get_dialogs.side_effect = dialogs
    assert await clients.get_user_chat(CHANNEL_ID) is chat


@pytest.mark.asyncio
async def test_missing_channel_keeps_safe_bot_limit_and_logs_reason(caplog):
    clients, bot, _ = make_clients(error=PeerIdInvalid("unknown channel"), dialogs=[])
    task, before_start = make_task(clients, bot)
    with caplog.at_level(logging.INFO):
        await before_start(task)
    assert task.transmission_mode == "bot"
    assert task.split_size == task.max_split_size == BOT_LIMIT
    assert "PeerIdInvalid: unknown channel" in caplog.text
    assert "requested=both effective=bot" in caplog.text


@pytest.mark.asyncio
async def test_dialog_refresh_is_time_bounded():
    clients, _, _ = make_clients(error=PeerIdInvalid(), timeout=lambda _: asyncio.timeout(0))

    async def dialogs():
        await asyncio.sleep(1)
        yield SimpleNamespace(chat=SimpleNamespace(id=CHANNEL_ID))

    clients.user.get_dialogs.side_effect = dialogs
    with pytest.raises(TimeoutError):
        await clients.get_user_chat(CHANNEL_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,chat_id", [(RuntimeError("disconnected"), CHANNEL_ID), (PeerIdInvalid(), "@unknown")]
)
async def test_unrelated_errors_and_unknown_usernames_do_not_scan_dialogs(error, chat_id):
    clients, _, _ = make_clients(error=error)
    with pytest.raises(type(error)):
        await clients.get_user_chat(chat_id)
    clients.user.get_dialogs.assert_not_called()


@pytest.mark.asyncio
async def test_user_without_post_permission_still_falls_back(caplog):
    clients, bot, _ = make_clients(can_post=False)
    task, before_start = make_task(clients, bot)
    with caplog.at_level(logging.WARNING):
        await before_start(task)
    assert task.transmission_mode == "bot"
    assert task.max_split_size == BOT_LIMIT
    assert "lacks permission to post" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "premium,bot_trans,expected", [(False, False, BOT_LIMIT), (True, True, BOT_LIMIT)]
)
async def test_nonpremium_and_explicit_bot_tasks_keep_two_gb_limit(premium, bot_trans, expected):
    clients, bot, _ = make_clients(premium=premium)
    task, before_start = make_task(clients, bot, bot_trans=bot_trans)
    await before_start(task)
    assert task.split_size == task.max_split_size == expected


@pytest.mark.asyncio
async def test_explicit_smaller_split_is_preserved():
    clients, bot, _ = make_clients()
    task, before_start = make_task(clients, bot, split_size="1073741824")
    await before_start(task)
    assert task.split_size == 1073741824
    assert task.max_split_size == PREMIUM_LIMIT


@pytest.mark.asyncio
async def test_missing_user_session_keeps_safe_limit_and_logs_reason(caplog):
    clients, bot, _ = make_clients()
    clients.user = None
    task, before_start = make_task(clients, bot)
    with caplog.at_level(logging.WARNING):
        await before_start(task)
    assert task.max_split_size == BOT_LIMIT
    assert "user session is unavailable" in caplog.text


@pytest.mark.asyncio
async def test_three_gb_file_is_not_split_after_peer_recovery():
    clients, bot, _ = make_clients(error=PeerIdInvalid())
    task, before_start = make_task(clients, bot)
    await before_start(task)
    task.is_file = True
    split = load_method(
        "bot/helper/common.py",
        "TaskConfig",
        "proceed_split",
        {
            "get_path_size": AsyncMock(return_value=3 * 1024**3),
        },
    )
    await split(task, "/downloads/file.mkv", "gid")
    assert task.files_to_proceed == {}
