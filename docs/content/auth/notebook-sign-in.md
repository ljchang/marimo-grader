# Notebook sign-in

How a notebook proves whose it is, when it cannot follow a redirect. This is the mechanism behind the **Sign in** button a student presses once per session.

It is the [OAuth 2.0 device authorization grant](https://datatracker.ietf.org/doc/html/rfc8628) in shape — the flow a television uses to sign you in to a streaming service — adapted to a notebook whose front end is a widget in the same browser as the tab that will do the signing in.

## The flow

```
notebook widget                    grader                          browser tab
      |                              |                                  |
      ├── POST /auth/device ────────►|                                  |
      |   {client: "…/0.1.1"}        |  mint device_code (secret)       |
      |                              |  mint user_code  ABCD-1234       |
      |◄── codes + verification_url ─┤  10 minutes, single use          |
      |                              |                                  |
      |  open the tab ──────────────────────────────────────────────────►
      |                              |◄── GET /auth/device/verify?code= ┤
      |                              |    no session? → SAML → back here|
      |                              |    bind ABCD-1234 to this NetID  |
      |                              ├── "you can close this tab" ─────►|
      |                              |                                  |
      ├── POST /auth/device/token ──►|  pending … pending …             |
      |   {device_code}              |  approved → mint an 8-hour JWT   |
      |◄── access_token, netid ──────┤  device_code consumed            |
      |                              |                                  |
   store in localStorage,            |                                  |
   submit with Bearer <jwt>          |                                  |
```

Every request in that diagram is made by **JavaScript in the student's browser**. The Python kernel takes no part: it reads the notebook file and builds the payload, and that is all. This is why the flow works identically whether the kernel is in MoLab, on a cluster, on a laptop, or absent entirely because the notebook is running in WASM — and why the only network requirement is that the student's *browser* can reach the grader.

## The two codes

| | `device_code` | `user_code` |
|---|---|---|
| Looks like | 43 random URL-safe characters | `ABCD-1234` |
| Who sees it | only the widget | the human, on screen |
| Sent to | the grader, when polling | typed into the verification page, if the tab did not carry it |
| Stored as | a SHA-256 hash | itself |
| Lifetime | 10 minutes, single use | the same row |

The user code alphabet omits `0`, `O`, `1` and `I`, so a code read off a screen and typed by hand cannot be ambiguous. The device code is the actual secret and is returned exactly once; the server keeps only its hash, so a database read does not yield a credential.

## Step by step

**1. The widget asks for a pair.** `POST /auth/device` with a client string identifying the package and version. The response carries both codes, a `verification_url` with the user code already in it, `expires_in` (600) and `interval` (3).

**2. The student's browser opens the verification URL.** The widget opens it directly, having created the tab synchronously on the click so a popup blocker does not eat it.

If that tab has no grader session yet, `/auth/device/verify` bounces it through `/auth/login` — the ordinary SAML round trip, Duo and all — and comes back. If it arrives without a code (a blocked popup, a link pasted by hand), it renders a small form asking for the code shown in the notebook. Either way the outcome is the same: the user code row is stamped with that NetID and an approval time, and the page says *you can close this tab*.

**3. The widget polls.** `POST /auth/device/token` with the device code, every three seconds:

| Response | Meaning |
|---|---|
| `{"status": "pending"}` | nobody has approved the code yet |
| `{"status": "approved", "access_token": …, "netid": …, "expires_in": 28800}` | signed in; the device code is now consumed |
| `{"status": "expired"}` | ten minutes passed, or the code was already used |

**4. The token goes into the browser.** `localStorage`, under the key `grader:<server>:token`, with its expiry. The next notebook the student opens against the same server finds it there and shows them already signed in.

## What the token is

An Ed25519-signed JWT (`EdDSA`) whose claims are minimal:

```json
{
  "sub": "f00abc1",
  "scope": "notebook",
  "iat": 1771200000,
  "exp": 1771228800,
  "jti": "T2Vb…"
}
```

`sub` is the NetID, `scope` is always `notebook`, and `jti` gives the token an identity that can be revoked. It carries no roles and no course: authorization is resolved from the database on every request, so a token issued before a student was added to a course starts working the moment they are, and stops the moment they are dropped — without being reissued.

Only the server holds the private key. See [Sessions and tokens](sessions-and-tokens.md) for lifetimes and rotation.

## What the student sees, and what it means

| In the notebook | What happened |
|---|---|
| **Sign in with Dartmouth** | no token in this browser for this server |
| *Signed in as f00abc1* | a valid token is in `localStorage` |
| **sign-in is not available yet** | the server is in `disabled` mode; Check still runs, Submit opens later |
| *Could not reach …* | the browser cannot reach the grader — a network restriction, or a CORS origin that has not been allowed |
| *The notebook source is not readable in this environment* | the kernel could not read its own file, so there is nothing to submit; download the notebook and submit from MoLab or a laptop |

The sign-in control also checks `/api/health` before starting, so a student is told that submission is unavailable rather than watching a handshake fail.

## Where the notebook gets its identity

Nothing in the flow above tells the grader *which assignment* is being submitted. That comes from the notebook file itself: publishing writes `grader-server`, `grader-assignment-version` and friends into the PEP 723 block, and the widget reads them. See [Notebook metadata](../reference/notebook-metadata.md).

## Things worth knowing

**One tab, one approval, many notebooks.** The token is per server, not per assignment. A student signs in once and every assignment from that grader is submittable for the next eight hours.

**A notebook that is shared is not a signed-in notebook.** The token is in the browser's local storage, never in the file. Emailing a notebook to a friend hands over the work, not the identity.

**Private-mode browsing and sandboxed frames.** `localStorage` may be unavailable or wiped. The widget handles this without failing, but the student will be asked to sign in again more often.

**Approval is a first-party action.** The tab that approves a code is on the grader's own origin with the student's session cookie. A page on another site cannot approve a code, and no cookie ever crosses an origin — [cross-origin requests from notebooks are made without credentials](sessions-and-tokens.md#cors-which-origins-may-call).
