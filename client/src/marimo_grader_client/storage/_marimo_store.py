"""``storage.cache_store()``: course storage behind ``mo.persistent_cache``.

marimo's persistent cache writes to ``__marimo__/cache`` beside the notebook,
which molab throws away with the sandbox. Passing this store keeps the same
cache in the bucket instead, so a student's second run -- in a new sandbox,
or on a laptop -- restores rather than recomputes::

    with mo.persistent_cache("preprocess", store=storage.cache_store()):
        data = data.filter(...).smooth(6)

Lookup order, via marimo's ``TieredStore``:

1. the local disk (fast; scratch on molab)
2. ``/cache/shared`` -- what the instructor warmed by running the notebook
3. ``/cache/private`` -- the student's own earlier results

A hit is copied into the tiers before it (so a shared hit lands on the local
disk, not in the student's space); a miss is written to every tier that
accepts it. ``/cache/shared`` is read-only for students, so only an
instructor's run warms it.

Same trust rule as :func:`storage.cache`: marimo unpickles what this store
returns without checking a signature (an explicitly passed store is trusted
caller code), so it only ever reads the caller's own private cache and the
shared one only the instructor can write -- never another student's.

The key is marimo's hash of the cached block and the cells above it, and it
must come out the same in every sandbox or nothing ever hits. Two things break
that (both verified on marimo 0.24):

- ``Path(__file__)`` anywhere upstream: the notebook's absolute path is hashed.
- A per-session value upstream. marimo re-hashes ancestor cells *with their
  UI values*, so a widget whose value carried the session token would give
  every sign-in its own keys. Since client 0.2.2 the sign-in button delivers
  the token by message and its value is the same for every signed-in reader,
  so cached cells may depend on the button. (With client 0.2.1's button they
  must not.) This function still opens the session itself from a cached
  token, so a cell does not need that edge just to reach the bucket.
"""

from __future__ import annotations

from marimo._save.stores import FileStore, Store, TieredStore

from . import _state
from ._fs import NotFound

PREFIX = "marimo"  # keeps marimo's blobs apart from @storage.cache's under the same mount


class MountStore(Store):
    """A marimo cache ``Store`` over one storage mount."""

    def __init__(self, logical: str) -> None:
        self.logical = logical
        self.mount = _state.session().mount(logical)

    @staticmethod
    def _rel(key: str) -> str:
        return f"{PREFIX}/{key}"

    def get(self, key: str) -> bytes | None:
        try:
            return self.mount.get_bytes(self._rel(key))
        except NotFound:
            return None

    def put(self, key: str, value: bytes) -> bool:
        if not self.mount.writable:
            return False  # a student's /cache/shared: expected, not an error
        self.mount.put_bytes(self._rel(key), value)
        return True

    def hit(self, key: str) -> bool:
        return self.mount.exists(self._rel(key))

    def __repr__(self) -> str:
        return f"<MountStore {self.logical}>"


def cache_store(*, shared: bool = True) -> Store:
    """The store to hand ``mo.persistent_cache(..., store=...)``.

    Without a storage session (not signed in, or in the browser) this is
    marimo's default on-disk store, so a notebook can pass it unconditionally.
    ``shared=False`` skips the instructor-warmed tier. Never prompts.
    """
    local = FileStore()
    if not (_state.connected() or _state.use_local()):
        # A token cached by an earlier run (molab keeps it in .env) opens the
        # session here, so the cell needs no dataflow edge to the sign-in button.
        from . import connect

        if not connect(quiet=True):
            return local
    have = _state.session().logicals()
    wanted = ["/cache/shared", "/cache/private"] if shared else ["/cache/private"]
    tiers: list[Store] = [local, *(MountStore(m) for m in wanted if m in have)]
    return TieredStore(tiers) if len(tiers) > 1 else local
