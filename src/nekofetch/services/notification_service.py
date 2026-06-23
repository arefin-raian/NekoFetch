from __future__ import annotations

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger

log = get_logger(__name__)


class NotificationService:
    def __init__(self, container: Container) -> None:
        self._c = container

    @property
    def _client(self):
        return getattr(self._c, "admin_client", None)

    async def _send(self, user_id: int, text: str) -> None:
        if not self._client:
            return
        try:
            from pyrogram.enums import ParseMode
            await self._client.send_message(user_id, text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.debug("notification.send.failed", user_id=user_id, error=str(exc))

    async def download_complete(self, user_id: int, anime_title: str, request_code: str) -> None:
        await self._send(
            user_id,
            f"<blockquote><b>✅ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"ᴅᴏᴡɴʟᴏᴀᴅ ꜰɪɴɪsʜᴇᴅ! ɪᴛ's ɴᴏᴡ ʙᴇɪɴɢ ᴘʀᴏᴄᴇssᴇᴅ."
            f"</blockquote>"
        )

    async def processing_complete(self, user_id: int, anime_title: str, request_code: str, needs_approval: bool = False) -> None:
        body = (
            f"ᴘʀᴏᴄᴇssɪɴɢ ᴄᴏᴍᴘʟᴇᴛᴇ! "
            f"{'ɪᴛs ᴀᴡᴀɪᴛɪɴɢ sᴛᴀꜰꜰ ᴀᴘᴘʀᴏᴠᴀʟ.' if needs_approval else 'ᴄʜᴇᴄᴋ ᴛʜᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ ʙᴏᴛ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ꜰɪʟᴇs.'}"
        )
        await self._send(
            user_id,
            f"<blockquote><b>📦 ᴄᴏɴᴛᴇɴᴛ ʀᴇᴀᴅʏ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"{body}"
            f"</blockquote>"
        )

    async def processing_failed(self, user_id: int, anime_title: str, request_code: str, error: str) -> None:
        display_error = error[:200] + "…" if len(error) > 200 else error
        await self._send(
            user_id,
            f"<blockquote><b>⚙️ ᴘʀᴏᴄᴇssɪɴɢ ꜰᴀɪʟᴇᴅ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅ ꜰɪɴɪsʜᴇᴅ ʙᴜᴛ ᴘʀᴏᴄᴇssɪɴɢ ᴇɴᴄᴏᴜɴᴛᴇʀᴇᴅ ᴀɴ ᴇʀʀᴏʀ. ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ sᴛᴀꜰꜰ.\n\n"
            f"<code>{display_error}</code>"
            f"</blockquote>"
        )

    async def download_failed(self, user_id: int, anime_title: str, request_code: str, error: str) -> None:
        display_error = error[:200] + "…" if len(error) > 200 else error
        await self._send(
            user_id,
            f"<blockquote><b>❌ ᴅᴏᴡɴʟᴏᴀᴅ ꜰᴀɪʟᴇᴅ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ ᴅᴜʀɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ. ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ sᴛᴀꜰꜰ.\n\n"
            f"<code>{display_error}</code>"
            f"</blockquote>"
        )

    async def request_published(self, user_id: int, anime_title: str, request_code: str) -> None:
        await self._send(
            user_id,
            f"<blockquote><b>🎉 ᴄᴏɴᴛᴇɴᴛ ᴘᴜʙʟɪsʜᴇᴅ!</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ ɪs ɴᴏᴡ ʟɪᴠᴇ! ᴏᴘᴇɴ ᴛʜᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ ʙᴏᴛ ᴀɴᴅ sᴇᴀʀᴄʜ ꜰᴏʀ ɪᴛ."
            f"</blockquote>"
        )

    async def processing_stage_warning(self, user_id: int, anime_title: str, stage: str, note: str) -> None:
        await self._send(
            user_id,
            f"<blockquote><b>⚠️ ᴘʀᴏᴄᴇssɪɴɢ ᴡᴀʀɴɪɴɢ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>sᴛᴀɢᴇ:</b> <code>{stage}</code>\n"
            f"<b>ɴᴏᴛᴇ:</b> <code>{note}</code>\n\n"
            f"ᴛʜɪs ɪs ᴀ ɴᴏɴ-ꜰᴀᴛᴀʟ ᴡᴀʀɴɪɴɢ. ᴘʀᴏᴄᴇssɪɴɢ ᴡɪʟʟ ᴄᴏɴᴛɪɴᴜᴇ."
            f"</blockquote>"
        )
