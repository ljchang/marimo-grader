# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "marimo-grader-client", "mograder"]
# ///
"""Demo assignment for marimograder.org.

This is a *student* notebook, in the shape `grader publish` produces: solutions
replaced by `# YOUR CODE HERE`, solution variables left as `...`, hidden tests
stripped down to a `# HIDDEN TESTS` placeholder, and a marks cell listing every
question.

Two things a published assignment has and this one does not, because no grading
server stands behind a documentation page:

* the `grader-*` keys in the PEP 723 block above, which the server writes at
  publish time and the widget reads (see Reference -> Notebook metadata);
* the `g.signin_button()`, `g.submit_button(...)` and `g.feedback(...)` cells,
  which need that server to do anything.

Everything else is real: `g.check` is the same call a student runs in a course,
and it renders here exactly as it does there.
"""

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    from marimo_grader_client import Grader

    g = Grader()  # in a course, reads the assignment's identity from the PEP 723 block
    return g, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Demo assignment: reaction times

    Three questions about a small block of reaction-time data. Work through them the
    way a student would.

    Each question has a cell for your answer and a **Check** cell below it. Check runs
    here in your browser, instantly, as often as you like — it tells you what is still
    wrong, and it is not your grade. Everything you type is kept in this browser and
    goes nowhere else.

    /// admonition | Where sign-in and Submit would be
        type: info

    In a course, a **Sign in** control sits here and each question ends with a
    **Submit** button and a feedback panel — three cells the instructor writes once:

    ```python
    g.signin_button()          # once, at the top
    g.submit_button("q01")     # after each question's check
    g.feedback("q01")          # the score and comments, once graded
    ```

    They talk to a grading server, so they are left out of this demo. [What the
    instructor wrote](what-the-instructor-wrote.md) shows the full notebook.
    ///
    """)
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


@app.function
def keep_between(values, lo, hi):
    # YOUR CODE HERE
    pass


@app.cell
def _(TRIALS, g, mo):
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
            # HIDDEN TESTS
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    /// admonition | The check above is doing two things at once
        type: tip

    It reports what you see — and it also records the result, so that pressing
    **Submit** in a real assignment sends the outcome along with your notebook. And
    one of its conditions is not shown to you: the `# HIDDEN TESTS` comment in the
    check cell is where a stricter condition was removed when this student copy was
    generated. The grader puts it back before scoring, which is why a question that
    passes Check can still lose a point.

    Both behaviours come from the [grading engine](../how-it-works/grading-engine.md).
    ///
    """)
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

    return


@app.cell
def _():
    mean_rt = ...
    # YOUR CODE HERE
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
            # HIDDEN TESTS
        ],
    )
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
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    /// admonition | A written question has no check
        type: info

    Nothing here can tell you whether that answer is good; a person reads it. In a
    course the cell below this one would be

    ```python
    g.submit_button("demo-q03", outputs={"answer": answer.value})
    ```

    A text box's value is not part of the notebook file, so it is passed as an output
    and stored with the attempt. The grader sees it beside the rendered notebook.
    ///
    """)
    return


if __name__ == "__main__":
    app.run()
