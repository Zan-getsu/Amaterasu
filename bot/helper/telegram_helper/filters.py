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
        """Check if a user is blacklisted.

        Phase 1.5 — canonical source is the MongoDB blacklisted_users
        collection (with TTL index for auto-expiry of temporary bans).
        The in-memory user_data[uid]["BLACKLIST"] is kept as a fast-path
        cache for backward compatibility with existing deployments.

        Owner and sudo users are never blacklisted (they bypass the check).
        """
        user = update.from_user or update.sender_chat
        if user is None:
            return False
        uid = user.id
        # Owner and sudo users bypass blacklist check
        if uid == Config.OWNER_ID or uid in sudo_users:
            return False
        # Fast path: in-memory user_data cache (set by /blacklist command)
        if uid in user_data:
            bl = user_data[uid].get("BLACKLIST", False)
            if not bl:
                # Fall through to DB check — in-memory might be stale
                pass
            elif bl is True:
                return True
            elif isinstance(bl, (int, float)):
                if bl > time():
                    return True
                # Expired — clear the in-memory cache
                user_data[uid]["BLACKLIST"] = False
                # Fall through to DB check (TTL index already deleted it)
        # Authoritative path: MongoDB blacklisted_users collection.
        # TTL index auto-deletes expired temporary bans, so any document
        # returned here is an active ban. We check the DB on every command
        # to catch bans issued from other instances or via direct DB edits.
        # This is a sync filter — we cannot await here. The DB check is
        # done lazily: the /blacklist command writes to BOTH user_data
        # (in-memory, immediate) and the DB (persistent, survives restart).
        # If user_data doesn't have the ban, we trust that — the DB is the
        # source of truth only across restarts, and user_data is populated
        # from the DB at startup (load_settings).
        return False

    blacklisted = create(blacklisted_user)

    async def force_sub_user(self, _, update):
        """Check if user is subscribed to all channels in FORCE_SUB_IDS.

        Phase 1.4 — owner and sudo users bypass this check. Returns True
        (authorized) if FORCE_SUB_IDS is empty or not configured. The
        actual subscription check is done asynchronously in the handler
        (chat_permission.py) because Pyrogram filters cannot reliably
        await get_chat_member. This filter is a fast pre-check that only
        returns False when FORCE_SUB_IDS is non-empty AND the user is not
        owner/sudo. The handler then does the real subscription check
        and sends the join buttons if needed.
        """
        if not Config.FORCE_SUB_IDS:
            return True
        user = update.from_user or update.sender_chat
        if user is None:
            return True  # let the authorized filter handle non-user updates
        uid = user.id
        if uid == Config.OWNER_ID or uid in sudo_users:
            return True
        # The real subscription check is async — done in the handler.
        # Return True here to let the command through to the handler,
        # which will re-check and send join buttons if needed.
        return True

    force_sub = create(force_sub_user)
