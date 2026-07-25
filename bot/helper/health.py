"""Runtime health reporting for Telegram and Hyper transfer components."""

from datetime import UTC, datetime


def _client_state(client, connection_check=None):
    if client is None:
        return "not_configured"
    connected = (
        connection_check(client)
        if connection_check is not None
        else bool(getattr(client, "is_connected", False))
    )
    if connected:
        return "connected"
    return "disconnected"


def _configured_stream_token_count(config):
    bot_token = getattr(config, "BOT_TOKEN", "")
    return sum(
        1
        for token in getattr(config, "MULTI_TOKENS", {}).values()
        if token and token != bot_token
    )


def get_health_report():
    """Build a secret-free snapshot suitable for the public health route."""
    from bot.core.config_manager import Config
    from bot.core.tg_client import (
        WARP_ALIGNED_CHUNK_SIZE,
        TelegramClient,
        TgClient,
    )

    runtime = TelegramClient.runtime()
    def client_state(client):
        return _client_state(client, TelegramClient.is_connected)

    configured_bot_tokens = len(
        [token for token in (Config.HELPER_TOKENS or "").split() if token]
    )
    configured_user_sessions = len(
        [session for session in (Config.HELPER_STRINGS or "").split() if session]
    )
    active_bot_tokens = sum(
        client_state(client) == "connected"
        for client in TgClient.helper_bots.values()
    )
    active_user_sessions = sum(
        client_state(client) == "connected"
        for client in TgClient.helper_users.values()
    ) + int(client_state(TgClient.user) == "connected")

    bot_state = client_state(TgClient.bot)
    user_state = client_state(TgClient.user)
    stream_states = {
        str(client_id): client_state(client)
        for client_id, client in TgClient.stream_clients.items()
    }
    configured_stream_clients = _configured_stream_token_count(Config) + int(
        bool(Config.BOT_TOKEN)
    )
    active_stream_clients = sum(
        state == "connected" for state in stream_states.values()
    )

    crypto_active = runtime["crypto"] == "WarpCrypto"
    bot_connected = bot_state == "connected"
    stream_pool_ready = (
        configured_stream_clients == 0
        or active_stream_clients >= configured_stream_clients
    )
    healthy = crypto_active and bot_connected and stream_pool_ready

    return {
        "status": "ok" if healthy else "degraded",
        "checked_at": datetime.now(UTC).isoformat(),
        "bot_connection_status": bot_state,
        "crypto_library": runtime["crypto"],
        "crypto_acceleration_active": crypto_active,
        "wzgram_version": runtime["version"],
        "max_concurrent_transmissions": runtime[
            "max_concurrent_transmissions"
        ],
        # HyperDL and HyperUP share the helper-token pool. Keep explicit fields
        # for dashboards that alert on either transfer direction.
        "hyperdl_token_count": configured_bot_tokens,
        "hyperup_token_count": configured_bot_tokens,
        "hyper": {
            "enabled": bool(Config.USE_HYPER),
            "configured_bot_token_count": configured_bot_tokens,
            "active_bot_token_count": active_bot_tokens,
            "configured_user_session_count": configured_user_sessions,
            "active_user_session_count": active_user_sessions,
        },
        "clients": {
            "bot": bot_state,
            "user": user_state,
            "stream": {
                "configured_count": configured_stream_clients,
                "active_count": active_stream_clients,
                "states": stream_states,
            },
        },
        "stream_chunk_size": WARP_ALIGNED_CHUNK_SIZE,
    }
