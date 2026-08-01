import ast
import asyncio
import logging
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
