# Email delivery

Only needed if you want [email sign-in links](../auth/email-links.md) — the self-service path for the window before SAML is registered, or if it goes down mid-term. The grader sends no other mail.

Amazon SES is used here through its **SMTP interface**, so the service needs no AWS SDK and no AWS credentials at runtime: a host, a username and a password. Any other relay works the same way.

Before SES exists, `GRADER_MAIL_TRANSPORT=console` writes each message to the container log instead of sending it. That is the right setting on staging, and for testing the flow.

## One-time SES setup

**1. Pick a region and stay in it.** SES identities are per-region; `us-east-1` is fine.

**2. Verify a sending domain** — a subdomain, so grader mail cannot affect the reputation of your main domain:

```bash
aws sesv2 create-email-identity --email-identity mail.example.edu --region us-east-1
aws sesv2 get-email-identity --email-identity mail.example.edu --region us-east-1 \
    --query 'DkimAttributes.Tokens'
```

Each of the three tokens becomes a DNS CNAME: `<token>._domainkey.mail.example.edu → <token>.dkim.amazonses.com`.

**3. SPF and DMARC** as TXT records on `mail.example.edu`:

```
v=spf1 include:amazonses.com ~all
_dmarc  →  v=DMARC1; p=none; rua=mailto:you@example.edu
```

**4. Request production access, first.** New accounts sit in the SES sandbox and can only send to pre-verified addresses, which is useless for a class. Approval usually takes about a day, so do this before you need it:

```bash
aws sesv2 put-account-details --region us-east-1 \
    --production-access-enabled --mail-type TRANSACTIONAL \
    --website-url https://example.edu \
    --use-case-description "One-time sign-in links for students enrolled in a single course. \
Recipients are course rosters only; volume is tens of messages per term; bounces and \
complaints are monitored."

aws sesv2 get-account --region us-east-1 --query ProductionAccessEnabled
```

**5. Create SMTP credentials, scoped to this identity.** The console button works but creates an IAM user with account-wide send rights; two commands do better:

```bash
aws iam create-user --user-name grader-ses
aws iam put-user-policy --user-name grader-ses \
    --policy-name ses-send-mail --policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Action": ["ses:SendRawEmail", "ses:SendEmail"],
        "Resource": "arn:aws:ses:us-east-1:<account-id>:identity/mail.example.edu"
      }]}'
aws iam create-access-key --user-name grader-ses
```

The SMTP **username** is the access key id. The SMTP **password** is an HMAC derivation of the secret access key, not the key itself; [`deploy/ses-smtp-password.py`](https://github.com/ljchang/marimo-grader/blob/main/deploy/ses-smtp-password.py) computes it:

```bash
python3 deploy/ses-smtp-password.py <SecretAccessKey> us-east-1
```

Scoping matters here: a leaked key of this shape can send only as this domain, never as another identity in the account.

**6. Fill in `.env`** and redeploy:

```bash
GRADER_EMAIL_LOGIN_ENABLED=true
GRADER_MAIL_TRANSPORT=smtp
GRADER_MAIL_FROM="Grader <grader@mail.example.edu>"
GRADER_MAIL_REPLY_TO=you@example.edu
GRADER_SMTP_HOST=email-smtp.us-east-1.amazonaws.com
GRADER_SMTP_PORT=587
GRADER_SMTP_USERNAME=<SES SMTP username>
GRADER_SMTP_PASSWORD=<SES SMTP password>
```

`GRADER_MAIL_FROM` must be at a verified identity or SES rejects every message. Turning the feature on with `smtp` and no `GRADER_SMTP_HOST` is refused at startup — a sign-in link nobody receives is worse than no button at all.

## Verify before you tell anyone

```bash
curl -sS -X POST https://grader.example.edu/api/v1/auth/email-login \
     -H 'Content-Type: application/json' -d '{"email":"<yournetid>@example.edu"}'
```

A 202 means *accepted, and I will not say whether that address matched* — the response is identical in every case, deliberately. Check the mailbox, and the container log if nothing arrives.

/// admonition | Test this with a real account
    type: warning

Sign-in links assume the local part of a campus address **is** the NetID — the same rule the roster importer uses for a Canvas *SIS Login ID*. If `netid@yourdomain` does not deliver at your institution, that assumption does not hold and the roster needs real addresses instead. Find that out now rather than after the first assignment.
///

## Turning it off

Set `GRADER_EMAIL_LOGIN_ENABLED=false` once SAML is working and redeploy. The route then returns 404 rather than a refusal, so there is nothing left to probe. The SES identity can stay; it costs nothing idle and the path is there if you need it again.
