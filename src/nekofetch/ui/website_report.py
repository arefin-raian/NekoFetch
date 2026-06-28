"""Render the Website source report into a confirmation-style caption.

Pure builder (no I/O): takes a :class:`WebsiteReport` and returns HTML. The
analysis lines are produced by the report service (they already contain the
findings); here we frame the tree, per-source coverage, and analysis.
"""

from __future__ import annotations

import html

from nekofetch.core.constants import RULE, TREE_END, TREE_MID
from nekofetch.localization.messages import M, t
from nekofetch.services.website_report import WebsiteReport


def _esc(x: object) -> str:
    return html.escape(str(x if x is not None else ""), quote=False)


def render_report(report: WebsiteReport) -> str:
    rows = [t(M.WEB_REPORT_TITLE, title=_esc(report.title)), f"<i>{RULE}</i>"]
    rows.append(t(M.WEB_REPORT_EXPECTS,
                  eps=report.anilist_episodes or "?", seasons=report.anilist_seasons or "?"))

    # ── download tree (release order), capped + expandable ──
    tree = report.tree[:12]
    if tree:
        lines = [f"<b>{t(M.WEB_REPORT_TREE_TITLE)}</b>"]
        for i, node in enumerate(tree):
            marker = TREE_END if i == len(tree) - 1 else TREE_MID
            reps = node.get("episodes")
            eps = f" · {reps} eps" if reps else ""
            lines.append(t(M.WEB_REPORT_TREE_ROW, marker=marker,
                           title=_esc(node.get("title")),
                           relation=_esc((node.get("relation") or "").replace("_", " ").title()),
                           fmt=_esc(node.get("format") or "?"), eps=eps))
        rows += ["", f"<blockquote expandable>{chr(10).join(lines)}</blockquote>"]

    # ── per-source coverage ──
    rows += ["", t(M.WEB_REPORT_COVERAGE_TITLE)]
    for c in report.coverages:
        if not c.available:
            rows.append(t(M.WEB_REPORT_COV_UNAVAILABLE, source=c.source.title()))
            continue
        rows.append(t(M.WEB_REPORT_COV_ROW, source=c.source.title(),
                      total=c.total_episodes, sub=c.sub_episodes, dub=c.dub_episodes,
                      approx=t(M.WEB_REPORT_APPROX) if c.approximate else ""))

    # ── analysis (lines already carry their own emoji + HTML) ──
    if report.analysis:
        rows += ["", t(M.WEB_REPORT_ANALYSIS_TITLE)]
        rows += report.analysis

    rows += ["", t(M.WEB_REPORT_PICK)]
    return "\n".join(rows)
