from html import escape
from pyrogram.enums import ButtonStyle
from time import monotonic, time
from uuid import uuid4
from re import match, compile as re_compile, IGNORECASE as re_IGNORECASE

from aiofiles import open as aiopen
from cloudscraper import create_scraper
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .. import LOGGER, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task, update_user_ldata
from ..helper.ext_utils.links_utils import decode_slink
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.ext_utils.db_handler import database
from ..helper.languages import Language
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    edit_reply_markup,
    send_file,
    send_message,
)


@new_task
async def start(_, message):
    userid = message.from_user.id
    lang = Language()
    buttons = ButtonMaker()
    buttons.url_button(
        lang.START_BUTTON1, "https://github.com/its-niloy/Amaterasu"
    )
    buttons.url_button(lang.START_BUTTON2, "https://t.me/itsniloybhowmick")
    reply_markup = buttons.build_menu(2)

    if len(message.command) > 1 and message.command[1] == "amaterasu":
        await delete_message(message)
    elif len(message.command) > 1 and message.command[1] != "start":
        decrypted_url = decode_slink(message.command[1])
        if Config.MEDIA_STORE and decrypted_url.startswith("file"):
            decrypted_url = decrypted_url.replace("file", "")
            chat_id, msg_id = decrypted_url.split("&&")
            LOGGER.info(f"Copying message from {chat_id} & {msg_id} to {userid}")
            return await TgClient.bot.copy_message(  # TODO: make it function
                chat_id=userid,
                from_chat_id=int(chat_id) if match(r"\d+", chat_id) else chat_id,
                message_id=int(msg_id),
                disable_notification=True,
            )
        elif Config.VERIFY_TIMEOUT:
            input_token, pre_uid = decrypted_url.split("&&")
            if int(pre_uid) != userid:
                return await send_message(
                    message,
                    "<b>Access Token is not yours!</b>\n\n<i>Kindly generate your own to use.</i>",
                )
            data = user_data.get(userid, {})
            if "VERIFY_TOKEN" not in data or data["VERIFY_TOKEN"] != input_token:
                return await send_message(
                    message,
                    "<b>Access Token already used!</b>\n\n<i>Kindly generate a new one.</i>",
                )
            elif (
                Config.LOGIN_PASS
                and data["VERIFY_TOKEN"].casefold() == Config.LOGIN_PASS.casefold()
            ):
                return await send_message(
                    message,
                    "<b>Bot Already Logged In via Password</b>\n\n<i>No Need to Accept Temp Tokens.</i>",
                )
            buttons.data_button(
                "Activate Access Token", f"start pass {input_token}", "header"
            )
            reply_markup = buttons.build_menu(2)
            msg = f"""⌬ Access Login Token : 
    │
    ┟ <b>Status</b> → <code>Generated Successfully</code>
    ┟ <b>Access Token</b> → <code>{input_token}</code>
    ┃
    ┖ <b>Validity:</b> {get_readable_time(int(Config.VERIFY_TIMEOUT))}"""
            return await send_message(message, msg, reply_markup)

    if await CustomFilters.authorized(_, message):
        start_string = lang.START_MSG.format(
            cmd=BotCommands.HelpCommand[0],
        )
        await send_message(message, start_string, reply_markup, photo="IMAGES")
    elif Config.BOT_PM:
        await send_message(
            message,
            "<i>Now, Bot will send you all your files and links here. Start Using Now...</i>",
            reply_markup,
            photo="IMAGES",
        )
    else:
        await send_message(
            message,
            "<i>Bot can mirror/leech from links|tgfiles|torrents|nzb|rclone-cloud to any rclone cloud, Google Drive or to telegram.\n\n⚠️ You Are not authorized user! Deploy your own Amaterasu bot</i>",
            reply_markup,
            photo="IMAGES",
        )
    await database.set_pm_users(userid)


