# Try an assignment

The fastest way to understand this tool is to be a student for five minutes. There is a real assignment attached to this page. Press **Assignment** in the header, or **Open assignment** on the card at the bottom, and it slides up in a drawer along the bottom of the window — its own notebook, running in your browser, while this page stays readable above it.

Nothing is installed and nothing is sent anywhere. The first open takes a few seconds while the browser fetches Python.

## What to do

1. **Read Q1 and write the function.** `keep_between(values, lo, hi)` should return the values from `lo` to `hi`, bounds included. Replace the `# YOUR CODE HERE` line and delete the `pass`.
2. **Watch the check below it.** Before you answer it says *Complete the function above first* — that is the check waiting, not an error. Once the function returns a list the check runs and tells you which conditions pass. Get one wrong on purpose and read what it says.
3. **Do Q2.** It asks for a value rather than a function, so its answer cell starts as `mean_rt = ...`. That `...` is what a stripped solution leaves behind.
4. **Read Q3.** It is a written question, so it has a text box and no check. A person reads that one.

The drawer is drag-resizable, **Minimize** tucks it down to its bar without stopping the notebook, and your answers save into this browser as you type — close the tab and they are still there tomorrow.

## What is real here, and what is missing

Everything you interact with is the real thing: this is a student notebook in the shape `grader publish` produces, and **Check** is the same `g.check(...)` call a student runs in a course, rendering the same callouts and the same per-condition marks.

Three controls are missing, because a documentation page has no grading server behind it:

| In a course | What it does | Why it is not here |
|---|---|---|
| `g.signin_button()` | starts the sign-in handshake, once per notebook | there is no server to sign in to |
| `g.submit_button("demo-q01")` | records an attempt for that question | nothing to record it against |
| `g.feedback("demo-q01")` | shows the score and the instructor's comments | no attempt, no feedback |

In a real assignment those sit at the top and after each question, and the page looks like this:

![An assignment page on a course website, with the launch buttons in the header and the sign-in control at the top of the notebook](../../images/dartbrains-assignment-page.png)

There is also a **fourth** thing you cannot see, and that one is deliberate even in a course: each check cell here ends with a `# HIDDEN TESTS` comment. In the instructor's copy that comment is a stricter condition, removed when the student copy was generated and put back at grading time. It is why a question that passes Check can still lose a point — and why the feedback tells you which condition failed.

## Then read the other side

[What the instructor wrote](what-the-instructor-wrote.md) puts the instructor's notebook and this student copy side by side, so you can see exactly what publishing removed.

If you want the full student path instead — MoLab, a cluster, a laptop, signing in, attempts, feedback — start at [Open an assignment](../students/open-an-assignment.md).

## Running the demo yourself

The two notebooks are ordinary files in the repository. With [uv](https://docs.astral.sh/uv/) installed:

```bash
# the student copy, the one in the drawer above
uv run marimo edit --sandbox \
  https://raw.githubusercontent.com/ljchang/marimo-grader/main/docs/content/demo/assignment.py

# the instructor copy, with solutions and hidden tests
uv run marimo edit --sandbox \
  https://raw.githubusercontent.com/ljchang/marimo-grader/main/docs/examples/reaction-times.py
```

`--sandbox` reads the dependency list inside the notebook and builds an environment for it, so it runs the same way it does in the drawer.
