from __future__ import annotations

_SMALL_CAPS = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
)

_BOLD_UPPER = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
_BOLD_LOWER = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
_PLAIN_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PLAIN_LOWER = "abcdefghijklmnopqrstuvwxyz"
_BOLD_SERIF = str.maketrans(_PLAIN_UPPER + _PLAIN_LOWER, _BOLD_UPPER + _BOLD_LOWER)


def small_caps(text: str) -> str:
    return text.translate(_SMALL_CAPS)


def bold_serif(text: str) -> str:
    return text.translate(_BOLD_SERIF)


def bq(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


def bqx(text: str) -> str:
    return f"<blockquote expandable>{text}</blockquote>"


def heading(text: str) -> str:
    return bq(f"<b>{bold_serif(text)}</b>")


def field(label: str, value: str) -> str:
    return f"<b>{small_caps(label)}:</b> <code>{value}</code>"
