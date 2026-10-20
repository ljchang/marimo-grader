"""Why a submission could not be graded, in words a grader can act on.

The worker records the raw exception text (``GraderRun.error``). Staff need
three things from it: what went wrong, whose move it is, and whether a retry
can change anything. A retry re-runs the same notebook with the same grader,
so it only helps when something outside the notebook was at fault.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Cause:
    kind: str  # safety | notebook | timeout | data | grader
    summary: str
    advice: str
    retry_helps: bool

    def as_dict(self) -> dict:
        return asdict(self)


_STUDENT = "Only the student can fix this: they need to change the notebook and resubmit. A retry fails the same way."


def classify(error: str | None) -> Cause:
    text = error or ""
    if m := re.search(r"safety check failed: (.+?)(?:$|\n)", text):
        what = m.group(1).strip()
        return Cause(
            "safety",
            f"The safety check refused the notebook ({what})",
            "The student's code uses something the grader does not run. " + _STUDENT,
            False,
        )
    if m := re.search(r"MultipleDefinitionError: The variable '([^']+)'", text):
        return Cause(
            "notebook",
            f"The notebook cannot run: `{m.group(1)}` is defined in more than one cell",
            _STUDENT,
            False,
        )
    if re.search(r"CycleError|SyntaxError|IndentationError", text):
        kind = re.search(r"CycleError|SyntaxError|IndentationError", text).group(0)
        return Cause("notebook", f"The notebook cannot run: {kind}", _STUDENT, False)
    if re.search(r"timed? ?out after \d+|timeout after \d+", text):
        secs = re.search(r"after (\d+)\s*s", text)
        limit = f" ({secs.group(1)} s)" if secs else ""
        return Cause(
            "timeout",
            f"It ran out of time{limit}",
            "A heavy or stuck notebook. Retry when the grader is quiet; if it times out "
            "again, raise the assignment's time limit or read the code for a loop.",
            True,
        )
    if "no check cell ran" in text:
        return Cause(
            "data",
            "Nothing in the notebook could be checked",
            "Usually data the sandbox cannot reach offline. Run `grader warm-cache` for "
            "this assignment, then retry.",
            True,
        )
    if "could not build the notebook environment" in text or "not installed" in text:
        return Cause(
            "grader",
            "The grader could not set up the notebook's packages",
            "A problem on the grader, not in the notebook. Retry; if it fails again, "
            "check the worker logs.",
            True,
        )
    if "some cells failed to execute" in text:
        return Cause(
            "notebook",
            "Cells raised errors while the notebook ran",
            "Open the submission to see which cells failed. If it is the student's code, "
            + _STUDENT[0].lower()
            + _STUDENT[1:],
            False,
        )
    first = text.strip().splitlines()[0][:160] if text.strip() else "no error recorded"
    return Cause(
        "grader",
        f"Unexpected error: {first}",
        "Retry; if it fails again, check the worker logs.",
        True,
    )
