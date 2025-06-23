import ctypes
import typing
from ctypes import _Pointer

from ._types import DetourTime  # noqa

# Monkeypatch typed _Pointer from typeshed into ctypes.
# c/o https://github.com/python/mypy/issues/7540#issuecomment-845741357
if not typing.TYPE_CHECKING:
    ctypes._Pointer_orig = _Pointer

    class _Pointer(ctypes._Pointer):
        def __class_getitem__(cls, item):
            return ctypes.POINTER(item)

    ctypes._Pointer = _Pointer


def pymhf_overload(func):
    setattr(func, "_is_overloaded", True)
    return func


_typing_overload = typing.overload  # noqa
typing.overload = pymhf_overload
