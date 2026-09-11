"""Prepare a submitted notebook for execution in the worker.

Student notebooks carry a PEP 723 block whose ``dependencies`` name the
packages a MoLab/WASM session installs, including ``grader-client`` and
``mograder``. The worker executes with ``uv run --isolated`` (via marimo's
``--sandbox`` and MoGrader's runner), which resolves that list from an index.
Two adjustments are needed before that works:

* ``grader-client`` may not be on an index yet (or the worker should use the
  exact version it ships with). ``GRADER_CLIENT_REQUIREMENT`` overrides the
  requirement string, e.g. ``grader-client @ file:///app/client`` in the
  container or a local path in development.
* ``mograder`` is pinned to the worker's own version so the checks that run
  during grading match the engine that scores them.

Everything else in the block is left untouched, so the assignment's real
dependencies (numpy, nilearn, ...) still come from the notebook itself.
"""

from __future__ import annotations

import os
import re
from importlib import metadata

_BLOCK = re.compile(r"^# /// script\s*$(?P<body>.*?)^# ///\s*$", re.M | re.S)
_DEPS = re.compile(r"^# dependencies\s*=\s*\[(?P<items>.*?)\]", re.M | re.S)
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _client_requirement() -> str:
    return os.environ.get("GRADER_CLIENT_REQUIREMENT") or "grader-client"


def _mograder_requirement() -> str:
    try:
        return f"mograder=={metadata.version('mograder')}"
    except metadata.PackageNotFoundError:  # pragma: no cover
        return "mograder"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def rewrite_dependencies(source: str) -> str:
    """Return ``source`` with the worker's requirement strings for grader-client and mograder."""
    m = _BLOCK.search(source)
    if not m:
        return source
    body = m.group("body")
    dm = _DEPS.search(body)
    if not dm:
        return source
    items = [
        s.strip().strip('"').strip("'")
        for s in dm.group("items").replace("\n", " ").replace("#", " ").split(",")
    ]
    items = [s for s in items if s]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        nm = _NAME.match(item)
        key = _normalize(nm.group(1)) if nm else item
        if key == "grader-client":
            item = _client_requirement()
        elif key == "mograder":
            item = _mograder_requirement()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    if "grader-client" not in seen:
        out.append(_client_requirement())
    if "mograder" not in seen:
        out.append(_mograder_requirement())
    new_deps = "# dependencies = [" + ", ".join(f'"{d}"' for d in out) + "]"
    new_body = body[: dm.start()] + new_deps + body[dm.end() :]
    return source[: m.start("body")] + new_body + source[m.end("body") :]