@new_task
async def start_cb(_, query):
    user_id = query.from_user.id
    input_token = query.data.split()[2]
    data = user_data.get(user_id, {})

    if input_token == "activated":
        return await query.answer("Already Activated!", show_alert=True)
    elif "VERIFY_TOKEN" not in data or data["VERIFY_TOKEN"] != input_token:
        return await query.answer("Already Used, Generate New One", show_alert=True)

    update_user_ldata(user_id, "VERIFY_TOKEN", str(uuid4()))
    update_user_ldata(user_id, "VERIFY_TIME", time())
    if Config.DATABASE_URL:
        await database.update_user_data(user_id)
    await query.answer("Activated Access Login Token!", show_alert=True)

    kb = query.message.reply_markup.inline_keyboard[1:]
    kb.insert(
        0,
        [
            InlineKeyboardButton(
                "✅️ Activated ✅", callback_data="start pass activated"
            )
        ],
    )
    await edit_reply_markup(query.message, InlineKeyboardMarkup(kb))


@new_task
async def login(_, message):
    if Config.LOGIN_PASS is None:
        return await send_message(message, "<i>Login is not enabled !</i>")
    elif len(message.command) > 1:
        user_id = message.from_user.id
        input_pass = message.command[1]

        if user_data.get(user_id, {}).get("VERIFY_TOKEN", "") == Config.LOGIN_PASS:
            return await send_message(
                message, "<b>Already Bot Login In!</b>\n\n<i>No Need to Login Again</i>"
            )

        if input_pass.casefold() != Config.LOGIN_PASS.casefold():
            return await send_message(
                message, "<b>Wrong Password!</b>\n\n<i>Kindly check and try again</i>"
            )

        update_user_ldata(user_id, "VERIFY_TOKEN", Config.LOGIN_PASS)
        if Config.DATABASE_URL:
            await database.update_user_data(user_id)
        return await send_message(
            message, "<b>Bot Permanent Logged In!</b>\n\n<i>Now you can use the bot</i>"
        )
    else:
        await send_message(
            message, "<b>Bot Login Usage :</b>\n\n<code>/login [password]</code>"
        )


@new_task
async def ping(_, message):
    start_time = monotonic()
    reply = await send_message(message, "<i>Starting Ping..</i>")
    end_time = monotonic()
    await edit_message(
        reply, f"<i>Pong!</i>\n <code>{int((end_time - start_time) * 1000)} ms</code>"
    )


# --- Log redaction ------------------------------------------------------
# Patterns that match credential-bearing substrings in log lines.
# Each pattern is replaced with the captured group + '[REDACTED]'.
_REDACT_PATTERNS = [
    # /qbit/?pass=... / /nzb/?pass=...
    re_compile(r"(pass=)[A-Za-z0-9]+"),
    # api_key=..., apikey=..., key=..., token=..., password=..., secret=...
    re_compile(r"((?:api_?key|key|token|password|secret|apikey)=)[^\s&]+", re_IGNORECASE),
    # Authorization: Bearer ...
    re_compile(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9._\-]+", re_IGNORECASE),
    # MongoDB connection string with credentials:
    # mongodb://user:pass@host
    re_compile(r"(mongodb(?:\+srv)?://[^:/@\s]+:)[^@/\s]+(@)"),
    # Generic email:pass pairs (e.g. JD_EMAIL:JD_PASS, MEGA_EMAIL:MEGA_PASSWORD)
    re_compile(r"((?:JD_PASS|MEGA_PASSWORD|LOGIN_PASS)\s*=\s*)[^\s]+", re_IGNORECASE),
    # BOT_TOKEN value patterns (numeric:id:hex) — common when log lines
    # echo the token by accident
    re_compile(r"(\bBOT_TOKEN\s*=\s*)\d+:[A-Za-z0-9_\-]+", re_IGNORECASE),
]


