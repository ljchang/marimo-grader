"""A Mount: one logical root (``/private``, ``/course``, …) with the operations
notebooks use. Backend-independent; everything goes through an :class:`ObjectFS`.

``put``/``get`` pick a serialisation from the file extension so the common
cases read naturally::

    private.put("week3/betas.pkl", betas)         # pickle
    private.put("week3/betas.npy", array)         # numpy
    private.put("week3/table.csv", df)            # pandas, polars, DesignMatrix, array
    private.put("week3/notes.json", {"k": 1})     # json
    private.put("week3/mask.nii.gz", brain)       # nibabel image or nltools BrainData
    private.put("week3/map.png", fig)             # a figure: .png .jpg .svg .pdf
    private.put("week3/raw.bin", b"...")          # bytes as-is
    private.put("week3/report.txt", "text")       # str as utf-8

``local_path`` is what nibabel/nilearn/nltools want: an ordinary path,
materialised on first use and reused while the object is unchanged.
"""

from __future__ import annotations

import fnmatch
import gzip
import io
import json
import os
import pickle
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ._fs import Entry, NotFound, ObjectFS


class ReadOnly(PermissionError):
    pass


@dataclass
class Mount:
    logical: str
    prefix: str
    mode: str
    fs: ObjectFS
    cache_root: Path

    # -- introspection -----------------------------------------------------

    @property
    def writable(self) -> bool:
        return self.mode == "rw"

    @property
    def store(self):
        """The backend's native store object (an ``obstore.store.S3Store`` for
        R2), for marimo's Files panel or direct ``obstore`` use."""
        return self.fs.native

    def __repr__(self) -> str:
        return f"<Mount {self.logical} ({self.mode}) -> {self.prefix}>"

    # -- paths -------------------------------------------------------------

    @staticmethod
    def _key(rel: str) -> str:
        rel = rel.strip("/")
        parts = rel.split("/")
        if not rel or any(p in ("", ".", "..") for p in parts):
            raise ValueError(f"bad path: {rel!r}")
        return rel

    def _check_write(self) -> None:
        if not self.writable:
            raise ReadOnly(f"{self.logical} is read-only")

    # -- listing -----------------------------------------------------------

    def ls(self, rel: str = "") -> list[str]:
        prefix = self._key(rel) + "/" if rel.strip("/") else ""
        return [e.key for e in self.fs.list(prefix)]

    def glob(self, pattern: str) -> list[str]:
        return [k for k in self.ls() if fnmatch.fnmatch(k, pattern.strip("/"))]

    def exists(self, rel: str) -> bool:
        return self.fs.head(self._key(rel)) is not None

    def info(self, rel: str) -> Entry | None:
        return self.fs.head(self._key(rel))

    def usage(self) -> int:
        """Bytes stored under this mount."""
        return sum(e.size for e in self.fs.list(""))

    # -- raw bytes ---------------------------------------------------------

    def get_bytes(self, rel: str) -> bytes:
        return self.fs.get_bytes(self._key(rel))

    def put_bytes(self, rel: str, data: bytes) -> None:
        self._check_write()
        self.fs.put_bytes(self._key(rel), bytes(data))

    def delete(self, rel: str) -> None:
        self._check_write()
        self.fs.delete(self._key(rel))

    @contextmanager
    def open(self, rel: str, mode: str = "r"):
        """``open()``-like access: text unless ``b`` is in ``mode``. Reads hold the
        whole object in memory; writes upload when the block ends."""
        text = "b" not in mode
        if "w" in mode or "a" in mode:
            self._check_write()
            buf = io.StringIO() if text else io.BytesIO()
            if "a" in mode and self.exists(rel):
                existing = self.get_bytes(rel)
                buf.write(existing.decode() if text else existing)
            yield buf
            data = buf.getvalue()
            self.put_bytes(rel, data.encode() if text else data)
        else:
            data = self.get_bytes(rel)
            yield io.StringIO(data.decode()) if text else io.BytesIO(data)

    # -- files -------------------------------------------------------------

    def local_path(self, rel: str, *, refresh: bool = False) -> str:
        """Materialise ``rel`` locally and return its path. Reused while the
        remote object's size/etag are unchanged."""
        key = self._key(rel)
        if hasattr(self.fs, "root"):  # LocalFS: the file is already a file
            p = Path(self.fs.root) / key
            if not p.is_file():
                raise NotFound(key)
            return str(p)
        dest = self.cache_root / self.prefix.strip("/") / key
        meta = dest.with_name(dest.name + ".meta.json")
        remote = self.fs.head(key)
        if remote is None:
            raise NotFound(key)
        if not refresh and dest.is_file() and meta.is_file():
            try:
                m = json.loads(meta.read_text())
                if m.get("size") == remote.size and m.get("etag") == remote.etag:
                    os.utime(dest)  # LRU touch
                    return str(dest)
            except (OSError, ValueError):
                pass
        self.fs.download(key, dest)
        meta.write_text(json.dumps({"size": remote.size, "etag": remote.etag}))
        return str(dest)

    def download(self, rel: str, dest: str | os.PathLike) -> Path:
        dest = Path(dest)
        self.fs.download(self._key(rel), dest)
        return dest

    def upload(self, src: str | os.PathLike, rel: str) -> None:
        self._check_write()
        self.fs.upload(Path(src), self._key(rel))

    def sync(self, src: str | os.PathLike, rel: str = "") -> list[str]:
        """Upload every file under a local directory (rsync-like, add/update only)."""
        self._check_write()
        src = Path(src)
        base = self._key(rel) + "/" if rel.strip("/") else ""
        have = {e.key: e for e in self.fs.list(base)}
        sent = []
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            key = base + p.relative_to(src).as_posix()
            e = have.get(key)
            if e is not None and e.size == p.stat().st_size:
                continue
            self.fs.upload(p, key)
            sent.append(key)
        return sent

    def copy_from(self, other: Mount, rel: str, dest_rel: str | None = None) -> None:
        """Bring an object over from another mount (e.g. ``/course`` → ``/private``).

        Goes through this kernel, not server-side: no single credential can
        read the source *and* write here, so a bucket copy is refused by R2.
        """
        self._check_write()
        self.put_bytes(dest_rel or rel, other.get_bytes(rel))

    # -- typed objects -----------------------------------------------------

    def put(self, rel: str, obj) -> None:
        self._check_write()
        self.put_bytes(rel, _encode(rel, obj))

    def get(self, rel: str):
        ext = _ext(rel)
        if ext in (".nii", ".nii.gz"):
            import nibabel as nib

            return nib.load(self.local_path(rel))
        return _decode(rel, self.get_bytes(rel))


