# SAML and the identity provider

For the operator. Registering the grader with an institution's identity provider, what it asks for, and what it does with the answer.

The grader is a SAML 2.0 **service provider**. It asks the institution one question — *who is this person* — and takes a NetID from the answer. Roles, courses and permissions are its own business; see [How sign-in works](index.md).

## What to give your identity team

Three values, plus a metadata URL that supplies everything else. The service publishes its metadata in every auth mode, so you can deploy first and register second.

| | Value |
|---|---|
| Identifier (entity id) | `https://grader.example.edu` |
| Reply URL (assertion consumer service) | `https://grader.example.edu/api/v1/auth/saml/acs` |
| SP metadata | `https://grader.example.edu/api/v1/auth/saml/metadata` |
| Requested attribute | `eduPersonPrincipalName` (`urn:oid:1.3.6.1.4.1.5923.1.1.1.6`) |
| Optional | `displayName`, `uid`, `eduPersonAffiliation` |

A ready-to-send draft is in [`deploy/saml-registration.md`](https://github.com/ljchang/marimo-grader/blob/main/deploy/saml-registration.md) in the repository.

Staging registers separately, with its own entity id and its own certificate. Student notebooks embed the server they were published from, so nothing published on staging can submit to production by accident.

## How the NetID is derived

From `eduPersonPrincipalName`, taking the part before the `@` and lowercasing it — `f00abc1@example.edu` becomes `f00abc1`. If the assertion carries no EPPN, the service falls back to `uid` and then to the NameID.

/// admonition | This is the assumption most worth checking
    type: warning

Enrollments are keyed on the NetID that came from your Canvas roster's **SIS Login ID**. If the identity provider's EPPN local part is not that same NetID, every enrollment lookup misses silently: people sign in successfully and then appear to be enrolled in nothing at all.

Verify it with one real account before a class depends on it.
///

Attributes are read by friendly name first and by OID second, because identity providers differ in which they release; either works.

## The security settings

These are set by the service and are not configurable, because each one is a decision rather than a preference:

| Setting | Value | Why |
|---|---|---|
| `authnRequestsSigned` | on | the identity provider can verify the request came from this service |
| `wantAssertionsSigned` | on | the assertion carrying the identity must be signed |
| `wantMessagesSigned` | off | many identity providers sign the assertion but not the response envelope; requiring both rejects perfectly valid logins |
| `requestedAuthnContext` | off | asking for a specific authentication context makes some identity providers refuse; the institution decides how it authenticates, including its second factor |
| Signature / digest algorithm | RSA-SHA256 | — |
| Clock skew | 120 seconds | `GRADER_SAML_CLOCK_SKEW_SECONDS` |

The second factor — Duo, or whatever the institution uses — happens inside the identity provider. The grader never sees it, and never needs to.

## Configuration

| Setting | Meaning |
|---|---|
| `GRADER_SAML_SP_ENTITY_ID` | the identifier you registered; defaults to the base URL |
| `GRADER_SAML_IDP_ENTITY_ID` | the identity provider's entity id |
| `GRADER_SAML_IDP_SSO_URL` | its single sign-on endpoint (HTTP-POST binding) |
| `GRADER_SAML_IDP_LOGOUT_URL` | where sign-out sends the browser |
| `GRADER_SAML_IDP_CERT` | the identity provider's signing certificate, PEM or bare base64 |
| `GRADER_SAML_SP_CERT`, `GRADER_SAML_SP_KEY` | this service's own certificate and key |

The service's certificate is self-signed and exists only to sign AuthnRequests and identify the service in metadata; generate it with a long life and treat rotating it as a re-registration:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout sp.key -out sp.crt -subj "/CN=grader.example.edu"
```

Multi-line PEM values go into `.env` on one line with `\n` separators — see [Deploy](../operators/deploy.md#3-write-env).

## The Dartmouth configuration

Dartmouth moved from Apero CAS to **Microsoft EntraID** in 2026. The entity id and sign-on URL are already the defaults in `config.py`, so only the signing certificate has to be supplied:

```bash
GRADER_AUTH_MODE=saml
GRADER_SAML_SP_ENTITY_ID=https://grader.dartbrains.org
GRADER_SAML_IDP_ENTITY_ID=https://sts.windows.net/995b0936-48d6-40e5-a31e-bf689ec9446f/
GRADER_SAML_IDP_SSO_URL=https://login.microsoftonline.com/995b0936-48d6-40e5-a31e-bf689ec9446f/saml2
GRADER_SAML_IDP_LOGOUT_URL=https://logout.dartmouth.edu
GRADER_SAML_IDP_CERT=<X509Certificate body from the metadata below>
```

The IdP side comes from ITC's published metadata at <https://dartmouth.github.io/dartmouth-idp-metadata/metadata.xml>. Verify the certificate you paste against the thumbprint ITC publishes rather than trusting the copy you happen to have:

```bash
curl -s https://dartmouth.github.io/dartmouth-idp-metadata/metadata.xml \
  | sed -n 's:.*<X509Certificate>\(.*\)</X509Certificate>.*:\1:p' | tr -d ' \n' \
  | base64 -d | openssl x509 -inform der -noout -fingerprint -sha1
```

EntraID sources `eduPersonPrincipalName` from `userPrincipalName`, so the NetID rule above holds while Dartmouth accounts are `netid@dartmouth.edu` with name forms as aliases. ITC releases each attribute under both its OID and its friendly name.

## Before registration is complete

Run with `GRADER_AUTH_MODE=disabled`. Students can open assignments and press Check all term; Submit tells them sign-in is not available yet and opens the moment you switch to `saml` and redeploy. No notebook changes.

Meanwhile, two paths let named people in: [`grader login-link`](sessions-and-tokens.md#operator-sign-in) for anyone with shell access to mint, and [email sign-in links](email-links.md) for self-service. Publishing an assignment does not need a browser at all — [`grader token`](../reference/cli.md#grader-token) mints a credential for the CLI.

## When something is wrong

| Symptom | Usually |
|---|---|
| The identity provider refuses the request outright | the service is not registered yet, or the entity id does not match exactly |
| `SAML error: invalid_response` | the IdP signing certificate in `.env` is not the one the IdP is using — re-fetch the metadata |
| Signature validation fails intermittently | clock drift; check the host's time sync before raising the skew |
| Sign-in succeeds, but the person is enrolled in nothing | the NetID rule — see the warning above |
| Sign-in loops back to the login page | cookies are being dropped: `GRADER_COOKIE_SECURE=true` without HTTPS end to end, or a frontend URL on a different site than the API |

The service's own view of its configuration is at `/api/health`, which reports the environment and the auth mode without requiring a session.
