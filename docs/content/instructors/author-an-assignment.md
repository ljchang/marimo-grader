# Author an assignment

For instructors and TAs writing assignments. An assignment is one marimo notebook that contains the solutions, the tests, and the marks; the grader derives the student version from it.

## Where instructor notebooks live

Keep them in a private repository. They contain solutions and hidden tests, and the grader refuses to publish any file that still contains those markers. Nothing from the instructor notebook reaches a public site except the student version that publishing generates.

A minimal layout:

```
assignments/
  glm.py
  signal-processing.py
README.md
```

Edit with `uv run marimo edit --sandbox assignments/glm.py`.

## The notebook, cell by cell

The conventions come from [MoGrader](https://github.com/jameskermode/mograder), James Kermode's autograder for marimo notebooks, which the grader uses for stripping solutions, restoring hidden tests, and running checks. Its [documentation](https://github.com/jameskermode/mograder#readme) covers the markers in more depth; [Built on MoGrader](../reference/mograder.md) lists the behaviors that matter here.

**Dependencies.** The PEP 723 block at the top is the environment contract: the same list builds the environment in MoLab, in the browser, on a cluster, on a laptop, and in the grader's sandbox. List everything the notebook imports, plus the two grading packages.

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "numpy", "nilearn", "marimo-grader-client", "mograder"]
# ///
```

**Grader and sign-in.** One cell creates the client; it reads the assignment's identity from the metadata that publishing adds.

```python
@app.cell
def _():
    import marimo as mo
    from marimo_grader_client import Grader
    g = Grader()
    return Grader, g, mo

@app.cell
def _(g):
    g.signin_button()
    return
```

**Marks.** One cell lists every question and its points. Question ids are stable identifiers; the visible title can change, the id should not.

```python
@app.cell
def _():
    # === MOGRADER: MARKS ===
    _marks = {"glm-q01": 5, "glm-q02": 5, "glm-q05": 5}
    return
```

**Solutions.** Put the answer between solution markers. The student version replaces the block with `# YOUR CODE HERE` and assigns `...` to the variables the block defined.

```python
@app.cell
def _(np):
    ### BEGIN SOLUTION
    boxcar = np.tile(np.r_[np.ones(10), np.zeros(10)], 5)
    ### END SOLUTION
    return (boxcar,)
```

**Checks.** A check cell names the question and lists conditions. The text after the colon becomes the question's title in the grader. Each condition is `(passes, message, weight)`. Put stricter conditions inside hidden-test markers; students see the visible ones, the grader runs both.

```python
@app.cell
def _(boxcar, g, mo, np):
    mo.stop(
        boxcar is ...,
        mo.md("**Complete the code cell above first.** This check runs once `boxcar` is defined."),
    )
    g.check(
        "glm-q01: Boxcar regressor",
        [
            (boxcar.shape == (100,), "boxcar should have 100 time points", 1),
            (np.isclose(boxcar.mean(), 0.5), "half the TRs should be on", 1),
            ### BEGIN HIDDEN TESTS
            (boxcar[0] == 1 and boxcar[10] == 0, "start on, switch off at TR 10", 2),
            ### END HIDDEN TESTS
        ],
    )
    return
```

The `mo.stop` guard matters: without it the student version raises on the `...` placeholders, which shows a traceback on the course website and in a fresh MoLab session before the student has done anything.

**Submit.** One button per question.

```python
@app.cell
def _(g):
    g.submit_button("glm-q01")
    return
```

**Written answers.** A text box's value is not part of the notebook file, so pass it as an output. It is stored with the attempt and shown to the grader beside the rendered notebook.

```python
@app.cell
def _(mo):
    answer = mo.ui.text_area(placeholder="Your answer...", full_width=True)
    answer
    return (answer,)

@app.cell
def _(answer, g):
    g.submit_button("glm-q05", outputs={"answer": answer.value})
    return
```

A question with no check is graded by hand. A question with a check is autograded; you can also make it hybrid (part automatic, part by hand) when you publish.

## Grading modes

| Mode | Set by | Score |
|---|---|---|
| auto | a `g.check` exists for the question id | weighted fraction of conditions passed, times the question's points |
| manual | no check, or `--manual qid` at publish | entered by a person in the grading queue |
| hybrid | `--hybrid qid=auto_points` at publish | automatic part plus a manual part |

## Validate before publishing

The publish command refuses a notebook with invalid markers or leaked solutions, but it is faster to catch problems locally:

- Run the instructor notebook once; every check should pass.
- Generate the student version and run it; every check cell should stop with the guard message and nothing should raise. From the grader's `backend` directory: `uv run grader publish --help` shows the flags, and `--student` lets you publish a student notebook you generated yourself.
- Keep computations light. The grader runs each submission in a sandbox with a time limit (five minutes by default) and no network, so any dataset must be small or pre-cached on the worker.

## Datasets

The sandbox has no network. An assignment that needs data from Hugging Face reaches it through `dartbrains_tools.data.localizer`, and the operator warms the worker's cache before grading with `grader warm-cache`, which reads the published notebook's own `get_file`/`download` calls -- so you do not have to list anything. If your notebook builds a path at run time, where that scan cannot see it, list it in the assignment's `required_datasets` setting as `"<repo_id> <filename>"` instead. Either way, ask the operator to re-run the warm step after you publish, or the first submission will fail with a grader error rather than a zero.
