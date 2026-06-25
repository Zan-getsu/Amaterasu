from pyrogram import Client
from pyrogram.enums import ButtonStyle
from pyrogram.filters import command, regex
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import Message

from .. import LOGGER
from ..core.plugin_manager import get_plugin_manager
from ..helper.ext_utils.bot_utils import new_task
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
    delete_message,
)


async def get_plugins_menu(user_id: int, stype: str = "main"):
    plugin_manager = get_plugin_manager()
    buttons = ButtonMaker()

    if stype == "main":
        loaded_plugins = plugin_manager.list_plugins()
        available_plugins = plugin_manager.discover_plugins()
        loaded_names = {p.name for p in loaded_plugins}
        total_plugins = len(set(available_plugins) | loaded_names)

        buttons.data_button(
            "Loaded Plugins", f"plugins {user_id} loaded", position="header"
        )
        buttons.data_button("Available Plugins", f"plugins {user_id} available")
        buttons.data_button("Plugin Info", f"plugins {user_id} info")
        buttons.data_button("✕ CLOSE", f"plugins {user_id} close", position="footer", style=ButtonStyle.DANGER)

        text = f"""<b>❖ PLUGIN MANAGEMENT</b>
<code>┌─ {'Loaded Plugins':<17}: {len(loaded_plugins)}
├─ {'Available Plugins':<17}: {len(available_plugins)}
└─ {'Total Plugins':<17}: {total_plugins}
</code>"""

        btns = buttons.build_menu(2)

    elif stype == "loaded":
        loaded_plugins = plugin_manager.list_plugins()

        for plugin in loaded_plugins:
            status = "✅" if plugin.enabled else "❌"
            buttons.data_button(
                f"{status} {plugin.name}", f"plugins {user_id} plugin {plugin.name}"
            )

        buttons.data_button("↩ BACK", f"plugins {user_id} main", position="footer")
        buttons.data_button("✕ CLOSE", f"plugins {user_id} close", position="footer", style=ButtonStyle.DANGER)

        text = f"""<b>❖ LOADED PLUGINS</b>
<code>└─ {'Total Loaded':<12}: {len(loaded_plugins)}
</code>"""

        btns = buttons.build_menu(1)

    elif stype == "available":
        available_plugins = plugin_manager.discover_plugins()
        loaded_plugins = [p.name for p in plugin_manager.list_plugins()]

        for plugin in available_plugins:
            if plugin not in loaded_plugins:
                buttons.data_button(f"📦 {plugin}", f"plugins {user_id} load {plugin}")

        buttons.data_button("↩ BACK", f"plugins {user_id} main", position="footer")
        buttons.data_button("✕ CLOSE", f"plugins {user_id} close", position="footer", style=ButtonStyle.DANGER)

        unloaded_count = len([p for p in available_plugins if p not in loaded_plugins])
        text = f"""<b>❖ AVAILABLE PLUGINS</b>
<code>└─ {'Unloaded Plugins':<16}: {unloaded_count}
</code>"""

        btns = buttons.build_menu(1)

    elif stype == "info":
        loaded_plugins = plugin_manager.list_plugins()

        text = "<b>❖ PLUGIN INFORMATION</b>\n<code>"
        for i, plugin in enumerate(loaded_plugins):
            status = "✅ Enabled" if plugin.enabled else "❌ Disabled"
            prefix1 = "┌─"
            prefix2 = "├─"
            prefix3 = "└─"
            text += f"{prefix1} {plugin.name} v{plugin.version}\n"
            text += f"{prefix2} {'Author':<11}: {plugin.author}\n"
            text += f"{prefix2} {'Status':<11}: {status}\n"
            text += f"{prefix2} {'Commands':<11}: {', '.join(plugin.commands) if plugin.commands else 'None'}\n"
            text += f"{prefix3} {'Description':<11}: {plugin.description}\n\n"
        text += "</code>"

        buttons.data_button("↩ BACK", f"plugins {user_id} main", position="footer")
        buttons.data_button("✕ CLOSE", f"plugins {user_id} close", position="footer", style=ButtonStyle.DANGER)
        btns = buttons.build_menu(1)

    elif stype.startswith("plugin_"):
        plugin_name = stype.split("_", 1)[1]
        plugin_info = plugin_manager.get_plugin_info(plugin_name)

        if plugin_info:
            status = "✅ Enabled" if plugin_info.enabled else "❌ Disabled"
            buttons.data_button(
                "Disable" if plugin_info.enabled else "Enable",
                f"plugins {user_id} toggle {plugin_name}",
            )
            buttons.data_button("Unload", f"plugins {user_id} unload {plugin_name}")
            buttons.data_button("Reload", f"plugins {user_id} reload {plugin_name}")

            buttons.data_button("↩ BACK", f"plugins {user_id} loaded", position="footer")
            buttons.data_button("✕ CLOSE", f"plugins {user_id} close", position="footer", style=ButtonStyle.DANGER)

            text = f"""<b>❖ PLUGIN: {plugin_name}</b>
<code>┌─ {'Version':<11}: {plugin_info.version}
├─ {'Author':<11}: {plugin_info.author}
├─ {'Status':<11}: {status}
├─ {'Commands':<11}: {', '.join(plugin_info.commands) if plugin_info.commands else 'None'}
└─ {'Description':<11}: {plugin_info.description}
</code>"""

            btns = buttons.build_menu(2)
        else:
            text = f"❌ Plugin {plugin_name} not found"
            buttons.data_button("↩ BACK", f"plugins {user_id} loaded", position="footer")
            btns = buttons.build_menu(1)

    else:
        text = f"❌ Unknown menu type: {stype}"
        buttons.data_button("↩ BACK", f"plugins {user_id} main", position="footer")
        btns = buttons.build_menu(1)

    return text, btns


