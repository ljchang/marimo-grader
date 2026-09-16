#!/usr/bin/env python
"""Pre-download every dataset file the published assignments need into HF_HOME.

Why this exists
---------------
Autograding runs the student's notebook under bubblewrap with ``--unshare-net``
(see ``deploy/README.md``), so a notebook that downloads data can only read what
is already in the worker's HuggingFace cache. ``docker-compose.prod.yml`` points
``HF_HOME`` at the persistent ``hf_cache`` volume, but nothing fills it. Cold, an
autograde run fails with ``LocalEntryNotFoundError`` and the submission is
reported as "notebook execution failed" -- a grader failure rather than a zero.

Run this after every deploy and after publishing an assignment that touches new
data::

    docker compose -f docker-compose.prod.yml run --rm worker \
        python deploy/warm_cache.py

Add ``--check`` to report what is missing and change nothing, which is what you
want in a smoke test.

Where the file list comes from
------------------------------
Two sources, in this order:

1. **The published notebook itself.** Every dataset path in the course funnels
   through ``dartbrains_tools.data.localizer``, so the notebook's own calls are
   the authoritative list. Deriving it here means the list cannot drift from the
   assignment the way a hand-maintained one does.
2. **The assignment's ``required_datasets`` setting**, for anything the scan
   cannot see -- a path built at run time, or a dataset reached through another
   library. Entries are ``"<repo_id> <filename>"`` pairs.

Warming happens inside each assignment's own prepared venv (the one
``prepare_env`` builds from its PEP 723 block), so the download goes through the
very ``localizer.get_file`` the notebook will call rather than a reimplementation
of its path rules here.

A ``get_file`` reference is warmed for **every** subject, because the subject
argument is normally a loop variable and cannot be read statically. An assignment
that only ever touches one subject therefore over-warms -- ten conditions pinned
to S01 fetch all twenty subjects, 382 MB rather than 19 MB. That is deliberate:
over-warming costs disk on a persistent volume, while under-warming fails the
autograde run, so the trade is not symmetric.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from grader.api.public import _student_bytes  # noqa: E402
from grader.db import get_sessionmaker  # noqa: E402
from grader.models import Assignment, Offering  # noqa: E402
from grader.worker.materialize import rewrite_dependencies  # noqa: E402
from grader.worker.sandbox import prepare_env  # noqa: E402

# Runs inside the assignment's own venv: resolves each reference with the real
# localizer, so this file never has to know how a beta filename is spelled.
_WARM = r"""
import json, os, sys

# --check answers "would autograding work right now?", so it has to look the way
# the sandbox does: offline, cache-only. Set before the first hub import, since
# huggingface_hub reads this at import time.
if sys.argv[2] == "check":
    os.environ["HF_HUB_OFFLINE"] = "1"

from dartbrains_tools.data import localizer

refs = json.loads(sys.argv[1])
ok, missing = 0, []
for ref in refs:
    try:
        if ref["kind"] == "get_file":
            for subject in localizer.get_subjects():
                localizer.get_file(subject, ref["scope"], ref["suffix"])
                ok += 1
        else:
            localizer.download(ref["repo_id"], ref["filename"])
            ok += 1
    except Exception as exc:
        missing.append(f'{ref} -> {type(exc).__name__}')
