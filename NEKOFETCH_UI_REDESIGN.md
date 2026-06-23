# NekoFetch UI Redesign — Full Specification

> **Instruction to the AI developer:** This document is a direct order from me (the project owner) to fully redesign the Telegram UI of **NekoFetch**. Read every section carefully. Every rule here is mandatory. Do not skip any section. If a file or function is mentioned, you must edit it. If a new helper is specified, you must create it.

---

## 0. Context & Source of Inspiration

I have two bots:

| Repo | Role |
|------|------|
| `arefin-raian/NekoFetch` | **My main bot — the one being redesigned** |
| `arefin-raian/nonayarbusiness` (branch: `Makise-Weebs`) | **Reference bot — the style I want to copy** |

The reference bot (`nonayarbusiness / Makise-Weebs`) does several things my bot does not:

1. **Small-caps Unicode font** for all display text (ʙᴜᴛᴛᴏɴs, ᴄᴀᴘᴛɪᴏɴs, ᴍᴇssᴀɢᴇs)
2. **`<blockquote>` and `<blockquote expandable>` HTML tags** wrapping every important message block
3. **Sticker → delay → delete** pattern on `/start`
4. **Spoiler photo + caption** for the welcome screen (not plain text)
5. **Dot-escalation loading animation** — editing a message through `Loading!` → `Loading!!` → `Loading!!!` before showing the real content
6. **Bold Unicode serif** for headings (`𝗛𝗲𝗹𝗹𝗼, 𝗔𝗱𝗺𝗶𝗻!`)

I want **all of the above** adopted into NekoFetch on **every step**, not just `/start`. The bot is slow, so users need to see something happening at every stage. This document tells you exactly what to build.

---

## 1. Typography Rules (Apply Everywhere)

### 1.1 Small-Caps Unicode Font

All visible text in button labels, captions, status messages, and body text must use the **Unicode small-caps alphabet**. This is what makes the reference bot look premium.

**Conversion table:**

```
A → ᴀ  B → ʙ  C → ᴄ  D → ᴅ  E → ᴇ  F → ғ  G → ɢ  H → ʜ  I → ɪ
J → ᴊ  K → ᴋ  L → ʟ  M → ᴍ  N → ɴ  O → ᴏ  P → ᴘ  Q → ǫ  R → ʀ
S → s  T → ᴛ  U → ᴜ  V → ᴠ  W → ᴡ  X → x  Y → ʏ  Z → ᴢ
```

Use these in:
- All `InlineKeyboardButton` labels
- All status/loading messages
- All caption body text
- All section headers in messages

### 1.2 Bold Unicode Serif for Headings

For top-level headings inside messages, use the **mathematical bold serif** alphabet (the same style the reference bot uses in `HELP_MSG`):

```
𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭
𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇
```

Example: `𝗡𝗲𝗸𝗼𝗙𝗲𝘁𝗰𝗵` for the welcome title, `𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹` for the admin home.

### 1.3 `<blockquote>` Wrapping

Every message body must be wrapped in `<blockquote>` or `<blockquote expandable>` HTML tags. Use `expandable` for any message longer than ~3 lines. This renders as the collapsed expandable block in Telegram, which is the key visual feature of the reference bot.

**Pattern:**
```python
# Short messages
"<blockquote><b>ʜᴇʏ, {mention}! ᴡᴇʟᴄᴏᴍᴇ ʙᴀᴄᴋ.</b></blockquote>"

# Long messages (expandable)
"<blockquote expandable><b>ʟᴏɴɢ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ʜᴇʀᴇ...</b></blockquote>"
```

All `edit_text` and `reply` calls must use `parse_mode=ParseMode.HTML`.

---

## 2. The Loading Animation (Most Important — Apply Everywhere)

### 2.1 How It Works in the Reference Bot

In `nonayarbusiness/plugins/start.py`, the `force_sub` decorator does this:

```python
msg = await message.reply_photo(caption="<code>Connecting!</code>", photo=..., has_spoiler=SPOILER)
await msg.edit_text("<code>Connecting!!</code>")
await msg.edit_text("<code>Connecting!!!</code>")
await msg.edit_text("<code>Loading!</code>")
# ... do real work ...
await msg.edit_text("<code>Loading!!</code>")
await msg.edit_text("<code>Loading!!!</code>")
await msg.edit_text("<code>Subscription Status: Passed</code>")
```

This creates an animation by rapidly editing the same message — dots escalate (`!` → `!!` → `!!!`), giving the user a sense that something is happening.

### 2.2 What I Want in NekoFetch

