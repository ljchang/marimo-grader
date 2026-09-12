# HTTP API

For tool authors. The contract that the notebook widget, the web app, and the publish command use. Base path `/api/v1` unless noted.


Base path: `/api/v1`. JSON everywhere. All timestamps are ISO 8601 UTC from the server clock.

## Principals and authentication

| Caller | Credential | How |
|---|---|---|
| Browser (Svelte app) | HttpOnly session cookie `grader_session` + header `X-CSRF-Token` on mutating requests | `GET /auth/login` → SAML → cookie set; `GET /auth/csrf` returns the token for the current session |
| Notebook widget / CLI | `Authorization: Bearer <jwt>` | obtained through the device handshake below |

Errors: `{"error": {"code": "not_enrolled", "message": "..."}}` with 401 (unauthenticated), 403 (forbidden), 404, 409 (conflict), 422 (validation).

### Session endpoints (browser)

- `GET /auth/login?next=/o/abc` → 302 to Dartmouth SAML (or, in dev mode, to `/auth/dev-login`).
- `POST /auth/saml/acs` → SAML assertion consumer; sets cookie; 302 to `next`.
- `GET /auth/saml/metadata` → SP metadata XML.
- `POST /auth/logout` → clears cookie; 302 to `https://logout.dartmouth.edu` in prod.
- `GET /auth/me` → `{"netid": "f00abc1", "display_name": "...", "platform_admin": false, "enrollments": [{"offering_id": "...", "course_slug": "neuroimaging", "term": "2026-fall", "title": "...", "role": "student|ta|instructor"}]}`
- `GET /auth/csrf` → `{"csrf_token": "..."}`
- Dev only (`GRADER_AUTH_MODE=dev`): `GET /auth/dev-login?netid=f00abc1&next=/` sets a session for that NetID (creating the user if needed).

### Device handshake (notebook)

- `POST /auth/device` body `{"client": "dartbrains-tools/0.2.0"}` → `{"device_code": "...", "user_code": "ABCD-1234", "verification_url": "https://.../auth/device/verify?code=ABCD-1234", "expires_in": 600, "interval": 3}`
- `GET /auth/device/verify?code=ABCD-1234` → browser page; requires session (redirects through `/auth/login` if none); on success binds the code to the NetID and renders "You can close this tab."
- `POST /auth/device/token` body `{"device_code": "..."}` → `{"status": "pending"}` (200) while waiting; `{"status": "approved", "access_token": "<jwt>", "token_type": "bearer", "expires_in": 28800, "netid": "f00abc1"}` once approved; `{"status": "expired"}` after expiry.
- JWT claims: `sub` = NetID, `scope` = `"notebook"`, `iat`, `exp` (8 h), `jti`. Signed Ed25519 (`EdDSA`).

## Offerings

- `GET /offerings` → offerings the caller is enrolled in (same shape as `/auth/me.enrollments`, plus `settings`).
- `GET /offerings/{offering_id}` → offering detail incl. `sections` and the caller's `role`.
- `GET /offerings/{offering_id}/assignments` → `[{"id", "slug", "title", "latest_version", "settings": {"due_at", "attempts_allowed", "grade_policy": "latest|highest|first|selected", "environments": ["molab","wasm","discovery"], "log_checks": true}, "questions": [{"id", "qid", "title", "max_points", "grading_mode": "auto|manual|hybrid", "order"}]}]`

## Assignments (instructor)

- `POST /offerings/{offering_id}/assignments` `{slug, title, settings}` → assignment.
- `PATCH /offerings/{offering_id}/assignments/{assignment_id}` `{title?, settings?}` (audited).
- `POST /offerings/{offering_id}/assignments/{assignment_id}/versions` multipart: `instructor_notebook` (file), `student_notebook` (file), `questions` (JSON string: `[{"qid","title","max_points","grading_mode","check_keys":[...]}]`), `cell_hashes` (JSON string) → `{"version": 3, "student_url": "/api/v1/assignment-versions/{id}/student.py"}`
- `GET /assignment-versions/{version_id}/student.py` → student notebook source (public if the offering allows, else enrolled).

## Public alias routes (no prefix, no auth; gated by `offering.settings.public_student_notebooks`, default on)

- `GET /a/{course}/{term}/assignments.json` → `{"course","term","offering_id","title","assignments":[{"slug","title","assignment_id","version","version_id","published_at","due_at","points","environments","questions":[...],"student_url","molab_url"}]}`. What `marimo-book sync-assignments` reads.
- `GET /a/{course}/{term}/{slug}/student.py[?v=N]` → the distributed student notebook, exact bytes the server finalized at publish (headers `X-Grader-Version`, `X-Grader-Version-Id`).
- `GET /a/{course}/{term}/{slug}/molab[?v=N]` → 302 to `https://molab.marimo.io/new/#code/<lzstring>`.

