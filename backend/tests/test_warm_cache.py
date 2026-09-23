"""The dataset-reference scan that decides what gets pre-downloaded.

Autograding runs with no network, so anything this scan misses is a file the worker
cannot fetch at grade time. Every miss found so far has been a layer of indirection:
a condition reaching get_file through a local helper, a localizer helper that calls
get_file inside dartbrains_tools, or a notebook iterating CONDITIONS without naming one.
"""

from __future__ import annotations

from grader.warm_cache import references

HEADER = "import marimo\napp = marimo.App()\n"


def _suffixes(src: str) -> set[str]:
    return {r["suffix"] for r in references(src) if r["kind"] == "get_file"}


def test_literal_get_file_arguments():
    refs = references(HEADER + 'localizer.get_file(sub, "derivatives", "bold")\n')
    assert {"kind": "get_file", "scope": "derivatives", "suffix": "bold"} in refs


def test_download_with_literal_filename():
    refs = references(HEADER + 'localizer.download("dartbrains/localizer", "participants.tsv")\n')
    assert {
        "kind": "download",
        "repo_id": "dartbrains/localizer",
        "filename": "participants.tsv",
    } in refs


def test_condition_named_only_through_a_helper():
    """get_file's suffix is a variable here, so only the bare literal reveals it."""
    src = (
        HEADER
        + 'def load(c):\n    return localizer.get_file(s, "betas", c)\nload("video_sentence")\n'
    )
    assert "video_sentence" in _suffixes(src)


def test_localizer_helpers_that_wrap_get_file():
    """load_confounds names no scope or suffix anywhere in the notebook."""
    assert "confounds" in _suffixes(HEADER + "localizer.load_confounds(sub)\n")
    assert "events" in _suffixes(HEADER + "localizer.load_events(sub)\n")


def test_iterating_conditions_means_all_of_them():
    """A notebook looping over localizer.CONDITIONS names no condition at all."""
    src = HEADER + "for c in localizer.CONDITIONS:\n    load_condition(c)\n"
    assert len(_suffixes(src)) == 10


def test_notebook_without_data_needs_nothing():
    assert references(HEADER + "import numpy as np\nnp.zeros(10)\n") == []


def test_unparseable_source_does_not_raise():
    assert references("this is not python (((") == []


def test_solution_only_access_is_why_the_instructor_copy_is_scanned():
    """Publishing strips solutions, so a student copy hides the data access in them.

    warm() reads the instructor notebook for exactly this reason. This pins the
    difference the two copies produce, so the reason cannot be quietly lost.
    """
    instructor = HEADER + (
        "def _(localizer):\n"
        "    ### BEGIN SOLUTION\n"
        "    localizer.load_confounds(sub)\n"
        "    ### END SOLUTION\n"
    )
    published = HEADER + "def _(localizer):\n    # YOUR CODE HERE\n    pass\n"
    assert "confounds" in _suffixes(instructor)
    assert references(published) == []


def _downloads(src: str) -> set[tuple[str, str]]:
    return {(r["repo_id"], r["filename"]) for r in references(src) if r["kind"] == "download"}


def test_salary_tables_through_dartbrains_tools():
    """The pandas/polars/plotting CSVs, since dartbrains-tools 0.3.1."""
    src = (
        HEADER
        + "from dartbrains_tools.data import salary\n"
        + 'df = pd.read_csv(salary.get_file("salary_exercise.csv"))\n'
        + "raw = pl.read_csv(salary.get_file())\n"
    )
    assert _downloads(src) == {
        ("dartbrains/salary", "salary_exercise.csv"),
        ("dartbrains/salary", "salary.csv"),
    }


def test_salary_name_that_is_not_a_literal_warms_both_tables():
    src = HEADER + "which = pick()\npath = salary.get_file(which)\n"
    assert _downloads(src) == {
        ("dartbrains/salary", "salary.csv"),
        ("dartbrains/salary", "salary_exercise.csv"),
    }
    assert _downloads(HEADER + 'p = salary.get_file(name="salary.csv")\n') == {
        ("dartbrains/salary", "salary.csv")
    }


def test_salary_module_imported_under_another_name():
    """The assignments import it as salary_data: `salary` is their dataframe."""
    src = (
        HEADER
        + "from dartbrains_tools.data import salary as salary_data\n"
        + 'CSV_PATH = salary_data.get_file("salary_exercise.csv")\n'
        + "salary = pd.read_csv(CSV_PATH)\n"
    )
    assert _downloads(src) == {("dartbrains/salary", "salary_exercise.csv")}
    src2 = HEADER + "import dartbrains_tools.data.salary as sal\np = sal.get_file()\n"
    assert _downloads(src2) == {("dartbrains/salary", "salary.csv")}
