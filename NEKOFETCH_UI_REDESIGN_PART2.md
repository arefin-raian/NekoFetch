# NekoFetch UI Redesign — Part 2: Progress Displays, Error Handling & Log Channel

> **Instruction to the AI developer:** This is Part 2 of the UI redesign spec. It is equally mandatory as Part 1. Read the entire document before touching any file. Every section describes a real problem found in the repository that must be fixed. Do not fix just the surface — fix the root cause.

---

## 0. Problems Found in the Repository (Full Audit)

After reading every file in `src/nekofetch/`, the following specific issues were found. These are **not suggestions** — they are bugs and UX failures that need to be fixed.

### Silent Failures (User Gets No Feedback)

| File | Location | What Fails Silently |
|------|----------|---------------------|
| `services/download_service.py` | `_handle_failure` | Download failure is logged to structlog + log channel but the **user who requested it is never told their download failed** |
| `services/processing/pipeline.py` | `run_for_job` | `ProcessingError` is raised and logged but **the requesting user never gets notified** |
| `services/processing/stages.py` | `VerifyStage`, `RenameStage`, `MetadataStage` | Stage notes (e.g. `verify failed`, `rename skipped`) are appended to `ctx.notes` but **never shown anywhere** |
| `bots/manager.py` | `_load_distribution_bots` | Distribution bot load failures are `log.error`'d but the **admin gets no Telegram message** |
| `bots/manager.py` | `_try_resolve` / `_retry_resolve` | Channel resolution failures only log to structlog — **admin never receives a Telegram alert** |
| `bots/admin/handlers/review.py` | `_approve` | Uses `q.answer(f"Queued (job #{job_id})")` — this is a **toast popup that disappears in 5 seconds**. The queue message itself is not updated |
| `bots/admin/handlers/bots_admin.py` | `_token` | Registration failure shows a bare text message with no styling |
| `bots/admin/handlers/admin_tools.py` | `_broadcast` | Individual user send failures are silently counted but never described |
| `bots/force_sub.py` | `channels_to_join` | Exceptions silently add channels without URLs — user sees a button with no link |
| `bots/middleware.py` | `_msg_mw` | Rate limit reply is plain unstyled text |

### Log Channel Format Issues

| File | Issue |
|------|-------|
| `services/log_channel_service.py` → `event()` | Mixes Markdown backtick `` ` `` syntax with `**bold**` — Telegram renders these inconsistently. No `ParseMode` is specified so the output depends on Telegram's default guess |
| `_dashboard_text()` | Uses `**bold**` Markdown. No `ParseMode.HTML` specified |
| `_catalog_text()` | Uses `**bold**` Markdown. No `ParseMode.HTML` specified |
| `_ensure_pin()` | Pins a message but **never deletes the "X pinned a message" system message** that Telegram auto-posts. This clutters the log channel |
| `event()` detail format | `key=value  key=value` flat string — unreadable for long error messages or tracebacks |

### Progress Bar / Queue Dashboard Issues

| File | Issue |
|------|-------|
| `bots/admin/handlers/settings.py` → `_queue` | Uses `**bold**` Markdown mixed with `progress.bar()` — once we switch to HTML mode this breaks |
| `_queue` | Has a manual "⟳ Refresh" button — there is no auto-refresh. When a download is running, the admin must keep tapping Refresh |
| `progress.bar()` output | Returns `▰▰▱▱▱▱▱▱▱▱ 20%` — bare text, not wrapped in `<code>` for monospaced alignment |
| Queue blocks | `label_status`, `label_speed`, `label_eta` are plain text field labels with no visual hierarchy |
| No episode label | The queue row shows the job's `anime_title` but never shows the **current episode** being downloaded (`current_episode` exists in `ProgressSnapshot` but is not displayed) |
| No bytes downloaded | `downloaded_bytes` / `total_bytes` exist in `ProgressSnapshot` but are never shown in the queue dashboard |

### Other Missing User Feedback

| File | Issue |
|------|-------|
| `bots/admin/handlers/commands.py` → `_help` | Plain Markdown, no blockquote HTML |
| `bots/admin/handlers/commands.py` → `_cancel` | "Cancelled. Send /start to open the menu." — plain text |
| `bots/admin/handlers/review.py` → `_detail` | `label_requested_by: {req.user_id}` shows a raw user ID, not a mention |
| `bots/admin/handlers/settings.py` → `_home` | `"**◈ Admin Panel**"` — just a title, no body text, looks empty |
| `bots/admin/handlers/storage_admin.py` → `_menu` | Status line is plain `enabled/disabled`, no emoji, no blockquote |
| `bots/admin/handlers/bots_admin.py` → `_list` | Awaiting bot list uses inline code `` `doc` `` mixed with `**bold**` Markdown |
| `services/log_channel_service.py` | No notification to admin bot when a download **completes** (only `log_channel.event` — admin must check the log channel) |

---

## 1. Fix: Log Channel — HTML Format & Pin System Message Deletion

### 1.1 Switch Everything to HTML

File: `src/nekofetch/services/log_channel_service.py`

**Current `event()` format (broken):**
```python
text = f"{glyph} `{ts}`  **{category}.{action}**" + (f"\n{detail}" if detail else "")
await self._client.send_message(self.cfg.channel_id, text)
```

**New `event()` format:**
```python
async def event(self, category: str, action: str, **fields) -> None:
    if not self._active() or not self._wants(category):
        return
    try:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        glyph = _CATEGORY_GLYPH.get(category, "◆")
        
        # Build field lines as <code>key</code>: value pairs
        field_lines = "\n".join(
            f"<b>{k}:</b> <code>{v}</code>"
            for k, v in fields.items()
            if v is not None
        )
        
        # Error category gets special treatment — show error in a code block
        if category == "error" and "error" in fields:
            error_text = str(fields.get("error", ""))
            # Truncate very long errors
            if len(error_text) > 300:
                error_text = error_text[:300] + "…"
            other_fields = {k: v for k, v in fields.items() if k != "error"}
            other_lines = "\n".join(
                f"<b>{k}:</b> <code>{v}</code>"
                for k, v in other_fields.items()
                if v is not None
            )
            text = (
                f"<blockquote>"
                f"{glyph} <b>{category}.{action}</b>  <code>{ts}</code>"
                f"</blockquote>"
                + (f"\n{other_lines}" if other_lines else "")
                + f"\n\n<code>{error_text}</code>"
            )
        else:
            text = (
                f"<blockquote>"
                f"{glyph} <b>{category}.{action}</b>  <code>{ts}</code>"
                + (f"\n{field_lines}" if field_lines else "")
                + "</blockquote>"
            )
        
        await self._client.send_message(
            self.cfg.channel_id,
            text,
            parse_mode=ParseMode.HTML,
            disable_notification=True,   # events should not ping
        )
    except Exception as exc:
        log.warning("logchannel.event.failed", error=str(exc))
