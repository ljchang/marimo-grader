# DartBrains Grader

A multi-tenant, FERPA-appropriate grading service for [marimo](https://marimo.io) assignments.
Students open a notebook (MoLab, WASM, or a local kernel), sign in with Dartmouth SSO from
inside the notebook, and click **Submit**. Instructors and TAs grade in a web app. Grades export
to Canvas.

The design document is in [`docs/design.html`](docs/design.html); the API contract is in
[`docs/api.md`](docs/api.md).

```
backend/   FastAPI service + worker  (Python, PostgreSQL, SQLAlchemy 2, Alembic, python3-saml)
frontend/  Instructor, TA and student UI  (Svelte 5 runes, TypeScript, Vite)
client/    grader-client: the anywidget students see in the notebook  (Python, anywidget)
deploy/    nginx config for the same-origin production deployment
docs/      design document and API contract
```

## How it fits together

* **Identity.** Browsers sign in through Dartmouth SAML (Shibboleth + Duo) and get an HttpOnly
  session cookie. Notebooks never see credentials: the widget starts a device-style handshake,
  the student approves it in a browser tab, and the notebook receives an 8-hour token bound to
  their NetID.
* **Submissions are immutable.** Every Submit stores the whole notebook as a content-addressed
  artifact and records an attempt for one question. The worker autogrades with
  [MoGrader](https://github.com/jameskermode/mograder)'s engine (used as a library, not as a
  server) and renders the notebook to HTML for the grading view.
* **Authorization is per offering.** Roles (student, TA, instructor) live on enrollments. Every
  route resolves the caller's enrollment first. Platform admins manage courses but cannot read
  student work.
* **Audit.** Grade, roster, settings, and export actions append to `grade_audit`.

## Local development

Requirements: `uv`, `pnpm`, Docker (for PostgreSQL only; the test suite runs on SQLite).

```bash
cp .env.example .env                      # dev defaults: GRADER_AUTH_MODE=dev
docker compose up -d postgres

cd backend
uv sync --all-extras
uv run alembic upgrade head
uv run grader seed                        # course + offering, instructor "prof", two students
uv run grader-api                         # http://localhost:8000  (docs at /api/docs)

cd ../frontend
pnpm install && pnpm dev                  # http://localhost:5173, proxies /api to :8000
```

Sign in during development at `http://localhost:8000/api/v1/auth/dev-login?netid=prof`
(any NetID works; `prof` is the seeded instructor and platform admin).

Run the worker in a second terminal (needs the `worker` extra, which installs mograder and marimo):

```bash
cd backend && uv run grader-worker
```

### Tests

```bash
cd backend && uv run pytest && uv run ruff check src tests
cd frontend && pnpm check && pnpm build
cd client && uv run pytest
```

## Publishing an assignment

Write one marimo notebook with MoGrader markers (`### BEGIN SOLUTION`, `### BEGIN HIDDEN TESTS`,
a `_marks = {...}` cell, and `check("glm-q01: Load the data", [...])` calls). Then:

```bash
cd backend
uv run grader publish path/to/glm.py --server http://localhost:8000 \
    --offering <offering-id> --slug glm --title "GLM" --manual glm-q05
```

The command signs you in through the device handshake, generates the student version, uploads
both, and writes `glm_student.py` with the server, offering, assignment, and version ids embedded
in its PEP 723 block. That file is what dartbrains.org links to. Inside it, the assignment cells
use `grader-client`:

```python
from grader_client import Grader
g = Grader()                 # reads server/ids from the notebook's PEP 723 block
g.signin_button()
g.check("glm-q01: Load the data", [(bold.shape[0] == 128, "Expected 128 volumes")])
g.submit_button("glm-q01")
```

## Production

`docker compose up -d --build` starts PostgreSQL, migrations, the API, the worker, a static
frontend build, and nginx. Before that:

1. Set every secret in `.env` (`GRADER_ENV=prod` refuses to start otherwise): session secret,
   Ed25519 JWT key, SAML SP certificate and key, IdP certificate.
2. Register the SP with Dartmouth IT. The metadata is served at `/api/v1/auth/saml/metadata`.
   The IdP metadata, a working SP metadata template, and the registration email template are in
   the pbs_knowledge repository.
3. Put TLS certificates in `deploy/certs/` (or set `TLS_CERT_DIR`).
4. Submit the deployment for Dartmouth's security and privacy review (see design §13).

## Status

Phase 1 skeleton (see design §16). Done: schema and migrations, SAML SP and dev login, device
handshake and notebook tokens, immutable submissions, worker with MoGrader integration, triage
and grid endpoints, manual scoring with audit, roster import from Canvas CSV and Banner files,
Canvas gradebook export, the Svelte UI, and the notebook widget. Open spikes from the design
document (§15) still apply, most importantly a live test against the Dartmouth IdP and the
device handshake from a MoLab notebook.

MIT.
