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

### SAML registration (Microsoft EntraID)

Dartmouth moved from Apero CAS to EntraID in 2026. Give ITC these three values; everything
else they need is in the SP metadata the running service publishes:

| | |
|---|---|
| Identifier (Entity ID) | `https://grader.dartbrains.org` |
| Reply URL (ACS) | `https://grader.dartbrains.org/api/v1/auth/saml/acs` |
| SP metadata | `https://grader.dartbrains.org/api/v1/auth/saml/metadata` |

The IdP side comes from ITC's published metadata,
<https://dartmouth.github.io/dartmouth-idp-metadata/metadata.xml>. The entity ID and SSO URL
are the defaults in `config.py`; only the signing certificate has to be set:

```bash
GRADER_AUTH_MODE=saml
GRADER_SAML_SP_ENTITY_ID=https://grader.dartbrains.org
GRADER_SAML_IDP_ENTITY_ID=https://sts.windows.net/995b0936-48d6-40e5-a31e-bf689ec9446f/
GRADER_SAML_IDP_SSO_URL=https://login.microsoftonline.com/995b0936-48d6-40e5-a31e-bf689ec9446f/saml2
GRADER_SAML_IDP_LOGOUT_URL=https://logout.dartmouth.edu   # unchanged from the CAS era
GRADER_SAML_IDP_CERT=<X509Certificate body from the metadata above>
```

Verify the certificate you paste against the thumbprint ITC publishes:

```bash
curl -s https://dartmouth.github.io/dartmouth-idp-metadata/metadata.xml \
  | sed -n 's:.*<X509Certificate>\(.*\)</X509Certificate>.*:\1:p' | tr -d ' \n' \
  | base64 -d | openssl x509 -inform der -noout -fingerprint -sha1
# SHA1 Fingerprint=B6:A5:E2:42:97:F1:EE:90:64:44:32:75:2D:B8:9A:7F:29:B6:23:23
```

**The NetID comes from the local part of `eduPersonPrincipalName`**, which EntraID sources
from `userPrincipalName`. That is correct only while Dartmouth accounts are
`netid@dartmouth.edu` with the name forms as aliases. If that ever changes, every
enrollment lookup silently misses, because enrollments are keyed on the NetID from the
Canvas SIS Login ID. ITC releases each attribute under both its OID and its friendly name;
`saml.py` tries the friendly name first and falls back to the OID, so either works.

Until the IdP knows the SP, sign-in redirects to EntraID and fails there, but `/api/health`
and the static UI work, so you can deploy first and register second. `grader login-link`
and email sign-in links both work in the meantime.

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

`grader login-link <netid>` prints a one-time URL (valid 30 minutes) that signs that NetID into
the browser UI. It works in every auth mode and can only be minted with shell access, so it is
also the break-glass path if SSO is ever unavailable:

```bash
docker compose -f docker-compose.prod.yml run --rm web grader login-link f00275v
```

## Email sign-in links (Amazon SES)

A self-service version of the link above: the sign-in page offers "email me a link", the student
enters their Dartmouth address, and the server mails a one-time link. It exists for the window
before the SP is registered, and as the break-glass path if SSO goes down mid-term. **Turn it off
once `GRADER_AUTH_MODE=saml` works** — proving control of a mailbox is weaker than SAML + Duo.

Guard rails, all enforced server-side: the route 404s unless enabled; only addresses at
`GRADER_EMAIL_LOGIN_DOMAIN` are considered; only NetIDs with an active enrollment receive
anything (it never creates a user); each NetID is limited to `MAX_PER_DAY` links no closer
together than `MIN_INTERVAL_SECONDS`; every send is written to `grade_audit`; and the response is
identical whether or not the address is enrolled, so the form cannot be used to test roster
membership. No address is stored — the local part of a campus address *is* the NetID, the same
rule `roster.py` uses for a Canvas "SIS Login ID".

### One-time SES setup

SES is reached over its SMTP interface, so the service needs no AWS SDK and no AWS credentials at
runtime — only an SMTP username and password.

1. **Pick a region** and stay in it; SES identities are per-region. `us-east-1` is fine.
2. **Verify a sending domain.** Use a subdomain (`mail.dartbrains.org`) so grader mail cannot
   affect the apex domain's reputation:

   ```bash
   aws sesv2 create-email-identity --email-identity mail.dartbrains.org --region us-east-1
   aws sesv2 get-email-identity --email-identity mail.dartbrains.org --region us-east-1 \
       --query 'DkimAttributes.Tokens'
   ```

   Each of the three tokens becomes a DNS CNAME:
   `<token>._domainkey.mail.dartbrains.org → <token>.dkim.amazonses.com`.
   dartbrains.org is on Google nameservers, so add them there.
3. **SPF and DMARC** TXT records on `mail.dartbrains.org`:
   `v=spf1 include:amazonses.com ~all` and `_dmarc` → `v=DMARC1; p=none; rua=mailto:you@...`.
