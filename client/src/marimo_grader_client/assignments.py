"""A card that links a chapter to its assignment on the grader."""

from __future__ import annotations

import os


def assignment_card(
    slug: str,
    *,
    title: str | None = None,
    server: str | None = None,
    course: str | None = None,
    term: str | None = None,
):
    """A card linking to this chapter's assignment on the grader.

    The assignment lives on the grader, not in the chapter: one link opens
    it in molab (the grader hands molab the version it currently publishes),
    the other downloads the same notebook for a laptop. Where it lives comes
    from the chapter's ``[tool.grader]`` block (written by marimo-book's
    ``sync-deps``), so a new term never touches the chapter. On the static
    site the page's own assignment drawer already does this; the card is for
    molab and local runs.
    """

    import marimo as mo

    from .storage import _notebook

    if os.environ.get("GRADER_RENDER"):
        # The static site: the page's own assignment drawer already carries
        # these links, so the card would be a duplicate there.
        return mo.Html("")

    try:
        server = _notebook.resolve_server(server)
    except _notebook.NoServer:
        return mo.md(f"*Assignment `{slug}`: no grader server is configured for this notebook.*")
    course = course or _notebook.resolve_course()
    term = term or _notebook.resolve_term()
    if not course or not term:
        return mo.md(
            f"*Assignment `{slug}`: this notebook does not say which course and term it belongs "
            "to (no `[tool.grader]` in its script block), so the assignment link cannot be built.*"
        )
    base = f"{server}/a/{course}/{term}/{slug}"
    name = title or slug.replace("-", " ").replace("_", " ").title()
    return mo.Html(
        '<div style="border:1px solid var(--border-color,#ddd);border-radius:8px;'
        'padding:0.9rem 1.1rem;margin:0.5rem 0">'
        f'<div style="font-weight:600;margin-bottom:0.35rem">Assignment: {name}</div>'
        '<div style="display:flex;gap:0.6rem;flex-wrap:wrap;align-items:center">'
        f'<a href="{base}/molab" target="_blank" rel="noopener" '
        'style="display:inline-block;padding:0.35rem 0.8rem;border-radius:6px;'
        'background:#00693E;color:#fff;text-decoration:none">Open in molab</a>'
        f'<a href="{base}/student.py" target="_blank" rel="noopener">Download the notebook</a>'
        '<span style="opacity:0.7">Sign in with Dartmouth inside it to submit.</span>'
        "</div></div>"
    )
