# Deploying to DigitalOcean

One droplet runs the API, the autograde worker, and Caddy (TLS + static frontend) with
Docker Compose. DigitalOcean Managed PostgreSQL holds the data. GitHub Actions builds the
images and pushes them to GHCR; the droplet only pulls.

```
GitHub push to main ──► .github/workflows/images.yml ──► ghcr.io/ljchang/marimo-grader-backend:main
                                                        ghcr.io/ljchang/marimo-grader-web:main
                                                                        │
                                       droplet: /srv/grader/deploy.sh  ◄┘   (pull, migrate, up)
                                       ├─ proxy   Caddy :80/:443 → /srv (Svelte) and /api → web
                                       ├─ web     uvicorn :8000
                                       ├─ worker  grader-worker (bubblewrap sandbox)
                                       └─ migrate alembic upgrade head (one-shot)
                                                  │
                                       Managed PostgreSQL (private network, sslmode=require)
```

Files in this directory:

| File | Purpose |
| --- | --- |
| `bootstrap.sh` | One-time droplet setup as root (Docker, `deploy` user, ufw, fail2ban, unattended upgrades). |
| `deploy.sh` | Pull images, migrate, restart services. Run as `deploy` in `/srv/grader`. |
| `web/Dockerfile`, `web/Caddyfile` | The `marimo-grader-web` image: Caddy carrying the built frontend. |
| `../docker-compose.prod.yml` | The stack the droplet runs. |

## 1. Create the infrastructure

### Droplet

* **Image:** Ubuntu 24.04 LTS x64.
* **Size:** Premium (Intel or AMD), 2 vCPU / 4 GB. The worker executes student notebooks
  with scientific Python (nilearn, marimo); 2 GB is not enough headroom.
* **Region:** the one closest to Hanover (`nyc3` or `nyc1`). The database must be in the
  same region.
* **VPC:** the default VPC for the region (needed for the private database connection).
* **Authentication:** SSH key. Do not enable password login.
* **Options:** enable monitoring; tag it `grader`.

### Cloud firewall (Networking → Firewalls)

Create a firewall and apply it to the droplet by tag:

| Direction | Rule |
| --- | --- |
| Inbound | SSH TCP 22 from your IPs (or All IPv4 if you rely on fail2ban) |
| Inbound | HTTP TCP 80, HTTPS TCP 443, HTTPS UDP 443 from All |
| Outbound | All |

`bootstrap.sh` also configures `ufw` on the host; the cloud firewall is the outer layer.

### Managed PostgreSQL (Databases → Create)

* **Engine:** PostgreSQL 16. **Plan:** Basic, 1 vCPU / 1 GB is plenty to start.
* **Region / VPC:** the same as the droplet.
* After it is created:
  1. **Users & Databases:** add database `grader` and user `grader`.
  2. **Settings → Trusted sources:** add the droplet (by name). Nothing else should be
     able to reach the database.
  3. **Overview → Connection details:** choose *VPC network*, user `grader`, database
     `grader`, and copy the connection string. It looks like

     ```
     postgresql://grader:<password>@private-db-postgresql-nyc3-12345-do-user-1-0.b.db.ondigitalocean.com:25060/grader?sslmode=require
     ```

     The application uses the psycopg driver, so the `.env` value is the same string with
     the scheme changed to `postgresql+psycopg://`. Keep `?sslmode=require`; the managed
     cluster rejects unencrypted connections.

Managed PostgreSQL takes daily backups automatically (7-day retention on Basic plans) and
supports point-in-time recovery from the *Backups* tab.

### DNS

Add an **A record** for `grader.dartbrains.org` (and `grader-staging.dartbrains.org` if you
run staging) pointing at the droplet's public IPv4. Caddy obtains the Let's Encrypt
certificate on first start, so DNS must resolve before you run `deploy.sh`.

## 2. Bootstrap the droplet

From your laptop, with the repository checked out:

```bash
ssh root@<droplet-ip> 'bash -s' < deploy/bootstrap.sh
```