```

Add `from pyrogram.enums import ParseMode` at the top of the file.

### 1.2 Fix `_dashboard_text()` and `_catalog_text()`

Both must use HTML. New implementations:

```python
async def _dashboard_text(self) -> str:
    from nekofetch.services.analytics_service import AnalyticsService
    s = await AnalyticsService(self._c).dashboard()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    top = "\n".join(
        f"  {i + 1}. {t}  <code>({c})</code>"
        for i, (t, c) in enumerate(s.most_requested)
    ) or "  —"
    return (
        f"<blockquote><b>◈ ɴᴇᴋᴏꜰᴇᴛᴄʜ — ʟɪᴠᴇ ᴅᴀsʜʙᴏᴀʀᴅ</b>  <code>{ts}</code></blockquote>\n\n"
        f"<b>ᴜsᴇʀs:</b> <code>{s.total_users}</code>\n"
        f"<b>ᴅᴏᴡɴʟᴏᴀᴅs:</b> <code>{s.total_downloads}</code>\n"
        f"<b>ǫᴜᴇᴜᴇ:</b> <code>{s.queue_size}</code>\n"
        f"<b>ꜰᴀɪʟᴇᴅ:</b> <code>{s.failed_tasks}</code>\n"
        f"<b>ᴘᴜʙʟɪsʜᴇᴅ:</b> <code>{s.published}</code>\n\n"
        f"<blockquote expandable><b>ᴍᴏsᴛ ʀᴇǫᴜᴇsᴛᴇᴅ</b>\n{top}</blockquote>"
    )

async def _catalog_text(self) -> str:
    from nekofetch.services.distribution_service import DistributionService
    dist = DistributionService(self._c)
    titles = await dist.published_titles()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    if not titles:
        return (
            f"<blockquote><b>◈ ɴᴇᴋᴏꜰᴇᴛᴄʜ — ᴄᴀᴛᴀʟᴏɢ</b>  <code>{ts}</code></blockquote>\n\n"
            "<code>ɴᴏ ᴘᴜʙʟɪsʜᴇᴅ ᴄᴏɴᴛᴇɴᴛ ʏᴇᴛ.</code>"
        )
    lines = []
    for doc_id, title in titles[:40]:
        seasons = await dist.seasons_for(doc_id)
        season_str = "  ".join(f"<code>S{s}</code>" for s in seasons) or "<code>—</code>"
        lines.append(f"◆ {title}  ➜  {season_str}")
    count = len(titles)
    return (
        f"<blockquote><b>◈ ɴᴇᴋᴏꜰᴇᴛᴄʜ — ᴄᴀᴛᴀʟᴏɢ</b>  <code>{count} ᴛɪᴛʟᴇs</code>  <code>{ts}</code></blockquote>\n\n"
        + "\n".join(lines)
    )
```

Both `_edit_pin` calls must pass `parse_mode=ParseMode.HTML`.

### 1.3 Delete the "Pinned a Message" System Message

When Telegram pins a message in a channel/group, it auto-posts a system service message saying "X pinned a message". This clogs the log channel. Delete it immediately after pinning.

**Current `_ensure_pin`:**
```python
await self._client.pin_chat_message(self.cfg.channel_id, msg.id, disable_notification=True)
```

**New `_ensure_pin`:**
```python
try:
    pin_event = await self._client.pin_chat_message(
        self.cfg.channel_id, msg.id, disable_notification=True
    )
    # Delete the "pinned a message" service message Telegram auto-posts.
    # pin_chat_message returns the service Message object in Pyrogram.
    if pin_event and hasattr(pin_event, "id"):
        try:
            await self._client.delete_messages(self.cfg.channel_id, [pin_event.id])
        except Exception:   # noqa: BLE001 — may not have delete permission; ignore
            pass
except Exception:  # noqa: BLE001 — pin may be restricted
    pass