@new_task
async def plugins_command(client: Client, message: Message):
    try:
        plugin_manager = get_plugin_manager()
        plugin_manager.bot = client

        text, buttons = await get_plugins_menu(message.from_user.id)
        await send_message(message, text, buttons)

    except Exception as e:
        LOGGER.error(f"Error in plugins_command: {e}", exc_info=True)
        await message.reply_text("Error loading plugin menu")


@new_task
async def edit_plugins_menu(client: Client, query):
    try:
        user_id = query.from_user.id
        data = query.data.split()

        if len(data) < 3:
            return await query.answer("Invalid data!", show_alert=True)

        if (
            data[2] in {"plugin", "load", "unload", "reload", "toggle"}
            and len(data) < 4
        ):
            return await query.answer("Invalid data!", show_alert=True)

        if user_id != int(data[1]):
            return await query.answer("Not yours!", show_alert=True)

        if data[2] == "main":
            await query.answer()
            text, buttons = await get_plugins_menu(user_id, "main")
            await edit_message(query.message, text, buttons)

        elif data[2] == "loaded":
            await query.answer()
            text, buttons = await get_plugins_menu(user_id, "loaded")
            await edit_message(query.message, text, buttons)

        elif data[2] == "available":
            await query.answer()
            text, buttons = await get_plugins_menu(user_id, "available")
            await edit_message(query.message, text, buttons)

        elif data[2] == "info":
            await query.answer()
            text, buttons = await get_plugins_menu(user_id, "info")
            await edit_message(query.message, text, buttons)

        elif data[2] == "plugin":
            await query.answer()
            plugin_name = data[3]
            text, buttons = await get_plugins_menu(user_id, f"plugin_{plugin_name}")
            await edit_message(query.message, text, buttons)

        elif data[2] == "load":
            await query.answer("Loading plugin...", show_alert=True)
            plugin_name = data[3]
            plugin_manager = get_plugin_manager()
            plugin_manager.bot = client

            success = await plugin_manager.load_plugin(plugin_name)
            if success:
                await query.answer(
                    f"Plugin {plugin_name} loaded successfully!", show_alert=True
                )
            else:
                await query.answer(
                    f"Failed to load plugin {plugin_name}", show_alert=True
                )

            text, buttons = await get_plugins_menu(user_id, "available")
            await edit_message(query.message, text, buttons)

        elif data[2] == "unload":
            await query.answer("Unloading plugin...", show_alert=True)
            plugin_name = data[3]
            plugin_manager = get_plugin_manager()
            plugin_manager.bot = client

            success = await plugin_manager.unload_plugin(plugin_name)
            if success:
                await query.answer(
                    f"Plugin {plugin_name} unloaded successfully!", show_alert=True
                )
            else:
                await query.answer(
                    f"Failed to unload plugin {plugin_name}", show_alert=True
                )

            text, buttons = await get_plugins_menu(user_id, "loaded")
            await edit_message(query.message, text, buttons)

        elif data[2] == "reload":
            await query.answer("Reloading plugin...", show_alert=True)
            plugin_name = data[3]
            plugin_manager = get_plugin_manager()
            plugin_manager.bot = client

            success = await plugin_manager.reload_plugin(plugin_name)
            if success:
                await query.answer(
                    f"Plugin {plugin_name} reloaded successfully!", show_alert=True
                )
            else:
                await query.answer(
                    f"Failed to reload plugin {plugin_name}", show_alert=True
                )

            text, buttons = await get_plugins_menu(user_id, f"plugin_{plugin_name}")
            await edit_message(query.message, text, buttons)

        elif data[2] == "toggle":
            await query.answer("Toggling plugin...", show_alert=True)
            plugin_name = data[3]
            plugin_manager = get_plugin_manager()
            plugin_manager.bot = client

            plugin_info = plugin_manager.get_plugin_info(plugin_name)
            if plugin_info:
                if plugin_info.enabled:
                    success = await plugin_manager.disable_plugin(plugin_name)
                    action = "disabled"
                else:
                    success = await plugin_manager.enable_plugin(plugin_name)
                    action = "enabled"

                if success:
                    await query.answer(
                        f"Plugin {plugin_name} {action} successfully!", show_alert=True
                    )
                else:
                    await query.answer(
                        f"Failed to {action} plugin {plugin_name}", show_alert=True
                    )

            text, buttons = await get_plugins_menu(user_id, f"plugin_{plugin_name}")
            await edit_message(query.message, text, buttons)

        elif data[2] == "close":
            await delete_message(query.message)

    except Exception as e:
        LOGGER.error(f"Error in edit_plugins_menu: {e}", exc_info=True)
        await query.answer("Error occurred", show_alert=True)


def register_plugin_commands():
    from ..core.handlers import TgClient
    from ..helper.telegram_helper.bot_commands import BotCommands

    TgClient.bot.add_handler(
        MessageHandler(
            plugins_command,
            filters=command(BotCommands.PluginsCommand, case_sensitive=True)
            & CustomFilters.sudo,
        )
    )
    TgClient.bot.add_handler(
        CallbackQueryHandler(edit_plugins_menu, filters=regex("^plugins"))
    )
