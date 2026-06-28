"""Centralized message catalog — the single access point for every visible string.

ALL user-facing text (bot messages, prompts, status/progress, errors, success,
admin output, log-channel cards, notifications, human-readable debug) lives in
``resources/language/<code>.json`` and is reached through this module. Business
logic references a message **key** (a constant on :class:`M`) — never a raw
string — so editing a word, emoji, or bit of HTML in the JSON propagates
everywhere with no code change.

HTML is the default parse mode; every string in the catalog is authored as HTML.

Usage::

    from nekofetch.localization.messages import t, M
    caption = t(M.WELCOME_TITLE, name="Raiyan")
"""

from __future__ import annotations

from pathlib import Path

from pyrogram.enums import ParseMode

from nekofetch.localization.i18n import Localizer

# Default parse mode for everything rendered from the catalog.
PARSE_MODE = ParseMode.HTML

# Absolute path to the catalog, computed from this file's location so it resolves
# correctly no matter what working directory the bot is launched from.
LANG_DIR = Path(__file__).resolve().parents[3] / "resources" / "language"
_localizer = Localizer(LANG_DIR, default="en")

# The single shared Localizer instance. Handlers and the container MUST use this
# (via ``container.localizer``) rather than constructing their own, so there is
# exactly one catalog in memory and an en.json edit propagates everywhere on the
# next ``reload()`` / restart.
localizer = _localizer


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Resolve a catalog ``key`` to its HTML string, formatting ``{placeholders}``.

    Unknown keys fall back to the default language then to the key itself, so a
    gap is visible rather than crashing.
    """
    return _localizer.get(key, lang=lang, **kwargs)


def reload() -> None:
    """Re-read the JSON catalogs (e.g. after an admin edits a message)."""
    _localizer.reload()


def languages() -> list[str]:
    return _localizer.languages


class M:
    """Message keys. The string value IS the JSON key — reference these, never
    raw text. Grouped by surface for navigation."""

    # ── meta / common ──
    SEP_DOT = "sep_dot"

    # ── welcome ──
    WELCOME_TITLE = "welcome_title"
    WELCOME_BODY = "welcome_body"
    WELCOME_LIBRARY = "welcome_library"

    # ── buttons ──
    BTN_REQUEST_ANIME = "btn_request_anime"
    BTN_MY_REQUESTS = "btn_my_requests"
    BTN_BACK = "btn_back"
    BTN_CANCEL = "btn_cancel"
    BTN_SERIES_YES = "btn_series_yes"
    BTN_SERIES_NO = "btn_series_no"
    BTN_VERSION_NEITHER = "btn_version_neither"
    BTN_RETRY = "btn_retry"
    BTN_REASSIGN = "btn_reassign"
    BTN_DISMISS = "btn_dismiss"

    # ── my requests ──
    MYREQ_TITLE = "myreq_title"
    MYREQ_EMPTY = "myreq_empty"
    MYREQ_ROW = "myreq_row"
    MYREQ_SUMMARY = "myreq_summary"

    # ── search / confirm ──
    ASK_TITLE = "ask_title"
    SEARCHING = "searching"
    CONFIRM_HEADER = "confirm_header"
    CONFIRM_QUESTION = "confirm_question"
    VERSION_HEADER = "version_header"
    RETRY_TITLE = "retry_title"

    # ── fields (label : value) ──
    F_TYPE = "field_type"
    F_CONTENT = "field_content"
    F_GENRES = "field_genres"
    F_RATING = "field_rating"
    F_ANIME = "field_anime"
    F_STATUS = "field_status"
    F_QUEUE = "field_queue"
    F_REQUEST = "field_request"
    F_BY = "field_by"
    F_SOURCE = "field_source"
    F_NOW = "field_now"
    F_STUCK_AT = "field_stuck_at"
    F_REASON = "field_reason"
    F_SEASONS = "field_seasons"
    F_QUALITIES = "field_qualities"
    F_EPISODES = "field_episodes"
    F_TOOK = "field_took"

    VALUE_TV = "value_tv_series"
    VALUE_MOVIE = "value_movie"
    VALUE_QUEUED = "value_queued"

    # ── request received ──
    REQ_RECEIVED = "req_received"
    REQ_RECEIVED_BODY = "req_received_body"

    # ── lifecycle steps (log card) ──
    LC_REQUESTED = "lc_requested"
    LC_PENDING = "lc_pending"
    LC_SOURCE_ASSIGNED = "lc_source_assigned"
    LC_DOWNLOADING = "lc_downloading"
    LC_PROCESSING_META = "lc_processing_metadata"
    LC_EXTRACTING_SUBS = "lc_extracting_subtitles"
    LC_WATERMARK = "lc_applying_watermark"
    LC_UPLOADING = "lc_uploading"
    LC_PUBLISHED = "lc_published"
    LC_COMPLETED = "lc_completed"

    # ── log card headers ──
    LOG_PROGRESS_TITLE = "log_progress_title"
    LOG_COMPLETED_TITLE = "log_completed_title"
    LOG_BLOCKED_TITLE = "log_blocked_title"

    # ── admin ──
    ADMIN_NEW_REQUEST = "admin_new_request"
    ADMIN_ASSIGN_SOURCE = "admin_assign_source"
    ADMIN_BTN_TELEGRAM = "admin_btn_telegram"
    ADMIN_BTN_WEBSITE = "admin_btn_website"
    ADMIN_BTN_TORRENT = "admin_btn_torrent"
    ADMIN_BTN_REJECT = "admin_btn_reject"
    ADMIN_BTN_AUTOMATIC = "admin_btn_automatic"
    ADMIN_BTN_MANUAL = "admin_btn_manual"
    ADMIN_TG_CHOOSE = "admin_tg_choose"
    ADMIN_TG_MANUAL_PROMPT = "admin_tg_manual_prompt"

    # ── Phase 1: search / confirm ──
    CONFIRM_ADAPTATION_CHOOSE = "confirm_adaptation_choose"
    BTN_CHOOSE = "btn_choose"
    BTN_READ_MORE = "btn_read_more"
    FIELD_TITLE_ROMAJI = "field_title_romaji"
    FRANCHISE_CONTENT = "franchise_content"
    RELATION_GRAPH = "relation_graph"
    UNIT_SEASONS = "unit_seasons"
    UNIT_MOVIES = "unit_movies"
    UNIT_OVAS = "unit_ovas"
    UNIT_ONAS = "unit_onas"
    UNIT_SPECIALS = "unit_specials"
    UNIT_SPINOFFS = "unit_spinoffs"
    UNIT_EPS = "unit_eps"
    FIELD_STUDIO = "field_studio"
    FIELD_SCORE = "field_score"
    FIELD_FORMAT = "field_format"
    FIELD_SYNOPSIS = "field_synopsis"
    SEARCH_NOT_FOUND = "search_not_found"

    # ── website source admin ──
    SITE_PREFERENCE_TITLE = "site_preference_title"
    SITE_PREFERENCE_PROMPT = "site_preference_prompt"
    SITE_PROVIDER_ANIKOTO = "site_provider_anikoto"
    SITE_PROVIDER_KICKASS = "site_provider_kickass"
    BTN_CONFIRM_PRIORITY = "btn_confirm_priority"

    # ── log channel events ──
    LOG_REQUEST_SUBMITTED = "log_request_submitted"
    LOG_REQUEST_APPROVED = "log_request_approved"
    LOG_REQUEST_REJECTED = "log_request_rejected"
    LOG_SOURCE_ASSIGNED = "log_source_assigned"
    LOG_JOB_QUEUED = "log_job_queued"
    LOG_JOB_COMPLETED = "log_job_completed"
    LOG_JOB_FAILED = "log_job_failed"
    LOG_STAGE_COMPLETE = "log_stage_complete"
    LOG_PUBLISHED = "log_published"

    # ── log channel: control-center sections ──
    CC_DASHBOARD_TITLE = "cc_dashboard_title"
    CC_PENDING_TITLE = "cc_pending_title"
    CC_ACTIVE_TITLE = "cc_active_title"
    CC_COMPLETED_TITLE = "cc_completed_title"
    CC_NOTICES_TITLE = "cc_notices_title"
    CC_CATALOG_TITLE = "cc_catalog_title"
    CC_INTRO = "cc_intro"
    CC_INITIALIZING = "cc_initializing"
    CC_UPDATED = "cc_updated"
    CC_EMPTY_PENDING = "cc_empty_pending"
    CC_EMPTY_ACTIVE = "cc_empty_active"
    CC_EMPTY_COMPLETED = "cc_empty_completed"
    CC_EMPTY_NOTICES = "cc_empty_notices"
    CC_EMPTY_CATALOG = "cc_empty_catalog"
    CC_STAT_USERS = "cc_stat_users"
    CC_STAT_DOWNLOADS = "cc_stat_downloads"
    CC_STAT_QUEUE = "cc_stat_queue"
    CC_STAT_FAILED = "cc_stat_failed"
    CC_STAT_PUBLISHED = "cc_stat_published"
    CC_STAT_ROW = "cc_stat_row"
    CC_MOST_REQUESTED = "cc_most_requested"
    CC_MOST_REQUESTED_ROW = "cc_most_requested_row"
    CC_PENDING_ROW = "cc_pending_row"
    CC_ACTIVE_ROW = "cc_active_row"
    CC_COMPLETED_ROW = "cc_completed_row"
    CC_NOTICE_ROW = "cc_notice_row"
    CC_RESERVED_1 = "cc_reserved_1"
    CC_RESERVED_2 = "cc_reserved_2"
    CC_RESERVED_3 = "cc_reserved_3"
    CC_REQUEST_CARD_TITLE = "cc_request_card_title"
    CC_REQUEST_CARD_BODY = "cc_request_card_body"
    CC_REQUEST_CHOOSE_SOURCE = "cc_request_choose_source"
    CC_AMBIGUITY_TITLE = "cc_ambiguity_title"
    CC_AMBIGUITY_BODY = "cc_ambiguity_body"

    # ── log channel: notice emoji + human labels (category → key) ──
    LOG_EMOJI = {
        "request": "log_emoji_request", "queue": "log_emoji_queue",
        "download": "log_emoji_download", "processing": "log_emoji_processing",
        "publish": "log_emoji_publish", "delivery": "log_emoji_delivery",
        "admin": "log_emoji_admin", "bot": "log_emoji_bot",
        "error": "log_emoji_error", "system": "log_emoji_system",
    }

    # ── commands / help ──
    CMD_START = "cmd_start"
    CMD_HELP = "cmd_help"
    CMD_CANCEL = "cmd_cancel"
    CMD_RELOAD = "cmd_reload"
    CMD_RESETOVERRIDES = "cmd_resetoverrides"
    RELOAD_DONE = "reload_done"
    OVERRIDES_CLEARED = "overrides_cleared"
    HELP_TITLE = "help_title"
    HELP_INTRO = "help_intro"
    HELP_H_COMMANDS = "help_h_commands"
    HELP_H_EVERYONE = "help_h_everyone"
    HELP_H_STAFF = "help_h_staff"
    HELP_H_ADMIN = "help_h_admin"
    HELP_CMD_START = "help_cmd_start"
    HELP_CMD_HELP = "help_cmd_help"
    HELP_CMD_CANCEL = "help_cmd_cancel"
    HELP_CAP_REQUEST = "help_cap_request"
    HELP_CAP_MYREQ = "help_cap_myreq"
    HELP_CAP_REVIEW = "help_cap_review"
    HELP_CAP_QUEUE = "help_cap_queue"
    HELP_CAP_APPROVALS = "help_cap_approvals"
    HELP_CAP_ADMIN = "help_cap_admin"
    CANCELLED = "cancelled"

    # ── staff review / source assignment ──
    REVIEW_TITLE = "review_title"
    REVIEW_EMPTY = "review_empty"
    REVIEW_COUNT = "review_count"
    REVIEW_DETAIL_TITLE = "review_detail_title"
    REVIEW_DETAIL_BODY = "review_detail_body"
    REVIEW_ROW = "review_row"
    SITE_BTN_ANIKOTO_PRIMARY = "site_btn_anikoto_primary"
    SITE_BTN_KICKASS_PRIMARY = "site_btn_kickass_primary"
    SCOPE_SEASON = "scope_season"
    SCOPE_SEASON_EPS = "scope_season_eps"
    TOAST_QUEUED = "toast_queued"
    TOAST_REJECTED = "toast_rejected"
    STATUS_UPDATING = "status_updating"
    STATUS_QUEUING = "status_queuing"
    MANUAL_QUEUED = "manual_queued"
    MANUAL_QUEUE_FAILED = "manual_queue_failed"

    # ── admin home / settings ──
    BTN_REVIEW_REQUESTS = "btn_review_requests"
    ADMIN_BTN_PANEL = "admin_btn_panel"
    ADMIN_HOME_TITLE = "admin_home_title"
    ADMIN_HOME_INTRO = "admin_home_intro"
    ADMIN_BTN_QUEUE = "admin_btn_queue"
    ADMIN_BTN_ANALYTICS = "admin_btn_analytics"
    ADMIN_BTN_STAFF = "admin_btn_staff"
    ADMIN_BTN_BOTS = "admin_btn_bots"
    ADMIN_BTN_SETTINGS = "admin_btn_settings"
    ADMIN_BTN_STORAGE = "admin_btn_storage"
    ADMIN_BTN_APPROVALS = "admin_btn_approvals"
    ADMIN_BTN_BROADCAST = "admin_btn_broadcast"
    SETTINGS_HOME_TITLE = "settings_home_title"
    SETTINGS_HOME_INTRO = "settings_home_intro"
    SETTINGS_SECTION_INTRO = "settings_section_intro"
    SETTINGS_FIELD_ROW = "settings_field_row"
    SETTINGS_VALUE_ROW = "settings_value_row"
    SETTINGS_ON = "settings_on"
    SETTINGS_OFF = "settings_off"
    SETTINGS_EDIT_TITLE = "settings_edit_title"
    SETTINGS_LBL_ABOUT = "settings_lbl_about"
    SETTINGS_LBL_OPTIONS = "settings_lbl_options"
    SETTINGS_LBL_PLACEHOLDERS = "settings_lbl_placeholders"
    SETTINGS_LBL_PLACEHOLDER_ROW = "settings_lbl_placeholder_row"
    SETTINGS_LBL_HTML = "settings_lbl_html"
    SETTINGS_LBL_EXAMPLE = "settings_lbl_example"
    SETTINGS_LBL_CURRENT = "settings_lbl_current"
    SETTINGS_EDIT_HINT = "settings_edit_hint"
    SETTINGS_LIST_HINT = "settings_list_hint"
    SETTINGS_EDIT_DONE = "settings_edit_done"
    SETTINGS_EDIT_BAD = "settings_edit_bad"
    SETTINGS_TOAST_TOGGLED = "settings_toast_toggled"
    SETTINGS_STATE_ON = "settings_state_on"
    SETTINGS_STATE_OFF = "settings_state_off"
    QUEUE_TITLE = "queue_title"
    QUEUE_EMPTY = "queue_empty"

    # ── approvals ──
    APPROVALS_TITLE = "approvals_title"
    APPROVALS_EMPTY = "approvals_empty"
    APPROVALS_DETAIL_TITLE = "approvals_detail_title"
    APPROVALS_DETAIL_BODY = "approvals_detail_body"
    APPROVALS_VALUE_YES = "approvals_value_yes"
    APPROVALS_VALUE_NO = "approvals_value_no"
    APPROVALS_PUBLISHED = "approvals_published"
    APPROVALS_CANCELLED = "approvals_cancelled"
    APPROVALS_TOAST_PUBLISHED = "approvals_toast_published"
    APPROVALS_TOAST_REPROCESSED = "approvals_toast_reprocessed"
    APPROVALS_TOAST_CANCELLED = "approvals_toast_cancelled"
    BTN_PUBLISH = "btn_publish"
    BTN_REPROCESS = "btn_reprocess"

    # ── staff & users ──
    STAFF_TITLE = "staff_title"
    STAFF_EMPTY = "staff_empty"
    STAFF_MEMBER_ROW = "staff_member_row"
    STAFF_MEMBER_DOT_ACTIVE = "staff_member_dot_active"
    STAFF_MEMBER_DOT_BANNED = "staff_member_dot_banned"
    STAFF_FLAG_BANNED = "staff_flag_banned"
    STAFF_BTN_REMOVE = "staff_btn_remove"
    STAFF_BTN_BAN = "staff_btn_ban"
    STAFF_BTN_UNBAN = "staff_btn_unban"
    STAFF_BTN_ADD = "staff_btn_add"
    STAFF_ADD_PROMPT = "staff_add_prompt"
    STAFF_ADD_BAD_ID = "staff_add_bad_id"
    STAFF_ADD_DONE = "staff_add_done"
    STAFF_TOAST_DEMOTED = "staff_toast_demoted"
    STAFF_TOAST_BANNED = "staff_toast_banned"
    STAFF_TOAST_UNBANNED = "staff_toast_unbanned"

    # ── distribution bots ──
    BOTS_TITLE = "bots_title"
    BOTS_EMPTY = "bots_empty"
    BOTS_ROW = "bots_row"
    BOTS_DOT_ACTIVE = "bots_dot_active"
    BOTS_DOT_DISABLED = "bots_dot_disabled"
    BOTS_PENDING_HEADER = "bots_pending_header"
    BOTS_PENDING_ROW = "bots_pending_row"
    BOTS_BTN_BIND = "bots_btn_bind"
    BOTS_BTN_ADD = "bots_btn_add"
    BOTS_BIND_PROMPT = "bots_bind_prompt"
    BOTS_ADD_PROMPT = "bots_add_prompt"
    BOTS_VALIDATING = "bots_validating"
    BOTS_REGISTER_FAILED = "bots_register_failed"
    BOTS_REGISTERED = "bots_registered"
    BOTS_DETAIL_NAMED = "bots_detail_named"
    BOTS_DETAIL_NAME = "bots_detail_name"
    BOTS_BOUND = "bots_bound"
    BOTS_UNBOUND = "bots_unbound"

    # ── storage channel ──
    STORAGE_TITLE = "storage_title"
    STORAGE_STATUS = "storage_status"
    STORAGE_STATUS_ENABLED = "storage_status_enabled"
    STORAGE_STATUS_DISABLED = "storage_status_disabled"
    STORAGE_CHANNEL_UNSET = "storage_channel_unset"
    STORAGE_BTN_INDEX = "storage_btn_index"
    STORAGE_BTN_LIST = "storage_btn_list"
    STORAGE_PACKS_TITLE = "storage_packs_title"
    STORAGE_PACKS_EMPTY = "storage_packs_empty"
    STORAGE_PACK_ROW = "storage_pack_row"
    STORAGE_INDEX_PROMPT = "storage_index_prompt"
    STORAGE_INDEX_BAD_COUNT = "storage_index_bad_count"
    STORAGE_INDEX_BAD_FIELDS = "storage_index_bad_fields"
    STORAGE_INDEXING = "storage_indexing"
    STORAGE_INDEX_FAILED = "storage_index_failed"
    STORAGE_INDEX_FAILED_DEFAULT = "storage_index_failed_default"
    STORAGE_INDEXED = "storage_indexed"

    # ── broadcast ──
    BROADCAST_PROMPT = "broadcast_prompt"
    BROADCAST_SENDING = "broadcast_sending"
    BROADCAST_DONE = "broadcast_done"

    # ── misc / distribution ──
    BTN_REFRESH = "btn_refresh"
    DIST_NOT_SUBSCRIBED = "dist_not_subscribed"
    DIST_SUBSCRIBED_THANKS = "dist_subscribed_thanks"
    DIST_UNAVAILABLE = "dist_unavailable"

    # ── startup ──
    CONNECTING = "connecting"
    LOADING_STAGE_CONNECTING = "loading_stage_connecting"
    LOADING_STAGE_LOADING = "loading_stage_loading"
    LOADING_STAGE_VERIFYING = "loading_stage_verifying"
    # section labels keyed by config attribute
    SETTINGS_SECTIONS = {
        "features": "settings_sec_features",
        "downloads": "settings_sec_downloads",
        "processing": "settings_sec_processing",
        "rename": "settings_sec_rename",
        "metadata": "settings_sec_metadata",
        "thumbnail": "settings_sec_thumbnail",
        "watermark": "settings_sec_watermark",
        "branding": "settings_sec_branding",
        "distribution": "settings_sec_distribution",
        "queue": "settings_sec_queue",
        "security": "settings_sec_security",
        "storage_channel": "settings_sec_storage_channel",
        "log_channel": "settings_sec_log_channel",
        "main_channel": "settings_sec_main_channel",
        "index_channel": "settings_sec_index_channel",
        "acquisition": "settings_sec_acquisition",
        "access": "settings_sec_access",
        "shortlink": "settings_sec_shortlink",
        "sources": "settings_sec_sources",
        "ui": "settings_sec_ui",
    }

    # ── errors / notices ──
    ERR_GENERIC = "error_generic"
    ERR_NOT_FOUND = "error_not_found"
    RATE_LIMITED = "rate_limited"
    ACCESS_DENIED = "access_denied"
    OWNER_ONLY = "owner_only"

    # ── notifications ──
    NOTIF_READY_TITLE = "notif_ready_title"
    NOTIF_READY_BODY = "notif_ready_body"
