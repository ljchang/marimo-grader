# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "marimo-grader-client", "mograder"]
# ///
"""Instructor notebook for the demo assignment on marimograder.org.

This is the file an instructor writes and keeps in a private repository. It holds
the solutions, the hidden tests and the marks. Publishing derives the student
notebook from it:

    grader publish docs/examples/reaction-times.py \
        --server https://grader.example.edu \
        --offering methods/2026-fall --slug reaction-times \
        --title "Reaction times"

The student copy that produces is on the site as the demo assignment; see
https://marimograder.org/demo/what-the-instructor-wrote/ for the two side by side.
"""

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    from marimo_grader_client import Grader

    g = Grader()  # reads server / offering / assignment / version from this file's PEP 723 block
    return g, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Assignment: reaction times

    Three questions about a small block of reaction-time data.

    Each question has a cell for your answer, a **Check** cell that runs instantly and
    tells you what is still wrong, and a **Submit** button that records an attempt on the
    server. Sign in once at the top. Check as often as you like; it is not your grade.

    The last question is written, and an instructor reads it.
    """)
    return


@app.cell
def _(g):
    g.signin_button()
    return


@app.cell
def _():
    # === MOGRADER: MARKS ===
    _marks = {"demo-q01": 4, "demo-q02": 3, "demo-q03": 3}
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Q1. Keep the plausible trials

    `TRIALS` holds fourteen reaction times in milliseconds from one participant. A few
    are not real responses: some are far too fast to be a decision, others are trials
    where the participant looked away and came back.

    Write `keep_between(values, lo, hi)` so it returns a **new list** holding just the
    values from `lo` to `hi`, bounds included, in the order they appeared.

    ```python
    keep_between([100, 400, 9000], 150, 1500)   # -> [400]
    ```
    """)
    return


@app.cell
def _():
    TRIALS = [412, 388, 455, 1980, 402, 377, 439, 61, 421, 466, 398, 3125, 430, 409]
    return (TRIALS,)


@app.cell
def _():
    def keep_between(values, lo, hi):
        ### BEGIN SOLUTION
        return [v for v in values if lo <= v <= hi]
        ### END SOLUTION

    return (keep_between,)


@app.cell
def _(TRIALS, g, keep_between, mo):
    _probe = keep_between([400], 150, 1500)
    mo.stop(
        _probe is None,
        mo.md("**Complete the function above first.** It should `return` a list."),
    )

    _plausible = [412, 388, 455, 402, 377, 439, 421, 466, 398, 430, 409]
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
    return


@app.cell
def _(g):
    g.submit_button("demo-q01")
    return


@app.cell
def _(g):
    g.feedback("demo-q01")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Q2. The average of what is left

    Set `mean_rt` to the mean of the trials Q1 keeps — the eleven plausible ones, not
    all fourteen — rounded to one decimal place.

    *`statistics.fmean` is already imported below, or do the arithmetic yourself.*
    """)
    return


@app.cell
def _():
    from statistics import fmean

    return (fmean,)


@app.cell
def _(TRIALS, fmean, keep_between):
    ### BEGIN SOLUTION
    mean_rt = round(fmean(keep_between(TRIALS, 150, 1500)), 1)
    ### END SOLUTION
    return (mean_rt,)


@app.cell
def _(g, mean_rt, mo):
    mo.stop(
        mean_rt is ...,
        mo.md("**Complete the code cell above first.** This check runs once `mean_rt` is defined."),
    )

    g.check(
        "demo-q02: The average of what is left",
        [
            (isinstance(mean_rt, (int, float)), "mean_rt should be a number", 1),
            (
                isinstance(mean_rt, (int, float)) and abs(mean_rt - 417.9) < 0.05,
                "mean_rt should be 417.9 — the mean of the eleven trials Q1 keeps, to one "
                "decimal place",
                2,
            ),
            ### BEGIN HIDDEN TESTS
            # Catches the mean of all fourteen trials (697.4), which the visible
            # tolerance already excludes, and any hard-coded 417.9 that ignores TRIALS.
            (
                isinstance(mean_rt, (int, float)) and abs(mean_rt - 697.4) > 1,
                "mean_rt should come from the trimmed trials, not all fourteen",
                1,
            ),
            ### END HIDDEN TESTS
        ],
    )
    return


@app.cell
def _(g):
    g.submit_button("demo-q02")
    return


@app.cell
def _(g):
    g.feedback("demo-q02")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Q3. What the trimming costs

    Dropping the implausible trials made the average a better summary of this
    participant's responding. It also threw away data.

    In two or three sentences: name one thing that could produce a 3125 ms trial other
    than the participant looking away, and say what you would want to know about those
    discarded trials before reporting the mean.
    """)
    return


@app.cell
def _(mo):
    answer = mo.ui.text_area(placeholder="Your answer...", full_width=True)
    answer
    return (answer,)


@app.cell
def _(answer, g):
    # UI element values are not part of the notebook file, so pass them as outputs;
    # they are stored with the attempt and shown to the grader next to the notebook.
    g.submit_button("demo-q03", outputs={"answer": answer.value})
    return


@app.cell
def _(g):
    g.feedback("demo-q03")
    return


if __name__ == "__main__":
    app.run()
