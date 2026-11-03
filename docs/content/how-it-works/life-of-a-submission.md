# The life of a submission

One student, one question, from the moment they press **Submit** to the moment a score appears in their notebook. This page is the mechanism behind everything else on the site; read it once and the rest of the documentation stops being a list of features.

```
notebook (browser)          grader (API)              worker                  student
      |                         |                       |                        |
   Submit ──── POST /submissions ──►                    |                        |
      |                    store notebook               |                        |
      |                    as an artifact               |                        |
      |                    record attempt N             |                        |
      |                    queue: snapshot, render,     |                        |
      |                           autograde             |                        |
      |◄──── attempt no. + time ──┤                     |                        |
      |                           ├──────── claim ─────►|                        |
      |                           |                 student's outputs to HTML    |
      |                           |                 re-run to HTML               |
      |                           |                 restore checks               |
      |                           |                 reinject hidden tests        |
      |                           |                 run, sandboxed, no network   |
      |                           |◄──── score + feedback ──┤                    |
      |◄──── poll: graded ────────┤                     |                        |
   feedback appears               ├─────────── visible in the portal ───────────►|
```

## 1. In the notebook

The widget's JavaScript, running in the student's browser, assembles a payload:

- **the whole notebook source**, re-read from disk at the moment of the click — not the copy loaded when the page opened, so late edits are included;
- **the question id** being submitted;
- **the check results** recorded by every `g.check` that ran in this session, up to 200 of them;
- **outputs**, the values of any `mo.ui` element the author passed explicitly — this is how a written answer travels, since a text box's contents are not part of the notebook file;
- **the session snapshot**: marimo's record of every cell's last outputs (`__marimo__/session/<notebook>.py.json`), each tagged with a hash of the code that produced it. marimo writes it a second or two after outputs change, so the kernel waits up to about 2.5 s for a fresh write. It travels by message, never in the widget's synced state, so it cannot end up inside the next snapshot;
- **a client id** for the submission, so a double-click cannot create two attempts.

It posts this to the grader with the student's notebook token as a bearer credential. The Python kernel never makes a network call; it only reads the files and builds the payload. That separation is what lets the same notebook submit from MoLab, a cluster, a laptop or a browser tab — see [Notebook sign-in](../auth/notebook-sign-in.md).

## 2. At the API

The server resolves the caller's enrollment in the offering that owns the assignment version *before* anything else, and then:

1. **Rejects an oversized notebook** (2 MiB by default) or oversized outputs (8 MiB).
2. **Deduplicates** on the client submission id — a retry or a double-click returns the original attempt rather than making a second.
3. **Enforces the attempt cap**, if the assignment has one: a 409, not a silent extra attempt.
4. **Stores the notebook as a content-addressed artifact**, the outputs as a second one and the session snapshot as a third. A snapshot that is too large (10 MiB) or not a marimo session is dropped and noted on the attempt, never a reason to refuse it.
5. **Inserts the submission**: enrollment, assignment version, question, attempt number, the artifacts, and the check results the client claimed.
6. **Queues its runs** — snapshot render always, re-run render and autograde when the assignment has them on — and publishes an event so open grading pages update themselves.

It answers immediately with the attempt number and time. Nothing has been graded yet, and the student's notebook says so.

The submission is now immutable. It is bound to the assignment *version* the student opened, which is what makes a mid-term republish safe.

## 3. In the worker

Workers claim queued runs with `SELECT … FOR UPDATE SKIP LOCKED`, so several can run side by side without treading on each other.

**The snapshot render goes first.** It matches the snapshot's outputs to the submitted cells by code hash (in document order where two cells have the same code) and hands them to marimo's HTML exporter: the page `marimo export html` would make, without executing anything, in about a second. A cell edited after it last ran keeps its code and loses its stale output. With no snapshot on the attempt it renders nothing, and the grading view shows the code. The result is the render graders see until a re-run replaces it, and the only one when re-run is off. It parses the notebook statically and runs in a subprocess, and it uses marimo internals, so the worker pins marimo's version.

**Render goes before autograde when both are queued.** Rendering runs outside the sandbox and therefore has network; autograding does not. For an assignment that downloads data, grading first on a cold cache fails the whole run while the render quietly warms it — so the failure disappears on the next attempt and cannot be reproduced. Ordering the two removes that ghost. (Warming the cache at deploy time is the real fix; see [Sandbox and data](../operators/sandbox-and-data.md).)

Then autograde:

1. **Materialize.** Write the submitted notebook out, and rewrite two lines of its dependency block: the grading client and the engine are pinned to the versions the worker itself ships, so the code that runs the checks is the code that scores them. Every other dependency — numpy, nilearn, whatever the assignment needs — is left exactly as the author wrote it.
2. **Prepare the environment.** Build a virtual environment for that dependency list, *outside* the sandbox, because installing packages needs network and a writable disk. One environment per distinct dependency list, reused by every submission of that assignment. This is why the first submission of a newly published assignment takes about a minute longer than the rest.
3. **Check integrity — twice.** The engine compares the submitted check and marks cells against two baselines: the **instructor's** copy, to decide what will actually be graded, and the **released student** copy, to decide whether this student changed anything. Edited cells are replaced with the instructor's versions, and the feedback says so. Comparing against the released copy rather than the instructor's is what stops every submission from being reported as "modified" merely because solutions were stripped from it.
4. **Reinject hidden tests.** The conditions removed when the student copy was generated go back in.
5. **Run it.** The notebook executes with the prepared environment, an address-space cap, and a wall-clock timeout (five minutes by default). In production it runs inside bubblewrap: filesystem read-only, a private `/tmp`, and `--unshare-net` — no network at all. Anything the notebook needs must already be installed or cached.
6. **Score it.** Each check writes a line to a results sidecar. The worker takes the checks belonging to the submitted question, weights the conditions that passed, multiplies by the question's marks, and writes an `auto_points` score.

If the run fails — a timeout, a package that would not build, a crash — that is recorded as a **grader failure**, not a zero. It surfaces on the course page with a **Retry** button.

## 4. Back to the student

The widget polls the submission until it leaves the pending state, then shows the score and the per-condition feedback in the notebook itself.

Hand-graded questions stop here and say *waiting for grade* until somebody opens the [grading queue](../instructors/grading.md). Hybrid questions show their automatic part and wait for the rest.

Either way the feedback also lives in the [student portal](../students/feedback-and-grades.md), which outlives the MoLab session the work was done in.

## 5. What is left behind

| Written | Where | Mutable? |
|---|---|---|
| The submitted notebook, byte for byte | artifact store, addressed by content hash | no |
| Written answers | artifact store | no |
| The attempt | `submissions` | no |
| The session snapshot (the student's own outputs) | artifact store | no; an instructor may attach another, which is labelled as such |
| Rendered HTML for the grading view | artifact store | replaced if re-rendered |
| Automatic score | `scores` | superseded, never overwritten |
| Human score and feedback | `scores` | superseded, never overwritten |
| Who did what, when, before, after | `grade_audit` | append-only |

A grade is therefore always reconstructible: which version was graded, which bytes were submitted, which tests ran, what each save changed and who made it.

## What this buys you

- **A republish mid-term is safe.** Old attempts keep their version, their tests and their scores.
- **A regrade needs nothing from the student.** Their notebook is on the server.
- **A dispute has an answer.** The change log says who changed what and why.
- **A student cannot grade themselves.** Edited checks are restored, hidden tests are reinjected, and the whole thing runs on your machine, not theirs.
- **A broken autograder is visible** rather than being scored as failure.
