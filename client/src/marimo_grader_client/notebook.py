"""Notebook-side helpers: locate the running notebook, read its PEP 723
metadata, gather MoGrader check results and assemble a submission payload.

Nothing in this module touches the network. All values are best effort and
degrade to ``None`` / empty containers when the environment does not expose
them (for example a WASM kernel without a readable file system).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

# Keys the grader client understands, in normalized (snake_case) form.
GRADER_KEYS = ("assignment_version_id", "offering_id", "assignment_id", "server")

# MoGrader injects these into the ``# /// script`` block of student notebooks.
MOGRADER_KEYS = (
    "mograder_assignment",
    "mograder_cell_hashes",
    "mograder_hidden_tests",
    "mograder_type",
)

_ENV_VARS = {
    "assignment_version_id": "GRADER_ASSIGNMENT_VERSION_ID",
    "offering_id": "GRADER_OFFERING_ID",
    "assignment_id": "GRADER_ASSIGNMENT_ID",
    "server": "GRADER_SERVER",
}

_KEY_ALIASES = {
    "assignment_version": "assignment_version_id",
    "assignment_version_id": "assignment_version_id",
    "version_id": "assignment_version_id",
    "offering": "offering_id",
    "offering_id": "offering_id",
    "assignment": "assignment_id",
    "assignment_id": "assignment_id",
    "server": "server",
    "url": "server",
}

_SCRIPT_OPEN = "# /// script"
_SCRIPT_CLOSE = "# ///"
_LINE_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+?)\s*$")


# --------------------------------------------------------------------------
# Locating the notebook source
# --------------------------------------------------------------------------


def _read_text(path: Any) -> str | None:
    try:
        p = Path(str(path))
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - any failure means "not readable"
        pass
    return None


def _marimo_filename() -> str | None:
    """Best-effort file name of the running marimo notebook (None outside marimo)."""
    try:
        from marimo._runtime.context import get_context

        name = getattr(get_context(), "filename", None)
        return str(name) if name else None
    except Exception:  # noqa: BLE001
        return None


def notebook_path() -> Path | None:
    """Return the path of the running notebook if it can be determined."""
    candidates: list[Any] = []
    env = os.environ.get("GRADER_NOTEBOOK_PATH")
    if env:
        candidates.append(env)
    try:
        import __main__

        candidates.append(getattr(__main__, "__file__", None))
    except Exception:  # noqa: BLE001
        pass
    candidates.append(_marimo_filename())

    dirs: list[Any] = []
    try:
        import marimo

        for fn in ("notebook_location", "notebook_dir"):
            f = getattr(marimo, fn, None)
            if f is not None:
                try:
                    dirs.append(f())
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass

    for c in candidates:
        if not c:
            continue
        p = Path(str(c))
        if p.is_file():
            return p
        # A bare file name: resolve it against the marimo notebook directory.
        for d in dirs:
            if d is None:
                continue
            try:
                q = Path(str(d)) / p.name
                if q.is_file():
                    return q
            except Exception:  # noqa: BLE001
                continue
    for d in dirs:
        if d is None:
            continue
        try:
            q = Path(str(d))
            if q.is_file():
                return q
        except Exception:  # noqa: BLE001
            continue
    return None


def read_notebook_source(path: str | os.PathLike[str] | None = None) -> str | None:
    """Read the source of the running notebook.

    Tries, in order: an explicit ``path``, ``$GRADER_NOTEBOOK_PATH``,
    ``__main__.__file__``, the marimo runtime's file name, and
    ``marimo.notebook_location()`` / ``marimo.notebook_dir()``. Returns
    ``None`` when nothing is readable (e.g. in a WASM kernel).
    """
    if path is not None:
        return _read_text(path)
    p = notebook_path()
    return _read_text(p) if p is not None else None


# --------------------------------------------------------------------------
# PEP 723 metadata
# --------------------------------------------------------------------------


def script_block(source: str) -> str | None:
    """Return the body of the first ``# /// script`` block with comment
    prefixes removed, or ``None`` if the source has no such block."""
    lines: list[str] = []
    inside = False
    for raw in source.splitlines():
        stripped = raw.strip()
        if not inside:
            if stripped == _SCRIPT_OPEN:
                inside = True
            continue
        if stripped == _SCRIPT_CLOSE:
            return "\n".join(lines) + "\n"
        if stripped.startswith("#"):
            lines.append(stripped[1:].removeprefix(" "))
        else:
            # A non-comment line ends the block early (malformed but tolerated).
            break
    return "\n".join(lines) + "\n" if inside else None


def _scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _parse_block_loosely(body: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Line-by-line fallback used when the block is not valid TOML.

    Returns ``(top_level, tool_grader)``.
    """
    top: dict[str, Any] = {}
    grader: dict[str, Any] = {}
    section: dict[str, Any] | None = top
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("["):
            name = line.strip("[] ").strip()
            section = grader if name == "tool.grader" else None
            continue
        if section is None:
            continue
        m = _LINE_RE.match(line)
        if m:
            section[m.group(1)] = _scalar(m.group(2))
    return top, grader


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def read_assignment_metadata(source: str | None) -> dict[str, Any]:
    """Parse assignment metadata from a notebook's PEP 723 block.

    Two spellings are accepted and merged (a ``[tool.grader]`` value wins over
    a top-level comment key)::

        # /// script
        # mograder-assignment = "week03"
        # grader-assignment-version = "1f0e..."
        # grader-offering-id = "..."
        # grader-assignment-id = "..."
        # grader-server = "https://grader.dartbrains.org"
        # ///

    or::

        # /// script
        # [tool.grader]
        # assignment-version = "1f0e..."
        # offering-id = "..."
        # assignment-id = "..."
        # server = "https://grader.dartbrains.org"
        # ///

    The result uses snake_case keys: ``assignment_version_id``,
    ``offering_id``, ``assignment_id``, ``server`` plus any ``mograder_*``
    keys found (``mograder_cell_hashes`` is split into a list).
    """
    out: dict[str, Any] = {}
    if not source:
        return out
    body = script_block(source)
    if body is None:
        return out

    top: dict[str, Any]
    grader: dict[str, Any]
    try:
        parsed = tomllib.loads(body)
        top = {k: v for k, v in parsed.items() if not isinstance(v, dict)}
        tool = parsed.get("tool")
        grader = tool.get("grader", {}) if isinstance(tool, dict) else {}
        if not isinstance(grader, dict):
            grader = {}
    except (tomllib.TOMLDecodeError, ValueError):
        top, grader = _parse_block_loosely(body)

    for key, value in top.items():
        nk = _normalize_key(key)
        if nk.startswith("mograder_"):
            out[nk] = value
        elif nk.startswith("grader_"):
            alias = _KEY_ALIASES.get(nk.removeprefix("grader_"))
            if alias:
                out[alias] = value

    for key, value in grader.items():
        nk = _normalize_key(key).removeprefix("grader_")
        alias = _KEY_ALIASES.get(nk)
        if alias:
            out[alias] = value

    hashes = out.get("mograder_cell_hashes")
    if isinstance(hashes, str):
        out["mograder_cell_hashes"] = [h for h in hashes.split(",") if h]
    for k in GRADER_KEYS:
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = str(out[k])
    return out


