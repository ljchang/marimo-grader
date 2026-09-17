# Author an assignment

For instructors and TAs writing assignments. An assignment is **one notebook** containing the solutions, the tests and the marks; the student version is derived from it, never written by hand.

If you have not seen the two side by side, start with [What the instructor wrote](../demo/what-the-instructor-wrote.md) — it is this page's content as a worked example, and the [file it is built from](https://github.com/ljchang/marimo-grader/blob/main/docs/examples/reaction-times.py) is a reasonable thing to copy.

## Where instructor notebooks live

In a **private repository**. They contain solutions and hidden tests, and publishing refuses any file that still has those markers in it. Nothing from the instructor notebook reaches a public site except the student version publishing generates.

```
assignments/
  glm.py
  signal-processing.py
README.md
```

Edit with `uv run marimo edit --sandbox assignments/glm.py`.

## The notebook, cell by cell

The conventions come from the [grading engine](../how-it-works/grading-engine.md); its [documentation](https://github.com/jameskermode/mograder#readme) covers the markers in more depth.

### Dependencies

The PEP 723 block at the top is the environment contract: the same list builds the environment in MoLab, in the browser, on a cluster, on a laptop and in the grading sandbox. List everything the notebook imports, plus the two grading packages.

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "numpy", "nilearn", "marimo-grader-client", "mograder"]
# ///
```

Keep it lean. Every package here is installed in the grading sandbox for every distinct dependency list, and a heavy list makes the first submission after each publish slower.

### Grader and sign-in

One cell creates the client; it reads the assignment's identity from the metadata publishing adds.

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

### Marks

One cell lists every question and its points. Ids are stable identifiers; the visible title can change, the id should not.

```python
@app.cell
def _():
    # === MOGRADER: MARKS ===
    _marks = {"glm-q01": 5, "glm-q02": 5, "glm-q05": 5}
    return
```

### Solutions

Put the answer between solution markers. The student version replaces the block with `# YOUR CODE HERE`, and assigns `...` to the variables the block defined.

```python
@app.cell
def _(np):
    ### BEGIN SOLUTION
    boxcar = np.tile(np.r_[np.ones(10), np.zeros(10)], 5)
    ### END SOLUTION
    return (boxcar,)
```

### Checks

A check cell names the question and lists conditions. The text before the first colon is the question id; the text after it becomes the title. Each condition is `(passes, message, weight)`. Put stricter conditions inside hidden-test markers: students see the visible ones, grading runs both.

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

/// admonition | The `mo.stop` guard is not optional
    type: warning

Without it the student version raises on the `...` placeholders the moment it opens — a wall of tracebacks on your course website and in every fresh session, before the student has done anything. It is the single most common authoring mistake.
///

Write the messages for the student who is stuck, not for yourself. *"boxcar should have 100 time points"* is a hint; *"assertion failed"* is not.

### Submit and feedback

One of each per question. The feedback cell is optional but worth including: it shows the score and comments in the notebook once grading is done, so the student does not have to leave to find out how they did.

```python
@app.cell
def _(g):
    g.submit_button("glm-q01")
    return

@app.cell
def _(g):
    g.feedback("glm-q01")
    return
```

### Written answers

A text box's value is not part of the notebook file, so pass it as an output. It is stored with the attempt and shown to the grader beside the rendered notebook.

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

Forget `outputs=` and the question submits an empty answer, which is the kind of mistake you find out about while grading.

## Grading modes

| Mode | Set by | Score |
|---|---|---|
| auto | a `g.check` exists for the question id | weighted fraction of conditions passed, times the question's points |
| manual | no check, or `--manual qid` at publish | entered by a person in the [grading queue](grading.md) |
| hybrid | `--hybrid qid=auto_points` at publish | the automatic part plus a manual part |

Hybrid is how you say *five points for running, five for explaining it*.

## Designing questions that autograde well

**One `check()` per question.** Marks are summed per id, so a second call with the same id makes the question count twice.

**Check the thing, not the path to it.** A condition on a returned value lets a student solve it their own way; a condition on a variable name they were never told about fails people who were right.

**Give partial credit deliberately.** Weights are the mechanism — a shape check worth 1 and a values check worth 3 turns a near-miss into a 25 % rather than a 0.

**Use hidden tests for generality, not for surprises.** The good use is an edge case that a solution fitted to the visible examples would miss. The bad use is a condition the student had no way to anticipate.

**Guard every check.** See above.

**Keep it fast.** Each submission runs in a sandbox with a five-minute wall clock and no network. If a notebook takes minutes, the deadline hour will be unpleasant — subsample, precompute, or move the expensive part out of the graded path.

## Validate before you publish

Publishing refuses a notebook with invalid markers or leaked solutions, but catching it locally is faster:

1. **Run the instructor notebook.** Every check should pass. If yours does not, the answer key is wrong.
2. **Generate the student version and run that.** Every check cell should stop with its guard message and **nothing should raise**. This is the run that catches a missing `mo.stop`.
3. **Read the messages** as a stuck student would.

`uv run grader publish --help` lists the flags; `--student` lets you publish a student notebook you generated yourself.

## Datasets

The grading sandbox has **no network**, so an assignment can only read data that is already cached on the worker.

Assignments that fetch data through `dartbrains_tools.data.localizer` are handled automatically: the operator runs `grader warm-cache`, which reads your **instructor** notebook's own `get_file`/`download` calls — you do not have to list anything, and it sees the references inside your solutions. If your notebook builds a path at run time, where that scan cannot see it, list it in the assignment's `required_datasets` setting as `"<repo_id> <filename>"`.

Either way: **tell your operator to re-run the warm step after you publish.** Otherwise the first submission fails with a grader error rather than a zero — recoverable, but only after somebody notices. They can confirm with `grader warm-cache --check --slug <your-slug>`, which downloads nothing and exits non-zero if anything is missing.

Keep the data small. A per-condition beta image is about 2 MB; raw preprocessed BOLD is about 57 MB per subject.

## Test it as a student

Staff can submit, so do. Publish to your offering, open the student notebook the way your class will, sign in, answer a question wrongly, submit, read the feedback, then answer it correctly and submit again. Twenty minutes, and it catches the things this page cannot tell you about your own assignment.
