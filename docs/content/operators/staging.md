# Staging

A second host, its own database, its own secrets, its own SAML registration. The compose file and the scripts are identical; only `.env` differs.

Worth having if you teach with this while developing it. Not worth having if you do not.

## What changes

| Variable | Production | Staging |
|---|---|---|
| `GRADER_ENV` | `prod` | `prod` — **also prod** |
| `GRADER_HOST` | `grader.example.edu` | `grader-staging.example.edu` |
| `GRADER_STAGING` | `0` | `1` (Caddy adds `X-Robots-Tag: noindex`) |
| `GRADER_BASE_URL`, `GRADER_FRONTEND_URL` | the production hostname | the staging hostname |
| `GRADER_DATABASE_URL` | the production database | a second database, same cluster is fine |
| `GRADER_SESSION_COOKIE` | `grader_session` | a different name |
| `GRADER_SESSION_SECRET`, `GRADER_JWT_PRIVATE_KEY_PEM`, SAML cert and key | production values | **different values** |
| `GRADER_SAML_SP_ENTITY_ID` | the production entity id | its own, registered separately |
| `GRADER_IMAGE_TAG` | `main` or a release | `main` or the `sha-…` under test |

Staging runs with `GRADER_ENV=prod` on purpose. It then exercises the same fail-closed configuration checks, the same SAML flow, the same secure cookies and the same content security policy as production — which is the only reason it is worth running at all. A staging host in `dev` mode tests nothing you care about.

Give it a distinct session cookie name so a browser can hold both sessions at once without them fighting.

## Why a notebook cannot cross over

Publishing writes the server into the student notebook's PEP 723 block, so a notebook published on staging always submits to staging, and a notebook published on production always submits to production. There is no way to point one at the other by accident, and nothing to remember when testing.

The corollary: a notebook published from staging is not a notebook you can hand to students. Republish from production.

## What to test there

The things that can only be tested against a real host:

- a SAML round trip with a real account, including the second factor;
- a submission from a course website, which is where a missing [CORS origin](../auth/sessions-and-tokens.md#cors-which-origins-may-call) shows up;
- an assignment that reads data, with a cold cache, so you find out whether [warming](sandbox-and-data.md#the-dataset-cache) covers it;
- a migration against a database with data in it.

Copying production data to staging means copying student work, so do not. Seed it instead: `grader seed` makes a course, an offering, an instructor and some students in one command.