Create a new utility function in `src/nekofetch/ui/progress.py` called `loading_animation`. Here is the exact implementation to add:

```python
import asyncio
from pyrogram.types import Message

async def loading_animation(msg: Message, label: str, steps: int = 3, delay: float = 0.35) -> None:
    """
    Animate a loading label by escalating dots via message edits.

    Example output sequence:
        <code>sᴇᴀʀᴄʜɪɴɢ!</code>
        <code>sᴇᴀʀᴄʜɪɴɢ!!</code>
        <code>sᴇᴀʀᴄʜɪɴɢ!!!</code>
    """
    for i in range(1, steps + 1):
        await msg.edit_text(f"<code>{label}{'!' * i}</code>", parse_mode="html")
        await asyncio.sleep(delay)
```

And a multi-stage version for showing multiple phases:

```python
async def staged_loading(msg: Message, stages: list[str], delay_per_stage: float = 0.4) -> None:
    """
    Cycle through multiple loading stage labels with dot escalation.

    stages = ["ᴄᴏɴɴᴇᴄᴛɪɴɢ", "ʟᴏᴀᴅɪɴɢ", "ᴠᴇʀɪғʏɪɴɢ"]
    """
    for stage in stages:
        for dots in range(1, 4):
            await msg.edit_text(f"<code>{stage}{'!' * dots}</code>", parse_mode="html")
            await asyncio.sleep(delay_per_stage / 3)
```

### 2.3 Where to Apply the Loading Animation

Apply `loading_animation` or `staged_loading` **at every step where the bot is doing any async work**. This includes (but is not limited to):

| File | Handler / Function | Stages to Show |
|------|--------------------|----------------|
| `bots/admin/handlers/start.py` | `_start` | `ᴄᴏɴɴᴇᴄᴛɪɴɢ` → `ʟᴏᴀᴅɪɴɢ` → `ᴠᴇʀɪғʏɪɴɢ ᴀᴄᴄᴇss` |
| `bots/admin/handlers/requests.py` | `_do_search` | `sᴇᴀʀᴄʜɪɴɢ` → `ʀᴇᴛʀɪᴇᴠɪɴɢ ʀᴇsᴜʟᴛs` |
| `bots/admin/handlers/requests.py` | `_pick` (title selected) | `ʟᴏᴀᴅɪɴɢ ᴄᴏɴᴛᴇɴᴛ` |
| `bots/admin/handlers/requests.py` | season/resolution/language steps | `ʀᴇᴛʀɪᴇᴠɪɴɢ sᴇᴀsᴏɴs` |
| `bots/admin/handlers/requests.py` | `_submit_selected` | `sᴜʙᴍɪᴛᴛɪɴɢ ʀᴇǫᴜᴇsᴛ` |
| `bots/admin/handlers/approvals.py` | `_panel` | `ʟᴏᴀᴅɪɴɢ ᴀᴘᴘʀᴏᴠᴀʟs` |
| `bots/admin/handlers/approvals.py` | `_action` (publish/reprocess) | `ᴘʀᴏᴄᴇssɪɴɢ` |
| `bots/admin/handlers/commands.py` | any analytics or stats fetch | `ғᴇᴛᴄʜɪɴɢ sᴛᴀᴛs` |
| `bots/distribution/app.py` | `_start` | `ᴄᴏɴɴᴇᴄᴛɪɴɢ` → `ᴄʜᴇᴄᴋɪɴɢ ᴀᴄᴄᴇss` |
| `bots/distribution/app.py` | `_show_title` | `ʟᴏᴀᴅɪɴɢ ᴀɴɪᴍᴇ` |
| `bots/distribution/app.py` | `_show_catalog` | `ʟᴏᴀᴅɪɴɢ ᴄᴀᴛᴀʟᴏɢ` |
| `bots/distribution/app.py` | delivery / copy files | `ᴘʀᴇᴘᴀʀɪɴɢ ᴘᴀᴄᴋᴀɢᴇ` → `sᴇɴᴅɪɴɢ` |
| `bots/force_sub.py` | subscription check | `ᴄʜᴇᴄᴋɪɴɢ sᴜʙsᴄʀɪᴘᴛɪᴏɴ` |

**Rule:** Anywhere you `await` something that can take more than 0.2 seconds — add a loading animation first. Reply with a loading message, run the animation, then do the real work, then edit the message to the final result.

---

## 3. `/start` Screen — Full Redesign

### 3.1 Admin Bot Start (`bots/admin/handlers/start.py`)

Replace the entire current implementation. The new flow must be:

