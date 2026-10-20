# Changelog

All notable changes to `marimo-grader` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two things release from this repository on their own tags. The service — the
backend, worker and web app, shipped as container images — releases on `v*`.
The notebook widget, `marimo-grader-client` on PyPI, releases on `client-v*`
and is versioned separately, because a student's notebook and the server it
submits to upgrade at different times by design. Entries below say which.

## [Unreleased]

## [0.1.9] — 2026-10-19

### Changed

- **Publish a new version from the assignment page, with the instructor
  notebook alone.** The grader builds the student copy and reads the questions
  as `grader publish` does (`services/student_copy.py`, now shared with the
  CLI). A preview comes first -- the version number, the questions and how
  each is graded, what is new, removed or changed, the student copy to
  download -- and **Publish version N** makes it live
  (`POST .../versions/preview`, `POST .../versions/from-notebook`). The hand
  upload of two notebooks plus question JSON is gone from the page; its API
  remains for the CLI.

### Fixed

- Version history times carry their UTC offset; they showed as hours in the
  future on servers whose database returns naive timestamps.

## [0.1.8] — 2026-10-19

### Changed

- **Assignments is a table.** One row per assignment with its access, status,
  opens / due / closes, version, questions, points and grading; click a column
  to sort, again to reverse (due date by default). Click rows to select them
  (or **Select all**) and **Export Canvas CSV** takes the selection. The title
  opens a new **assignment page**: key settings, a **Settings** button that
  opens the form in place, the student notebook, Open in molab and a copyable
  launch link, the questions with their grading queues, and the version history
  (`GET /offerings/{id}/assignments/{aid}/versions`). Uploading a version by
  hand moved there, under the `grader publish` command that is the usual way.

## [0.1.7] — 2026-10-19

### Changed

- **Needs attention groups grading failures by cause.** One entry per
  assignment and cause instead of one line per submission, saying what happened,
  whose move it is, and whether a retry can help (`services/failures.py`).
  **Retry all** re-queues a group (`POST /offerings/{id}/retry`), and the page
  follows each retried submission to its outcome -- queued, grading, graded,
  waiting for a hand grade, or failed again with the new reason
  (`GET /offerings/{id}/retry-status`). The awaiting-grade line no longer repeats
  a question id used as its title.

## [0.1.6] — 2026-10-19

### Security

- **The safety scan excuses only findings the release also had.** 0.1.5
  excused a flagged line whenever its text appeared anywhere in the released
  copy, so a line the release merely contained (in a string, say) could cover
  a student's import. A finding is now excused only when the released copy was
  flagged for the same thing on an identical line.

## [0.1.5] — 2026-10-19

### Changed

- **Renders show the code.** The worker renders submissions with
  `--include-code`, so the grading view (and a student's own) shows each cell's
  code above its output instead of only "passed". The submission view has
  **Rendered** / **Code** tabs, the second being the source as submitted.
  `grader rerender` re-renders older submissions one at a time while the queue
  is otherwise idle.

### Fixed

- **A student is not refused for a line the course gave them.** The safety
  scan now runs before grading and excuses a flagged line that appears, as
  written, in the released copy. A thresholding release shipped `import io` in
  its setup cell, and every submission from it failed before running.

## [0.1.4] — 2026-10-19

### Added

- **Student preview.** Instructors and TAs can switch their own view of an
  offering to a student's (`PUT /offerings/{id}/preview`, *Preview as a
  student* on the Student view page) and test an assignment the way the class
  will: the student list and portal, `close_at` and the deadline enforced,
  student-scoped storage credentials, staff pages refused -- in the web app and
  in notebooks signed in as them. Release dates do not apply, so an exam can be
  tried before it opens; submissions remain test attempts. A banner offers
  *Exit preview*. New `enrollments.preview_student` column (migration
  `c4d8e1f2a903`).

## [0.1.3] — 2026-10-19

### Added

- **Private assignments and exams.** `visibility: enrolled` keeps an
  assignment out of `assignments.json` and serves its notebook (`/a/.../student.py`,
  `/molab`) only to signed-in members of the offering, by session or notebook
  token. `release_at` / `due_at` / `close_at` form one window for the notebook,
  its storage data and submissions; staff are exempt. A private assignment
  without a `release_at` stays closed and is left out of students' assignment
  list, so an exam can be built in place. `grader publish` sends settings with
  the create, so a new private assignment is never briefly public. `late_policy: reject`
  refuses work after the deadline, otherwise it is accepted and marked `late`.
  A new `/a/<course>/<term>/<slug>/launch` link signs a student in and lands on
  their portal, which now offers *Open in molab* and *Download .py* and shows
  the window. Storage credentials and presigned URLs no longer outlive an
  assignment's `close_at`. Docs: *For instructors → Exams and private assignments*.
- **Whole-notebook submission.** `notebook_submission` adds a `notebook`
  question that takes the entire notebook: manual when `notebook_points` > 0, a
  graded-on-arrival receipt at 0. Turning it on lets a version publish without
  a `_marks` cell; `notebook` is a reserved qid.
