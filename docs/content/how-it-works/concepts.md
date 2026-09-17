# Concepts

The words this documentation uses, and what each one is pinned to. Most of them are ordinary, but a few carry weight — *version*, *attempt* and *question id* in particular decide what happens when something goes wrong mid-term.

## Course, offering, term

A **course** is the thing that has a name and a slug: `neuroimaging`. An **offering** is one running of it in one **term**: `neuroimaging/2026-fall`. Everything that concerns students — the roster, the assignments, the grades, the settings — belongs to an offering, never to the course.

This is what lets last year's grades sit untouched beside this year's, and what makes the answer to "can this person see that" always resolvable: a platform administrator creates courses and offerings and names their first instructor, and from then on the instructor runs their own offering.

## Enrollment and role

An **enrollment** binds one person to one offering with one **role**: student, TA, or instructor. Roles live here and nowhere else — in particular they never come from the identity provider, which is only asked *who is this*.

A TA may additionally be scoped to **sections**, in which case they see only those sections' students. Dropping a student ends their enrollment; it deletes nothing.

## Assignment, version, slug

An **assignment** is a named piece of work inside an offering, identified by a **slug**: `glm`. Publishing it creates a **version**, and versions are immutable and numbered. Republish and you get version N+1; students who already opened version N keep working against version N and are graded against version N's tests, forever.

That is the single most important consequence to internalise: **a mid-term fix never retroactively changes how earlier work was graded.** It also means "the assignment" is ambiguous in a way the system is not — when it matters, the docs say *version*.

## Question, id, title, marks

A version has **questions**. Each has:

- a **question id** (`glm-q03`) — permanent, and what attempts, scores and the Canvas column are keyed on;
- a **title** (*Design matrix*) — cosmetic, and safe to reword at any time;
- **marks**, its point value, from the assignment's marks cell;
- a **grading mode**.

Ids and titles come from one string in the notebook. A check labelled `"glm-q03: Design matrix"` splits at the first colon: id before, title after. [What the instructor wrote](../demo/what-the-instructor-wrote.md) shows this.

| Grading mode | Set by | Score comes from |
|---|---|---|
| auto | a check exists for the id | the conditions that passed, weighted, times the question's marks |
| manual | no check, or `--manual qid` at publish | a person in the grading queue |
| hybrid | `--hybrid qid=auto_points` at publish | an automatic part plus a manual part |

## Check, condition, weight, hidden test

A **check** is one call in the notebook naming a question and listing **conditions**. Each condition is `(passes, message, weight)`: the message is what the student reads when it fails, the weight is its share of the question's marks.

Conditions inside hidden-test markers are removed from the student copy and put back at grading time. So a check has two audiences: it is a teaching tool when the student runs it, and part of the grade when the grader does.

One check per question. Marks are summed per id, so a second check with the same id makes the question count twice.

## Attempt and submission

Pressing Submit creates a **submission**: an immutable record of the *whole notebook* at that moment, bound to one question and to the version the student opened. Each is numbered as an **attempt**, and nothing ever overwrites an earlier one.

Submitting question 3 stores the whole notebook, not question 3's cells — which is why the grading view can show a grader the student's actual working, and why an attempt can be re-graded later without asking the student for anything.

The **grade policy** decides which attempt counts:

| Policy | Counts |
|---|---|
| `latest` (default) | the most recent attempt |
| `highest` | the attempt with the highest total |
| `first` | the first attempt |
| `selected` | the one an instructor pinned on the student's history page |

`attempts_allowed` caps how many a student may make per question; unlimited by default.

## Artifact

Notebooks, rendered HTML and roster uploads are stored as **artifacts**: files addressed by the hash of their content. Two students who submit byte-identical notebooks occupy one artifact; a submission's bytes cannot change without changing its address. The database holds the metadata and points at these.

## Run

Each submission queues two **runs**:

- **render** — turn the notebook into HTML for the grading view and the student portal;
- **autograde** — execute it in a sandbox against the instructor's tests and write a score.

Runs can fail independently and be retried, which is why "the autograder could not run this" is a distinct state from "this scored zero". The distinction matters: one is the student's problem, the other is yours.

## Score, release, audit

A **score** is a record, not a field — every save writes a new one, so a grade has a history. A score can be **released** to the student or held as a draft.

Every action that could change a grade or who is in the course appends to the **audit trail**: who, when, before, after, and a reason if one was given. It is append-only and visible to instructors as the [change log](../instructors/change-log.md).

## Two more, for completeness

**MoLab** is marimo's hosted notebook service — a full Python environment in a browser tab, with its own account, unrelated to your university sign-in. **WASM** means the notebook runs in the page itself, with no server at all; fine for light assignments, and the mode the [demo](../demo/try-an-assignment.md) on this site uses.