**Step 1 — Send sticker**
```python
sticker_id = "CAACAgUAAyEFAASAgUwqAAJh_mckw2STkeY1WMOHJGY4Hs9_1-2fAAIPFAACYLShVon-N6AFLnIiHgQ"
start_sticker = await client.send_sticker(chat_id=message.chat.id, sticker=sticker_id)
```
(This is the same sticker the reference bot uses. If the owner wants to change it, they set `STICKER_ID` in config. Make it configurable via `config.yaml` under a new `ui.start_sticker_id` key.)

**Step 2 — Send loading message and animate**
```python
msg = await message.reply("<code>ᴄᴏɴɴᴇᴄᴛɪɴɢ!</code>", parse_mode=ParseMode.HTML)
await staged_loading(msg, ["ᴄᴏɴɴᴇᴄᴛɪɴɢ", "ʟᴏᴀᴅɪɴɢ", "ᴠᴇʀɪғʏɪɴɢ ᴀᴄᴄᴇss"])
```

**Step 3 — Do real work (load user/role)**

**Step 4 — Delete sticker (after ~1 second)**
```python
await asyncio.sleep(1)
await start_sticker.delete()
```

**Step 5 — Edit message to welcome photo + caption**

Use `msg.delete()` then send a fresh photo message with `has_spoiler=True` and the welcome caption:

```python
await msg.delete()
await client.send_photo(
    chat_id=message.chat.id,
    photo="https://envs.sh/odE.png",   # make this configurable: ui.start_image_url
    caption=_welcome_caption(localizer, role, lang),
    has_spoiler=True,
    parse_mode=ParseMode.HTML,
    reply_markup=welcome_keyboard(localizer, role, lang),
)
```

**Step 6 — The welcome caption format:**
```python
def _welcome_caption(localizer, role, lang):
    mention = ...  # message.from_user.mention (HTML)
    return (
        f"<blockquote><b>𝗡𝗲𝗸𝗼𝗙𝗲𝘁𝗰𝗵 ✌</b></blockquote>\n\n"
        f"<blockquote expandable>"
        f"<b>ʜᴇʏ, {mention}! ɪ'ᴍ ɴᴇᴋᴏꜰᴇᴛᴄʜ — ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴀɴɪᴍᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ sʏsᴛᴇᴍ. "
        f"ᴘɪᴄᴋ ᴀ sᴇᴀsᴏɴ, ᴄʜᴏᴏsᴇ ʏᴏᴜʀ ǫᴜᴀʟɪᴛʏ, ᴀɴᴅ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇs. sɪᴍᴘʟᴇ.</b>"
        f"</blockquote>\n\n"
        f"<blockquote><b>ᴀᴄᴄᴇss ʟᴇᴠᴇʟ:</b> <code>{role_label}</code></blockquote>"
    )
```

### 3.2 Distribution Bot Start (`bots/distribution/app.py` → `_start`)

Same pattern:

1. Send sticker → animate loading → delete sticker → check access → show title/catalog

For the loading stages use: `["ᴄᴏɴɴᴇᴄᴛɪɴɢ", "ᴄʜᴇᴄᴋɪɴɢ ᴀᴄᴄᴇss", "ᴘʀᴇᴘᴀʀɪɴɢ"]`

---

## 4. Button Labels — Full Conversion

All `InlineKeyboardButton` labels must be rewritten in small-caps. Below is the complete mapping for every button that currently exists in `bots/admin/keyboards.py` and throughout the codebase:

