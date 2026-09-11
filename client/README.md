# grader-client

Notebook-side client for the dartbrains grader. It gives a marimo notebook three
small widgets - **sign in**, **submit** and **feedback** - backed by the
`/api/v1` contract in `docs/api.md`.

Every HTTP request is made from the student's browser by the widget's
JavaScript. The kernel never sees the bearer token; it only reads the notebook
file, collects check results and hands the payload to the widget.

```
pip install grader-client            # core: anywidget + traitlets
pip install "grader-client[mograder]" # also use MoGrader's check()/sidecar
```

## What an assignment looks like

The instructor (or the grader's publish step) injects the assignment identity
into the notebook's PEP 723 block. Either spelling works; a `[tool.grader]`
table wins over top-level keys.

```python
import marimo

# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "grader-client"]
# mograder-assignment = "week03-glm"
# mograder-cell-hashes = "8f3a...,1c9e..."
# grader-assignment-version = "1f0e5c2a-...-..."
# grader-offering-id = "9b7d...-..."
# grader-assignment-id = "4a21...-..."
# grader-server = "https://grader.dartbrains.org"
# ///
```

or

```python
# /// script
# [tool.grader]
# assignment-version = "1f0e5c2a-...-..."
# offering-id = "9b7d...-..."
# assignment-id = "4a21...-..."
# server = "https://grader.dartbrains.org"
# ///
```

Anything missing from the metadata falls back to the environment variables
`GRADER_SERVER`, `GRADER_ASSIGNMENT_VERSION_ID`, `GRADER_OFFERING_ID` and
`GRADER_ASSIGNMENT_ID`; explicit `Grader(...)` arguments override both.

### Cells

```python
@app.cell
def _():
    from grader_client import Grader
    grader = Grader()          # reads the metadata above
    grader.signin_button()     # "Sign in with Dartmouth" - once per notebook
    return (grader,)
```

```python
@app.cell
def _(grader, beta):
    grader.check("q03: GLM betas", [
        (beta.shape == (4,), "beta should have four entries"),
        (abs(beta[0] - 1.2) < 0.1, "the intercept looks off", 2),   # optional weight
    ])
```

```python
@app.cell
def _(grader):
    grader.submit_button("q03")   # "Submit q03"
```

```python
@app.cell
def _(grader):
    grader.feedback("q03")        # latest attempt: score, max points, feedback
```

`check()` delegates to `mograder.runtime.check` when MoGrader is installed
(so its callouts, marks badges and JSONL sidecar keep working) and otherwise
renders an equivalent callout on its own. Either way the outcome is recorded on
the `Grader` instance and included in the next submission as `check_results`.

Make the submit cell depend on the variables your checks use (as above) so it
re-runs after edits; the widget also re-reads the notebook file from disk the
moment the button is clicked.

## What the widgets do

- **Sign in** opens a tab to the grader's device verification page, shows the
  `ABCD-1234` code and the URL for manual use, polls
  `POST /api/v1/auth/device/token` until approval and stores the token in the
  browser's `localStorage` under `grader:<server>:token`. The token also lands
  in the widget's `token` / `netid` traits.
- **Submit** posts `{assignment_version_id, question_id, notebook,
  check_results, outputs, client}` to `POST /api/v1/submissions` with the
  bearer token, shows the attempt number and time, then polls
  `GET /api/v1/submissions/{id}` every 3 s (up to 2 min) and shows
  `score.total / max_points` plus feedback once graded. A `401` shows an
  inline sign-in button.
- **Feedback** reads `GET /api/v1/offerings/{offering_id}/me/submissions?assignment_id=...`
  and renders the latest attempt for the question.

Only the browser can reach the grader, so nothing works in a kernel without a
readable notebook file (for example WASM): `read_notebook_source()` returns
`None` and the submit button explains that the notebook cannot be sent.

## Python API

```python
from grader_client import Grader, GraderWidget, check, __version__
from grader_client.notebook import (
    read_notebook_source, read_assignment_metadata,
    collect_check_results, build_payload,
)
```

- `Grader(server=None, assignment_version_id=None, offering_id=None, assignment_id=None, *, source=None, notebook_path=None)`
  - `.signin_button()`, `.submit_button(question_id, outputs=None)`, `.feedback(question_id)` -> `GraderWidget`
  - `.check(label, conditions, **kw)` -> callout HTML; `.check_results()` -> recorded records
  - `.build_payload(outputs=None)` -> the submission body (minus the ids the widget adds)
  - `.metadata` -> parsed PEP 723 metadata
- `GraderWidget` traits: `server`, `mode` (`signin|submit|feedback`),
  `assignment_version_id`, `question_id`, `offering_id`, `assignment_id`,
  `token`, `netid`, `payload`, `result`, `status`
  (`idle|pending|approved|submitting|done|error`), `message`.

## Development

```
uv sync --all-extras
uv run ruff check src tests
uv run pytest
```
