from .. import bot_cache
from ..helper.ext_utils.telegram_destinations import MAX_MANUAL_LEECH_DUMPS
from ..helper.telegram_helper.message_utils import (
    build_leech_dump_selection_buttons,
    edit_message,
    leech_dump_selection_text,
)


async def select_leech_dumps(_, query):
    data = query.data.split(maxsplit=3)
    if len(data) != 4:
        return await query.answer("Invalid selection.", show_alert=True)

    user_id = int(data[1])
    msg_id = int(data[2])
    if query.from_user.id != user_id:
        return await query.answer("This selection belongs to another user.", show_alert=True)

    cache_key = ("leech_dump", user_id, query.message.chat.id, msg_id)
    state = bot_cache.get(cache_key)
    if not isinstance(state, dict):
        return await query.answer("This selection has expired.", show_alert=True)

    action = data[3]
    if action == "cancel":
        state["cancelled"] = True
        return await query.answer("Task cancelled.")
    if action == "done":
        if not state["selected"]:
            return await query.answer(
                "Select at least one dump, or use Select All.", show_alert=True
            )
        state["done"] = True
        return await query.answer("Selection confirmed.")
    if action == "all":
        state["selected"] = set(range(len(state["dumps"])))
        state["done"] = True
        return await query.answer("All dumps selected.")

    try:
        index = int(action)
    except ValueError:
        return await query.answer("Invalid selection.", show_alert=True)
    if index < 0 or index >= len(state["dumps"]):
        return await query.answer("Dump not found.", show_alert=True)

    selected = state["selected"]
    if index in selected:
        selected.remove(index)
        response = f"Removed: {state['dumps'][index][0]}"
    else:
        if len(selected) >= MAX_MANUAL_LEECH_DUMPS:
            return await query.answer(
                f"Choose at most {MAX_MANUAL_LEECH_DUMPS} dumps, or use Select All.",
                show_alert=True,
            )
        selected.add(index)
        response = f"Added: {state['dumps'][index][0]}"

    await query.answer(response)
    await edit_message(
        query.message,
        leech_dump_selection_text(state["dumps"], selected),
        build_leech_dump_selection_buttons(user_id, msg_id, state["dumps"], selected),
    )