| Current Label | New Label |
|---------------|-----------|
| `Request Anime` | `ʀᴇǫᴜᴇsᴛ ᴀɴɪᴍᴇ` |
| `My Requests` | `ᴍʏ ʀᴇǫᴜᴇsᴛs` |
| `▸ Review Requests` | `▸ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs` |
| `▸ Downloads Queue` | `▸ ᴅᴏᴡɴʟᴏᴀᴅs ǫᴜᴇᴜᴇ` |
| `◈ Admin Panel` | `◈ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ` |
| `▸ Queue` | `▸ ǫᴜᴇᴜᴇ` |
| `▸ Analytics` | `▸ ᴀɴᴀʟʏᴛɪᴄs` |
| `▸ Staff` | `▸ sᴛᴀꜰꜰ` |
| `▸ Bots` | `▸ ʙᴏᴛs` |
| `▸ Settings` | `▸ sᴇᴛᴛɪɴɢs` |
| `▸ Storage` | `▸ sᴛᴏʀᴀɢᴇ` |
| `▸ Approvals` | `▸ ᴀᴘᴘʀᴏᴠᴀʟs` |
| `▸ Broadcast` | `▸ ʙʀᴏᴀᴅᴄᴀsᴛ` |
| `Publish` | `ᴘᴜʙʟɪsʜ ✓` |
| `Reprocess` | `ʀᴇᴘʀᴏᴄᴇss` |
| `Cancel` | `ᴄᴀɴᴄᴇʟ ✗` |
| `Back` | `← ʙᴀᴄᴋ` |
| `Next` | `ɴᴇxᴛ →` |
| `Previous` | `← ᴘʀᴇᴠ` |
| `Entire Series` | `ᴇɴᴛɪʀᴇ sᴇʀɪᴇs` |
| `Selected Episodes` | `sᴇʟᴇᴄᴛᴇᴅ ᴇᴘɪsᴏᴅᴇs` |
| `Get Season Package` | `📦 ɢᴇᴛ sᴇᴀsᴏɴ ᴘᴀᴄᴋᴀɢᴇ` |
| `➜ Get Access` | `➜ ɢᴇᴛ ᴀᴄᴄᴇss` |
| `Get Your File Again!` | `📬 ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ ᴀɢᴀɪɴ` |
| `➜ Prev` | `← ᴘʀᴇᴠ` |
| `Next ➜` | `ɴᴇxᴛ →` |

Apply this conversion to **every** `InlineKeyboardButton` in:
- `bots/admin/keyboards.py`
- `bots/admin/handlers/requests.py`
- `bots/admin/handlers/approvals.py`
- `bots/admin/handlers/settings.py`
- `bots/admin/handlers/bots_admin.py`
- `bots/admin/handlers/staff_admin.py`
- `bots/admin/handlers/admin_tools.py`
- `bots/admin/handlers/storage_admin.py`
- `bots/distribution/app.py`

Also update `resources/language/en.json` for all `btn_*` keys to their small-caps equivalents so they flow through the localizer.

---

## 5. Message Bodies — Format and Wrapping

### 5.1 Global Rule

Every message sent or edited by the bot must:
1. Use `parse_mode=ParseMode.HTML`
2. Have its body wrapped in `<blockquote>` or `<blockquote expandable>`
3. Use `<b>` for field labels and important text
4. Use `<code>` for IDs, status values, and numeric data

### 5.2 Welcome Message

Already covered in Section 3. Add a `𝗡𝗲𝗸𝗼𝗙𝗲𝘁𝗰𝗵` header (bold serif Unicode), then an expandable blockquote for the body.

### 5.3 Search Results (`_results_text` in `requests.py`)

Current:
```python
f"**{L('search_results_header')}**\n\n" + "\n".join(lines)
```

New:
```python
f"<blockquote><b>🔍 sᴇᴀʀᴄʜ ʀᴇsᴜʟᴛs</b></blockquote>\n\n" +
"<blockquote expandable>" + "\n".join(f"◆ {l}" for l in lines) + "</blockquote>"
```

### 5.4 Request Accepted Message

Current format uses plain markdown. New format:

```python
(
    f"<blockquote><b>✅ ʀᴇǫᴜᴇsᴛ ᴀᴄᴄᴇᴘᴛᴇᴅ</b></blockquote>\n\n"
    f"<blockquote expandable>"
    f"<b>ʀᴇǫᴜᴇsᴛ ɪᴅ:</b> <code>{req_id}</code>\n"
    f"<b>ᴘᴏsɪᴛɪᴏɴ:</b> <code>#{position}</code>\n"
    f"<b>ᴇᴛᴀ:</b> <code>{eta}</code>"
    f"</blockquote>"
)
```

### 5.5 Approval Panel (`approvals.py`)

Current:
```python
f"**{L('publish_panel_title')}**\n\n"
f"{L('label_anime')}: {item.title}\n"
...
```

New:
```python
(
    f"<blockquote><b>𝗖𝗼𝗻𝘁𝗲𝗻𝘁 𝗔𝗽𝗽𝗿𝗼𝘃𝗮𝗹</b></blockquote>\n\n"
    f"<blockquote expandable>"
    f"<b>ᴀɴɪᴍᴇ:</b> <code>{item.title}</code>\n"
    f"<b>ꜰɪʟᴇs:</b> <code>{item.files}</code>\n"
    f"<b>ʀᴇsᴏʟᴜᴛɪᴏɴ:</b> <code>{item.resolution or '—'}</code>\n"
    f"<b>ʟᴀɴɢᴜᴀɢᴇ:</b> <code>{item.audio or '—'}</code>\n"
    f"<b>ᴛʜᴜᴍʙɴᴀɪʟ:</b> <code>{'✓ ᴀᴠᴀɪʟᴀʙʟᴇ' if item.has_thumbnail else '✗ ɴᴏɴᴇ'}</code>\n"
    f"<b>ᴍᴇᴛᴀᴅᴀᴛᴀ:</b> <code>✓ ᴜᴘᴅᴀᴛᴇᴅ</code>"
    f"</blockquote>"
)
```

