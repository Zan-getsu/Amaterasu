from speedtest import Speedtest, ConfigRetrievalError

from pyrogram import Client
from pyrogram.types import Message

from bot.core.plugin_manager import PluginBase, PluginInfo
from bot.helper.ext_utils.bot_utils import new_task, sync_to_async
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)


class SpeedtestPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="speedtest_plugin",
        version="1.5.0",
        author="Amaterasu",
        description="Speedtest plugin for testing internet speed",
        enabled=True,
        handlers=[],
        commands=["speedtest"],
        dependencies=[],
    )

    async def on_load(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Speedtest plugin loaded")
        return True

    async def on_unload(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Speedtest plugin unloaded")
        return True

    async def on_enable(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Speedtest plugin enabled")
        return True

    async def on_disable(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Speedtest plugin disabled")
        return True


@new_task
async def speedtest_command(client: Client, message: Message):
    speed = await send_message(message, "<i>◷ Initiating Speedtest...</i>")
    try:
        speed_results = await sync_to_async(Speedtest)
        await sync_to_async(speed_results.get_best_server)
        await sync_to_async(speed_results.download)
        await sync_to_async(speed_results.upload)
    except ConfigRetrievalError:
        await edit_message(
            speed,
            "<b>⚑ ERROR:</b> <i>Can't connect to Server at the Moment, Try Again Later!</i>",
        )
        return
    speed_results.results.share()
    result = speed_results.results.dict()
    string_speed = f"""<b>❖ SPEEDTEST INFO</b>
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
├ Upload     : <code>⇅ {get_readable_file_size(result['upload'] / 8)}/s</code>
├ Download   : <code>⇅ {get_readable_file_size(result['download'] / 8)}/s</code>
├ Ping       : <code>◷ {result['ping']} ms</code>
├ Time       : <code>{result['timestamp']}</code>
├ Data Sent  : <code>{get_readable_file_size(int(result['bytes_sent']))}</code>
└ Data Recv  : <code>{get_readable_file_size(int(result['bytes_received']))}</code>
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
<b>❖ SERVER</b>
├ Name       : <code>{result['server']['name']}</code>
├ Country    : <code>{result['server']['country']}, {result['server']['cc']}</code>
├ Sponsor    : <code>{result['server']['sponsor']}</code>
├ Latency    : <code>{result['server']['latency']}</code>
├ Latitude   : <code>{result['server']['lat']}</code>
└ Longitude  : <code>{result['server']['lon']}</code>
"""
    try:
        await send_message(message, string_speed, photo=result["share"])
        await delete_message(speed)
    except Exception as e:
        from bot import LOGGER

        LOGGER.error(str(e))
        await edit_message(speed, string_speed)
