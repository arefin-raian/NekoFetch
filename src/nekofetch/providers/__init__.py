"""Pluggable provider layers.

``providers.metadata`` is the isolated metadata/enrichment seam: implement scraping in a
single file (``metadata/scraper.py``) and the rest of the application consumes the typed
output automatically. See ``docs/SCRAPER_GUIDE.md``.
"""
