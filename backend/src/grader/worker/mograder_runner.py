"""Bridge between a submission and MoGrader's grading engine.

MoGrader (``mograder``) is used strictly as a library:

* ``mograder.grading.integrity.check_integrity`` reinjects the instructor's
  ``check()`` and marks cells if the student modified them.
* ``mograder.grading.integrity.inject_hidden_tests`` restores hidden tests.
* ``mograder.grading.runner.run_notebook`` executes the notebook in a sandbox
  (rlimits, wall-clock timeout, optional bubblewrap with no network) and
  parses the JSONL sidecar written by ``check()``.

Question mapping: MoGrader keys every check by the text before the first colon
of its label (``check("glm-q03: Design matrix", ...)`` → ``glm-q03``). A
question's ``check_keys`` lists the keys that count toward it; when empty the
question's ``qid`` is used.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

from sqlalchemy.orm import Session

from grader.models import Artifact, Submission
from grader.services.artifacts import store
from grader.worker.materialize import rewrite_dependencies

TIMEOUT = int(os.environ.get("GRADER_AUTOGRADE_TIMEOUT", "300"))
USE_BWRAP = (
    os.environ.get("GRADER_USE_BUBBLEWRAP", "").lower() in ("1", "true", "yes")
    and shutil.which("bwrap") is not None
)


@dataclass
class GradeResult:
    grader_version: str
    fraction: float  # 0..1 of the auto portion earned
    feedback: str
    checks: list[dict] = field(default_factory=list)
    tampered: list[str] = field(default_factory=list)
    export_ok: bool = True
    export_error: str = ""
    cell_errors: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _key(label: str) -> str:
    return label.split(":", 1)[0].strip()


def grade(db: Session, sub: Submission) -> GradeResult:
    try:
        from mograder.grading import integrity
        from mograder.grading.runner import run_notebook
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("mograder is not installed in the worker image") from e

    version = sub.version
    instructor_art = db.get(Artifact, version.instructor_artifact_id)
    notebook_art = db.get(Artifact, sub.notebook_artifact_id)
    assert instructor_art is not None and notebook_art is not None
    source_text = store().get(instructor_art).decode()
    submitted_text = store().get(notebook_art).decode()

    tampered: list[str] = []
    integ = integrity.check_integrity(source_text, submitted_text)
    tampered += list(integ.tampered_checks)
    if integ.tampered_marks:
        tampered.append("__marks__")
    fixed = integ.fixed_source
    if integrity.has_hidden_tests(source_text):
        fixed, _hidden = integrity.inject_hidden_tests(source_text, fixed)

    with tempfile.TemporaryDirectory(prefix="grader-run-") as td:
        nb = Path(td) / "submission.py"
        nb.write_text(rewrite_dependencies(fixed))
        result = run_notebook(
            nb,
            timeout=TIMEOUT,
            safety_check=True,
            isolate_cwd=True,
            use_bubblewrap=USE_BWRAP,
        )

    if not result.export_ok:
        # The notebook could not run at all: a grader failure to look at, not a zero.
        raise RuntimeError(f"notebook execution failed: {result.export_error[:1500]}")

    q = sub.question
    keys = set(q.check_keys or [q.qid])
    earned = total = 0.0
    lines: list[str] = []
    checks_out: list[dict] = []
    for c in result.checks:
        d = {
            "label": c.label,
            "status": c.status,
            "details": list(c.details),
            "earned": c.earned_weight,
            "total": c.total_weight,
            "hidden": c.hidden,
        }
        checks_out.append(d)
        if _key(c.label) not in keys:
            continue
        tw = c.total_weight or 1.0
        ew = c.earned_weight if c.total_weight else (tw if c.status == "success" else 0.0)
        earned += ew
        total += tw
        mark = "✓" if c.status == "success" else "✗"
        detail = (
            f" — {'; '.join(c.details)}"
            if c.details and c.status != "success" and not c.hidden
            else ""
        )
        lines.append(f"{mark} {c.label}{detail}")

    if result.cell_errors:
        lines.insert(0, f"{result.cell_errors} cell(s) raised an error during execution.")
    if tampered:
        lines.append("Note: modified check cells were restored from the assignment before grading.")

    try:
        gv = metadata.version("mograder")
    except metadata.PackageNotFoundError:  # pragma: no cover
        gv = "unknown"
    return GradeResult(
        grader_version=f"mograder {gv}",
        fraction=(earned / total) if total else 0.0,
        feedback="\n".join(lines),
        checks=checks_out,
        tampered=tampered,
        export_ok=result.export_ok,
        export_error=result.export_error,
        cell_errors=result.cell_errors,
    )
