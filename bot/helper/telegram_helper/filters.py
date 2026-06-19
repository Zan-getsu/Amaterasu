from time import time

from pyrogram.filters import create
from pyrogram.enums import ChatType

from ... import auth_chats, sudo_users, user_data
from ...core.config_manager import Config
from .tg_utils import chat_info


class CustomFilters:
    async def owner_filter(self, _, update):
        user = update.from_user or update.sender_chat
        return user is not None and user.id == Config.OWNER_ID

    owner = create(owner_filter)

    async def authorized_user(self, _, update):
        """Authorize if any of:
            - user is the owner
            - user has AUTH or SUDO flag in user_data[uid]
            - user is in the global sudo_users set
            - chat has AUTH flag in user_data[chat_id] (with optional
              thread_id restriction)
            - chat is in the global auth_chats dict (with optional
              thread_id restriction)

        Thread restriction rules:
            - If the configured thread_ids list is empty/None, the chat
              is authorized in ALL threads (including non-topic chats).
            - If thread_ids is non-empty, the chat is authorized ONLY in
              the listed threads (and only when the update is from a
              topic message in one of those threads).
        """
        user = update.from_user or update.sender_chat
        if user is None:
            return False
        uid = user.id
        chat_id = update.chat.id
        thread_id = (
            update.message_thread_id if update.is_topic_message else None
        )

        # Owner is god.
        if uid == Config.OWNER_ID:
            return True

        # Per-user AUTH or SUDO flag in user_data (keyed by uid).
        user_cfg = user_data.get(uid, {})
        if user_cfg.get("AUTH") or user_cfg.get("SUDO"):
            return True

        # Global sudo list.
        if uid in sudo_users:
            return True

        # Per-chat AUTH (user_data keyed by chat_id).
        chat_cfg = user_data.get(chat_id, {})
        if chat_cfg.get("AUTH"):
            allowed_threads = chat_cfg.get("thread_ids")
            if not allowed_threads:
                return True
            if thread_id is not None and thread_id in allowed_threads:
                return True

        # Global auth_chats (Config.AUTHORIZED_CHATS, parsed into the
        # auth_chats dict at startup). The dict value is a (possibly
        # empty) list of allowed thread_ids.
        if chat_id in auth_chats:
            allowed_threads = auth_chats[chat_id]
            if not allowed_threads:
                return True
            if thread_id is not None and thread_id in allowed_threads:
                return True

        return False

    authorized = create(authorized_user)

    async def authorized_usetting(self, _, update):
        uid = (update.from_user or update.sender_chat).id
        is_exists = False
        if await CustomFilters.authorized("", update):
            is_exists = True
        elif update.chat.type == ChatType.PRIVATE:
            for channel_id in user_data:
                if not (
                    user_data[channel_id].get("is_auth")
                    and str(channel_id).startswith("-100")
                ):
                    continue
                try:
                    if await (await chat_info(str(channel_id))).get_member(uid):
                        is_exists = True
                        break
                except Exception:
                    continue
        return is_exists

    authorized_uset = create(authorized_usetting)

    async def sudo_user(self, _, update):
        user = update.from_user or update.sender_chat
        if user is None:
            return False
        uid = user.id
        return bool(
            uid == Config.OWNER_ID
            or uid in user_data
            and user_data[uid].get("SUDO")
            or uid in sudo_users
        )

    sudo = create(sudo_user)

    async def blacklisted_user(self, _, update):
        uid = (update.from_user or update.sender_chat).id
        if uid not in user_data:
            return False
        bl = user_data[uid].get("BLACKLIST", False)
        if not bl:
            return False
        if bl is True:
            return True
        if isinstance(bl, (int, float)):
            if bl > time():
                return True
            user_data[uid]["BLACKLIST"] = False
            return False
        return False

    blacklisted = create(blacklisted_user)
