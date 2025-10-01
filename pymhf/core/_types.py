from enum import Enum
from typing import Any, NamedTuple, Optional, Protocol

from typing_extensions import NotRequired, TypedDict


class pymhfGUIConfig(TypedDict):
    shown: NotRequired[bool]
    scale: NotRequired[float]
    always_on_top: NotRequired[bool]


class pymhfLoggingConfig(TypedDict):
    default_log_dir: NotRequired[str]
    log_level: NotRequired[str]
    window_name_override: NotRequired[str]
    shown: NotRequired[bool]


class pymhfConfig(TypedDict):
    exe: NotRequired[str]
    pid: NotRequired[int]
    steam_guid: NotRequired[int]
    args: NotRequired[list[str]]
    required_assemblies: NotRequired[list[str]]
    start_paused: NotRequired[bool]
    default_mod_save_dir: NotRequired[str]
    internal_mod_dir: NotRequired[str]
    start_exe: NotRequired[bool]
    interactive_console: NotRequired[bool]
    logging: NotRequired[pymhfLoggingConfig]
    gui: NotRequired[pymhfGUIConfig]


class LoadTypeEnum(Enum):
    INVALID = 0
    SINGLE_FILE = 1
    LIBRARY = 2
    MOD_FOLDER = 3


class FunctionIdentifier(NamedTuple):
    name: str
    offset: int
    binary: str
    is_absolute: bool

    def __eq__(self, other: "FunctionIdentifier"):
        """Two FunctionIdentifier's are the same if their offset and binary are the same."""
        return self.offset == other.offset and self.binary == other.binary

    def __hash__(self):
        """Only use the offset and binary values for the hash. Name doesn't matter."""
        return hash((self.offset, self.binary))


# TODO: Fully deprecate.
class FUNCDEF(NamedTuple):
    restype: Any
    argtypes: list


class DetourTime(Enum):
    NONE = 0
    BEFORE = 1
    AFTER = 2


class KeyPressProtocol(Protocol):
    _hotkey: str
    _hotkey_press: str


class CustomTriggerProtocol(Protocol):
    _custom_trigger: Optional[str]
    _description: Optional[str]
    _hook_time: DetourTime

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class HookProtocol(Protocol):
    _disabled: bool
    _is_funchook: bool
    _is_manual_hook: bool
    _is_imported_func_hook: bool
    _is_exported_func_hook: bool
    _has__result_: bool
    _hook_func_name: str
    _hook_func_def: FUNCDEF
    _hook_offset: Optional[int]
    _hook_pattern: Optional[str]
    _hook_time: DetourTime
    _func_overload: Optional[str]
    _get_caller: Optional[bool]
    _noop: Optional[bool]
    _dll_name: Optional[str]

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class CallerHookProtocol(HookProtocol):
    def caller_address(self) -> int:
        """The address relative to the base of the calling binary that this functiuon detour was called from.
        Note that this will be the address one instruction after the caller since this value is where
        execution returns to after the detours and original function have been run.
        """
        ...


# TODO: Remove once we have got the binary able to be specified for function_hook decorators.
class ManualHookProtocol(HookProtocol):
    _hook_binary: Optional[str]
