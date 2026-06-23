from ast import literal_eval
from pyrogram import Client, enums
from pyrogram.errors import FloodWait
from pyrogram.types import ChatPrivileges
from asyncio import Lock, gather, sleep
from hashlib import sha256
from inspect import signature

from .. import LOGGER, bot_loop
from .config_manager import Config

# DB partition salt loaded from per-deployment secrets module.
# Backward-compat: if neither env var nor .amaterasu_secrets is set,
# falls back to the legacy constant so existing deployments keep their
# partition name (and thus their data). Set AMATERASU_DB_PARTITION_SALT
# explicitly to migrate to a fresh per-deployment value.
try:
    from ..helper.ext_utils.secrets import DB_PARTITION_SALT as _DB_PARTITION_SALT
except Exception:  # pragma: no cover
    _DB_PARTITION_SALT = b"wzmlx_v3_db_partition_salt"


def db_partition_id(bot_id):
    raw = sha256(_DB_PARTITION_SALT + str(bot_id).encode("utf-8")).hexdigest()
    return f"p_{raw[:24]}"


class TgClient:
    _lock = Lock()
    _hlock = Lock()
    _ulock = Lock()

    bot = None
    user = None
    helper_bots = {}
    helper_loads = {}
    stream_clients = {}
    stream_loads = {}
    helper_users = {}
    helper_user_loads = {}

    BNAME = ""
    ID = 0
    PARTITION = ""
    IS_PREMIUM_USER = False
    MAX_SPLIT_SIZE = 2097152000

    @classmethod
    def AmaterasutgClient(cls, *args, proxy=None, **kwargs):
        kwargs["api_id"] = Config.TELEGRAM_API
        kwargs["api_hash"] = Config.TELEGRAM_HASH
        kwargs["proxy"] = Config.TG_PROXY if proxy is None else proxy
        kwargs["parse_mode"] = enums.ParseMode.HTML
        kwargs["in_memory"] = True
        for param, value in {
            "max_concurrent_transmissions": 100,
            "skip_updates": False,
        }.items():
            if param in signature(Client.__init__).parameters:
                kwargs[param] = value
        return Client(*args, **kwargs)

    tgClient = AmaterasutgClient

    @classmethod
    def _parse_proxies(cls, raw):
        if not raw:
            return []
        proxies = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                proxies.append(None)
                continue
            try:
                parsed = literal_eval(line)
                proxies.append(parsed if isinstance(parsed, dict) else None)
            except (ValueError, SyntaxError):
                proxies.append(None)
        return proxies

    @classmethod
    async def _retry_hclient(cls, no, b_token, delay, proxy=None):
        await sleep(delay)
        try:
            hbot = cls.tgClient(
                f"Amaterasu-HBot{no}",
                bot_token=b_token,
                no_updates=True,
                proxy=proxy,
            )
            await hbot.start()
            LOGGER.info(f"Helper Bot [@{hbot.me.username}] Started!")
            cls.helper_bots[no], cls.helper_loads[no] = hbot, 0
        except FloodWait as e:
            LOGGER.warning(
                f"Helper Bot{no} FloodWait: Retrying in {e.value}s..."
            )
            bot_loop.create_task(cls._retry_hclient(no, b_token, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper bot {no} from HELPER_TOKENS. {e}")

    @classmethod
    async def start_hclient(cls, no, b_token, proxy=None):
        try:
            hbot = cls.tgClient(
                f"Amaterasu-HBot{no}",
                bot_token=b_token,
                no_updates=True,
                proxy=proxy,
            )
            await hbot.start()
            LOGGER.info(f"Helper Bot [@{hbot.me.username}] Started!")
            cls.helper_bots[no], cls.helper_loads[no] = hbot, 0
        except FloodWait as e:
            LOGGER.warning(
                f"Helper Bot{no} FloodWait: Retrying in {e.value}s (non-blocking)..."
            )
            bot_loop.create_task(cls._retry_hclient(no, b_token, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper bot {no} from HELPER_TOKENS. {e}")
            cls.helper_bots.pop(no, None)

    @classmethod
    async def start_helper_bots(cls):
        if not Config.HELPER_TOKENS:
            return
        LOGGER.info("Generating helper client from HELPER_TOKENS")
        bot_proxies = cls._parse_proxies(Config.HELPER_BOT_PROXIES)
        async with cls._hlock:
            await gather(
                *(
                    cls.start_hclient(
                        no, b_token,
                        bot_proxies[no - 1] if bot_proxies and no - 1 < len(bot_proxies) else None,
                    )
                    for no, b_token in enumerate(Config.HELPER_TOKENS.split(), start=1)
                )
            )

    @classmethod
    async def _retry_huser(cls, no, session_string, delay, proxy=None):
        await sleep(delay)
        try:
            huser = cls.tgClient(
                f"Amaterasu-HUser{no}",
                session_string=session_string,
                sleep_threshold=60,
                no_updates=True,
                proxy=proxy,
            )
            await huser.start()
            uname = huser.me.username or huser.me.first_name
            LOGGER.info(f"Helper User [{uname}] Started!")
            cls.helper_users[no], cls.helper_user_loads[no] = huser, 0
        except FloodWait as e:
            LOGGER.warning(f"Helper User{no} FloodWait: Retrying in {e.value}s...")
            bot_loop.create_task(cls._retry_huser(no, session_string, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper user {no} from HELPER_STRINGS. {e}")

    @classmethod
    async def start_huser(cls, no, session_string, proxy=None):
        try:
            huser = cls.tgClient(
                f"Amaterasu-HUser{no}",
                session_string=session_string,
                sleep_threshold=60,
                no_updates=True,
                proxy=proxy,
            )
            await huser.start()
            uname = huser.me.username or huser.me.first_name
            LOGGER.info(f"Helper User [{uname}] Started!")
            cls.helper_users[no], cls.helper_user_loads[no] = huser, 0
        except FloodWait as e:
            LOGGER.warning(
                f"Helper User{no} FloodWait: Retrying in {e.value}s (non-blocking)..."
            )
            bot_loop.create_task(cls._retry_huser(no, session_string, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper user {no} from HELPER_STRINGS. {e}")
            cls.helper_users.pop(no, None)

    @classmethod
    async def start_helper_users(cls):
        if not Config.HELPER_STRINGS:
            return
        LOGGER.info("Generating helper client from HELPER_STRINGS")
        user_proxies = cls._parse_proxies(Config.HELPER_USER_PROXIES)
        async with cls._ulock:
            await gather(
                *(
                    cls.start_huser(
                        no, session_string,
                        user_proxies[no - 1] if user_proxies and no - 1 < len(user_proxies) else None,
                    )
                    for no, session_string in enumerate(
                        Config.HELPER_STRINGS.split(), start=1
                    )
                )
            )

    @classmethod
    async def start_bot(cls):
        LOGGER.info("Generating client from BOT_TOKEN")
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        cls.PARTITION = db_partition_id(cls.ID)
        cls.bot = cls.tgClient(
            f"Amaterasu-Bot{cls.ID}",
            bot_token=Config.BOT_TOKEN,
            workdir="/usr/src/app",
        )
        # Cap retries so we don't loop forever if Telegram is permanently
        # rate-limiting the token (e.g. banned token, persistent network
        # issue). After MAX_RETRIES attempts, raise so the caller can
        # decide whether to exit or continue without the main bot.
        MAX_RETRIES = 10
        attempt = 0
        while attempt < MAX_RETRIES:
            try:
                await cls.bot.start()
                break
            except FloodWait as e:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    LOGGER.error(
                        f"Main bot FloodWait exhausted after {MAX_RETRIES} "
                        f"attempts (last wait: {e.value}s). Giving up — "
                        "check your BOT_TOKEN and network, then restart."
                    )
                    raise
                LOGGER.warning(
                    f"Main bot FloodWait: attempt {attempt}/{MAX_RETRIES}, "
                    f"sleeping {e.value}s before retry..."
                )
                await sleep(e.value)
        cls.BNAME = cls.bot.me.username
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        # Phase 4.8 — detect Telegram Premium on the bot account. Bots
        # can have premium if they're associated with a premium user.
        # Premium bots get 4 GB upload limit (vs 2 GB standard) and
        # higher rate limits. Store in Config.IS_PREMIUM_BOT for the
        # uploader to check. Also bump TgClient.MAX_SPLIT_SIZE if premium.
        try:
            bot_me = cls.bot.me
            is_premium = getattr(bot_me, "is_premium", False)
            Config.IS_PREMIUM_BOT = is_premium
            if is_premium:
                cls.MAX_SPLIT_SIZE = 4 * 1024 * 1024 * 1024  # 4 GB
                LOGGER.info(
                    f"Telegram Premium: enabled on bot account. "
                    f"File size limit: 4 GB"
                )
            else:
                LOGGER.info(
                    f"Telegram Premium: disabled on bot account. "
                    f"File size limit: 2 GB"
                )
        except Exception as e:
            LOGGER.warning(f"Could not detect bot premium status: {e}")
            Config.IS_PREMIUM_BOT = False
        LOGGER.info(f"Amaterasu Bot : [@{cls.BNAME}] Started!")

    @classmethod
    async def _retry_user(cls, delay):
        await sleep(delay)
        try:
            cls.user = cls.tgClient(
                "Amaterasu-User",
                session_string=Config.USER_SESSION_STRING,
                sleep_threshold=60,
                no_updates=True,
            )
            await cls.user.start()
            cls.IS_PREMIUM_USER = cls.user.me.is_premium
            if cls.IS_PREMIUM_USER:
                cls.MAX_SPLIT_SIZE = 4194304000
            uname = cls.user.me.username or cls.user.me.first_name
            LOGGER.info(f"WZ User : [{uname}] Started!")
        except FloodWait as e:
            LOGGER.warning(f"User client FloodWait: Retrying in {e.value}s...")
            bot_loop.create_task(cls._retry_user(e.value))
        except Exception as e:
            LOGGER.error(f"Failed to start client from USER_SESSION_STRING. {e}")
            cls.IS_PREMIUM_USER = False
            cls.user = None

    @classmethod
    async def start_user(cls):
        if Config.USER_SESSION_STRING:
            LOGGER.info("Generating client from USER_SESSION_STRING")
            try:
                cls.user = cls.tgClient(
                    "Amaterasu-User",
                    session_string=Config.USER_SESSION_STRING,
                    sleep_threshold=60,
                    no_updates=True,
                )
                await cls.user.start()
                cls.IS_PREMIUM_USER = cls.user.me.is_premium
                if cls.IS_PREMIUM_USER:
                    cls.MAX_SPLIT_SIZE = 4194304000
                uname = cls.user.me.username or cls.user.me.first_name
                LOGGER.info(f"Amaterasu User : [{uname}] Started!")
            except FloodWait as e:
                LOGGER.warning(
                    f"User client FloodWait: Retrying in {e.value}s (non-blocking)..."
                )
                bot_loop.create_task(cls._retry_user(e.value))
            except Exception as e:
                LOGGER.error(f"Failed to start client from USER_SESSION_STRING. {e}")
                cls.IS_PREMIUM_USER = False
                cls.user = None

    @classmethod
    async def start_stream_clients(cls):
        cls.stream_clients[0] = cls.bot
        cls.stream_loads[0] = 0

        tokens = [
            (key, token)
            for key, token in Config.MULTI_TOKENS.items()
            if token and token != Config.BOT_TOKEN
        ]
        if not tokens:
            return

        def token_sort(item):
            digits = "".join(ch for ch in item[0] if ch.isdigit())
            return int(digits) if digits else 0

        LOGGER.info("Generating stream clients from MULTI_TOKENs")
        for no, (key, token) in enumerate(sorted(tokens, key=token_sort), start=1):
            try:
                client = cls.tgClient(
                    f"Amaterasu-Stream{no}",
                    bot_token=token,
                    no_updates=True,
                )
                await client.start()
                cls.stream_clients[no] = client
                cls.stream_loads[no] = 0
                LOGGER.info(f"Stream Bot [{key}] [@{client.me.username}] Started!")
            except Exception as e:
                LOGGER.error(f"Failed to start stream bot from {key}. {e}")

    @classmethod
    async def provision_stream_bots(cls):
        """Add configured FileToLink stream bots to storage chats on startup.

        Telegram bot accounts cannot invite other bots, so this opt-in flow
        runs through the configured user session. The caller logs any
        provisioning error and continues normal bot startup.
        """
        if not Config.AUTO_PROVISION_STREAM_BOTS:
            return
        if cls.user is None:
            raise RuntimeError(
                "AUTO_PROVISION_STREAM_BOTS requires a running USER_SESSION_STRING"
            )

        chat_ids = []
        for raw_chat_id in (Config.BIN_CHANNEL, Config.LEECH_DUMP_CHAT):
            if raw_chat_id in (None, "", 0, "0"):
                continue
            try:
                chat_id = int(raw_chat_id)
            except (TypeError, ValueError) as e:
                raise RuntimeError(
                    f"Invalid provisioning chat ID: {raw_chat_id!r}"
                ) from e
            if chat_id not in chat_ids:
                chat_ids.append(chat_id)
        if not chat_ids:
            raise RuntimeError(
                "AUTO_PROVISION_STREAM_BOTS requires BIN_CHANNEL or LEECH_DUMP_CHAT"
            )

        expected_tokens = {
            token
            for token in Config.MULTI_TOKENS.values()
            if token and token != Config.BOT_TOKEN
        }
        stream_bots = {}
        for client_id, client in cls.stream_clients.items():
            if client_id == 0 or not getattr(client, "me", None):
                continue
            stream_bots[client.me.id] = client.me.username or str(client.me.id)
        if not stream_bots or len(stream_bots) != len(expected_tokens):
            raise RuntimeError(
                "Not all configured MULTI_TOKEN stream bots started; "
                "cannot provision an incomplete FileToLink pool"
            )

        for chat_id in chat_ids:
            try:
                chat = await cls.user.get_chat(chat_id)
            except Exception as e:
                raise RuntimeError(
                    f"Cannot inspect provisioning chat {chat_id}: {e}"
                ) from e
            is_channel = chat.type == enums.ChatType.CHANNEL
            for bot_id, bot_name in stream_bots.items():
                # The stream client knows its own numeric ID, but that ID is
                # not necessarily in the user session's peer cache. Resolve
                # the public bot username first so subsequent member/invite
                # operations have a valid InputUser peer.
                try:
                    peer = await cls.user.get_users(bot_name)
                    bot_id = peer.id
                except Exception as e:
                    raise RuntimeError(
                        f"Cannot resolve FileToLink stream bot [@{bot_name}]: {e}"
                    ) from e
                try:
                    member = await cls.user.get_chat_member(chat_id, bot_id)
                except Exception as e:
                    if type(e).__name__ != "UserNotParticipant":
                        raise RuntimeError(
                            f"Cannot check @{bot_name} in {chat_id}: {e}"
                        ) from e
                    if is_channel:
                        # Telegram channels do not allow bots to be ordinary
                        # members (USER_BOT). promote_chat_member below adds
                        # the bot directly as an administrator.
                        member = None
                    else:
                        try:
                            await cls.user.add_chat_members(chat_id, bot_id)
                            member = await cls.user.get_chat_member(chat_id, bot_id)
                            LOGGER.info(
                                f"Added FileToLink stream bot [@{bot_name}] to {chat_id}"
                            )
                        except Exception as add_error:
                            raise RuntimeError(
                                f"Cannot add [@{bot_name}] to {chat_id}: {add_error}"
                            ) from add_error

                status = str(getattr(member, "status", "")).lower()
                if member and any(
                    role in status for role in ("administrator", "owner", "creator")
                ):
                    continue
                try:
                    await cls.user.promote_chat_member(
                        chat_id,
                        bot_id,
                        privileges=ChatPrivileges(
                            can_manage_chat=True,
                            can_post_messages=True,
                        ),
                    )
                    LOGGER.info(
                        f"Promoted FileToLink stream bot [@{bot_name}] in {chat_id}"
                    )
                except Exception as e:
                    raise RuntimeError(
                        f"Cannot promote [@{bot_name}] in {chat_id}: {e}"
                    ) from e

    @classmethod
    async def stop(cls):
        async with cls._lock:
            clients = []
            if cls.bot:
                clients.append(cls.bot.stop())
                cls.bot = None
            if cls.user:
                clients.append(cls.user.stop())
                cls.user = None
            if cls.helper_bots:
                clients.extend(h_bot.stop() for h_bot in cls.helper_bots.values())
                cls.helper_bots = {}
            if cls.stream_clients:
                stop_tasks = [
                    client.stop()
                    for cid, client in cls.stream_clients.items()
                    if cid != 0
                ]
                if stop_tasks:
                    await gather(*stop_tasks)
                cls.stream_clients = {}
                cls.stream_loads = {}
            if cls.helper_users:
                clients.extend(h_user.stop() for h_user in cls.helper_users.values())
                cls.helper_users = {}
            if clients:
                await gather(*clients, return_exceptions=True)
            LOGGER.info("All Client(s) stopped")

    @classmethod
    async def reload(cls):
        async with cls._lock:
            await cls.bot.restart()
            if cls.user:
                await cls.user.restart()
            if cls.helper_bots:
                await gather(*[h_bot.restart() for h_bot in cls.helper_bots.values()])
            if cls.stream_clients:
                restart_tasks = [
                    client.restart()
                    for cid, client in cls.stream_clients.items()
                    if cid != 0
                ]
                if restart_tasks:
                    await gather(*restart_tasks)
            if cls.helper_users:
                await gather(
                    *[h_user.restart() for h_user in cls.helper_users.values()]
                )
            LOGGER.info("All Client(s) restarted")