```

> **Note:** Pyrogram's `pin_chat_message` returns the service `Message` object that Telegram creates for the "pinned a message" notification. Deleting that message removes the clutter from the log channel.

---

## 2. Fix: Progress Bar / Queue Dashboard

### 2.1 New HTML Progress Block Builder

Add this function to `src/nekofetch/ui/progress.py`:

```python
def queue_block_html(
    *,
    anime_title: str,
    status: str,
    progress: float,
    speed_bps: float,
    eta_seconds: int | None,
    current_episode: int | None = None,
    downloaded_bytes: int = 0,
    total_bytes: int = 0,
    job_id: int | None = None,
) -> str:
    """
    Render a single download job as a styled HTML blockquote block.

    Example output:
        ┌─────────────────────────────────┐
        │ 📥 Attack on Titan              │
        │                                  │
        │ ᴇᴘɪsᴏᴅᴇ:   S01E04             │
        │ sᴛᴀᴛᴜs:    ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ        │
        │ ᴘʀᴏɢʀᴇss: ▰▰▰▱▱▱▱▱▱▱ 30%     │
        │ sᴘᴇᴇᴅ:     12.4 MB/s            │
        │ ᴇᴛᴀ:       02m 14s              │
        │ sɪᴢᴇ:      312.1 MB / 1.1 GB   │
        └─────────────────────────────────┘
    """
    bar_str = bar(progress)
    ep_line = f"\n<b>ᴇᴘɪsᴏᴅᴇ:</b> <code>S{current_episode:02d}</code>" if current_episode else ""
    size_line = ""
    if total_bytes > 0:
        size_line = f"\n<b>sɪᴢᴇ:</b> <code>{human_bytes(downloaded_bytes)} / {human_bytes(total_bytes)}</code>"
    id_line = f"  <code>#{job_id}</code>" if job_id else ""

    return (
        f"<blockquote>"
        f"📥 <b>{anime_title}</b>{id_line}"
        f"{ep_line}\n"
        f"<b>sᴛᴀᴛᴜs:</b> <code>{status}</code>\n"
        f"<b>ᴘʀᴏɢʀᴇss:</b> <code>{bar_str}</code>\n"
        f"<b>sᴘᴇᴇᴅ:</b> <code>{human_speed(speed_bps)}</code>\n"
        f"<b>ᴇᴛᴀ:</b> <code>{human_eta(eta_seconds)}</code>"
        f"{size_line}"
        f"</blockquote>"
    )
```

### 2.2 Rewrite the Queue Dashboard Handler

File: `src/nekofetch/bots/admin/handlers/settings.py` → `_queue` handler

Replace the entire `_queue` handler body with:

```python
@client.on_callback_query(filters.regex(r"^queue\|view"))
async def _queue(_: Client, q: CallbackQuery) -> None:
    if not _allowed(q, Permission.QUEUE_DOWNLOADS):
        await q.answer(L("access_denied"), show_alert=True)
        return
    from nekofetch.services.queue_service import QueueService

    await q.answer()
    rows = await QueueService(container).dashboard()

    if not rows:
        await q.message.edit_text(
            f"<blockquote><b>📥 ᴅᴏᴡɴʟᴏᴀᴅs ǫᴜᴇᴜᴇ</b></blockquote>\n\n"
            f"<code>ǫᴜᴇᴜᴇ ɪs ᴇᴍᴘᴛʏ.</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(
                [("⟳ ʀᴇꜰʀᴇsʜ", cb("queue", "view", 0))],
                [("← ʙᴀᴄᴋ", cb("admin", "home"))],
            ),
        )
        return

    blocks = []
    for r in rows:
        # Fetch the live progress snapshot for richer data
        snap = await container.progress.get(r.job_id) if container.progress else None
        blocks.append(
            progress.queue_block_html(
                anime_title=r.anime_title,
                status=r.status,
                progress=r.progress,
                speed_bps=r.speed_bps,
                eta_seconds=r.eta_seconds,
                current_episode=snap.current_episode if snap else None,
                downloaded_bytes=snap.downloaded_bytes if snap else 0,
                total_bytes=snap.total_bytes if snap else 0,
                job_id=r.job_id,
            )
        )

    header = f"<blockquote><b>📥 ᴅᴏᴡɴʟᴏᴀᴅs ǫᴜᴇᴜᴇ</b>  <code>{len(rows)} ᴊᴏʙs</code></blockquote>\n\n"
    await q.message.edit_text(
        header + "\n\n".join(blocks),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(
            [("⟳ ʀᴇꜰʀᴇsʜ", cb("queue", "view", 0))],
            [("← ʙᴀᴄᴋ", cb("admin", "home"))],
        ),
    )
```

Add `from pyrogram.enums import ParseMode` to the imports in `settings.py`.

### 2.3 Add `current_episode` to `QueueRow`

File: `src/nekofetch/services/queue_service.py`

Add `current_episode: int | None = None` to the `QueueRow` dataclass and populate it from the Redis snapshot in `dashboard()`:

```python
@dataclass(slots=True)
class QueueRow:
    job_id: int
    anime_title: str
    requested_by: str
    status: str
    progress: float
    speed_bps: float
    eta_seconds: int | None
    current_episode: int | None = None      # ADD THIS
    downloaded_bytes: int = 0               # ADD THIS
    total_bytes: int = 0                    # ADD THIS
