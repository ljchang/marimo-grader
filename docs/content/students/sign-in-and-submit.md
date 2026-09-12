# Sign in and submit

For students. How checking, signing in, submitting, and feedback work inside an assignment notebook.

## Check first, submit when ready

Every question has two actions, and they mean different things.

**Check** runs in your notebook, instantly, as often as you like. It tells you whether your answer passes the visible tests and gives hints when it does not. Checks are for learning; they are not your grade.

**Submit** records an attempt on the grader. It sends your whole notebook, tagged with the question you submitted, and returns an attempt number and time. Autograded questions come back with a score and feedback within about a minute. Written questions show *waiting for grade* until a person reads them.

Some assignments also run hidden tests when you submit, so a question that passes Check can still lose points. The feedback says which test failed.

## Sign in once

The first time you press Submit, the notebook asks you to sign in.

1. Press **Sign in with Dartmouth**. A new tab opens on your university's sign-in page (Duo included). The notebook shows a short code in case the tab does not open; you can enter it by hand on the page that opens.
2. Sign in as usual. The tab says *you can close this tab* when it is done.
3. Back in the notebook, the button changes to *Signed in as* your NetID.

The sign-in lasts eight hours in that browser. Your password never enters the notebook: the notebook only receives a short-lived token that identifies you to the grader.

If the button says **sign-in is not available yet**, the course has not finished setting up university sign-in. Keep working; Check still runs, and Submit opens as soon as sign-in is enabled. Your work is safe in MoLab or on your computer meanwhile.

## Attempts

You can usually submit a question more than once. Each submission is a separate attempt with its own score, and nothing is overwritten. Which attempt counts is your instructor's setting: the latest, the highest, the first, or one they choose. The assignment page says which, and whether attempts are limited.

Pressing Submit twice by accident does not create two attempts.

## Versions and the "newer version" notice

Instructors sometimes republish an assignment mid-term to fix a typo or a test. Your open notebook keeps working and is graded against the version you opened. After submitting you may see a note that a newer version exists; open the assignment page again to get the current copy if you want it. Nothing you submitted is lost.

## Feedback

Feedback appears in the notebook right after grading, and it also stays on the grader's website even after your MoLab session is gone. Open the grader and sign in to see every assignment, every attempt, its score, and the instructor's comments.

## If something goes wrong

- *The notebook source is not readable in this environment*: the notebook could not read its own file, which happens in some browser-only setups. Download the notebook and submit from MoLab or your computer.
- *Could not reach the grader*: the browser cannot reach the grading server, often a network restriction. Try another network, or download and submit later.
- A red traceback in a Check cell after you have written an answer means your code raised an error. Read the last line of the traceback; it is the same message you would get running the code anywhere.
