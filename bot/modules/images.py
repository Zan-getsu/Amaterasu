from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import handleIndex, new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)


# ────────────────────────────────────────────────────────────────────
# Phase 1.6 — Interactive image search
# ────────────────────────────────────────────────────────────────────
# Extends the existing /images command: if a query argument is given,
# search wallpaperflare/peapix/wallhaven and return paginated results
# with Mirror/Leech buttons. If no query, show the bot's image gallery
# (v1.5.0 behavior). The search uses the existing _fetch_wallpaperflare,
# _fetch_peapix, _fetch_wallhaven helpers in bot_utils.py.

async def _search_images_for_query(query, page=1, per_page=4):
    """Search wallpaperflare, peapix, wallhaven for the query.
    Returns a list of image URLs (max per_page). Page is 1-indexed."""
    from httpx import AsyncClient, Limits
    from ..helper.ext_utils.bot_utils import (
        _fetch_wallpaperflare,
        _fetch_peapix,
        _fetch_wallhaven,
    )
    seen = set()
    all_results = []
    sources = Config.IMG_SOURCES if isinstance(Config.IMG_SOURCES, list) else ["wallpaperflare"]
    try:
        async with AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            limits=Limits(max_connections=5),
            timeout=30,
        ) as client:
            if "wallpaperflare" in sources:
                # Fetch 2 pages to have enough results
                for p in range(1, page + 1):
                    results = await _fetch_wallpaperflare(client, query, p, seen)
                    for url in results:
                        if url not in seen:
                            seen.add(url)
                            all_results.append(url)
            if "wallhaven" in sources:
                for p in range(1, page + 1):
                    results = await _fetch_wallhaven(client, query, p, seen)
                    for url in results:
                        if url not in seen:
                            seen.add(url)
                            all_results.append(url)
    except Exception:
        pass
    # Return the slice for the requested page
    start = (page - 1) * per_page
    return all_results[start : start + per_page], len(all_results)


@new_task
async def image_search(_, message):
    """Handle /images <query> — interactive search with Mirror/Leech buttons.
    Called when /images is invoked with a query argument."""
    query = message.command[1].strip() if len(message.command) > 1 else ""
    if not query:
        # No query — fall through to gallery display
        await pictures(_, message)
        return
    editable = await send_message(message, f"<i>Searching images for '{query}'...</i>")
    results, total = await _search_images_for_query(query, page=1)
    if not results:
        await edit_message(
            editable,
            f"<b>No images found for '{query}'.</b> Try different keywords.",
        )
        return
    # Store the search results in bot_cache keyed by user_id for the
    # callback handler to access. Key format: "imgsearch:{user_id}"
    from .. import bot_cache
    user_id = message.from_user.id
    cache_key = f"imgsearch:{user_id}"
    bot_cache[cache_key] = {
        "query": query,
        "results": results,
        "page": 1,
        "total": total,
    }
    buttons = ButtonMaker()
    for i, url in enumerate(results):
        buttons.url_button(f"Mirror {i+1}", url)
    if total > len(results):
        buttons.data_button("Next Page", f"imgsearch {user_id} next 2")
    buttons.data_button("Close", f"imgsearch {user_id} close")
    await delete_message(editable)
    await send_message(
        message,
        f"<b>Image Search: {query}</b>\n"
        f"<code>Page 1 — {len(results)} of {total} results</code>\n"
        f"Click a button to mirror the image.",
        buttons.build_menu(2),
    )


