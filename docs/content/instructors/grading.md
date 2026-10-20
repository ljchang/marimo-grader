# Grading

For instructors and TAs. Where to look, what to grade, and how scores become grades.

## The course page

The course page answers one question first: who needs my attention? A list at the top shows only the items that need a person:

![The course page: a Needs attention list above the class progress grid, one column per question](../../images/course-page.png)

The screenshot shows a course with one assignment open and nothing waiting: the attention list collapses to a single line and the grid carries the detail.

- submissions waiting for a grade, per question, with a **Grade now** button;
- students with no activity for a week while an assignment is open;
- checks that more than a third of the class has been failing in the last two days;
- submissions the autograder could not run, one entry per cause, with what to do about it.

When there is nothing, it says so in one line.

Below it, **Class progress** is a grid of students by question for the selected assignment. A cell shows the points earned, *waiting* for an ungraded submission, *failed* for a grading failure, or a dash. The footer tallies each column. Clicking a student opens their attempt history; clicking a hand-graded question's header opens its queue. The page updates itself as submissions arrive.

## The assignments page

**Assignments** lists every assignment, grouped into *Open now*, *Coming up* and *Closed* (folded away until you open it). Each row shows the one date that matters next -- *Due in 5 days*, *Opens Nov 18*, *Closed* -- the class's progress as a bar (graded, waiting for you, failed, not submitted), and the average score over students whose work is fully graded. Labels appear only for what is unusual: *Hidden from students* (private, with no open date yet), *Enrolled only*, *Not re-run*.

**Grade** shows how many answers are waiting for you and goes straight to the queue when only one question has them; **Review** opens the assignment when everything is graded automatically. **Settings** opens the assignment's settings in a side panel. **More** has *Copy student link*, *Preview as a student*, *Upload corrected notebook* and *Export to Canvas*. The filters above the table narrow it to what needs grading, or to one group; search matches the title.

Click a row to select it, and shift-click to select a run of rows; **Select all** takes every row shown. The bar that appears at the bottom exports the selection to Canvas or changes their due date at once.

Click an assignment's title for its page: a sentence on where it stands, and under **Grading** one row per question with a strip of marks, one per enrolled student, colored by where that student stands. Click a mark to open that student's answer in the queue.

## The grading queue

Each hand-graded or hybrid question has a queue: one entry per student, showing their latest attempt, ungraded ones first and oldest first.

![The grading queue: the rendered notebook on the left, score, feedback, and the student's written answer on the right](../../images/grading-queue.png)

The rendered notebook fills the left pane; the right pane holds the score, the feedback box, and any written answers the student submitted.

The left pane is the student's notebook, rendered by the grader after execution: each cell's code above the output it produced, so you read the answer and not only whether a check passed. **Code** switches to the notebook source exactly as submitted. Written answers submitted through a text box appear in the right pane under **Submitted answers**. Student code never runs in your browser.

The right pane holds the score. If the question has a rubric, each item has its own points and the total sums them; you can override the total. Feedback is a free text box the student sees.

/// admonition | "Release this grade to the student" does not withhold it
    type: warning

The checkbox is on by default. Unticking it marks the score **provisional**, not private: the student portal still shows the points and the feedback, and the notebook adds *Provisional score; a final grade may follow.*

So an unreleased score is a score the student can see and you have said you may change — not a draft they cannot. If you need marks to stay invisible until the whole class is graded, do not save them yet.
///

Keyboard: `j` and `k` move between students, `f` jumps to the feedback box, and `Cmd+Enter` (or `Ctrl+Enter`) saves. New submissions that arrive while you grade are added to the end of the queue without moving you.

Staff can submit to their own offering, so an instructor's test submissions appear here too — that is the intended way to rehearse an assignment before releasing it.

## How a score becomes a grade

Every save creates a new score record; nothing is overwritten, and each save is in the change log with who, when, before, after, and an optional reason.

The grade for a question is derived from the assignment's grade policy over the student's attempts:

| Policy | Counts |
|---|---|
| `latest` (default) | the most recent attempt |
| `highest` | the attempt with the highest total |
| `first` | the first attempt |
| `selected` | the attempt an instructor pins on the student's history page |

Autograded points and hand-entered points add up to the question's total. An assignment's grade is the sum of its questions.

## Retrying failed grading

If the autograder could not run a submission, the course page groups it with every other submission of that assignment that failed for the same reason: twenty copies of one error are one problem. Each entry says what happened in plain words, whose move it is, and whether a retry can help; **Error as recorded** shows the raw message.

- **The student's move** -- the safety check refused something they wrote, or the notebook cannot run (a variable defined in two cells, a syntax error). A retry runs the same notebook and fails the same way, so the button reads **Retry anyway**; the student needs to fix and resubmit.
- **The grader's move** -- a timeout, data the sandbox could not reach (ask the operator to run `grader warm-cache`), a package that would not install, or an unexpected error. **Retry** (or **Retry all**) is worth trying.

After a retry the entry stays on the page and follows each submission: *queued*, *grading*, then *graded*, *graded automatically, waiting for you* (a question you grade by hand), or *failed again* with the new reason. **Clear results** removes the finished rows.

## Attempt limits and regrading

`attempts_allowed` on the assignment caps attempts per question; the widget tells students when they have used them. Republishing an assignment does not regrade old submissions; they stay bound to the version they were made against.
