# Command line

For instructors (`publish`) and operators (everything else). The `grader` command is installed with the backend package; on a server, run it inside the web container: `docker compose -f docker-compose.prod.yml run --rm web grader ...`.

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
| `--offering` | `course/term` alias (or an offering id) |
| `--slug` | assignment name within the offering; reuse it to publish a new version |
| `--title` | display title; defaults to the slug on first publish |
| `--student` | use a student notebook you generated yourself instead of stripping with MoGrader |
| `--manual` | grade this question by hand even though it has a check |
| `--hybrid` | this question is autograded for `AUTO_POINTS` and hand-graded for the rest |
| `--token` | a token from `grader token`; without it the command signs you in through the browser |
| `--out` | where to write the student notebook; default `<name>_student.py` beside the source |

Exit status is non-zero if markers are invalid, solutions would leak, or the server refuses.

## `grader seed`

Create a course, an offering, an instructor (also made platform admin), and optional students in an empty database. Idempotent.

```
grader seed [--course SLUG] [--title TITLE] [--term TERM] [--instructor NETID] [--students NETID ...]
```

## `grader token`

Mint a notebook/CLI token for a NetID directly from the server's signing key. Creates the user if needed; with `--offering` also creates or updates their enrollment.

```
grader token NETID [--offering COURSE/TERM] [--role student|ta|instructor] [--admin] [--display-name NAME]
```

Prints the token on stdout. Valid eight hours. Works in every auth mode.

## `grader login-link`

Print a one-time browser sign-in URL for an existing user, valid thirty minutes.

```
grader login-link NETID
```

## Services

`grader-api` runs the web API with uvicorn; `grader-worker` runs the grading loop (`--once` processes one job and exits, useful for tests). Both read the same environment; see [Configuration](configuration.md).
