"""Back up the student's notebook and its outputs while they work, automatically.

Once a sign-in succeeds (``storage.connect()`` or the sign-in button), one
daemon thread per kernel copies two files to the student's own storage::

    private/<grader-assignment>/.autosave/notebook.py    the notebook source
    private/<grader-assignment>/.autosave/session.json   marimo's session snapshot:
                                                         every cell's last outputs

whenever either changes (checked every ``INTERVAL`` seconds), plus a copy of
both under ``.autosave/history/<UTC stamp>/`` at most every ``HISTORY_EVERY``
seconds, keeping the newest ``KEEP``. The grader renders a submission from the
snapshot when none came with it, and staff never see ``.autosave/`` among a
student's saved files.

It never prompts, never blocks the kernel and never raises into it: a failed
upload is retried on the next check and shows in the sign-in widget. It does
nothing in the grader's own render (``GRADER_RENDER``), in the browser (WASM,
no storage), against a local storage root (the book build, tests), for a
notebook that does not name its assignment (``grader-assignment`` in the PEP 723
block, written by publishing), or with ``GRADER_AUTOSAVE=0``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from marimo_grader_client.notebook import (
    notebook_path,
    read_assignment_metadata,
    session_snapshot_path,
)

INTERVAL = 45.0
HISTORY_EVERY = 600.0
KEEP = 20
DIR = ".autosave"

_current: Autosaver | None = None
_lock = threading.Lock()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(p: Path | None) -> bytes | None:
    try:
        return p.read_bytes() if p is not None else None
    except OSError:
        return None


class Autosaver:
    """Uploads what changed on each :meth:`tick`; :meth:`start` runs ticks in a thread.

    ``mount`` is the student's ``/private`` mount, or a callable that opens it
    (called lazily from the thread, and again after a failure).
    """

    def __init__(
        self,
        mount: Any,
        slug: str,
        notebook: Path,
        snapshot: Path | None = None,
        *,
        interval: float = INTERVAL,
        history_every: float = HISTORY_EVERY,
        keep: int = KEEP,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._open = mount if callable(mount) else (lambda: mount)
        self._mount = None
        self.base = f"{slug.strip('/')}/{DIR}"
        self.notebook = Path(notebook)
        self.snapshot = snapshot
        self.interval = interval
        self.history_every = history_every
        self.keep = keep
        self.clock = clock
        self._uploaded: dict[str, str] = {}
        self._history_at: float | None = None
        self.saved_at: float | None = None
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- one check -----------------------------------------------------------

    def _files(self) -> dict[str, bytes]:
        files = {}
        nb = _read(self.notebook)
        if nb is not None:
            files["notebook.py"] = nb
        snap = _read(self.snapshot)
        if snap is not None:
            try:
                json.loads(snap)
            except ValueError:
                pass  # caught mid-write; the next check gets it
            else:
                files["session.json"] = snap
        return files

    def tick(self) -> bool:
        """Upload whatever changed since the last upload. True if anything was."""
        files = self._files()
        changed = {k: v for k, v in files.items() if self._uploaded.get(k) != _sha(v)}
        if not changed:
            return False
        try:
            if self._mount is None:
                self._mount = self._open()
            m = self._mount
            for name, data in changed.items():
                m.put_bytes(f"{self.base}/{name}", data)
                self._uploaded[name] = _sha(data)
            now = self.clock()
            if self._history_at is None or now - self._history_at >= self.history_every:
                stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
                for name, data in files.items():
                    m.put_bytes(f"{self.base}/history/{stamp}/{name}", data)
                self._history_at = now
                self._prune(m)
        except Exception as e:  # noqa: BLE001 - retried next tick, shown in the widget
            self._mount = None  # e.g. an expired credential: open it again next time
            self.error = f"{type(e).__name__}: {e}"[:200]
            raise
        self.saved_at = now
        self.error = None
        return True

    def _prune(self, m) -> None:
        stamps = sorted(
            {k.split("/history/", 1)[1].split("/", 1)[0] for k in m.ls(self.base + "/history")}
        )
        for stamp in stamps[: max(0, len(stamps) - self.keep)]:
            for k in m.ls(f"{self.base}/history/{stamp}"):
                m.delete(k)

    # -- the thread ----------------------------------------------------------

    def _run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - never let the thread die
                pass
            if self._stop.wait(self.interval):
                return

    def start(self) -> Autosaver:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="marimo-grader-autosave", daemon=True
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        """What the sign-in widget shows: on, last saved (epoch seconds), or the error."""
        return {"on": True, "saved_at": self.saved_at, "error": self.error}


# --------------------------------------------------------------------------
# Starting it from a sign-in
# --------------------------------------------------------------------------


def disabled_reason(nb: Path | None = None) -> str | None:
    """Why autosave would not run here, or ``None`` if it would."""
    from marimo_grader_client.storage import _runtime, _state

    if os.environ.get("GRADER_AUTOSAVE", "").lower() in ("0", "false", "off", "no"):
        return "GRADER_AUTOSAVE is off"
    if os.environ.get("GRADER_RENDER"):
        return "grader render"
    if _runtime.kind() == "wasm":
        return "browser (no storage)"
    if _state.use_local():
        return "local storage root"
    if nb is None:
        return "notebook file not found"
    return None


def _private_mount(token, offering: str | None) -> Callable[[], Any]:
    """Opens ``/private``: the notebook's own storage session when it has one,
    else a session of our own, so autosave never changes ``storage``'s state."""

    def open_private():
        from marimo_grader_client.storage import _auth, _notebook, _runtime, _state
        from marimo_grader_client.storage._broker import Broker
        from marimo_grader_client.storage._session import R2Session

        if _state.connected():
            return _state.session().mount("/private")
        tok = token if token is not None else _auth.load(_notebook.resolve_server(None))
        if tok is None or not tok.valid():
            raise _auth.NotSignedIn("sign in again to keep autosaving")
        b = Broker(
            tok,
            _notebook.resolve_offering(offering),
            course=_notebook.resolve_course(),
            term=_notebook.resolve_term(),
        )
        client = f"marimo-grader-client/{_runtime.kind()}"
        return R2Session(b, b.session(client), client=client).mount("/private")

    return open_private


def start(token=None, *, offering: str | None = None, notebook=None) -> Autosaver | None:
    """Start the kernel's autosave if it is not running; never raises.

    ``token`` is a :class:`storage.Token` (``None``: the cached one).
    """
    global _current
    try:
        with _lock:
            if _current is not None:
                return _current
            nb = Path(notebook) if notebook is not None else notebook_path()
            if disabled_reason(nb) is not None:
                return None
            src = _read(nb)
            meta = read_assignment_metadata(src.decode("utf-8", "replace") if src else None)
            slug = meta.get("assignment_slug")
            if not slug:
                return None  # not a published assignment: nothing to name the folder by
            _current = Autosaver(
                _private_mount(token, offering or meta.get("offering_id")),
                str(slug),
                nb,
                session_snapshot_path(nb),
            ).start()
            return _current
    except Exception:  # noqa: BLE001 - a backup must never break the notebook
        return None


def current() -> Autosaver | None:
    return _current


def status() -> dict[str, Any]:
    return _current.status() if _current is not None else {"on": False}


def _reset_for_tests() -> None:
    global _current
    if _current is not None:
        _current.stop()
    _current = None


__all__ = ["Autosaver", "start", "current", "status", "INTERVAL", "HISTORY_EVERY", "KEEP"]
