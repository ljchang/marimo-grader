# Security model

For operators and security reviewers. What data the service holds, who can reach it, and the controls that enforce that. Written to be handed to an institutional review as is.

## Data held

| Data | Where | Retention |
|---|---|---|
| NetID, and a display name if the identity provider sends one | `users` | life of the account |
| A preferred name, if the person sets one | `users` | life of the account |
| Course enrollment and role | `enrollments` | life of the offering |
| Submitted notebooks, written answers, rendered HTML | content-addressed artifact volume | per-offering retention window (deletion job planned) |
| Scores, feedback, per-question grades | database | per institutional policy |
| Audit trail of grade, roster, settings, publish, export and sign-in-link actions | `grade_audit`, append-only | per institutional policy |
| Login events | server logs | one year |

**Not held:** passwords — none exist; email addresses; affiliation; anything from the identity provider beyond a NetID and a display name. Where an email address is used at all, for [sign-in links](../auth/email-links.md), it is converted to a NetID and discarded: it is a lookup key, never a column. Logs record user ids rather than NetIDs.

## Identity

Every human authenticates through the institution's SAML 2.0 identity provider, including its second factor, which happens inside the identity provider and is never seen here. Notebooks receive short-lived tokens only after a completed SAML sign-in, through a device-style handshake in which credentials never enter the notebook. See [How sign-in works](../auth/index.md).

A `dev` mode exists for developers' laptops; the production configuration validator refuses to start with it, and that refusal is a startup failure rather than a warning.

Two additional paths exist for the window before an institution has registered the service, and as break-glass if it becomes unavailable:

- **Operator sign-in links** require shell access on the host to mint, are single-use, and expire in thirty minutes.
- **Email sign-in links** are off by default; when enabled they are limited to one configured domain, are sent only to NetIDs that already have an active enrollment (the route never creates a user), are rate-limited per NetID, are recorded in the audit trail, and return an identical response whether or not the address matched — so the form cannot be used to test roster membership. They are meant to be turned off once SSO works, since proving control of a mailbox is a weaker claim than SAML with a second factor.

## Authorization and isolation

Access is decided server-side on every request. Each route that touches student data resolves the caller's enrollment in the offering named in the path *first*; a route cannot skip that step without also lacking an offering to query. Roles live in the grader's own tables and are never read from SAML attributes.

- A **student** sees only their own submissions, feedback and grades. Requests for another student's data return not-found.
- A **TA** sees submissions and history only for the offering they are enrolled in as a TA, and, if scoped, only for their sections.
- An **instructor** sees and changes everything in their offering and nothing outside it.
- A **platform administrator** manages courses, offerings and instructors, and sees a platform-level audit log. They **cannot** read submissions, grades, or the roster grid of any offering. If they need to, they add themselves as an instructor — which is itself an audited action.
- **Public routes** expose assignment metadata and student notebooks, which contain no solutions, per offering, and can be turned off per offering.

These rules are enforced by an automated test suite that exercises every data-bearing route across two offerings from the wrong side — student to student, TA across sections, staff across offerings, administrator to student data — and runs on every change.

## Submissions are immutable

A submission is an insert-only record bound to the exact assignment version the student opened; the notebook bytes are content-addressed, so they cannot change without changing their address. Grading writes new score records; nothing overwrites. Every grade change, roster change, settings change, publish and export appends an audit row with actor, time, before, after and reason.

A grade is therefore reconstructible after the fact: which version was graded, which bytes were submitted, which tests ran, and who changed what.

## Executing student code

Student code runs only in the grading worker — never in the web application, never in a grader's browser. The worker:

- prepares the notebook's Python environment **outside** the sandbox, because installation needs network and a writable disk;
- runs the notebook **inside bubblewrap** with the filesystem read-only, a private `/tmp`, no network (`--unshare-net`), an address-space cap and a wall-clock timeout;
- **reinjects the instructor's check cells and hidden tests** from the stored version, so a student cannot alter what is tested — edited cells are detected by hash, replaced, and reported;
- renders the notebook to HTML that the grading view shows inside a **sandboxed iframe with a strict content security policy**, so a submission cannot run scripts against a grader's session.

The worker container is run with three Docker confinement options relaxed. That is what permits the inner sandbox to exist at all: without them bubblewrap cannot create its namespaces, and student code would fall back to the container's isolation alone. See [Sandbox and data](sandbox-and-data.md#docker-gets-in-the-way-once).

## Transport and storage

TLS everywhere with HSTS. A content security policy on the web app that permits form posts only to the identity provider. Cookies `HttpOnly`, `Secure`, `SameSite=Lax`, carrying an opaque signed session id with all state server-side, so a session can be revoked. CSRF tokens on every state-changing browser request, enforced in the dependency every authenticated route resolves.

CORS is limited to the origins where notebooks run, and **credentials are never allowed cross-origin**: no cookie crosses an origin, and every route a notebook calls is bearer-authenticated with a token the student approved in a first-party tab.

Database and artifacts on encrypted volumes with managed backups. Secrets in an environment file readable only by the deploy user; the service refuses to start in production without them.

## Operations

A single deploy user with SSH key access; root login unused after bootstrap; unattended security updates; fail2ban; a cloud firewall in front of the host's own. Images are built by CI from a public repository and pulled read-only — the host builds nothing. Operator break-glass actions require shell access and are single-use or time-limited.

## Known limits

Stated plainly, because a reviewer will find them anyway:

- **Retention deletion is manual.** The per-offering window is a setting; the job that acts on it does not exist yet.
- **Single-token revocation is not exposed.** Every request checks a revocation table, but no route writes to it; revoking a notebook token today means rotating the signing key, which revokes all of them.
- **Rate limiting relies on the reverse proxy's defaults**, apart from the per-NetID limits on sign-in links.
- **The deployment is a pilot on commercial cloud infrastructure**, pending institutional review. It is portable to an institutional host without code changes.
- **There is one host.** No high availability, and a restore is a manual procedure that should be rehearsed once a term.

## Questions a review usually asks

**Where is student work stored, and is it encrypted?** On an encrypted volume on the application host, content-addressed, with metadata in an encrypted managed database. Both are backed up; backups leave the host.

**Can an administrator read student work?** No. That is enforced in code, not policy, and tested. They can grant themselves an instructor role, and doing so is recorded.

**What happens if a student edits the grading code in their notebook?** It is detected by hash and replaced with the instructor's version before grading, and the feedback says so.

**Can student code reach the network or the filesystem?** No network, and a read-only filesystem apart from one working directory. Anything it needs must be cached before it runs.

**What does the identity provider release?** A NetID, and optionally a display name. Nothing else is requested or stored.
