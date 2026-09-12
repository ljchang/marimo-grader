# marimo-grader

For anyone deciding whether this tool fits a course, and for finding the right page below.

marimo-grader is a grading service for assignments written as [marimo](https://marimo.io) notebooks. A student opens a notebook, works through it, presses **Check** for instant feedback, signs in with their university account from inside the notebook, and presses **Submit**. Teaching staff grade in a web app. Grades export to Canvas.

The student's mental model is the whole design:

> read → experiment → check → submit → get feedback

Students never touch Git, tokens, servers, or Python environments. The same notebook, with the same buttons, works wherever it runs:

| Environment | What it is | Typical use |
|---|---|---|
| Browser (WASM) | The notebook runs in the page itself, no server | Light assignments: Python basics, pandas, plotting |
| MoLab | marimo's hosted notebooks, a full Python environment | Most data-science assignments |
| A cluster (Open OnDemand) | marimo on institutional HPC | Large datasets, neuroimaging, GPUs |
| A laptop | `marimo edit --sandbox assignment.py` | Anyone who prefers local work |

Execution and grading are independent. Whatever the kernel runs on, the widget's JavaScript runs in the student's browser, so the only network requirement is that the browser can reach the grader.

## How the pieces fit

```
private assignments repo          instructor notebooks: solutions, hidden tests, marks
        |  grader publish
        v
marimo-grader server              versions, student notebooks, grading, roster, exports
        |  student notebook served at /a/{course}/{term}/{slug}/student.py
        v
course website / MoLab / cluster  students open the assignment
        ^
student's browser  ---  sign-in handshake and submit, from the notebook widget
```

Every submission stores the whole notebook as an immutable attempt against the exact assignment version the student opened. A worker autogrades it with [MoGrader](https://github.com/jameskermode/mograder)'s engine inside a network-less sandbox and renders it to HTML for the grading view. Written answers wait in a queue for a person.

## Where to start

- **Students**: [Open an assignment](students/open-an-assignment.md), then [Sign in and submit](students/sign-in-and-submit.md).
- **Instructors and TAs**: [Author an assignment](instructors/author-an-assignment.md), [Publish](instructors/publish.md), [Roster and staff](instructors/roster-and-staff.md), [Grading](instructors/grading.md).
- **Operators**: [Deploy](operators/deploy.md), [Single sign-on](operators/single-sign-on.md), and the [Security model](operators/security-model.md) to hand to a reviewer.
- **Reference**: the [command line](reference/cli.md), [configuration](reference/configuration.md), [notebook metadata](reference/notebook-metadata.md), the [HTTP API](reference/api.md), and the [design document](reference/design.md).

The code is at [github.com/ljchang/marimo-grader](https://github.com/ljchang/marimo-grader), MIT licensed. The first course using it is [DartBrains](https://dartbrains.org) at Dartmouth.

## Related

This site and the [DartBrains](https://dartbrains.org) course book are built with [marimo-book](https://marimobook.org), a static-site generator for marimo notebooks ([source](https://github.com/ljchang/marimo-book)). A book publishes the student version of an assignment as an ordinary page and links it here; see marimo-book's [Assignments and grading](https://marimobook.org/assignments-and-grading/) page.
