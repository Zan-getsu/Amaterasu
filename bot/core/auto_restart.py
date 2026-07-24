"""Daily maintenance restart scheduler."""

from asyncio import sleep

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone, utc

from .. import LOGGER, bot_loop
from .config_manager import Config

AUTO_RESTART_JOB_ID = "daily_auto_restart"
AUTO_RESTART_HOUR = 6
AUTO_RESTART_MINUTE = 0

auto_restart_scheduler = AsyncIOScheduler(event_loop=bot_loop)
_shutdown_requested = False


def _owner_timezone():
    try:
        return timezone(Config.TIMEZONE)
    except Exception:
        LOGGER.warning(
            "Invalid TIMEZONE %r for daily auto restart; falling back to UTC",
            Config.TIMEZONE,
        )
        return utc


async def _run_scheduled_restart():
    from ..modules.restart import scheduled_restart

    await scheduled_restart()


def schedule_auto_restart():
    """Schedule one restart every day at 06:00 in the configured timezone."""
    if _shutdown_requested:
        LOGGER.warning("Ignoring daily auto-restart scheduling during shutdown")
        return

    owner_tz = _owner_timezone()
    auto_restart_scheduler.add_job(
        _run_scheduled_restart,
        trigger=CronTrigger(
            hour=AUTO_RESTART_HOUR,
            minute=AUTO_RESTART_MINUTE,
            timezone=owner_tz,
        ),
        id=AUTO_RESTART_JOB_ID,
        name="Daily bot restart",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    if not auto_restart_scheduler.running:
        auto_restart_scheduler.start()

    job = auto_restart_scheduler.get_job(AUTO_RESTART_JOB_ID)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else "unknown"
    LOGGER.info(
        "Daily auto restart scheduled for 06:00 %s (next run: %s)",
        getattr(owner_tz, "zone", str(owner_tz)),
        next_run,
    )


async def shutdown_auto_restart_scheduler():
    global _shutdown_requested
    _shutdown_requested = True
    if auto_restart_scheduler.running:
        auto_restart_scheduler.shutdown(wait=False)
        await sleep(0)
