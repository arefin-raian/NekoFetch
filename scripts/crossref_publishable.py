"""Cross-reference anime entries against channel verification results.

Outputs a filtered list of entries that have active download channels,
marked as publishable, plus a list of entries to skip (banned channels).

Usage:
    python scripts/crossref_publishable.py
"""

import json
import os
import re

EXPORT_PATH = os.path.expanduser("~/Documents/old_main_export.json")
VERIFY_PATH = os.path.expanduser("~/Documents/channel_verification_v2.json")
OUTPUT_PATH = os.path.expanduser("~/Documents/publishable_entries.json")


def extract_channel_ref(url: str) -> str | None:
    m = re.match(r"https?://t\.me/(.+)", url)
    if not m:
        return None
    path = m.group(1).split("/")
    if not path:
        return None
    if path[0] == "ani_weebs_index":
        return None
    return path[0]


def extract_title(caption: str) -> str:
    first_line = caption.split("\n")[0] if "\n" in caption else caption[:100]
    if "『" in first_line:
        return first_line.split("『")[0].strip()
    return first_line.strip()


def main():
    with open(EXPORT_PATH, encoding="utf-8") as f:
        export = json.load(f)
    with open(VERIFY_PATH, encoding="utf-8") as f:
        verify = json.load(f)

    results = verify.get("results", {})
    entries = export.get("entries", [])

    publishable = []
    skipped = []

    for e in entries:
        caption = e.get("caption", "")
        btns = e.get("buttons", [])
        title = extract_title(caption)
        btn_texts = [b.get("text", "").upper() for b in btns]
        has_index = any("INDEX" in b for b in btn_texts)
        has_download = any("DOWNLOAD" in b for b in btn_texts)
        has_watch = any("WATCH" in b for b in btn_texts)

        if not (has_index and has_download):
            reason = "movie_post" if has_watch else "non_anime_post"
            skipped.append({"id": e["id"], "title": title, "skip_reason": reason})
            continue

        download_channels = []
        all_active = True
        for b in btns:
            url = b.get("url", "")
            ref = extract_channel_ref(url)
            if ref:
                status = results.get(ref, {}).get("status", "unknown")
                download_channels.append({"text": b["text"], "url": url, "channel": ref, "status": status})
                if status != "active":
                    all_active = False

        entry = {
            "id": e["id"],
            "title": title,
            "old_link": e.get("old_link", ""),
            "caption": caption,
            "photo": e.get("photo"),
            "download_channels": download_channels,
        }

        if all_active and download_channels:
            entry["publishable"] = True
            publishable.append(entry)
        else:
            entry["publishable"] = False
            skipped.append({"id": e["id"], "title": title, "skip_reason": "banned_channel"})

    output = {
        "total_publishable": len(publishable),
        "total_skipped": len(skipped),
        "publishable_entries": publishable,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Publishable: {len(publishable)}")
    print(f"Skipped: {len(skipped)}")
    print()
    print("=== PUBLISHABLE ===")
    for i, e in enumerate(publishable):
        ch = ", ".join(c["channel"] for c in e["download_channels"])
        print(f"  {i+1:2d}. {e['title']} -> {ch}")
    print()
    print("=== SKIPPED ===")
    for e in skipped:
        print(f"  {e['title']} ({e['skip_reason']})")
    print(f"\nSaved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