```

And in `dashboard()`, populate from the snap:
```python
rows.append(
    QueueRow(
        ...,
        current_episode=(snap.current_episode if snap else None),
        downloaded_bytes=(snap.downloaded_bytes if snap else 0),
        total_bytes=(snap.total_bytes if snap else 0),
    )
)
```

---

## 3. Fix: User Notification on Download Complete / Fail

This is the most important fix in this document. Currently, when a download succeeds or fails, **the user who requested it is never told**. They have to check the log channel or ask.

### 3.1 Create a New `NotificationService`

Create `src/nekofetch/services/notification_service.py`:

```python
"""
Notification service — sends styled in-bot messages to users about their requests.

Called from the download worker and processing pipeline to tell users when their
content is ready, failed, or in an unexpected state. Never raises into the caller.
"""

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
        """Fire-and-forget — never raises."""
        if not self._client:
            return
        try:
            from pyrogram.enums import ParseMode
            await self._client.send_message(
                user_id, text, parse_mode=ParseMode.HTML
            )
        except Exception as exc:  # noqa: BLE001 — user may have blocked the bot
            log.debug("notification.send.failed", user_id=user_id, error=str(exc))

    async def download_complete(self, user_id: int, anime_title: str, request_code: str) -> None:
        """Tell the user their download finished and is pending approval."""
        await self._send(
            user_id,
            f"<blockquote><b>✅ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"ᴅᴏᴡɴʟᴏᴀᴅ ꜰɪɴɪsʜᴇᴅ! ɪᴛ's ɴᴏᴡ ʙᴇɪɴɢ ᴘʀᴏᴄᴇssᴇᴅ ᴀɴᴅ ᴡɪʟʟ ʙᴇ "
            f"ᴀᴠᴀɪʟᴀʙʟᴇ sᴏᴏɴ."
            f"</blockquote>"
        )

    async def processing_complete(self, user_id: int, anime_title: str, request_code: str) -> None:
        """Tell the user their content is ready (or pending staff approval)."""
        await self._send(
            user_id,
            f"<blockquote><b>📦 ᴄᴏɴᴛᴇɴᴛ ʀᴇᴀᴅʏ</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"ᴘʀᴏᴄᴇssɪɴɢ ᴄᴏᴍᴘʟᴇᴛᴇ! ᴄʜᴇᴄᴋ ᴛʜᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ ʙᴏᴛ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ꜰɪʟᴇs."
            f"</blockquote>"
        )

    async def download_failed(self, user_id: int, anime_title: str, request_code: str, error: str) -> None:
        """Tell the user their download failed."""
        # Truncate the error for display
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
        """Tell the user their content has been published and is accessible."""
        await self._send(
            user_id,
            f"<blockquote><b>🎉 ᴄᴏɴᴛᴇɴᴛ ᴘᴜʙʟɪsʜᴇᴅ!</b></blockquote>\n\n"
            f"<blockquote expandable>"
            f"<b>ᴀɴɪᴍᴇ:</b> <code>{anime_title}</code>\n"
            f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>#{request_code}</code>\n\n"
            f"ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ ɪs ɴᴏᴡ ʟɪᴠᴇ! ᴏᴘᴇɴ ᴛʜᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ ʙᴏᴛ ᴀɴᴅ sᴇᴀʀᴄʜ ꜰᴏʀ ɪᴛ."
            f"</blockquote>"
        )

    async def processing_stage_warning(
        self, user_id: int, anime_title: str, stage: str, note: str
    ) -> None:
        """Warn the user that a processing stage had a non-fatal issue."""
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
```

### 3.2 Wire `NotificationService` into `DownloadWorker`

File: `src/nekofetch/services/download_service.py`

Update `_complete()` and `_handle_failure()`:

```python
async def _complete(self, job_id: int) -> None:
    anime_title = "—"
    user_id = None
    request_code = None
    async with session_scope(self._c.pg_sessionmaker) as session:
        job = await session.get(DownloadJob, job_id)
        job.status = JobStatus.COMPLETED
        job.progress = 100.0
        job.finished_at = _now()
        req = await RequestRepository(session).get(job.request_id)
        if req:
            req.status = RequestStatus.PROCESSING
            anime_title = req.anime_title
            user_id = req.user_id
            request_code = req.code
    log.info("download.job.complete", job_id=job_id)

    from nekofetch.services.log_channel_service import LogChannelService
    from nekofetch.services.notification_service import NotificationService

    await LogChannelService(self._c).event(
        "download", "complete", job=job_id, anime=anime_title
    )

    # Notify the requesting user
    if user_id:
        await NotificationService(self._c).download_complete(
            user_id, anime_title, request_code or "—"
        )

    from nekofetch.services.processing.pipeline import ProcessingPipeline
    ctx = await ProcessingPipeline(self._c).run_for_job(job_id)

    await LogChannelService(self._c).event(
        "processing", "complete", job=job_id, notes=len(ctx.notes)
    )

    # Notify user that processing is done
    if user_id:
        if ctx.notes:
            # Surface any non-fatal stage warnings to the user
            for note in ctx.notes:
                stage = note.split(":")[0] if ":" in note else "processing"
                await NotificationService(self._c).processing_stage_warning(
                    user_id, anime_title, stage, note
                )
        await NotificationService(self._c).processing_complete(
            user_id, anime_title, request_code or "—"
        )


async def _handle_failure(self, job_id: int, exc: Exception) -> None:
    anime_title = "—"
    user_id = None
    request_code = None
    async with session_scope(self._c.pg_sessionmaker) as session:
        job = await session.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.error = str(exc)
        req = await RequestRepository(session).get(job.request_id)
        if req:
            anime_title = req.anime_title
            user_id = req.user_id
            request_code = req.code

    log.error("download.job.failed", job_id=job_id, error=str(exc))

    from nekofetch.services.log_channel_service import LogChannelService
    from nekofetch.services.notification_service import NotificationService

    await LogChannelService(self._c).event(
        "error", "download_failed", job=job_id, anime=anime_title, error=str(exc)
    )

    # Tell the requesting user their download failed
    if user_id:
        await NotificationService(self._c).download_failed(
            user_id, anime_title, request_code or "—", str(exc)
        )
```

### 3.3 Wire `NotificationService` into `PublishingService`

File: `src/nekofetch/services/publishing_service.py`

In the `publish()` method, after successfully publishing, notify the requesting user:

```python
# After publishing files and committing:
if req and req.user_id:
    from nekofetch.services.notification_service import NotificationService
    await NotificationService(self._c).request_published(
        req.user_id, req.anime_title, req.code
    )
```

---

## 4. Fix: Admin Bot Startup Alert

File: `src/nekofetch/bots/manager.py`

When distribution bots fail to load, the admin must be told in-bot. Add a startup alert method:

```python
async def _alert_admin(self, text: str) -> None:
    """Send an HTML alert to the bot owner (OWNER_ID from config)."""
    from pyrogram.enums import ParseMode
    owner_id = self._c.config.security.owner_id  # Add this field to config if missing
    if not owner_id or not self._admin:
        return
    try:
        await self._admin.send_message(
            owner_id, text, parse_mode=ParseMode.HTML
        )
    except Exception:  # noqa: BLE001
        pass
