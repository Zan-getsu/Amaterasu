import os
import aiohttp

from .. import LOGGER
from ..helper.ext_utils.bot_utils import new_task
from ..helper.telegram_helper.message_utils import send_message, edit_message

@new_task
async def telegraph_upload(_, message):
    reply = message.reply_to_message
    if not reply or not getattr(reply, 'media', None):
        await send_message(message, "Reply to a media (image/video/document) to upload it to Telegraph!")
        return
        
    if reply.document and not reply.document.mime_type.startswith("image/") and not reply.document.mime_type.startswith("video/"):
        await send_message(message, "Only images and videos are supported by Telegraph!")
        return

    if reply.video and reply.video.file_size > 5242880:
        await send_message(message, "Video size should be less than 5MB for Telegraph!")
        return
    elif reply.document and reply.document.file_size > 5242880:
        await send_message(message, "Document size should be less than 5MB for Telegraph!")
        return

    msg = await send_message(message, "<i>Downloading to my local storage...</i>")
    file_path = None
    try:
        file_path = await reply.download()
        if not file_path:
            await edit_message(msg, "Failed to download media.")
            return

        await edit_message(msg, "<i>Uploading to Telegraph...</i>")
        
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'image/jpeg'
        
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename=os.path.basename(file_path), content_type=mime_type)
                
                async with session.post('https://telegra.ph/upload', data=data) as response:
                    res_json = await response.json()
                    
                    if isinstance(res_json, list) and len(res_json) > 0 and 'src' in res_json[0]:
                        url = f"https://telegra.ph{res_json[0]['src']}"
                        await edit_message(msg, f"<b>Telegraph Link:</b>\n<code>{url}</code>")
                    elif isinstance(res_json, dict) and 'error' in res_json:
                        await edit_message(msg, f"<b>Error:</b> {res_json['error']}")
                    else:
                        await edit_message(msg, f"Failed to upload to telegraph! response: {res_json}")
    except Exception as e:
        LOGGER.error(f"Telegraph upload failed: {e}")
        await edit_message(msg, f"<b>Error:</b> {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

