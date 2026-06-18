from asyncio import sleep, gather
from random import choice
from re import match as re_match, search as re_search, sub
from time import time

from pyrogram.types import Message, InputMediaPhoto
from pyrogram.enums import ButtonStyle, ParseMode
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    MessageEmpty,
    ReplyMarkupInvalid,
    PhotoInvalidDimensions,
    WebpageCurlFailed,
    WebpageMediaEmpty,
    MediaEmpty,
    MediaCaptionTooLong,
    EntityBoundsInvalid,
    MessageIdInvalid,
    PeerIdInvalid,
)

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from ... import LOGGER, bot_cache, categories_dict, intervals, status_dict, task_dict_lock, user_data
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.bot_utils import SetInterval, download_image_url, fetch_drive_cat
from ..ext_utils.exceptions import TgLinkException
from ..ext_utils.status_utils import get_readable_message
from .button_build import ButtonMaker


def _resolve_photo(photo):
    if photo == "IMAGES":
        if Config.IMAGES:
            Config.USE_IMAGES = True
            return choice(Config.IMAGES)
        return None
    return photo


def _shorten_caption(text, limit=900):
    text = sub(r"<[^>]+>", "", str(text))
    suffix = "\n\n... (truncated)"
    if len(text) <= limit:
        return text
    return f"{text[:limit - len(suffix)]}{suffix}"


async def _send_text(message, text, buttons=None, **kwargs):
    if isinstance(message, (int, str)):
        try:
            chat_id = int(message)
        except ValueError:
            chat_id = message
        return await TgClient.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            disable_notification=True,
            reply_markup=buttons,
        )
    return await message.reply(
        text=text,
        quote=True,
        disable_web_page_preview=True,
        disable_notification=True,
        reply_markup=buttons,
        **kwargs,
    )


async def send_message(message, text, buttons=None, block=True, photo=None, **kwargs):
    try:
        if photo:
            try:
                photo = _resolve_photo(photo)
                if photo is None:
                    return await _send_text(message, text, buttons, **kwargs)
                if isinstance(message, Message):
                    return await message.reply_photo(
                        photo=photo,
                        reply_to_message_id=message.id,
                        caption=text,
                        quote=True,
                        reply_markup=buttons,
                        disable_notification=True,
                        **kwargs,
                    )
                return await TgClient.bot.send_photo(
                    chat_id=message,
                    photo=photo,
                    caption=text,
                    reply_markup=buttons,
                    disable_notification=True,
                    **kwargs,
                )
            except FloodWait as f:
                LOGGER.warning(str(f))
                if not block:
                    return str(f)
                await sleep(f.value * 1.2)
                return await send_message(message, text, buttons, block, photo)
            except MediaCaptionTooLong:
                return await send_message(
                    message,
                    _shorten_caption(text),
                    buttons,
                    block,
                    photo,
                )
            except (
                PhotoInvalidDimensions,
                WebpageCurlFailed,
                WebpageMediaEmpty,
                MediaEmpty,
            ):
                try:
                    des_dir = await download_image_url(photo)
                    if des_dir:
                        msg = await send_message(message, text, buttons, block, des_dir)
                        from aiofiles.os import remove as aioremove

                        await aioremove(des_dir)
                        return msg
                except Exception:
                    LOGGER.error("Failed to send fallback photo", exc_info=True)
                return await _send_text(message, text, buttons, **kwargs)
            except Exception:
                LOGGER.error("Error while sending photo", exc_info=True)
                return await _send_text(message, text, buttons, **kwargs)
        
        return await _send_text(message, text, buttons, **kwargs)
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await send_message(message, text, buttons)
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await send_message(message, text, None)
    except (MessageEmpty, EntityBoundsInvalid):
        return await send_message(message, text, parse_mode=ParseMode.DISABLED)
    except PeerIdInvalid:
        LOGGER.warning(f"PeerIdInvalid {type(message)}") # My Debug Style
        if isinstance(message, (int, str)):
            return await send_message(int(message), text, buttons, block, photo)
    except ConnectionError:
        return
    except Exception as e:
        if "PeerIdInvalid" in str(type(e).__name__):
            LOGGER.warning(f"PeerIdInvalid {type(message)}")
            if isinstance(message, (int, str)):
                return await send_message(int(message), text, buttons, block, photo)
        LOGGER.error(str(e), exc_info=True)
        return str(e)



