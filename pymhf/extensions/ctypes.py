# Some extenions to ctypes to add some extra functionality

import ctypes
import types
from enum import IntEnum
from typing import Generic, Type, TypeVar

_cenum_type_cache = {}

T = TypeVar("T", bound=IntEnum)


class c_enum32(ctypes.c_int32, Generic[T]):
    """c_int32 wrapper for enums. This doesn't have the full set of features an enum would normally have,
    but just enough to make it useful."""

    _enum_type: IntEnum

    def __repr__(self):
        return self._enum_type(self.value).__repr__()

    def __eq__(self, other):
        return other == self.value

    def __class_getitem__(cls: Type["c_enum32"], enum_type: Type[IntEnum]):
        """Get the actual concrete type based on the enum_type provided.
        This will be cached so we only generate one instance of the type per IntEnum."""
        if not issubclass(enum_type, IntEnum):
            raise TypeError(f"Indexed type {enum_type!r} of type {enum_type} is not an IntEnum")
        if enum_type in _cenum_type_cache:
            return _cenum_type_cache[enum_type]
        else:
            _cls: c_enum32 = types.new_class(f"c_enum32[{enum_type}]", (c_enum32,))
            _cls._enum_type = enum_type
            _cenum_type_cache[enum_type] = _cls
            return _cls
