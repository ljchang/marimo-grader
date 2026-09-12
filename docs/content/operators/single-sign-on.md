# Single sign-on

For the operator. How people prove who they are, the three auth modes, and what to do before the institution has approved the service.

## Two kinds of sign-in, one identity source

- **Browsers** (the web app) sign in through SAML 2.0 against the institution's identity provider and receive an HttpOnly session cookie. Roles come from the grader's own enrollment tables, never from SAML attributes.
- **Notebooks** cannot complete a SAML redirect, so the widget runs a device-style handshake: it asks the grader for a short code, opens a browser tab where the student completes SAML, then polls until the grader mints an eight-hour token bound to that NetID. Credentials never enter the notebook.

The Dartmouth configuration is a Shibboleth IdP: the NetID comes from `eduPersonPrincipalName`, the assertion is signed but the response envelope is not, AuthnRequests are signed, and Duo runs inside the IdP.

## Auth modes

`GRADER_AUTH_MODE` selects one of:

| Mode | Browser sign-in | Notebook tokens | Use |
|---|---|---|---|
| `saml` | institution SSO | after SSO | production |
| `disabled` | a page saying sign-in is not available yet | none, except operator-minted | a public host waiting for SSO approval |
| `dev` | any NetID typed into a URL, no password | any | a developer's laptop only |

`dev` must never run on a host anyone else can reach: it lets any visitor become any user. The production settings validator refuses `dev` when `GRADER_ENV=prod`.

## Registering the service provider

1. Deploy with the SAML certificate and key set; the metadata is served at `/api/v1/auth/saml/metadata` in every mode.
2. Send the registration request to the identity team. A ready-to-send draft is in [`deploy/saml-registration.md`](https://github.com/ljchang/marimo-grader/blob/main/deploy/saml-registration.md): entity id, assertion consumer URL, metadata URL, requested attributes, and who should be authorized.
3. Run with `GRADER_AUTH_MODE=disabled` until approval. Students can open assignments and run checks; Submit tells them sign-in is not available yet.
4. On approval, set `GRADER_AUTH_MODE=saml` and redeploy. No notebook changes are needed.

## Operator sign-in and tokens

While sign-in is disabled, or if SSO is ever down, two commands on the server let named people in. Both require shell access to the host, which is what makes them safe to leave enabled.

```bash
# a one-time browser sign-in link, valid 30 minutes
docker compose -f docker-compose.prod.yml run --rm web grader login-link f00abc1

# a notebook/CLI token, valid 8 hours; also creates the user and an enrollment if asked
docker compose -f docker-compose.prod.yml run --rm web grader token f00abc1 \
    --offering neuroimaging/2026-fall --role instructor --admin
```

Publishing from CI uses a token the same way (`grader publish --token`).

## Sessions and tokens in numbers

| | Lifetime | Where it lives |
|---|---|---|
| Browser session | 12 hours | HttpOnly, Secure, SameSite=Lax cookie; server-side session row |
| Notebook token | 8 hours | the widget's memory and the browser's local storage for that server |
| Device code | 10 minutes, single use | server |
| Login link | 30 minutes, single use | server |

Tokens are Ed25519 JWTs; the private key is `GRADER_JWT_PRIVATE_KEY_PEM`. Rotating it invalidates every outstanding notebook token, which is the intended emergency response.
