"""Offline copies of plain-URL data files, and failing runs where nothing could run.

The pandas and polars assignments read a CSV straight from GitHub. Autograding has
no network, so every submission scored 0 with no checks run and empty feedback.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from grader import url_cache
from grader.worker.mograder_runner import nothing_ran_reason

SALARY = "https://raw.githubusercontent.com/ljchang/dartbrains/master/data/salary/salary.csv"
NB = f"""import marimo
app = marimo.App()

@app.cell
def _(pd):
    df = pd.read_csv("{SALARY}")
    # see https://pandas.pydata.org/docs/ and https://github.com/ljchang/dartbrains
    return (df,)
"""


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(url_cache, "URL_CACHE_DIR", tmp_path / "url-cache")
    return tmp_path / "url-cache"


def test_finds_data_file_urls_not_links_in_comments_or_docs():
    assert url_cache.data_urls(NB) == [SALARY]
    other = 'x = "https://example.org/page.html"\ny = "https://example.org/d.tsv?raw=1"\n'
    assert url_cache.data_urls(other) == ["https://example.org/d.tsv?raw=1"]
    assert url_cache.data_urls("def broken(:\n") == []


def test_warm_then_rewrite_points_the_notebook_at_the_copy(cache_dir, monkeypatch):
    fetched = []

    def fake_urlopen(url, timeout=None):
        fetched.append(url)
        return io.BytesIO(b"salary,gender\n1,0\n")

    monkeypatch.setattr(url_cache.urllib.request, "urlopen", fake_urlopen)

    # Nothing cached: --check reports it, rewrite leaves the notebook alone.
    assert url_cache.warm_urls([SALARY], check=True) == (0, [SALARY])
    assert url_cache.rewrite_urls(NB) == NB

    assert url_cache.warm_urls([SALARY]) == (1, [])
    assert url_cache.warm_urls([SALARY]) == (1, [])  # second time is a no-op
    assert fetched == [SALARY]

    path = url_cache.cached_path(SALARY)
    assert path.read_bytes().startswith(b"salary,gender")
    assert path.suffix == ".csv" and path.parent == cache_dir
    rewritten = url_cache.rewrite_urls(NB)
    assert SALARY not in rewritten and f'pd.read_csv("{path}")' in rewritten


def test_a_failed_download_is_reported_not_raised(cache_dir, monkeypatch):
    def boom(url, timeout=None):
        raise OSError("unreachable")

    monkeypatch.setattr(url_cache.urllib.request, "urlopen", boom)
    present, missing = url_cache.warm_urls([SALARY])
    assert present == 0 and "unreachable" in missing[0]


def _result(checks, export_error="", cell_errors=0):
    return SimpleNamespace(checks=checks, export_error=export_error, cell_errors=cell_errors)


def test_a_notebook_where_no_check_ran_fails_instead_of_scoring_zero():
    why = nothing_ran_reason(_result([], "some cells failed to execute", 7), 5.0)
    assert why and "no check cell ran" in why and "some cells failed to execute" in why


def test_one_broken_answer_still_scores():
    # Another question's check ran: this student's own code failed, and 0 is right.
    assert nothing_ran_reason(_result([object()], "some cells failed to execute", 1), 5.0) is None


def test_an_unanswered_notebook_scores_zero_rather_than_failing():
    # Every check cell guards with mo.stop(answer is ..., ...). Left unanswered,
    # nothing fails and nothing is checked: that is a 0, not a grader problem.
    assert nothing_ran_reason(_result([], "", 0), 5.0) is None


def test_a_hand_graded_question_is_left_alone():
    assert nothing_ran_reason(_result([]), 0.0) is None