### 5.6 Queue / Download Dashboard

Any message showing download progress must use this format:

```python
(
    f"<blockquote><b>📥 ᴅᴏᴡɴʟᴏᴀᴅ ǫᴜᴇᴜᴇ</b></blockquote>\n\n"
    f"<blockquote expandable>"
    f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime}</code>\n"
    f"<b>ᴇᴘɪsᴏᴅᴇ:</b> <code>{episode}</code>\n"
    f"<b>sᴛᴀᴛᴜs:</b> <code>{status}</code>\n"
    f"<b>ᴘʀᴏɢʀᴇss:</b> {bar_str}\n"
    f"<b>sᴘᴇᴇᴅ:</b> <code>{speed}</code>\n"
    f"<b>ᴇᴛᴀ:</b> <code>{eta}</code>"
    f"</blockquote>"
)
```

### 5.7 Access Denied / Error Messages

```python
# Access denied
"<blockquote><b>🚫 ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>\n\nʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴘᴇʀᴍɪssɪᴏɴ ᴛᴏ ᴜsᴇ ᴛʜɪs ꜰᴇᴀᴛᴜʀᴇ.</blockquote>"

# Generic error
"<blockquote><b>⚠️ sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ.</b>\n\nᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote>"

# Rate limited
"<blockquote><b>⏳ sʟᴏᴡ ᴅᴏᴡɴ!</b>\n\nʏᴏᴜ'ʀᴇ ɢᴏɪɴɢ ᴛᴏᴏ ꜰᴀsᴛ.</blockquote>"
```

### 5.8 Auto-Delete Warning (distribution bot)

```python
(
    f"<blockquote><b>⏳ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ</b>\n\n"
    f"ᴛʜᴇsᴇ ꜰɪʟᴇs ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ <code>{humanize.naturaldelta(del_timer)}</code>.\n"
    f"ꜰᴏʀᴡᴀʀᴅ ᴛʜᴇᴍ ᴛᴏ ʏᴏᴜʀ sᴀᴠᴇᴅ ᴍᴇssᴀɢᴇs ɴᴏᴡ!</blockquote>"
)
```

### 5.9 Files Deleted Message (after auto-delete timer)

```python
"<blockquote><b>📂 ᴀʟʟ ꜰɪʟᴇs ʜᴀᴠᴇ ʙᴇᴇɴ ᴅᴇʟᴇᴛᴇᴅ ᴛᴏ ᴀᴠᴏɪᴅ ᴄᴏᴘʏʀɪɢʜᴛ ɪssᴜᴇs.</b></blockquote>"
```

### 5.10 Force-Subscribe Wall

```python
(
    f"<blockquote><b>🔒 ᴊᴏɪɴ ᴛᴏ ᴀᴄᴄᴇss ᴛʜɪs ʙᴏᴛ!</b></blockquote>\n\n" +
    "\n".join(
        f"<b>{i+1}. {name}</b>\n<b>sᴛᴀᴛᴜs:</b> <code>{userstatus}</code>\n"
        for i, (name, userstatus) in enumerate(channels_list)
    ) +
    f"\n<blockquote><b>ᴀꜰᴛᴇʀ ᴊᴏɪɴɪɴɢ ᴀʟʟ ᴄʜᴀɴɴᴇʟs, ᴄʟɪᴄᴋ ᴛʀʏ ᴀɢᴀɪɴ.</b></blockquote>"
)
```

### 5.11 Help Message (distribution bot)

```python
(
    "<blockquote><b>𝗛𝗼𝘄 𝗶𝘁 𝗪𝗼𝗿𝗸𝘀</b></blockquote>\n\n"
    "<blockquote expandable>"
    "<b>◆ /start</b> — ʙʀᴏᴡsᴇ ᴛʜᴇ ʟɪʙʀᴀʀʏ ᴏʀ ᴏᴘᴇɴ ᴀ ᴛɪᴛʟᴇ\n"
    "<b>◆</b> ᴘɪᴄᴋ ᴀ sᴇᴀsᴏɴ → ʀᴇsᴏʟᴜᴛɪᴏɴ → ʟᴀɴɢᴜᴀɢᴇ\n"
    "<b>◆</b> ᴛᴀᴘ <b>ɢᴇᴛ sᴇᴀsᴏɴ ᴘᴀᴄᴋᴀɢᴇ</b> ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ʏᴏᴜʀ ꜰɪʟᴇs"
    "</blockquote>"
)
```

