# DartBrains Storage & Access Architecture — v2

**Status:** Design spec, pre-commitment (supersedes the v1 exploration spec)
**Date:** 2026-09-18
**Stack:** DartBrains marimo-book + molab + marimo-grader (Dartmouth SAML) + dartbrains-tools
**Decision under review:** Hugging Face for public data, Cloudflare R2 for everything private/writable, marimo-grader as the credential broker.

---

## 0. Summary

v1 asked one gating question: *can an arbitrary-code molab session be given narrowly scoped access to exactly one student's, group's, or released assignment's data without receiving credentials that permit broader access?*

Research answers it:

| Backend | Answer | Why |
|---|---|---|
| Hugging Face Storage Buckets | **No** (without Enterprise) | No prefix scoping, no presigned URLs, no STS/session tokens, no bucket policies/ACLs. S3 credentials are UI-generated only. Programmatic token issuance and Resource Groups are Enterprise-plan features. Academia Hub has a 250-seat minimum. |
| Cloudflare R2 | **Yes** | `temp-access-credentials` API: per-bucket, per-prefix, read-only or read-write, TTL ≤ 7 days, returns S3 credentials + session token. Presigned URLs and CORS for the browser path. $0 egress. |
| AWS S3 + STS | Yes | Mature, but egress-billed ($0.085/GB after CloudFront's 1 TB/month free tier) and two more services to operate. The reference baseline, not the pick. |

The second finding is about molab, and it changes v1's caching model: **since 2026-08-26 molab only persists files created through its file browser (plus `mo.persistent_cache` under undisclosed limits), and storage is per-notebook, not per-user.** Each "Open in molab" click forks a separate notebook with its own sandbox. A local disk cache therefore cannot be warm across chapters or sessions. The durable cache tier has to live in the object store.

Recommendation: **commit to HF (public) + R2 (private) + grader (broker)**, but only after the one-day spike in §11 proves cross-student isolation from two real molab sessions. Everything else in this document survives if that spike passes and is moot if it fails.

---

## 1. Goals and non-goals

### Goals (unchanged from v1)

- **Public course data** — large neuroimaging datasets readable by anyone, no sign-in. Already on `huggingface.co/datasets/dartbrains/*`; keep it there.
- **Protected assignment/exam data** — readable only by enrolled students, only after release, read-only.
- **Private student storage** — persistent, writable, visible only to that student plus instructor/TA.
- **Group storage** — persistent, writable, shared by project-group members only.
- **Durable cache** — datasets downloaded once and expensive derivatives computed once, surviving molab teardown and spanning chapters.
- **One student-facing API** that hides which backend holds a path and works identically in the three runtimes DartBrains already targets: local kernel, molab, in-browser WASM workbench.
- **Cheap.** Target ≤ $10/month for a 50-student offering.

### Non-goals

- Students never hold or manage HF tokens, Cloudflare tokens, or AWS keys.
- No secret ever ships inside `dartbrains-tools` or a notebook. A secret in a package a student can `inspect` is not a secret (v1 §7 stands).
- The grader does not become a byte proxy for multi-GB NIfTIs. It issues authorization; bytes flow directly between the runtime and the object store.
- No FUSE/NFS mount dependency. molab's own remote-storage feature is fsspec/obstore-based, which strongly suggests no `/dev/fuse`; a working mount would be a bonus, never a requirement.

---

## 2. What the research changed

### 2.1 molab (facts as of Sept 2026)

- Free; 4 CPU / 32 GB RAM per notebook; optional RTX Pro 6000 GPU; 12 h max session; 90 min idle shutdown.
- Persistence: **only files created/uploaded via the file browser** for notebooks created after 2026-08-26, plus `mo.persistent_cache` data "subject to limitations (such as on size and TTL) that may change at our discretion." Files > 1 GB are never retained. Downloaded data, virtualenvs, unpacked archives are dropped at teardown.
- Storage is **per notebook**. marimo's own guidance: "if you need to access the same data across multiple notebooks, connect your own remote cloud storage."
- `.env` persists across sessions, is editable in a secrets pane, and is **excluded when someone forks the notebook**. It is the one safe place for a per-student token.
- Remote storage = `fsspec` / `obstore` connections. marimo auto-detects `ObjectStore` / `AbstractFileSystem` / `HfApi` variables in the kernel and shows them in the Files panel (browse, search, copy URL, download, insert read/download snippets). Supported: S3-compatible, GCS, Azure, Hugging Face, Google Drive, CoreWeave.
- Launch model: marimo-book emits `https://molab.marimo.io/github/ljchang/dartbrains/blob/master/content/<chapter>.py` (`marimo-book/src/marimo_book/launch_buttons.py:97`). Every student who clicks gets **their own fork of that chapter**.
- Privacy: notebooks are "public but undiscoverable" (gist-style). marimo blocked crawler indexing after a July 2025 incident, but there is no private-notebook setting. **Anyone with the URL can view a student's forked notebook.** This is an exam-integrity concern independent of storage (§9.3).

### 2.2 Hugging Face Storage Buckets

Real and good, but not a multi-tenant authorization system.

- S3-compatible gateway at `https://s3.hf.co/<namespace>`, path-style, single-region, `GetObject` 302s to CDN edge for non-boto clients (proxied for boto3/aws-cli).
- `hf://buckets/...` via `HfFileSystem`; `hf-mount` (NFS or FUSE); server-side copy from dataset repos into buckets; SSE change stream; CDN pre-warming by region; Xet chunk dedup.
- **Explicitly unsupported:** ACLs, bucket policies, object tagging, versioning, lifecycle rules, SSE, bucket notifications. No presigned URLs. No STS or session tokens.
- S3 credentials are generated **only in the web UI** from an existing user token and inherit that token's permissions. Fine-grained tokens can be scoped to namespaces/buckets — bucket granularity at best, never prefix.
- Private buckets in a free org are visible to every org member. Per-member isolation requires Resource Groups (Enterprise). Programmatic scoped token minting for members is "OAuth Token Exchange" (Enterprise). Academia Hub: $10/seat/month, **250-seat minimum**, managed at the institution level — not a per-course option.
- Storage: free user/org gets 100 GB private; public is best-effort/free; paid private storage $18/TB/month.

Verdict: keep HF for what it is already doing well — public, versioned, CDN-served teaching datasets with zero auth and zero cost. Do not attempt student isolation on it.

### 2.3 Cloudflare R2

- `POST /accounts/{account_id}/r2/temp-access-credentials` — body: `bucket`, `parentAccessKeyId`, `permission` ∈ {`object-read-only`, `object-read-write`, `admin-read-only`, `admin-read-write`}, `ttlSeconds` ≤ 604800, optional `prefixes[]` and/or `objects[]`. Returns `accessKeyId`, `secretAccessKey`, `sessionToken`. Credentials are AWS SigV4 with `X-Amz-Security-Token`; work with boto3, s3fs, obstore, rclone, aws4fetch.
- Presigned URLs supported (standard S3 presign against the R2 endpoint). CORS supported, configurable **only via the S3 API** (not the dashboard), and `AllowedHeaders` must list `content-type` explicitly — `*` does not work on R2.
- Pricing: $0.015/GB-month standard; Class A (writes/lists) $4.50/M; Class B (reads) $0.36/M; **$0 egress**; monthly free tier 10 GB + 1 M Class A + 10 M Class B.
- molab's own persistent storage is R2-backed, so molab↔R2 traffic stays inside Cloudflare's network.

### 2.4 marimo-grader already is the identity authority

`dartbrains-grader/backend/src/grader/`:

- `models.py`: `User` (NetID), `Course`, `Offering`, `Section`, `Enrollment` (`role` ∈ student/TA/instructor, `status`, `ta_sections`), `Assignment` (`settings` JSON already carries `due_at`, `required_datasets`), `AssignmentVersion`, `Submission`, `GradeAudit`, `WebSession`, `DeviceCode`, `RevokedToken`.
- `auth/device.py`: RFC 8628-shaped device handshake — widget gets a `user_code`, student approves in a browser tab through SAML+Duo, widget polls and receives a notebook JWT.
- `auth/tokens.py`: EdDSA JWTs, claims `sub` (NetID), `scope="notebook"`, `iat`/`exp`/`jti`; 8 h lifetime; revocable by `jti`.

Everything the broker needs to *decide* already exists. What's missing is the code that turns a decision into a scoped storage credential (§5).

---

## 3. Alternatives considered

Each was evaluated against: student isolation without Enterprise seats, direct bulk transfer, works in all three runtimes, cost at 50 students / ~1 TB reads per term, operational surface for a single instructor.

| # | Option | Isolation | Bulk transfer | WASM path | Cost / month | Verdict |
|---|---|---|---|---|---|---|
| A | HF native (fine-grained tokens, buckets) | ✗ bucket-level, org-wide visibility | ✓ | ✓ public only | $0–18/TB | Public data only |
| A′ | HF Enterprise / Academia Hub | ✓ Resource Groups + token exchange | ✓ | ✓ | ~$1,000+ (50 seats) or 250-seat institutional minimum | Wrong economics |
| B | HF + grader byte proxy | ✓ | ✗ droplet in data path | ✓ | droplet bandwidth | Rejected (v1 §6B concern confirmed) |
| C | AWS S3 + STS session policies (+ CloudFront signed URLs) | ✓ prefix-level | ✓ | ✓ via CloudFront | ~$7 storage; egress $0 for first 1 TB via CloudFront, $85/TB after | Viable baseline; three services, no cost advantage |
| **D** | **R2 + temp-access-credentials, grader mints** | **✓ prefix-level** | **✓** | **✓ presign** | **~$5** | **Recommended** |
| D′ | R2 behind a Cloudflare Worker gateway (JWT-checked HTTP, R2 binding) | ✓ path-level in Worker | ✓ (edge streams) | ✓ plain `fetch` + bearer | ~$5 + $5 Workers paid | Strong second; see §3.1 |
| E | Presign-only broker (backend-agnostic) | ✓ object-level | ✓ | ✓ | backend-dependent | Good fallback if temp creds disappoint; loses fsspec/Files-panel UX |
| F | Backblaze B2 (app keys with `namePrefix` + expiry) | ✓ prefix-level | ✓ | ✓ presign | $6/TB; egress free to 3× storage, then $0.01/GB | Real alternative; keys are long-lived objects you must delete, no session-token model |
| G | Tigris | ✓ IAM policies with prefix ARNs | ✓ | ✓ | $20/TB, $0 egress | No temporary credentials — per-student long-lived keys |
| H | DigitalOcean Spaces (same provider as grader) | ✗ presign only, no STS | ✓ | ✓ presign | $5 flat (250 GB + 1 TB egress) | Fine under Option E only |
| I | Google Drive via molab connector | ✗ per-student Google auth, no course semantics | ~ | ✗ | $0 | Not a course storage layer |
| J | Self-hosted MinIO on the grader droplet | ✓ STS AssumeRole with session policy | droplet bandwidth | ✓ | droplet disk/egress | Operational burden lands on you; DO egress caps |
| K | Per-student HF *user* buckets | ✗ instructor can't read them; needs HF accounts | ✓ | ✓ | $0 | Rejected |

### 3.1 D vs D′ — the real choice

Both put data in R2 and identity in the grader. They differ in *what the notebook holds*:

**D (temp credentials).** The notebook receives S3 credentials scoped to its prefixes. Standard tooling works: `obstore.S3Store`, `s3fs`, `aws s3`, `rclone`. marimo detects the store object and shows the student's private storage in the Files panel — browse, download, insert snippets. No Cloudflare code to deploy: one bucket, one R2 API token, one CORS rule. Broker is ~60 lines calling one Cloudflare endpoint. WASM needs a second tiny endpoint that presigns.

**D′ (Worker gateway).** The notebook holds only the grader JWT it already has. All access is HTTPS `GET/PUT/LIST` against `https://data.dartbrains.org/<logical-path>` with `Authorization: Bearer <jwt>`. A Worker verifies the EdDSA signature (WebCrypto supports Ed25519), maps NetID→prefixes (either by calling the grader or by trusting claims the grader adds to the JWT), and streams from an R2 binding — no S3 credentials exist anywhere in the student runtime. Same code path in all three runtimes. Range requests give random access for free. Cons: a Worker to write and deploy; fsspec access is via `HTTPFileSystem` (works, but the Files panel shows an HTTP root, not a browsable S3 tree); listing must be implemented in the Worker; Workers paid plan ($5/mo) for a class's request volume.

**Pick D first.** It's less code, it gives the best in-editor UX, and its broker is trivially portable to B2 or S3 if R2 ever disappoints. Keep D′ in the back pocket for two specific cases: (1) a public-data CDN front for the HF-hosted datasets if HF's edge turns out slow to molab's region, and (2) if the spike shows temp-credential minting has rate limits or latency that hurt at class scale.

---

## 4. Recommended architecture (Option D)

### 4.1 Physical layout

```
huggingface.co/datasets/dartbrains/*         public · free · CDN · unauthenticated
                                              unchanged; today's hf_hub_download path

r2://dartbrains  (one bucket, one Cloudflare account)
  course/<offering>/...                       private class datasets            student: RO
  assignments/<offering>/<slug>/...           exams / protected data            student: RO iff released
  users/<offering>/<uid>/...                  private student storage           student: RW
  groups/<offering>/<gid>/...                 project-group storage             members: RW
  cache/shared/<offering>/<key>/...           instructor-warmed derivatives     student: RO
  cache/users/<offering>/<uid>/<key>/...      student derivatives               student: RW
  submissions/<offering>/...                  grader-only; never in a student credential
```

`<uid>` is an opaque per-offering identifier (e.g. HMAC of NetID with a per-offering secret), not the NetID — so a listing never leaks classmates' identities and a credential dumped to stdout reveals nothing about the roster.

**One bucket.** R2 temp credentials are scoped to a single bucket; a multi-bucket layout multiplies credentials for no isolation gain. Prefixes give the same partitioning, and end-of-term cleanup is one recursive delete per prefix.

**Per-offering prefixes.** Even course-shared data is namespaced by offering so an exam bucket from 2026F cannot be reached by a 2027W credential, and so retiring a term is a prefix delete.

### 4.2 Logical namespace (student-facing)

```
/course/                     RO
/assignments/<slug>/         RO, only after release
/private/                    RW
/group/                      RW
/cache/                      transparent; managed by the library
```

Notebooks only ever address logical paths. `dartbrains_tools.storage` maps them to HF or R2 physical locations from the broker's mount table.

### 4.3 Credential model — two credentials per session

R2's `permission` applies to the entire credential, so read-only and read-write scopes cannot share one. The broker mints two:

```python
ro = r2.temp_credentials(
    bucket="dartbrains",
    permission="object-read-only",
    prefixes=[
        f"course/{offering}/",
        *[f"assignments/{offering}/{slug}/" for slug in released_assignments],
        f"cache/shared/{offering}/",
    ],
    ttl=3600,
)
rw = r2.temp_credentials(
    bucket="dartbrains",
    permission="object-read-write",
    prefixes=[
        f"users/{offering}/{uid}/",
        *[f"groups/{offering}/{gid}/" for gid in groups],
        f"cache/users/{offering}/{uid}/",
    ],
    ttl=3600,
)
```

A student who prints both credentials learns nothing beyond what they were already authorized to read. There is no prefix in either credential they could not already reach through the API.

**TTL: 1 hour**, refreshed transparently by the library from the grader JWT (8 h). Short enough that a revocation or an assignment un-release takes effect within the hour; long enough that a lab session never sees a credential expire mid-download.

### 4.4 Identity flow

```
student opens chapter in molab (own fork)
        │
        ▼
storage.signin()  ── JWT cached in .env? ──yes──▶ skip
        │ no
        ▼
device handshake (existing grader widget)
   student clicks link → Dartmouth SAML + Duo → approves user_code
        │
        ▼
notebook JWT (8 h, NetID, revocable)  → written to .env (molab) / keyring or ~/.config (local) / IndexedDB (WASM)
        │
        ▼
POST /api/v1/storage/session   Authorization: Bearer <jwt>
        │
        ▼ grader resolves: enrollment, role, section, groups, released assignments
        │
        ▼ grader calls Cloudflare temp-access-credentials ×2
        │
        ▼
{ mounts[], credentials{ro, rw}, expires_at }
        │
        ▼
dartbrains_tools.storage builds obstore/s3fs clients; bytes flow R2 ⇄ runtime directly
```

The grader is in the control path only. Its droplet never carries a NIfTI.

---

## 5. marimo-grader: the storage broker

### 5.1 Endpoints

```
POST /api/v1/storage/session
  auth:  notebook JWT (existing)
  body:  { "offering": "<id or slug>" }          # optional if JWT already implies one active enrollment
  200:   {
           "backend": "r2",
           "endpoint": "https://<account>.r2.cloudflarestorage.com",
           "bucket": "dartbrains",
           "region": "auto",
           "expires_at": "2026-09-18T19:04:00Z",
           "mounts": [
             {"logical": "/course",             "prefix": "course/psyc60-2026F/",                "mode": "r",  "cred": "ro"},
             {"logical": "/assignments/week-03","prefix": "assignments/psyc60-2026F/week-03/",   "mode": "r",  "cred": "ro"},
             {"logical": "/private",            "prefix": "users/psyc60-2026F/a3f1…/",           "mode": "rw", "cred": "rw"},
             {"logical": "/group",              "prefix": "groups/psyc60-2026F/group-07/",       "mode": "rw", "cred": "rw"},
             {"logical": "/cache/shared",       "prefix": "cache/shared/psyc60-2026F/",          "mode": "r",  "cred": "ro"},
             {"logical": "/cache/private",      "prefix": "cache/users/psyc60-2026F/a3f1…/",     "mode": "rw", "cred": "rw"}
           ],
           "public": [
             {"logical": "/data/localizer", "backend": "hf", "repo": "dartbrains/localizer"}
           ],
           "credentials": {
             "ro": {"access_key_id": "...", "secret_access_key": "...", "session_token": "..."},
             "rw": {"access_key_id": "...", "secret_access_key": "...", "session_token": "..."}
           }
         }

POST /api/v1/storage/presign
  auth:  notebook JWT
  body:  { "path": "/private/results/model.pkl", "method": "GET" | "PUT", "expires": 900 }
  200:   { "url": "https://…?X-Amz-…", "expires_at": "…" }
  # For the WASM runtime, which cannot reasonably SigV4-sign in Pyodide.
  # Same authorization logic as /session; the grader signs with its parent key.

GET  /api/v1/storage/ls?path=/private/results/     # optional convenience for WASM; molab/local list via S3
```

Instructor/TA variants come from the same endpoint: an `instructor` or `ta` enrollment gets `users/<offering>/` (all students, or the TA's sections) under `ro` — or `rw` if you want TAs to be able to drop feedback files into a student's folder.

### 5.2 Data-model additions

- `Group(id, offering_id, slug, name)` and `GroupMember(group_id, enrollment_id)`. Roster UI: CSV upload like `RosterUpload`, or instructor-side drag-and-drop later.
- `Assignment.settings["release_at"]` (ISO 8601). Already has `due_at`; add `release_at` and, for exams, `storage_prefix` if the data lives somewhere other than `assignments/<offering>/<slug>/`.
- `StorageGrant` audit rows: `(user_id, offering_id, role, prefixes_ro, prefixes_rw, ttl, issued_at, client, jti)`. Append-only, same spirit as `grade_audit`.
- `Offering.settings["storage"]`: `{"bucket": "dartbrains", "uid_secret_ref": "...", "enabled": true}` so a course can opt out.

### 5.3 Exam release gating

The broker includes `assignments/<offering>/<slug>/` in the `ro` prefix list **only when** `release_at <= now < (close_at or ∞)` for an active enrollment. Before release the prefix is absent from every credential ever minted, so the bytes are unreachable at the storage layer regardless of what the notebook UI shows. With a 1 h TTL, pulling an assignment (setting `release_at` into the future) locks everyone out within the hour; revoking the JWT `jti` locks one student out immediately.

Optional attempt gating (v1 §7): tie the grant to an open `Submission` attempt window if you ever need "you can see the exam data only while your attempt is open."

### 5.4 Cloudflare configuration (one-time)

1. Create bucket `dartbrains`. Do not enable public access.
2. R2 → **Manage R2 API Tokens** → create an account-owned token, *Object Read & Write*, scoped to bucket `dartbrains`, no expiry. It yields an **Access Key ID + Secret Access Key** (the S3 pair) and the endpoint `https://<account>.r2.cloudflarestorage.com`. The access key is the `parentAccessKeyId`; store the pair as `GRADER_R2_PARENT_ACCESS_KEY_ID` / `GRADER_R2_PARENT_SECRET`. This is the only long-lived storage secret and it lives on the droplet, never in a notebook.
   *Verified 2026-09-18:* the "Token value" this screen also shows is **not** a Cloudflare REST bearer token — it fails `/tokens/verify` and returns `code 10000 Authentication error` on the mint endpoint. Ignore it.
3. Manage Account → **Account API Tokens** → Create Token → custom policy **Entire Account · Workers R2 Storage · Edit**. This is `GRADER_CF_API_TOKEN` (with `GRADER_CF_ACCOUNT_ID`), the token that calls `temp-access-credentials`.
   *Verified 2026-09-18:* the bucket-scoped variant (`R2 Buckets → dartbrains → Workers R2 Storage Bucket Item · Edit`) is **insufficient** — it verifies as active but every account-level R2 REST call, including the mint, returns `10000`. Only the account-wide permission works. Blast radius is bounded anyway: temporary credentials can never exceed the bucket-scoped parent key from step 2.
4. Set CORS on the bucket via the S3 API (dashboard cannot): `AllowedOrigins: ["https://dartbrains.org", "http://localhost:*"]`, `AllowedMethods: [GET, PUT, HEAD]`, `AllowedHeaders: ["content-type", "range", "x-amz-*"]` (R2 rejects `*`), `ExposeHeaders: ["ETag", "Content-Range"]`.
5. Optional: lifecycle rule to expire `cache/users/**` after N days; R2 supports lifecycle rules.

### 5.5 Instructor tooling

`grader storage` CLI subcommands, mirroring `grader publish`:

```
grader storage upload  --offering psyc60-2026F course/ ./localizer-derivatives/
grader storage release --offering psyc60-2026F --assignment midterm --at 2026-11-04T09:00-05:00
grader storage groups  --offering psyc60-2026F groups.csv
grader storage warm    --offering psyc60-2026F content/Connectivity.py   # runs the notebook, pushes cache
grader storage ls      --offering psyc60-2026F users/<netid>/
grader storage purge   --offering psyc60-2026F --confirm
```

The CLI authenticates through the same device handshake and gets an instructor-scoped credential; it never needs the parent key.

---

## 6. `dartbrains_tools.storage`

Lives in dartbrains-tools (PyPI), re-exported as `dartbrains.storage`. Generalizes today's `dartbrains_tools/data/_hub.py` (`download(repo_id, filename)` with a WASM branch into `_wasm_cache.py`) — the shape is the same, the backends multiply.

### 6.1 Student API

```python
from dartbrains import storage

storage.signin()                          # no-op if a valid JWT is cached; else device handshake

course  = storage.course()                # RO
private = storage.private()               # RW
group   = storage.group()                 # RW; raises if not in a group
exam    = storage.assignment("midterm")   # RO; raises NotReleased before release_at
public  = storage.dataset("localizer")    # HF; no sign-in required

p = course.local_path("sherlock/derivatives/fmriprep/sub-01/func/bold.nii.gz")   # ordinary path
private.put("week3/betas.pkl", betas)     # pickles / DataFrames / nib images / bytes / paths
betas = private.get("week3/betas.pkl")
with private.open("notes.txt", "w") as f: ...
private.ls("week3/"); private.glob("**/*.nii.gz"); private.exists(...)
group.sync("./figures", "figures/")       # rsync-like, either direction
private.usage()                           # bytes used; quota if the offering sets one

fs = private.fs                           # obstore.S3Store (or fsspec) rooted at the student's prefix
                                          # → marimo Files panel auto-detects and shows it
```

`local_path()` is the workhorse for nibabel/nilearn/nltools: resolve authorization → local cache hit? → validate cheaply (size + ETag) → else download → return path.

### 6.2 Backends

| Backend | Used for | Auth | Notes |
|---|---|---|---|
| `HFRepoBackend` | `/data/*` public datasets | none | today's `hf_hub_download`; WASM branch via `resolve` URLs unchanged |
| `R2Backend` | everything under the bucket | temp creds from broker | `obstore.S3Store` primary, `s3fs` fallback; refreshes creds before `expires_at` |
| `PresignBackend` | WASM runtime | presigned URLs from broker | sync XHR as in `_wasm_cache.py`; PUT via presigned PUT |
| `LocalBackend` | offline dev / tests / build | none | maps logical roots to local dirs; used by the marimo-book build |

### 6.3 Runtime matrix

| | Local kernel | molab | WASM workbench |
|---|---|---|---|
| JWT storage | `~/.config/dartbrains/token` (0600) | `.env` (persisted, not forked) | IndexedDB (own mount, like `_wasm_cache`) |
| Transport | obstore / s3fs | obstore / s3fs | presigned URL + XHR |
| Local cache | `~/.cache/dartbrains/objects/` (durable) | `/tmp/dartbrains/` (**ephemeral**) | IDBFS (durable, budgeted, exists today) |
| Durable cache | remote (§7) | remote (§7) — the only durable tier | IDBFS + remote |
| Files panel | ✓ | ✓ | n/a |

Detection is the same trick `_wasm_cache.active()` already uses, plus a molab probe (env var / hostname; verify in spike).

### 6.4 Build-time behaviour

The marimo-book build runs every notebook. It has no student identity. `LocalBackend` (or an instructor-scoped credential from a CI secret) backs `/course`; `/private` and `/group` point at a scratch directory so `put()` succeeds and the rendered page shows what a student would see. Assignment notebooks that read exam data do not run at build time — the assignment drawer already keeps them out of the static site.

---

## 7. Caching

Given molab's ephemeral disk, the hierarchy is:

```
1. process memory                 (mo's reactive graph already does this)
2. runtime-local disk             molab: /tmp, gone at teardown · local: ~/.cache · WASM: IDBFS
3. cache/shared/<offering>/       instructor-warmed, read-only          ← the big win
4. cache/users/<offering>/<uid>/  student's own derivatives, durable across notebooks & sessions
5. compute
```

### 7.1 Datasets (`local_path`)

Public data: HF CDN → local disk. On molab, re-downloaded per notebook per session; a 107 MB preprocessed bold is 3–8 s, which is acceptable. Mirroring public data into R2 buys nothing on egress ($0 both) and only matters if HF's edge is slow to molab's region — benchmark in the spike before deciding.

Private data: R2 → local disk, same policy.

### 7.2 Derivatives (`@storage.cache`)

```python
@storage.cache                      # key = f(func qualname, source hash, args, kwargs, pinned pkg versions)
def fit_glm(subject, smoothing_mm):
    ...
    return betas
```

Lookup order: local → `cache/shared` → `cache/private` → compute → write to local + `cache/private`. The instructor's `grader storage warm` runs the same notebook with an instructor credential whose `rw` scope includes `cache/shared/`, so every student's first run of a heavy chapter becomes a download instead of a computation.

Two cautions carried over from `CLAUDE.md`: `mo.persistent_cache` memoizes Python values but not matplotlib side effects, so neither it nor `@storage.cache` may wrap a plotting cell; and molab's persistent-cache limits are explicitly discretionary, so do not build course guarantees on it.

### 7.3 Budgets

`cache/users/**` gets an R2 lifecycle expiry (e.g. 90 days) so abandoned derivatives don't accumulate. `usage()` lets a student see their footprint; an optional per-offering quota is enforced client-side (soft) and by an instructor cron (hard) — R2 has no per-prefix quota primitive.

---

## 8. Groups

Group storage is just another `rw` prefix in a member's credential. Members run independent molab notebooks against `/group/` — no simultaneous-editing requirement, no notebook co-editing. Code collaboration stays on GitHub. The grader owns `student → offering → group`. A student in two groups (rare) gets two mounts: `/group/<slug>`.

---

## 9. Threat model

Assume a student runs arbitrary Python and can read env vars, `.env`, memory, network traffic, and `inspect.getsource` of anything.

| Threat | Mitigation |
|---|---|
| Student reads their own credential | By design harmless: it names only prefixes they may reach. |
| Student reads another student's prefix | Impossible by construction — the credential does not include it; R2 enforces server-side. This is the spike's pass/fail test. |
| Student reads pre-release exam data | Prefix absent from every credential until `release_at`. Not UI-hidden; unreachable. |
| Student shares their credential with a friend | Same exposure as sharing a password. 1 h TTL bounds it; `StorageGrant` audit + R2 access logs (if enabled) make it attributable. Accept. |
| Student writes to `course/` | `ro` credential cannot PUT. |
| Student reaches `submissions/` | Never in any student credential. |
| Notebook fork leaks a token | `.env` is excluded from molab forks. Also token is per-student and revocable. |
| Grader compromise | Holds the parent key; blast radius is the bucket. Same trust already placed in it for grades. Rotate the R2 token; all temp creds derived from it die. |
| molab notebook is public-by-URL | Not a storage issue, but an exam-integrity one: a student's *notebook* (code, outputs) is visible to anyone with the link. See §11 Q2. |

---

## 10. Cost (50-student offering)

| Item | Size | $/month |
|---|---|---|
| Public datasets on HF | ~200 GB | 0 |
| R2 — private course data + exams | 40 GB | 0.60 |
| R2 — 50 × 5 GB private | 250 GB | 3.75 |
| R2 — shared warm cache | 50 GB | 0.75 |
| R2 — 50 × 2 GB private cache | 100 GB | 1.50 |
| R2 ops (Class A/B) | ≪ free tier | 0 |
| R2 egress | ~1 TB/term | 0 |
| Broker | existing DO droplet | 0 |
| **Total** | | **≈ $7** |

Comparison: AWS S3 + CloudFront ≈ $10 storage + $0–85 egress depending on whether reads stay under CloudFront's 1 TB free tier (they will for one section; not for two). HF Enterprise ≈ $1,000+. Backblaze B2 ≈ $3 (egress free to 3× storage ≈ 1.3 TB) — the cheapest, but with long-lived keys to manage instead of session tokens.

---

## 11. Open questions and the spike

### 11.1 Ranked unknowns

1. ~~**Does R2 prefix scoping actually hold under adversarial use?**~~ **Yes — verified 2026-09-18, see §11.3.** Sibling `GET`/`PUT`/`DELETE`, root listing, cross-prefix `CopyObject` in both directions, multipart into a sibling prefix, writes with the read-only credential, and an expired (`ttl=1`) credential are all refused server-side. Path traversal is a non-issue: obstore refuses `..` keys client-side, boto3 sends them verbatim and R2 answers `SignatureDoesNotMatch`; a literal `%2E%2E` key is a distinct object (`NoSuchKey`), not a normalised path.
2. **molab notebook visibility.** Public-by-URL is fine for chapters, questionable for exams. Ask marimo (they invite educator contact) whether unlisted-but-authenticated or org-private notebooks exist or are planned. If not, the mitigation is procedural: exam notebooks live in the WASM workbench or a local kernel, not molab. *Ask.*
3. **Sign-in friction.** One device handshake per molab notebook (per chapter) per term, cached in `.env`. If that's too much, the alternative is a longer-lived refresh token (30 days) in `.env` with the 8 h JWT minted from it silently. Decide before the token model is built. *Decision.*
4. **`obstore.S3Store` with temporary credentials and a prefix.** Session token parameter name, and whether a prefix-rooted store shows a browsable tree in marimo's Files panel (or whether `s3fs` is needed for that). *Spike.*
5. **Cloudflare temp-credential API rate limits and latency.** *Measured 2026-09-18:* 0.36–0.44 s per mint from a laptop. Two calls per student per hour is ~100/h for the class; no rate limit was hit during the spike (~8 mints in a minute). Watch for it at class scale.
6. **How does molab authenticate its own users** (GitHub? Google?), and does a class of 50 on the free tier hit any fairness limits? *Ask.*
7. **HF → molab throughput** for the public datasets. If the HF edge is slow from molab's region, the D′ Worker (or an R2 mirror) becomes worth it. *Benchmark.*
8. **Anything mountable in molab?** Probably not; `hf-mount`/`rclone mount` need FUSE/NFS. One `ls /dev/fuse` in a molab cell answers it. *Spike, low stakes.*
9. **Dartmouth institutional cloud.** If ITC provides AWS/GCP/Azure credits or an institutional Cloudflare account, the cost table changes little but ownership/continuity might. *Ask.*

### 11.2 The spike (one day)

Goal: prove or refute isolation from real molab sessions before writing any API surface.

1. Create bucket, R2 API token, Cloudflare API token, CORS rule (§5.4).
2. Put three objects: `course/x/a.txt`, `users/x/A/a.txt`, `users/x/B/b.txt`.
3. Hand-mint (curl) credentials for "A" (`ro`: `course/x/`; `rw`: `users/x/A/`) and "B".
4. In two molab notebooks, with `obstore` and with `s3fs`: read own, write own, list own; then attempt every cross-prefix operation in §11.1 Q1. Every cross attempt must fail with 403.
5. Time: credential mint latency; 107 MB download from R2 vs from HF; 107 MB upload; range-read of 1 MB from a 500 MB object.
6. Check `/dev/fuse`, `.env` persistence across a teardown, and Files-panel detection of the prefix-rooted store.

Pass → build §5 and §6. Fail on isolation → Option E (presign-only) on R2 or B2 keeps everything else in this document intact.

### 11.3 Spike results (2026-09-18, `scripts/r2_spike.py` + a boto3 traversal check)

**Isolation: 22/22.** Student A's credentials could read, write, list, and delete only under their own prefix and read only the course prefix; every cross-prefix operation returned `PermissionDeniedError` from R2. A wider `LIST` was refused outright rather than filtered, so no neighbour's keys leak. B's credential was equally blind to A. A `ttl=1` credential was dead 3 s later. A presigned GET from the parent key was fetchable with plain `urllib` — the WASM path works.

**Throughput (laptop, residential fibre):** mint 0.4 s · 100 MB upload 5.5 s · 105 MB download with a temporary credential 3.4 s (31 MB/s) · 1 MB range read from the middle of a 100 MB object 0.08 s · the same 112 MB file from HF 3.6 s (31 MB/s). R2 and HF are indistinguishable from here; the comparison that matters is from molab's region (still open, Q7).

**Split-credential consequence, confirmed:** a server-side copy from `course/` into `users/<uid>/` fails, because no single credential holds read on the source *and* write on the destination. "Copy a course file into my private area" must be a download-then-upload in the library, not a `CopyObject`. Cheap at this scale; note it in `Mount.copy_from()`'s docstring.

**Still open from the molab side (needs a molab session, `run(env, molab=True)`):** does a Python-written `.env` survive teardown; is `/dev/fuse` present; does a prefix-rooted `S3Store` appear in the Files panel.

---

## 12. Phasing

1. **Spike** (§11.2).
2. **Broker**: `/storage/session`, `/storage/presign`, `Group` models, `release_at`, `StorageGrant`. Tests against a fake Cloudflare endpoint.
3. **Library**: `dartbrains_tools.storage` with `R2Backend` + `HFRepoBackend` + `LocalBackend`; `local_path`, `get/put`, `ls`; `.env` token cache; credential refresh. Ship as dartbrains-tools 0.2.
4. **First consumer**: one chapter (`Connectivity.py` or `Download_Data.py`) reading a private course dataset; one assignment writing to `/private`.
5. **WASM**: `PresignBackend`; CORS verified from `dartbrains.org`.
6. **Cache**: `@storage.cache`, `grader storage warm`, shared cache for the two heaviest chapters.
7. **Groups + instructor CLI**.
8. **Docs**: a "Where your data lives" page in the book; update `Download_Data.py`.

---

## 13. Questions to take to other people

**marimo** (contact@marimo.io — they ask educators to write):
1. Is there any private/unlisted-authenticated notebook mode, or plans for classroom orgs?
2. Any per-user (not per-notebook) persistent storage planned?
3. What are the actual `mo.persistent_cache` size/TTL limits on molab today?
4. Is `/dev/fuse` or NFS mounting available in the molab sandbox?
5. Which provider/region hosts molab compute (for HF pre-warming / R2 locality)?
6. Any hook to pre-seed `.env` when a notebook is opened from a URL?

**Hugging Face** (only if we ever want private data there):
1. Any plan for prefix-scoped tokens or STS-like credentials on Storage Buckets outside Enterprise?
2. Any per-course academic option below the 250-seat Academia Hub minimum?

**Dartmouth ITC / Research Computing:**
1. Institutional Cloudflare, AWS, or GCP accounts a course can bill to?
2. Any policy constraint on student data (FERPA) living in R2 — the grader's FERPA posture already covers submissions; private storage is the same class of data.

---

## Appendix — Sources consulted

- molab: [storage overview](https://marimo.io/pages/molab/storage) · [seamless storage (Aug 2026 persistence change)](https://marimo.io/blog/seamless-storage-in-molab) · [remote storage connectors](https://marimo.io/blog/drive-storage) · [molab guide](https://docs.marimo.io/guides/molab/) · [remote storage detection](https://docs.marimo.io/guides/working_with_data/remote_storage/) · [privacy discussion](https://biggo.com/news/202507200125_molab-privacy-security-concerns) · [for educators](https://marimo.io/for-educators)
- Hugging Face: [Storage Buckets](https://huggingface.co/docs/hub/en/storage-buckets) · [S3 compatibility & limitations](https://huggingface.co/docs/hub/en/storage-buckets-s3) · [access patterns](https://huggingface.co/docs/hub/storage-buckets-access) · [storage limits & pricing](https://huggingface.co/docs/hub/storage-limits) · [programmatic access control](https://huggingface.co/docs/hub/programmatic-user-access-control) · [enterprise token management](https://huggingface.co/docs/hub/enterprise-tokens-management) · [Academia Hub](https://github.com/huggingface/hub-docs/blob/main/docs/hub/academia-hub.md)
- Cloudflare R2: [temporary credentials](https://developers.cloudflare.com/r2/api/s3/temporary-credentials/) · [API reference](https://developers.cloudflare.com/api/resources/r2/subresources/temporary_credentials/methods/create/) · [pricing](https://developers.cloudflare.com/r2/pricing) · [presigned URLs & CORS gotchas](https://mikeesto.medium.com/pre-signed-urls-cors-on-cloudflare-r2-c90d43370dc4)
- Alternatives: [Backblaze B2 app keys](https://www.backblaze.com/apidocs/b2-create-key) · [B2 pricing](https://www.backblaze.com/cloud-storage/pricing) · [Tigris IAM](https://www.tigrisdata.com/docs/iam/) · [DO Spaces pricing](https://docs.digitalocean.com/products/spaces/details/pricing/) · [CloudFront free tier](https://aws.amazon.com/cn/blogs/china/aws-free-tier-data-transfer-expansion-100-gb-from-regions-and-1-tb-from-amazon-cloudfront-per-month)
- obstore: [R2 example](https://developmentseed.org/obstore/latest/examples/r2/) · [fsspec integration](https://developmentseed.org/obstore/latest/integrations/fsspec/)
- Local code: `dartbrains-grader/backend/src/grader/{models.py, auth/device.py, auth/tokens.py}` · `dartbrains-tools/src/dartbrains_tools/data/{_hub.py, _wasm_cache.py}` · `marimo-book/src/marimo_book/launch_buttons.py`