- **`autograde: false`** stores and renders submissions without running checks,
  and **`render_timeout`** gives an assignment longer than the worker default.
  **`render: false`** skips the re-run too: the grading view shows the submitted
  code and a *Saved files* panel of what the student wrote under
  `storage.private()/<slug>/` (`GET /submissions/{id}/files`, presigned links,
  files changed after `due_at` flagged).
- `grader publish` gains `--private/--public`, `--release`, `--due`, `--close`,
  `--late-policy`, `--no-autograde`, `--notebook-points` and `--render-timeout`.

- **Client 0.2.0: course storage in the notebook.** `marimo_grader_client.storage`
  is the notebook side of the storage broker, moved here from
  dartbrains-tools so any course on the grader gets it: `signin_button()` /
  `connect()`, `course()`, `private()`, `group()`, `assignment(slug)`, a
  durable `@cache`, `local_path()` for anything that wants a file. One
  obstore store per mount with a self-renewing credential; the token is
  cached where the runtime keeps things (`~/.config/marimo-grader`, or
  molab's `.env`, which it recognises by its sandbox). `GRADER_*` names
  throughout; `storage.configure(server=...)` for a course's default.
  `assignment_card(slug)` links a chapter to its assignment on the grader.
  dartbrains-tools 0.3 wraps this and keeps its imports working.

### Fixed

- **Client 0.1.2:** a sign-in token restored from the browser's storage now
  reaches the kernel as well. The widget showed "signed in" but left the
  `token` trait empty, so Python code keyed off it -- the storage layer's
  `connect()` -- saw nobody. Only a fresh click synced it.

## [0.1.2] — 2026-09-18

### Added

- **Storage broker (service).** A signed-in notebook can ask the grader for
  storage credentials: `POST /offerings/{id}/storage/session` returns two
  Cloudflare R2 temporary credentials scoped to exactly the prefixes the
  enrollment may reach — course data, released assignments and the shared
  cache read-only; the student's own area, group folders and private cache
  read-write; staff additionally the student areas they may grade.
  `POST …/storage/presign` gives a single presigned URL for runtimes that
  cannot sign requests, `GET …/storage/me` the mount table without minting.
  The grader stays in the control path only; bytes flow between the
  notebook and R2 directly. Student prefixes are an HMAC of the NetID, so a
  listing never exposes the roster. Assignments gain optional `release_at`
  and `close_at` settings; outside that window the prefix is absent from
  every credential, so pre-release data is unreachable rather than hidden.
  Off until `GRADER_STORAGE_ENABLED` and the Cloudflare values are set;
  see the configuration reference and `docs/storage-architecture.md`.
- New tables `groups`, `group_members` and the append-only
  `storage_grants` audit (migration `b7c2e9d41f03`).
- `scripts/r2_spike.py`, the isolation experiment the design rests on.

## [0.1.1] — 2026-09-17

### Security

- **Every login-link code is now refused at the device poll, not just the
  operator one.** `poll()` compared the code's client against the literal
  `"operator-login-link"` rather than checking `LOGIN_LINK_CLIENTS`, so only
  half the set was excluded. Both kinds of login-link row are minted
  pre-approved and unconsumed, and the poll mints a notebook token from any
  such row — so `POST /auth/device/token`, given the code out of a sign-in
  email, returned an eight-hour notebook token without the link ever being
  opened. An email code lives seven days; a device code lives ten minutes.
  Impact was limited — the holder of the code is the intended user, and the
  token grants only their own submit-and-read access — but the two paths are
  meant to be disjoint, and `consume_login_code()` already checked the set.
  (#19)

### Removed

- A roster test helper, `_netids`, that nothing called and that could not have
  worked if anything had: the endpoint it read returns a list, so its first
  line would raise. (#18)

### Documentation

- **The documentation site was reworked** ([marimograder.org](https://marimograder.org/)):
  a live demo assignment that runs in the reader's browser alongside the
  instructor notebook it was generated from, an Authentication section covering
  the device handshake, SAML, email sign-in links and token lifetimes, the
  deployment runbook moved out of `deploy/README.md` and onto the site as eight
  operator pages, and a How it works section. (#14, #15)
- Corrections found by reviewing the new pages against the code: an unreleased
  score is *provisional* rather than hidden — the student portal shows it and
  the widget labels it — `grader seed` defaults `--students` to two example
  NetIDs, `warm-cache` scans the version's instructor artifact rather than the
  published copy, the Ed25519 key-type error is raised at first token mint
  rather than at startup, and `GRADER_USE_BUBBLEWRAP=1` enables the sandbox
  without requiring it. (#15)
- The sidebar labels the index page "Home" instead of repeating the site name,
  and the header carries marimo-book's mark until the grader has one of its
  own. (#16, #17)

## [0.1.0] — 2026-09-16

First tagged release: the service as deployed for the DartBrains pilot —
SAML and notebook sign-in, publishing, immutable per-attempt submissions,
sandboxed autograding, the grading web app, roster import and Canvas export.
