from html import escape

from ..helper.ext_utils.bot_utils import COMMAND_USAGE, new_task
from ..helper.ext_utils.help_messages import (
    CLONE_HELP_DICT,
    MIRROR_HELP_DICT,
    YT_HELP_DICT,
    help_string,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)


@new_task
async def arg_usage(_, query):
    data = query.data.split()
    message = query.message
    await query.answer()
    if data[1] == "close":
        return await delete_message(message, message.reply_to_message)
    pg_no = int(data[3])
    key = {"m": "mirror", "y": "yt", "c": "clone"}.get(data[2], data[2])

    if data[1] in ("nex", "pre", "back"):
        pages = COMMAND_USAGE.get(key)
        if not pages:
            return
        button_index = pg_no + 1
        if 1 <= button_index < len(pages):
            await edit_message(message, pages[0], pages[button_index])
    elif data[1] in COMMAND_USAGE:
        info = {
            "mirror": ("m", MIRROR_HELP_DICT),
            "yt": ("y", YT_HELP_DICT),
            "clone": ("c", CLONE_HELP_DICT),
        }
        back_key, help_dict = info[data[1]]
        buttons = ButtonMaker()
        buttons.data_button("↩ BACK", f"help back {back_key} {pg_no}")
        await edit_message(message, help_dict[data[2]], buttons.build_menu())


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
                    "<b>✦ NO COMMAND FOUND</b>\n"
                    "<i>The command directory did not find a close match.</i>\n\n"
                    f"╭─ <b>Query</b> : <code>{escape(query)}</code>\n"
                    "├─ <b>Status</b> : <code>No match</code>\n"
                    "╰─ <b>Next</b> : <code>/help</code>",
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
    lines = [
        line.strip()
        for line in help_string.split("\n")
        if line.strip() and "/" in line
    ]
    try:
        from rapidfuzz import fuzz
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
            return (
                "<b>✦ COMMAND MATCH</b>\n"
                "<i>Closest command found from the directory.</i>\n\n"
                f"╭─ <b>Query</b> : <code>{escape(query)}</code>\n"
                f"├─ <b>Confidence</b> : <code>{best_score}%</code>\n"
                f"╰─ <b>Command</b> : {best_match}\n\n"
                "<i>Use /help to browse every command.</i>"
            )
        return ""
    except ImportError:
        # rapidfuzz not installed — fall back to substring search
        query_lower = query.lower()
        matches = [line for line in lines if query_lower in line.lower()]
        if matches:
            return (
                "<b>✦ COMMAND MATCH</b>\n\n"
                f"╭─ <b>Query</b> : <code>{escape(query)}</code>\n"
                "├─ <b>Confidence</b> : <code>substring</code>\n"
                f"╰─ <b>Command</b> : {matches[0]}\n\n"
                "<i>Use /help to browse every command.</i>"
            )
        return ""
