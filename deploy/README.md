# Deployment files

The runbook now lives on the documentation site, so there is one copy to keep current:

**<https://marimograder.org/operators/deploy/>**

| Page | Covers |
| --- | --- |
| [Overview](https://marimograder.org/operators/overview/) | what the services are, the volumes, what a deploy does, sizing |
| [Deploy](https://marimograder.org/operators/deploy/) | infrastructure, bootstrap, secrets, `.env`, first deploy, verification, the first course |
| [Email delivery](https://marimograder.org/operators/email-delivery/) | Amazon SES setup for sign-in links |
| [Sandbox and data](https://marimograder.org/operators/sandbox-and-data/) | the bubblewrap check and warming the dataset cache |
| [Staging](https://marimograder.org/operators/staging/) | a second host |
| [Backups and upgrades](https://marimograder.org/operators/backups-and-upgrades/) | what to back up, restoring, upgrading, rotating secrets |
| [Troubleshooting](https://marimograder.org/operators/troubleshooting/) | symptoms and first checks |
| [SAML](https://marimograder.org/auth/saml/) | registering the service provider, including the Dartmouth EntraID values |

The site is built from `docs/` in this repository; edit it there.

## What is in this directory

| File | Purpose |
| --- | --- |
| `bootstrap.sh` | One-time host setup as root: Docker, the `deploy` user, ufw, fail2ban, unattended upgrades, unprivileged user namespaces. |
| `deploy.sh` | Pull images, migrate, restart. Run as `deploy` in `/srv/grader`. Takes an optional image tag. |
| `saml-registration.md` | A ready-to-send registration request for an identity team. |
| `ses-smtp-password.py` | Derives an SES SMTP password from an IAM secret access key. |
| `web/Dockerfile`, `web/Caddyfile` | The `marimo-grader-web` image: Caddy carrying the built frontend. |
| `../docker-compose.prod.yml` | The stack the host runs. |
