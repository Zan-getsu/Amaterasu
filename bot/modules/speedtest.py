from asyncio import Lock
from html import escape

from speedtest import ConfigRetrievalError, Speedtest, SpeedtestException

from .. import LOGGER
from ..helper.ext_utils.bot_utils import new_task, sync_to_async
from ..helper.ext_utils.status_utils import get_readable_file_size
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)

_SPEEDTEST_LOCK = Lock()


def _safe_text(value, fallback="Unknown"):
    if value is None or value == "":
        return fallback
    return escape(str(value))


def _readable_size(value):
    try:
        return get_readable_file_size(max(0, float(value)))
    except (TypeError, ValueError):
        return "Unknown"


def _readable_rate(bits_per_second):
    try:
        return f"{get_readable_file_size(max(0, float(bits_per_second)) / 8)}/s"
    except (TypeError, ValueError):
        return "Unknown"


def _decimal(value, suffix=""):
    try:
        return f"{float(value):.2f}{suffix}"
    except (TypeError, ValueError):
        return "Unknown"


def _progress_message(stage, detail):
    return f"""<b>✦ NETWORK DIAGNOSTIC</b>

<b>Status</b> : <code>Running</code>
<b>Stage</b> : <code>{escape(stage)}</code>
<b>Detail</b> : <code>{escape(detail)}</code>"""


def _result_message(result):
    server = result.get("server") or {}
    client = result.get("client") or {}
    country = _safe_text(server.get("country"))
    country_code = _safe_text(server.get("cc"), "")
    server_location = (
        f"{country} ({country_code})" if country_code else country
    )

    return f"""<b>✦ SPEEDTEST COMPLETE</b>

<b>Status</b> : <code>Online</code>
<b>Download</b> : <code>{_readable_rate(result.get('download'))}</code>
<b>Upload</b> : <code>{_readable_rate(result.get('upload'))}</code>
<b>Ping</b> : <code>{_decimal(result.get('ping'), ' ms')}</code>
<b>Received</b> : <code>{_readable_size(result.get('bytes_received'))}</code>
<b>Sent</b> : <code>{_readable_size(result.get('bytes_sent'))}</code>
<b>Measured</b> : <code>{_safe_text(result.get('timestamp'))}</code>

<b>✦ TEST SERVER</b>

<b>Node</b> : <code>{_safe_text(server.get('name'))}</code>
<b>Location</b> : <code>{server_location}</code>
<b>Sponsor</b> : <code>{_safe_text(server.get('sponsor'))}</code>
<b>Latency</b> : <code>{_decimal(server.get('latency'), ' ms')}</code>
<b>Distance</b> : <code>{_decimal(server.get('d'), ' km')}</code>
<b>Coordinates</b> : <code>{_safe_text(server.get('lat'))}, {_safe_text(server.get('lon'))}</code>

<b>✦ CLIENT NETWORK</b>

<b>Provider</b> : <code>{_safe_text(client.get('isp'))}</code>
<b>Country</b> : <code>{_safe_text(client.get('country'))}</code>
<b>Coordinates</b> : <code>{_safe_text(client.get('lat'))}, {_safe_text(client.get('lon'))}</code>
<b>ISP Rating</b> : <code>{_decimal(client.get('isprating'))}</code>"""


def _failure_message(stage, detail):
    return f"""<b>✦ SPEEDTEST STOPPED</b>

<b>Status</b> : <code>Failed</code>
<b>Stage</b> : <code>{escape(stage)}</code>
<b>Cause</b> : <code>{escape(detail)}</code>

Try again after confirming the bot server can reach Speedtest.net."""


@new_task
async def speedtest(_, message):
    if _SPEEDTEST_LOCK.locked():
        await send_message(
            message,
            """<b>✦ SPEEDTEST BUSY</b>

<b>Status</b> : <code>Already running</code>
<b>Action</b> : <code>Wait for the current test to finish</code>""",
        )
        return

    async with _SPEEDTEST_LOCK:
        status = await send_message(
            message,
            _progress_message("Connecting", "Contacting Speedtest.net"),
        )
        stage = "Connecting"
        try:
            speed_results = await sync_to_async(Speedtest)

            stage = "Server selection"
            await edit_message(
                status,
                _progress_message(stage, "Finding the lowest-latency test node"),
            )
            best_server = await sync_to_async(speed_results.get_best_server)
            server_name = str((best_server or {}).get("name") or "Unknown")

            stage = "Download"
            await edit_message(
                status,
                _progress_message(stage, f"Testing against {server_name}"),
            )
            await sync_to_async(speed_results.download)

            stage = "Upload"
            await edit_message(
                status,
                _progress_message(stage, f"Testing against {server_name}"),
            )
            await sync_to_async(speed_results.upload)
        except ConfigRetrievalError:
            await edit_message(
                status,
                _failure_message(
                    stage,
                    "Speedtest.net did not provide a usable test configuration",
                ),
            )
            return
        except (SpeedtestException, OSError, TimeoutError) as error:
            LOGGER.warning("Speedtest failed during %s: %s", stage, error)
            await edit_message(
                status,
                _failure_message(stage, str(error) or type(error).__name__),
            )
            return
        except Exception as error:
            LOGGER.error("Unexpected speedtest failure", exc_info=True)
            await edit_message(
                status,
                _failure_message(stage, str(error) or type(error).__name__),
            )
            return

        stage = "Result card"
        await edit_message(
            status,
            _progress_message(stage, "Generating the share image"),
        )
        share_url = None
        try:
            share_url = await sync_to_async(speed_results.results.share)
        except Exception as error:
            LOGGER.warning(
                "Speedtest completed but its share image was unavailable: %s",
                error,
            )

        try:
            result = speed_results.results.dict()
            if not isinstance(result, dict):
                raise TypeError("Speedtest returned a non-dictionary result")
            result_text = _result_message(result)
        except Exception:
            LOGGER.error("Unable to render completed speedtest results", exc_info=True)
            await edit_message(
                status,
                _failure_message(
                    stage,
                    "The test completed, but its result data was invalid",
                ),
            )
            return

        photo = result.get("share") or share_url
        if not isinstance(photo, str) or not photo.startswith(("http://", "https://")):
            photo = None

        delivered = await send_message(message, result_text, photo=photo)
        if hasattr(delivered, "id"):
            await delete_message(status)
        else:
            await edit_message(status, result_text)