# --------------------------------------------------------------------------
# Serialisation by extension
# --------------------------------------------------------------------------


def _ext(name: str) -> str:
    low = name.lower()
    if low.endswith(".nii.gz"):
        return ".nii.gz"
    return os.path.splitext(low)[1]


# Formats a str can't be the contents of: a str here is a file name passed by
# mistake, which would otherwise be stored as the file.
_BINARY = (
    ".pkl",
    ".pickle",
    ".npy",
    ".npz",
    ".parquet",
    ".nii",
    ".nii.gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
)
_FIGURE_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".svg": "svg", ".pdf": "pdf"}


def _encode(name: str, obj) -> bytes:
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)
    if isinstance(obj, Path):
        return obj.read_bytes()
    ext = _ext(name)
    if isinstance(obj, str):
        if ext in _BINARY:
            raise TypeError(
                f"a str can't be stored as {name!r}; to store a file, pass Path({obj!r}) "
                f"or use upload({obj!r}, {name!r})"
            )
        return obj.encode()
    if ext in (".pkl", ".pickle"):
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    if ext == ".json":
        return json.dumps(obj, indent=2, default=_json_default).encode()
    if ext in (".npy", ".npz"):
        import numpy as np

        buf = io.BytesIO()
        (np.save if ext == ".npy" else np.savez)(buf, obj)
        return buf.getvalue()
    if ext in (".csv", ".tsv"):
        return _table_bytes(obj, "\t" if ext == ".tsv" else ",")
    if ext == ".parquet":
        buf = io.BytesIO()
        obj.to_parquet(buf)
        return buf.getvalue()
    if ext in (".nii", ".nii.gz"):
        # nltools BrainData converts itself; nibabel's to_bytes() is always
        # uncompressed, so a .nii.gz name is gzipped here or nothing can read it.
        img = obj.to_nifti() if hasattr(obj, "to_nifti") else obj
        data = img.to_bytes()
        return gzip.compress(data, compresslevel=6, mtime=0) if ext == ".nii.gz" else data
    if ext in _FIGURE_FORMATS:
        return _figure_bytes(obj, _FIGURE_FORMATS[ext], name)
    if ext in (".txt", ".md", ".py"):
        return str(obj).encode()
    raise TypeError(
        f"don't know how to store a {type(obj).__name__} as {name!r}; use a .pkl, .json, "
        ".npy, .csv, .parquet, .nii.gz or .png name, or pass bytes"
    )


