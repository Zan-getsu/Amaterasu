"""Telegram entry point for the private session generator."""

from urllib.parse import urlencode

from pyrogram.enums import ChatType

from web.security import make_signed_token

from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.secrets import get_web_secret
from ..helper.ext_utils.telegram_session import SESSION_PAGE_TTL_SECONDS
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import send_message


@new_task
async def gen_pyro_string(_, message):
    if message.chat.type != ChatType.PRIVATE:
        await send_message(message, "Run /sessiongen in your private chat with the bot.")
        return
    user = message.from_user
    if user is None:
        await send_message(message, "Run /sessiongen from a Telegram user account.")
        return
    if not Config.BASE_URL:
        await send_message(
            message,
            "<b>Session Generator unavailable:</b> BASE_URL is not configured.",
        )
        return
    if not Config.DATABASE_URL:
        await send_message(
            message,
            "<b>Session Generator unavailable:</b> DATABASE_URL is required for private session storage.",
        )
        return

    page_token = make_signed_token(
        get_web_secret(),
        "telegram-session",
        user.id,
        ttl=SESSION_PAGE_TTL_SECONDS,
    )
    query = urlencode({"user_id": user.id, "token": page_token})
    url = f"{Config.BASE_URL.rstrip('/')}/app/session-generator?{query}"

    buttons = ButtonMaker()
    buttons.url_button("Open Session Generator", url)
    text = (
        "<b>Telegram Session Generator</b>\n\n"
        "Sign in through your private Amaterasu page. The generated session is "
        "encrypted in your database record and sent to your Saved Messages. "
        "This link belongs only to you and expires in 15 minutes. "
        "Run <code>/sessiongen</code> again for a fresh link."
    )
    await send_message(message, text, buttons.build_menu(1))
