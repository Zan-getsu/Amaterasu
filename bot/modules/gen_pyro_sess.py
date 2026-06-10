from asyncio import Event, TimeoutError as AsyncTimeout, wait_for
from html import escape
from os import getcwd
from os.path import exists as path_exists, join as path_join

from aiofiles.os import remove as aioremove
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import (
    ApiIdInvalid,
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)
from pyrogram.filters import create, private, text, user
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)

_STOP = "gensess_stop"
_TIMEOUT = 120


def _safe(value):
    return escape(str(value), quote=False)


def _stop_filter(uid):
    async def _check(_, __, update):
        return update.data == _STOP and update.from_user.id == uid

    return create(_check)


async def _safe_disconnect(client):
    try:
        await client.disconnect()
    except ConnectionError:
        pass


def _stop_btns():
    btns = ButtonMaker()
    btns.data_button("Cancel Process", data=_STOP)
    return btns.build_menu(1)


def _header(user_name):
    return (
        "<b><u>Pyrogram String Session Generator</u></b>\n\n"
        f"<b>User:</b> <code>{_safe(user_name)}</code>"
    )


def _collected(api_id=None, api_hash=None, phone=None):
    parts = []
    if api_id is not None:
        parts.append(f"<b>API_ID:</b> <code>{_safe(api_id)}</code>")
    if api_hash is not None:
        masked = api_hash[:4] + "*" * max(len(api_hash) - 4, 0)
        parts.append(f"<b>API_HASH:</b> <code>{_safe(masked)}</code>")
    if phone is not None:
        parts.append(f"<b>Phone:</b> <code>{_safe(phone)}</code>")
    return "\n".join(parts)


def _with_state(header, state, body):
    return f"{header}\n\n{state}\n\n{body}" if state else f"{header}\n\n{body}"


def _stop_msg(header, state):
    return _with_state(header, state, "<b>Process stopped.</b>")


def _timeout_msg(header, state):
    return _with_state(header, state, "<b>Timed out.</b>\n<i>Process stopped.</i>")


def _error_msg(header, state, error):
    return _with_state(header, state, error)


async def _invoke(user_id, timeout=_TIMEOUT):
    event = Event()
    result = [None]

    async def _on_text(_, message):
        await delete_message(message)
        result[0] = message.text or ""
        event.set()

    async def _on_stop(_, query):
        await query.answer()
        result[0] = _STOP
        event.set()

    text_handler = TgClient.bot.add_handler(
        MessageHandler(_on_text, filters=user(user_id) & text & private),
        group=-1,
    )
    stop_handler = TgClient.bot.add_handler(
        CallbackQueryHandler(_on_stop, filters=_stop_filter(user_id)),
        group=-1,
    )
    try:
        await wait_for(event.wait(), timeout)
    except AsyncTimeout:
        result[0] = None
    finally:
        TgClient.bot.remove_handler(*text_handler)
        TgClient.bot.remove_handler(*stop_handler)

    return result[0]


async def _stop_or_timeout(value, msg, header, state, pyro_client=None):
    if value is None:
        await edit_message(msg, _timeout_msg(header, state))
        if pyro_client:
            await _safe_disconnect(pyro_client)
        return True
    if value == _STOP:
        await edit_message(msg, _stop_msg(header, state))
        if pyro_client:
            await _safe_disconnect(pyro_client)
        return True
    return False


