"""Telegram entry point for the per-user Google token generator."""

from urllib.parse import urlencode

from web.security import make_signed_token

from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.google_token import TOKEN_PAGE_TTL_SECONDS
from ..helper.ext_utils.secrets import get_web_secret
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import send_message


@new_task
async def token_generator(_, message):
    user = message.from_user
    if user is None:
        await send_message(message, "Run /tokengen from a Telegram user account.")
        return
    if not Config.BASE_URL:
        await send_message(
            message,
            "<b>Token Generator unavailable:</b> BASE_URL is not configured.",
        )
        return
    if not Config.DATABASE_URL:
        await send_message(
            message,
            "<b>Token Generator unavailable:</b> DATABASE_URL is required for private token storage.",
        )
        return

    page_token = make_signed_token(
        get_web_secret(),
        "google-token",
        user.id,
        ttl=TOKEN_PAGE_TTL_SECONDS,
    )
    query = urlencode({"user_id": user.id, "token": page_token})
    url = f"{Config.BASE_URL.rstrip('/')}/app/token-generator?{query}"

    buttons = ButtonMaker()
    buttons.url_button("🌐 Open Token Generator", url)
    text = (
        "<b>Google Token Generator</b>\n\n"
        "Create, replace, or download your private <code>token.pickle</code>. "
        "This link belongs only to you and expires in 15 minutes. "
        "Run <code>/tokengen</code> again whenever you need a fresh link."
    )
    await send_message(message, text, buttons.build_menu(1))
