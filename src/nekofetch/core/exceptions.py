"""Domain and infrastructure exceptions.

A single hierarchy lets handlers distinguish expected, user-facing failures
(`NekoFetchError`) from unexpected ones, and map them to localized messages.
"""

from __future__ import annotations


class NekoFetchError(Exception):
    """Base class for all expected, handled errors.

    `message_key` is a localization key resolved by the i18n layer when the
    error is surfaced to a user.
    """

    message_key: str = "error_generic"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.__class__.__name__)
        self.detail = detail


class ConfigError(NekoFetchError):
    """Invalid or missing configuration."""


class PermissionDenied(NekoFetchError):
    message_key = "access_denied"


class RateLimited(NekoFetchError):
    message_key = "rate_limited"


class NotFound(NekoFetchError):
    """A requested entity does not exist."""


class SourceError(NekoFetchError):
    """A content source failed (search/details/download)."""


class DownloadError(SourceError):
    """A download failed and could not be recovered."""


class ProcessingError(NekoFetchError):
    """A processing-pipeline stage failed."""


class LinkExpired(NekoFetchError):
    message_key = "link_expired"


class FeatureDisabled(NekoFetchError):
    """A feature toggled off in configuration was invoked."""