def env_metadata() -> dict[str, str]:
    """Grader settings taken from ``GRADER_*`` environment variables."""
    return {k: v for k, var in _ENV_VARS.items() if (v := os.environ.get(var))}


# --------------------------------------------------------------------------
# Check results and payload
# --------------------------------------------------------------------------


def collect_check_results(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """Read MoGrader's JSONL sidecar (``$MOGRADER_SIDECAR_PATH``) if present.

    Each line is a record like ``{"label", "status", "details",
    "earned_weight", "total_weight"}``. Unparseable lines are skipped.
    """
    p = path or os.environ.get("MOGRADER_SIDECAR_PATH")
    if not p:
        return []
    results: list[dict[str, Any]] = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    results.append(rec)
    except OSError:
        return []
    return results


def detect_env() -> str:
    """Rough execution-environment label for the ``client.env`` field."""
    override = os.environ.get("GRADER_ENV")
    if override:
        return override
    if sys.platform == "emscripten":
        return "wasm"
    if os.environ.get("MOLAB") or os.environ.get("MARIMO_MOLAB"):
        return "molab"
    return "local"


def client_info(version: str) -> dict[str, str]:
    return {"package": "marimo-grader-client", "version": version, "env": detect_env()}


def build_payload(
    source: str | None,
    check_results: list[dict[str, Any]] | None = None,
    outputs: dict[str, Any] | None = None,
    client: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the body sent to ``POST /api/v1/submissions`` (minus the
    ``assignment_version_id`` / ``question_id`` fields the widget adds)."""
    return {
        "notebook": source or "",
        "check_results": list(check_results or []),
        "outputs": dict(outputs or {}),
        "client": dict(client or {}),
    }
