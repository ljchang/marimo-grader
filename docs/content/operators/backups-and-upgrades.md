# Backups and upgrades

What to back up, how to restore it, how to move to a new release, and how to rotate a secret.

## What needs backing up

Two things, and they need to be recent relative to each other: a database restored to last night beside artifacts restored to last week gives you submissions with no files and files with no submissions.

| Data | Mechanism | Restore |
|---|---|---|
| Database — grades, roster, audit trail, submission metadata | managed PostgreSQL: daily backups plus point-in-time recovery | restore a new cluster from the provider console, point `GRADER_DATABASE_URL` at it |
| Artifacts volume — submitted notebooks, rendered HTML, roster uploads | nightly archive of the `artifacts` Docker volume, pushed off the host | extract into a fresh volume before starting the services |
| `.env` | a copy in a password manager | copy back to `/srv/grader/.env`, mode 600 |

The `hf_cache`, `uv_cache` and `sandboxes` volumes are rebuildable; Caddy's certificates are reissued automatically. None of them need backing up.

A nightly archive from the deploy user's crontab, keeping fourteen days:

```cron
15 3 * * * docker run --rm -v grader_artifacts:/data:ro -v /srv/grader/backups:/backup alpine:3 \
  tar czf /backup/artifacts-$(date +\%F).tar.gz -C /data . && \
  find /srv/grader/backups -name 'artifacts-*.tar.gz' -mtime +14 -delete
```

`mkdir -p /srv/grader/backups` first. **Then get the archive off the host**, with `rclone copy /srv/grader/backups <remote>:grader-backups` or `s3cmd`, because a backup that lives on the machine it protects is not a backup. Whole-disk snapshots from the provider are a reasonable second layer, not a first one.

/// admonition | Test a restore once a term
    type: tip

Create the volume, extract the archive, start the stack, open a rendered submission from it. A backup nobody has restored is a hypothesis. Half an hour, once, between terms.
///

## Upgrading

1. Read the release notes for schema changes. Migrations are applied by `deploy.sh` before the API starts, and a migration failure stops the deploy before anything else changes.
2. `./deploy.sh`, or `./deploy.sh <tag>` for a specific build.
3. Check `/api/health` and the worker log:

```bash
docker compose -f docker-compose.prod.yml logs --tail 20 worker
```

A worker restart re-queues any grading run that was in progress, so nothing is lost mid-upgrade.

Prefer deploying between assignment deadlines. Nothing about a deploy affects open student notebooks — they hold an immutable version — but a restart during a submission spike is needless drama.

**Rolling back** is `./deploy.sh <older tag>`. Migrations are forward-only: roll back the application, not the schema, unless you have checked that the migration in between is reversible. If a release both migrates and misbehaves, rolling forward to a fix is usually faster than unpicking it.

## Rotating secrets

| Secret | Rotating it means | Cost |
|---|---|---|
| `GRADER_SESSION_SECRET` | everyone signed out of the web app | small — they sign in again |
| `GRADER_JWT_PRIVATE_KEY_PEM` | every notebook token invalid | small — students press Sign in once more. **This is the intended emergency response** |
| Database password | rotate in the provider console, update `.env`, redeploy | a restart |
| SAML SP certificate | re-registering with the identity provider | an IT ticket and a wait — plan it |
| SES SMTP credentials | update `.env`, redeploy | small |

The session secret must otherwise stay **stable across deploys**: changing it by accident signs out the whole class at once, which looks exactly like an outage.

## Retention

Set `retention_until` on an offering when the term ends.

Deleting artifacts and check events after that date is a **manual job today** — the per-offering window is a setting without an automatic job behind it yet. Grades and the audit trail are kept per institutional policy. This is named in the [security model](security-model.md#known-limits) rather than buried here, because a reviewer will ask.
