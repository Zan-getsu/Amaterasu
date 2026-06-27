from os import getcwd, path as ospath
from urllib.parse import unquote, urlparse

from aiofiles import open as aiopen
from aiofiles.os import mkdir, path as aiopath, remove as aioremove
from aiohttp import ClientSession

from .. import LOGGER
from ..core.tg_client import TgClient
from ..helper.ext_utils.media_utils import generate_mediainfo_content
from ..helper.ext_utils.telegraph_helper import telegraph
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import send_message, edit_message
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.filters import regex


def _link_filename(link):
    parsed_name = unquote(urlparse(link).path.rsplit("/", 1)[-1]).strip()
    return parsed_name or "mediainfo-sample.bin"


def _media_filename(media, message):
    name = getattr(media, "file_name", None)
    if name:
        return name
    unique_id = getattr(media, "file_unique_id", None) or getattr(media, "file_id", None)
    message_id = getattr(message, "id", "media")
    return f"{unique_id or message_id}.media"


async def gen_mediainfo(message, link=None, media=None, mmsg=None):
    temp_send = await send_message(message, "<i>Generating MediaInfo...</i>")
    des_path = None
    tc = ""
    try:
        path = "mediainfo/"
        if not await aiopath.isdir(path):
            await mkdir(path)
        file_size = 0
        if link:
            filename = _link_filename(link)
            des_path = ospath.join(path, filename)
            headers = {
                "user-agent": "Mozilla/5.0 (Linux; Android 12; 2201116PI) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
            }
            async with ClientSession() as session:
                async with session.get(link, headers=headers) as response:
                    file_size = int(response.headers.get("Content-Length", 0))
                    async with aiopen(des_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(10000000):
                            await f.write(chunk)
                            break
        elif media:
            des_path = ospath.join(path, _media_filename(media, mmsg or message))
            file_size = media.file_size or 0
            if file_size <= 50000000:
                await mmsg.download(ospath.join(getcwd(), des_path))
            else:
                async for chunk in TgClient.bot.stream_media(mmsg, limit=5):
                    async with aiopen(des_path, "ab") as f:
                        await f.write(chunk)
        tc = await generate_mediainfo_content(des_path, file_size)
    except Exception as e:
        LOGGER.error(e)
        await edit_message(temp_send, f"MediaInfo Stopped due to {str(e)}")
        return
    finally:
        if des_path and await aiopath.exists(des_path):
            await aioremove(des_path)
    link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]
    await temp_send.edit(
        f"<b>MediaInfo:</b>\n\n➲ <b>Link :</b> https://graph.org/{link_id}",
        disable_web_page_preview=False,
    )


async def mediainfo(_, message):
    rply = message.reply_to_message
    help_msg = f"""
<b>By replying to media:</b>
<code>/{BotCommands.MediaInfoCommand[0]} or /{BotCommands.MediaInfoCommand[1]} [media]</code>

<b>By reply/sending download link:</b>
<code>/{BotCommands.MediaInfoCommand[0]} or /{BotCommands.MediaInfoCommand[1]} [link]</code>
"""
    if len(message.command) > 1 or rply and rply.text:
        link = rply.text if rply else message.command[1]
        return await gen_mediainfo(message, link)
    elif rply:
        if file := next(
            (
                i
                for i in [
                    rply.document,
                    rply.video,
                    rply.audio,
                    rply.voice,
                    rply.animation,
                    rply.video_note,
                ]
                if i is not None
            ),
            None,
        ):
            return await gen_mediainfo(message, None, file, rply)
        else:
            return await send_message(message, help_msg)
    else:
        return await send_message(message, help_msg)

async def minfo_callback(_, query):
    message = query.message
    await query.answer()
    if file := next(
        (
            i
            for i in [
                message.document,
                message.video,
                message.audio,
                message.voice,
                message.animation,
                message.video_note,
            ]
            if i is not None
        ),
        None,
    ):
        await gen_mediainfo(message, None, file, message)
    else:
        await send_message(message, "Media not found!")

TgClient.bot.add_handler(
    CallbackQueryHandler(minfo_callback, filters=regex("^minfo$"))
)