def _redact_log_content(text: str) -> str:
    """Redact known credential patterns from a log string.

    Applied before sending log.txt to a chat or pastebin. Catches the
    most common leaks (pass=, api_key=, Authorization: Bearer, MongoDB
    URL with creds, BOT_TOKEN=). Not exhaustive — operators should still
    avoid logging secrets in the first place.
    """
    def _replace(m):
        # Always preserve group(1) (the prefix like 'pass=' or 'mongodb://user:')
        out = m.group(1) + "[REDACTED]"
        # If the pattern has a group(2) (e.g. the '@' in mongodb://user:pass@host),
        # preserve it too so the log line stays readable.
        if m.lastindex and m.lastindex >= 2:
            out += m.group(2)
        return out

    for pattern in _REDACT_PATTERNS:
        text = pattern.sub(_replace, text)
    return text


@new_task
async def log(_, message):
    uid = message.from_user.id
    buttons = ButtonMaker()
    buttons.data_button("Log Disp", f"log {uid} disp")
    buttons.data_button("Web Log", f"log {uid} web")
    buttons.data_button("✕ CLOSE", f"log {uid} close", style=ButtonStyle.DANGER)
    # Read log.txt, redact secrets, write to a temp file, send that.
    # Avoids sending the raw log.txt which may contain pass= / token=
    # leaks from earlier unredacted log lines.
    import os
    from uuid import uuid4
    try:
        async with aiopen("log.txt", "r") as f:
            content = await f.read()
        redacted = _redact_log_content(content)
        # Unique filename per invocation — avoids races if the same user
        # runs /log twice concurrently.
        tmp_path = f"log_redacted_{uid}_{uuid4().hex[:8]}.txt"
        async with aiopen(tmp_path, "w") as f:
            await f.write(redacted)
        await send_file(message, tmp_path, buttons=buttons.build_menu(2))
        # Best-effort cleanup after sending
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    except FileNotFoundError:
        await send_message(message, "log.txt not found.")
    except Exception as e:
        LOGGER.error(f"Failed to send redacted log: {e}")
        await send_message(message, f"Failed to read log: {e}")


@new_task
async def log_cb(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message, message.reply_to_message)
    elif data[2] == "disp":
        await query.answer("Fetching Log..")
        async with aiopen("log.txt", "r") as f:
            content = await f.read()
        content = _redact_log_content(content)  # redact before display

        def parse(line):
            parts = line.split("] [", 1)
            return f"[{parts[1]}" if len(parts) > 1 else line

        try:
            res, total = [], 0
            for line in reversed(content.splitlines()):
                line = parse(line)
                res.append(line)
                total += len(line) + 1
                if total > 3500:
                    break

            joined_res = '\n'.join(reversed(res))
            text = f"<b>Showing Last {len(res)} Lines from log.txt:</b> \n\n----------<b>START LOG</b>----------\n\n<blockquote expandable>{escape(joined_res)}</blockquote>\n----------<b>END LOG</b>----------"

            btn = ButtonMaker()
            btn.data_button("✕ CLOSE", f"log {user_id} close", style=ButtonStyle.DANGER)
            await send_message(message, text, btn.build_menu(1))
            await edit_reply_markup(message, None)
        except Exception as err:
            LOGGER.error(f"TG Log Display : {str(err)}")
    elif data[2] == "web":
        boundary = "R1eFDeaC554BUkLF"
        headers = {
            "Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary{boundary}",
            "Origin": "https://spaceb.in",
            "Referer": "https://spaceb.in/",
            "sec-ch-ua": '"Not-A.Brand";v="99", "Chromium";v="124"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        }

        async with aiopen("log.txt", "r") as f:
            content = await f.read()
        content = _redact_log_content(content)  # redact before pastebin upload

        data = (
            f"------WebKitFormBoundary{boundary}\r\n"
            f'Content-Disposition: form-data; name="content"\r\n\r\n'
            f"{content}\r\n"
            f"------WebKitFormBoundary{boundary}--\r\n"
        )

        cget = create_scraper().request
        resp = cget("POST", "https://spaceb.in/", headers=headers, data=data)
        if resp.status_code == 200:
            await query.answer("Generating..")
            btn = ButtonMaker()
            btn.url_button("📨 Web Paste (SB)", resp.url, style=ButtonStyle.PRIMARY)
            await edit_reply_markup(message, btn.build_menu(1))
        else:
            await query.answer("Web Paste Failed ! Check Logs", show_alert=True)

