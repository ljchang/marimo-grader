# Sessions, tokens and revocation

Every credential the system issues, what it is worth, where it lives, and how to take it away.

## The whole set

| Credential | Lifetime | Lives in | Single use? |
|---|---|---|---|
| Browser session | 12 hours | HttpOnly cookie carrying a signed session id, plus a row in `web_sessions` | no |
| Notebook token | 8 hours | the browser's `localStorage`, keyed by grader server | no |
| Device code | 10 minutes | the widget's memory; the server keeps a hash | yes |
| User code (`ABCD-1234`) | the same 10 minutes | shown on screen | yes |
| Operator login link | 30 minutes | wherever the operator put it | yes |
| Email sign-in link | 7 days | the student's mailbox | yes |

The two on top are what people use all day. The four below are ways of getting one of the top two.

## Browser sessions

The cookie carries an **opaque, signed session id** and nothing else — no user id, no roles, no expiry the client can edit. Everything about the session lives in `web_sessions`, which is what makes a session revocable server-side: delete the row and the cookie is instantly worthless.

Cookie attributes: `HttpOnly` (JavaScript cannot read it), `Secure` in production, `SameSite=Lax`, `Path=/`, and a 12-hour max age matching the server-side row. A tampered cookie fails its signature check and is treated as absent.

**CSRF.** Every session carries its own CSRF token, fetched from `GET /api/v1/auth/csrf` and echoed in `X-CSRF-Token` on every `POST`, `PUT`, `PATCH` and `DELETE`. A mutating request without it is refused with 403 — the check lives in the dependency every authenticated route resolves, so a route cannot omit it by forgetting. `SameSite=Lax` already blocks the common cases; the token covers the rest.

**Sign-out** deletes the session row and clears the cookie, then sends the browser to the identity provider's logout URL.

## Notebook tokens

An Ed25519-signed JWT with five claims — `sub` (NetID), `scope` (always `notebook`), `iat`, `exp`, `jti` — and no roles, no course, no email. Authorization is resolved from the database on every request, so a token stays correct as enrollments change.

They are **bearer** credentials: anyone holding one can act as that student for its remaining life. Three things keep that acceptable — eight hours, a browser-local store rather than the notebook file, and the fact that nothing in the API lets a student do anything more interesting than submit their own work and read their own feedback.

The private key is `GRADER_JWT_PRIVATE_KEY_PEM`, held only by the server. In development a key is generated once and persisted beside the artifact directory so tokens survive a reload; in production a missing key is a startup failure.

## Revocation

| To revoke | Do this | Effect |
|---|---|---|
| One browser session | delete its `web_sessions` row | that browser is signed out |
| Every browser session | rotate `GRADER_SESSION_SECRET` | everyone signs in again |
| Every notebook token | rotate `GRADER_JWT_PRIVATE_KEY_PEM` | every notebook signs in again on its next submit |
| A person's access entirely | end their enrollment | tokens and cookies survive but authorize nothing |

Every request carrying a notebook token checks its `jti` against a `revoked_tokens` table, so single-token revocation is in place at the enforcement end. There is **no route that writes to that table yet** — revoking one token today means rotating the key, which revokes all of them. That is a blunt instrument, and the right one in an emergency.

Rotating the notebook key is the intended emergency response, and it is cheap: students press Sign in once more and carry on. Rotating the SAML certificate is not cheap — it means re-registering with the identity provider.

## CORS: which origins may call

A notebook's JavaScript runs on whatever origin the notebook is served from, so the grader has to allow those origins explicitly.

`GRADER_CORS_ORIGINS` is the list — by default localhost for development, `https://molab.marimo.io`, and the course website. There is also a regular expression for MoLab, which serves a running notebook from a per-session subdomain of `molab.run` whose id changes every session, so no fixed list can cover it.

Allowing an origin broadly is safe here because of one decision: **credentials are never allowed on cross-origin requests.** No cookie crosses an origin, and every route a notebook calls is bearer-authenticated with a token the student had to approve in a first-party tab. An arbitrary page that guessed the endpoints would have nothing to send.

If a student reports *Could not reach the grader* from a course site that used to work, an unlisted origin is the first thing to check. The browser's console will name it.

## Operator sign-in

Two commands on the server let a named person in without the identity provider. Both require shell access on the host, which is precisely what makes them safe to leave available.

```bash
# a one-time browser sign-in link, valid 30 minutes
docker compose -f docker-compose.prod.yml run --rm web grader login-link f00abc1

# a notebook/CLI token, valid 8 hours; creates the user and enrollment if asked
docker compose -f docker-compose.prod.yml run --rm web grader token f00abc1 \
    --offering neuroimaging/2026-fall --role instructor --admin
```

Both work in every auth mode, including `disabled`. Publishing from CI uses the second one (`grader publish --token`).

Login-link codes and device codes are separate kinds of row in the same table, told apart by the client string recorded when they are minted — which is also what lets the audit trail distinguish an operator handing over a link from a student requesting one. `/auth/exchange` accepts only login-link rows.

## Sessions in a hurry

| Symptom | Cause |
|---|---|
| 403 `csrf` on every save | the frontend is not sending `X-CSRF-Token`; fetch it from `/auth/csrf` after sign-in |
| Sign-in loops back to the login page | `GRADER_COOKIE_SECURE=true` without HTTPS end to end, or an API and frontend on different sites |
| A notebook says *Signed in as* someone else | a shared browser profile — the stored token is per browser, not per person. **Sign in again** in the widget discards it and starts a fresh handshake |
| Everyone signed out at once after a deploy | `GRADER_SESSION_SECRET` changed — it must be stable across deploys |