```

Then in `_load_distribution_bots`, replace the silent `log.error` with:

```python
except Exception as exc:  # one bad token must not stop the fleet
    log.error("bots.distribution.failed", id=row.id, error=str(exc))
    await self._alert_admin(
        f"<blockquote><b>⚠️ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ ʙᴏᴛ ꜰᴀɪʟᴇᴅ ᴛᴏ sᴛᴀʀᴛ</b></blockquote>\n\n"
        f"<blockquote expandable>"
        f"<b>ʙᴏᴛ ɪᴅ:</b> <code>{row.id}</code>\n"
        f"<b>ɴᴀᴍᴇ:</b> <code>{getattr(row, 'name', '—')}</code>\n"
        f"<b>ᴇʀʀᴏʀ:</b>\n<code>{str(exc)[:300]}</code>"
        f"</blockquote>"
    )
```

And when a channel stays unreachable after all retries (`_retry_resolve` exhausted):

```python
async def _retry_resolve(self, name: str, cid: int) -> None:
    log.info("bots.channel.retrying", channel=name, id=cid)
    for attempt in range(1, _RESOLVE_MAX_RETRIES + 1):
        await asyncio.sleep(_RESOLVE_RETRY_SECONDS)
        try:
            chat = await self._admin.get_chat(cid)
            log.info("bots.channel.resolved", channel=name, id=cid)
            return
        except Exception:
            log.debug("bots.channel.retry_pending", channel=name, id=cid, attempt=attempt)
    # Exhausted all retries — alert the owner
    log.warning("bots.channel.retry_exhausted", channel=name, id=cid)
    await self._alert_admin(
        f"<blockquote><b>🔴 ᴄʜᴀɴɴᴇʟ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ</b></blockquote>\n\n"
        f"<blockquote expandable>"
        f"<b>ᴄʜᴀɴɴᴇʟ:</b> <code>{name}</code>\n"
        f"<b>ɪᴅ:</b> <code>{cid}</code>\n\n"
        f"ᴍᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ʙᴏᴛ ɪs ᴀᴅᴍɪɴ ɪɴ ᴛʜɪs ᴄʜᴀɴɴᴇʟ ᴀɴᴅ ᴛʜᴀᴛ ᴛʜᴇ ɪᴅ ɪs ᴛʜᴇ ꜰᴜʟʟ "
        f"<code>-100…</code> ᴠᴀʟᴜᴇ. ᴘᴏsᴛ ᴀɴʏ ᴍᴇssᴀɢᴇ ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ᴛᴏ ʀᴇꜰʀᴇsʜ ᴛʜᴇ ᴘᴇᴇʀ ᴄᴀᴄʜᴇ."
        f"</blockquote>"
    )
```

---

## 5. Fix: All Remaining Silent Failures in Handlers

### 5.1 Rate Limit Message (`bots/middleware.py`)

```python
# Replace this:
await message.reply(container.localizer.get("rate_limited"))

# With this:
from pyrogram.enums import ParseMode
await message.reply(
    "<blockquote><b>⏳ sʟᴏᴡ ᴅᴏᴡɴ!</b>\n\nʏᴏᴜ'ʀᴇ ɢᴏɪɴɢ ᴛᴏᴏ ꜰᴀsᴛ. ᴡᴀɪᴛ ᴀ ᴍᴏᴍᴇɴᴛ.</blockquote>",
    parse_mode=ParseMode.HTML,
)
```

### 5.2 Cancel Command (`bots/admin/handlers/commands.py`)

```python
# Replace this:
await message.reply("Cancelled. Send /start to open the menu.")

# With this:
from pyrogram.enums import ParseMode
await message.reply(
    "<blockquote><b>✗ ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>\n\nᴏᴘᴇʀᴀᴛɪᴏɴ ᴄʟᴇᴀʀᴇᴅ. sᴇɴᴅ /start ᴛᴏ ᴏᴘᴇɴ ᴛʜᴇ ᴍᴇɴᴜ.</blockquote>",
    parse_mode=ParseMode.HTML,
)
```

### 5.3 Help Command (`bots/admin/handlers/commands.py`)

Replace the entire `_help` handler with HTML + blockquotes:

```python
@client.on_message(filters.command("help"))
async def _help(_: Client, message: Message) -> None:
    from pyrogram.enums import ParseMode
    role = _role(message)
    lines = [
        "<blockquote><b>◈ ɴᴇᴋᴏꜰᴇᴛᴄʜ — ʜᴇʟᴘ</b></blockquote>\n",
        "<blockquote expandable>",
        "<b>ᴄᴏᴍᴍᴀɴᴅs</b>\n",
        "◆ /start — ᴏᴘᴇɴ ᴛʜᴇ ᴍᴀɪɴ ᴘᴀɴᴇʟ\n",
        "◆ /help — sʜᴏᴡ ᴛʜɪs ᴍᴇssᴀɢᴇ\n",
        "◆ /cancel — ᴀʙᴏʀᴛ ᴛʜᴇ ᴄᴜʀʀᴇɴᴛ ᴏᴘᴇʀᴀᴛɪᴏɴ\n\n",
        "<b>ᴇᴠᴇʀʏᴏɴᴇ ᴄᴀɴ</b>\n",
        "◆ ʀᴇǫᴜᴇsᴛ ᴀɴɪᴍᴇ — sᴇᴀʀᴄʜ ᴀ ᴛɪᴛʟᴇ, ᴘɪᴄᴋ ᴀ sᴇᴀsᴏɴ, sᴜʙᴍɪᴛ\n",
        "◆ ᴍʏ ʀᴇǫᴜᴇsᴛs — ᴛʀᴀᴄᴋ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛs",
    ]
    if role in (Role.STAFF, Role.ADMIN):
        lines += [
            "\n\n<b>sᴛᴀꜰꜰ ᴄᴀɴ ᴀʟsᴏ</b>\n",
            "◆ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs — ᴀᴘᴘʀᴏᴠᴇ ᴏʀ ʀᴇᴊᴇᴄᴛ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs\n",
            "◆ ᴅᴏᴡɴʟᴏᴀᴅs ǫᴜᴇᴜᴇ — ᴡᴀᴛᴄʜ ʟɪᴠᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴘʀᴏɢʀᴇss\n",
            "◆ ᴀᴘᴘʀᴏᴠᴀʟs — ᴘᴜʙʟɪsʜ / ʀᴇᴘʀᴏᴄᴇss / ᴄᴀɴᴄᴇʟ ꜰɪɴɪsʜᴇᴅ ᴄᴏɴᴛᴇɴᴛ",
        ]
    if role is Role.ADMIN:
        lines += [
            "\n\n<b>ᴀᴅᴍɪɴs ᴄᴀɴ ᴀʟsᴏ</b>\n",
            "◆ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ — sᴇᴛᴛɪɴɢs · ᴀɴᴀʟʏᴛɪᴄs · sᴛᴀꜰꜰ · ʙᴏᴛs · sᴛᴏʀᴀɢᴇ · ʙʀᴏᴀᴅᴄᴀsᴛ",
        ]
    lines.append("</blockquote>")
    await message.reply("".join(lines), parse_mode=ParseMode.HTML)
