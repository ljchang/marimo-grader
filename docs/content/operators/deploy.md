# Deploy

For the person running the server. The reference deployment is one small virtual machine plus a managed PostgreSQL database; the full step-by-step runbook with every command is [`deploy/README.md`](https://github.com/ljchang/marimo-grader/blob/main/deploy/README.md) in the repository.

## Shape

```
GitHub Actions  --builds-->  ghcr.io/ljchang/marimo-grader-backend   (API and worker)
                             ghcr.io/ljchang/marimo-grader-web       (Caddy + the Svelte app)
                                     |
                                     v  docker compose pull
droplet (Ubuntu 24.04, 2 vCPU / 4 GB)         managed PostgreSQL (private network)
  proxy   Caddy: TLS, security headers, /api and /a to the API
  web     FastAPI
  worker  grading in bubblewrap, no network inside the sandbox
  volumes artifacts, prepared environments, uv and dataset caches
```

Nothing is built on the server. Every push to `main` builds and pushes both images; a deploy is `docker compose pull` plus a migration.

## Steps

1. **Create the infrastructure.** A droplet with your SSH key, a cloud firewall allowing 22 from you and 80/443 from anywhere, a managed PostgreSQL 16 cluster in the same region and VPC with the droplet as its only trusted source, and a DNS A record for the hostname. Use the database's private connection string with `sslmode=require`.
2. **Bootstrap the droplet** as root: `ssh root@<ip> 'bash -s' < deploy/bootstrap.sh`. It installs Docker, creates a `deploy` user, enables the firewall, unattended security updates, and fail2ban, and prepares `/srv/grader`.
3. **Write `.env`** in `/srv/grader` (mode 600). Generate a session secret and an Ed25519 key for notebook tokens, create a self-signed SAML certificate, and fill in the database URL. [Configuration](../reference/configuration.md) lists every setting. In production the service refuses to start if a required secret is missing.
4. **Copy `docker-compose.prod.yml` and `deploy/deploy.sh`** into `/srv/grader` and run `./deploy.sh`. It pulls images, fixes volume ownership, runs migrations, starts the services, and waits for the health check.
5. **Verify**: `curl https://<host>/api/health` returns `{"ok": true, ...}`; the SAML metadata is at `/api/v1/auth/saml/metadata`.
6. **Seed the first course** and mint an instructor token or sign-in link with the [command line](../reference/cli.md), then publish an assignment.

## Redeploying

```bash
ssh deploy@<ip> 'cd /srv/grader && ./deploy.sh'          # latest main
ssh deploy@<ip> 'cd /srv/grader && ./deploy.sh sha-abc1234'  # a specific build
```

Rolling back is the same command with an older tag. Migrations run forward only; roll back the application, not the schema, unless a migration is known to be reversible.

## The worker sandbox on Docker

Student code runs inside bubblewrap with the filesystem read-only and no network. Docker's defaults block the user namespaces and the fresh `/proc` mount bubblewrap needs, so the worker service sets `security_opt: [seccomp:unconfined, apparmor:unconfined, systempaths=unconfined]`. Verify after the first deploy:

```bash
docker compose -f docker-compose.prod.yml exec worker \
  bwrap --ro-bind / / --unshare-all --dev /dev --proc /proc -- /bin/true && echo sandbox ok
```

Environments for notebooks are built outside the sandbox, one per distinct dependency list, and reused; the first submission of a new assignment takes about a minute longer than the rest.

## Staging and production

Run staging and production as separate hosts with separate databases. Set `GRADER_STAGING=1` on staging so search engines ignore it and the header is marked. Student notebooks embed the server they were published from, so a notebook published on staging always submits to staging.
