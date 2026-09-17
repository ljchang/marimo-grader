# Overview

For the person running the server. What the system is made of, what it needs, and what a deploy actually does.

The reference deployment is **one small virtual machine plus a managed PostgreSQL database**. That is enough for a course; it has no horizontal-scaling story yet and does not need one. Nothing is built on the server — images are built by CI and pulled.

## The shape of it

```
GitHub push to main ──► images.yml ──► ghcr.io/ljchang/marimo-grader-backend
                                       ghcr.io/ljchang/marimo-grader-web
                                                      │  docker compose pull
                                                      ▼
   host (Ubuntu 24.04, 2 vCPU / 4 GB)          managed PostgreSQL 16
   ├─ proxy    Caddy :80/:443 — TLS, security headers, static frontend
   ├─ web      FastAPI (uvicorn), /api and /a                 (private network,
   ├─ worker   grading: render + autograde in bubblewrap       sslmode=require)
   └─ migrate  alembic upgrade head, one-shot, before the rest
```

| Service | Image | Does |
|---|---|---|
| `proxy` | `marimo-grader-web` | Caddy: obtains the certificate, serves the built Svelte app, proxies `/api` and `/a` to `web` |
| `web` | `marimo-grader-backend` | the HTTP API, SAML, publishing, everything a browser or a notebook talks to |
| `worker` | `marimo-grader-backend` | claims queued runs: renders submissions to HTML, autogrades them in the sandbox |
| `migrate` | `marimo-grader-backend` | runs `alembic upgrade head` once and exits; a failure stops the deploy before anything else changes |

## The volumes

| Volume | Holds | Back up? |
|---|---|---|
| `artifacts` | submitted notebooks, rendered HTML, roster uploads — content-addressed | **yes** — this is student work and it is not in the database |
| `hf_cache` | datasets the grading sandbox is allowed to read | no, but warm it (see [Sandbox and data](sandbox-and-data.md)) |
| `uv_cache` | downloaded packages | no |
| `sandboxes` | prepared per-assignment Python environments | no |
| `caddy_data`, `caddy_config` | TLS certificates | no — reissued automatically |

Grades, roster, audit trail and submission metadata are in PostgreSQL; the notebooks themselves are on the artifacts volume. A backup needs both, and they have to be recent relative to each other.

## What a deploy is

`./deploy.sh` on the host: pull both images at the configured tag, fix volume ownership for the non-root container user, run migrations, start the services, wait for the health check, prune old images. Roughly a minute.

Every push to `main` builds and publishes `:main`; `./deploy.sh <tag>` runs any specific build or release tag instead. Migrations are forward-only.

Nothing about a deploy disturbs open student notebooks. They hold the assignment *version* they opened, which is immutable, and a notebook that submits mid-restart retries.

## Sizing

2 vCPU / 4 GB is the floor rather than a recommendation: the worker executes student notebooks with scientific Python, and 2 GB leaves no headroom. Grading is the only thing on the box that is ever busy — the API serves a course, not the internet.

The database is small. A course of a few hundred students generates tens of thousands of rows; the notebooks are the bulk, and they are on disk.

## What it needs from the institution

| Need | Why |
|---|---|
| A hostname and DNS control | Caddy obtains the certificate on first start, so DNS must resolve before the first deploy |
| SAML registration | so people can sign in — see [SAML](../auth/saml.md). The service runs happily in `disabled` mode until this arrives |
| Nothing from Canvas | roster import and grade export are CSV, by design; no Canvas API access is needed |

## Where to go

1. [Deploy](deploy.md) — infrastructure, secrets, first deploy, verification.
2. [Email delivery](email-delivery.md) — only if you want [email sign-in links](../auth/email-links.md).
3. [Sandbox and data](sandbox-and-data.md) — the bubblewrap check, and warming the dataset cache. Do this before the first assignment is due, not after.
4. [Staging](staging.md) — a second host, if you want one.
5. [Backups and upgrades](backups-and-upgrades.md) — and test a restore once a term.
6. [Troubleshooting](troubleshooting.md) — when something is wrong.
7. [Security model](security-model.md) — written to be handed to an institutional review as is.