```

### 5.4 Review Detail Panel (`bots/admin/handlers/review.py`)

The `_detail` handler currently shows `req.user_id` as a raw number. Fix it to show a proper mention, and wrap the whole thing in blockquote HTML:

```python
text = (
    f"<blockquote><b>▸ ʀᴇᴠɪᴇᴡ · <code>#{req.code}</code></b></blockquote>\n\n"
    f"<blockquote expandable>"
    f"<b>ᴀɴɪᴍᴇ:</b> <code>{req.anime_title}</code>\n"
    f"<b>sᴛᴀᴛᴜs:</b> <code>{req.status}</code>\n"
    f"<b>sᴄᴏᴘᴇ:</b> <code>{_scope_label(req)}</code>\n"
    f"<b>sᴏᴜʀᴄᴇ:</b> <code>{req.source}</code>\n"
    f"<b>ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ:</b> <a href='tg://user?id={req.user_id}'>{req.user_id}</a>"
    f"</blockquote>"
)
# Parse mode must be HTML
await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=...)
```

Also fix button labels for `_approve` and `_reject`:
```python
# Old:
("✓ Approve → Queue", cb("staff", "rapprove", req.code))
("✕ Reject", cb("staff", "rreject", req.code))

# New:
("✓ ᴀᴘᴘʀᴏᴠᴇ → ǫᴜᴇᴜᴇ", cb("staff", "rapprove", req.code))
("✕ ʀᴇᴊᴇᴄᴛ", cb("staff", "rreject", req.code))
```

### 5.5 Request List Panel (`bots/admin/handlers/review.py` → `_render_list`)

```python
# Old:
await q.message.edit_text(
    f"**▸ Review Requests**\n\n{len(pending)} awaiting review. Tap one to review.",
    reply_markup=kb,
)

# New:
await q.message.edit_text(
    f"<blockquote><b>▸ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs</b>  <code>{len(pending)} ᴘᴇɴᴅɪɴɢ</code></blockquote>\n\n"
    f"<code>ᴛᴀᴘ ᴀ ʀᴇǫᴜᴇsᴛ ᴛᴏ ʀᴇᴠɪᴇᴡ ɪᴛ.</code>",
    parse_mode=ParseMode.HTML,
    reply_markup=kb,
)
```

### 5.6 Broadcast Result (`bots/admin/handlers/admin_tools.py`)

```python
# Old:
await status.edit_text(f"**Broadcast complete**\n\nDelivered: {sent}\nFailed: {failed}")

# New:
from pyrogram.enums import ParseMode
await status.edit_text(
    f"<blockquote><b>📡 ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ</b></blockquote>\n\n"
    f"<blockquote>"
    f"<b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> <code>{sent}</code>\n"
    f"<b>ꜰᴀɪʟᴇᴅ:</b> <code>{failed}</code>\n"
    f"<b>ᴛᴏᴛᴀʟ:</b> <code>{sent + failed}</code>"
    f"</blockquote>",
    parse_mode=ParseMode.HTML,
)
```

### 5.7 Bot Registration Result (`bots/admin/handlers/bots_admin.py`)

```python
# Old:
await status.edit_text("Validating token…")
# ... on success:
await status.edit_text(f"{DIAMOND_FILLED} **Bot registered & live**\n\nName: {info.name}\n...")
# ... on failure:
await status.edit_text(f"{DIAMOND_HOLLOW} {exc.detail or 'Registration failed.'}")

# New:
from pyrogram.enums import ParseMode

# Loading state:
await status.edit_text(
    "<code>ᴠᴀʟɪᴅᴀᴛɪɴɢ ᴛᴏᴋᴇɴ!</code>", parse_mode=ParseMode.HTML
)
await asyncio.sleep(0.35)
await status.edit_text(
    "<code>ᴠᴀʟɪᴅᴀᴛɪɴɢ ᴛᴏᴋᴇɴ!!</code>", parse_mode=ParseMode.HTML
)
await asyncio.sleep(0.35)
await status.edit_text(
    "<code>ʀᴇɢɪsᴛᴇʀɪɴɢ!</code>", parse_mode=ParseMode.HTML
)

# On success:
await status.edit_text(
    f"<blockquote><b>✅ ʙᴏᴛ ʀᴇɢɪsᴛᴇʀᴇᴅ & ʟɪᴠᴇ</b></blockquote>\n\n"
    f"<blockquote>"
    f"<b>ɴᴀᴍᴇ:</b> <code>{info.name}</code>\n"
    f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> <code>@{info.username}</code>"
    f"</blockquote>",
    parse_mode=ParseMode.HTML,
)

