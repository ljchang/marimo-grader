"""Per-assignment Python environments and safe subprocess execution for the worker.

Why this exists: student code runs inside bubblewrap with the filesystem
read-only and no network. Package installation therefore has to happen
*before* entering the sandbox. We build one venv per distinct dependency list
(the notebook's PEP 723 block after ``rewrite_dependencies``) under
``GRADER_SANDBOX_DIR`` and reuse it for every submission of that assignment.
MoGrader's ``create_shared_sandbox`` does the install; the venv is then passed
to its runner, which executes marimo with ``--no-sandbox`` so uv is never
invoked inside bubblewrap.
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
from pathlib import Path

from grader.config import get_settings

_DEPS_RE = re.compile(r"^# dependencies\s*=\s*\[(?P<items>.*?)\]", re.M | re.S)
_PY_RE = re.compile(r'^# requires-python\s*=\s*"([^"]*)"', re.M)


def sandbox_root() -> Path:
    root = os.environ.get("GRADER_SANDBOX_DIR")
    if root:
        return Path(root)
    return Path(get_settings().artifact_dir).parent / "sandboxes"


def env_key(notebook_text: str) -> str:
    """Stable key for a notebook's environment: its dependency list and Python constraint."""
    m = _DEPS_RE.search(notebook_text)
    deps = sorted(
        s.strip().strip('"').strip("'")
        for s in (m.group("items") if m else "").replace("\n", " ").replace("#", " ").split(",")
        if s.strip()
    )
    py = _PY_RE.search(notebook_text)
    raw = "\n".join(deps) + "\n" + (py.group(1) if py else "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def prepare_env(notebook_text: str) -> Path | None:
    """Return the venv directory for this notebook's dependencies, building it if needed.

    Returns ``None`` when the notebook declares no inline dependencies; callers
    then fall back to the worker's own interpreter.
    """
    if not _DEPS_RE.search(notebook_text):
        return None
    from mograder.grading.runner import _venv_python, create_shared_sandbox

    d = sandbox_root() / env_key(notebook_text)
    d.mkdir(parents=True, exist_ok=True)
    stub = d / "env.py"
    # The stub only carries the PEP 723 block; that is all create_shared_sandbox reads.
    header_end = notebook_text.find("# ///", notebook_text.find("# /// script") + 1)
    if header_end == -1:
        return None
    stub.write_text(notebook_text[: header_end + len("# ///")] + "\n")
    venv = d / ".venv"
    if _venv_python(venv).exists() and (venv / ".ready").exists():
        return venv
    built = create_shared_sandbox(stub)
    if built is None:
        raise RuntimeError("could not build the notebook environment (uv install failed)")
    (built / ".ready").write_text(env_key(notebook_text))
    return built


def run_with_timeout(
    cmd: list[str], *, timeout: int, env: dict | None = None, cwd: str | Path | None = None
) -> subprocess.CompletedProcess:
    """``subprocess.run`` that kills the whole process group on timeout.

    ``marimo export --sandbox`` and uv spawn grandchildren that keep the output
    pipes open; a plain ``subprocess.run(timeout=...)`` kills only the direct
    child and then blocks forever in ``communicate``. A new session lets us kill
    the group.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:  # pragma: no cover
            pass
        out, err = proc.communicate()
        raise RuntimeError(f"timed out after {timeout}s: {' '.join(cmd[:4])} ...") from None
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
