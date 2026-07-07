"""Phase 2.3 — Disk space pre-check utilities.

Checks available disk space before starting a download to fail fast
with a clear message instead of failing mid-download with a confusing
OSError.
"""

from shutil import disk_usage
from logging import getLogger

LOGGER = getLogger(__name__)


def check_disk_space(required_bytes, path="."):
    """Check if there's enough free disk space at `path` for `required_bytes`.

    Adds a 10% safety buffer (so requires 1.1 * required_bytes free).
    Returns True if sufficient space, False otherwise.

    For downloads where size is unknown upfront (streaming, some direct
    links), skip this check and rely on write errors with proper catch.
    """
    try:
        usage = disk_usage(path)
        free = usage.free
        # 10% buffer — partial downloads, temp files, archive extraction
        # can all consume more than the raw file size.
        required_with_buffer = int(required_bytes * 1.1)
        return free >= required_with_buffer
    except Exception as e:
        LOGGER.warning(f"disk_utils.check_disk_space error: {e}")
        # If we can't check, allow the download to proceed — better to
        # try and fail mid-download than to block legitimate downloads.
        return True


def format_bytes(num_bytes):
    """Format bytes as human-readable string (e.g., '1.5 GB')."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def get_free_space_gb(path="."):
    """Return free space at path in GB (float)."""
    try:
        return disk_usage(path).free / (1024 ** 3)
    except Exception:
        return 0.0
