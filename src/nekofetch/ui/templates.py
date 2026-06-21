"""Template engine for messages, captions, and file names.

Templates are ``str.format``-style strings with ``{variable}`` placeholders. They are
stored in config / MongoDB and rendered with a context dict. Unknown placeholders are
left intact rather than raising, so an admin's typo never crashes a flow.

Used for: message bodies, captions, descriptions, and the file-rename template
(variables: {title} {season} {episode} {resolution} {audio} {source} {group}).
"""

from __future__ import annotations

import string


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # leave unknown placeholders untouched
        return "{" + key + "}"


def render(template: str, **context) -> str:
    return string.Formatter().vformat(template, (), _SafeDict(**context))


def render_filename(template: str, **context) -> str:
    """Render a rename template and strip characters illegal in file names."""
    name = render(template, **context)
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "")
    return " ".join(name.split())  # collapse whitespace