async def image_search_callback(_, query):
    """Handle Next Page / Close buttons from image search results."""
    data = query.data.split()
    if len(data) < 3 or query.from_user.id != int(data[1]):
        await query.answer("Not authorized.", show_alert=True)
        return
    from .. import bot_cache
    from ..helper.telegram_helper.message_utils import edit_message, delete_message
    cache_key = f"imgsearch:{data[1]}"
    search_state = bot_cache.get(cache_key)
    if not search_state:
        await query.answer("Search expired. Run /images <query> again.", show_alert=True)
        return
    action = data[2]
    if action == "close":
        await query.answer()
        await delete_message(query.message)
        bot_cache.pop(cache_key, None)
        return
    if action == "next":
        page = int(data[3]) if len(data) > 3 else 1
        results, total = await _search_images_for_query(
            search_state["query"], page=page
        )
        if not results:
            await query.answer("No more results.", show_alert=True)
            return
        search_state["results"] = results
        search_state["page"] = page
        bot_cache[cache_key] = search_state
        buttons = ButtonMaker()
        for i, url in enumerate(results):
            buttons.url_button(f"Mirror {i+1}", url)
        if page > 1:
            buttons.data_button("Prev Page", f"imgsearch {data[1]} prev {page-1}")
        if total > page * len(results):
            buttons.data_button("Next Page", f"imgsearch {data[1]} next {page+1}")
        buttons.data_button("Close", f"imgsearch {data[1]} close")
        await query.answer()
        await edit_message(
            query.message,
            f"<b>Image Search: {search_state['query']}</b>\n"
            f"<code>Page {page} — {len(results)} of {total} results</code>\n"
            f"Click a button to mirror the image.",
            buttons.build_menu(2),
        )
    elif action == "prev":
        page = int(data[3]) if len(data) > 3 else 1
        results, total = await _search_images_for_query(
            search_state["query"], page=page
        )
        if not results:
            await query.answer("No results.", show_alert=True)
            return
        search_state["results"] = results
        search_state["page"] = page
        bot_cache[cache_key] = search_state
        buttons = ButtonMaker()
        for i, url in enumerate(results):
            buttons.url_button(f"Mirror {i+1}", url)
        if page > 1:
            buttons.data_button("Prev Page", f"imgsearch {data[1]} prev {page-1}")
        if total > page * len(results):
            buttons.data_button("Next Page", f"imgsearch {data[1]} next {page+1}")
        buttons.data_button("Close", f"imgsearch {data[1]} close")
        await query.answer()
        await edit_message(
            query.message,
            f"<b>Image Search: {search_state['query']}</b>\n"
            f"<code>Page {page} — {len(results)} of {total} results</code>\n"
            f"Click a button to mirror the image.",
            buttons.build_menu(2),
        )


@new_task
async def picture_add(_, message):
    resm = message.reply_to_message
    editable = await send_message(message, "<i>Fetching Input ...</i>")
    if len(message.command) > 1 or resm and resm.text:
        msg_text = resm.text if resm else message.command[1]
        if not msg_text.startswith("http"):
            return await edit_message(
                editable, "<b>Not a Valid Link, Must Start with 'http'</b>"
            )
        pic_add = msg_text.strip()
    elif resm and resm.photo:
        if resm.photo.file_size > 5242880 * 2:
            return await edit_message(
                editable, "<i>Media is Not Supported! Only Photos!!</i>"
            )
        pic_add = resm.photo.file_id
    else:
        help_msg = f"""<b>❖ ADD IMAGE USAGE</b>
<code>├─ Reply to Link : /{BotCommands.AddImageCommand} {{link}}
├─ Reply to Photo: /{BotCommands.AddImageCommand}
└─ Supported     : Telegra.ph, DDL links, Telegram photos
</code>"""
        return await edit_message(editable, help_msg)
    Config.IMAGES.append(pic_add)
    Config.USE_IMAGES = True
    if Config.DATABASE_URL:
        await database.update_config({"IMAGES": Config.IMAGES, "USE_IMAGES": True})
    await edit_message(
        editable,
        f"<b>❖ IMAGE ADDED</b>\n<code>├─ Total Images          : {len(Config.IMAGES)}\n└─ Random Message Images : Enabled\n</code>",
    )


