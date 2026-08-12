from ast import literal_eval
from asyncio import CancelledError, Lock, gather, get_running_loop, sleep
from hashlib import sha256
from importlib import import_module
from inspect import signature

from pyrogram import Client, enums
from pyrogram import __version__ as WZGRAM_VERSION
from pyrogram.errors import FloodWait
from pyrogram.types import ChatPrivileges

from .. import LOGGER, bot_loop
from .config_manager import Config

MAX_CONCURRENT_TRANSMISSIONS = 8
WARP_ALIGNED_CHUNK_SIZE = 1024 * 1024
_TRANSIENT_RPC_ERRORS = frozenset(
    {
        "InternalServerError",
        "InterDcCallError",
        "InterDcCallRichError",
        "RpcCallFail",
        "ServiceUnavailable",
    }
)

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:  # WZGram/Pyrogram compatibility
    FloodPremiumWait = FloodWait


def get_crypto_backend():
    """Return the crypto adapter WZGram is actually bound to at runtime."""
    try:
        aes = import_module("pyrogram.crypto.aes")
    except (AttributeError, ImportError, OSError):
        return "Unavailable"
    try:
        warpcrypto = import_module("warpcrypto")
    except (ImportError, OSError):
        warpcrypto = None
    if warpcrypto is not None and getattr(aes, "warpcrypto", None) is warpcrypto:
        return "WarpCrypto"

    # Report the adapter bound into AES, not a package that merely happens to
    # be installed in the environment.
    encrypt_module = getattr(
        getattr(aes, "ige256_encrypt", None),
        "__module__",
        "",
    ).lower()
    if getattr(aes, "tgcrypto", None) is not None or "tgcrypto" in encrypt_module:
        return "TgCrypto"
    return "Python"


def _query_name(query):
    """Get a stable raw API operation name, unwrapping invoke containers."""
    inner = query
    for _ in range(4):
        wrapped = getattr(inner, "query", None)
        if wrapped is None or wrapped is inner:
            break
        inner = wrapped
    return getattr(inner, "QUALNAME", type(inner).__name__)


def _query_is_idempotent(query):
    """Avoid replaying ambiguous send/admin calls after transport failures."""
    name = _query_name(query).split(".")[-1]
    return (
        name.startswith(("Get", "Search", "Check", "Read", "Ping"))
        or name
        in {
            "GetFile",
            "GetWebFile",
            "ReuploadCdnFile",
            "SaveFilePart",
            "SaveBigFilePart",
        }
    )


async def resilient_tg_operation(
    operation,
    *args,
    operation_name=None,
    max_attempts=3,
    idempotent=True,
    **kwargs,
):
    """Run one Telegram operation with bounded, flood-aware retries.

    Every client created by :class:`TelegramClient` routes raw API calls
    through this boundary. Flood waits are safe to retry because Telegram
    rejected the request. Ambiguous mutating requests are not replayed after
    transport/server errors, preventing duplicate messages and admin actions.
    """
    name = operation_name or getattr(operation, "__name__", "telegram_operation")
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation(*args, **kwargs)
        except CancelledError:
            raise
        except (FloodWait, FloodPremiumWait) as error:
            if attempt >= max_attempts:
                raise
            delay = max(float(getattr(error, "value", 1)), 1.0) + 1.0
            LOGGER.warning(
                "Telegram %s hit FloodWait; retry %s/%s in %.1fs",
                name,
                attempt + 1,
                max_attempts,
                delay,
            )
            await sleep(delay)
        except Exception as error:
            transient = isinstance(error, (ConnectionError, OSError, TimeoutError)) or (
                type(error).__name__ in _TRANSIENT_RPC_ERRORS
            )
            if not transient or not idempotent or attempt >= max_attempts:
                raise
            delay = min(2 ** (attempt - 1), 8)
            LOGGER.warning(
                "Transient Telegram %s failure (%s); retry %s/%s in %ss",
                name,
                type(error).__name__,
                attempt + 1,
                max_attempts,
                delay,
            )
            await sleep(delay)


