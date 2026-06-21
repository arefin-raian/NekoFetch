"""Active metadata-provider selection.

Mirrors the sources registry. To add a second authorized provider later, register it here
and select by name; nothing downstream changes because they all return AnimeTemplateData.
"""

from __future__ import annotations

from nekofetch.providers.metadata.base import MetadataProvider


def build_metadata_provider(name: str = "scraper", **kwargs) -> MetadataProvider:
    from nekofetch.providers.metadata.scraper import ScraperMetadataProvider

    providers: dict[str, type[MetadataProvider]] = {
        ScraperMetadataProvider.name: ScraperMetadataProvider,
    }
    cls = providers.get(name, ScraperMetadataProvider)
    return cls(**kwargs)
