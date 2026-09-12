# Configuration

For operators. Every setting is an environment variable prefixed `GRADER_`, read once at startup (a `.env` file in the working directory is also read). With `GRADER_ENV=prod` the service refuses to start unless the session secret, the token key, and, in `saml` mode, the SAML values are set and cookies are secure.

## Core

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_ENV` | `dev` | `dev`, `test`, or `prod`; `prod` enables the fail-closed checks |
| `GRADER_BASE_URL` | `http://localhost:8000` | public URL of the API; embedded in published notebooks and device-handshake links |
| `GRADER_FRONTEND_URL` | `http://localhost:5173` | where sign-in redirects land; the same host as the API in production |
| `GRADER_DATABASE_URL` | local PostgreSQL | SQLAlchemy URL, `postgresql+psycopg://...?sslmode=require` in production |
| `GRADER_ARTIFACT_DIR` | `./data/artifacts` | content-addressed store for notebooks and renders |
| `GRADER_CORS_ORIGINS` | localhost, MoLab, dartbrains.org | JSON list of origins the notebook widget may call from |
| `GRADER_MAX_NOTEBOOK_BYTES` | 2 MiB | largest accepted notebook |
| `GRADER_MAX_OUTPUTS_BYTES` | 8 MiB | largest accepted written-answer payload |

## Sessions and tokens

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_SESSION_SECRET` | dev placeholder | signs browser session cookies; required in prod |
| `GRADER_SESSION_COOKIE` | `grader_session` | cookie name; use distinct names on staging and production |
| `GRADER_SESSION_TTL_SECONDS` | 43200 | browser session lifetime (12 h) |
| `GRADER_COOKIE_SECURE` | `false` | must be `true` in prod |
| `GRADER_JWT_PRIVATE_KEY_PEM` | none | Ed25519 private key for notebook tokens; required in prod. Dev mode persists a generated key beside the artifact directory |
| `GRADER_NOTEBOOK_TOKEN_TTL_SECONDS` | 28800 | notebook token lifetime (8 h) |
| `GRADER_DEVICE_CODE_TTL_SECONDS` | 600 | how long a sign-in code from the widget stays valid |
| `GRADER_DEVICE_POLL_INTERVAL_SECONDS` | 3 | how often the widget polls during sign-in |

## Authentication

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_AUTH_MODE` | `dev` | `saml`, `disabled`, or `dev`; see [Single sign-on](../operators/single-sign-on.md) |
| `GRADER_SAML_SP_ENTITY_ID` | base URL | the entity id registered with the identity provider |
| `GRADER_SAML_IDP_ENTITY_ID` | Dartmouth's | identity provider entity id |
| `GRADER_SAML_IDP_SSO_URL` | Dartmouth's | identity provider single sign-on endpoint (HTTP-POST) |
| `GRADER_SAML_IDP_LOGOUT_URL` | Dartmouth's | where sign-out redirects |
| `GRADER_SAML_IDP_CERT` | none | identity provider signing certificate (PEM or base64 body) |
| `GRADER_SAML_SP_CERT`, `GRADER_SAML_SP_KEY` | none | this service's certificate and private key (PEM) |
| `GRADER_SAML_CLOCK_SKEW_SECONDS` | 120 | tolerance for clock differences with the identity provider |

## Worker

These are plain environment variables read by the worker process.

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_USE_BUBBLEWRAP` | off | run notebooks inside bubblewrap (requires the compose `security_opt` settings) |
| `GRADER_AUTOGRADE_TIMEOUT` | 300 | seconds a submission may run |
| `GRADER_RENDER_TIMEOUT` | 180 | seconds a render may take |
| `GRADER_RLIMIT_AS` | 4 GiB | address-space cap for the notebook process |
| `GRADER_SANDBOX_DIR` | beside the artifact dir | where prepared notebook environments are kept |
| `GRADER_CLIENT_REQUIREMENT` | `marimo-grader-client` | requirement string substituted for the client package when building environments |
| `UV_CACHE_DIR`, `HF_HOME` | | package and dataset caches; mount them on persistent volumes |

## Deployment

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_HOST` | `localhost` | hostname Caddy serves and obtains a certificate for |
| `GRADER_STAGING` | `0` | `1` marks the site noindex |
| `GRADER_IMAGE_TAG` | `main` | which image tag `docker compose` runs |
