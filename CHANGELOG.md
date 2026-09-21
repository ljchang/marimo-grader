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

### Added

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
