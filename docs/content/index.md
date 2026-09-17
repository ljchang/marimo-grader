# marimo-grader

Assignments that are real notebooks, graded without anybody touching Git.

marimo-grader is a grading service for coursework written as [marimo](https://marimo.io) notebooks. A student opens a notebook, works through it, presses **Check** for instant feedback, signs in with their university account from inside the notebook, and presses **Submit**. Teaching staff grade in a web app. Grades export to Canvas.

/// admonition | Be a student for five minutes
    type: tip

[**Try an assignment**](demo/try-an-assignment.md) — a real one, in your browser, on this site. Nothing to install, nothing submitted anywhere.
///

## The loop

> read → experiment → **check** → submit → get feedback

That is the whole student-facing design, and everything else exists to protect it. Students never touch Git, tokens, servers, virtual environments, or a submission portal. They press two buttons, and the difference between them is the thing worth learning:

| | **Check** | **Submit** |
|---|---|---|
| Runs | in the student's notebook | on the grader |
| When | as often as they like | when they are ready |
| Speed | instant | a score back in about a minute |
| Counts? | no — it is for learning | yes — it records an attempt |
| Sees | the visible tests | the visible tests *and* the hidden ones |

## The same notebook, wherever it runs

| Environment | What it is | Typical use |
|---|---|---|
| Browser (WASM) | the notebook runs in the page itself, no server | light assignments: Python basics, pandas, plotting |
| MoLab | marimo's hosted notebooks, a full Python environment | most data-science assignments |
| A cluster (Open OnDemand) | marimo on institutional HPC | large datasets, neuroimaging, GPUs |
| A laptop | `marimo edit --sandbox assignment.py` | anyone who prefers local work |

Execution and grading are independent. Whatever the kernel runs on, the widget's JavaScript runs in the student's browser, so the only network requirement is that the *browser* can reach the grader. A notebook on a cluster behind a VPN submits perfectly well.

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

Every submission stores the whole notebook as an immutable attempt against the exact assignment version the student opened. A worker autogrades it inside a sandbox with no network and renders it to HTML for the grading view. Written answers wait in a queue for a person. [The life of a submission](how-it-works/life-of-a-submission.md) follows one all the way through.

The autograding itself is [MoGrader](https://github.com/jameskermode/mograder), James Kermode's open-source grading engine for marimo notebooks, used as a library. It supplies the authoring markers, the checks, the integrity hashes and the sandboxed runner; marimo-grader supplies single sign-on, the multi-course service around it, and the notebook widget. See [The grading engine](how-it-works/grading-engine.md).

## What the staff side looks like

The course page leads with the only question that matters on a Tuesday — who needs my attention? — and puts the class grid underneath.

![The course page: a Needs attention list above the class progress grid, one column per question](../images/course-page.png)

Hand-graded questions have a queue: the student's rendered notebook on the left, score and feedback on the right, `j`/`k` to move, `Cmd+Enter` to save. Student code never runs in a grader's browser.

![The grading queue: the rendered notebook on the left, score, feedback, and the student's written answer on the right](../images/grading-queue.png)

## Where to start

- **New here** — [Try an assignment](demo/try-an-assignment.md), then [What the instructor wrote](demo/what-the-instructor-wrote.md). Fifteen minutes and you will know whether this fits your course.
- **Students** — [Open an assignment](students/open-an-assignment.md) · [Sign in and submit](students/sign-in-and-submit.md) · [Feedback and grades](students/feedback-and-grades.md)
- **Instructors and TAs** — [Author an assignment](instructors/author-an-assignment.md) · [Publish](instructors/publish.md) · [Roster and staff](instructors/roster-and-staff.md) · [Grading](instructors/grading.md) · [Canvas export](instructors/canvas-export.md)
- **Understanding it** — [Concepts](how-it-works/concepts.md) · [The life of a submission](how-it-works/life-of-a-submission.md) · [The grading engine](how-it-works/grading-engine.md)
- **Authentication** — [How sign-in works](auth/index.md), then the [notebook handshake](auth/notebook-sign-in.md), [SAML](auth/saml.md), [email links](auth/email-links.md), and [sessions and tokens](auth/sessions-and-tokens.md).
- **Running a server** — [Overview](operators/overview.md) · [Deploy](operators/deploy.md) · [Security model](operators/security-model.md), which is written to be handed to an institutional review as is.
- **Reference** — [command line](reference/cli.md) · [configuration](reference/configuration.md) · [notebook metadata](reference/notebook-metadata.md) · [HTTP API](reference/api.md) · [design document](reference/design.md)

## Status

A pilot. It runs one course — [DartBrains](https://dartbrains.org) at Dartmouth — and is built to run more. The code is at [github.com/ljchang/marimo-grader](https://github.com/ljchang/marimo-grader), MIT licensed. Things that are planned rather than done are labelled as such on the page where they belong; [the design document](reference/design.md) has the roadmap.

## Related projects

This site and the [DartBrains](https://dartbrains.org) course book are built with [marimo-book](https://marimobook.org), a static-site generator for marimo notebooks ([source](https://github.com/ljchang/marimo-book)). A book publishes the student version of an assignment as an ordinary page and links it here — the drawer on [Try an assignment](demo/try-an-assignment.md) is that feature. See marimo-book's [Assignments and grading](https://marimobook.org/assignments-and-grading/).

[MoGrader](https://github.com/jameskermode/mograder) (James Kermode, University of Warwick, MIT license) is the grading engine. If you publish work that used this system, please cite it alongside marimo-grader.
