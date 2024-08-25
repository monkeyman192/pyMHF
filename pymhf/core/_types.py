from collections import namedtuple
from enum import Enum
from typing import Any, Callable, Optional, Protocol


FUNCDEF = namedtuple("FUNCDEF", ["restype", "argtypes"])


class DetourTime(Enum):
    NONE = 0
    BEFORE = 1
    AFTER = 2


class HookProtocol(Protocol):
    _is_funchook: bool
    _is_manual_hook: bool
    _has__result_: bool
    _hook_func_name: str
    _hook_time: DetourTime
    _custom_trigger: Optional[str]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...


class ManualHookProtocol(HookProtocol):
    _hook_offset: Optional[int]
    _hook_pattern: Optional[str]
    _hook_binary: Optional[str]
    _hook_func_def: FUNCDEF
