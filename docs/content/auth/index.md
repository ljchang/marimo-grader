# How sign-in works

Two kinds of thing need to prove who they are, and only one of them can follow a redirect. That single fact shapes the whole design.

- A **browser** — a student looking at their grades, a TA in the grading queue — can be sent to the institution's identity provider and back. It signs in with SAML and gets a session cookie.
- A **notebook** cannot. It may be running in MoLab, on a cluster behind a VPN, in a WASM page, or on a laptop, and there is no browser redirect that ends up back inside it. So the widget runs a device-style handshake: it shows a short code, the student approves it in a browser tab where SAML works normally, and the notebook receives a short-lived token.

Both paths end at the same place: a `users` row keyed by NetID. Neither path decides what anybody may do.

## The three questions, kept apart

| Question | Answered by | Never by |
|---|---|---|
| **Who are you?** | the institution's identity provider | the grader |
| **How do I know this request is you?** | a session cookie, or a bearer token | — |
| **What may you do?** | the grader's own `enrollments` table | the identity provider |

Roles are deliberately not taken from SAML attributes. An identity provider knows that someone is a member of the university; it does not know that they are the TA for section 02 of one offering, and asking it to would make every roster change an IT ticket. The grader asks SAML for a NetID and nothing else.

## What the grader learns about a person

A NetID, and a display name if the identity provider sends one. No password (none exists here), no email address, no affiliation, no group membership. A student may set a preferred name for themselves; that is stored separately so an identity provider's version never overwrites it.

## The four ways in

| Path | Who | Gives | Where it is documented |
|---|---|---|---|
| SAML | anyone with a browser | a 12-hour session cookie | [SAML and the identity provider](saml.md) |
| Device handshake | a notebook, after its student has completed SAML | an 8-hour notebook token | [Notebook sign-in](notebook-sign-in.md) |
| Email link | an already-enrolled student, when SSO is unavailable | a session cookie | [Email sign-in links](email-links.md) |
| `grader login-link` | an operator with shell access, for a named person | a session cookie | [Sessions and tokens](sessions-and-tokens.md) |

The last two exist for the window before an institution has registered the service, and as the break-glass path if SSO goes down mid-term. Both are meant to be off or unused once SAML works.

## The three auth modes

`GRADER_AUTH_MODE` picks how a browser signs in:

| Mode | Browser sign-in | Notebook tokens | For |
|---|---|---|---|
| `saml` | institutional SSO | after SSO | production |
| `disabled` | a page saying sign-in is not available yet | only operator-minted | a public host waiting for approval |
| `dev` | any NetID typed into a URL, no password | any | a developer's laptop, and nowhere else |

`dev` lets any visitor become any user, including an instructor. The production configuration validator refuses it when `GRADER_ENV=prod`, and that refusal is a startup failure, not a warning.

Running with `disabled` is a genuinely useful state rather than a broken one: students can open assignments and press Check all term, and the moment approval arrives you set `saml` and redeploy. No notebook has to change, because a notebook never knew how sign-in worked.

## What a student experiences

Once, per browser, per eight hours: press **Sign in**, complete the usual university page including its second factor, close the tab. After that, Submit just works. Their password never touches the notebook — the notebook only ever receives a token that says *this is NetID `f00abc1`, for the next eight hours*.

## Where to go next

- [Notebook sign-in](notebook-sign-in.md) — the handshake in detail, with its endpoints, timings and failure modes.
- [SAML and the identity provider](saml.md) — registering the service, and the Dartmouth (EntraID) configuration.
- [Email sign-in links](email-links.md) — the self-service fallback and the four things that fence it in.
- [Sessions and tokens](sessions-and-tokens.md) — lifetimes, storage, CSRF, CORS, rotation.
- [Security model](../operators/security-model.md) — the whole picture, written for a reviewer.