# On failure:
await status.edit_text(
    f"<blockquote><b>❌ ʀᴇɢɪsᴛʀᴀᴛɪᴏɴ ꜰᴀɪʟᴇᴅ</b></blockquote>\n\n"
    f"<code>{exc.detail or 'Invalid token or bot already registered.'}</code>",
    parse_mode=ParseMode.HTML,
)
```

### 5.8 Storage Admin Menu (`bots/admin/handlers/storage_admin.py`)

```python
# Old:
await q.message.edit_text(
    "**▸ Storage Channel**\n\n"
    f"Status: {'enabled' if enabled else 'disabled'}\n"
    f"Channel: `{container.config.storage_channel.channel_id or 'not set'}`",
    ...
)

# New:
from pyrogram.enums import ParseMode
status_label = "✅ ᴇɴᴀʙʟᴇᴅ" if enabled else "🔴 ᴅɪsᴀʙʟᴇᴅ"
await q.message.edit_text(
    f"<blockquote><b>▸ sᴛᴏʀᴀɢᴇ ᴄʜᴀɴɴᴇʟ</b></blockquote>\n\n"
    f"<blockquote>"
    f"<b>sᴛᴀᴛᴜs:</b> <code>{status_label}</code>\n"
    f"<b>ᴄʜᴀɴɴᴇʟ:</b> <code>{container.config.storage_channel.channel_id or 'ɴᴏᴛ sᴇᴛ'}</code>"
    f"</blockquote>",
    parse_mode=ParseMode.HTML,
    reply_markup=...,
)
```

### 5.9 Analytics Panel (`bots/admin/handlers/settings.py` → `_analytics`)

```python
# Old:
await q.message.edit_text(
    "**▸ Analytics**\n\n"
    f"{DIAMOND_FILLED} Total Users: {s.total_users}\n"
    ...
)

# New:
from pyrogram.enums import ParseMode
top = "\n".join(
    f"  {i + 1}. {t}  <code>({c})</code>"
    for i, (t, c) in enumerate(s.most_requested)
) or "  <code>—</code>"
await q.message.edit_text(
    f"<blockquote><b>▸ ᴀɴᴀʟʏᴛɪᴄs</b></blockquote>\n\n"
    f"<blockquote>"
    f"<b>ᴜsᴇʀs:</b> <code>{s.total_users}</code>\n"
    f"<b>ᴅᴏᴡɴʟᴏᴀᴅs:</b> <code>{s.total_downloads}</code>\n"
    f"<b>ǫᴜᴇᴜᴇ:</b> <code>{s.queue_size}</code>\n"
    f"<b>ꜰᴀɪʟᴇᴅ:</b> <code>{s.failed_tasks}</code>\n"
    f"<b>ᴘᴜʙʟɪsʜᴇᴅ:</b> <code>{s.published}</code>"
    f"</blockquote>\n\n"
    f"<blockquote expandable><b>ᴍᴏsᴛ ʀᴇǫᴜᴇsᴛᴇᴅ</b>\n{top}</blockquote>",
    parse_mode=ParseMode.HTML,
    reply_markup=keyboard([("← ʙᴀᴄᴋ", cb("admin", "home"))]),
)
```

### 5.10 Settings Toggle (`bots/admin/handlers/settings.py` → `_render_settings`)

```python
# Old:
label = f"{glyph} {name.replace('_', ' ').title()}"

# New (small-caps the feature name):
from nekofetch.ui.typography import small_caps
label = f"{glyph} {small_caps(name.replace('_', ' '))}"
```

And the settings header:
```python
# Old:
"**▸ Feature Settings**\n\n"
f"{DIAMOND_FILLED} enabled   {DIAMOND_HOLLOW} disabled\n"
"Tap to toggle. Changes apply immediately."

