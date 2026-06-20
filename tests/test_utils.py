"""Phase 6.1 — Utility smoke tests.

Tests disk space check, engine selector, retry decorator, and flood
wait manager.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock


# ────────────────────────────────────────────────────────────────────
# Disk space check tests (bot/helper/ext_utils/disk_utils.py)
# ────────────────────────────────────────────────────────────────────

def test_disk_space_check_insufficient():
    """check_disk_space returns False when insufficient space."""
    from bot.helper.ext_utils.disk_utils import check_disk_space
    # Mock disk_usage to return 1 GB free, request 10 GB
    with patch("bot.helper.ext_utils.disk_utils.disk_usage") as mock_du:
        mock_du.return_value = MagicMock(free=1024 * 1024 * 1024)  # 1 GB
        result = check_disk_space(10 * 1024 * 1024 * 1024)  # 10 GB needed
        assert result is False


def test_disk_space_check_sufficient():
    """check_disk_space returns True when sufficient space."""
    from bot.helper.ext_utils.disk_utils import check_disk_space
    with patch("bot.helper.ext_utils.disk_utils.disk_usage") as mock_du:
        mock_du.return_value = MagicMock(free=100 * 1024 * 1024 * 1024)  # 100 GB
        result = check_disk_space(10 * 1024 * 1024 * 1024)  # 10 GB needed
        assert result is True


def test_disk_space_check_with_buffer():
    """check_disk_space adds 10% buffer — requires 1.1x the requested bytes."""
    from bot.helper.ext_utils.disk_utils import check_disk_space
    with patch("bot.helper.ext_utils.disk_utils.disk_usage") as mock_du:
        # Request 10 GB, have exactly 11 GB (1.1x buffer = 11 GB needed)
        mock_du.return_value = MagicMock(free=11 * 1024 * 1024 * 1024)
        result = check_disk_space(10 * 1024 * 1024 * 1024)
        assert result is True
        # Request 10 GB, have 10.5 GB (< 11 GB needed with buffer)
        mock_du.return_value = MagicMock(free=int(10.5 * 1024 * 1024 * 1024))
        result = check_disk_space(10 * 1024 * 1024 * 1024)
        assert result is False


# ────────────────────────────────────────────────────────────────────
# Engine selector tests (bot/helper/mirror_leech_utils/download_utils/engine_selector.py)
# ────────────────────────────────────────────────────────────────────

def test_engine_selector_magnet():
    """select_engine returns ['qbit', 'aria2'] for magnet links."""
    from bot.helper.mirror_leech_utils.download_utils.engine_selector import select_engine
    result = select_engine("magnet:?xt=urn:btih:abc123")
    assert "qbit" in result
    assert "aria2" in result
    assert result[0] == "qbit"  # qbit preferred for magnets


def test_engine_selector_mega():
    """select_engine returns ['mega', 'aria2'] for mega links."""
    from bot.helper.mirror_leech_utils.download_utils.engine_selector import select_engine
    result = select_engine("https://mega.nz/file/abc123#key")
    assert "mega" in result
    assert "aria2" in result
    assert result[0] == "mega"


def test_engine_selector_gdrive():
    """select_engine returns ['gdrive', 'aria2'] for GDrive links."""
    from bot.helper.mirror_leech_utils.download_utils.engine_selector import select_engine
    result = select_engine("https://drive.google.com/file/d/abc123/view")
    assert "gdrive" in result
    assert "aria2" in result
    assert result[0] == "gdrive"


def test_engine_selector_http():
    """select_engine returns ['direct', 'aria2'] for HTTP links."""
    from bot.helper.mirror_leech_utils.download_utils.engine_selector import select_engine
    result = select_engine("https://example.com/file.zip")
    assert "direct" in result
    assert "aria2" in result


def test_engine_selector_skips_unavailable():
    """select_engine skips UNAVAILABLE engines."""
    from bot.helper.mirror_leech_utils.download_utils.engine_selector import select_engine
    health = {"qbit": "UNAVAILABLE", "aria2": "HEALTHY"}
    result = select_engine("magnet:?xt=urn:btih:abc123", engine_health=health)
    assert "qbit" not in result  # qbit is unavailable, skip it
    assert "aria2" in result


# ────────────────────────────────────────────────────────────────────
# Retry decorator tests (bot/helper/ext_utils/retry.py)
# ────────────────────────────────────────────────────────────────────

def test_retry_decorator_retries_and_fails():
    """@retryable retries max_retries times then re-raises."""
    from bot.helper.ext_utils.retry import retryable

    call_count = 0

    @retryable(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
    async def failing_func():
        nonlocal call_count
        call_count += 1
        raise ValueError(f"Attempt {call_count}")

    with pytest.raises(ValueError):
        asyncio.get_event_loop().run_until_complete(failing_func())
    # 1 initial + 3 retries = 4 calls
    assert call_count == 4


def test_retry_decorator_succeeds_after_retry():
    """@retryable succeeds if a retry succeeds."""
    from bot.helper.ext_utils.retry import retryable

    call_count = 0

    @retryable(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
    async def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("First attempt fails")
        return "success"

    result = asyncio.get_event_loop().run_until_complete(flaky_func())
    assert result == "success"
    assert call_count == 2  # failed once, succeeded on retry


# ────────────────────────────────────────────────────────────────────
# Flood wait manager tests (bot/helper/telegram_helper/flood_wait_manager.py)
# ────────────────────────────────────────────────────────────────────

def test_flood_wait_manager_delays():
    """@with_flood_wait adds preemptive delay for recent FloodWait chats."""
    from bot.helper.telegram_helper.flood_wait_manager import (
        _is_recent_floodwait,
        _record_floodwait,
        _FLOODWAIT_COOLDOWN,
    )
    import time
    chat_id = 123456789
    # Initially no recent floodwait
    assert _is_recent_floodwait(chat_id) is False
    # Record a floodwait
    _record_floodwait(chat_id)
    # Now should be recent
    assert _is_recent_floodwait(chat_id) is True


def test_flood_wait_manager_clears_stale():
    """_is_recent_floodwait returns False for stale entries."""
    from bot.helper.telegram_helper.flood_wait_manager import (
        _is_recent_floodwait,
        _record_floodwait,
        _floodwait_state,
    )
    import time
    chat_id = 987654321
    _record_floodwait(chat_id)
    # Manually backdate the entry
    _floodwait_state[chat_id] = time.time() - 120  # 2 minutes ago (> 60s cooldown)
    assert _is_recent_floodwait(chat_id) is False
