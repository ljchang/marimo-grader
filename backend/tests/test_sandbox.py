import sys

import pytest

from grader.worker.sandbox import env_key, run_with_timeout

NB = '# /// script\n# requires-python = ">=3.11"\n# dependencies = ["marimo", "numpy>=2"]\n# ///\nimport marimo\n'


def test_env_key_depends_only_on_dependencies():
    a = env_key(NB)
    assert a == env_key(NB + "\n# a comment that changes the notebook but not its deps\n")
    assert a == env_key(
        NB.replace('"marimo", "numpy>=2"', '"numpy>=2", "marimo"')
    )  # order-insensitive
    assert a != env_key(NB.replace("numpy>=2", "numpy>=1"))
    assert a != env_key(NB.replace(">=3.11", ">=3.12"))


def test_run_with_timeout_kills_process_group():
    # A child that spawns a grandchild holding stdout open; a plain subprocess.run would hang.
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)"
    with pytest.raises(RuntimeError, match="timed out"):
        run_with_timeout([sys.executable, "-c", code], timeout=2)


def test_run_with_timeout_returns_output():
    proc = run_with_timeout([sys.executable, "-c", "print('hi')"], timeout=10)
    assert proc.returncode == 0 and proc.stdout.strip() == "hi"