---

## 6. Progress Bar Styling Update

The existing `▰▱` progress bar in `ui/progress.py` is good. Keep it. But wrap it in blockquote when shown as a status message:

```python
def labeled_html(label: str, percent: float, *, width: int = 10) -> str:
    """HTML blockquote version of the labeled progress bar."""
    return (
        f"<blockquote><b>{label}</b>\n\n"
        f"<code>{bar(percent, width=width)}</code></blockquote>"
    )
```

Use `labeled_html` instead of `labeled` everywhere the bot sends a progress update as a standalone message (queue dashboard, download progress edits).

---

## 7. Admin Panel Home Page Redesign

File: `bots/admin/keyboards.py` → `admin_home_keyboard()`
File: `bots/admin/handlers/commands.py` (wherever the admin home text is built)

The admin home message must look like:

```
𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹

<blockquote expandable>ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ᴅᴏᴡɴʟᴏᴀᴅs, ᴀᴘᴘʀᴏᴠᴀʟs, sᴛᴀꜰꜰ, ᴀɴᴅ sᴇᴛᴛɪɴɢs.</blockquote>
```

Keyboard layout stays the same as current `admin_home_keyboard()`, but labels are rewritten per Section 4.

---

## 8. `en.json` — Language File Updates

Update `resources/language/en.json` as follows. All `btn_*` values and status strings must be converted to small-caps. Here are the key ones to update (apply the same logic to every remaining key):

```json
{
  "welcome_title": "𝗡𝗲𝗸𝗼𝗙𝗲𝘁𝗰𝗵",
  "welcome_subtitle": "ᴘʀᴇᴍɪᴜᴍ ᴀɴɪᴍᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ",

  "btn_request_anime": "ʀᴇǫᴜᴇsᴛ ᴀɴɪᴍᴇ",
  "btn_my_requests": "ᴍʏ ʀᴇǫᴜᴇsᴛs",
  "btn_entire_series": "ᴇɴᴛɪʀᴇ sᴇʀɪᴇs",
  "btn_selected_episodes": "sᴇʟᴇᴄᴛᴇᴅ ᴇᴘɪsᴏᴅᴇs",
  "btn_back": "← ʙᴀᴄᴋ",
  "btn_next": "ɴᴇxᴛ →",
  "btn_prev": "← ᴘʀᴇᴠ",
  "btn_cancel": "ᴄᴀɴᴄᴇʟ ✗",
  "btn_publish": "ᴘᴜʙʟɪsʜ ✓",
  "btn_reprocess": "ʀᴇᴘʀᴏᴄᴇss",

  "status_searching": "sᴇᴀʀᴄʜɪɴɢ",
  "status_searching_db": "sᴇᴀʀᴄʜɪɴɢ ᴅᴀᴛᴀʙᴀsᴇ",
  "status_retrieving_seasons": "ʀᴇᴛʀɪᴇᴠɪɴɢ sᴇᴀsᴏɴs",
  "status_complete": "ᴄᴏᴍᴘʟᴇᴛᴇ",
  "status_downloading": "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ",
  "status_processing": "ᴘʀᴏᴄᴇssɪɴɢ",
  "status_queued": "ǫᴜᴇᴜᴇᴅ",
  "status_published": "ᴘᴜʙʟɪsʜᴇᴅ",

  "access_denied": "🚫 ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ.",
  "error_generic": "⚠️ sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ.",
  "rate_limited": "⏳ ʏᴏᴜ'ʀᴇ ɢᴏɪɴɢ ᴛᴏᴏ ꜰᴀsᴛ.",
  "link_expired": "🔗 ᴛʜɪs ʟɪɴᴋ ʜᴀs ᴇxᴘɪʀᴇᴅ."
}
```

---

## 9. `config.yaml` — New UI Section

Add a new `ui` section to `config.yaml`:

```yaml
ui:
  start_sticker_id: "CAACAgUAAyEFAASAgUwqAAJh_mckw2STkeY1WMOHJGY4Hs9_1-2fAAIPFAACYLShVon-N6AFLnIiHgQ"
  start_image_url: "https://envs.sh/odE.png"  # spoiler photo shown on /start
  start_image_has_spoiler: true
  sticker_delete_delay: 1.5    # seconds to wait before deleting the start sticker
  loading_dot_delay: 0.32      # seconds between each dot step in loading animation
  loading_steps: 3             # how many dots to go up to (! → !! → !!!)
```

