"""Behavioral checks for merge order identity and the save/freeze boundary."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from threading import Barrier

import pytest

from bot.helper.ext_utils.merge_order import episode_sort_key, natural_key
from web import merge_plan_store as store


@pytest.fixture
def plans(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_BASE_DIR", str(tmp_path / "plans"))
    return store


def _two_source_plan(plans, plan_id="batch"):
    assert plans.create_plan(plan_id, 7, -100, "Episodes", 2)
    plans.register_source(plan_id, "first", 1, "First")
    return plans.register_source(plan_id, "second", 2, "Second")


def _final_files():
    return [
        {"source_id": "first", "key": "first.mkv", "path": "first/first.mkv", "name": "First", "position": 1},
        {"source_id": "second", "key": "second.mkv", "path": "second/second.mkv", "name": "Second", "position": 2},
    ]


def _cross_process_writer(base_dir, desired, revision, start, results):
    from web import merge_plan_store as child_store

    child_store._BASE_DIR = base_dir
    start.wait()
    saved, error = child_store.update_order("batch", desired, revision)
    results.put(("save", saved, error))


def _cross_process_freezer(base_dir, start, results):
    from web import merge_plan_store as child_store

    child_store._BASE_DIR = base_dir
    start.wait()
    results.put(("freeze", child_store.sync_final_files("batch", _final_files())))


def test_progress_update_does_not_conflict_with_order_save(plans):
    plan = _two_source_plan(plans)
    assert plans.set_plan_status("batch", "downloading")
    repeated = plans.register_source("batch", "second", 2, "Second")
    assert repeated["order_revision"] == plan["order_revision"]
    saved, error = plans.update_order(
        "batch", [item["id"] for item in reversed(plan["items"])], plan["order_revision"]
    )
    assert not error
    assert saved["order_saved"]
    assert saved["revision"] > saved["order_revision"]


def test_save_and_freeze_are_atomic(plans):
    plan = _two_source_plan(plans)
    desired = [item["id"] for item in reversed(plan["items"])]
    start = Barrier(2)

    def save():
        start.wait()
        return plans.update_order("batch", desired, plan["order_revision"])

    def freeze():
        start.wait()
        return plans.sync_final_files("batch", _final_files())

    with ThreadPoolExecutor(max_workers=2) as executor:
        save_future = executor.submit(save)
        freeze_future = executor.submit(freeze)
        saved, error = save_future.result()
        frozen = freeze_future.result()

    assert frozen is not None
    assert frozen["locked"]
    if not error:
        assert [item["source_id"] for item in frozen["items"]] == ["second", "first"]
    else:
        assert error == "This merge has already started."
        assert saved["locked"]


def test_save_and_freeze_are_atomic_across_processes(plans):
    plan = _two_source_plan(plans)
    desired = [item["id"] for item in reversed(plan["items"])]
    context = get_context("spawn")
    start = context.Event()
    results = context.Queue()
    writer = context.Process(
        target=_cross_process_writer,
        args=(plans._BASE_DIR, desired, plan["order_revision"], start, results),
    )
    freezer = context.Process(
        target=_cross_process_freezer,
        args=(plans._BASE_DIR, start, results),
    )
    writer.start()
    freezer.start()
    start.set()
    outcomes = dict((result[0], result[1:]) for result in (results.get(timeout=15), results.get(timeout=15)))
    writer.join(timeout=15)
    freezer.join(timeout=15)
    assert writer.exitcode == freezer.exitcode == 0
    frozen = outcomes["freeze"][0]
    saved, error = outcomes["save"]
    assert frozen and frozen["locked"]
    if not error:
        assert [item["source_id"] for item in frozen["items"]] == ["second", "first"]
    else:
        assert error == "This merge has already started."
        assert saved["locked"]


def test_ready_update_preserves_interleaved_order(plans):
    _two_source_plan(plans)
    plans.replace_source_files("batch", "first", [
        {"key": "A1.mkv", "name": "A1", "ordinal": 1},
        {"key": "A2.mkv", "name": "A2", "ordinal": 2},
    ])
    plan = plans.replace_source_files("batch", "second", [
        {"key": "B1.mkv", "name": "B1", "ordinal": 1},
    ])
    by_name = {item["name"]: item["id"] for item in plan["items"]}
    saved, error = plans.update_order(
        "batch", [by_name[name] for name in ("A1", "B1", "A2")], plan["order_revision"]
    )
    assert not error
    refreshed = plans.replace_source_files("batch", "first", [
        {"key": "A1.mkv", "name": "A1 ready", "ordinal": 1, "ready": True},
        {"key": "A2.mkv", "name": "A2 ready", "ordinal": 2, "ready": True},
    ])
    assert [item["name"] for item in refreshed["items"]] == ["A1 ready", "B1", "A2 ready"]
    assert refreshed["order_revision"] == saved["order_revision"]


def test_case_distinct_paths_and_changed_identity(plans):
    assert plans.create_plan("case", 7, -100, "Case", 1)
    plans.register_source("case", "folder", 1, "Folder")
    plan = plans.replace_source_files("case", "folder", [
        {"key": "Episode.mkv", "name": "Episode.mkv"},
        {"key": "episode.mkv", "name": "episode.mkv"},
    ])
    assert len({item["id"] for item in plan["items"]}) == 2
    saved, error = plans.update_order("case", [item["id"] for item in reversed(plan["items"])], plan["order_revision"])
    assert not error
    assert plans.sync_final_files("case", [
        {"source_id": "folder", "key": "Other.mkv", "path": "Other.mkv", "name": "Other"},
        {"source_id": "folder", "key": "episode.mkv", "path": "episode.mkv", "name": "episode"},
    ]) is None
    assert plans.read_plan("case")["inventory_error"]
    assert not plans.read_plan("case")["locked"]


def test_stale_cleanup_keeps_active_plan(plans):
    assert plans.create_plan("active", 7, -100, "Active")
    assert plans.create_plan("done", 7, -100, "Done")
    assert plans.set_plan_status("done", "completed", locked=True)
    old = time.time() - 30
    for plan_id in ("active", "done"):
        os.utime(plans._path(plan_id), (old, old))
    assert plans.cleanup_stale_plans(max_age_seconds=10) == 1
    assert plans.read_plan("active") is not None
    assert plans.read_plan("done") is None


def test_restart_marks_only_unfinished_plans_interrupted(plans):
    assert plans.create_plan("active", 7, -100, "Active")
    assert plans.create_plan("done", 7, -100, "Done")
    assert plans.set_plan_status("done", "completed", locked=True)
    assert plans.mark_interrupted_plans() == 1
    active = plans.read_plan("active")
    assert active["status"] == "interrupted"
    assert active["locked"]
    assert "will not upload twice" in active["error"]
    assert plans.read_plan("done")["status"] == "completed"
    assert plans.mark_interrupted_plans() == 0


def test_episode_sort_uses_season_folder_and_is_deterministic():
    names = [
        "Season 02/Episode 01.mkv", "Season 01/Episode 10.mkv",
        "Season 01/Episode 02.mkv", "Episode.mkv", "episode.mkv",
    ]
    assert sorted(names[:3], key=episode_sort_key) == [
        "Season 01/Episode 02.mkv", "Season 01/Episode 10.mkv",
        "Season 02/Episode 01.mkv",
    ]
    assert sorted(names[3:], key=natural_key) == ["Episode.mkv", "episode.mkv"]
