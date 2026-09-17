# What the instructor wrote

There is one file. The instructor writes a notebook containing the solutions, the tests and the marks, keeps it in a private repository, and publishes it; the student notebook is *derived*, never written by hand. This page shows the same assignment you just tried, from the other side.

The two files are in the repository: the instructor's [`docs/examples/reaction-times.py`](https://github.com/ljchang/marimo-grader/blob/main/docs/examples/reaction-times.py) and the student copy it produces, [`docs/content/demo/assignment.py`](https://github.com/ljchang/marimo-grader/blob/main/docs/content/demo/assignment.py).

## A question with a solution

=== "Instructor notebook"

    ```python
    @app.cell
    def _():
        def keep_between(values, lo, hi):
            ### BEGIN SOLUTION
            return [v for v in values if lo <= v <= hi]
            ### END SOLUTION

        return (keep_between,)
    ```

=== "What the student gets"

    ```python
    @app.cell
    def _():
        def keep_between(values, lo, hi):
            # YOUR CODE HERE
            pass

        return (keep_between,)
    ```

The markers are the contract. Everything between `### BEGIN SOLUTION` and `### END SOLUTION` is removed and replaced with a placeholder, and `grader publish` refuses to continue if any marker survives into the student copy.

## A question whose answer is a value

When the solution block assigned variables rather than defining a function, stripping leaves those variables defined as `...` — Python's `Ellipsis` — so the notebook still parses and the cells below it still have something to refer to.

=== "Instructor notebook"

    ```python
    @app.cell
    def _(TRIALS, fmean, keep_between):
        ### BEGIN SOLUTION
        mean_rt = round(fmean(keep_between(TRIALS, 150, 1500)), 1)
        ### END SOLUTION
        return (mean_rt,)
    ```

=== "What the student gets"

    ```python
    @app.cell
    def _():
        mean_rt = ...
        # YOUR CODE HERE
        return (mean_rt,)
    ```

This is why check cells open with a guard:

```python
mo.stop(
    mean_rt is ...,
    mo.md("**Complete the code cell above first.** This check runs once `mean_rt` is defined."),
)
```

Without it, an untouched notebook raises on the `...` the moment it opens — a wall of tracebacks on the course website and in every fresh session, before the student has done anything wrong. With it, each unanswered question says what it is waiting for. It is the single easiest thing to forget when authoring.

## The checks, and the ones that are hidden

=== "Instructor notebook"

    ```python
    g.check(
        "demo-q01: Keep the plausible trials",
        [
            (
                keep_between(TRIALS, 150, 1500) == _plausible,
                "keep_between(TRIALS, 150, 1500) should drop the three implausible trials "
                "and keep the other eleven in order",
                2,
            ),
            (
                keep_between([], 150, 1500) == [],
                "an empty list of values gives an empty list back",
                1,
            ),
            ### BEGIN HIDDEN TESTS
            # Both bounds are inclusive. A student who wrote `lo < v < hi` passes
            # everything visible above, because no trial sits exactly on a bound.
            (
                keep_between([150, 1500], 150, 1500) == [150, 1500],
                "lo and hi are themselves inside the range",
                1,
            ),
            ### END HIDDEN TESTS
        ],
    )
    ```

=== "What the student gets"

    ```python
    g.check(
        "demo-q01: Keep the plausible trials",
        [
            (
                keep_between(TRIALS, 150, 1500) == _plausible,
                "keep_between(TRIALS, 150, 1500) should drop the three implausible trials "
                "and keep the other eleven in order",
                2,
            ),
            (
                keep_between([], 150, 1500) == [],
                "an empty list of values gives an empty list back",
                1,
            ),
            # HIDDEN TESTS
        ],
    )
    ```

Each condition is `(passes, message, weight)`. The student sees three of the four marks and can chase them with Check; the fourth is put back when the submission is graded, so an answer that happens to satisfy the visible conditions still has to be right.

The comment that survives in the student copy is deliberate. It tells the student a hidden condition exists — which is fairer than a silent deduction — without telling them what it is.

Note also what the label does. The text before the first colon, `demo-q01`, is the question's permanent id; the text after it, *Keep the plausible trials*, is the title shown in the grading app and can be reworded at any time. Ids are what attempts, scores and the Canvas column are keyed on, so they should never change once students have submitted.

## The marks

```python
@app.cell
def _():
    # === MOGRADER: MARKS ===
    _marks = {"demo-q01": 4, "demo-q02": 3, "demo-q03": 3}
    return
```

One cell, copied into the student notebook unchanged, listing every question and what it is worth. Publishing reads it to build the assignment's question list, and a question here with no `g.check` anywhere — `demo-q03` — is a hand-graded question.

## The written question

=== "Instructor notebook"

    ```python
    @app.cell
    def _(mo):
        answer = mo.ui.text_area(placeholder="Your answer...", full_width=True)
        answer
        return (answer,)


    @app.cell
    def _(answer, g):
        g.submit_button("demo-q03", outputs={"answer": answer.value})
        return
    ```

=== "What the student gets"

    ```python
    @app.cell
    def _(mo):
        answer = mo.ui.text_area(placeholder="Your answer...", full_width=True)
        answer
        return (answer,)


    @app.cell
    def _(answer, g):
        g.submit_button("demo-q03", outputs={"answer": answer.value})
        return
    ```

Identical — there is nothing to strip. The detail worth knowing is `outputs=`: what a reader types into a `mo.ui` element is not part of the notebook file, so passing it explicitly is what gets it stored with the attempt and shown to the grader beside the rendered notebook. Forget it and the question submits an empty answer.

## What publishing does to the rest of the file

| In the instructor notebook | In the student copy |
|---|---|
| `### BEGIN SOLUTION` … `### END SOLUTION` | `# YOUR CODE HERE`, and any variables the block defined set to `...` |
| `### BEGIN HIDDEN TESTS` … `### END HIDDEN TESTS` | a single `# HIDDEN TESTS` comment |
| the marks cell | unchanged |
| `g.check`, `g.signin_button`, `g.submit_button`, `g.feedback` | unchanged |
| the PEP 723 dependency block | unchanged, plus the `grader-*` keys the server writes: which course, which assignment, which version |
| — | a hash of every check and marks cell, so an edited check can be detected and the instructor's version restored before grading |

That last row is what makes the student copy safe to publish on a public website: it contains no solutions, and editing a check to make it pass gains nothing.

## Next

- [Author an assignment](../instructors/author-an-assignment.md) — the conventions in full, including grading modes and datasets.
- [Publish](../instructors/publish.md) — the command, what a version is, and keeping a course website in step.
- [The grading engine](../how-it-works/grading-engine.md) — where the markers and the sandbox come from.
