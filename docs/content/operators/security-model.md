# Security model

For operators and security reviewers. What data the service holds, who can reach it, and the controls that enforce that. Written to be handed to an institutional review as is.

## Data held

| Data | Where | Retention |
|---|---|---|
| NetID and optional display name | `users` | life of the account |
| Course enrollment and role | `enrollments` | life of the offering |
| Submitted notebooks, written answers, rendered HTML | content-addressed artifact volume | per-offering retention window (deletion job planned) |
| Scores, feedback, per-question grades | database | per institutional policy |
| Audit trail of grade, roster, settings, publish, and export actions | `grade_audit`, append-only | per institutional policy |
| Login events | server logs | one year |

Not held: passwords (none exist), email addresses, affiliation, anything from the identity provider beyond NetID and display name. Logs record user ids, not NetIDs, at the default level.

## Identity

Every human authenticates through the institution's SAML identity provider, including its second factor. Notebooks receive short-lived tokens only after a completed SAML sign-in; see [Single sign-on](single-sign-on.md). A `dev` mode exists for developers' laptops and is refused by the production configuration validator.

## Authorization and isolation

Access is decided server-side on every request. Each route that touches student data resolves the caller's enrollment in the offering named in the path first; a route cannot skip that step without also lacking an offering to query.

- A **student** sees only their own submissions, feedback, and grades. Requests for another student's data return not-found.
- A **TA** sees submissions and history only for the offering they are enrolled in as a TA, and, if scoped, only for their sections.
- An **instructor** sees and changes everything in their offering and nothing outside it.
- A **platform administrator** manages courses, offerings, and instructors, and sees a platform-level audit log. They cannot read submissions, grades, or the roster grid of any offering. If they need to, they add themselves as an instructor, which is itself logged.
- Public routes expose assignment metadata and student notebooks (no solutions) per offering, and can be turned off per offering.

These rules are enforced by an automated test suite that exercises every data-bearing route across two offerings from the wrong side (student to student, TA across sections, staff across offerings, administrator to student data) and runs on every change.

## Submissions are immutable

A submission is an insert-only record bound to the exact assignment version the student opened; the notebook bytes are content-addressed. Grading writes new score records; nothing overwrites. Every grade change, roster change, settings change, publish, and export appends an audit row with actor, time, before, after, and reason.

## Executing student code

Student code runs only in the grading worker, never in the web application or in a grader's browser. The worker:

- prepares the notebook's Python environment outside the sandbox, then
- runs the notebook inside bubblewrap with the filesystem read-only, a private `/tmp`, no network (`--unshare-net`), CPU and address-space limits, and a wall-clock timeout;
- reinjects the instructor's check cells and hidden tests from the stored version, so a student cannot alter what is tested;
- renders the notebook to HTML that the grading view shows inside a sandboxed iframe with a strict content security policy, so a submission cannot run scripts against a grader's session.

## Transport and storage

TLS everywhere with HSTS; a content security policy on the web app that permits form posts only to the identity provider; cookies HttpOnly, Secure, SameSite=Lax; CSRF tokens on state-changing browser requests; CORS limited to the origins where notebooks run. Database and artifacts on encrypted volumes with managed backups. Secrets in an environment file readable only by the deploy user; the service refuses to start in production without them.

## Operations

A single deploy user with SSH key access; root login not used after bootstrap; unattended security updates; fail2ban; images built by CI from a public repository and pulled read-only. Operator break-glass actions (sign-in links, tokens) require shell access and are single-use or time-limited.

## Known limits

- Retention deletion is a manual operation today; the per-offering window is a setting without an automatic job yet.
- Rate limiting relies on the reverse proxy's defaults.
- The platform runs as a pilot on commercial cloud infrastructure pending institutional review; the deployment is portable to an institutional host without code changes.
