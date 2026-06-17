from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import handleIndex, new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)


@new_task
async def picture_add(_, message):
    resm = message.reply_to_message
    editable = await send_message(message, "<i>Fetching Input ...</i>")
    if len(message.command) > 1 or resm and resm.text:
        msg_text = resm.text if resm else message.command[1]
        if not msg_text.startswith("http"):
            return await edit_message(
                editable, "<b>Not a Valid Link, Must Start with 'http'</b>"
            )
        pic_add = msg_text.strip()
    elif resm and resm.photo:
        if resm.photo.file_size > 5242880 * 2:
            return await edit_message(
                editable, "<i>Media is Not Supported! Only Photos!!</i>"
            )
        pic_add = resm.photo.file_id
    else:
        help_msg = f"""<b>❖ ADD IMAGE USAGE</b>
<code>├─ Reply to Link : /{BotCommands.AddImageCommand} {{link}}
├─ Reply to Photo: /{BotCommands.AddImageCommand}
└─ Supported     : Telegra.ph, DDL links, Telegram photos
</code>"""
        return await edit_message(editable, help_msg)
    Config.IMAGES.append(pic_add)
    Config.USE_IMAGES = True
    if Config.DATABASE_URL:
        await database.update_config({"IMAGES": Config.IMAGES, "USE_IMAGES": True})
    await edit_message(
        editable,
        f"<b>❖ IMAGE ADDED</b>\n<code>├─ Total Images          : {len(Config.IMAGES)}\n└─ Random Message Images : Enabled\n</code>",
    )


@new_task
async def pictures(_, message):
    if not Config.IMAGES:
        await send_message(
            message,
            f"<b>No Photo to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
        )
    else:
        if not Config.USE_IMAGES:
            Config.USE_IMAGES = True
            if Config.DATABASE_URL:
                await database.update_config({"USE_IMAGES": True})
        to_edit = await send_message(message, "<i>Generating Grid of your Images...</i>")
        buttons = ButtonMaker()
        user_id = message.from_user.id
        buttons.data_button("\u00ab", f"images {user_id} turn -1")
        buttons.data_button("\u00bb", f"images {user_id} turn 1")
        buttons.data_button("Remove Image", f"images {user_id} remov 0")
        buttons.data_button("Close", f"images {user_id} close")
        buttons.data_button("Remove All", f"images {user_id} removall", "footer")
        await delete_message(to_edit)
        total = len(Config.IMAGES)
        await send_message(
            message,
            f"<b>❖ IMAGE GALLERY</b>\n<code>└─ \U0001f304 No. : 1 / {total}\n</code>",
            buttons.build_menu(2),
            photo=Config.IMAGES[0],
        )


@new_task
async def pics_callback(_, query):
    message = query.message
    user_id = query.from_user.id
    data = query.data.split()
    if user_id != int(data[1]):
        await query.answer(text="Not Authorized User!", show_alert=True)
        return
    if data[2] == "turn":
        await query.answer()
        if not Config.IMAGES:
            await delete_message(message)
            await send_message(
                message,
                f"<b>No Photo to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
            )
            return
        ind = handleIndex(int(data[3]), Config.IMAGES)
        total = len(Config.IMAGES)
        no = ind + 1
        pic_info = f"<b>❖ IMAGE GALLERY</b>\n<code>└─ \U0001f304 No. : {no} / {total}\n</code>"
        buttons = ButtonMaker()
        buttons.data_button("\u00ab", f"images {data[1]} turn {ind - 1}")
        buttons.data_button("\u00bb", f"images {data[1]} turn {ind + 1}")
        buttons.data_button("Remove Image", f"images {data[1]} remov {ind}")
        buttons.data_button("Close", f"images {data[1]} close")
        buttons.data_button("Remove All", f"images {data[1]} removall", "footer")
        if message.media:
            await edit_message(message, pic_info, buttons.build_menu(2), photo=Config.IMAGES[ind])
        else:
            await delete_message(message)
            await send_message(
                message,
                pic_info,
                buttons.build_menu(2),
                photo=Config.IMAGES[ind],
            )
    elif data[2] == "remov":
        Config.IMAGES.pop(int(data[3]))
        if Config.DATABASE_URL:
            await database.update_config({"IMAGES": Config.IMAGES})
        await query.answer("Image Successfully Deleted", show_alert=True)
        if len(Config.IMAGES) == 0:
            await delete_message(message)
            await send_message(
                message,
                f"<b>No Photo to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
            )
            return
        ind = int(data[3])
        ind = min(ind, len(Config.IMAGES) - 1)
        total = len(Config.IMAGES)
        no = ind + 1
        pic_info = f"<b>❖ IMAGE GALLERY</b>\n<code>└─ \U0001f304 No. : {no} / {total}\n</code>"
        buttons = ButtonMaker()
        buttons.data_button("\u00ab", f"images {data[1]} turn {ind - 1}")
        buttons.data_button("\u00bb", f"images {data[1]} turn {ind + 1}")
        buttons.data_button("Remove Image", f"images {data[1]} remov {ind}")
        buttons.data_button("Close", f"images {data[1]} close")
        buttons.data_button("Remove All", f"images {data[1]} removall", "footer")
        if message.media:
            await edit_message(message, pic_info, buttons.build_menu(2), photo=Config.IMAGES[ind])
        else:
            await delete_message(message)
            await send_message(
                message,
                pic_info,
                buttons.build_menu(2),
                photo=Config.IMAGES[ind],
            )
    elif data[2] == "removall":
        Config.IMAGES.clear()
        if Config.DATABASE_URL:
            await database.update_config({"IMAGES": Config.IMAGES})
        await query.answer("All Images Successfully Deleted", show_alert=True)
        await delete_message(message)
        await send_message(
            message,
            f"<b>No Images to Show !</b> Add by <code>/{BotCommands.AddImageCommand}</code>",
        )
    else:
        await query.answer()
        await delete_message(message)
        if message.reply_to_message:
            await delete_message(message.reply_to_message)

