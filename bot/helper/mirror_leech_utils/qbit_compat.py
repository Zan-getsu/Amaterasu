from datetime import datetime

METADATA_STATES = {"metaDL", "forcedMetaDL", "checkingResumeData"}
DOWNLOAD_STATES = {"downloading", "forcedDL"}
STALLED_DOWNLOAD_STATES = {"stalledDL"}
PAUSED_STATES = {"stoppedDL", "stoppedUP", "pausedDL", "pausedUP"}
CHECKING_STATES = {"checkingUP", "checkingDL", "checkingResumeData"}
QUEUE_DOWNLOAD_STATES = {"queuedDL"}
QUEUE_UPLOAD_STATES = {"queuedUP"}
SEEDING_STATES = {"queuedUP", "stalledUP", "uploading", "forcedUP"}
TERMINAL_SEED_STATES = {"stoppedUP", "pausedUP", "stoppedDL", "pausedDL"}


def torrent_tags(torrent) -> list[str]:
    tags = getattr(torrent, "tags", None)
    if not tags:
        return []
    if isinstance(tags, str):
        return [tag.strip() for tag in tags.split(",") if tag.strip()]
    try:
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    except TypeError:
        tag = str(tags).strip()
        return [tag] if tag else []


def first_torrent_tag(torrent) -> str:
    tags = torrent_tags(torrent)
    return tags[0] if tags else ""


def completion_timestamp(torrent) -> int:
    value = getattr(torrent, "completion_on", -1)
    if value is None:
        return -1
    if isinstance(value, datetime):
        return int(value.timestamp())
    if hasattr(value, "timestamp"):
        try:
            return int(value.timestamp())
        except (TypeError, ValueError, OSError):
            return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def seconds_value(value) -> int:
    if value is None:
        return 0
    if hasattr(value, "total_seconds"):
        return int(value.total_seconds())
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def is_metadata_state(state: str) -> bool:
    return state in METADATA_STATES


def is_download_state(state: str) -> bool:
    return state in DOWNLOAD_STATES


def is_complete_for_upload(torrent) -> bool:
    return completion_timestamp(torrent) != -1 and getattr(torrent, "state", "") in SEEDING_STATES
