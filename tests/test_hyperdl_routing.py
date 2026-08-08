import ast
import asyncio
import json
import logging
import re
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
DOWNLOAD_SOURCE = (
    ROOT
    / "bot"
    / "helper"
    / "mirror_leech_utils"
    / "download_utils"
    / "telegram_download.py"
)
HYPERDL_SOURCE = ROOT / "bot" / "helper" / "ext_utils" / "hyperdl_utils.py"
BOT_UTILS_SOURCE = ROOT / "bot" / "helper" / "ext_utils" / "bot_utils.py"
FILES_UTILS_SOURCE = ROOT / "bot" / "helper" / "ext_utils" / "files_utils.py"
MEDIA_UTILS_SOURCE = ROOT / "bot" / "helper" / "ext_utils" / "media_utils.py"
TELEGRAM_UPLOADER_SOURCE = (
    ROOT
    / "bot"
    / "helper"
    / "mirror_leech_utils"
    / "upload_utils"
    / "telegram_uploader.py"
)
MESSAGE_UTILS_SOURCE = (
    ROOT / "bot" / "helper" / "telegram_helper" / "message_utils.py"
)
MIRROR_SOURCE = ROOT / "bot" / "modules" / "mirror_leech.py"
UPHOSTER_SOURCE = ROOT / "bot" / "modules" / "uphoster.py"


def load_top_level_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    exec(compile(ast.Module(functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def load_method(path, class_name, method_name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    exec(compile(ast.Module([method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[method_name]


def load_extract_parser():
    tree = ast.parse(BOT_UTILS_SOURCE.read_text(encoding="utf-8"))
    names = {
        "_SWITCH_ARGS",
        "_OPTIONAL_VALUE_ARGS",
        "_SINGLE_VALUE_ARGS",
        "_RCLONE_PATH",
    }
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            )
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name in {"_looks_like_download_input", "arg_parser"}
        )
    ]
    namespace = {"re_compile": re.compile}
    exec(
        compile(
            ast.Module(nodes, type_ignores=[]),
            str(BOT_UTILS_SOURCE),
            "exec",
        ),
        namespace,
    )
    return namespace["arg_parser"]


def load_archive_detectors():
    tree = ast.parse(FILES_UTILS_SOURCE.read_text(encoding="utf-8"))
    names = {"FIRST_SPLIT_REGEX", "SPLIT_REGEX"}
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            )
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name in {"is_first_archive_split", "is_archive_split"}
        )
    ]
    namespace = {"I": re.I, "re_search": re.search}
    exec(
        compile(
            ast.Module(nodes, type_ignores=[]),
            str(FILES_UTILS_SOURCE),
            "exec",
        ),
        namespace,
    )
    return namespace["is_first_archive_split"], namespace["is_archive_split"]


def extract_args():
    return {"-e": False, "-z": False, "-n": "", "link": ""}


def load_media_quality():
    namespace = load_top_level_functions(
        MEDIA_UTILS_SOURCE,
        {"_get_media_quality"},
        {},
    )
    return namespace["_get_media_quality"]


def test_media_quality_finds_video_after_audio_stream():
    streams = [
        {"codec_type": "audio", "codec_name": "aac"},
        {"codec_type": "video", "codec_name": "hevc", "height": 1080},
    ]

    assert load_media_quality()(streams) == "1080p"


def test_media_quality_ignores_attached_cover_art():
    streams = [
        {
            "codec_type": "video",
            "codec_name": "mjpeg",
            "height": 3000,
            "disposition": {"attached_pic": 1},
        },
        {"codec_type": "video", "codec_name": "h264", "height": 720},
    ]

    assert load_media_quality()(streams) == "720p"


def test_media_quality_handles_missing_height_safely():
    streams = [{"codec_type": "video", "codec_name": "h264"}]

    assert load_media_quality()(streams) == ""


def test_media_quality_supports_real_mjpeg_video_as_fallback():
    streams = [
        {"codec_type": "video", "codec_name": "mjpeg", "height": 1080}
    ]

    assert load_media_quality()(streams) == "1080p"


def test_get_media_info_reads_quality_when_audio_stream_is_first():
    payload = {
        "format": {"duration": "125.4"},
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "tags": {"language": "eng"},
            },
            {"codec_type": "video", "codec_name": "hevc", "height": 1080},
            {"codec_type": "subtitle", "tags": {"language": "spa"}},
        ],
    }

    async def cmd_exec(_command):
        return json.dumps(payload), "", 0

    class Language:
        @staticmethod
        def get(code):
            return SimpleNamespace(display_name=lambda: code)

    namespace = {
        "Language": Language,
        "LOGGER": SimpleNamespace(error=lambda *_args, **_kwargs: None),
        "cmd_exec": cmd_exec,
        "json": json,
        "suppress": suppress,
    }
    load_top_level_functions(
        MEDIA_UTILS_SOURCE,
        {"_get_media_quality", "get_media_info"},
        namespace,
    )

    result = asyncio.run(namespace["get_media_info"]("example.mkv", True))

    assert result == (125, "1080p", "eng", "spa")


