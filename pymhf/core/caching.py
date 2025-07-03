# A collection of functions which will cache things.

import json
import os
import os.path as op
from logging import getLogger
from typing import Optional

from pymem.ressources.structure import MODULEINFO

import pymhf.core._internal as _internal

logger = getLogger(__name__)


# "handle-module" cache to avoid having to get the handles and such every time we need to do a look up.
hm_cache: dict[str, tuple[int, MODULEINFO]] = {}


class OffsetCache:
    """A simple cache to store offsets once they have been found within a particular binary.
    This cached data is only correct for a specific exe unique by the hash."""

    def __init__(self):
        self._lookup: dict[str, dict[str, int]] = {}
        self.loaded = False

    @property
    def path(self) -> str:
        return op.join(_internal.CACHE_DIR, f"{_internal.BINARY_HASH}.json")

    def load(self):
        """Load the data."""
        logger.debug(f"loading cache {self.path}")
        if op.exists(self.path):
            with open(self.path, "r") as f:
                self._lookup = json.load(f)
                self.loaded = True

    def save(self):
        """Persist the cache to disk."""
        if not op.exists(op.dirname(self.path)):
            os.makedirs(op.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._lookup, f, indent=1)

    def get(self, pattern: str, binary: Optional[str] = None) -> Optional[int]:
        """Get the offset based on the pattern provided."""
        return self._lookup.get(binary or _internal.EXE_NAME, {}).get(pattern)

    def set(self, pattern: str, offset: int, binary: Optional[str] = None, save: bool = True):
        """Set the pattern with the given value and optionally save."""
        _binary = binary
        if _binary is None:
            _binary = _internal.EXE_NAME
        if _binary not in self._lookup:
            self._lookup[_binary] = {}
        self._lookup[_binary][pattern] = offset
        if save:
            self.save()

    def items(self, binary: Optional[str] = None):
        for pattern, offset in self._lookup.get(binary or _internal.EXE_NAME, {}).items():
            yield pattern, offset


module_map: dict[str, MODULEINFO] = {}
offset_cache = OffsetCache()
