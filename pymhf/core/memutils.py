import ctypes
import logging
import sys
from gc import get_referents
from types import FunctionType, ModuleType
from typing import Literal, Optional, Sequence, Type, TypeVar, Union, overload

import pymem
import pymem.pattern
from pymem.ressources.structure import MODULEINFO

import pymhf.core._internal as _internal
import pymhf.core.caching as cache
from pymhf.extensions.ctypes import CTYPES

__all__ = ["getsize", "get_addressof", "map_struct", "find_pattern_in_binary"]

# Custom objects know their class.
# Function objects seem to know way too much, including modules.
# Exclude modules as well.
BLACKLIST = type, ModuleType, FunctionType


logger = logging.getLogger(__name__)

MEM_ACCESS_R = 0x100  # Read only.
MEM_ACCESS_RW = 0x200  # Read and Write access.


ctypes.pythonapi.PyMemoryView_FromMemory.argtypes = (
    ctypes.c_char_p,
    ctypes.c_ssize_t,
    ctypes.c_int,
)
ctypes.pythonapi.PyMemoryView_FromMemory.restype = ctypes.py_object


# TypeVar for the map_struct so that we can correctly get the returned type to
# be the same as the input type.
Struct = TypeVar("Struct", bound=CTYPES)


def getsize(obj):
    """Sum size of object & members."""
    if isinstance(obj, BLACKLIST):
        raise TypeError("getsize() does not take argument of type: " + str(type(obj)))
    seen_ids = set()
    size = 0
    objects = [obj]
    while objects:
        need_referents = []
        for _obj in objects:
            if not isinstance(_obj, BLACKLIST) and id(_obj) not in seen_ids:
                seen_ids.add(id(_obj))
                size += sys.getsizeof(_obj)
                need_referents.append(_obj)
        objects = get_referents(*need_referents)
    try:
        _len = len(obj)
    except TypeError:
        _len = None
    return size, _len


