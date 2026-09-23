"""Bridge between a submission and MoGrader's grading engine.

MoGrader (``mograder``) is used strictly as a library:

* ``mograder.grading.integrity.check_integrity`` swaps in the instructor's
  ``check()`` and marks cells. It is called twice, against two baselines: the
  instructor copy to decide what to grade, and the released copy to decide
  whether the student actually changed anything. See :func:`grade`.
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
from grader.url_cache import rewrite_urls
from grader.worker.materialize import rewrite_dependencies

TIMEOUT = int(os.environ.get("GRADER_AUTOGRADE_TIMEOUT", "300"))
# Address-space cap for the notebook process. numpy/scipy/nilearn reserve a lot of virtual
# memory at import, so MoGrader's 1 GiB default is too small for neuroimaging assignments.
RLIMIT_AS = int(os.environ.get("GRADER_RLIMIT_AS", str(4 << 30)))
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


def nothing_ran_reason(result, auto_points_max: float) -> str | None:
    """Why this run must fail rather than score, or None if it can be scored.

    marimo finishes a notebook whose cells raised, so ``export_ok`` stays True and
    the checks that depended on those cells are simply absent. For one question
    that is the student's own broken answer and 0 is right. When *no check cell in
    the whole notebook* ran, something every question needs failed -- data the
    sandbox could not reach, a missing package -- and scoring it would give the
    whole class 0 with empty feedback (the pandas and polars assignments,
    September 2026). Fail the run instead so staff see it and can retry.
    """
    if auto_points_max <= 0 or result.checks:
        return None
    why = result.export_error or "no check cell ran"
    return (
        f"no check cell ran ({why}; {result.cell_errors} cell error(s)) -- the notebook "
        "could not get far enough to grade, e.g. data it reads was not reachable offline"
    )


def grade(db: Session, sub: Submission) -> GradeResult:
    try:
        from mograder.grading import integrity
        from mograder.grading.runner import run_notebook
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("mograder is not installed in the worker image") from e

    version = sub.version
    instructor_art = db.get(Artifact, version.instructor_artifact_id)
    release_art = db.get(Artifact, version.student_artifact_id)
    notebook_art = db.get(Artifact, sub.notebook_artifact_id)
    assert instructor_art is not None and notebook_art is not None
    source_text = store().get(instructor_art).decode()
    submitted_text = store().get(notebook_art).decode()

    # Two different questions, two different baselines.
    #
    # What to GRADE: the instructor's check cells, which carry the hidden tests.
    # check_integrity swaps them in, and that swap is how hidden tests reach the
    # graded notebook -- it is load-bearing, not incidental.
    integ = integrity.check_integrity(source_text, submitted_text)
    fixed = integ.fixed_source

    # What to REPORT: whether the student changed anything. Comparing their cells
    # against the instructor copy always says yes, because the copy they were given
    # has the hidden tests stripped out of those very cells -- so the two can never
    # match. Diff against the release instead: that is what they actually received,
    # and a difference there is a real edit. (mograder's own hub compares this way.)
    tampered: list[str] = []
    if release_art is not None:
        release_text = store().get(release_art).decode()
        real = integrity.check_integrity(release_text, submitted_text)
        tampered += list(real.tampered_checks)
        if real.tampered_marks:
            tampered.append("__marks__")
    if integrity.has_hidden_tests(source_text):
        fixed, _hidden = integrity.inject_hidden_tests(source_text, fixed)

    from grader.worker.sandbox import prepare_env

    fixed = rewrite_dependencies(fixed)
    # Data read from a plain URL: use the copy warm-cache fetched (the sandbox has
    # no network). See grader.url_cache.
    fixed = rewrite_urls(fixed)
    # Build (or reuse) the notebook's environment *outside* bubblewrap: inside the
    # sandbox the filesystem is read-only and there is no network, so marimo must
    # run with --no-sandbox against a prepared venv.
    venv = prepare_env(fixed)
    with tempfile.TemporaryDirectory(prefix="grader-run-") as td:
        nb = Path(td) / "submission.py"
        nb.write_text(fixed)
        # MoGrader's bubblewrap mode binds only the notebook's directory read-write and
        # puts a private tmpfs over /tmp, yet it creates its HTML output and the check
        # sidecar with tempfile (i.e. in /tmp). Those files would be written inside the
        # sandbox's tmpfs and be invisible afterwards. Pointing tempfile at the run
        # directory keeps every per-run file inside the bound path. The directory is
        # unique per run, so isolate_cwd is not needed on top of it.
        saved_tmp = tempfile.tempdir
        tempfile.tempdir = td
        try:
            result = run_notebook(
                nb,
                timeout=TIMEOUT,
                sandbox_dir=venv,
                safety_check=True,
                isolate_cwd=False,
                use_bubblewrap=USE_BWRAP,
                rlimit_as=RLIMIT_AS,
            )
        finally:
            tempfile.tempdir = saved_tmp

    if not result.export_ok:
        # The notebook could not run at all: a grader failure to look at, not a zero.
        raise RuntimeError(f"notebook execution failed: {result.export_error[:1500]}")

    q = sub.question
    nothing_ran = nothing_ran_reason(result, float(q.auto_points_max or 0))
    if nothing_ran:
        raise RuntimeError(nothing_ran)
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