class WzgramClient(Client):
    """WZGram implementation behind Amaterasu's framework-neutral boundary."""

    async def invoke(self, query, *args, **kwargs):
        query_name = _query_name(query)
        try:
            return await resilient_tg_operation(
                super().invoke,
                query,
                *args,
                operation_name=query_name,
                idempotent=_query_is_idempotent(query),
                **kwargs,
            )
        except Exception as error:
            # Telegram callback acknowledgements expire quickly.  Treat only
            # this acknowledgement RPC as a no-op so the handler can still
            # perform its real action (close, back, refresh, and so on).
            if (
                type(error).__name__ == "QueryIdInvalid"
                and query_name.split(".")[-1] == "SetBotCallbackAnswer"
            ):
                return None
            raise

    async def _get_media_session_pool(self, dc_id, requested_size):
        return await _get_stable_media_session_pool(
            self,
            dc_id,
            requested_size,
        )


class TelegramClient:
    """Small construction/runtime facade for future MTProto framework swaps."""

    framework = "WZGram"

    @staticmethod
    def create(*args, **kwargs):
        backend = get_crypto_backend()
        if backend != "WarpCrypto":
            raise RuntimeError(
                f"WZGram requires active WarpCrypto; detected {backend}"
            )
        return WzgramClient(*args, **kwargs)

    @staticmethod
    def is_connected(client):
        if client is None:
            return False
        state = getattr(client, "is_connected", False)
        return bool(state() if callable(state) else state)

    @staticmethod
    def runtime():
        return {
            "framework": TelegramClient.framework,
            "version": WZGRAM_VERSION,
            "crypto": get_crypto_backend(),
            "max_concurrent_transmissions": MAX_CONCURRENT_TRANSMISSIONS,
        }


def _stabilize_peer_username_storage(client):
    """Normalize WZGram peer aliases before SQLite parameter binding.

    Telegram occasionally supplies integer/string wrapper objects which look
    valid to Python but are rejected by sqlite3's parameter binder.  WZGram's
    peer cache is disposable, but an uncaught binding error also aborts that
    update-dispatch task.  Coercing the two persisted scalar types keeps the
    normal storage implementation and transaction behavior intact.
    """
    storage = getattr(client, "storage", None)
    if storage is None or getattr(storage, "_amaterasu_usernames_stabilized", False):
        return client

    update_usernames = storage.update_usernames

    async def normalized_update_usernames(usernames):
        normalized = []
        for peer_id, aliases in usernames:
            try:
                peer_id = int(peer_id)
            except (TypeError, ValueError, OverflowError):
                LOGGER.warning("Skipping malformed Telegram peer id: %r", peer_id)
                continue
            if isinstance(aliases, str):
                aliases = [aliases]
            clean_aliases = [str(alias) for alias in aliases if alias is not None]
            if clean_aliases:
                normalized.append((peer_id, clean_aliases))
        return await update_usernames(normalized)

    storage.update_usernames = normalized_update_usernames
    storage._amaterasu_usernames_stabilized = True
    return client


async def _get_stable_media_session_pool(client, dc_id, requested_size):
    lock = client._media_sessions_locks.setdefault(dc_id, Lock())
    async with lock:
        requested_size = max(1, int(requested_size))
        pool = [
            session
            for session in client.media_session_pools.get(dc_id, [])
            if session.is_started.is_set()
        ]
        session = client.media_sessions.get(dc_id)
        if session is None or not session.is_started.is_set():
            if session is not None:
                try:
                    await session.stop()
                except Exception:
                    pass
                client.media_sessions.pop(dc_id, None)
            session = await client.get_session(dc_id, is_media=True)
        if session not in pool:
            pool.insert(0, session)

        while len(pool) < requested_size:
            try:
                pool.append(
                    await client.get_session(
                        dc_id,
                        is_media=True,
                        temporary=True,
                    )
                )
            except Exception as error:
                # The first standard session is a known-good fallback.
                # Returning the available pool keeps uploads operational
                # even if Telegram temporarily rejects an extra session.
                LOGGER.warning(
                    "WZGram media pool started %s/%s sessions for DC%s: %s",
                    len(pool),
                    requested_size,
                    dc_id,
                    error,
                )
                break

        client.media_session_pools[dc_id] = pool
        return list(pool)