Read these from `core/config.py` in a new `UIConfig` Pydantic model and wire it into the container.

---

## 10. New File: `src/nekofetch/ui/typography.py`

Create this new file to centralize all typography helpers:

```python
"""
Typography utilities for the NekoFetch UI.

Provides:
- small_caps(text): converts ASCII text to Unicode small-caps
- bold_serif(text): converts ASCII text to Unicode bold serif (𝗔𝗕𝗖...)
- bq(text): wraps text in a Telegram <blockquote>
- bqx(text): wraps text in a Telegram <blockquote expandable>
"""

from __future__ import annotations

_SMALL_CAPS = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
)

# Bold sans-serif Unicode for headings
_BOLD_UPPER = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
_BOLD_LOWER = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
_PLAIN_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PLAIN_LOWER = "abcdefghijklmnopqrstuvwxyz"
_BOLD_SERIF = str.maketrans(_PLAIN_UPPER + _PLAIN_LOWER, _BOLD_UPPER + _BOLD_LOWER)


def small_caps(text: str) -> str:
    """Convert ASCII letters to Unicode small-caps."""
    return text.translate(_SMALL_CAPS)


def bold_serif(text: str) -> str:
    """Convert ASCII letters to Unicode bold sans-serif (for headings)."""
    return text.translate(_BOLD_SERIF)


def bq(text: str) -> str:
    """Wrap in a Telegram blockquote."""
    return f"<blockquote>{text}</blockquote>"


def bqx(text: str) -> str:
    """Wrap in a Telegram expandable blockquote."""
    return f"<blockquote expandable>{text}</blockquote>"


def heading(text: str) -> str:
    """A bold-serif heading wrapped in a blockquote."""
    return bq(f"<b>{bold_serif(text)}</b>")


def field(label: str, value: str) -> str:
    """Format a label/value pair in the house style."""
    return f"<b>{small_caps(label)}:</b> <code>{value}</code>"
```

Then **import from this file** everywhere instead of hardcoding Unicode characters inline. Update `ui/__init__.py` to export `typography`.

---

## 11. File-by-File Change Summary

> This is the checklist for the AI developer. Tick off each one.

### `src/nekofetch/ui/progress.py`
- [ ] Add `loading_animation(msg, label, steps, delay)` async function
- [ ] Add `staged_loading(msg, stages, delay_per_stage)` async function
- [ ] Add `labeled_html(label, percent, width)` function returning `<blockquote>` HTML

### `src/nekofetch/ui/typography.py` *(new file)*
- [ ] Create with `small_caps`, `bold_serif`, `bq`, `bqx`, `heading`, `field` helpers

### `src/nekofetch/ui/__init__.py`
- [ ] Export `typography` module

### `src/nekofetch/core/config.py`
- [ ] Add `UIConfig` Pydantic model
- [ ] Add `ui: UIConfig` field to the main config

### `config.yaml`
- [ ] Add `ui:` section (sticker_id, image_url, spoiler, delays)

### `resources/language/en.json`
- [ ] Convert all `btn_*` values to small-caps
- [ ] Convert all `status_*` values to small-caps
- [ ] Convert all error/access message values to small-caps + blockquote format
- [ ] Update `welcome_title` to bold-serif Unicode

### `src/nekofetch/bots/admin/handlers/start.py`
- [ ] Add sticker send at top of `_start`
- [ ] Replace progress bar loading with `staged_loading`
- [ ] Delete sticker after delay
- [ ] Replace final `edit_text` with `send_photo` (spoiler photo + blockquote caption)
- [ ] All text → `ParseMode.HTML`

### `src/nekofetch/bots/admin/keyboards.py`
- [ ] All button labels → small-caps (per Section 4 table)

### `src/nekofetch/bots/admin/handlers/requests.py`
- [ ] Wrap all `reply` / `edit_text` calls in `ParseMode.HTML`
- [ ] Add `staged_loading` before `source.search()` call
- [ ] Add `loading_animation` before any other async DB/source fetch
- [ ] Reformat `_results_text` with blockquote HTML
- [ ] Reformat request-accepted message with blockquote HTML

### `src/nekofetch/bots/admin/handlers/approvals.py`
- [ ] Add `loading_animation` before `list_ready()` call
- [ ] Add `loading_animation` during publish/reprocess
- [ ] Reformat approval panel text with blockquote HTML
- [ ] All text → `ParseMode.HTML`
- [ ] Button labels → small-caps

