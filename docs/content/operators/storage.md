# Storage

The storage broker lets signed-in notebooks read course data and keep their own files on Cloudflare R2, with credentials the grader mints per session and per prefix. It is off until every setting below is present. What instructors and students see is on [Course storage](../instructors/course-storage.md); the reasoning is in [the design document](../../storage-architecture.md).

## Why R2

One bucket, prefix-scoped temporary credentials from a single API call, presigned URLs for the browser, and no egress charge — which is the whole bill for a class that downloads the same large files fifty times. Hugging Face keeps the public datasets; it has no way to scope a credential to one student without an Enterprise plan.

## Cloudflare setup

1. **R2 → Create bucket** — name it (the default the grader expects is `dartbrains`), leave the location automatic, do **not** enable public access.

2. **R2 → Manage R2 API Tokens → Create API token** — *Object Read & Write*, scoped to that bucket, no expiry. The confirmation page shows, once:
   - Access Key ID → `GRADER_R2_PARENT_ACCESS_KEY_ID`
   - Secret Access Key → `GRADER_R2_PARENT_SECRET_ACCESS_KEY`
   - the endpoint `https://<account-id>.r2.cloudflarestorage.com` → `GRADER_R2_ENDPOINT`

   This pair is the *parent* credential: every student credential is derived from it and can never exceed it. It lives in `/srv/grader/.env` and nowhere else. The "Token value" on the same page is **not** a REST token; ignore it.

3. **Manage Account → Account API Tokens → Create Token → custom** — one policy: **Entire Account · Workers R2 Storage · Edit**. This token calls the credential-minting endpoint → `GRADER_CF_API_TOKEN`, with the account id → `GRADER_CF_ACCOUNT_ID`.

   The bucket-scoped variant (*R2 Buckets → … → Workers R2 Storage Bucket Item · Edit*) verifies as active but every account-level R2 call, including the mint, returns `code 10000 Authentication error`. Only the account-wide permission works; its reach is bounded by the bucket-scoped parent key anyway.

4. Generate the id secret: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` → `GRADER_STORAGE_UID_SECRET`. It is the HMAC key behind students' opaque prefix ids. **Keep it stable**; rotating it moves every student to an empty prefix.

## Settings

Append to `/srv/grader/.env` (back it up first), then `./deploy.sh <tag>`:

```sh
GRADER_STORAGE_ENABLED=true
GRADER_CF_ACCOUNT_ID=…
GRADER_CF_API_TOKEN=…
GRADER_R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
GRADER_R2_BUCKET=dartbrains
GRADER_R2_PARENT_ACCESS_KEY_ID=…
GRADER_R2_PARENT_SECRET_ACCESS_KEY=…
GRADER_STORAGE_CREDENTIAL_TTL_SECONDS=3600
GRADER_STORAGE_UID_SECRET=…
```

The full list, with defaults, is in the [configuration reference](../reference/configuration.md#storage-broker). With `GRADER_STORAGE_ENABLED=true` the API refuses to start if any value is missing.

## Verify

`curl -fsS https://<host>/api/v1/offerings/<offering-id>/storage/me` without a token should answer **401** (`unauthenticated`), not 404: the routes are mounted and gated.

The acceptance test for the whole design is `scripts/r2_spike.py` in the repository, run from a laptop with the six values in its environment:

```sh
uv run --with obstore --with huggingface_hub scripts/r2_spike.py
```

It mints two students' credentials the way the grader does and tries every cross-prefix operation it can — sibling reads and writes, listing above the prefix, copies, multipart uploads, expired credentials. Every one must be refused by R2. It prints a table and exits non-zero on any failure.

## Operating notes

- **Audit.** `storage_grants` records every credential issued: user, offering, role, prefixes, TTL, client. It is append-only; the credentials themselves are never stored.
- **Revocation.** A student's notebook token can be revoked like any other (`revoked_tokens`); credentials already minted expire within `GRADER_STORAGE_CREDENTIAL_TTL_SECONDS`. Rotating the R2 API token on Cloudflare invalidates every derived credential at once.
- **Cost.** Storage is billed per GB-month with no egress; a 50-student term with a few GB each is a few dollars a month. Consider an R2 lifecycle rule on `cache/users/` if derived caches grow.
- **Term end.** Everything for an offering lives under prefixes that carry `<course>-<term>`; deleting a term is a recursive delete per prefix.
