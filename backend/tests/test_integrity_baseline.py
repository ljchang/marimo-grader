"""Which notebook a submission is diffed against.

check_integrity() serves two purposes in the worker, and they need different
baselines:

* against the INSTRUCTOR copy, to swap in check cells carrying the hidden tests
  -- that swap is how hidden tests reach the graded notebook
* against the RELEASED copy, to decide whether the student edited anything

Using the instructor copy for both reports every question as tampered on every
submission, because the released copy has the hidden tests stripped out of those
very cells and so can never match. These tests pin that distinction.
"""

from __future__ import annotations

import pytest

integrity = pytest.importorskip("mograder.grading.integrity")

HEAD = """import marimo

app = marimo.App()


@app.cell
def _():
    from marimo_grader_client import Grader

    g = Grader()
    return (g,)


@app.cell
def _(g):
    g.check(
        "q01: adds up",
        [
            (total == 3, "total should be 3", 1),
"""

TAIL = """        ],
    )
    return


if __name__ == "__main__":
    app.run()
"""

HIDDEN = """            ### BEGIN HIDDEN TESTS
            (total_is_int, "total should be an int", 1),
            ### END HIDDEN TESTS
"""
STRIPPED = "            # HIDDEN TESTS\n"

INSTRUCTOR = HEAD + HIDDEN + TAIL
RELEASE = HEAD + STRIPPED + TAIL
# What a student sends back having touched only their answer cell.
UNTOUCHED_SUBMISSION = RELEASE
# What an actual edit looks like: the threshold moved.
EDITED_SUBMISSION = RELEASE.replace("total == 3", "total == 0")


def test_instructor_baseline_always_reports_tampering():
    """The false positive we shipped: nobody edited anything here."""
    r = integrity.check_integrity(INSTRUCTOR, UNTOUCHED_SUBMISSION)
    assert "q01" in r.tampered_checks


def test_release_baseline_reports_nothing_for_an_untouched_submission():
    r = integrity.check_integrity(RELEASE, UNTOUCHED_SUBMISSION)
    assert r.tampered_checks == []
    assert r.tampered_marks is False


def test_release_baseline_still_catches_a_real_edit():
    """The detection has to keep working -- this is the point of it."""
    r = integrity.check_integrity(RELEASE, EDITED_SUBMISSION)
    assert "q01" in r.tampered_checks


def test_instructor_baseline_is_what_carries_the_hidden_tests():
    """Why the instructor comparison cannot simply be dropped."""
    r = integrity.check_integrity(INSTRUCTOR, UNTOUCHED_SUBMISSION)
    assert "total_is_int" in r.fixed_source
    assert "total_is_int" not in UNTOUCHED_SUBMISSION