Publishing (`POST .../versions`) is finalized server-side: the server injects `grader-server`, `grader-course`, `grader-term`, `grader-offering-id`, `grader-assignment`, `grader-assignment-id`, `grader-assignment-version`, `grader-version` into the student notebook's PEP 723 block and stores those bytes. It refuses (`422 solution_leak`) if solution or hidden-test markers remain, and returns `200 {"unchanged": true}` when the instructor notebook and question list are identical to the latest version.

## Submissions

- `POST /submissions` (Bearer) body (optional `client_submission_id`: an id per click; a retry with the same id returns the same attempt with `"duplicate": true`):
  ```json
  {"assignment_version_id": "uuid", "question_id": "glm-q03", "notebook": "<source>", "check_results": [], "outputs": {}, "client": {"package": "dartbrains-tools", "version": "0.2.0", "env": "molab"}}
  ```
  → 201 `{"id", "attempt_no", "submitted_at", "status": "received", "version": 2, "latest_version": 3, "stale": true, "duplicate": false}`. Questions resolve against the submitted version's snapshot, so an older copy keeps working after a republish; `stale` tells the widget to suggest the latest copy. 403 `not_enrolled` if the NetID has no active student enrollment in the version's offering; 409 `attempts_exhausted`.
- `GET /submissions/{id}` (owner, or TA/instructor of the offering) → submission incl. `status`, `score` (if any), `feedback`, `render_url`.
- `GET /offerings/{offering_id}/me/submissions?assignment_id=` (student) → own attempts.
- `POST /check-events` (Bearer) `{"assignment_version_id", "question_id", "check_key", "passed": true}` → 202. Best effort; ignored if `log_checks` is off.

## Grading (instructor/TA)

- `GET /offerings/{offering_id}/triage` → `{"awaiting_manual": [{"question_id","qid","count","oldest_submitted_at"}], "inactive_students": [...], "failing_checks": [{"qid","check_key","fail_rate","n"}], "grader_failures": [...]}`
- `GET /offerings/{offering_id}/grid?assignment_id=` → `{"students": [{"netid","display_name","section","last_activity","cells": {"<question_id>": {"state": "none|checking|submitted|graded", "points": 4, "max": 5}}}]}`
- `GET /offerings/{offering_id}/queue?question_id=` → `{"question": {"id","qid","title","max_points","auto_points_max","grading_mode","rubric": {"id","name","items":[{"key","label","points","description"}]} | null}, "items": [submission...]}`. One item per student (their latest attempt), `needs_grading` first, oldest first. Each submission carries `outputs` (the structured answers the widget sent, e.g. text-area values) and `render_url` (worker-rendered HTML, served with a strict CSP and meant for a sandboxed iframe).
- `POST /submissions/{id}/score` `{"manual_points": 3.5, "rubric_scores": {"r1": 2, "r2": 1.5}, "feedback": "...", "final": true}` → score row (audited).
- `GET /offerings/{offering_id}/students/{netid}` → attempt history across assignments.

## Roster (instructor)

- `POST /offerings/{offering_id}/roster/preview` multipart `file` + `source=canvas_csv|banner` → `{"adds": [...], "drops": [...], "moves": [...], "unmatched": [...]}` with rows `{netid, display_name, section}`.
- `POST /offerings/{offering_id}/roster/apply` body = the preview payload (possibly edited) → applied counts (audited).
- `GET /offerings/{offering_id}/roster` → enrollments.

- `POST /offerings/{offering_id}/roster/staff` (instructor) `{netid, role: ta|instructor, ta_sections: [...], display_name?}` → adds or updates a teaching-staff enrollment (audited). Students come from roster import, never from this route.

## Audit

- `GET /offerings/{offering_id}/audit?limit=` (instructor) → every audited action in the offering, newest first: `[{id, at, actor (netid), entity, entity_id, action, before, after, reason}]`. Includes grade changes.
- `GET /admin/audit?limit=` (platform admin) → platform-level entries only (course, offering, user, enrollment, assignment, assignment_version, roster, export) with an `offering` alias; grade rows are excluded because admins do not see student work.

## Operator commands (server shell)

- `grader token <netid> [--offering course/term --role instructor --admin]` → notebook/CLI token, works in any auth mode.
- `grader login-link <netid>` → one-time browser sign-in URL (10 min) exchanged at `GET /auth/exchange?code=`.

## Export

- `GET /offerings/{offering_id}/export/canvas?assignment_ids=a,b` with an uploaded Canvas gradebook on file → CSV.

## Admin (platform admin)

- `GET/POST /admin/courses`, `POST /admin/courses/{id}/offerings`, `POST /admin/offerings/{id}/instructors` `{netid}`.

## Events

- `GET /offerings/{offering_id}/events` → Server-Sent Events: `submission.received`, `submission.graded`, `score.updated`, each with `{"submission_id","question_id","netid"}`.