def test_leech_caption_quality_is_wired_to_media_probe():
    source = TELEGRAM_UPLOADER_SOURCE.read_text(encoding="utf-8")

    assert "dur, qual, lang, subs = await get_media_info(up_path, True)" in source
    assert "quality=qual" in source


def test_autorename_caption_supports_quality_and_safe_unknown_variables():
    source = (ROOT / "bot" / "modules" / "autorename.py").read_text(
        encoding="utf-8"
    )

    assert "await get_media_info(local_path, True)" in source
    assert "quality=quality" in source
    assert "user_caption.format_map(" in source


def test_extract_password_after_link_is_parsed():
    args = extract_args()
    load_extract_parser()(
        "https://example.com/file.rar -e password".split(), args
    )

    assert args["link"] == "https://example.com/file.rar"
    assert args["-e"] == "password"


def test_extract_password_keeps_wzmlx_compatible_spaces_until_next_option():
    args = extract_args()
    load_extract_parser()(
        "https://example.com/file.rar -e multi word password -n release".split(),
        args,
    )

    assert args["link"] == "https://example.com/file.rar"
    assert args["-e"] == "multi word password"
    assert args["-n"] == "release"


def test_bare_extract_flag_before_link_does_not_consume_link():
    args = extract_args()
    load_extract_parser()("-e https://example.com/file.rar".split(), args)

    assert args["link"] == "https://example.com/file.rar"
    assert args["-e"] is True


def test_non_password_optional_flags_still_consume_one_value_only():
    args = {"-b": False, "link": ""}
    load_extract_parser()("-b 1:3 local-file.bin".split(), args)

    assert args["-b"] == "1:3"
    assert args["link"] == "local-file.bin"


