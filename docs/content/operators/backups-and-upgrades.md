# Backups and upgrades

For the operator. What to back up, how to restore, and how to move to a new release.

## What needs backing up

| Data | Mechanism | Restore |
|---|---|---|
| Database (grades, roster, audit, submission metadata) | managed PostgreSQL: daily backups plus point-in-time recovery | restore a new cluster from the provider console, point `GRADER_DATABASE_URL` at it |
| Artifacts volume (submitted notebooks, rendered HTML, roster uploads) | nightly archive of the `grader_artifacts` Docker volume to object storage | extract the archive into a fresh volume before starting the services |
| `.env` | keep a copy in a password manager; it holds every secret | copy back to `/srv/grader/.env`, mode 600 |

The prepared-environment, uv, and dataset cache volumes are rebuildable and need no backup.

A minimal nightly artifact archive from the deploy user's crontab:

```bash
docker run --rm -v grader_artifacts:/data:ro -v /srv/backups:/out alpine:3 \
  tar czf /out/artifacts-$(date +%F).tgz -C /data .
```

Sync `/srv/backups` to a bucket with `rclone` or `s3cmd`. Test a restore once per term: create the volume, extract, start the stack, open a rendered submission.

## Upgrading

1. Read the release notes for schema changes; migrations are applied by `deploy.sh` before the API starts.
2. `./deploy.sh` (or `./deploy.sh <tag>` for a specific build) pulls, migrates, restarts, and waits for the health check.
3. Check `/api/health` and the worker log (`docker compose -f docker-compose.prod.yml logs --tail 20 worker`). A worker restart re-queues any grading run that was in progress.

Mid-term, prefer deploying between assignment deadlines. Nothing about a deploy affects open student notebooks; they keep the version they opened.

## Rotating secrets

- **Session secret**: signs cookies; rotating signs everyone out of the web app.
- **Notebook token key** (`GRADER_JWT_PRIVATE_KEY_PEM`): rotating invalidates every notebook token; students sign in again on their next submit.
- **SAML certificate**: rotating requires re-registering the metadata with the identity provider.
- **Database password**: rotate in the provider console, update `.env`, redeploy.

## Retention

Set `retention_until` on an offering when the term ends. Deleting artifacts and check events after that date is a manual job today; grades and the audit trail are kept per institutional policy.
