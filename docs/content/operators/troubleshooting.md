# Troubleshooting

Symptoms, in the order they tend to appear, with the first thing to check.

Start here, always:

```bash
curl -fsS https://<host>/api/health
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail 50 web worker proxy
```

`/api/health` reports the environment and the auth mode without needing a session, which settles "is it running and how is it configured" in one request.

## The service will not start

| In the log | Means |
|---|---|
| `Refusing to start in prod with missing configuration: …` | exactly what it says; the named settings are absent. This check is deliberate — do not set `GRADER_ENV=dev` to get past it |
| `GRADER_EMAIL_LOGIN_ENABLED=true … requires GRADER_SMTP_HOST` | email links are on with no relay. Set the host, or set `GRADER_MAIL_TRANSPORT=console` |
| `GRADER_JWT_PRIVATE_KEY_PEM must be an Ed25519 key` | the key is a different algorithm — regenerate it with the command in [Deploy](deploy.md#generate-the-secrets) |
| The migration container exits non-zero | a migration failed; the rest of the deploy stopped on purpose. Read its log before retrying |

## No certificate

Caddy obtains one on first start, so the hostname must resolve to the host **before** the first deploy. If it did not, fix DNS, wait for propagation, and restart the proxy. Let's Encrypt rate-limits repeated failures, so do not loop on it.

## Sign-in

See [SAML](../auth/saml.md#when-something-is-wrong) for identity-provider symptoms, and [Sessions and tokens](../auth/sessions-and-tokens.md) for cookie ones. The two that reach an operator most often:

**Everyone was signed out at once.** `GRADER_SESSION_SECRET` changed between deploys. It must be stable.

**Sign-in succeeds and the person is enrolled in nothing.** The NetID from the identity provider is not the NetID the roster was keyed on. Compare one real account's `eduPersonPrincipalName` local part against its Canvas *SIS Login ID*.

## Students cannot submit

**"Could not reach the grader"** — the browser cannot reach the server from the origin the notebook is running on. Nearly always a missing entry in `GRADER_CORS_ORIGINS`; the student's browser console names the origin. MoLab's per-session `*.molab.run` subdomains are covered by a regular expression rather than the list.

**"sign-in is not available yet"** — `GRADER_AUTH_MODE=disabled`. Expected before registration; Check still works.

**"The notebook source is not readable in this environment"** — the kernel could not read its own file, so there is nothing to submit. Not a server problem; the student should download the notebook and submit from MoLab or a laptop.

**409 `attempts_exhausted`** — the assignment's `attempts_allowed` cap. An instructor can raise it in the assignment's settings without republishing.

## Grading

**Submissions sit at *waiting*.** Check the worker is running and claiming. A worker that restarted mid-run re-queues it.

**"Notebook execution failed" on everything for one assignment.** Almost always a cold dataset cache — see [Sandbox and data](sandbox-and-data.md#the-dataset-cache). Run `grader warm-cache --check` for that slug; it exits non-zero and names what is missing.

**"Notebook execution failed" on one student's submission.** Usually their code: an infinite loop against the timeout, or memory against `GRADER_RLIMIT_AS`. The error is on the course page; **Retry** re-queues it.

**Everything fails since a new host.** Run the bubblewrap check in [Sandbox and data](sandbox-and-data.md#the-worker-sandbox). Docker's defaults block what the sandbox needs.

**The first submission of a new assignment is slow.** Expected: an environment is built for that dependency list, once, then reused.

## Mail

Nothing arrives, but the API returned 202. That response is identical in every case by design, so it tells you nothing. The log does:

- `email login link rate limited` — the per-NetID cap;
- `email login link could not be delivered` — SES refused or the relay is unreachable. Check `GRADER_MAIL_FROM` is at a verified identity, and that the account is out of the SES sandbox.

## Disk

The artifacts volume grows with submissions and renders; the uv and dataset caches grow with assignments. `docker system df -v` shows the volumes. Package and dataset caches are safe to delete — they rebuild, at the cost of one slow grading run. **The artifacts volume is not**: it holds student work that is not in the database.

## Getting more detail

Both services log at INFO. Logs record user ids rather than NetIDs, which is deliberate — a log aggregator should not become a roster.

For a submission that will not grade, the worker log carries the engine's own output, including the notebook's traceback: the same message the student would get running that code anywhere. For a request that is refused, the API log names the error code the client saw (`not_enrolled`, `csrf`, `attempts_exhausted`), which is usually enough to tell a misconfiguration from a misuse.

To watch a single submission from end to end:

```bash
docker compose -f docker-compose.prod.yml logs -f worker | grep -i <submission-id>
```
