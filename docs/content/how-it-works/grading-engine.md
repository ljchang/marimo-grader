# The grading engine

marimo-grader does not implement autograding. It uses **[MoGrader](https://github.com/jameskermode/mograder)**, an open-source grading engine for marimo notebooks written by [James Kermode](https://warwick.ac.uk/fac/sci/eng/people/james_kermode/) at the University of Warwick and released under the MIT license.

MoGrader is installed as an ordinary Python dependency, in the notebook alongside marimo and in the worker that grades. It is not forked and not vendored: the engine is the part that has to be correct and reproducible, and it is best maintained in one place, upstream.

## What it provides

| MoGrader | What it does here |
|---|---|
| Authoring markers — `### BEGIN SOLUTION`, `### BEGIN HIDDEN TESTS`, the `MOGRADER: MARKS` cell | the conventions instructors write in. `grader publish` uses MoGrader's marker validation and solution stripping to produce the student notebook |
| `check()` | the call a student runs in the notebook. `marimo-grader-client` wraps it so the result is also recorded for submission, and defers to MoGrader for the rendering and the marks badges |
| Cell hashes and the integrity check | detects check or marks cells a student edited, and restores the instructor's versions before grading |
| Hidden-test reinjection | puts the stricter conditions back into the submitted notebook so grading sees more than the student did |
| The sandboxed runner | executes the notebook with resource limits, a wall-clock timeout, an AST safety scan, and — in production — inside bubblewrap with no network |
| Check weights and the results sidecar | partial credit per condition, and the machine-readable results the worker turns into a score |

## What marimo-grader adds around it

A multi-course service: single sign-on for browsers and notebooks, immutable per-attempt submissions bound to a published version, a PostgreSQL schema with an audit trail, roster import, a grading web app for staff, Canvas export, and the widget that signs in and submits from inside a notebook wherever it happens to be running.

The split is the point. The engine decides whether an answer is right; the service decides who may see what, what was submitted when, and what the grade is.

## Things worth knowing when you author

These are MoGrader behaviours that shape how an assignment is written. None of them are surprises once you know them, and [What the instructor wrote](../demo/what-the-instructor-wrote.md) shows each one in a real file.

**Question ids are check labels.** Every check is keyed by the text before the first colon of its label, so `check("glm-q03: Design matrix", ...)` belongs to question `glm-q03`. marimo-grader uses that key as the question id and the text after the colon as the title.

**One `check()` per question.** Marks are summed per key. Put the visible and hidden conditions in one call rather than writing a second call with the same id, or the question counts twice.

**Hidden tests live inside the check list.** The `### BEGIN HIDDEN TESTS` block is removed from the student copy and put back at grading time. Students see a `# HIDDEN TESTS` comment where it was — that comment is intentional, not a leak: it tells them a hidden condition exists without telling them what it is.

**Stripping a solution leaves `...` behind.** Variables a solution block defined are assigned `Ellipsis` in the student copy, so check cells should open with a guard:

```python
mo.stop(
    mean_rt is ...,
    mo.md("**Complete the code cell above first.** This check runs once `mean_rt` is defined."),
)
```

Without it, an untouched notebook raises the moment it opens.

**The environment is prepared before the sandbox, not inside it.** MoGrader can build a virtual environment from the notebook's PEP 723 block; marimo-grader does that outside the sandbox, once per distinct dependency list, and then runs the notebook with no network and a read-only filesystem. Everything the notebook needs at grading time must be installed or cached beforehand — which is what [`grader warm-cache`](../operators/sandbox-and-data.md) is for.

**Engine and checks are versioned together.** The worker pins the MoGrader version it ships with (0.3.x at the time of writing) and rewrites each submitted notebook's `mograder` requirement to match, so the code that runs the checks is the code that scores them. Moving to a new version is deliberate: run marimo-grader's test suite against it before changing the pin.

## Where MoGrader's own documentation helps

MoGrader's [README](https://github.com/jameskermode/mograder#readme) is the reference for the markers and `check()` itself, and worth reading if you are writing a lot of assignments. MoGrader also ships transports of its own — a single-course server, a session hub, a Moodle integration, a workshop mode — which are alternatives to this service rather than parts of it; if your course fits one of them, it is a smaller thing to run.

## Attribution

If you publish work that used this system, please cite MoGrader alongside marimo-grader. The repository is [github.com/jameskermode/mograder](https://github.com/jameskermode/mograder) and the package is `mograder` on PyPI.