@new_task
async def pictures(_, message):
    """Handle /images with no query — show the bot's image gallery.
    If a query is provided, delegate to image_search instead."""
    if len(message.command) > 1:
        # Has a query argument — do a search instead
        await image_search(_, message)
        return
    if not Config.IMAGES:
        await send_message(
            message,
            f"<b>No Photo to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>\n"
            f"<i>Or search with</i> <code>/{BotCommands.ImagesCommand} cats</code>",
        )
    else:
        if not Config.USE_IMAGES:
            Config.USE_IMAGES = True
            if Config.DATABASE_URL:
                await database.update_config({"USE_IMAGES": True})
        to_edit = await send_message(message, "<i>Generating Grid of your Images...</i>")
        buttons = ButtonMaker()
        user_id = message.from_user.id
        buttons.data_button("\u00ab", f"images {user_id} turn -1")
        buttons.data_button("\u00bb", f"images {user_id} turn 1")
        buttons.data_button("Remove Image", f"images {user_id} remov 0")
        buttons.data_button("Close", f"images {user_id} close")
        buttons.data_button("Remove All", f"images {user_id} removall", "footer")
        await delete_message(to_edit)
        total = len(Config.IMAGES)
        await send_message(
            message,
            f"<b>❖ IMAGE GALLERY</b>\n<code>└─ \U0001f304 No. : 1 / {total}\n</code>",
            buttons.build_menu(2),
            photo=Config.IMAGES[0],
        )


@new_task
async def pics_callback(_, query):
    message = query.message
    user_id = query.from_user.id
    data = query.data.split()
    if user_id != int(data[1]):
        await query.answer(text="Not Authorized User!", show_alert=True)
        return
    if data[2] == "turn":
        await query.answer()
        if not Config.IMAGES:
            await delete_message(message)
            await send_message(
                message,
                f"<b>No Photo to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
            )
            return
        ind = handleIndex(int(data[3]), Config.IMAGES)
        total = len(Config.IMAGES)
        no = ind + 1
        pic_info = f"<b>❖ IMAGE GALLERY</b>\n<code>└─ \U0001f304 No. : {no} / {total}\n</code>"
        buttons = ButtonMaker()
        buttons.data_button("\u00ab", f"images {data[1]} turn {ind - 1}")
        buttons.data_button("\u00bb", f"images {data[1]} turn {ind + 1}")
        buttons.data_button("Remove Image", f"images {data[1]} remov {ind}")
        buttons.data_button("Close", f"images {data[1]} close")
        buttons.data_button("Remove All", f"images {data[1]} removall", "footer")
        if message.media:
            await edit_message(message, pic_info, buttons.build_menu(2), photo=Config.IMAGES[ind])
        else:
            await delete_message(message)
            await send_message(
                message,
                pic_info,
                buttons.build_menu(2),
                photo=Config.IMAGES[ind],
            )
    elif data[2] == "remov":
        Config.IMAGES.pop(int(data[3]))
        if Config.DATABASE_URL:
            await database.update_config({"IMAGES": Config.IMAGES})
        await query.answer("Image Successfully Deleted", show_alert=True)
        if len(Config.IMAGES) == 0:
            await delete_message(message)
            await send_message(
                message,
                f"<b>No Photo to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
            )
            return
        ind = int(data[3])
        ind = min(ind, len(Config.IMAGES) - 1)
        total = len(Config.IMAGES)
        no = ind + 1
        pic_info = f"<b>❖ IMAGE GALLERY</b>\n<code>└─ \U0001f304 No. : {no} / {total}\n</code>"
        buttons = ButtonMaker()
        buttons.data_button("\u00ab", f"images {data[1]} turn {ind - 1}")
        buttons.data_button("\u00bb", f"images {data[1]} turn {ind + 1}")
        buttons.data_button("Remove Image", f"images {data[1]} remov {ind}")
        buttons.data_button("Close", f"images {data[1]} close")
        buttons.data_button("Remove All", f"images {data[1]} removall", "footer")
        if message.media:
            await edit_message(message, pic_info, buttons.build_menu(2), photo=Config.IMAGES[ind])
        else:
            await delete_message(message)
            await send_message(
                message,
                pic_info,
                buttons.build_menu(2),
                photo=Config.IMAGES[ind],
            )
    elif data[2] == "removall":
        Config.IMAGES.clear()
        if Config.DATABASE_URL:
            await database.update_config({"IMAGES": Config.IMAGES})
        await query.answer("All Images Successfully Deleted", show_alert=True)
        await delete_message(message)
        await send_message(
            message,
            f"<b>No Images to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
        )
    else:
        await query.answer()
        await delete_message(message)
        if message.reply_to_message:
            await delete_message(message.reply_to_message)