def test_command_readers_collapse_repeated_whitespace():
    for relative_path in (
        "bot/modules/category_select.py",
        "bot/modules/clone.py",
        "bot/modules/mirror_leech.py",
        "bot/modules/uphoster.py",
        "bot/modules/ytdlp.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert 'text[0].split()' in source
        assert 'text[0].split(" ")' not in source

def test_rar_numeric_multipart_first_volume_is_detected():
    is_first_archive_split, is_archive_split = load_archive_detectors()

    assert is_first_archive_split("release.rar.001")
    assert not is_first_archive_split("release.rar.002")
    assert is_archive_split("release.rar.001")
    assert is_archive_split("release.rar.002")
    assert is_first_archive_split("release.rar.01")
    assert is_archive_split("release.rar.02")


def test_hyperdl_lane_respects_calculated_capacity():
    namespace = {"_hyper_download_active": 0}
    load_top_level_functions(
        DOWNLOAD_SOURCE,
        {"_claim_hyper_download", "_release_hyper_download"},
        namespace,
    )

    assert namespace["_claim_hyper_download"](2)
    assert namespace["_claim_hyper_download"](2)
    assert not namespace["_claim_hyper_download"](2)
    namespace["_release_hyper_download"]()
    assert namespace["_claim_hyper_download"](2)
    namespace["_release_hyper_download"]()
    namespace["_release_hyper_download"]()
    namespace["_release_hyper_download"]()
    assert namespace["_hyper_download_active"] == 0


def test_hyperdl_capacity_uses_available_helpers_and_thread_setting():
    config = SimpleNamespace(HYPER_THREADS=0)
    tg_client = SimpleNamespace(
        helper_bots={index: object() for index in range(1, 7)},
        helper_users={},
        user=None,
    )
    capacity = load_method(
        DOWNLOAD_SOURCE,
        "TelegramDownloadHelper",
        "_hyper_capacity",
        {"Config": config, "TgClient": tg_client},
    )
    helper = SimpleNamespace(
        _listener=SimpleNamespace(transmission_mode="bot"),
    )

    assert capacity(helper) == 1
    config.HYPER_THREADS = 2
    assert capacity(helper) == 3


@pytest.mark.asyncio
async def test_hyperdl_resolves_helper_references_concurrently():
    active = 0
    peak_active = 0

    async def fetch_ref(client_id, _client):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        try:
            await asyncio.sleep(0.01)
            return f"ref-{client_id}"
        finally:
            active -= 1

    resolve = load_method(
        HYPERDL_SOURCE,
        "HypertgDownload",
        "_resolve_file_refs",
        {
            "CancelledError": asyncio.CancelledError,
            "LOGGER": logging.getLogger(__name__),
            "gather": asyncio.gather,
        },
    )
    helper = SimpleNamespace(
        clients={1: object(), 2: object(), 3: object()},
        _fetch_ref=fetch_ref,
    )

    result = await resolve(helper, [1, 2, 3])

    assert result == {1: "ref-1", 2: "ref-2", 3: "ref-3"}
    assert peak_active == 3


@pytest.mark.asyncio
async def test_hyperdl_continues_when_one_helper_reference_fails():
    async def fetch_ref(client_id, _client):
        if client_id == 2:
            raise RuntimeError("helper unavailable")
        return f"ref-{client_id}"

    resolve = load_method(
        HYPERDL_SOURCE,
        "HypertgDownload",
        "_resolve_file_refs",
        {
            "CancelledError": asyncio.CancelledError,
            "LOGGER": logging.getLogger(__name__),
            "gather": asyncio.gather,
        },
    )
    helper = SimpleNamespace(
        clients={1: object(), 2: object(), 3: object()},
        _fetch_ref=fetch_ref,
    )

    result = await resolve(helper, [1, 2, 3])

    assert result == {1: "ref-1", 3: "ref-3"}


@pytest.mark.asyncio
async def test_hyperdl_reference_resolution_propagates_cancellation():
    async def fetch_ref(client_id, _client):
        if client_id == 2:
            raise asyncio.CancelledError
        return f"ref-{client_id}"

    resolve = load_method(
        HYPERDL_SOURCE,
        "HypertgDownload",
        "_resolve_file_refs",
        {
            "CancelledError": asyncio.CancelledError,
            "LOGGER": logging.getLogger(__name__),
            "gather": asyncio.gather,
        },
    )
    helper = SimpleNamespace(
        clients={1: object(), 2: object()},
        _fetch_ref=fetch_ref,
    )

    with pytest.raises(asyncio.CancelledError):
        await resolve(helper, [1, 2])


@pytest.mark.asyncio
async def test_hyperdl_mixed_mode_fills_all_available_worker_slots():
    picked_clients = []

    async def pick_clients(_loads, clients, count):
        picked = list(clients)[:count]
        picked_clients.extend(picked)
        return picked

    async def makedirs(*_args, **_kwargs):
        return None

    async def run_with_clients(client_ids, _final):
        return tuple(client_ids)

    async def release_client_loads(_client_ids):
        return None

    handle_download = load_method(
        HYPERDL_SOURCE,
        "HypertgDownload",
        "handle_download",
        {
            "LOGGER": logging.getLogger(__name__),
            "_pick_clients": pick_clients,
            "makedirs": makedirs,
            "os": __import__("os"),
            "sub": lambda _pattern, _replacement, value: value,
        },
    )
    helper = SimpleNamespace(
        _cancel=SimpleNamespace(clear=lambda: None),
        _obj=SimpleNamespace(_processed_bytes=99),
        _listener=SimpleNamespace(transmission_mode="both"),
        _handle_download_with_clients=run_with_clients,
        _release_client_loads=release_client_loads,
        clients={1: object(), 2: object(), 3: object(), -1: object()},
        directory="downloads",
        file_name="file.bin",
        num_parts=4,
        work_loads={},
    )

    result = await handle_download(helper)

    assert len(result) == 4
    assert set(result) == {1, 2, 3, -1}
    assert picked_clients == [1, 2, -1, 3]


@pytest.mark.asyncio
async def test_download_completion_always_releases_global_task_state():
    class AsyncLock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def fail_completion():
        raise RuntimeError("listener callback failed")

    global_gid = {42: object()}
    complete = load_method(
        DOWNLOAD_SOURCE,
        "TelegramDownloadHelper",
        "_on_download_complete",
        {"GLOBAL_GID": global_gid, "global_lock": AsyncLock()},
    )
    helper = SimpleNamespace(
        _id=42,
        _listener=SimpleNamespace(on_download_complete=fail_completion),
        _log_performance=lambda _outcome: None,
    )

    with pytest.raises(RuntimeError, match="listener callback failed"):
        await complete(helper)

    assert 42 not in global_gid


def test_download_routes_hyperdl_first_and_wzgram_for_overflow():
    source = DOWNLOAD_SOURCE.read_text(encoding="utf-8")

    assert "Telegram download route: HyperDL primary lane" in source
    assert "Telegram download route: WZGram overflow lane" in source


def test_failed_download_performance_does_not_report_expected_size_as_transferred():
    records = []
    log_performance = load_method(
        DOWNLOAD_SOURCE,
        "TelegramDownloadHelper",
        "_log_performance",
        {
            "LOGGER": SimpleNamespace(info=lambda *args: records.append(args)),
            "time": lambda: 10.0,
        },
    )
    helper = SimpleNamespace(
        _start_time=9.0,
        _processed_bytes=0,
        _download_engine="WZGram",
        _listener=SimpleNamespace(name="queued.mkv", size=500_000_000),
    )

    log_performance(helper, "failed")

    assert records[0][4] == 0
    assert records[0][6] == 0


@pytest.mark.asyncio
async def test_delete_links_can_preserve_media_reply_until_download_finishes():
    deleted = []

    async def delete_message(*messages):
        deleted.append(messages)

    delete_links = load_top_level_functions(
        MESSAGE_UTILS_SOURCE,
        {"delete_links"},
        {
            "Config": SimpleNamespace(DELETE_LINKS=True),
            "delete_message": delete_message,
        },
    )["delete_links"]
    reply = object()
    command = SimpleNamespace(reply_to_message=reply)

    await delete_links(command, preserve_reply=True)
    await delete_links(command)

    assert deleted == [(command,), (command, reply)]


def test_direct_media_source_cleanup_is_deferred_in_both_command_paths():
    for path in (MIRROR_SOURCE, UPHOSTER_SOURCE):
        source = path.read_text(encoding="utf-8")

        assert "direct_media_reply = True" in source
        assert "preserve_reply = direct_media_reply and file_ is not None" in source
        assert "delete_links(self.message, preserve_reply=preserve_reply)" in source
        assert "if preserve_reply and Config.DELETE_LINKS:" in source
        assert "await delete_message(reply_to)" in source


def _queued_message_helper(tg_client):
    namespace = {
        "LOGGER": logging.getLogger(__name__),
        "TgClient": tg_client,
    }
    methods = {}
    for name in (
        "_has_downloadable_media",
        "_message_identity",
        "_remember_source_message",
        "_refresh_source_message",
        "_message_after_queue",
        "_standard_download",
    ):
        methods[name] = load_method(
            DOWNLOAD_SOURCE,
            "TelegramDownloadHelper",
            name,
            namespace,
        )
    return type("QueuedMessageHelper", (), methods)


def _telegram_message(message_id, *, has_media=True):
    document = object() if has_media else None
    return SimpleNamespace(
        chat=SimpleNamespace(id=-100123) if has_media else None,
        id=message_id if has_media else None,
        media=SimpleNamespace(value="document") if has_media else None,
        document=document,
    )


@pytest.mark.asyncio
async def test_queued_download_preserves_original_when_refresh_has_no_media():
    original = _telegram_message(77)
    empty_refresh = _telegram_message(None, has_media=False)

    class Client:
        async def get_messages(self, *, chat_id, message_ids):
            assert (chat_id, message_ids) == (-100123, 77)
            return empty_refresh

    client = Client()
    helper_class = _queued_message_helper(SimpleNamespace(user=None))
    helper = helper_class()
    helper.session = "bot"
    helper._listener = SimpleNamespace(client=client)
    helper._source_message = None
    helper._source_chat_id = None
    helper._source_message_id = None
    helper._remember_source_message(original)

    result = await helper._message_after_queue(original)

    assert result is original
    assert helper._source_message is original


@pytest.mark.asyncio
async def test_queued_download_uses_valid_refreshed_media_message():
    original = _telegram_message(77)
    refreshed = _telegram_message(77)

    class Client:
        async def get_messages(self, *, chat_id, message_ids):
            assert (chat_id, message_ids) == (-100123, 77)
            return refreshed

    client = Client()
    helper_class = _queued_message_helper(SimpleNamespace(user=None))
    helper = helper_class()
    helper.session = "bot"
    helper._listener = SimpleNamespace(client=client)
    helper._source_message = None
    helper._source_chat_id = None
    helper._source_message_id = None
    helper._remember_source_message(original)

    result = await helper._message_after_queue(original)

    assert result is refreshed
    assert helper._source_message is refreshed


@pytest.mark.asyncio
async def test_standard_fallback_uses_preserved_source_identity_safely():
    original = _telegram_message(77)
    empty_message = _telegram_message(None, has_media=False)
    attempted = []

    class Client:
        async def get_messages(self, *, chat_id, message_ids):
            assert (chat_id, message_ids) == (-100123, 77)
            return empty_message

    async def standard_download_once(candidate, _path, label):
        attempted.append((label, candidate))
        return "downloaded.bin"

    tg_client = SimpleNamespace(user=None, bot=None)
    helper_class = _queued_message_helper(tg_client)
    helper = helper_class()
    helper._listener = SimpleNamespace(
        client=Client(),
        is_cancelled=False,
        transmission_mode="bot",
    )
    helper._source_message = None
    helper._source_chat_id = None
    helper._source_message_id = None
    helper._standard_download_once = standard_download_once
    helper._remember_source_message(original)

    result = await helper._standard_download(empty_message, "downloads/")

    assert result == "downloaded.bin"
    assert attempted == [("current", original)]
