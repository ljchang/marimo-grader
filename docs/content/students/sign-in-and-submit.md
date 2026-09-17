# Sign in and submit

For students. What checking and submitting actually do, how signing in works, and what to do when something goes wrong.

## Check and Submit are not the same thing

Every question has two actions, and the difference between them is the thing worth understanding.

| | **Check** | **Submit** |
|---|---|---|
| Runs | in your notebook | on the grader |
| Costs you | nothing, any number of times | an attempt |
| Tells you | which visible tests pass, and why | your score, usually within a minute |
| Counts? | **no** | yes |

Check is for learning. Use it constantly — get a condition wrong on purpose and read what it says. Nobody sees your checks except, in aggregate, your instructor, who may see that half the class is stuck on the same one.

Submit records an attempt: it sends your whole notebook, tagged with the question you submitted, and returns an attempt number and a time.

## Hidden tests

Some checks end with a `# HIDDEN TESTS` comment. That marks a condition your instructor wrote and did not show you; it is put back when your work is graded.

This is why a question that passes Check can still lose a point. It is not a trick — the comment is there precisely so you know a hidden condition exists — and when one fails, the feedback tells you which. The usual cause is an answer that is right for the examples you were given and wrong in general: an edge case, an empty input, a boundary.

## Sign in once

The first time you press Submit, the notebook asks you to sign in.

1. Press **Sign in**. A tab opens on your university's sign-in page, second factor and all. The notebook also shows a short code like `ABCD-1234`, in case the tab was blocked — you can open the link it shows and type the code by hand.
2. Sign in as usual. The tab says *you can close this tab* when it is done.
3. Back in the notebook, the button becomes *Signed in as* your NetID.

That lasts **eight hours in that browser**, across every assignment from the same grader. Your password never enters the notebook: it receives only a short-lived token saying who you are. (The mechanism, if you are curious: [Notebook sign-in](../auth/notebook-sign-in.md).)

If the button says **sign-in is not available yet**, your course has not finished setting up university sign-in. Keep working — Check still runs, and Submit opens as soon as it is enabled. Nothing you do meanwhile is lost.

Some courses also offer *email me a link* on the grader's sign-in page, which works if you are already on the roster. It exists as a fallback; your university sign-in is the normal way in.

## Attempts

You can usually submit a question more than once. Each submission is a separate attempt with its own score, and **nothing is overwritten**. Which one counts is your instructor's setting — the latest, the highest, the first, or one they choose — and the assignment page says which, and whether attempts are limited.

Pressing Submit twice by accident does not create two attempts.

If you have used your attempts, the notebook tells you rather than silently failing.

## What gets sent

Your **whole notebook**, not just the question you pressed Submit on, plus the results of the checks you ran and anything typed into a text box for that question. So:

- Work on other questions is included — which is fine, and how a grader can see your working.
- A written answer only arrives if the question was set up to send it, which your instructor handles. If a text box is followed by a Submit button, it is being sent.
- Your notebook is read from disk at the moment you click, so last-second edits count.

## Versions and the "newer version" notice

Instructors sometimes republish an assignment mid-term to fix a typo or a test. Your open notebook keeps working, and it is graded against the version you opened — this is guaranteed, not best-effort.

After submitting you may see a note that a newer version exists. Open the assignment page again if you want the current copy. Nothing you have already submitted is affected.

## If something goes wrong

**"The notebook source is not readable in this environment"** — the notebook could not read its own file, which happens in some browser-only setups. Download it and submit from MoLab or your own computer.

**"Could not reach the grader"** — your browser cannot reach the grading server. Often a network restriction: try another network. Your work is safe; you can submit later.

**"The sign-in code expired"** — the code is good for ten minutes. Press Sign in again.

**A red traceback in a Check cell, after you have written an answer** — your code raised an error. Read the last line; it is the same message you would get running that code anywhere.

**A traceback mentioning `Ellipsis` or `...`** — a cell is using an answer that has not been filled in yet. Look above it for the question you skipped.

**Submitted, and it says *waiting for grade*** — expected for written questions, which a person reads. For a code question it means the grader is still running; if it stays that way for a long time, tell your instructor: there is a **Retry** button on their side, and that state is a problem on the server, not a zero for you.

## Where your grades live

In the [student portal](feedback-and-grades.md) — every assignment, every attempt, every score and comment — which outlives the MoLab session you did the work in.
