# Exams and private assignments

Every student notebook is public by default: it carries no solutions, and a course book republishes it anyway. An exam is different, because the questions themselves are the secret. Setting an assignment's **visibility** to *enrolled* keeps it away from anyone outside the class, and three dates decide when the class can reach it.

## The window

| Setting | What it controls |
|---|---|
| `visibility: enrolled` | Left out of `assignments.json`; its notebook goes only to signed-in members of the offering. To anyone else it does not exist. |
| `release_at` | From this moment students can download the notebook, open it in molab, and read `storage.assignment("<slug>")`. |
| `due_at` | The submission deadline. After it, `late_policy` decides: accepted and marked **late** (the default), or `reject`. |
| `close_at` | The hard end: no notebook download, no data, no submissions. It may be later than the deadline, so students can still re-run their work after submitting. Leave it blank on a private assignment and the form closes it at the deadline. |

Staff are never held to the window, so you can open, run and submit your own exam before students see it; those attempts are marked as tests and stay out of the gradebook.

The window also limits storage credentials. A student's credential covering an assignment with a `close_at` expires at the close instead of an hour later, and in the final minute the assignment is no longer granted at all. Data a student already downloaded stays on their machine — the window controls when they can *start*, and the deadline is enforced when they submit.

## Reading the whole notebook

**Whole-notebook submission** adds one question, `notebook`, that is not tied to a cell: the student submits the entire notebook and you read it in the grading queue. Give it points to grade it by hand, or leave it at 0 for a receipt that is stored and rendered but never asks for a score. With it on, the instructor notebook needs no `_marks` cell.

Turn **autograde** off when nothing should be run against checks. Submissions are still rendered: the grader re-runs the notebook and stores the HTML you read. Raise `render_timeout` (30–3600 s) when that re-run is a real analysis.

Turn **re-run** (`render`) off when the notebook is too heavy for the grader — an analysis over a few gigabytes of data will not fit on a small worker, and the time it takes grows with the data. The grading view then shows the submitted code and a **Saved files** panel: everything the student wrote under `storage.private()/<slug>/` (figures, CSVs, statistical maps), with download links. Ask students to save their results there:

```python
out = storage.private()
fig.savefig("result.png")
out.upload("result.png", "final-exam/figures/result.png")
out.put("final-exam/answers.csv", answers_df)  # typed by extension
```

A student's private storage stays writable after the deadline, so each file shows when it last changed, and one modified after `due_at` is flagged.

## Who sees what

A submission, its notebook, render and saved files are visible to the student who made it and to the course staff: instructors, and TAs (a TA assigned to sections sees only those sections). Another student gets the same 404 as for a submission that does not exist. In storage, each student's credential names only their own `users/<offering>/<id>/` prefix, so one student's notebook cannot read a classmate's files either.

One thing the grader cannot control: a notebook opened in molab lives at a molab URL that anyone holding the link can view. Students should not share their molab link during the exam.

## Publishing one

```bash
grader publish exam.py --server https://grader.dartbrains.org \
    --offering neuroimaging/2026-fall --slug final-exam --title "Final exam" \
    --private --release 2026-11-20T09:00-05:00 --due 2026-11-22T23:59-05:00 \
    --close 2026-11-23T23:59-05:00 --late-policy reject \
    --no-autograde --notebook-points 100
```

Settings you leave out keep their current values, and every one of them can be changed later under **Assignments → Edit settings**. Put the exam's data under `storage.assignment("final-exam")` from an instructor session; students read it once the window opens.

## What students see

Link to the assignment from the course page with its launch URL rather than the notebook itself:

```text
https://grader.dartbrains.org/a/<course>/<term>/<slug>/launch
```

It sends a signed-out reader through Dartmouth sign-in and lands on their portal, where the exam row offers **Open in molab** and **Download .py**, or says when it opens or that it has closed. Do not add a private assignment to a course book's `assignment:` key: the book fetches and republishes what that key names.
