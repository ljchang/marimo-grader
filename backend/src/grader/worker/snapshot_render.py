"""Render a submitted notebook from the student's own outputs, without running it.

marimo keeps every cell's last outputs in ``__marimo__/session/<notebook>.py.json``,
each tagged with a hash of the code that produced them. Matching those hashes to
the submitted notebook's cells and handing the result to marimo's HTML exporter
gives the page ``marimo export html`` would make, minus the execution: seconds
instead of the 15 minutes a heavy analysis takes, and exactly what the student
saw. A cell whose code changed after its outputs were saved shows its code and
no output, so nothing stale is passed off as current.

Nothing here executes the notebook: ``load_notebook`` parses it statically. It
still runs in a subprocess (``python -m grader.worker.snapshot_render``) so a
malformed file cannot take the worker down with it::

    python -m grader.worker.snapshot_render notebook.py session.json -o out.html

prints ``{"matched": n, "total": m}``.

These are marimo internals, checked against the version the worker pins
(``marimo==0.25.2`` in pyproject.toml); bump them together.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def render(notebook: Path, session: dict) -> tuple[str, int, int]:
    """``(html, cells with outputs, cells)`` for ``notebook`` and a parsed session."""
    from marimo._config.manager import get_default_config_manager
    from marimo._export.exporter import Exporter
    from marimo._export.file import _resolve_and_inline_layout
    from marimo._export.requests import HTMLExportRequest
    from marimo._export.serialization import serialize_notebook_snapshot
    from marimo._schemas.export_options import HTMLExportOptions
    from marimo._session.notebook import load_notebook
    from marimo._session.state.serialize import _hash_code, deserialize_session

    file_manager = load_notebook(str(notebook.resolve()))
    cells = list(file_manager.app.cell_manager.cell_data())
    by_hash, session = _pair_by_occurrence(
        [(_hash_code(c.code), c.cell_id) for c in cells], session
    )
    view = deserialize_session(session, by_hash)
    for c in cells:  # code for every cell; outputs only where the hash matched
        view.last_executed_code[c.cell_id] = c.code

    display = get_default_config_manager(current_path=file_manager.path).get_config()["display"]
    html, _ = Exporter().export_as_html(
        HTMLExportRequest(
            filename=file_manager.filename,
            app_code=file_manager.app.to_py(),
            app_config=file_manager.app.config,
            snapshot=serialize_notebook_snapshot(
                file_manager.app,
                view,
                drop_virtual_file_outputs=False,
                include_model_notifications=True,
            ),
            display_config=display,
            options=HTMLExportOptions(files=(), include_code=True),
            layout=_resolve_and_inline_layout(file_manager.app),
            sharing_config=None,
        )
    )
    # Empty cells have nothing to show; counting them would read as lost outputs.
    with_code = [c for c in cells if c.code.strip()]
    matched = sum(1 for c in with_code if c.cell_id in view.cell_notifications)
    return html, matched, len(with_code)


def _pair_by_occurrence(cells: list[tuple[str, str]], session: dict) -> tuple[dict[str, str], dict]:
    """A code-hash map that keeps cells with identical code apart.

    marimo matches outputs to cells by code hash alone, so two cells with the same
    code (``df.head()`` twice, or blank cells) collapse onto one: the first loses
    its output and the last shows whichever ran last. Suffixing each hash with its
    occurrence number, in document order on both sides, pairs the n-th such cell
    with the n-th such output instead.
    """
    seen: dict[str, int] = {}
    by_key: dict[str, str] = {}
    for h, cell_id in cells:
        by_key[f"{h}#{seen.get(h, 0)}"] = cell_id
        seen[h] = seen.get(h, 0) + 1
    seen = {}
    out_cells = []
    for cell in session.get("cells", []):
        h = cell.get("code_hash")
        if h is not None:
            cell = {**cell, "code_hash": f"{h}#{seen.get(h, 0)}"}
            seen[h] = seen.get(h, 0) + 1
        out_cells.append(cell)
    return by_key, {**session, "cells": out_cells}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m grader.worker.snapshot_render")
    ap.add_argument("notebook", type=Path)
    ap.add_argument("session", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    a = ap.parse_args(argv)
    html, matched, total = render(a.notebook, json.loads(a.session.read_text()))
    a.output.write_text(html)
    json.dump({"matched": matched, "total": total}, sys.stdout)


if __name__ == "__main__":
    main()