def _report_wzgram_upload_pool():
    """Build WZGram pools through its reliable media-endpoint resolver.

    WZGram 3.0.23 downloads create their first media connection through
    Client.get_session(), while uploads use a separate pool constructor. A
    failure in that constructor occurs before the first progress callback and
    Session.start retries silently, leaving every upload at zero percent.

    Seed the pool with the proven cached media session and create additional
    sessions through ``get_session(..., temporary=True)``.  That path resolves
    WZGram's dynamic media-only endpoint while preserving its native four
    upload sessions and four workers per session.
    """
    try:
        save_file_module = import_module("pyrogram.methods.advanced.save_file")
    except (ImportError, AttributeError):
        return

    LOGGER.info(
        "WZGram media pools stabilized: %s sessions x %s chunk workers",
        getattr(save_file_module, "POOL_SIZE", 1),
        getattr(save_file_module, "WORKERS_PER_SESSION", 1),
    )


_report_wzgram_upload_pool()

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
    helper_bot_clients = {}
    stream_clients = {}
    stream_loads = {}
    stream_prewarm = {}
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
        try:
            client_loop = get_running_loop()
        except RuntimeError:
            client_loop = bot_loop
        for param, value in {
            "loop": client_loop,
            "max_concurrent_transmissions": MAX_CONCURRENT_TRANSMISSIONS,
            "skip_updates": False,
        }.items():
            if param in signature(Client.__init__).parameters:
                kwargs[param] = value
        return _stabilize_peer_username_storage(
            TelegramClient.create(*args, **kwargs)
        )

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
            cls.helper_bot_clients[b_token] = hbot
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
            cls.helper_bot_clients[b_token] = hbot
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
        helper_tokens = Config.helper_bot_tokens()
        if not helper_tokens:
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
                    for no, b_token in enumerate(helper_tokens, start=1)
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
                    "Telegram Premium: enabled on bot account. "
                    "File size limit: 4 GB"
                )
            else:
                LOGGER.info(
                    "Telegram Premium: disabled on bot account. "
                    "File size limit: 2 GB"
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
        cls.stream_prewarm = {}
        cls.stream_clients[0] = cls.bot
        cls.stream_loads[0] = 0

        tokens = Config.stream_bot_tokens()
        if not tokens:
            await cls.prewarm_stream_clients()
            return

        helper_tokens = Config.helper_bot_tokens()
        helper_proxies = cls._parse_proxies(Config.HELPER_BOT_PROXIES)
        proxy_by_token = {
            token: helper_proxies[index]
            for index, token in enumerate(helper_tokens)
            if index < len(helper_proxies) and helper_proxies[index] is not None
        }

        LOGGER.info("Generating configured FileToLink stream clients")
        for no, token in enumerate(tokens, start=1):
            try:
                client = cls.helper_bot_clients.get(token)
                if client is None:
                    client = cls.tgClient(
                        f"Amaterasu-Stream{no}",
                        bot_token=token,
                        no_updates=True,
                        proxy=proxy_by_token.get(token),
                    )
                    await client.start()
                    source = "Stream Bot"
                else:
                    source = "Shared Helper Bot"
                cls.stream_clients[no] = client
                cls.stream_loads[no] = 0
                LOGGER.info(f"{source} [@{client.me.username}] Started!")
            except Exception as e:
                LOGGER.error(f"Failed to start FileToLink stream bot {no}. {e}")
        await cls.prewarm_stream_clients()

    @classmethod
    async def prewarm_stream_clients(cls):
        """Verify every stream bot has a live API connection before serving."""

        async def warm(client_id, client):
            if client is None:
                return False
            media_dc_id = None
            try:
                await resilient_tg_operation(
                    client.get_me,
                    operation_name=f"stream_client_{client_id}.get_me",
                    max_attempts=2,
                )
                # Client.start() only opens the main MTProto session. Streaming
                # uses a separate media session, so establish the home media
                # DC now to avoid first-request connection/auth latency.
                media_dc_id = await client.storage.dc_id()
                requested_pool_size = max(
                    1,
                    int(getattr(client, "DOWNLOAD_POOL_SIZE", 1) or 1),
                )
                media_pool = await client._get_media_session_pool(
                    media_dc_id,
                    requested_pool_size,
                )
                ready_sessions = sum(
                    session.is_started.is_set() for session in media_pool
                )
                if not ready_sessions:
                    raise ConnectionError("media session pool did not start")
                LOGGER.info(
                    "Pre-warmed FileToLink stream client %s "
                    "(control + media DC%s, sessions=%s/%s)",
                    client_id,
                    media_dc_id,
                    ready_sessions,
                    requested_pool_size,
                )
                return True
            except Exception as error:
                if media_dc_id is not None:
                    stale_session = client.media_sessions.get(media_dc_id)
                    if (
                        stale_session is not None
                        and not stale_session.is_started.is_set()
                    ):
                        client.media_sessions.pop(media_dc_id, None)
                        try:
                            await stale_session.stop()
                        except Exception as stop_error:
                            LOGGER.debug(
                                "Could not stop stale media session for stream "
                                "client %s: %s",
                                client_id,
                                stop_error,
                            )
                LOGGER.warning(
                    "FileToLink stream client %s pre-warm failed: %s",
                    client_id,
                    error,
                )
                return False

        if not cls.stream_clients:
            cls.stream_prewarm = {}
            return
        clients = list(cls.stream_clients.items())
        results = await gather(
            *(warm(client_id, client) for client_id, client in clients)
        )
        cls.stream_prewarm = {
            client_id: bool(result)
            for (client_id, _), result in zip(
                clients,
                results,
                strict=True,
            )
        }
        LOGGER.info(
            "FileToLink stream pool ready: %s/%s connections pre-warmed",
            sum(results),
            len(results),
        )

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
        for raw_chat_id in (
            Config.effective_bin_channel(),
            Config.LEECH_DUMP_CHAT,
        ):
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

        expected_tokens = set(Config.stream_bot_tokens())
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
                clients.append(cls.bot)
                cls.bot = None
            if cls.user:
                clients.append(cls.user)
                cls.user = None
            if cls.helper_bots:
                clients.extend(cls.helper_bots.values())
                cls.helper_bots = {}
            cls.helper_loads = {}
            cls.helper_bot_clients = {}
            if cls.stream_clients:
                clients.extend(
                    client
                    for cid, client in cls.stream_clients.items()
                    if cid != 0
                )
                cls.stream_clients = {}
            cls.stream_loads = {}
            cls.stream_prewarm = {}
            if cls.helper_users:
                clients.extend(cls.helper_users.values())
                cls.helper_users = {}
            cls.helper_user_loads = {}
            if clients:
                unique_clients = {id(client): client for client in clients}.values()
                await gather(
                    *(client.stop() for client in unique_clients),
                    return_exceptions=True,
                )
            LOGGER.info("All Client(s) stopped")

    @classmethod
    async def reload(cls):
        async with cls._lock:
            clients = [cls.bot]
            if cls.user:
                clients.append(cls.user)
            if cls.helper_bots:
                clients.extend(cls.helper_bots.values())
            if cls.stream_clients:
                clients.extend(
                    client
                    for cid, client in cls.stream_clients.items()
                    if cid != 0
                )
            if cls.helper_users:
                clients.extend(cls.helper_users.values())
            unique_clients = {
                id(client): client for client in clients if client is not None
            }.values()
            await gather(
                *(client.restart() for client in unique_clients)
            )
            LOGGER.info("All Client(s) restarted")
