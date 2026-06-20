"""Phase 5.6 — Smart notifications.

Per-user notification preferences stored in user_data[uid]["NOTIFICATIONS"].
Options:
  - "all": notify on start + milestones (25%, 50%, 75%) + complete + fail
  - "compact": notify on complete + fail only (default)
  - "silent": no DM, only in-chat status

Milestones are tracked per-task in bot_cache to avoid duplicate notifications.
"""

from logging import getLogger

LOGGER = getLogger(__name__)

# Milestone percentages — notify when progress crosses these thresholds
_MILESTONES = [25, 50, 75]


def get_notification_pref(user_id):
    """Return the user's notification preference: 'all', 'compact', or 'silent'.
    Default is 'compact'."""
    from ... import user_data
    user_dict = user_data.get(user_id, {})
    return user_dict.get("NOTIFICATIONS", "compact")


def _get_milestone_key(mid):
    """Return the bot_cache key for tracking milestones for a task."""
    return f"milestone:{mid}"


def check_milestone(mid, progress_percent):
    """Check if a milestone notification should be sent for this progress.

    Returns the milestone percentage (25, 50, or 75) if it was just
    crossed, or None if no new milestone. Tracks sent milestones in
    bot_cache to avoid duplicates.
    """
    if progress_percent is None or progress_percent <= 0:
        return None
    from ... import bot_cache
    key = _get_milestone_key(mid)
    sent = bot_cache.get(key, set())
    for milestone in _MILESTONES:
        if progress_percent >= milestone and milestone not in sent:
            sent.add(milestone)
            bot_cache[key] = sent
            return milestone
    return None


def clear_milestones(mid):
    """Clear milestone tracking for a completed/cancelled task."""
    from ... import bot_cache
    bot_cache.pop(_get_milestone_key(mid), None)


async def send_notification(user_id, message_text, pref_override=None):
    """Send a DM notification to the user if their preference allows it.

    Args:
        user_id: Telegram user ID to notify.
        message_text: The notification message.
        pref_override: If set ('all', 'compact', 'silent'), overrides
            the user's stored preference. Used for force-sending
            failure notifications.

    For 'compact' and 'all' prefs: send the DM.
    For 'silent' pref: skip the DM (status is shown in-chat only).
    """
    pref = pref_override or get_notification_pref(user_id)
    if pref == "silent":
        return
    try:
        from ...core.tg_client import TgClient
        from ...core.config_manager import Config
        if TgClient.bot and Config.OWNER_ID:
            await TgClient.bot.send_message(user_id, message_text)
    except Exception as e:
        LOGGER.warning(f"Failed to send notification to user {user_id}: {e}")


async def notify_task_event(user_id, event_type, task_name="", progress=None, error=""):
    """Send a notification for a task event.

    event_type: 'start', 'milestone', 'complete', 'fail'
    task_name: Name of the task (for context in the message)
    progress: Progress percentage (0-100) — for milestone events
    error: Error message — for fail events
    """
    pref = get_notification_pref(user_id)
    if pref == "silent":
        return  # no DMs for silent mode

    if event_type == "start":
        if pref != "all":
            return  # 'compact' mode doesn't notify on start
        await send_notification(
            user_id,
            f"📤 <b>Task Started</b>\n{task_name}",
        )
    elif event_type == "milestone":
        if pref != "all":
            return  # only 'all' mode gets milestones
        await send_notification(
            user_id,
            f"📊 <b>{progress}% Complete</b>\n{task_name}",
        )
    elif event_type == "complete":
        # Both 'compact' and 'all' get completion notification
        await send_notification(
            user_id,
            f"✅ <b>Task Complete</b>\n{task_name}",
        )
    elif event_type == "fail":
        # Both 'compact' and 'all' get failure notification
        await send_notification(
            user_id,
            f"❌ <b>Task Failed</b>\n{task_name}\n<i>{error}</i>",
        )
