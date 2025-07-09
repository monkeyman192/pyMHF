from ctypes import CFUNCTYPE, WinDLL
from logging import getLogger
from typing import Any, Optional

import pymhf.core._internal as _internal
from pymhf.core._types import FUNCDEF
from pymhf.core.errors import UnknownFunctionError
from pymhf.core.memutils import _get_binary_info, find_pattern_in_binary
from pymhf.core.module_data import module_data
from pymhf.core.utils import saferun_decorator

calling_logger = getLogger("CallingManager")


# TODO: Everything in this file is deprecated. DO NOT use it.


@saferun_decorator
def call_exported(name: str, func_def: FUNCDEF, *args):
    """Call a function exported by the main binary.

    Parameters
    ----------
    name:
        The name of the exported function. This will generally be the mangled name of the function as provided
        by IDA/ghidra.
    func_def:
        The restype and argtypes of the function being called.
    args:
        The arguments to be passed to the function being called.
    """
    # TODO: Improve this so that the own_dll is cached as well as the func_def so that we only incur a slight
    # performance hit the very first time.
    own_dll = WinDLL(_internal.BINARY_PATH)
    func_ptr = getattr(own_dll, name)
    func_ptr.restype = func_def.restype
    func_ptr.argtypes = func_def.argtypes
    return func_ptr(*args)


@saferun_decorator
def call_function(
    name: str,
    *args,
    overload: Optional[str] = None,
    pattern: Optional[str] = None,
    func_def: Optional[FUNCDEF] = None,
    offset: Optional[int] = None,
    binary: Optional[str] = None,
) -> Any:
    """Call a named function.

    Parameters
    ----------
    name
        The name of the function to be called.
        For now the function signature will be looked up from the known signatures by name.
    args
        The args to pass to the function call.
    overload
        The overload name to be called if required.
    pattern
        The pattern which can be used to find where the function is.
        If provided this will be used instead of the offset as determined by the name.
    offset
        The offset relative to the binary.
        If provided it will take precedence over the `pattern` argument.
    binary
        The name of the binary to search for the pattern within, or to find the offset relative to.
        If not provided, will fallback to the name of the binary as provided by the `exe` config value.
    """
    if func_def is not None:
        _sig = func_def
    else:
        _sig = module_data.FUNC_CALL_SIGS[name]
    # If we have a binary defined in module_data, use it.
    binary = binary or module_data.FUNC_BINARY
    if offset is None:
        if pattern:
            offset = find_pattern_in_binary(pattern, False, binary)
        else:
            if (_pattern := module_data.FUNC_PATTERNS.get(name)) is not None:
                if isinstance(_pattern, str):
                    offset = find_pattern_in_binary(_pattern, False, binary)
                else:
                    if (opattern := _pattern.get(overload)) is not None:
                        offset = find_pattern_in_binary(opattern, False, binary)
                    else:
                        first = list(_pattern.items())[0]
                        calling_logger.warning(f"No pattern overload was provided for {name}. ")
                        calling_logger.warning(f"Falling back to the first overload ({first[0]})")
                        offset = find_pattern_in_binary(first[1], False, binary)
            else:
                offset = module_data.FUNC_OFFSETS.get(name)
            if offset is None:
                raise UnknownFunctionError(f"Cannot find function {name}")

    if isinstance(_sig, FUNCDEF):
        sig = CFUNCTYPE(_sig.restype, *_sig.argtypes)
    elif isinstance(_sig, dict):
        # TODO: Check to see if _sig is actually a dict. If it's not then we should raise an error.
        # Look up the overload:
        if (osig := _sig.get(overload)) is not None:  # type: ignore
            sig = CFUNCTYPE(osig.restype, *osig.argtypes)
        else:
            # Need to fallback on something. Raise a warning that no
            # overload was defined and that it will fallback to the
            # first entry in the dict.
            first = list(_sig.items())[0]
            calling_logger.warning(f"No function arguments overload was provided for {name}. ")
            calling_logger.warning(f"Falling back to the first overload ({first[0]})")
            sig = CFUNCTYPE(first[1].restype, *first[1].argtypes)
    else:
        raise ValueError(
            f"Invalid data type provided for `sig` argument: {type(_sig)}. Must be one of FUNCDEF or a "
            "dictionary containing a mapping of FUNCDEF objects representing overloads."
        )
    if isinstance(offset, dict):
        # Handle overloads
        if (_offset := offset.get(overload)) is not None:  # type: ignore
            offset = _offset
        else:
            _offset = list(offset.items())[0]
            calling_logger.warning(f"No function arguments overload was provided for {name}. ")
            calling_logger.warning(f"Falling back to the first overload ({_offset[0]})")
            offset = _offset[1]
    binary_base = _internal.BASE_ADDRESS
    # TODO: This is inefficient to look it up every time. This should be optimised at some point.
    if binary is not None:
        if (hm := _get_binary_info(binary)) is not None:
            _, module = hm
            binary_base = module.lpBaseOfDll

    cfunc = sig(binary_base + offset)
    return cfunc(*args)
