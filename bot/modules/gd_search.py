from html import escape

from .. import LOGGER, user_data
from ..helper.ext_utils.bot_utils import (
    get_telegraph_list,
    new_task,
    sync_to_async,
)
from ..helper.mirror_leech_utils.gdrive_utils.search import GoogleDriveSearch
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import edit_message, send_message

_OPTIONS_PREFIX = "Choose list options for:\n"


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in ("True", "False"):
        return value == "True"
    return False


def _options_message(key):
    return f"{_OPTIONS_PREFIX}<code>{escape(key)}</code>"


def _search_key_from_message(message):
    """Read the query from the durable menu text or a legacy replied command."""
    text = getattr(message, "text", "") or ""
    if text.startswith(_OPTIONS_PREFIX):
        return text.removeprefix(_OPTIONS_PREFIX).strip()

    reply = getattr(message, "reply_to_message", None)
    reply_text = getattr(reply, "text", "") or ""
    parts = reply_text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def list_buttons(user_id, is_recursive=True, user_token=False):
    buttons = ButtonMaker()
    buttons.data_button(
        f"{'✅️' if user_token else '❌️'} User Token",
        f"list_types {user_id} ut {is_recursive} {user_token}",
        "header",
    )
    buttons.data_button(
        f"{'✅️' if is_recursive else '❌️'} Recursive",
        f"list_types {user_id} rec {is_recursive} {user_token}",
        "header",
    )
    buttons.data_button(
        "Folders", f"list_types {user_id} folders {is_recursive} {user_token}"
    )
    buttons.data_button(
        "Files", f"list_types {user_id} files {is_recursive} {user_token}"
    )
    buttons.data_button(
        "Both", f"list_types {user_id} both {is_recursive} {user_token}"
    )

    buttons.data_button("✕ CANCEL", f"list_types {user_id} cancel", "footer")
    return buttons.build_menu(2)


async def _list_drive(key, message, item_type, is_recursive, user_token, user_id):
    LOGGER.info(f"GD Listing: {key}")
    if user_token:
        user_dict = user_data.get(user_id, {})
        target_id = user_dict.get("GDRIVE_ID", "") or ""
        LOGGER.info(target_id)
    else:
        target_id = ""
    telegraph_content, contents_no = await sync_to_async(
        GoogleDriveSearch(is_recursive=is_recursive, item_type=item_type).drive_list,
        key,
        target_id,
        user_id,
    )
    if telegraph_content:
        try:
            button = await get_telegraph_list(telegraph_content)
        except Exception as e:
            await edit_message(message, e)
            return
        msg = f"<b>Found {contents_no} result for <i>{escape(key)}</i></b>"
        await edit_message(message, msg, button)
    else:
        await edit_message(message, f"No result found for <i>{escape(key)}</i>")


@new_task
async def select_type(_, query):
    user_id = query.from_user.id
    message = query.message
    data = query.data.split()
    if user_id != int(data[1]):
        return await query.answer(text="Not Yours!", show_alert=True)
    if data[2] == "cancel":
        await query.answer()
        return await edit_message(message, "<i>List has been canceled!</i>")

    key = _search_key_from_message(message)
    if not key:
        await query.answer(
            text="This search menu has expired. Run the list command again.",
            show_alert=True,
        )
        return await edit_message(
            message,
            "<i>This search menu has expired. Run the list command again.</i>",
        )

    if data[2] == "rec":
        await query.answer()
        is_recursive = not _parse_bool(data[3])
        buttons = await list_buttons(user_id, is_recursive, _parse_bool(data[4]))
        return await edit_message(message, _options_message(key), buttons)
    elif data[2] == "ut":
        await query.answer()
        user_token = not _parse_bool(data[4])
        buttons = await list_buttons(user_id, _parse_bool(data[3]), user_token)
        return await edit_message(message, _options_message(key), buttons)
    await query.answer()
    item_type = data[2]
    is_recursive = _parse_bool(data[3])
    user_token = _parse_bool(data[4])
    await edit_message(message, f"<b>Searching.. for <i>{escape(key)}</i></b>")
    await _list_drive(key, message, item_type, is_recursive, user_token, user_id)


@new_task
async def gdrive_search(_, message):
    if len(message.text.split()) == 1:
        return await send_message(
            message, "<i>Send a search query along with list command</i>"
        )
    user_id = message.from_user.id
    key = message.text.split(maxsplit=1)[1].strip()
    buttons = await list_buttons(user_id)
    await send_message(message, _options_message(key), buttons)
