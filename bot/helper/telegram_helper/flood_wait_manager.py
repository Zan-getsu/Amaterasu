"""Phase 2.5 — Telegram FloodWait management.

Wraps Pyrogram API calls to handle FloodWait exceptions gracefully:
- On FloodWait(X): sleep X+1 seconds, then retry the operation once.
- Track per-chat FloodWait state. If a FloodWait was triggered for a
  chat in the last 60 seconds, add a 2-second delay before the next
  operation to that chat.
- Keep it simple — no message buffering, no operation queue.

Usage:
    from bot.helper.telegram_helper.flood_wait_manager import with_flood_wait

    @with_flood_wait
    async def send_message(chat_id, text):
        return await bot.send_message(chat_id, text)
"""

from asyncio import sleep
from functools import wraps
from logging import getLogger
from time import time

LOGGER = getLogger(__name__)

# Per-chat FloodWait state: {chat_id: last_floodwait_timestamp}
_floodwait_state = {}
_FLOODWAIT_COOLDOWN = 60  # seconds — if recent FloodWait, add delay
_PREEMPTIVE_DELAY = 2  # seconds — delay before next op to that chat


def _is_recent_floodwait(chat_id):
    """Check if a FloodWait was triggered for this chat recently."""
    last = _floodwait_state.get(chat_id)
    if last is None:
        return False
    if time() - last > _FLOODWAIT_COOLDOWN:
        # Stale — clean up
        _floodwait_state.pop(chat_id, None)
        return False
    return True


def _record_floodwait(chat_id):
    """Record that a FloodWait was triggered for this chat."""
    _floodwait_state[chat_id] = time()


def with_flood_wait(func):
    """Decorator that handles FloodWait exceptions.

    On FloodWait(X): sleeps X+1 seconds, retries once. If the retry
    also fails with FloodWait, gives up and re-raises.

    Before calling the wrapped function, if the chat had a recent
    FloodWait (within _FLOODWAIT_COOLDOWN seconds), adds a
    _PREEMPTIVE_DELAY second delay to avoid re-triggering.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Try to extract chat_id from args/kwargs for preemptive delay.
        # Most Pyrogram methods take chat_id as first positional arg
        # or as a keyword arg. We extract it best-effort.
        chat_id = kwargs.get("chat_id")
        if chat_id is None and args:
            # First positional arg is often chat_id for send/edit/etc.
            if isinstance(args[0], (int, str)):
                chat_id = args[0]

        # Preemptive delay if this chat had a recent FloodWait
        if chat_id is not None and _is_recent_floodwait(chat_id):
            LOGGER.debug(
                f"Preemptive FloodWait delay {_PREEMPTIVE_DELAY}s for chat {chat_id}"
            )
            await sleep(_PREEMPTIVE_DELAY)

        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # Pyrogram raises FloodWait with a `value` attribute (seconds)
            # Check for pyrogram.errors.FloodWait by name to avoid import
            # issues at module load time.
            if type(e).__name__ == "FloodWait":
                wait_seconds = getattr(e, "value", 60) + 1
                LOGGER.warning(
                    f"FloodWait for chat {chat_id}: sleeping {wait_seconds}s "
                    f"then retrying once"
                )
                if chat_id is not None:
                    _record_floodwait(chat_id)
                await sleep(wait_seconds)
                # Retry once — no further retries to avoid infinite loops
                return await func(*args, **kwargs)
            # Non-FloodWait exception — propagate
            raise

    return wrapper


def clear_floodwait_state(chat_id=None):
    """Clear FloodWait state for a chat (or all chats if None)."""
    if chat_id is None:
        _floodwait_state.clear()
    else:
        _floodwait_state.pop(chat_id, None)