def _table_bytes(obj, sep: str) -> bytes:
    if hasattr(obj, "to_csv"):  # pandas
        return obj.to_csv(sep=sep, index=_meaningful_index(obj)).encode()
    if hasattr(obj, "write_csv"):  # polars, nltools DesignMatrix
        buf = io.BytesIO()
        obj.write_csv(buf, separator=sep)
        return buf.getvalue()
    if hasattr(obj, "__array__"):  # numpy: one column per array column, headed 0, 1, …
        import numpy as np
        import pandas as pd

        return pd.DataFrame(np.asarray(obj)).to_csv(sep=sep, index=False).encode()
    raise TypeError(f"don't know how to write a {type(obj).__name__} as a table; pass a DataFrame")


def _meaningful_index(obj) -> bool:
    """Keep row labels (region names, dates, a named index) but not the 0, 1, 2…
    pandas adds, so a plain table reads back with the same columns."""
    index = obj.index
    return any(n is not None for n in index.names) or index.dtype.kind not in "iu"


def _figure_bytes(obj, fmt: str, name: str) -> bytes:
    """A matplotlib figure, or what carries one: an Axes or a seaborn grid
    (``.figure``), a nilearn plot (``.frame_axes``). A PIL image saves itself."""
    if hasattr(obj, "save") and hasattr(obj, "mode") and fmt != "svg":  # PIL
        buf = io.BytesIO()
        obj.save(buf, format=fmt.upper())
        return buf.getvalue()
    fig = getattr(obj, "figure", None)
    if fig is None and hasattr(obj, "frame_axes"):
        fig = obj.frame_axes.figure
    if fig is None or not hasattr(fig, "savefig"):
        raise TypeError(
            f"don't know how to store a {type(obj).__name__} as {name!r}; pass a matplotlib figure"
        )
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, bbox_inches="tight")
    return buf.getvalue()


def _decode(name: str, data: bytes):
    # Pickle is unpickled only from mounts the caller can already write to
    # (their own /private, their group) or that only the instructor can write
    # to (/course, /cache/shared, assignments). A student never unpickles
    # another student's object through this path. Staff reading a student's
    # area should use get_bytes()/local_path(), not get(), for .pkl files.
    ext = _ext(name)
    if ext in (".pkl", ".pickle"):
        return pickle.loads(data)
    if ext == ".json":
        return json.loads(data)
    if ext in (".npy", ".npz"):
        import numpy as np

        return np.load(io.BytesIO(data), allow_pickle=False)
    if ext in (".csv", ".tsv"):
        import pandas as pd

        return pd.read_csv(io.BytesIO(data), sep="\t" if ext == ".tsv" else ",")
    if ext == ".parquet":
        import pandas as pd

        return pd.read_parquet(io.BytesIO(data))
    if ext in (".txt", ".md", ".py"):
        return data.decode()
    return data


def _json_default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    raise TypeError(f"{type(o).__name__} is not JSON serialisable")