4. **Request production access.** New accounts are in the SES sandbox and can only send to
   verified addresses, which is useless for a class. Do this first — approval usually takes about
   a day but is not instant:

   ```bash
   aws sesv2 put-account-details --region us-east-1 \
       --production-access-enabled --mail-type TRANSACTIONAL \
       --website-url https://dartbrains.org \
       --use-case-description "One-time sign-in links for students enrolled in a single course. \
   Recipients are course rosters only; volume is tens of messages per term; bounces and \
   complaints are monitored."
   ```

   Check with `aws sesv2 get-account --region us-east-1 --query ProductionAccessEnabled`.
5. **Create SMTP credentials.** The console button (SMTP settings → Create SMTP credentials)
   works, but it creates an IAM user with account-wide send rights. Scoping it to this one
   identity is better and is two commands:

   ```bash
   aws iam create-user --user-name dartbrains-grader-ses
   aws iam put-user-policy --user-name dartbrains-grader-ses \
       --policy-name ses-send-mail-dartbrains --policy-document '{
         "Version": "2012-10-17",
         "Statement": [{
           "Effect": "Allow",
           "Action": ["ses:SendRawEmail", "ses:SendEmail"],
           "Resource": "arn:aws:ses:us-east-1:<account-id>:identity/mail.dartbrains.org"
         }]}'
   aws iam create-access-key --user-name dartbrains-grader-ses
   ```

   The SMTP *username* is the access key id. The SMTP *password* is an HMAC derivation of the
   secret access key, which `deploy/ses-smtp-password.py` computes:

   ```bash
   python3 deploy/ses-smtp-password.py <SecretAccessKey> us-east-1
   ```

   A leaked key then sends only as this domain, never as another identity in the account.
6. **Fill in `.env`** on the droplet and redeploy:

   ```bash
   GRADER_EMAIL_LOGIN_ENABLED=true
   GRADER_MAIL_TRANSPORT=smtp
   GRADER_MAIL_FROM="DartBrains Grader <grader@mail.dartbrains.org>"
   GRADER_MAIL_REPLY_TO=luke.j.chang@dartmouth.edu
   GRADER_SMTP_HOST=email-smtp.us-east-1.amazonaws.com
   GRADER_SMTP_PORT=587
   GRADER_SMTP_USERNAME=<SES SMTP username>
   GRADER_SMTP_PASSWORD=<SES SMTP password>
   ```

   `GRADER_MAIL_FROM` must be at a verified identity or SES rejects every message.
7. **Verify delivery** before telling students, and confirm the address shape works at all:

   ```bash
   curl -sS -X POST https://grader.dartbrains.org/api/v1/auth/email-login \
        -H 'Content-Type: application/json' -d '{"email":"<yournetid>@dartmouth.edu"}'
   ```

   A 202 means "accepted, and I will not tell you whether that address matched" — check the
   mailbox, and the container logs if nothing arrives. If `<netid>@dartmouth.edu` does not
   deliver at Dartmouth, the NetID-from-address rule does not hold and the roster needs to carry
   real addresses instead; find that out here rather than after the first assignment.

Leaving `GRADER_MAIL_TRANSPORT=console` logs messages instead of sending them, which is the right
setting for staging and for testing the flow before SES is approved.

## Dataset cache

Autograding runs under `--unshare-net`, so an assignment that downloads data can only read
what is already in the worker's HuggingFace cache. `docker-compose.prod.yml` points `HF_HOME`
at the persistent `hf_cache` volume; `deploy/warm_cache.py` fills it.

Run it after every deploy, and after publishing an assignment that touches new data:

```bash
docker compose -f docker-compose.prod.yml run --rm worker grader warm-cache
docker compose -f docker-compose.prod.yml run --rm worker grader warm-cache --check
```

It is a `grader` subcommand rather than a script under `deploy/` because the backend image
is built with `context: backend` (see `.github/workflows/images.yml`), so nothing outside
`backend/` can be copied into it — a script left in `deploy/` is simply not present in the
container that has to run it.

`--check` downloads nothing and reports what is missing, running cache-only exactly as the
sandbox does; it exits non-zero when anything is absent, so it works as a smoke test. `--slug <name>` limits either mode to one assignment.

The file list is derived from each published notebook's own `localizer.get_file` and
`localizer.download` calls, so it cannot drift from the assignment. Anything built at run time
and therefore invisible to that scan goes in the assignment's `required_datasets` setting as
`"<repo_id> <filename>"` entries, which the script also warms. Warming happens inside the
assignment's own prepared venv, so files are fetched through the same code path the notebook
will use rather than a reimplementation of its path rules.

Skipping this is not a quiet failure: a cold cache makes the autograde run raise
`LocalEntryNotFoundError`, which is reported as "notebook execution failed" — a grader failure
to investigate rather than a zero for the student. Sizes are small enough not to worry about
(a per-condition beta image is about 2 MB; a 20-subject, 4-condition assignment is ~150 MB),
but raw preprocessed bold is ~57 MB per subject, so an assignment that loops over subjects on
raw data is worth a second look before it is published.

## Worker sandbox

`docker-compose.prod.yml` runs the worker with `security_opt: [seccomp:unconfined,
apparmor:unconfined, systempaths=unconfined]`. Docker's defaults block the unprivileged user
namespaces and the fresh `/proc` mount that bubblewrap needs; with these three relaxed, student
code runs inside bubblewrap with `--unshare-net` (verified: no network from inside the sandbox).
The worker container itself never runs student code outside bubblewrap.
