"""Which grader, offering, course and term the running notebook belongs to.

Resolution order for each value: an explicit argument, the environment
(``GRADER_SERVER``, ``GRADER_OFFERING_ID``, ``GRADER_COURSE``, ``GRADER_TERM``),
the notebook's PEP 723 block (``grader-*`` keys or ``[tool.grader]`` -- the
same reader ``Grader()`` uses), then ``storage.configure()`` defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

from marimo_grader_client.notebook import notebook_path as _client_notebook_path
from marimo_grader_client.notebook import read_assignment_metadata, read_notebook_source


class NoServer(RuntimeError):
    pass


def notebook_path() -> Path | None:
    return _client_notebook_path()


def notebook_source() -> str | None:
    return read_notebook_source()


def script_metadata(source: str | None = None) -> dict[str, str]:
    """``server``, ``offering_id``, ``course``, ``term`` from the block, when present."""
    meta = read_assignment_metadata(source if source is not None else notebook_source())
    return {k: str(v) for k, v in meta.items() if k in ("server", "offering_id", "course", "term")}


def _resolve(explicit: str | None, env: str, key: str) -> str | None:
    from . import _state

    return explicit or os.environ.get(env) or script_metadata().get(key) or _state.DEFAULTS.get(key)


def resolve_server(explicit: str | None = None) -> str:
    server = _resolve(explicit, "GRADER_SERVER", "server")
    if not server:
        raise NoServer(
            "no grader server: set grader-server (or [tool.grader] server) in the notebook's "
            "script block, GRADER_SERVER in the environment, or storage.configure(server=...)"
        )
    return server.rstrip("/")


def resolve_offering(explicit: str | None = None) -> str | None:
    return _resolve(explicit, "GRADER_OFFERING_ID", "offering_id")


def resolve_course(explicit: str | None = None) -> str | None:
    return _resolve(explicit, "GRADER_COURSE", "course")


def resolve_term(explicit: str | None = None) -> str | None:
    return _resolve(explicit, "GRADER_TERM", "term")