### `src/nekofetch/bots/admin/handlers/settings.py`
- [ ] All messages → `ParseMode.HTML` + blockquote
- [ ] Button labels → small-caps
- [ ] Add loading animation when loading current settings

### `src/nekofetch/bots/admin/handlers/bots_admin.py`
- [ ] All messages → `ParseMode.HTML` + blockquote
- [ ] Button labels → small-caps
- [ ] Add loading animation when spawning/listing bots

### `src/nekofetch/bots/admin/handlers/staff_admin.py`
- [ ] All messages → `ParseMode.HTML` + blockquote
- [ ] Button labels → small-caps

### `src/nekofetch/bots/admin/handlers/admin_tools.py`
- [ ] Broadcast messages: use blockquote format
- [ ] Add loading animation while fetching stats

### `src/nekofetch/bots/admin/handlers/storage_admin.py`
- [ ] All messages → `ParseMode.HTML` + blockquote
- [ ] Button labels → small-caps
- [ ] Add loading animation during indexing operations

### `src/nekofetch/bots/distribution/app.py`
- [ ] `_start`: add sticker, staged loading, spoiler photo (same pattern as admin `/start`)
- [ ] `_help`: reformat with blockquote HTML + small-caps
- [ ] `_ensure_access` failed message: reformat with blockquote
- [ ] `_show_title` and `_show_catalog`: add `loading_animation` before fetching
- [ ] Season/resolution/language selection menus: button labels → small-caps
- [ ] Delivery message (auto-delete warning): reformat per Section 5.8
- [ ] Files-deleted message: reformat per Section 5.9
- [ ] All `reply_markup` keyboard labels → small-caps
- [ ] All `edit_text` / `reply` → `ParseMode.HTML`

### `src/nekofetch/bots/force_sub.py`
- [ ] Add `loading_animation` during subscription check
- [ ] Force-sub wall message: reformat per Section 5.10
- [ ] Status messages: `"ᴄᴏɴɴᴇᴄᴛɪɴɢ"` → `"ᴄᴏɴɴᴇᴄᴛɪɴɢ!!"` dot animation
- [ ] All text → `ParseMode.HTML`

---

## 12. Parse Mode Migration Guide

Currently the bot mixes Markdown (`**bold**`) and HTML. After this redesign, the bot is **100% HTML only**. Here is how to migrate:

| Old Markdown | New HTML |
|---|---|
| `**text**` | `<b>text</b>` |
| `*text*` | `<i>text</i>` |
| `` `text` `` | `<code>text</code>` |
| `[label](url)` | `<a href="url">label</a>` |

Add `parse_mode=ParseMode.HTML` to every `reply`, `edit_text`, `send_message`, `send_photo` call. Remove all `ParseMode.MARKDOWN` or `ParseMode.MARKDOWN_V2` references.

---

## 13. Testing Checklist After Implementation

Once all changes are applied, manually verify:

- [ ] `/start` on admin bot: sticker appears, loading animation plays, sticker disappears, spoiler photo reveals welcome screen
- [ ] `/start` on distribution bot: same pattern
- [ ] Searching for an anime: loading animation plays during search
- [ ] Selecting a title: loading animation plays while fetching content info
- [ ] Submitting a request: loading animation plays, confirmation message uses blockquote HTML
- [ ] Admin approval panel: loading animation plays, approval text uses blockquote HTML
- [ ] Force-sub wall: dot animation plays, channels list uses blockquote HTML
- [ ] All buttons across all menus display in small-caps font
- [ ] No raw `**markdown**` appears anywhere in messages
- [ ] Auto-delete warning message uses blockquote HTML
- [ ] Files-deleted message uses blockquote HTML

---

## 14. Notes & Constraints

1. **Do not change any business logic.** This is purely a UI layer change. The services, repositories, sources, and providers must not be touched.
2. **Backward compatibility for `en.json`:** The localizer reads keys — updating values is safe. Do not rename or remove any keys.
3. **Sticker ID is configurable.** Do not hardcode it anywhere except as the default in `config.yaml`.
4. **`ParseMode.HTML` is required** for `<blockquote>` to render. Ensure the import `from pyrogram.enums import ParseMode` is present in every file you edit.
5. **The `loading_animation` and `staged_loading` functions must handle `MessageNotModified` errors** gracefully (Telegram raises this if the edit content is identical to current). Wrap edits in `try/except MessageNotModified: pass`.
6. **Keep the existing `▰▱` progress bar.** It is still used for download dashboards. Just wrap it in `labeled_html` for HTML output.

---

*End of redesign specification. Follow this document exactly.*
