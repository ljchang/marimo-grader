# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "numpy", "marimo-grader-client", "mograder"]
# ///
"""Example instructor notebook: GLM assignment with two questions.

Publish with:
    grader publish docs/examples/glm.py --server http://localhost:8000 \
        --offering <offering-id> --slug glm --title "GLM"
"""

import marimo

__generated_with = "0.21.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np

    from marimo_grader_client import Grader

    g = Grader()  # reads server / offering / assignment / version from this file's PEP 723 block
    return Grader, g, mo, np


@app.cell
def _(mo):
    mo.md(
        r"""
        # Assignment: the General Linear Model

        Work through each question. **Check** runs locally and gives hints;
        **Submit** records an attempt on the server.
        """
    )
    return


@app.cell
def _(g):
    g.signin_button()
    return


@app.cell
def _():
    # === MOGRADER: MARKS ===
    _marks = {"glm-q01": 5, "glm-q02": 5}
    return


@app.cell
def _(mo):
    mo.md(r"""## Q1. Build a boxcar regressor with 10 TRs on, 10 TRs off, for 100 TRs.""")
    return


@app.cell
def _(np):
    ### BEGIN SOLUTION
    boxcar = np.tile(np.r_[np.ones(10), np.zeros(10)], 5)
    ### END SOLUTION
    return (boxcar,)


@app.cell
def _(boxcar, g, np):
    g.check(
        "glm-q01: Boxcar regressor",
        [
            (boxcar.shape == (100,), "boxcar should have 100 time points", 1),
            (np.isclose(boxcar.mean(), 0.5), "half the TRs should be on", 1),
            (boxcar[0] == 1 and boxcar[10] == 0, "start on, switch off at TR 10", 1),
        ],
    )
    return


@app.cell
def _(g):
    g.submit_button("glm-q01")
    return


@app.cell
def _(mo):
    mo.md(r"""## Q2. In two or three sentences, explain why we convolve the boxcar with an HRF.""")
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
    g.submit_button("glm-q02", outputs={"answer": answer.value})
    return


if __name__ == "__main__":
    app.run()
