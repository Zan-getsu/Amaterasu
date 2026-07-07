from ..helper.ext_utils.bot_utils import COMMAND_USAGE, new_task
from ..helper.ext_utils.help_messages import (
    YT_HELP_DICT,
    MIRROR_HELP_DICT,
    CLONE_HELP_DICT,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    edit_message,
    delete_message,
    send_message,
)
from ..helper.ext_utils.help_messages import help_string


@new_task
async def arg_usage(_, query):
    data = query.data.split()
    message = query.message
    await query.answer()
    if data[1] == "close":
        return await delete_message(message, message.reply_to_message)
    pg_no = int(data[3])
    if data[1] == "nex":
        if data[2] == "mirror":
            await edit_message(
                message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][pg_no + 1]
            )
        elif data[2] == "yt":
            await edit_message(
                message, COMMAND_USAGE["yt"][0], COMMAND_USAGE["yt"][pg_no + 1]
            )
        elif data[2] == "clone":
            await edit_message(
                message, COMMAND_USAGE["clone"][0], COMMAND_USAGE["clone"][pg_no + 1]
            )
    elif data[1] == "pre":
        if data[2] == "mirror":
            await edit_message(
                message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][pg_no - 1]
            )
        elif data[2] == "yt":
            await edit_message(
                message, COMMAND_USAGE["yt"][0], COMMAND_USAGE["yt"][pg_no - 1]
            )
        elif data[2] == "clone":
            await edit_message(
                message, COMMAND_USAGE["clone"][0], COMMAND_USAGE["clone"][pg_no - 1]
            )
    elif data[1] == "back":
        if data[2] == "m":
            await edit_message(
                message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][pg_no + 1]
            )
        elif data[2] == "y":
            await edit_message(
                message, COMMAND_USAGE["yt"][0], COMMAND_USAGE["yt"][pg_no + 1]
            )
        elif data[2] == "c":
            await edit_message(
                message, COMMAND_USAGE["clone"][0], COMMAND_USAGE["clone"][pg_no + 1]
            )
    elif data[1] == "mirror":
        buttons = ButtonMaker()
        buttons.data_button("↩ BACK", f"help back m {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, MIRROR_HELP_DICT[data[2]], button)
    elif data[1] == "yt":
        buttons = ButtonMaker()
        buttons.data_button("↩ BACK", f"help back y {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, YT_HELP_DICT[data[2]], button)
    elif data[1] == "clone":
        buttons = ButtonMaker()
        buttons.data_button("↩ BACK", f"help back c {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, CLONE_HELP_DICT[data[2]], button)


@new_task
async def bot_help(_, message):
    """Phase 5.3 — Help with fuzzy search.

    /help (no args): show full help string (v1.5.0 behavior).
    /help <query>: fuzzy-search command names + descriptions. If a good
    match is found, show that command's help. If no match, show a
    friendly "no match" message.
    """
    if len(message.command) > 1:
        query = " ".join(message.command[1:]).strip()
        if query:
            result = _fuzzy_search_command(query)
            if result:
                await send_message(message, result)
            else:
                await send_message(
                    message,
                    f"<b>No command found for '{query}'.</b>\n"
                    f"Use <code>/help</code> to browse all commands.",
                )
            return
    # No query — show full help
    await send_message(message, help_string)


def _fuzzy_search_command(query):
    """Fuzzy-search the help string for the query. Returns the matching
    line(s) if a good match is found (score > 60), or empty string.

    Uses rapidfuzz if available; falls back to simple substring search.
    """
    from ..helper.ext_utils.help_messages import help_string
    lines = [l.strip() for l in help_string.split("\n") if l.strip() and "/" in l]
    try:
        from rapidfuzz import process, fuzz
        # Search each line for the query — match against the command
        # name (first word starting with /) and the full line.
        best_match = None
        best_score = 0
        for line in lines:
            # Extract command name (e.g., "/mirror" from "/mirror: ...")
            cmd_part = line.split(":")[0].split()[0] if ":" in line else line.split()[0]
            score = max(
                fuzz.partial_ratio(query.lower(), cmd_part.lower()),
                fuzz.partial_ratio(query.lower(), line.lower()),
            )
            if score > best_score:
                best_score = score
                best_match = line
        if best_match and best_score > 60:
            return f"<b>Found (score: {best_score}):</b>\n<code>{best_match}</code>\n\nUse /help to browse all commands."
        return ""
    except ImportError:
        # rapidfuzz not installed — fall back to substring search
        query_lower = query.lower()
        matches = [l for l in lines if query_lower in l.lower()]
        if matches:
            return f"<b>Found:</b>\n<code>{matches[0]}</code>\n\nUse /help to browse all commands."
        return ""