This installs Docker, creates the `deploy` user (docker group, root's SSH keys), enables
unattended security upgrades, opens 22/80/443 in ufw, starts fail2ban, creates
`/srv/grader`, and permits unprivileged user namespaces for the bubblewrap sandbox. It is
safe to re-run.

Then log in as `deploy` and authenticate to GHCR with a **read-only** token so the droplet
can pull the private images. Create a classic personal access token with only the
`read:packages` scope (GitHub → Settings → Developer settings → Personal access tokens),
then:

```bash
ssh deploy@<droplet-ip>
echo '<PAT>' | docker login ghcr.io -u <github-username> --password-stdin
```

Docker stores the token in `~/.docker/config.json`. If the packages are public this step
is unnecessary.

## 3. Prepare `.env`

Start from `.env.example` on your laptop and produce the production file. Every line
matters: `GRADER_ENV=prod` refuses to boot if any secret is missing
(`backend/src/grader/config.py`).

### Generate secrets

```bash
# Session cookie signing secret
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Ed25519 key for notebook tokens (run inside the backend image so the
# dependencies are present; needs `docker login ghcr.io` first)
docker run --rm ghcr.io/ljchang/marimo-grader-backend:main \
  python -c "from grader.auth.tokens import generate_private_key_pem as g; print(g())"

# SAML service-provider certificate and key (10 years, self-signed)
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout sp.key -out sp.crt -subj "/CN=grader.dartbrains.org"
```

Multi-line PEM values go into `.env` on one line with `\n` separators, e.g.

```bash
printf 'GRADER_SAML_SP_KEY="%s"\n' "$(awk 'NF {printf "%s\\n", $0}' sp.key)"
```

(pydantic-settings unescapes `\n` inside double-quoted values.) Delete `sp.key` from
your laptop once it is in `.env`; the file is gitignored (`*.pem`, `.env`).

### Values

| Variable | Production | Staging |
| --- | --- | --- |
| `GRADER_ENV` | `prod` | `prod` (staging must exercise the same fail-closed checks) |
| `GRADER_HOST` | `grader.dartbrains.org` | `grader-staging.dartbrains.org` |
| `GRADER_STAGING` | `0` | `1` (Caddy adds `X-Robots-Tag: noindex`) |
| `GRADER_BASE_URL` / `GRADER_FRONTEND_URL` | `https://grader.dartbrains.org` | `https://grader-staging.dartbrains.org` |
| `GRADER_DATABASE_URL` | managed PG string, `postgresql+psycopg://…?sslmode=require` | a second database on the same cluster (`grader_staging`) |
| `GRADER_SESSION_SECRET` | generated above | different value |
| `GRADER_COOKIE_SECURE` | `true` | `true` |
| `GRADER_JWT_PRIVATE_KEY_PEM` | generated above | different key |
| `GRADER_AUTH_MODE` | `saml` | `saml` (dev-login is refused in prod) |
| `GRADER_SAML_SP_ENTITY_ID` | `https://grader.dartbrains.org` | `https://grader-staging.dartbrains.org` (register separately with Dartmouth IT) |
| `GRADER_SAML_IDP_*` | defaults from `.env.example` (login/logout.dartmouth.edu) | same |
| `GRADER_SAML_IDP_CERT` | PEM body from the IdP metadata (pbs_knowledge repo) | same |
| `GRADER_SAML_SP_CERT` / `GRADER_SAML_SP_KEY` | generated above | different pair |
| `GRADER_CORS_ORIGINS` | `["https://dartbrains.org","https://molab.marimo.io"]` | add the staging notebook host, e.g. `"http://localhost:2718"` |
| `GRADER_IMAGE_TAG` | `main`, or pin a release (`0.2.0`) | `main` or a `sha-<short>` under test |

`GRADER_ARTIFACT_DIR` is set by the image (`/data/artifacts`); leave it out.
`POSTGRES_PASSWORD` is only for the local compose stack and can be dropped.

### SAML registration

Send Dartmouth IT the SP metadata, which the running service publishes at
`https://grader.dartbrains.org/api/v1/auth/saml/metadata`. Until the IdP knows the SP,
sign-in redirects to `login.dartmouth.edu` and fails there, but `/api/health` and the
static UI work, so you can deploy first and register second. The IdP metadata, a working
SP metadata template, and the registration email template are in the pbs_knowledge
repository.

## 4. Copy files and deploy

```bash
scp docker-compose.prod.yml deploy/deploy.sh .env deploy@<droplet-ip>:/srv/grader/
ssh deploy@<droplet-ip> 'chmod 600 /srv/grader/.env && cd /srv/grader && ./deploy.sh'
```

`deploy.sh` pulls both images at `GRADER_IMAGE_TAG`, fixes volume ownership for the
non-root container user, runs `migrate` (Alembic; a failure stops the deploy before
anything else changes), starts `web`, `worker` and `proxy`, waits for the `web`
healthcheck, prunes old images and prints `docker compose ps`.

Verify:

```bash
curl -fsS https://grader.dartbrains.org/api/health
# {"ok":true,"env":"prod","auth_mode":"saml"}
curl -sI https://grader.dartbrains.org/ | grep -iE 'strict-transport|content-security|x-robots'
```

Then open the site, sign in through Dartmouth SSO, and confirm the worker sandbox works:

```bash
cd /srv/grader
docker compose -f docker-compose.prod.yml exec worker \
  bwrap --ro-bind / / --unshare-all --dev /dev true && echo sandbox ok
```

If that prints `bwrap: No permissions to create new namespace`, uncomment the
`security_opt` line on the `worker` service in `docker-compose.prod.yml` and run
`./deploy.sh` again (the comment there explains the trade-off).

### Redeploying

Every push to `main` publishes new `:main` images. On the droplet:

```bash
cd /srv/grader && ./deploy.sh              # latest main
cd /srv/grader && ./deploy.sh sha-1a2b3c4  # a specific commit
cd /srv/grader && ./deploy.sh v0.2.0       # a release tag
```

Passing a tag exports `GRADER_IMAGE_TAG` for that run only; put it in `.env` to make it
stick. Rolling back is `./deploy.sh <previous tag>` (migrations are forward-only, so check
`alembic history` before rolling back across a schema change).

Useful commands:

```bash
docker compose -f docker-compose.prod.yml logs -f web worker proxy
docker compose -f docker-compose.prod.yml exec web python -c "from grader.config import get_settings; print(get_settings().env)"
docker compose -f docker-compose.prod.yml run --rm web grader --help     # CLI (seed, publish, ...)
```

## 5. Backups

* **Database:** Managed PostgreSQL takes daily backups with point-in-time recovery. Restore
  from the cluster's *Backups* tab (it creates a new cluster; update `GRADER_DATABASE_URL`).
* **Artifacts:** submitted notebooks live in the `grader_artifacts` Docker volume and are
  not in the database. Snapshot them nightly as `deploy` (`crontab -e`):

  ```cron
  # nightly artifact archive, keep 14 days
  15 3 * * * docker run --rm -v grader_artifacts:/data:ro -v /srv/grader/backups:/backup alpine:3 tar czf /backup/artifacts-$(date +\%F).tar.gz -C /data . && find /srv/grader/backups -name 'artifacts-*.tar.gz' -mtime +14 -delete
  ```

  `mkdir -p /srv/grader/backups` first. To keep copies off the droplet, push the archive
  to a DigitalOcean Space with `s3cmd` or `rclone` (`rclone copy /srv/grader/backups
  do-spaces:grader-backups`) after the `tar` step, or enable droplet backups in the
  DigitalOcean control panel (weekly, whole disk).
* **Caddy certificates** (`grader_caddy_data`) are re-issued automatically if lost; no
  backup needed.
* **`.env`** is the only copy of the SP key and JWT key. Keep it in the team password
  manager.

## 6. Staging

Run staging as a second droplet with its own `.env` (see the table above): its own
hostname, `GRADER_STAGING=1`, its own database on the same managed cluster, its own SP
entity ID registered with Dartmouth IT, and separate secrets. The compose file and scripts
are identical; only `.env` differs. Because `GRADER_ENV` is `prod` on both, staging
exercises the same fail-closed configuration checks, the same SAML flow, and the same
CSP, which is the point.

## Notes

* The droplet never builds anything. If you need a hotfix without CI, build locally with
  `docker build -t ghcr.io/ljchang/marimo-grader-backend:hotfix backend` and
  `docker build -t ghcr.io/ljchang/marimo-grader-web:hotfix -f deploy/web/Dockerfile .`,
  push, and `./deploy.sh hotfix`.
* Compose reads `/srv/grader/.env` both for variable interpolation (`GRADER_HOST`,
  `GRADER_IMAGE_TAG`, `GRADER_STAGING`) and as `env_file` for the backend containers.
* Ports 80/443 are published by Docker directly, which bypasses ufw; the cloud firewall
  and ufw agree on those ports so this makes no practical difference.

## Publishing before sign-in is enabled

While `GRADER_AUTH_MODE=disabled` (waiting for SAML approval) nobody can sign in, so mint an
instructor token on the server instead. Run this once per term; the token is valid 8 hours:

```bash
cd /srv/grader
docker compose -f docker-compose.prod.yml run --rm web grader seed --course neuroimaging \
    --title "Introduction to Neuroimaging Analysis" --term 2026-fall --instructor <netid> --students
docker compose -f docker-compose.prod.yml run --rm web grader token <netid> \
    --offering neuroimaging/2026-fall --role instructor --admin
```

Then, from your laptop:

```bash
cd marimo-grader/backend
uv run grader publish ../../dartbrains-assignments/assignments/glm.py \
    --server https://grader.dartbrains.org --offering neuroimaging/2026-fall \
    --slug glm --title "GLM" --token <token>
```

## Signing in to the web UI before SSO is enabled

`grader login-link <netid>` prints a one-time URL (valid 10 minutes) that signs that NetID into
the browser UI. It works in every auth mode and can only be minted with shell access, so it is
also the break-glass path if SSO is ever unavailable:

```bash
docker compose -f docker-compose.prod.yml run --rm web grader login-link f00275v
```

## Worker sandbox

`docker-compose.prod.yml` runs the worker with `security_opt: [seccomp:unconfined,
apparmor:unconfined, systempaths=unconfined]`. Docker's defaults block the unprivileged user
namespaces and the fresh `/proc` mount that bubblewrap needs; with these three relaxed, student
code runs inside bubblewrap with `--unshare-net` (verified: no network from inside the sandbox).
The worker container itself never runs student code outside bubblewrap.
