# Sandbox and data

Two things that are invisible when they work and confusing when they do not: the isolation student code runs inside, and the data it is allowed to read.

## The worker sandbox

Student code runs only in the grading worker — never in the API, never in a grader's browser — and inside [bubblewrap](https://github.com/containers/bubblewrap), with:

- the filesystem **read-only**, apart from one bound working directory;
- a private `/tmp`;
- **no network** (`--unshare-net`);
- an address-space cap (`GRADER_RLIMIT_AS`, 4 GiB by default — scientific Python reserves a lot of virtual memory at import, so the engine's own 1 GiB default is too small for neuroimaging work);
- a wall-clock timeout (`GRADER_AUTOGRADE_TIMEOUT`, 300 seconds).

Packages are installed **before** the sandbox is entered, because installing needs network and a writable disk. One environment is built per distinct dependency list and reused by every submission of that assignment, which is why the first submission after a publish takes about a minute longer than the rest.

### Docker gets in the way, once

Docker's defaults block the unprivileged user namespaces and the fresh `/proc` mount bubblewrap needs. The worker service therefore runs with three relaxed settings:

```yaml
security_opt: ["seccomp:unconfined", "apparmor:unconfined", "systempaths=unconfined"]
```

That reads alarming and is the opposite: it is what allows the *inner* sandbox to exist. Without it bubblewrap cannot start, and student code would otherwise run with only the container's isolation. Verify after every first deploy on a new host:

```bash
docker compose -f docker-compose.prod.yml exec worker \
  bwrap --ro-bind / / --unshare-all --dev /dev --proc /proc -- /bin/true && echo sandbox ok
```

If that prints *bwrap: No permissions to create new namespace*, the `security_opt` line is missing or commented out, or the host has not enabled unprivileged user namespaces — `deploy/bootstrap.sh` does the latter.

Set `GRADER_USE_BUBBLEWRAP=1` to require it. Without bubblewrap the notebook still runs with resource limits and a timeout, but it has network, which is not a configuration to run a term on.

## The dataset cache

Because autograding has no network, an assignment that downloads data can only read what is **already** in the worker's cache. `HF_HOME` points at a persistent volume, and one command fills it:

```bash
docker compose -f docker-compose.prod.yml run --rm worker grader warm-cache
docker compose -f docker-compose.prod.yml run --rm worker grader warm-cache --check
```

Run it **after every deploy, and after publishing an assignment that touches new data.** `--slug <name>` limits either mode to one assignment.

`--check` downloads nothing. It reports what is missing, running cache-only exactly as the sandbox does, and exits non-zero when anything is absent — so it works as a smoke test in a deploy script.

### Where the file list comes from

From each published notebook's own `localizer.get_file` and `localizer.download` calls, so it cannot drift from the assignment. Warming happens inside that assignment's own prepared environment, through the same code path the notebook will use, rather than a reimplementation of its path rules.

Anything built at run time — a filename assembled from a loop variable, say — is invisible to that scan. List those in the assignment's `required_datasets` setting as `"<repo_id> <filename>"` entries, which the warm step also reads.

/// admonition | Skipping this is not a quiet failure
    type: warning

A cold cache makes the autograde run raise `LocalEntryNotFoundError`, reported as *notebook execution failed*. That is a **grader failure to investigate**, not a zero for the student — which is the right outcome, but it means a deadline's worth of submissions sitting in a failed state until someone notices.

There is a second-order version of the same problem: rendering runs *outside* the sandbox and therefore has network, so a render can quietly warm the cache and make the next attempt succeed. The failure then cannot be reproduced. The worker runs render before autograde partly to make that recovery deterministic — but warming at deploy time is the actual fix.
///

### Sizes

Small enough not to worry about, with one exception. A per-condition beta image is about 2 MB, so a 20-subject four-condition assignment is roughly 150 MB. Raw preprocessed BOLD is about 57 MB **per subject**, so an assignment that loops over subjects on raw data deserves a second look before it is published — for the grading time as much as the disk.

## Timeouts, and what to do about them

An assignment that takes four minutes to grade is an assignment whose deadline hour will not be fun. The sandbox's five-minute cap is per submission, and submissions queue.

If a notebook is genuinely slow, the fix is usually in the assignment rather than in `GRADER_AUTOGRADE_TIMEOUT`: precompute what the student does not need to compute, subsample, or cache the expensive step in the published notebook. [Author an assignment](../instructors/author-an-assignment.md) has more.
