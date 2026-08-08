import asyncio

from bot.helper.ext_utils.multi_leech_utils import (
    MultiLeechSummary,
    paginate_text_blocks,
    should_collect_multi_leech,
)


def test_multi_leech_scope_excludes_mirrors_single_tasks_and_folder_merges():
    assert should_collect_multi_leech(True, 3)
    assert not should_collect_multi_leech(False, 3)
    assert not should_collect_multi_leech(True, 1)
    assert not should_collect_multi_leech(True, 3, folder_name="/Batch")
    assert not should_collect_multi_leech(True, 3, is_youtube_upload=True)


def test_multi_leech_summary_waits_for_all_tasks_and_preserves_task_order():
    async def run():
        summary = MultiLeechSummary(3, anchor_message=object())

        second = await summary.record_success(
            102,
            2,
            "second",
            20,
            {"https://t.me/c/1/2": "second.bin"},
            tag="user",
        )
        first = await summary.record_success(
            101,
            1,
            "first",
            10,
            {"https://t.me/c/1/1": "first.bin"},
            tag="user",
        )
        final = await summary.record_success(
            103,
            3,
            "third",
            30,
            {"https://t.me/c/1/3": "third.bin"},
            corrupted=1,
            tag="user",
        )

        assert second is None
        assert first is None
        assert final.succeeded == 3
        assert final.failed == 0
        assert final.total_size == 60
        assert final.corrupted == 1
        assert [item.name for item in final.files] == [
            "first.bin",
            "second.bin",
            "third.bin",
        ]

    asyncio.run(run())


def test_multi_leech_summary_emits_once_with_failed_and_unstarted_tasks():
    async def run():
        summary = MultiLeechSummary(4, anchor_message=object())

        await summary.record_success(
            201,
            1,
            "ok",
            50,
            {"https://t.me/c/1/1": "ok.bin"},
        )
        await summary.record_failure(202, 2, "bad", "download failed")
        final = await summary.record_unstarted(2, 3, "no more sources")

        assert final.succeeded == 1
        assert final.failed == 3
        assert [failure.position for failure in final.failures] == [2, 3, 4]
        assert await summary.record_failure(202, 2, "bad", "duplicate") is None

    asyncio.run(run())


def test_multi_leech_summary_ignores_duplicate_terminal_callbacks():
    async def run():
        summary = MultiLeechSummary(2, anchor_message=object())

        await summary.record_success(301, 1, "one", 1, {})
        assert await summary.record_failure(301, 1, "one", "late error") is None
        final = await summary.record_success(302, 2, "two", 2, {})

        assert final.succeeded == 2
        assert final.failed == 0

    asyncio.run(run())


def test_multi_leech_summary_tolerates_invalid_numeric_uploader_values():
    async def run():
        summary = MultiLeechSummary(1, anchor_message=object())
        final = await summary.record_success(
            401,
            1,
            "task",
            "unknown",
            {},
            corrupted=None,
        )

        assert final.total_size == 0
        assert final.corrupted == 0

    asyncio.run(run())


def test_multi_leech_summary_paginates_large_batches_without_repeating_header():
    header = "summary\n"
    blocks = [f"task-{index}: {'x' * 250}\n" for index in range(40)]
    pages = paginate_text_blocks(header, blocks, "continued\n", max_bytes=1000)

    assert len(pages) > 1
    assert all(len(page.encode()) <= 1000 for page in pages)
    assert pages[0].startswith(header)
    assert all(page.startswith("continued\n") for page in pages[1:])
    assert "".join(pages).count("task-") == 40
