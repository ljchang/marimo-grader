"""Student-notebook metadata and safety checks shared by the publish API and the CLI.

The server, not the CLI, produces the final distributed student notebook: it
injects the ``grader-*`` keys (including the version id, which only exists once
the version row is created) into the PEP 723 block and stores exactly those
bytes. ``/a/{course}/{term}/{slug}/student.py`` serves them unchanged, so the
page, the download, and the notebook a student submits from never disagree.
"""

from __future__ import annotations

import re

SOLUTION_MARKERS = (
    "### BEGIN SOLUTION",
    "### END SOLUTION",
    "### BEGIN HIDDEN TESTS",
    "### END HIDDEN TESTS",
)

_BLOCK_RE = re.compile(r"^# /// script\s*$(?P<body>.*?)^# ///\s*$", re.M | re.S)


def leaked_markers(student_text: str) -> list[str]:
    """Return solution/hidden-test markers still present in a student notebook."""
    return [m for m in SOLUTION_MARKERS if m in student_text]


def strip_grader_keys(text: str) -> str:
    """Remove any existing ``# grader-... = "..."`` lines from the PEP 723 block."""
    return re.sub(r'^# grader-[a-z0-9-]+ = "[^"\n]*"\n', "", text, flags=re.M)


def inject_grader_keys(student_text: str, **keys: str | None) -> str:
    """Add ``# grader-<key> = "<value>"`` lines inside the PEP 723 block, creating one if needed.

    Keys are written with dashes (``assignment_version`` → ``grader-assignment-version``).
    Existing grader keys are replaced so the operation is idempotent.
    """
    text = strip_grader_keys(student_text)
    lines = [f'# grader-{k.replace("_", "-")} = "{v}"' for k, v in keys.items() if v]
    if not lines:
        return text
    m = _BLOCK_RE.search(text)
    if m:
        end = m.end("body")
        return text[:end] + "\n".join(lines) + "\n" + text[end:]
    return "# /// script\n" + "\n".join(lines) + "\n# ///\n" + text


def read_grader_keys(text: str) -> dict[str, str]:
    m = _BLOCK_RE.search(text)
    if not m:
        return {}
    out = {}
    for km in re.finditer(r'^# grader-([a-z0-9-]+) = "([^"\n]*)"', m.group("body"), re.M):
        out[km.group(1)] = km.group(2)
    return out
