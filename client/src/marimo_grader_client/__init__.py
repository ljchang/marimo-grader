"""marimo-grader-client: notebook-side widgets for the dartbrains grader.

Typical assignment cell::

    from marimo_grader_client import Grader

    grader = Grader()            # reads server/version ids from the notebook
    grader.signin_button()       # once per notebook
    grader.submit_button("q03")  # one per question

Every network call happens in the browser (see :mod:`marimo_grader_client.widget`);
the kernel only reads the notebook file and assembles the payload.
"""

from __future__ import annotations

import html as _html
import os
from collections.abc import Callable, Sequence
from typing import Any

from marimo_grader_client.notebook import (
    build_payload,
    client_info,
    collect_check_results,
    env_metadata,
    read_assignment_metadata,
    read_notebook_source,
)
from marimo_grader_client.widget import GraderWidget

__version__ = "0.1.2"

__all__ = [
    "Grader",
    "GraderWidget",
    "check",
    "__version__",
    "build_payload",
    "collect_check_results",
    "read_assignment_metadata",
    "read_notebook_source",
]

Check = tuple[bool, str] | tuple[bool, str, int | float]

_KIND_STYLES = {
    "success": ("#1a7f4b", "rgba(26,127,75,.10)"),
    "danger": ("#b3261e", "rgba(179,38,30,.10)"),
    "warn": ("#9a6700", "rgba(154,103,0,.12)"),
    "info": ("#1d5fbf", "rgba(29,95,191,.10)"),
}


