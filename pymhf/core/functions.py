import ctypes
import inspect
from _ctypes import _Pointer
from functools import lru_cache
from typing import Any, Callable, NamedTuple, Optional, Union, get_args

from typing_extensions import get_type_hints

from pymhf.core._types import FUNCDEF

CTYPES = Union[ctypes._SimpleCData, ctypes.Structure, ctypes._Pointer, _Pointer]


class ArgData(NamedTuple):
    name: str
    arg_type: CTYPES


class FuncDef:
    def __init__(self, restype: Any, argtypes: list[ArgData], defaults: Optional[dict] = None):
        self.restype = restype
        self._arg_names = [x.name for x in argtypes]
        self._arg_types = [x.arg_type for x in argtypes]
        self.defaults = defaults or dict()

    @property
    def arg_types(self) -> list[CTYPES]:
        return self._arg_types

    @property
    def arg_names(self) -> list[str]:
        return self._arg_names

    def to_FUNCDEF(self) -> FUNCDEF:
        return FUNCDEF(self.restype, self.arg_types)

    def flatten(self, *args, **kwargs):
        """Take the provided signature, args and kwargs and convert to a single list of args."""
        out_args = {}
        missing = []
        # First, apply the arg values
        for i, arg in enumerate(args):
            out_args[self.arg_names[i]] = arg
        # Then, if we have any kwargs, combine with the defaults and then apply to the args.
        if len(out_args) != len(self.arg_names):
            _defaults = dict(self.defaults)
            _defaults.update(kwargs)
            # To retain order, loop over the remaining indexes and pick out the corresponding arg.
            for i in range(len(out_args), len(self.arg_names)):
                key = self.arg_names[i]
                if key in _defaults:
                    out_args[key] = _defaults[key]
                else:
                    missing.append(key)
        if missing:
            raise ValueError(f"Missing argument(s): {missing}")
        return list(out_args.values())


@lru_cache(maxsize=1024)
def _get_funcdef(func: Callable) -> FuncDef:
    """Get the funcdef for the provided function.
    This is wrapped in an lru_cache so that if multiple detours use the same function, it will only be
    analysed once."""
    func_params = inspect.signature(func).parameters
    func_type_hints = get_type_hints(func)
    _restype = func_type_hints.pop("return", type(None))
    if _restype is type(None):
        restype = None
    elif issubclass(_restype, ctypes._SimpleCData):
        restype = _restype
    else:
        raise TypeError("Return type must be a subclass of a ctypes.Structure or a simple ctypes type.")
    argtypes = []
    defaults = {}
    _missing = []
    for name, param in func_params.items():
        if name != "self":
            if name in func_type_hints:
                argtype = func_type_hints[name]
                if issubclass(argtype, get_args(CTYPES)):
                    default_val = param.default
                    if default_val != inspect.Signature.empty:
                        defaults[name] = default_val
                    argtypes.append(ArgData(name, argtype))
                else:
                    raise TypeError(f"Invalid type {argtype!r} for argument {name!r}")
            else:
                _missing.append(name)
    if _missing:
        raise TypeError(f"The argument(s) {_missing} for {func.__name__!r} do not have type hints provided.")
    return FuncDef(restype, argtypes, defaults)
