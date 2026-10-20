"""From an instructor notebook to what gets published: the student copy and
the question list. ``grader publish`` and the web page's publish flow share
this, so a version looks the same whichever way it was made.

The student copy is MoGrader's: solution and hidden-test blocks stripped,
markdown cells converted, cell hashes injected. Questions come from the
``_marks = {...}`` cell; a question is auto-graded when some ``check("<qid>:
...")`` exists for it and graded by hand otherwise.
"""

from __future__ import annotations

import ast
import re

from grader.services.notebook_meta import leaked_markers

CHECK_RE = re.compile(r"""check\(\s*[rf]?["']([^"':]+)\s*:\s*([^"']*)["']""")
MARKS_RE = re.compile(r"_marks\s*=\s*(\{[^}]*\})", re.S)


class BuildError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def generate_student(source_text: str, name: str = "notebook.py") -> str:
    try:
        from mograder.grading import cells
    except ImportError as e:
        raise BuildError(
            "no_mograder", "mograder is not installed, so the student copy cannot be built"
        ) from e
    lines = source_text.splitlines(keepends=True)
    errors = cells.validate_markers(lines, name)
    if errors:
        raise BuildError("bad_markers", "; ".join(errors))
    out = cells.strip_solutions(lines)
    out = cells.strip_hidden_tests(out)
    out = cells.convert_markdown_cells(out)
    text = "".join(out)
    if hasattr(cells, "_inject_cell_hashes"):
        text = cells._inject_cell_hashes(text)
    leaked = leaked_markers(text)
    if leaked:
        raise BuildError(
            "solution_leak", f"the student copy would still contain {', '.join(leaked)}"
        )
    return text


def questions_from(
    source_text: str,
    manual: set[str] | frozenset[str] = frozenset(),
    hybrid: dict[str, float] | None = None,
    *,
    optional: bool = False,
) -> list[dict]:
    hybrid = hybrid or {}
    m = MARKS_RE.search(source_text)
    if not m:
        if optional:
            return []
        raise BuildError("no_marks", "no `_marks = {...}` cell found in the instructor notebook")
    try:
        marks = ast.literal_eval(m.group(1))
    except (ValueError, SyntaxError) as e:
        raise BuildError("bad_marks", f"the `_marks` cell is not a plain dict: {e}") from e
    titles = {k.strip(): t.strip() for k, t in CHECK_RE.findall(source_text)}
    qs = []
    for qid, pts in marks.items():
        if qid in hybrid:
            mode, auto_max = "hybrid", hybrid[qid]
        elif qid in manual or qid not in titles:
            mode, auto_max = "manual", 0.0
        else:
            mode, auto_max = "auto", float(pts)
        qs.append(
            {
                "qid": qid,
                "title": titles.get(qid) or qid,
                "max_points": float(pts),
                "auto_points_max": auto_max,
                "grading_mode": mode,
                "check_keys": [qid] if mode != "manual" else [],
            }
        )
    return qs