def chunks(lst: Union[Sequence, ctypes.Array], n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def match(patt: bytes, input: bytes):
    """Check whether or not the pattern matches the provided bytes."""
    for i, char in enumerate(patt):
        if not (char == b"." or char == input[i]):
            return False
    return True


def get_mem(offset: int, size: int) -> ctypes.Array[ctypes.c_char]:
    return (ctypes.c_char * size).from_address(offset)


def pprint_mem(offset: int, size: int, stride: Optional[int] = None) -> str:
    # TODO: Make this print a much nicer output... It sucks right now...
    if not offset:
        # If we are passed in an offset of 0, don't even try.
        return ""
    _data = (ctypes.c_char * size).from_address(offset)
    if stride:
        result = " ".join([f"{x:02X}".upper() for x in range(stride)]) + "\n"
        for chunk in chunks(_data, stride):
            result += " ".join([f"{k:02X}".upper() for k in chunk]) + "\n"
        return "\n" + result
    else:
        return "\n" + " ".join([k.hex().upper() for k in _data])


def _hex_repr(val: int, as_hex: bool) -> str:
    if as_hex:
        return hex(val)
    else:
        return str(val)


def get_field_info(obj, logger=None, indent: int = 0, as_hex: bool = True, max_depth: int = -1):
    if indent == max_depth:
        return
    if isinstance(obj, ctypes.Structure):
        # Need to get the actual class object to iterate over its' fields:
        cls_obj = obj.__class__
        has_values = True
    elif isinstance(obj, ctypes.Array):
        cls_obj = obj[0]
        has_values = True
    else:
        try:
            if issubclass(obj, ctypes.Structure):
                cls_obj = obj
                has_values = False
            elif issubclass(obj, ctypes.Array):
                cls_obj = obj._type_
                has_values = False
            else:
                raise TypeError(f"{obj} must be an instance of a ctypes.Structure or a subclass.")
        except TypeError as e:
            yield obj.__mro__
            raise TypeError(f"{obj} must be an instance of a ctypes.Structure or a subclass.") from e
    for field, field_type in cls_obj._fields_:
        if has_values:
            val = getattr(obj, field)
            # if isinstance(val, ctypes.Array):
            #     val = [x for x in val]
        field_data: ctypes._CField = getattr(cls_obj, field)
        offset = _hex_repr(field_data.offset, as_hex)
        size = _hex_repr(field_data.size, as_hex)
        if has_values and not isinstance(val, ctypes.Structure):
            msg = f"{field} ({field_type.__name__}): size: {size} offset: {offset} value: {val}"
        else:
            msg = f"{field} ({field_type.__name__}): size: {size} offset: {offset}"
        msg = indent * "  " + msg
        yield msg
        if not issubclass(field_type, (ctypes._SimpleCData, ctypes.Array, ctypes._Pointer)):
            if has_values:
                for _msg in get_field_info(val, logger, indent + 1, as_hex, max_depth):
                    yield _msg
            else:
                for _msg in get_field_info(field_type, logger, indent + 1, as_hex, max_depth):
                    yield _msg


def get_addressof(obj: CTYPES) -> int:
    """Get the address in memory of some object.
    If obj is a pointer, this will return the address pointed to."""
    try:
        # If it's a pointer, this is the branch that is used.
        return ctypes.cast(obj, ctypes.c_void_p).value or 0
    except Exception:
        # TODO: Get correct error type.
        # Otherwise fallback to the usual method.
        return ctypes.addressof(obj)


def _get_memview(offset: int, type_: Type[ctypes.Structure]) -> memoryview:
    """Return a memoryview which covers the region of memory specified by the
    struct provided.

    Parameters
    ----------
    offset:
        The memory address to start reading the struct from.
    type_:
        The type of the ctypes.Structure to be loaded at this location.
    """
    return ctypes.pythonapi.PyMemoryView_FromMemory(
        ctypes.cast(offset, ctypes.c_char_p),
        ctypes.sizeof(type_),
        MEM_ACCESS_RW,
    )


def _get_memview_with_size(offset: int, size: int) -> Optional[memoryview]:
    """Return a memoryview which covers the region of memory specified by the
    struct provided.

    Parameters
    ----------
    offset:
        The memory address to start reading the struct from.
    type_:
        The type of the ctypes.Structure to be loaded at this location.
    """
    if not offset:
        return None
    return ctypes.pythonapi.PyMemoryView_FromMemory(
        ctypes.cast(offset, ctypes.c_char_p),
        size,
        MEM_ACCESS_RW,
    )


def map_struct(
    offset: Union[int, ctypes.c_uint64, ctypes.c_uint32, ctypes._Pointer], type_: Type[Struct]
) -> Struct:
    r"""Return an instance of the ``type_`` struct provided which shares memory
    with the provided offset.
    Note that the amount of memory to read is automatically determined by the
    size of the struct provided.

    Parameters
    ----------
    offset:
        The memory address to start reading the struct from.
    type\_:
        The type of the ctypes.Structure to be loaded at this location.

    Returns
    -------
    An instance of the input type.
    """
    if not offset:
        raise ValueError("Offset is 0. This would result in a segfault or similar")
    instance = ctypes.cast(offset, ctypes.POINTER(type_))
    return instance.contents


def pattern_to_bytes(patt: str) -> bytes:
    """Take a pattern that looks like `8C 14 23 56 ?? 12` (etc) and convert it to a bytes object which can
    be searched with pymem.
    The format is what is provided by the IDA plugin `SigMakerEx` and the `??` values indicate a wildcard.
    This also supports the format by the IDA plugin `IDA-Fusion` which produces single `?` values for
    wildcards.
    """
    split = patt.split(" ")
    return b"".join([f"\\x{x}".encode() if (x != "??" and x != "?") else b"." for x in split])


def _get_binary_info(binary: str) -> Optional[tuple[int, MODULEINFO]]:
    if binary not in cache.hm_cache:
        try:
            pm_process = pymem.Pymem(_internal.EXE_NAME, exact_match=True)
            handle = pm_process.process_handle
            if ((module := cache.module_map.get(binary)) is None) or (handle is None):
                return None
            cache.hm_cache[binary] = (handle, module)
            return (handle, module)
        except TypeError:
            return None
    else:
        return cache.hm_cache[binary]


@overload
def find_pattern_in_binary(
    pattern: str,
    return_multiple: Literal[False],
    binary: Optional[str] = None,
) -> Optional[int]: ...


@overload
def find_pattern_in_binary(
    pattern: str,
    return_multiple: Literal[True],
    binary: Optional[str] = None,
) -> Optional[list[int]]: ...


def find_pattern_in_binary(
    pattern: str,
    return_multiple: bool = False,
    binary: Optional[str] = None,
) -> Union[int, list[int], None]:
    """
    Find a pattern in the specified binary. This is for the most part a wrapper around pymem's
    pattern_scan_module function so that we can just call this with a module name (often the name of the
    binary we ran, but it could be some other dll under the same process.)
    """
    if (_cached_offset := cache.offset_cache.get(pattern, binary)) is not None:
        logger.debug(
            f"Using cached offset 0x{_cached_offset:X} for pattern {pattern}"
            f" and binary {binary or _internal.EXE_NAME}"
        )
        return _cached_offset
    if binary is None:
        binary = _internal.EXE_NAME
    hm = _get_binary_info(binary)
    if not hm:
        return None
    handle, module = hm
    patt = pattern_to_bytes(pattern)
    _offset = pymem.pattern.pattern_scan_module(handle, module, patt, return_multiple=return_multiple)
    if _offset:
        if return_multiple:
            logger.error("Getting multiple offsets not currently supported. Falling back to first value.")
            _offset = _offset[0]
        _offset = _offset - module.lpBaseOfDll
    else:
        return None
    # Cache even if there is no result (so we don't repeatedly look for it when it's not there in case there
    # is an issue.)
    logger.debug(f"Found {pattern} at 0x{_offset:X} for binary {binary}")
    cache.offset_cache.set(pattern, _offset, binary, True)
    return _offset
