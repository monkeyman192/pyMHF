# Some extenions to ctypes to add some extra functionality

import ctypes
import types
from enum import IntEnum
from typing import Generic, Type, TypeVar, Union

from typing_extensions import TypeAlias

_cenum_type_cache = {}

IE = TypeVar("IE", bound=IntEnum)

# Bypass hack to allow ctypes basic types to be subclassed.
# c/o https://github.com/python/cpython/issues/73456#issuecomment-1093737626
super_bypass: TypeAlias = super


class c_char_p64(ctypes.c_uint64):
    """This is a thin wrapper around the uint64 type because python has issues having char* <-> c_char_p as
    the function argument type and then accessing the value.
    This class avoids the issue by casting the underlying integer value to a ``ctypes.c_char_p`` and getting
    the value of this."""

    @property
    def _value(self) -> bytes:
        if val := super_bypass(c_char_p64, self).value:  # type: ignore
            return ctypes.c_char_p(val).value or b""
        return b""

    def __str__(self):
        return self._value.decode()

    def __bytes__(self):
        return self._value


class c_char_p32(ctypes.c_uint32):
    """This is a thin wrapper around the uint32 type because python has issues having char* <-> c_char_p as
    the function argument type and then accessing the value.
    This class avoids the issue by casting the underlying integer value to a ``ctypes.c_char_p`` and getting
    the value of this."""

    @property
    def _value(self) -> bytes:
        if val := super_bypass(c_char_p32, self).value:  # type: ignore
            return ctypes.c_char_p(val).value or b""
        return b""

    def __str__(self):
        return self._value.decode()

    def __bytes__(self):
        return self._value


class c_enum16(ctypes.c_int16, Generic[IE]):
    """c_int16 wrapper for enums. This doesn't have the full set of features an enum would normally have,
    but just enough to make it useful."""

    _enum_type: Type[IE]

    @classmethod
    def _members(cls):
        return list(cls._enum_type.__members__.keys())

    @property
    def _enum_value(self) -> IE:
        return self._enum_type(self.value)

    @property
    def name(self) -> str:
        return self._enum_value.name

    def __str__(self) -> str:
        try:
            return self._enum_value.__str__()
        except ValueError:
            # In this case the value is probably invalid. Return a string...
            return f"INVALID ENUM VALID: {self.value}"

    def __repr__(self) -> str:
        return self._enum_value.__repr__()

    def __eq__(self, other) -> bool:
        return other == self.value

    def __class_getitem__(cls: Type["c_enum16"], enum_type: Type[IE]):
        """Get the actual concrete type based on the enum_type provided.
        This will be cached so we only generate one instance of the type per IntEnum."""
        if not issubclass(enum_type, IntEnum):
            raise TypeError(f"Indexed type {enum_type!r} of type {enum_type} is not an IntEnum")
        if enum_type in _cenum_type_cache:
            return _cenum_type_cache[enum_type]
        else:
            _cls: Type[c_enum16[IE]] = types.new_class(f"c_enum16[{enum_type}]", (c_enum16,))
            _cls._enum_type = enum_type
            _cenum_type_cache[enum_type] = _cls
            return _cls


class c_enum32(ctypes.c_int32, Generic[IE]):
    """c_int32 wrapper for enums. This doesn't have the full set of features an enum would normally have,
    but just enough to make it useful."""

    _enum_type: Type[IE]

    @classmethod
    def _members(cls):
        return list(cls._enum_type.__members__.keys())

    @property
    def _enum_value(self) -> IE:
        return self._enum_type(self.value)

    @property
    def name(self) -> str:
        return self._enum_value.name

    def __str__(self) -> str:
        try:
            return self._enum_value.__str__()
        except ValueError:
            # In this case the value is probably invalid. Return a string...
            return f"INVALID ENUM VALID: {self.value}"

    def __repr__(self) -> str:
        return self._enum_value.__repr__()

    def __eq__(self, other) -> bool:
        return other == self.value

    def __class_getitem__(cls: Type["c_enum32"], enum_type: Type[IE]):
        """Get the actual concrete type based on the enum_type provided.
        This will be cached so we only generate one instance of the type per IntEnum."""
        if not issubclass(enum_type, IntEnum):
            raise TypeError(f"Indexed type {enum_type!r} of type {enum_type} is not an IntEnum")
        if enum_type in _cenum_type_cache:
            return _cenum_type_cache[enum_type]
        else:
            _cls: Type[c_enum32[IE]] = types.new_class(f"c_enum32[{enum_type}]", (c_enum32,))
            _cls._enum_type = enum_type
            _cenum_type_cache[enum_type] = _cls
            return _cls


CTYPES = Union[
    ctypes._SimpleCData,
    ctypes.Structure,
    ctypes._Pointer,
    ctypes._Pointer_orig,  # The original, un-monkeypatched ctypes._Pointer object  # type: ignore
    ctypes.Array,
    ctypes.Union,
    c_enum32,
]
