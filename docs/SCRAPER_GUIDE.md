# Implementing the Metadata Scraper

NekoFetch isolates all metadata acquisition behind one file. **You implement four
functions in `src/nekofetch/providers/metadata/scraper.py`, flip one flag, and the rest of
the application starts showing rich metadata automatically** — no other file changes.

> **Authorization:** implement these against sources you are authorized to use (an
> official/licensed metadata API, your own database, content you own). The platform ships
> no scraper and points at no third-party site by default.

---

## TL;DR

1. Open `src/nekofetch/providers/metadata/scraper.py`.
2. Implement `fetch_profile_data` (required) and, optionally, `fetch_character_data`,
   `fetch_statistics`, `fetch_assets`.
3. Set `implemented = True`.
4. Done. The bots, caching, transformer, and renderer already consume your output.

Nothing else in the codebase needs editing.

---

## The single file and its functions

`ScraperMetadataProvider` in `scraper.py`. Method names map to your requested names:

| Requested name      | Implement here          | Required | Returns                 |
|---------------------|-------------------------|----------|-------------------------|
| `fetchProfileData`  | `fetch_profile_data`    | ✅ yes   | `RawProfile`            |
| `fetchCharacterData`| `fetch_character_data`  | optional | `list[RawCharacter]`    |
| `fetchStatistics`   | `fetch_statistics`      | optional | `RawStatistics \| None` |
| `fetchAssets`       | `fetch_assets`          | optional | `RawAssets \| None`     |
| `buildTemplateData` | `build_template_data`   | **provided** | `AnimeTemplateData \| None` |

`build_template_data` is already written on the base class — it calls your four fetchers,
handles failures of the optional ones gracefully, and runs the transformer. You should not
need to touch it.

Optional functions you don't support: return `[]` / `None` (don't raise). The card still
renders from whatever is present.

---

## Inputs

Every `fetch_*` receives a single argument:

- **`anime_ref: str`** — a provider-native reference passed through unchanged by
  NekoFetch. You decide what it means for your source: an id, a slug, or a URL. It comes
  from the title being enriched (a request's `source_ref` or the Mongo anime doc id).

A shared `httpx.AsyncClient` is available as `self.http` (lazily created, auto-closed). Set
an optional `base_url` when constructing the provider if your API has one.

---

## Required output structures

Full field docs live in `src/nekofetch/providers/metadata/models.py`. Summary:

```text
RawProfile     title (REQUIRED) · alt_titles[] · synopsis · genres[] · studio
               release_date · status · season_count · episode_count · source_url
RawCharacter   name (REQUIRED) · role · voice_actor · image_url
RawStatistics  score · scored_by · rank · popularity · members · favorites
               status · episode_count            (all optional)
RawAssets      poster_url · banner_url · cover_url · thumbnail_urls[] · trailer_url
```

### Fields the renderer requires

- **Hard requirement:** `RawProfile.title`. If it's missing/empty, enrichment returns
  `None` and the app falls back to basic metadata.
- **Header image:** `RawAssets.banner_url` preferred, else `poster_url`.
- Everything else is included only when present — **partial data renders fine.**

---

## Data flow: scraper → transformer → template → output

```
        scraper.py  (you)                         provided & stable
        ────────────────                          ─────────────────
 anime_ref ─▶ fetch_profile_data ─▶ RawProfile ─┐
          ─▶ fetch_character_data ▶ [RawCharacter]
          ─▶ fetch_statistics ────▶ RawStatistics ├─▶ transformer.build_template_data
          ─▶ fetch_assets ────────▶ RawAssets ────┘            │
                                                               ▼
                                                      AnimeTemplateData   (canonical view model)
                                                               │
                                                renderer.render_anime_info
                                                               ▼
                                                       RenderedAnimeInfo  (caption + image_url)
                                                               │
                          EnrichmentService  (cache to Mongo `anime`, serve)
                                                               │
                               ┌───────────────────────────────┴───────────────┐
                               ▼                                                ▼
                  distribution bot title page                       (any future consumer)
                  (rich card, with graceful fallback)
```

- **Transformer** (`transformer.py`) normalizes Raw models into `AnimeTemplateData`,
  applying fallbacks (e.g. statistics may fill in `status`/`episode_count`).
- **Renderer** (`renderer.py`) turns `AnimeTemplateData` into a Telegram-ready
  `RenderedAnimeInfo` (caption + header image), using the house glyphs and the branding
  footer.
- **EnrichmentService** (`services/enrichment_service.py`) is what the app calls. It caches
  results in MongoDB (`anime` collection, keyed by `anime_ref`) and returns `None` while
  the provider is unimplemented so callers fall back.

---

## Why "no other changes" works

The consumption points already call `EnrichmentService.render_card(anime_ref)`:

- While `implemented = False`, `build_template_data` returns `None`, so `render_card`
  returns `None`, and callers (e.g. the distribution bot's title page) use their existing
  basic-metadata path.
- The moment you implement the fetchers and set `implemented = True`, the same call returns
  a real card and the UI upgrades automatically.

To add another consumer anywhere, just call:

```python
from nekofetch.services.enrichment_service import EnrichmentService

card = await EnrichmentService(container).render_card(anime_ref)
if card:
    await message.reply_photo(card.image_url, caption=card.caption)  # or reply(card.caption)
```

---

## Caching & refresh

Results persist in MongoDB `anime` under `{anime_ref, template_data}`. Force a refresh:

```python
await EnrichmentService(container).get_template_data(anime_ref, force_refresh=True)
```

---

## Adding a second provider later

Implement another `MetadataProvider` subclass, register it in
`providers/metadata/registry.py`, and select it by name. Because every provider returns
`AnimeTemplateData`, the transformer, renderer, service, and bots stay unchanged.
