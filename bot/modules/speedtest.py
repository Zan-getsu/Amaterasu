from speedtest import Speedtest, ConfigRetrievalError

from .. import LOGGER
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)
from ..helper.ext_utils.bot_utils import new_task, sync_to_async
from ..helper.ext_utils.status_utils import get_readable_file_size


@new_task
async def speedtest(_, message):
    speed = await send_message(message, "<i>Initiating Speedtest...</i>")
    try:
        speed_results = await sync_to_async(Speedtest)
        await sync_to_async(speed_results.get_best_server)
        await sync_to_async(speed_results.download)
        await sync_to_async(speed_results.upload)
    except ConfigRetrievalError:
        await edit_message(
            speed,
            "<b>ERROR:</b> <i>Can't connect to Server at the Moment, Try Again Later !</i>",
        )
        return

    result = speed_results.results.dict()
    string_speed = f"""<b>❖ SPEEDTEST INFO</b>
<pre>
┌─ {'Upload':<9}: {get_readable_file_size(result['upload'] / 8)}/s
├─ {'Download':<9}: {get_readable_file_size(result['download'] / 8)}/s
├─ {'Ping':<9}: {result['ping']} ms
├─ {'Time':<9}: {result['timestamp']}
├─ {'Data Sent':<9}: {get_readable_file_size(int(result['bytes_sent']))}
├─ {'Data Recv':<9}: {get_readable_file_size(int(result['bytes_received']))}
├─ ─── SPEEDTEST SERVER ─────────
├─ {'Name':<9}: {result['server']['name']}
├─ {'Country':<9}: {result['server']['country']}, {result['server']['cc']}
├─ {'Sponsor':<9}: {result['server']['sponsor']}
├─ {'Latency':<9}: {result['server']['latency']}
├─ {'Latitude':<9}: {result['server']['lat']}
└─ {'Longitude':<9}: {result['server']['lon']}
</pre>
"""
    try:
        await send_message(message, string_speed)
        await delete_message(speed)
    except Exception as e:
        LOGGER.error(str(e))
        await edit_message(speed, string_speed)