async def edit_message(message, text, buttons=None, block=True, photo=None):
    try:
        photo = _resolve_photo(photo)
        if message.media:
            if photo:
                if photo:
                    try:
                        return await message.edit_media(
                            InputMediaPhoto(photo, text), reply_markup=buttons
                        )
                    except (
                        PhotoInvalidDimensions,
                        WebpageCurlFailed,
                        WebpageMediaEmpty,
                        MediaEmpty,
                    ):
                        des_dir = await download_image_url(photo)
                        if des_dir:
                            msg = await message.edit_media(
                                InputMediaPhoto(des_dir, text), reply_markup=buttons
                            )
                            from aiofiles.os import remove as aioremove

                            await aioremove(des_dir)
                            return msg
                        return await message.edit_caption(
                            caption=text, reply_markup=buttons
                        )
            return await message.edit_caption(caption=text, reply_markup=buttons)
        if photo:
            try:
                new_message = await send_message(
                    message.chat.id, text, buttons, block, photo
                )
                await delete_message(message)
                return new_message
            except Exception:
                LOGGER.error("Failed to replace text message with photo", exc_info=True)
        return await message.edit(
            text=text,
            disable_web_page_preview=True,
            reply_markup=buttons,
        )
    except (MessageNotModified, MessageEmpty, MessageIdInvalid):
        pass
    except EntityBoundsInvalid:
        if message.media:
            return await message.edit_caption(
                caption=text,
                reply_markup=buttons,
                parse_mode=ParseMode.DISABLED,
            )
        return await message.edit(
            text=text,
            disable_web_page_preview=True,
            reply_markup=buttons,
            parse_mode=ParseMode.DISABLED,
        )
    except MediaCaptionTooLong:
        short_text = _shorten_caption(text)
        if message.media:
            if photo:
                try:
                    return await message.edit_media(
                        InputMediaPhoto(
                            photo,
                            short_text,
                            parse_mode=ParseMode.DISABLED,
                        ),
                        reply_markup=buttons,
                    )
                except Exception:
                    pass
            return await message.edit_caption(
                caption=short_text,
                reply_markup=buttons,
                parse_mode=ParseMode.DISABLED,
            )
        return await message.edit(
            text=short_text,
            disable_web_page_preview=True,
            reply_markup=buttons,
            parse_mode=ParseMode.DISABLED,
        )
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await edit_message(message, text, None, block, photo)
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await edit_message(message, text, buttons, block, photo)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def edit_reply_markup(message, buttons):
    try:
        return await message.edit_reply_markup(reply_markup=buttons)
    except (MessageNotModified, MessageIdInvalid):
        pass
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await edit_reply_markup(message, buttons)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def send_file(message, file, caption="", buttons=None):
    try:
        return await message.reply_document(
            document=file,
            quote=True,
            caption=caption,
            disable_notification=True,
            reply_markup=buttons,
        )
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_file(message, file, caption)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def send_rss(text, chat_id, thread_id):
    try:
        app = TgClient.user or TgClient.bot
        return await app.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            message_thread_id=thread_id,
            disable_notification=True,
        )
    except (FloodWait, FloodPremiumWait) as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_rss(text, chat_id, thread_id)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def delete_message(*args):
    tasks = [msg.delete() for msg in args if isinstance(msg, Message)]
    if not tasks:
        return
    results = await gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            err_msg = str(result)
            if "MESSAGE_DELETE_FORBIDDEN" in err_msg:
                LOGGER.debug("Could not delete message (likely a service message or no permissions).")
            else:
                LOGGER.error(err_msg)


async def delete_links(message):
    if Config.DELETE_LINKS:
        await delete_message(message, message.reply_to_message)


async def auto_delete_message(*args, stime=90):
    await sleep(stime)
    await delete_message(*args)


async def delete_status():
    async with task_dict_lock:
        for key, data in list(status_dict.items()):
            try:
                await delete_message(data["message"])
                del status_dict[key]
            except Exception as e:
                LOGGER.error(str(e))


