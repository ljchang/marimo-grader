# Email sign-in links

A self-service way in for a student who is already on the roster: they type their campus address on the sign-in page, and the server mails them a one-time link.

It exists for two windows — before the service provider has been registered with the institution, and if single sign-on goes down mid-term — and it is **off by default**.

/// admonition | Turn it off once SAML works
    type: warning

Proving control of a mailbox is a weaker claim than SAML plus a second factor. Once `GRADER_AUTH_MODE=saml` is working, set `GRADER_EMAIL_LOGIN_ENABLED=false`. The route then returns 404 rather than a refusal, so there is nothing to probe.
///

## What a student does

1. On the sign-in page, choose *email me a link* and enter their campus address.
2. The page says: *if that address belongs to an enrolled account, a sign-in link is on its way.*
3. The message arrives with a link that works once and expires after seven days.
4. Opening it signs that browser in. They can then press **Sign in** inside a notebook and complete the [notebook handshake](notebook-sign-in.md) as usual.

## The four things that fence it in

All enforced server-side, and all of them necessary — an unauthenticated route that sends mail is worth being careful with.

**It is off unless an operator turns it on.** `GRADER_EMAIL_LOGIN_ENABLED` is false by default and the route 404s when false.

**Only the campus domain counts.** An address is converted to a NetID by taking the local part at `GRADER_EMAIL_LOGIN_DOMAIN` — the same rule the roster importer uses for a Canvas *SIS Login ID*. Anything else is ignored. The address itself is never stored; it is a lookup key, not a column.

**Only already-enrolled people receive anything.** The route looks up an existing user with an active enrollment. It never creates a user and never enrolls anyone, so it cannot be used to get an account — only to get back into one.

**Rate limits per NetID.** At most `GRADER_EMAIL_LOGIN_MAX_PER_DAY` links a day (5), no closer together than `GRADER_EMAIL_LOGIN_MIN_INTERVAL_SECONDS` (300). Every send is written to the audit trail.

And one more that is about what the *response* says rather than what the route does: **every outcome returns the same 202 and the same words.** Enrolled or not, rate-limited or not, delivered or not. A different answer for "sent" and "not found" would turn the form into a way of testing whether a given person is in your course, which is roster information.

If delivery fails, the code that was just minted is dropped, so an outage does not quietly consume a student's daily allowance.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `GRADER_EMAIL_LOGIN_ENABLED` | `false` | the whole feature |
| `GRADER_EMAIL_LOGIN_DOMAIN` | `dartmouth.edu` | the only domain whose addresses are considered |
| `GRADER_EMAIL_LOGIN_TTL_SECONDS` | 604800 (7 days) | how long a link stays valid |
| `GRADER_EMAIL_LOGIN_MAX_PER_DAY` | 5 | links per NetID per day |
| `GRADER_EMAIL_LOGIN_MIN_INTERVAL_SECONDS` | 300 | minimum gap between links |
| `GRADER_MAIL_TRANSPORT` | `console` | `console` logs the message; `smtp` sends it |
| `GRADER_MAIL_FROM` | — | must be an address at a verified sending identity |
| `GRADER_MAIL_REPLY_TO` | — | where a confused student's reply should land |
| `GRADER_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_STARTTLS` | — | the SMTP relay |

With `GRADER_MAIL_TRANSPORT=console` the message is written to the log instead of sent — the right setting for staging, and for testing the flow before a relay exists. Turning the feature on with `smtp` and no host configured is refused at startup rather than discovered on the first send.

Setting up Amazon SES as the relay, including the DNS records and scoping the credentials to one identity, is in [Email delivery](../operators/email-delivery.md).

## Checking it works

```bash
curl -sS -X POST https://grader.example.edu/api/v1/auth/email-login \
     -H 'Content-Type: application/json' -d '{"email":"yournetid@example.edu"}'
```

A 202 means *accepted, and I will not tell you whether that matched*. Check the mailbox; if nothing arrives, check the container log, which records the reason.

Do this with a real account before telling students the option exists. If `netid@yourdomain` does not actually deliver at your institution, the NetID-from-address rule does not hold there and the roster needs to carry real addresses instead — much better to find that out now.

## The operator's version

[`grader login-link <netid>`](sessions-and-tokens.md#operator-sign-in) does the same thing without email: it prints a one-time URL for a named person, valid thirty minutes. It works in every auth mode and can only be minted by someone with shell access on the host, which is what makes it safe to leave available.
