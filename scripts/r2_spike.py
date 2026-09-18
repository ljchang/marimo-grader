"""R2 isolation spike: does a prefix-scoped temporary credential really stop a student
reaching a neighbour's prefix?  (docs/storage-architecture.md §11.2)

This is the one experiment the whole storage design hangs on. It mints two students'
credentials the way the grader will, then tries every cross-prefix operation we could
think of and expects each to be refused by R2 itself -- not by anything client-side.

Run locally::

    uv run --with obstore --with huggingface_hub scripts/r2_spike.py

with these in the environment (or a ``.env`` file you ``source``; never commit them)::

    CF_ACCOUNT_ID               Cloudflare account id
    CF_API_TOKEN                API token that may call r2/temp-access-credentials
    R2_ENDPOINT                 https://<account>.r2.cloudflarestorage.com
    R2_BUCKET                   dartbrains
    R2_PARENT_ACCESS_KEY_ID     the R2 API token's access key (the *parent* credential)
    R2_PARENT_SECRET            its secret

Run in molab: paste this file into a cell, then in another cell call
``run({...the six values...}, molab=True)``. The molab flag adds the checks that only
make sense there (does a ``.env`` written from Python survive teardown, is there a
``/dev/fuse``, does a prefix-rooted store show up in the Files panel).

Prints a PASS/FAIL table. Objects it seeds live under ``_spike/`` and are deleted at the
end unless ``keep=True``.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta

ROOT = "_spike"  # every object this script touches lives under here
HF_REPO = "dartbrains/localizer"
HF_FILE = (
    "derivatives/fmriprep/sub-S01/func/"
    "sub-S01_task-localizer_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
)  # ~107 MB; the file the ICA chapter loads, so a realistic benchmark

DENIED_MARKERS = ("403", "forbidden", "accessdenied", "access denied", "permissiondenied", "unauthorized")


# --------------------------------------------------------------------------
# Cloudflare: mint a temporary credential the way the grader will
# --------------------------------------------------------------------------


def mint(env: dict, *, prefixes: list[str], permission: str, ttl: int = 900) -> dict:
    url = f"https://api.cloudflare.com/client/v4/accounts/{env['CF_ACCOUNT_ID']}/r2/temp-access-credentials"
    body = {
        "bucket": env["R2_BUCKET"],
        "parentAccessKeyId": env["R2_PARENT_ACCESS_KEY_ID"],
        "permission": permission,
        "ttlSeconds": ttl,
        "prefixes": prefixes,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {env['CF_API_TOKEN']}", "Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"mint failed: HTTP {e.code}: {e.read().decode()[:500]}") from e
    if not payload.get("success"):
        raise RuntimeError(f"mint failed: {payload.get('errors')}")
    out = payload["result"]
    out["_latency_s"] = time.perf_counter() - t0
    return out


def store_for(env: dict, cred: dict | None = None, *, prefix: str | None = None):
    """An obstore S3Store on the bucket; parent credential when ``cred`` is None."""
    from obstore.store import S3Store

    if cred is None:
        kw = {
            "access_key_id": env["R2_PARENT_ACCESS_KEY_ID"],
            "secret_access_key": env["R2_PARENT_SECRET"],
        }
    else:
        kw = {
            "access_key_id": cred["accessKeyId"],
            "secret_access_key": cred["secretAccessKey"],
            "token": cred["sessionToken"],
        }
    return S3Store(
        env["R2_BUCKET"],
        prefix=prefix,
        endpoint=env["R2_ENDPOINT"],
        region="auto",
        virtual_hosted_style_request=False,
        **kw,
    )


# --------------------------------------------------------------------------
# Result bookkeeping
# --------------------------------------------------------------------------


@dataclass
class Row:
    name: str
    expect: str  # "ok" | "denied"
    outcome: str = ""  # "ok" | "denied" | "error" | "client"
    detail: str = ""
    seconds: float | None = None

    @property
    def passed(self) -> bool:
        return self.outcome == self.expect


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def attempt(self, name: str, expect: str, fn):
        row = Row(name, expect)
        t0 = time.perf_counter()
        try:
            result = fn()
            row.outcome = "ok"
            row.detail = "" if result is None else str(result)[:80]
        except Exception as e:  # noqa: BLE001 - classifying every failure is the point
            msg = f"{type(e).__name__}: {e}"
            low = msg.lower()
            if any(m in low for m in DENIED_MARKERS):
                row.outcome = "denied"
            elif ("invalid" in low or "could not parse" in low) and "path" in low:
                # obstore/object_store normalised or rejected the key client-side; the
                # server was never asked. Not a pass for a "denied" expectation.
                row.outcome = "client"
            else:
                row.outcome = "error"
            row.detail = msg[:140]
        row.seconds = time.perf_counter() - t0
        self.rows.append(row)
        return row

    def note(self, text: str) -> None:
        self.notes.append(text)

    def render(self) -> str:
        w = max(len(r.name) for r in self.rows) + 2
        lines = [f"{'check'.ljust(w)} expect   got      pass  detail"]
        for r in self.rows:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(f"{r.name.ljust(w)} {r.expect:<8} {r.outcome:<8} {mark}  {r.detail}")
        n_fail = sum(not r.passed for r in self.rows)
        lines.append("")
        lines.append(f"{len(self.rows) - n_fail}/{len(self.rows)} passed")
        if self.notes:
            lines.append("")
            lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines)


# --------------------------------------------------------------------------
# The experiment
# --------------------------------------------------------------------------


def _isolation(env: dict, rep: Report) -> None:
    import obstore as obs

    parent = store_for(env)
    course = f"{ROOT}/course/x/"
    a_pfx, b_pfx = f"{ROOT}/users/x/A/", f"{ROOT}/users/x/B/"

    # Seed with the parent key: one course file, one file per student.
    obs.put(parent, f"{course}a.txt", b"course data\n")
    obs.put(parent, f"{a_pfx}a.txt", b"A's private data\n")
    obs.put(parent, f"{b_pfx}b.txt", b"B's private data\n")

    # Mint exactly what the grader will mint for student A.
    a_ro = mint(env, prefixes=[course], permission="object-read-only")
    a_rw = mint(env, prefixes=[a_pfx], permission="object-read-write")
    rep.note(f"mint latency: ro {a_ro['_latency_s']:.2f}s, rw {a_rw['_latency_s']:.2f}s")
    ro, rw = store_for(env, a_ro), store_for(env, a_rw)

    # -- what A must be able to do ------------------------------------------
    rep.attempt("A ro: get course file", "ok", lambda: obs.get(ro, f"{course}a.txt").bytes())
    rep.attempt("A ro: list course/", "ok", lambda: len(obs.list(ro, course).collect()))
    rep.attempt("A rw: get own file", "ok", lambda: obs.get(rw, f"{a_pfx}a.txt").bytes())
    rep.attempt("A rw: put own file", "ok", lambda: obs.put(rw, f"{a_pfx}new.txt", b"hi\n"))
    rep.attempt("A rw: list own prefix", "ok", lambda: len(obs.list(rw, a_pfx).collect()))
    rep.attempt("A rw: delete own file", "ok", lambda: obs.delete(rw, f"{a_pfx}new.txt"))

    # -- what A must NOT be able to do --------------------------------------
    rep.attempt("A rw: get B's file", "denied", lambda: obs.get(rw, f"{b_pfx}b.txt").bytes())
    rep.attempt("A ro: get B's file", "denied", lambda: obs.get(ro, f"{b_pfx}b.txt").bytes())
    rep.attempt("A rw: get course file (not in rw scope)", "denied", lambda: obs.get(rw, f"{course}a.txt").bytes())
    rep.attempt("A rw: put into B's prefix", "denied", lambda: obs.put(rw, f"{b_pfx}stolen.txt", b"x"))
    rep.attempt("A ro: put into course/", "denied", lambda: obs.put(ro, f"{course}new.txt", b"x"))
    rep.attempt("A rw: delete B's file", "denied", lambda: obs.delete(rw, f"{b_pfx}b.txt"))

    def list_root():
        got = obs.list(rw, f"{ROOT}/").collect()
        outside = [o["path"] for o in got if not o["path"].startswith(a_pfx)]
        if outside:
            raise AssertionError(f"listing leaked {len(outside)} objects outside own prefix: {outside[:3]}")
        return f"{len(got)} entries, all inside own prefix"

    # R2 may answer a wider listing with 403 (denied) or with only in-scope keys (ok);
    # both are acceptable. Leaking a neighbour's key is the failure.
    r = rep.attempt("A rw: list above own prefix", "denied", list_root)
    if r.outcome == "ok":
        r.expect = "ok"

    r = rep.attempt("A rw: traversal key users/x/A/../B/b.txt", "denied",
                    lambda: obs.get(rw, f"{a_pfx}../B/b.txt").bytes())
    if r.outcome == "client":
        # obstore never sends a `..` key. Checked separately with boto3 (which sends keys
        # verbatim): R2 answers SignatureDoesNotMatch, and a literal %2E%2E key is a
        # distinct object (NoSuchKey) -- keys are opaque strings, never normalised.
        r.expect = "client"
        rep.note("traversal: refused client-side by obstore; server behaviour verified with boto3 (see docs §11.3)")
    rep.attempt("A rw: copy own -> B's prefix", "denied",
                lambda: obs.copy(rw, f"{a_pfx}a.txt", f"{b_pfx}stolen.txt"))
    rep.attempt("A rw: copy course -> own (no read on source)", "denied",
                lambda: obs.copy(rw, f"{course}a.txt", f"{a_pfx}copy.txt"))
    six_mb = os.urandom(6 * 1024 * 1024)
    rep.attempt("A rw: multipart put into B's prefix", "denied",
                lambda: obs.put(rw, f"{b_pfx}big.bin", six_mb, use_multipart=True, chunk_size=5 * 1024 * 1024))
    rep.attempt("A rw: multipart put into own prefix", "ok",
                lambda: obs.put(rw, f"{a_pfx}big.bin", six_mb, use_multipart=True, chunk_size=5 * 1024 * 1024))

    # -- B's credential must be just as blind to A ---------------------------
    b_rw = store_for(env, mint(env, prefixes=[b_pfx], permission="object-read-write"))
    rep.attempt("B rw: get A's file", "denied", lambda: obs.get(b_rw, f"{a_pfx}a.txt").bytes())
    rep.attempt("B rw: get own file", "ok", lambda: obs.get(b_rw, f"{b_pfx}b.txt").bytes())

    # -- expiry: does a short TTL actually cut access off? --------------------
    try:
        short = mint(env, prefixes=[a_pfx], permission="object-read-only", ttl=1)
        time.sleep(3)
        rep.attempt("A: expired credential (ttl=1s)", "denied",
                    lambda: obs.get(store_for(env, short), f"{a_pfx}a.txt").bytes())
    except RuntimeError as e:
        rep.note(f"ttl=1 mint refused ({str(e)[:100]}); minimum TTL is above 1s -- fine, note the floor")

    # -- the presign path the WASM runtime will use ---------------------------
    def presign_roundtrip():
        url = obs.sign(parent, "GET", f"{a_pfx}a.txt", timedelta(minutes=5))
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()

    rep.attempt("parent: presigned GET fetched with plain urllib", "ok", presign_roundtrip)


def _timings(env: dict, rep: Report, *, size_mb: int = 100) -> None:
    import obstore as obs

    parent = store_for(env)
    key = f"{ROOT}/bench/{size_mb}mb.bin"
    blob = os.urandom(size_mb * 1024 * 1024)

    t0 = time.perf_counter()
    obs.put(parent, key, blob)
    rep.note(f"R2 upload {size_mb} MB: {time.perf_counter() - t0:.1f}s")

    cred = store_for(env, mint(env, prefixes=[f"{ROOT}/bench/"], permission="object-read-only"))
    t0 = time.perf_counter()
    n = len(obs.get(cred, key).bytes())
    dt = time.perf_counter() - t0
    rep.note(f"R2 download {n / 1e6:.0f} MB with temp credential: {dt:.1f}s ({n / 1e6 / dt:.0f} MB/s)")

    t0 = time.perf_counter()
    obs.get_range(cred, key, start=50 * 1024 * 1024, length=1024 * 1024)
    rep.note(f"R2 1 MB range read from the middle: {time.perf_counter() - t0:.2f}s")

    try:
        from huggingface_hub import hf_hub_download

        t0 = time.perf_counter()
        p = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset", force_download=True)
        dt = time.perf_counter() - t0
        sz = os.path.getsize(p) / 1e6
        rep.note(f"HF download {sz:.0f} MB (same file the ICA chapter loads): {dt:.1f}s ({sz / dt:.0f} MB/s)")
    except ImportError:
        rep.note("huggingface_hub not installed; skipped the HF comparison")
    except Exception as e:  # noqa: BLE001
        rep.note(f"HF comparison failed: {type(e).__name__}: {str(e)[:100]}")


def _molab_checks(env: dict, rep: Report) -> None:
    rep.note(f"/dev/fuse present: {os.path.exists('/dev/fuse')}")
    marker = f"DARTBRAINS_SPIKE_MARK={int(time.time())}"
    existing = ""
    if os.path.exists(".env"):
        with open(".env", encoding="utf-8") as f:
            existing = f.read()
    if "DARTBRAINS_SPIKE_MARK=" in existing:
        last = existing.strip().splitlines()[-1]
        rep.note(f".env written by Python SURVIVED a restart: found {last!r}")
    else:
        with open(".env", "a", encoding="utf-8") as f:
            f.write(marker + "\n")
        rep.note(f"wrote {marker!r} to .env from Python. Let the notebook idle out (or restart it), "
                 "re-run with molab=True: the line survived => .env can hold the token")
    # A prefix-rooted store as a notebook-level variable: does marimo's Files panel pick it up?
    cred = mint(env, prefixes=[f"{ROOT}/users/x/A/"], permission="object-read-write")
    globals()["spike_private_store"] = store_for(env, cred, prefix=f"{ROOT}/users/x/A")
    rep.note("`spike_private_store` is now a global S3Store rooted at the student prefix -- "
             "open the Files panel and see whether it appears and lists only A's files")


def run(env: dict | None = None, *, molab: bool = False, keep: bool = False, bench_mb: int = 100) -> Report:
    env = dict(env or os.environ)
    missing = [k for k in ("CF_ACCOUNT_ID", "CF_API_TOKEN", "R2_ENDPOINT", "R2_BUCKET",
                           "R2_PARENT_ACCESS_KEY_ID", "R2_PARENT_SECRET") if not env.get(k)]
    if missing:
        raise SystemExit(f"missing: {', '.join(missing)}")

    rep = Report()
    try:
        _isolation(env, rep)
        if bench_mb:
            _timings(env, rep, size_mb=bench_mb)
        if molab:
            _molab_checks(env, rep)
    finally:
        if not keep:
            import obstore as obs

            parent = store_for(env)
            paths = [o["path"] for o in obs.list(parent, f"{ROOT}/").collect()]
            if paths:
                obs.delete(parent, paths)
            rep.note(f"cleaned up {len(paths)} objects under {ROOT}/")
    print(rep.render())
    return rep


if __name__ == "__main__":
    args = set(sys.argv[1:])
    rep = run(molab="--molab" in args, keep="--keep" in args, bench_mb=0 if "--no-bench" in args else 100)
    sys.exit(0 if all(r.passed for r in rep.rows) else 1)