async def get_tg_link_message(link):
    message = None
    links = []
    if link.startswith(
        (
            "https://t.me/",
            "https://telegram.me/",
            "https://telegram.dog/",
            "https://telegram.space/",
        )
    ):
        private = False
        msg = re_match(
            r"https:\/\/(t\.me|telegram\.me|telegram\.dog|telegram\.space)\/(?:c\/)?([^\/]+)(?:\/[^\/]+)?\/([0-9-]+)",
            link,
        )
    else:
        private = True
        msg = re_match(
            r"tg:\/\/(openmessage)\?user_id=([0-9]+)&message_id=([0-9-]+)", link
        )
        if not TgClient.user:
            raise TgLinkException("USER_SESSION_STRING required for this private link!")

    chat = msg[2]
    msg_id = msg[3]
    if "-" in msg_id:
        start_id, end_id = msg_id.split("-")
        msg_id = start_id = int(start_id)
        end_id = int(end_id)
        btw = end_id - start_id
        if private:
            link = link.split("&message_id=")[0]
            links.append(f"{link}&message_id={start_id}")
            for _ in range(btw):
                start_id += 1
                links.append(f"{link}&message_id={start_id}")
        else:
            link = link.rsplit("/", 1)[0]
            links.append(f"{link}/{start_id}")
            for _ in range(btw):
                start_id += 1
                links.append(f"{link}/{start_id}")
    else:
        msg_id = int(msg_id)

    if chat.isdigit():
        chat = int(chat) if private else int(f"-100{chat}")

    if not private:
        try:
            message = await TgClient.bot.get_messages(chat_id=chat, message_ids=msg_id)
            if message.empty:
                private = True
        except Exception as e:
            private = True
            if not TgClient.user:
                raise e

    if not private:
        return (links, "bot") if links else (message, "bot")
    elif TgClient.user:
        try:
            user_message = await TgClient.user.get_messages(
                chat_id=chat, message_ids=msg_id
            )
        except Exception as e:
            raise TgLinkException(
                f"You don't have access to this chat!. ERROR: {e}"
            ) from e
        if not user_message.empty:
            return (links, "user") if links else (user_message, "user")
    else:
        raise TgLinkException("Private: Please report!")


async def update_status_message(sid, force=False):
    if intervals["stopAll"]:
        return
    async with task_dict_lock:
        if not status_dict.get(sid):
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
            return
        if time() < status_dict[sid].get("flood_until", 0):
            return
        if not force and time() - status_dict[sid]["time"] < 3:
            return
        status_dict[sid]["time"] = time()
        page_no = status_dict[sid]["page_no"]
        status = status_dict[sid]["status"]
        is_user = status_dict[sid]["is_user"]
        page_step = status_dict[sid]["page_step"]
        text, buttons = await get_readable_message(
            sid, is_user, page_no, status, page_step
        )
        if text is None:
            del status_dict[sid]
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
            return
        if text != status_dict[sid]["message"].text:
            message = await edit_message(
                status_dict[sid]["message"], text, buttons, block=False, photo="IMAGES"
            )
            if isinstance(message, str):
                if "FLOOD_WAIT" in message:
                    wait_match = re_search(r"wait (\d+) seconds", message)
                    wait_seconds = (
                        int(wait_match.group(1))
                        if wait_match
                        else Config.STATUS_UPDATE_INTERVAL
                    )
                    status_dict[sid]["flood_until"] = time() + wait_seconds
                    LOGGER.warning(
                        "Status updates for %s paused for %ss due to Telegram FloodWait.",
                        sid,
                        wait_seconds,
                    )
                    return
                if message.startswith("Telegram says: [40"):
                    del status_dict[sid]
                    if obj := intervals["status"].get(sid):
                        obj.cancel()
                        del intervals["status"][sid]
                else:
                    LOGGER.error(
                        f"Status with id: {sid} haven't been updated. Error: {message}"
                    )
                return
            status_dict[sid]["message"].text = text
            status_dict[sid]["time"] = time()


async def send_status_message(msg, user_id=0):
    if intervals["stopAll"]:
        return
    sid = user_id or msg.chat.id
    is_user = bool(user_id)
    async with task_dict_lock:
        if sid in status_dict:
            page_no = status_dict[sid]["page_no"]
            status = status_dict[sid]["status"]
            page_step = status_dict[sid]["page_step"]
            text, buttons = await get_readable_message(
                sid, is_user, page_no, status, page_step
            )
            if text is None:
                del status_dict[sid]
                if obj := intervals["status"].get(sid):
                    obj.cancel()
                    del intervals["status"][sid]
                return
            old_message = status_dict[sid]["message"]
            message = await send_message(msg, text, buttons, block=False, photo="IMAGES")
            if isinstance(message, str):
                LOGGER.error(
                    f"Status with id: {sid} haven't been sent. Error: {message}"
                )
                return
            await delete_message(old_message)
            message.text = text
            status_dict[sid].update({"message": message, "time": time()})
        else:
            text, buttons = await get_readable_message(sid, is_user)
            if text is None:
                return
            message = await send_message(msg, text, buttons, block=False, photo="IMAGES")
            if isinstance(message, str):
                LOGGER.error(
                    f"Status with id: {sid} haven't been sent. Error: {message}"
                )
                return
            message.text = text
            status_dict[sid] = {
                "message": message,
                "time": time(),
                "page_no": 1,
                "page_step": 1,
                "status": "All",
                "is_user": is_user,
            }
        if not intervals["status"].get(sid) and not is_user:
            intervals["status"][sid] = SetInterval(
                Config.STATUS_UPDATE_INTERVAL, update_status_message, sid
            )


