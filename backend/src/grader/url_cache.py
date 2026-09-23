"""Offline copies of the plain-URL data files notebooks read.

Autograding runs under bubblewrap with ``--unshare-net``. The Hugging Face cache
covers every dataset reached through ``dartbrains_tools``, but a notebook can also
read a small file straight from the web -- ``pd.read_csv("https://raw.github...
/salary.csv")`` -- and nothing warms that. Inside the sandbox the request fails,
the cells that depend on the data never run, and before this module every such
submission scored 0 (the pandas and polars assignments, September 2026).

``grader warm-cache`` downloads every data-file URL literal found in an
instructor notebook into ``URL_CACHE_DIR`` while it still has network. At grade
time :func:`rewrite_urls` replaces each URL that has a cached copy with the copy's
path, which the sandbox can read (it binds ``/`` read-only). That covers students'
own copies of the loading line too, as long as they typed the same URL.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import tempfile
import urllib.request
from pathlib import Path

URL_CACHE_DIR = Path(os.environ.get("GRADER_URL_CACHE_DIR", "/data/hf-cache/url-cache"))

# Data files only: a URL literal that is a link in prose or a docs page is not
# something a cell reads.
_DATA_URL = re.compile(
    r"^https?://[^\s'\"]+\.(?:csv|tsv|txt|json|parquet|feather|xlsx?)(?:\?[^\s'\"]*)?$",
    re.IGNORECASE,
)


def data_urls(source: str) -> list[str]:
    """Data-file URL string literals in ``source``, in first-seen order."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    seen: dict[str, None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if _DATA_URL.match(value):
                seen.setdefault(value, None)
    return list(seen)


def cached_path(url: str) -> Path:
    """Where ``url``'s copy lives: content-free name, the URL's extension kept."""
    suffix = Path(url.split("?", 1)[0]).suffix
    return URL_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:32] + suffix)


def warm_urls(urls: list[str], *, check: bool = False) -> tuple[int, list[str]]:
    """Download each URL that is not cached yet. Returns ``(present, missing)``."""
    present, missing = 0, []
    for url in urls:
        dest = cached_path(url)
        if dest.is_file():
            present += 1
            continue
        if check:
            missing.append(url)
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - instructor URLs
                data = resp.read()
            fd, tmp = tempfile.mkstemp(dir=dest.parent)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            present += 1
        except Exception as e:  # noqa: BLE001 - report and keep going
            missing.append(f"{url} ({e})")
    return present, missing


def rewrite_urls(source: str) -> str:
    """Point every data URL that has a cached copy at that copy instead."""
    for url in data_urls(source):
        path = cached_path(url)
        if path.is_file():
            source = source.replace(url, str(path))
    return source
