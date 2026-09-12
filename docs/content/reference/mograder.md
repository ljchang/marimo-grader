# Built on MoGrader

For anyone who wants to know where the grading engine comes from, what marimo-grader adds on top of it, and which of its behaviors you need to be aware of.

marimo-grader does not implement autograding itself. It uses [MoGrader](https://github.com/jameskermode/mograder), an open-source autograder for marimo notebooks written by [James Kermode](https://warwick.ac.uk/fac/sci/eng/people/james_kermode/) at the University of Warwick and released under the MIT license. MoGrader is installed as an ordinary Python dependency; marimo-grader does not fork or vendor it, and improvements that belong upstream are contributed there.

## What marimo-grader uses from MoGrader

| MoGrader piece | What it does here |
|---|---|
| Authoring markers (`### BEGIN SOLUTION`, `### BEGIN HIDDEN TESTS`, the `MOGRADER: MARKS` cell) | The notebook conventions instructors write in. `grader publish` calls MoGrader's marker validation and solution stripping to produce the student version. |
| `mograder.runtime.check` | The `check()` a student runs in the notebook, wrapped by `marimo-grader-client` so results are also recorded for submission. |
| Cell hashes (`mograder-cell-hashes` in the PEP 723 block) and the integrity check | Detects check cells or marks cells a student edited, and restores the instructor's versions before grading. |
| Hidden-test reinjection | Puts the hidden tests back into the submitted notebook so the autograder sees more than the student did. |
| The sandboxed runner | Executes the notebook with resource limits, a wall-clock timeout, an AST safety scan, and, in production, inside bubblewrap with no network. |
| Check weights and the JSONL sidecar | Partial credit per check and the machine-readable results the worker turns into a score. |

## What marimo-grader adds

MoGrader ships its own single-course server, a hub that spawns marimo sessions per user, a SQLite gradebook, and shared-secret tokens. marimo-grader replaces those layers with a multi-course service: single sign-on, immutable per-attempt submissions, a PostgreSQL schema with an audit trail, roster import, a grading web app, Canvas export, and the notebook widget that submits from the browser. The division is deliberate: the engine is the part that must be correct and reproducible, and it is better maintained upstream than copied.

## Things worth knowing

- **Question keys are check labels.** MoGrader keys every check by the text before the first colon of its label, so `check("glm-q03: Design matrix", ...)` belongs to question `glm-q03`. marimo-grader uses the same key as the stable question id and takes the text after the colon as the question title.
- **One `check()` per question.** MoGrader sums marks per label. Put visible and hidden conditions in the same `check()` list rather than writing a second call for the same key, or the question counts twice.
- **Hidden tests live inside the check list.** The `### BEGIN HIDDEN TESTS` block is removed from the student copy and reinjected at grading time. Students see a `# HIDDEN TESTS` placeholder comment; that is expected, not a leak.
- **The student copy assigns `...` to solution variables.** Stripping a solution leaves the variables defined as `Ellipsis`, so check cells should guard with `mo.stop(any(v is ... for v in (...)), ...)` before comparing values. Without the guard, an unfinished notebook shows tracebacks in the check cells.
- **Grading needs the environment prepared in advance.** MoGrader can build a venv from the notebook's PEP 723 block, and marimo-grader does this outside the sandbox, once per distinct dependency list, then runs the notebook inside bubblewrap with `--no-sandbox`. Inside the sandbox there is no network and the filesystem is read-only, so anything the notebook needs must be installed or cached before it runs.
- **A bubblewrap detail marimo-grader works around.** In its bubblewrap mode MoGrader mounts a private tmpfs over `/tmp` but writes its HTML output and the check sidecar to `/tmp` outside the one directory it binds read-write, so the results vanish when the sandbox exits. marimo-grader keeps every per-run temp file inside the bound directory. This should be fixed upstream; until it is, do not run MoGrader's bubblewrap mode directly with a `/tmp` temp directory.
- **Pinned version.** The worker pins the MoGrader version it ships with (currently 0.3.x) and rewrites each notebook's `mograder` requirement to match, so the checks that run during grading are the same code that scores them. Upgrading MoGrader is a deliberate step: run marimo-grader's test suite against the new version before changing the pin.
- **MoGrader's other transports are unused.** Its Moodle integration, HTTPS server, hub, and workshop mode are not part of marimo-grader.

## Attribution

If you publish work that used this system, please cite MoGrader alongside marimo-grader. The MoGrader repository is https://github.com/jameskermode/mograder and its package is `mograder` on PyPI.