async def open_category_btns(message):
    user_id = message.from_user.id
    msg_id = message.id
    buttons = ButtonMaker()
    cat_name = None
    dcats = fetch_drive_cat(user_id)
    default_id = user_data.get(user_id, {}).get("GDRIVE_ID") or Config.GDRIVE_ID
    default_index = user_data.get(user_id, {}).get("INDEX_URL") or Config.INDEX_URL
    merged = {
        "Default": {"drive_id": default_id, "index_link": default_index},
        **dcats,
        **categories_dict,
    }
    for i, name in enumerate(merged):
        if i == 0:
            cat_name = name
        buttons.data_button(
            f'{"✓️" if i == 0 else ""} {name}',
            f"scat {user_id} {msg_id} {name.replace(' ', '_')}",
        )
    buttons.data_button(
        "Cancel", f"scat {user_id} {msg_id} scancel", "footer", style=ButtonStyle.DANGER
    )
    buttons.data_button(
        "Done (60)", f"scat {user_id} {msg_id} sdone", "footer", style=ButtonStyle.SUCCESS
    )
    prompt = await send_message(
        message,
        f"<b>Select the category where you want to upload</b>\n\n"
        f"<i><b>Upload Category:</b></i> <code>{cat_name or 'None'}</code>\n\n"
        f"<b>Timeout:</b> 60 sec",
        buttons.build_menu(3),
    )
    start_time = time()
    bot_cache[msg_id] = [None, None, False, False, start_time]
    while time() - start_time <= 60:
        await sleep(0.5)
        if bot_cache[msg_id][2] or bot_cache[msg_id][3]:
            break
    drive_id, index_link, _, is_cancelled, __ = bot_cache[msg_id]
    if not is_cancelled:
        await delete_message(prompt)
    else:
        await edit_message(prompt, "<b>Task Cancelled</b>")
    del bot_cache[msg_id]
    return drive_id, index_link, is_cancelled


async def open_drive_clean(message):
    user_id = message.from_user.id
    msg_id = message.id
    buttons = ButtonMaker()
    dcats = fetch_drive_cat(user_id)
    default_id = user_data.get(user_id, {}).get("GDRIVE_ID") or Config.GDRIVE_ID
    default_index = user_data.get(user_id, {}).get("INDEX_URL") or Config.INDEX_URL
    merged = {
        "Default": {"drive_id": default_id, "index_link": default_index},
        **dcats,
        **categories_dict,
    }
    first_cat = None
    for i, name in enumerate(merged):
        if i == 0:
            first_cat = name
        buttons.data_button(
            f'{"✓️" if i == 0 else ""} {name}',
            f"gdccat {user_id} {msg_id} {name.replace(' ', '_')}",
        )
    buttons.data_button(
        "Cancel",
        f"gdccat {user_id} {msg_id} ccancel",
        position="footer",
        style=ButtonStyle.DANGER,
    )
    prompt = await send_message(
        message,
        f"<b>Select Drive Category to Clean</b>\n\n"
        f"<b>Category:</b> <code>{first_cat or 'None'}</code>\n\n"
        f"<b>Timeout:</b> 60 sec",
        buttons.build_menu(3),
    )
    start_time = time()
    bot_cache[msg_id] = [None, False, False, start_time]
    while time() - start_time <= 60:
        await sleep(0.5)
        if bot_cache[msg_id][1] or bot_cache[msg_id][2]:
            break
    drive_id = bot_cache[msg_id][0]
    is_cancelled = bot_cache[msg_id][1]
    if not is_cancelled:
        await delete_message(prompt)
    else:
        await edit_message(prompt, "<b>Task Cancelled</b>")
    del bot_cache[msg_id]
    return drive_id, is_cancelled