class _Html:
    """Minimal stand-in for ``marimo.Html`` when marimo is not importable."""

    def __init__(self, text: str) -> None:
        self.text = text

    def _repr_html_(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"<Html {self.text[:60]!r}>"


def _wrap_html(text: str) -> Any:
    try:
        import marimo as mo

        return mo.Html(text)
    except Exception:  # noqa: BLE001 - marimo absent or not usable here
        return _Html(text)


def _mograder_check() -> Callable[..., Any] | None:
    """Return ``mograder.runtime.check`` if the optional dependency works."""
    try:
        from mograder.runtime import check as mg_check
    except Exception:  # noqa: BLE001 - not installed, or marimo missing underneath it
        return None
    return mg_check


def _summarize(label: str, conditions: Sequence[Check]) -> dict[str, Any]:
    """Compute a MoGrader-sidecar-shaped record from check tuples."""
    if not conditions:
        return {
            "label": label,
            "status": "warn",
            "details": [],
            "earned_weight": 0.0,
            "total_weight": 0.0,
        }
    failures: list[str] = []
    earned = 0.0
    total = 0.0
    for item in conditions:
        ok, msg = bool(item[0]), str(item[1])
        weight = float(item[2]) if len(item) > 2 else 1.0
        total += weight
        if ok:
            earned += weight
        else:
            failures.append(msg)
    if not failures:
        status = "success"
    elif earned > 0:
        status = "partial"
    else:
        status = "danger"
    return {
        "label": label,
        "status": status,
        "details": failures,
        "earned_weight": earned,
        "total_weight": total,
    }


def render_check_html(record: dict[str, Any]) -> str:
    """A marimo-callout-like block for a check record (no dependencies)."""
    status = record.get("status", "warn")
    kind = {"success": "success", "danger": "danger", "partial": "info"}.get(status, "warn")
    fg, bg = _KIND_STYLES[kind]
    label = _html.escape(str(record.get("label", "")))
    if status == "warn":
        body = f"<strong>{label}</strong> - waiting for your code"
    elif status == "success":
        body = f"<strong>{label}</strong> - all checks passed"
    else:
        items = "".join(f"<li>{_html.escape(str(d))}</li>" for d in record.get("details", []))
        body = f"<strong>{label}</strong> - some checks failed:<ul style='margin:.4em 0 0 1.2em'>{items}</ul>"
    return (
        f'<div class="grader-check grader-check-{kind}" style="border:1px solid {fg};'
        f"border-left-width:4px;background:{bg};border-radius:6px;padding:.6rem .9rem;"
        f'margin:.25rem 0;line-height:1.5">{body}</div>'
    )


def _run_check(label: str, conditions: Sequence[Check], record: dict[str, Any], kw: dict) -> Any:
    mg = _mograder_check()
    if mg is not None:
        try:
            return mg(label, list(conditions), **kw)
        except TypeError:
            return mg(label, list(conditions))
    return _wrap_html(render_check_html(record))


def check(label: str, conditions: Sequence[Check], **kw: Any) -> Any:
    """Module-level ``check`` with the same signature as ``mograder.runtime.check``.

    Prefers MoGrader when installed (so its sidecar and marks badges keep
    working); otherwise renders a local callout. Results are not recorded;
    use :meth:`Grader.check` for that.
    """
    return _run_check(label, conditions, _summarize(label, conditions), kw)


def _first(*values: Any) -> Any:
    for v in values:
        if v not in (None, ""):
            return v
    return None


def _placeholder(label: str) -> Any:
    html = (
        '<span style="display:inline-block;padding:.3em .8em;border:1px dashed #9AA69C;'
        'border-radius:4px;color:#5A645E;font-size:.9em">'
        f"{_html.escape(label)} (control hidden in rendered view)</span>"
    )
    try:
        import marimo as mo

        return mo.Html(html)
    except ImportError:  # pragma: no cover
        return _Html(html)


class Grader:
    """Assignment context plus factories for the three widgets.

    Arguments resolve in this order: explicit argument, notebook PEP 723
    metadata (``[tool.grader]`` or ``grader-*`` keys), then environment
    variables ``GRADER_SERVER``, ``GRADER_ASSIGNMENT_VERSION_ID``,
    ``GRADER_OFFERING_ID`` and ``GRADER_ASSIGNMENT_ID``.
    """

    def __init__(
        self,
        server: str | None = None,
        assignment_version_id: str | None = None,
        offering_id: str | None = None,
        assignment_id: str | None = None,
        *,
        source: str | None = None,
        notebook_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._notebook_path = notebook_path
        self._explicit_source = source is not None
        self._source = source if source is not None else read_notebook_source(notebook_path)
        self.metadata = read_assignment_metadata(self._source)
        env = env_metadata()

        def resolve(arg: str | None, key: str) -> str:
            return str(_first(arg, self.metadata.get(key), env.get(key)) or "")

        self.server = resolve(server, "server").rstrip("/")
        self.assignment_version_id = resolve(assignment_version_id, "assignment_version_id")
        self.offering_id = resolve(offering_id, "offering_id")
        self.assignment_id = resolve(assignment_id, "assignment_id")
        self._checks: dict[str, dict[str, Any]] = {}

    # -- checks ------------------------------------------------------------

    def check(self, label: str, conditions: Sequence[Check], **kw: Any) -> Any:
        """Run checks, record the outcome for later submission, render a callout."""
        record = _summarize(label, conditions)
        qid = kw.pop("question_id", None)
        if qid:
            record["question_id"] = str(qid)
        self._checks[label] = record
        return _run_check(label, conditions, record, kw)

    def check_results(self) -> list[dict[str, Any]]:
        """Recorded checks from this instance plus MoGrader's sidecar, if any."""
        merged: dict[str, dict[str, Any]] = {}
        for rec in collect_check_results():
            merged[str(rec.get("label", ""))] = rec
        merged.update(self._checks)
        return list(merged.values())

    # -- payload -----------------------------------------------------------

    def read_source(self) -> str | None:
        """Re-read the notebook from disk (falls back to the source seen at init).

        An explicit ``source=`` passed to the constructor is authoritative and
        is never replaced by a disk read.
        """
        if self._explicit_source:
            return self._source
        fresh = read_notebook_source(self._notebook_path)
        if fresh is not None:
            self._source = fresh
        return self._source

    def build_payload(self, outputs: dict[str, Any] | None = None) -> dict[str, Any]:
        return build_payload(
            self.read_source(), self.check_results(), outputs, client_info(__version__)
        )

    # -- widgets -----------------------------------------------------------

    def _widget(self, mode: str, **traits: Any) -> Any:
        if os.environ.get("GRADER_RENDER"):
            # The grader worker renders submissions to static HTML for the grading
            # view; interactive sign-in / submit controls make no sense there.
            label = {
                "signin": "Sign in",
                "submit": f"Submit {traits.get('question_id', '')}",
                "feedback": "Feedback",
            }.get(mode, mode)
            return _placeholder(label.strip())
        return GraderWidget(
            mode=mode,
            server=self.server,
            assignment_version_id=self.assignment_version_id,
            offering_id=self.offering_id,
            assignment_id=self.assignment_id,
            **traits,
        )

    def signin_button(self) -> Any:
        """A "Sign in with Dartmouth" button (device handshake; token stays in the browser)."""
        return self._widget("signin", payload={"client": client_info(__version__)})

    def submit_button(self, question_id: str, outputs: dict[str, Any] | None = None) -> Any:
        """A "Submit <question_id>" button. The payload is rebuilt when clicked."""
        outputs = dict(outputs or {})
        return self._widget(
            "submit",
            question_id=question_id,
            payload=self.build_payload(outputs),
            payload_factory=lambda: self.build_payload(outputs),
        )

    def feedback(self, question_id: str) -> Any:
        """Show the latest attempt (score and feedback) for a question."""
        return self._widget("feedback", question_id=question_id)

    def __repr__(self) -> str:
        return (
            f"Grader(server={self.server!r}, assignment_version_id={self.assignment_version_id!r}, "
            f"offering_id={self.offering_id!r}, assignment_id={self.assignment_id!r})"
        )
