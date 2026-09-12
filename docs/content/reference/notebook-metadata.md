# Notebook metadata

For instructors and tool authors. The keys the grader writes into a student notebook's PEP 723 block, and how the client reads them.

When an assignment is published, the server finalizes the student notebook by adding comment lines inside the `# /// script` block. The client widget reads them so a student never types an id.

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "numpy", "marimo-grader-client", "mograder"]
# mograder-cell-hashes = "cff29c05,0def6f6b,..."
# grader-server = "https://grader.dartbrains.org"
# grader-course = "neuroimaging"
# grader-term = "2026-fall"
# grader-offering-id = "ff60e470-..."
# grader-assignment = "glm"
# grader-assignment-id = "f8a93305-..."
# grader-assignment-version = "7af78b67-..."
# grader-version = "1"
# ///
```

| Key | Written by | Used for |
|---|---|---|
| `dependencies`, `requires-python` | the author | the environment everywhere the notebook runs, including the grading sandbox |
| `mograder-cell-hashes` | MoGrader during publish | detecting edited check cells; the grader restores them before running |
| `grader-server` | the grader | where the widget signs in and submits |
| `grader-course`, `grader-term`, `grader-assignment` | the grader | human-readable identity and the public alias URLs |
| `grader-offering-id`, `grader-assignment-id` | the grader | the widget's feedback view |
| `grader-assignment-version` | the grader | which version a submission is bound to; authoritative |
| `grader-version` | the grader | the version number, for people |

The client also accepts a `[tool.grader]` table with the same names minus the prefix, and falls back to `GRADER_SERVER`, `GRADER_ASSIGNMENT_VERSION_ID`, `GRADER_OFFERING_ID`, and `GRADER_ASSIGNMENT_ID` from the environment. Explicit `Grader(...)` arguments override both.

Publishing replaces any existing `grader-*` lines, so a notebook can be republished without accumulating stale keys. Everything else in the block is left as the author wrote it.

When the grading worker prepares an environment it substitutes its own pinned requirement for `marimo-grader-client` and `mograder`, so grading always uses the versions the worker ships with.
