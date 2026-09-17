# Command line

`grader publish` is for instructors; everything else is for operators. The command is installed with the backend package. On a server, run it inside the web container:

```bash
docker compose -f docker-compose.prod.yml run --rm web grader <command> …
```

`grader --help` and `grader <command> --help` are authoritative.

## `grader publish`

Publish an instructor notebook as a new assignment version and download the finalized student notebook.

```
grader publish NOTEBOOK --server URL --offering COURSE/TERM --slug SLUG
                [--title TITLE] [--student STUDENT_NOTEBOOK]
                [--manual QID ...] [--hybrid QID=AUTO_POINTS ...]
                [--token TOKEN] [--out FILE]
```

| Flag | Meaning |
|---|---|
| `--server` | the grader's base URL |
| `--offering` | `course/term` alias, or an offering id |
| `--slug` | assignment name within the offering; reuse it to publish a new version |
| `--title` | display title; defaults to the slug on first publish |
| `--student` | use a student notebook you generated yourself instead of stripping the instructor copy |
| `--manual` | grade this question by hand even though it has a check |
| `--hybrid` | this question is autograded for `AUTO_POINTS` and hand-graded for the rest |
| `--token` | a token from `grader token`; without it the command signs you in through the browser |
| `--out` | where to write the student notebook; default `<name>_student.py` beside the source |

Exit status is non-zero if markers are invalid, solutions would leak, or the server refuses. See [Publish](../instructors/publish.md) for what it does step by step.

## `grader warm-cache`

Pre-download the datasets published assignments need. The grading sandbox has no network, so it can only read what is already cached.

```
grader warm-cache [--check] [--slug SLUG]
```

| Flag | Meaning |
|---|---|
| `--check` | report what is missing without downloading anything; exits non-zero if anything is absent, so it works as a smoke test |
| `--slug` | limit either mode to one assignment |

Run it after every deploy and after publishing an assignment that touches new data. Run it in the **worker** container, which is where the cache lives. [Sandbox and data](../operators/sandbox-and-data.md#the-dataset-cache) explains where the file list comes from.

## `grader seed`

Create a course, an offering, an instructor — also made a platform admin — and optional students. Idempotent.

Every flag has a default, including `--students`, which defaults to two example NetIDs. On a real server pass `--students` with nothing after it, or you will create them.

```
grader seed [--course SLUG] [--title TITLE] [--term TERM]
            [--instructor NETID] [--students NETID ...]
```

## `grader token`

Mint a notebook/CLI token for a NetID directly from the server's signing key. Creates the user if needed; with `--offering` also creates or updates their enrollment.

```
grader token NETID [--offering COURSE/TERM] [--role student|ta|instructor]
                   [--admin] [--display-name NAME]
```

Prints the token on stdout, valid eight hours, in every auth mode. This is how an instructor publishes before single sign-on is available, and how CI publishes at any time.

## `grader login-link`

Print a one-time browser sign-in URL for an existing user, valid thirty minutes, single use.

```
grader login-link NETID
```

Works in every auth mode. Because it can only be run by someone with shell access on the host, it is the break-glass path when SSO is unavailable — see [Sessions and tokens](../auth/sessions-and-tokens.md#operator-sign-in).

## Services

| Command | Runs |
|---|---|
| `grader-api` | the web API under uvicorn |
| `grader-worker` | the grading loop; `--once` processes one job and exits, which is useful in tests |

Both read the same environment; see [Configuration](configuration.md).
