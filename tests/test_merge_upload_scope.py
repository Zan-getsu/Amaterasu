"""Run the production completion pipeline up to a mocked Telegram upload."""

import ast
import asyncio
import os
import shutil
from mimetypes import guess_type
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["file", "split", "failed", "cancelled"])
async def test_merge_upload_excludes_episode_sources(tmp_path, outcome):
    task_dir = tmp_path / "task"
    episodes = task_dir / "Episodes"
    episodes.mkdir(parents=True)
    sources = [episodes / f"Episode-{index}.mkv" for index in range(1, 4)]
    for path in sources:
        path.write_bytes(b"original episode")
    result = task_dir / "Combined [Merged].mkv"
    uploaded = []

    async def sync_to_async(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def size(path):
        path = Path(path)
        return path.stat().st_size if path.is_file() else sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    async def merge(*_args):
        if outcome == "failed":
            return False
        result.write_bytes(b"validated merged video")
        if outcome == "cancelled":
            task.is_cancelled = True
        return str(result)

    async def split(path, _gid):
        if outcome == "split":
            path = Path(path)
            for index in (1, 2):
                path.with_name(f"{path.name}.{index:03}").write_bytes(b"merged split part")
            path.unlink()

    class Uploader:
        _hu = None

        def __init__(self, _listener, path):
            self.path = Path(path)

        async def upload(self):
            uploaded.extend(path.name for path in self.path.rglob("*") if path.is_file())
            assert all(path.read_bytes() == b"original episode" for path in sources)

    task = SimpleNamespace(
        dir=str(task_dir), up_dir="", mid=1, folder_name="", same_dir={}, name="Episodes",
        is_cancelled=False, is_merge=True, is_torrent=False, is_qbit=False, seed=False,
        excluded_extensions=[], merge_plan_id="", join=False, extract=False, ffmpeg_cmds=False,
        is_encode=False, is_leech=True, compress=False, name_swap=False, screen_shots=False,
        convert_audio=False, convert_video=False, sample_video=False, is_yt=False,
        file_details={}, message=SimpleNamespace(chat=SimpleNamespace(id=-100)),
        clear=lambda: None, _stage_merge_source_files=AsyncMock(),
        proceed_merge=merge, proceed_split=split, update_merge_plan_status=AsyncMock(),
        on_download_error=AsyncMock(), on_upload_error=AsyncMock(),
    )
    namespace = {
        "sleep": AsyncMock(), "gather": asyncio.gather, "task_dict_lock": asyncio.Lock(),
        "task_dict": {1: SimpleNamespace(name=lambda: "Episodes", gid=lambda: "gid")},
        "LOGGER": SimpleNamespace(info=lambda *_args: None),
        "aiopath": SimpleNamespace(exists=AsyncMock(side_effect=os.path.exists), isfile=AsyncMock(side_effect=os.path.isfile)),
        "get_path_size": size, "remove_excluded_files": AsyncMock(),
        "Config": SimpleNamespace(QUEUE_ALL=True), "ospath": os.path,
        "guess_type": guess_type, "sync_to_async": sync_to_async, "mkdtemp": mkdtemp,
        "move": AsyncMock(side_effect=shutil.move), "check_running_tasks": AsyncMock(return_value=(False, None)),
        "start_from_queued": AsyncMock(), "update_status_message": AsyncMock(),
        "TelegramUploader": Uploader, "TelegramStatus": lambda *_args: object(),
    }
    tree = ast.parse((ROOT / "bot/helper/listeners/task_listener.py").read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TaskListener")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_download_complete")
    exec(compile(ast.Module([method], type_ignores=[]), str(ROOT / "bot/helper/listeners/task_listener.py"), "exec"), namespace)
    await namespace["on_download_complete"](task)
    if outcome in {"failed", "cancelled"}:
        assert uploaded == []
        assert not list(task_dir.glob("merge-output-*"))
    else:
        assert Path(task.up_dir).parent == task_dir
        assert Path(task.up_dir) != task_dir
        assert sorted(uploaded) == (["Combined [Merged].mkv"] if outcome == "file" else
                                    ["Combined [Merged].mkv.001", "Combined [Merged].mkv.002"])