print(json.dumps({"ok": ok, "missing": missing}))
"""


# localizer helpers that call get_file inside dartbrains_tools, so the scope and
# suffix never appear in the notebook. Keep in step with dartbrains_tools.data.localizer.
_HELPER_SCOPES = {
    "load_confounds": ("derivatives", "confounds"),
    "load_events": ("raw", "events"),
}


def references(source: str) -> list[dict]:
    """Dataset references a notebook makes, derived from its own source.

    Recognises four shapes:

    * ``localizer.get_file(subject, "<scope>", "<suffix>")`` with literal scope
      and suffix -- warmed for every subject, since assignments loop over them.
    * ``localizer.download("<repo_id>", "<filename>")``.
    * the ``localizer`` helpers that wrap ``get_file`` inside dartbrains_tools
      rather than in the notebook (``load_confounds``, ``load_events``). These are
      invisible to a scan of the notebook alone: a notebook calling
      ``load_confounds(sub)`` names no scope or suffix anywhere, so without this
      the confounds TSV never gets warmed and the run fails at grade time.
    * any bare string literal that names a condition, which covers the common
      ``load_condition("video_sentence")`` style indirection where the condition
      reaches ``get_file`` through a local helper rather than directly.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    refs: list[dict] = []
    seen: set[tuple] = set()

    def add(ref: dict) -> None:
        key = tuple(sorted(ref.items()))
        if key not in seen:
            seen.add(key)
            refs.append(ref)

    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
        if node.func.attr in _HELPER_SCOPES:
            scope, suffix = _HELPER_SCOPES[node.func.attr]
            add({"kind": "get_file", "scope": scope, "suffix": suffix})
        elif node.func.attr == "get_file" and len(args) >= 3:
            if isinstance(args[1], str) and isinstance(args[2], str):
                add({"kind": "get_file", "scope": args[1], "suffix": args[2]})
        elif node.func.attr == "download" and len(args) >= 2:
            if isinstance(args[0], str) and isinstance(args[1], str):
                add({"kind": "download", "repo_id": args[0], "filename": args[1]})

    # Condition names used via a helper. CONDITIONS is imported lazily so this
    # script stays importable on a machine without dartbrains_tools installed.
    try:
        from dartbrains_tools.data.localizer import CONDITIONS
    except Exception:
        CONDITIONS = [
            "audio_computation",
            "audio_left_hand",
            "audio_right_hand",
            "audio_sentence",
            "horizontal_checkerboard",
            "vertical_checkerboard",
            "video_computation",
            "video_left_hand",
            "video_right_hand",
            "video_sentence",
        ]
    for name in sorted(literals & set(CONDITIONS)):
        add({"kind": "get_file", "scope": "betas", "suffix": name})
    return refs


def declared(assignment: Assignment) -> list[dict]:
    """``required_datasets`` entries, as ``"<repo_id> <filename>"`` pairs."""
    out = []
    for entry in (assignment.settings or {}).get("required_datasets") or []:
        parts = str(entry).split()
        if len(parts) == 2:
            out.append({"kind": "download", "repo_id": parts[0], "filename": parts[1]})
        else:
            print(f"    ignoring malformed required_datasets entry: {entry!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report gaps without downloading")
    ap.add_argument("--slug", help="warm only this assignment")
    args = ap.parse_args()

    failures = 0
    with get_sessionmaker()() as db:
        for offering in db.query(Offering).all():
            for assignment in db.query(Assignment).filter_by(offering_id=offering.id).all():
                if args.slug and assignment.slug != args.slug:
                    continue
                if not assignment.versions:
                    continue
                version = assignment.versions[-1]
                source = _student_bytes(db, version).decode("utf-8", "replace")

                refs = references(source) + declared(assignment)
                if not refs:
                    continue
                print(f"{assignment.slug} (v{version.version}): {len(refs)} dataset references")

                venv = prepare_env(rewrite_dependencies(source))
                if venv is None:
                    print("    no PEP 723 block; skipping")
                    continue
                python = venv / "bin" / "python"
                proc = subprocess.run(
                    [str(python), "-c", _WARM, json.dumps(refs), "check" if args.check else "warm"],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    print(f"    FAILED: {proc.stderr.strip()[-800:]}")
                    failures += 1
                    continue
                result = json.loads(proc.stdout.strip().splitlines()[-1])
                print(f"    {result['ok']} files present")
                for miss in result["missing"]:
                    print(f"    MISSING {miss}")
                    failures += 1

    if failures:
        print(f"\n{failures} problem(s); autograding will fail for these until they are fixed.")
    else:
        print("\nCache warm: every published assignment can read its data offline.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
