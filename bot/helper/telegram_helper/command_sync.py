from asyncio import sleep
from re import compile as re_compile

from pyrogram.types import BotCommand

from ... import LOGGER
from ...core.config_manager import Config
from ...core.tg_client import TgClient, resilient_tg_operation
from ..ext_utils.help_messages import get_bot_commands
from .bot_commands import BotCommands

_VALID_COMMAND = re_compile(r"^[a-z0-9_]{1,32}$")


def build_bot_command_menu():
    """Build a Telegram-valid command menu without one bad plugin entry
    preventing every command from being registered.
    """
    BotCommands.refresh_commands()
    descriptions = get_bot_commands()

    if Config.JD_EMAIL and Config.JD_PASS:
        descriptions["JdMirror"] = "[link/file] Mirror to Upload Destination using JDownloader"
        descriptions["JdLeech"] = "[link/file] Leech files to Upload to Telegram using JDownloader"
    if Config.USENET_SERVERS:
        descriptions["NzbMirror"] = "[nzb] Mirror to Upload Destination using Sabnzbd"
        descriptions["NzbLeech"] = "[nzb] Leech files to Upload to Telegram using Sabnzbd"
    if Config.LOGIN_PASS:
        descriptions["Login"] = "[password] Login to Bot"

    menu = []
    invalid = []
    seen = set()
    for key, description in descriptions.items():
        configured = getattr(BotCommands, f"{key}Command", None)
        if configured is None:
            continue
        command = configured[0] if isinstance(configured, list) else configured
        command = str(command).strip()
        if not _VALID_COMMAND.fullmatch(command):
            invalid.append(command or f"<empty:{key}>")
            continue
        if command in seen:
            continue
        seen.add(command)

        description = " ".join(str(description).split()).strip()
        if not description:
            description = key
        # Telegram accepts descriptions up to 256 characters. Truncating a
        # plugin description keeps the rest of the menu available.
        menu.append(BotCommand(command, description[:256]))

    if invalid:
        LOGGER.error(
            "Skipping invalid Telegram bot command(s): %s. Commands must "
            "match [a-z0-9_]{1,32}; check CMD_SUFFIX and plugin commands.",
            ", ".join(invalid),
        )
    if not menu:
        raise ValueError(
            "No valid Telegram bot commands were generated. Check CMD_SUFFIX "
            "and plugin command names."
        )
    if len(menu) > 100:
        LOGGER.warning(
            "Telegram permits at most 100 bot commands; truncating %s entries",
            len(menu) - 100,
        )
        menu = menu[:100]
    return menu


async def sync_bot_commands():
    """Register and read back the default Telegram command menu."""
    if TgClient.bot is None:
        raise RuntimeError("Main Telegram bot is not initialized")

    menu = build_bot_command_menu()
    result = await resilient_tg_operation(
        TgClient.bot.set_bot_commands,
        menu,
        operation_name="set_bot_commands",
        max_attempts=4,
        idempotent=True,
    )
    if result is False:
        raise RuntimeError("Telegram rejected the command menu without an error")

    expected = [(item.command, item.description) for item in menu]
    actual = []
    for read_attempt in range(3):
        registered = await resilient_tg_operation(
            TgClient.bot.get_bot_commands,
            operation_name="get_bot_commands",
            max_attempts=4,
            idempotent=True,
        )
        actual = [(item.command, item.description) for item in registered]
        if actual == expected:
            break
        if read_attempt < 2:
            await sleep(1)
    else:
        raise RuntimeError(
            "Telegram command read-back did not match the registered menu "
            f"(expected {len(expected)}, received {len(actual)})"
        )

    LOGGER.info(
        "Telegram command menu registered and verified: %s command(s)",
        len(menu),
    )
    return len(menu)
