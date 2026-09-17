# Configuration

For operators. Every setting is an environment variable prefixed `GRADER_`, read once at startup; a `.env` file in the working directory is read too.

With `GRADER_ENV=prod` the service **refuses to start** unless the session secret and the notebook token key are set, cookies are secure, the auth mode is not `dev`, and — in `saml` mode — the SAML values are present. That refusal is the feature; do not work around it by lowering `GRADER_ENV`.

## Core

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_ENV` | `dev` | `dev`, `test` or `prod`; `prod` enables the fail-closed checks |
| `GRADER_BASE_URL` | `http://localhost:8000` | public URL of the API; embedded in published notebooks and in sign-in links |
| `GRADER_FRONTEND_URL` | `http://localhost:5173` | where sign-in redirects land; the same host as the API in production |
| `GRADER_DATABASE_URL` | local PostgreSQL | SQLAlchemy URL; `postgresql+psycopg://…?sslmode=require` in production |
| `GRADER_ARTIFACT_DIR` | `./data/artifacts` | content-addressed store for notebooks and renders; set by the image in production |
| `GRADER_CORS_ORIGINS` | localhost, MoLab, dartbrains.org | JSON list of origins the notebook widget may call from |
| `GRADER_MAX_NOTEBOOK_BYTES` | 2 MiB | largest accepted notebook |
| `GRADER_MAX_OUTPUTS_BYTES` | 8 MiB | largest accepted written-answer payload |

MoLab's per-session `*.molab.run` subdomains are matched by a built-in regular expression rather than the origin list, because the sandbox id changes every session. See [CORS](../auth/sessions-and-tokens.md#cors-which-origins-may-call).

## Sessions and tokens

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_SESSION_SECRET` | dev placeholder | signs browser session cookies; required in prod, and must be **stable across deploys** |
| `GRADER_SESSION_COOKIE` | `grader_session` | cookie name; use distinct names on staging and production |
| `GRADER_SESSION_TTL_SECONDS` | 43200 | browser session lifetime (12 h) |
| `GRADER_COOKIE_SECURE` | `false` | must be `true` in prod |
| `GRADER_JWT_PRIVATE_KEY_PEM` | none | Ed25519 private key for notebook tokens; required in prod. In dev a generated key is persisted beside the artifact directory |
| `GRADER_NOTEBOOK_TOKEN_TTL_SECONDS` | 28800 | notebook token lifetime (8 h) |
| `GRADER_DEVICE_CODE_TTL_SECONDS` | 600 | how long a sign-in code from the widget stays valid |
| `GRADER_DEVICE_POLL_INTERVAL_SECONDS` | 3 | how often the widget polls during sign-in |

## Authentication

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_AUTH_MODE` | `dev` | `saml`, `disabled` or `dev`; see [How sign-in works](../auth/index.md) |
| `GRADER_SAML_SP_ENTITY_ID` | base URL | the entity id registered with the identity provider |
| `GRADER_SAML_IDP_ENTITY_ID` | Dartmouth's EntraID tenant | identity provider entity id |
| `GRADER_SAML_IDP_SSO_URL` | Dartmouth's EntraID tenant | identity provider single sign-on endpoint (HTTP-POST) |
| `GRADER_SAML_IDP_LOGOUT_URL` | `https://logout.dartmouth.edu` | where sign-out redirects |
| `GRADER_SAML_IDP_CERT` | none | identity provider signing certificate (PEM or base64 body) |
| `GRADER_SAML_SP_CERT`, `GRADER_SAML_SP_KEY` | none | this service's certificate and private key (PEM) |
| `GRADER_SAML_CLOCK_SKEW_SECONDS` | 120 | tolerance for clock differences with the identity provider |

Multi-line PEM values go into `.env` on one line with `\n` separators; pydantic-settings unescapes them inside double quotes.

## Email sign-in links

Off by default. See [Email sign-in links](../auth/email-links.md) for the guard rails and [Email delivery](../operators/email-delivery.md) for the relay.

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_EMAIL_LOGIN_ENABLED` | `false` | the feature; the route 404s when false |
| `GRADER_EMAIL_LOGIN_DOMAIN` | `dartmouth.edu` | the only domain considered; the local part is taken as the NetID |
| `GRADER_EMAIL_LOGIN_TTL_SECONDS` | 604800 | how long a link stays valid (7 days) |
| `GRADER_EMAIL_LOGIN_MAX_PER_DAY` | 5 | links per NetID per day |
| `GRADER_EMAIL_LOGIN_MIN_INTERVAL_SECONDS` | 300 | minimum gap between links for one NetID |

## Outbound mail

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_MAIL_TRANSPORT` | `console` | `smtp` sends; `console` logs the message; `memory` collects it for tests |
| `GRADER_MAIL_FROM` | `grader@example.test` | must be at a verified sending identity |
| `GRADER_MAIL_REPLY_TO` | none | where a reply should go |
| `GRADER_SMTP_HOST` | none | required when email links are on with `smtp` |
| `GRADER_SMTP_PORT` | 587 | |
| `GRADER_SMTP_USERNAME`, `GRADER_SMTP_PASSWORD` | none | relay credentials |
| `GRADER_SMTP_STARTTLS` | `true` | |

Enabling email links with `smtp` and no host is refused at startup: a sign-in link nobody receives is worse than no button at all.

## Worker

Plain environment variables read by the worker process.

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_USE_BUBBLEWRAP` | off | run notebooks inside bubblewrap (needs the compose `security_opt` settings) |
| `GRADER_AUTOGRADE_TIMEOUT` | 300 | seconds a submission may run |
| `GRADER_RENDER_TIMEOUT` | 180 | seconds a render may take |
| `GRADER_RLIMIT_AS` | 4 GiB | address-space cap for the notebook process |
| `GRADER_SANDBOX_DIR` | beside the artifact dir | where prepared notebook environments are kept |
| `GRADER_CLIENT_REQUIREMENT` | `marimo-grader-client` | requirement string substituted for the client package when building environments |
| `GRADER_RENDER` | unset | set inside the render path so the notebook's sign-in and submit widgets draw as static placeholders |
| `UV_CACHE_DIR`, `HF_HOME` | | package and dataset caches; mount them on persistent volumes |

## Deployment

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_HOST` | `localhost` | hostname Caddy serves and obtains a certificate for |
| `GRADER_STAGING` | `0` | `1` marks the site noindex |
| `GRADER_IMAGE_TAG` | `main` | which image tag `docker compose` runs |

## Checking what is actually set

```bash
curl -fsS https://<host>/api/health
# {"ok":true,"env":"prod","auth_mode":"saml"}

docker compose -f docker-compose.prod.yml exec web \
  python -c "from grader.config import get_settings; s=get_settings(); print(s.env, s.auth_mode, s.cors_origins)"
```