# New:
"<blockquote><b>▸ ꜰᴇᴀᴛᴜʀᴇ sᴇᴛᴛɪɴɢs</b></blockquote>\n\n"
f"<code>◆ ᴇɴᴀʙʟᴇᴅ  ◇ ᴅɪsᴀʙʟᴇᴅ</code>\n"
"<code>ᴛᴀᴘ ᴛᴏ ᴛᴏɢɢʟᴇ. ᴄʜᴀɴɢᴇs ᴀᴘᴘʟʏ ɪᴍᴍᴇᴅɪᴀᴛᴇʟʏ.</code>"
```

---

## 6. New `en.json` Keys to Add

Add the following new keys to `resources/language/en.json` to cover the new notification messages:

```json
{
  "notif_download_complete_title": "✅ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ",
  "notif_download_complete_body": "ᴅᴏᴡɴʟᴏᴀᴅ ꜰɪɴɪsʜᴇᴅ! ɪᴛ's ɴᴏᴡ ʙᴇɪɴɢ ᴘʀᴏᴄᴇssᴇᴅ.",
  "notif_processing_complete_title": "📦 ᴄᴏɴᴛᴇɴᴛ ʀᴇᴀᴅʏ",
  "notif_processing_complete_body": "ᴘʀᴏᴄᴇssɪɴɢ ᴄᴏᴍᴘʟᴇᴛᴇ! ᴄʜᴇᴄᴋ ᴛʜᴇ ᴅɪsᴛʀɪʙᴜᴛɪᴏɴ ʙᴏᴛ.",
  "notif_download_failed_title": "❌ ᴅᴏᴡɴʟᴏᴀᴅ ꜰᴀɪʟᴇᴅ",
  "notif_download_failed_body": "sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ. ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ sᴛᴀꜰꜰ.",
  "notif_published_title": "🎉 ᴄᴏɴᴛᴇɴᴛ ᴘᴜʙʟɪsʜᴇᴅ",
  "notif_published_body": "ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ ɪs ɴᴏᴡ ʟɪᴠᴇ!",
  "notif_stage_warning_title": "⚠️ ᴘʀᴏᴄᴇssɪɴɢ ᴡᴀʀɴɪɴɢ"
}
```

---

## 7. File-by-File Checklist (Part 2)

> Check off each item as you complete it.

### `src/nekofetch/services/notification_service.py` *(new file)*
- [ ] Create with all 5 notification methods as specified in Section 3.1

### `src/nekofetch/services/log_channel_service.py`
- [ ] Add `from pyrogram.enums import ParseMode`
- [ ] Rewrite `event()` to use HTML blockquote format with code-block error display (Section 1.1)
- [ ] Rewrite `_dashboard_text()` to use HTML (Section 1.2)
- [ ] Rewrite `_catalog_text()` to use HTML (Section 1.2)
- [ ] Add `parse_mode=ParseMode.HTML` to the `_edit_pin` `edit_message_text` call
- [ ] Fix `_ensure_pin()` to delete the pin system message after pinning (Section 1.3)

### `src/nekofetch/ui/progress.py`
- [ ] Add `queue_block_html()` function (Section 2.1)

### `src/nekofetch/services/queue_service.py`
- [ ] Add `current_episode`, `downloaded_bytes`, `total_bytes` to `QueueRow` (Section 2.3)
- [ ] Populate these fields from the Redis snapshot in `dashboard()`

### `src/nekofetch/bots/admin/handlers/settings.py`
- [ ] Rewrite `_queue` handler to use `queue_block_html()` (Section 2.2)
- [ ] Add `parse_mode=ParseMode.HTML` to all `edit_text` calls
- [ ] Rewrite `_analytics` handler to use HTML blockquote (Section 5.9)
- [ ] Rewrite `_render_settings` header to use HTML (Section 5.10)
- [ ] Fix feature name labels to use `small_caps()` (Section 5.10)

### `src/nekofetch/services/download_service.py`
- [ ] Update `_complete()` to call `NotificationService` (Section 3.2)
- [ ] Update `_handle_failure()` to call `NotificationService` (Section 3.2)
- [ ] Extract `anime_title`, `user_id`, `request_code` from the request in both methods

### `src/nekofetch/services/publishing_service.py`
- [ ] After successful publish, call `NotificationService.request_published()` (Section 3.3)

### `src/nekofetch/bots/manager.py`
- [ ] Add `_alert_admin()` method (Section 4)
- [ ] Replace silent `log.error` in `_load_distribution_bots` with `_alert_admin` (Section 4)
- [ ] Replace silent `log.warning` in `_retry_resolve` exhaustion with `_alert_admin` (Section 4)

### `src/nekofetch/bots/middleware.py`
- [ ] Replace plain rate-limit reply with HTML blockquote (Section 5.1)

### `src/nekofetch/bots/admin/handlers/commands.py`
- [ ] Rewrite `_cancel` reply to HTML blockquote (Section 5.2)
- [ ] Rewrite `_help` to full HTML blockquote format (Section 5.3)

### `src/nekofetch/bots/admin/handlers/review.py`
- [ ] Rewrite `_render_list` header to HTML blockquote (Section 5.5)
- [ ] Rewrite `_detail` text to HTML blockquote with tg:// user mention (Section 5.4)
- [ ] Fix approve/reject button labels to small-caps (Section 5.4)
- [ ] Add `parse_mode=ParseMode.HTML` to all `edit_text` calls in this file

### `src/nekofetch/bots/admin/handlers/admin_tools.py`
- [ ] Rewrite broadcast result message to HTML blockquote (Section 5.6)
- [ ] Add `parse_mode=ParseMode.HTML`

### `src/nekofetch/bots/admin/handlers/bots_admin.py`
- [ ] Add loading animation before `BotManagementService.register()` call (Section 5.7)
- [ ] Rewrite success/failure messages to HTML blockquote (Section 5.7)
- [ ] Add `parse_mode=ParseMode.HTML` to all `edit_text` calls

### `src/nekofetch/bots/admin/handlers/storage_admin.py`
- [ ] Rewrite storage menu to HTML blockquote (Section 5.8)
- [ ] Add `parse_mode=ParseMode.HTML` to all `edit_text` calls

### `resources/language/en.json`
- [ ] Add all new `notif_*` keys (Section 6)

---

## 8. Implementation Notes

1. **`NotificationService` is fire-and-forget.** It must never raise into the download worker or publishing service. Every method wraps its send in `try/except`.

2. **`owner_id` in config.** The `_alert_admin` method in `BotManager` needs the owner's Telegram user ID. Add `owner_id: int = 0` to the `SecurityConfig` (or whichever config section is appropriate) in `core/config.py`. The owner sets this in `config.yaml` under `security.owner_id`.

3. **`ParseMode.HTML` must be added to every `send_message`, `edit_text`, and `reply` call touched in this document.** Import it at the top of each file: `from pyrogram.enums import ParseMode`.

4. **Do not change any business logic.** `NotificationService` is a pure output layer — it reads data that already exists and sends messages. It does not write to any database.

5. **The `pin_chat_message` return value.** In Pyrogram v2+, `pin_chat_message` returns `bool`, not a `Message`. To delete the pin service message you may need to listen for `ChatMemberUpdated` or use a different approach. The correct cross-version approach is:
   ```python
   # After pinning, fetch the latest messages in the channel to find the service message
   # and delete it. Or, if the bot is the one posting: get the message ID from the context.
   # The simplest fallback: after pinning, iterate the last 3 messages and delete any
   # service messages (message.service is not None).
   async with client.get_chat_history(channel_id, limit=3) as msgs:
       async for m in msgs:
           if m.service:
               try:
                   await client.delete_messages(channel_id, [m.id])
               except Exception:
                   pass
               break
   ```
   Use this approach in `_ensure_pin` instead of using the return value of `pin_chat_message`.

6. **Do not spam the user with notifications.** The `_complete` method sends two notifications (download complete + processing complete). This is intentional — the two events can be minutes apart. If the config has `require_approval_before_publish = True`, the processing-complete notification should say "awaiting staff approval" instead of "check the distribution bot". Add this conditional to `NotificationService.processing_complete`.

---

*End of Part 2. This document and Part 1 together constitute the full UI redesign specification.*