@new_task
async def gen_pyro_string(_, message):
    if message.chat.type != ChatType.PRIVATE:
        return

    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"
    buttons = _stop_btns()
    header = _header(user_name)

    sess_msg = await send_message(
        message,
        _with_state(
            header,
            "",
            "<i>Send your <code>API_ID</code> / <code>APP_ID</code>.</i>\n"
            "<i>Get it from <a href='https://my.telegram.org'>my.telegram.org</a>.</i>\n\n"
            f"<b>Timeout:</b> <code>{get_readable_time(_TIMEOUT)}</code>",
        ),
        buttons,
    )

    api_id = await _invoke(user_id)
    if await _stop_or_timeout(api_id, sess_msg, header, ""):
        return

    try:
        api_id = int(api_id)
    except ValueError:
        return await edit_message(
            sess_msg,
            _error_msg(header, "", "<i><code>API_ID</code> is invalid.</i>"),
        )

    state = _collected(api_id=api_id)
    await edit_message(
        sess_msg,
        _with_state(
            header,
            state,
            "<i>Send your <code>API_HASH</code>.</i>\n"
            "<i>Get it from <a href='https://my.telegram.org'>my.telegram.org</a>.</i>\n\n"
            f"<b>Timeout:</b> <code>{get_readable_time(_TIMEOUT)}</code>",
        ),
        buttons,
    )

    api_hash = await _invoke(user_id)
    if await _stop_or_timeout(api_hash, sess_msg, header, state):
        return
    if len(api_hash) <= 30:
        return await edit_message(
            sess_msg,
            _error_msg(header, state, "<i><code>API_HASH</code> is invalid.</i>"),
        )

    state = _collected(api_id=api_id, api_hash=api_hash)

    while True:
        await edit_message(
            sess_msg,
            _with_state(
                header,
                state,
                "<i>Send your phone number in international format.</i>\n"
                "<b>Example:</b> <code>+14154566376</code>",
            ),
            buttons,
        )

        phone_no = await _invoke(user_id)
        if await _stop_or_timeout(phone_no, sess_msg, header, state):
            return

        phone_state = _collected(api_id=api_id, api_hash=api_hash, phone=phone_no)
        await edit_message(
            sess_msg,
            _with_state(
                header,
                phone_state,
                f"Is <code>{_safe(phone_no)}</code> correct?\n"
                "<b>Send:</b> <code>y</code> / <code>yes</code> or "
                "<code>n</code> / <code>no</code>",
            ),
            buttons,
        )

        confirm = await _invoke(user_id)
        if await _stop_or_timeout(confirm, sess_msg, header, phone_state):
            return
        if confirm.lower() in ("y", "yes"):
            state = phone_state
            break

    workdir = getcwd()
    session_name = f"Amaterasu-{user_id}"
    try:
        pyro_client = Client(
            session_name,
            api_id=api_id,
            api_hash=api_hash,
            workdir=workdir,
        )
    except Exception as e:
        return await edit_message(
            sess_msg,
            _error_msg(header, state, f"<b>Client error:</b> <i>{_safe(e)}</i>"),
        )

    try:
        await pyro_client.connect()
    except ConnectionError:
        await _safe_disconnect(pyro_client)
        await pyro_client.connect()

    try:
        user_code = await pyro_client.send_code(phone_no)
    except FloodWait as e:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(
                header,
                state,
                f"<b>FloodWait:</b> <i>Retry after {get_readable_time(e.value)}.</i>",
            ),
        )
    except ApiIdInvalid:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(
                header,
                state,
                "<i><code>API_ID</code> and <code>API_HASH</code> are invalid.</i>",
            ),
        )
    except PhoneNumberInvalid:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(header, state, "<i>Phone number is invalid.</i>"),
        )

    await edit_message(
        sess_msg,
        _with_state(
            header,
            state,
            "<i>OTP sent to your phone number.</i>\n"
            "<i>Enter it in <code>1 2 3 4 5</code> format.</i>\n\n"
            f"<b>Timeout:</b> <code>{get_readable_time(_TIMEOUT)}</code>",
        ),
        buttons,
    )

    otp_str = await _invoke(user_id)
    if await _stop_or_timeout(otp_str, sess_msg, header, state, pyro_client):
        return

    otp = " ".join(str(otp_str).split())

    try:
        if not pyro_client.is_connected:
            await pyro_client.connect()
        await pyro_client.sign_in(phone_no, user_code.phone_code_hash, phone_code=otp)
    except PhoneCodeInvalid:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(header, state, "<i>OTP is invalid.</i>"),
        )
    except PhoneCodeExpired:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(header, state, "<i>OTP has expired.</i>"),
        )
    except SessionPasswordNeeded:
        hint = await pyro_client.get_password_hint()
        await edit_message(
            sess_msg,
            _with_state(
                header,
                state,
                "<i>Account is protected with two-step verification.</i>\n"
                f"<b>Hint:</b> <i>{_safe(hint)}</i>\n\n"
                "<i>Send your password now.</i>",
            ),
            buttons,
        )

        password = await _invoke(user_id)
        if await _stop_or_timeout(password, sess_msg, header, state, pyro_client):
            return

        try:
            await pyro_client.check_password(password.strip())
        except Exception as e:
            await _safe_disconnect(pyro_client)
            return await edit_message(
                sess_msg,
                _error_msg(header, state, f"<b>Password error:</b> <i>{_safe(e)}</i>"),
            )
    except Exception as e:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(header, state, f"<b>Sign-in error:</b> <i>{_safe(e)}</i>"),
        )

    try:
        session_string = await pyro_client.export_session_string()
        await pyro_client.send_message(
            "me",
            "<b><u>Pyrogram Session Generated</u></b>\n\n"
            f"<code>{_safe(session_string)}</code>\n\n"
            "<b>Via Amaterasu</b>",
            disable_web_page_preview=True,
        )
        await _safe_disconnect(pyro_client)
        await edit_message(
            sess_msg,
            _with_state(
                header,
                state,
                "<b>String session generated successfully.</b>\n\n"
                "<i>Check your Saved Messages.</i>",
            ),
        )
    except Exception as e:
        await _safe_disconnect(pyro_client)
        return await edit_message(
            sess_msg,
            _error_msg(header, state, f"<b>Export error:</b> <i>{_safe(e)}</i>"),
        )

    for ext in ("session", "session-journal"):
        path = path_join(workdir, f"{session_name}.{ext}")
        if path_exists(path):
            try:
                await aioremove(path)
            except Exception:
                pass
