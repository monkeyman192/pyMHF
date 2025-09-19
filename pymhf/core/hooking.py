import ast
import ctypes
import inspect
import logging
import struct
import traceback
from collections import defaultdict
from collections.abc import Callable
from ctypes import CFUNCTYPE
from typing import Any, Optional, Type, Union

import cyminhook
from typing_extensions import Concatenate, Generic, ParamSpec, Self, TypeVar, deprecated

import pymhf.core._internal as _internal
from pymhf.core._types import (
    FUNCDEF,
    CallerHookProtocol,
    CustomTriggerProtocol,
    DetourTime,
    FunctionIdentifier,
    HookProtocol,
    KeyPressProtocol,
    ManualHookProtocol,
)
from pymhf.core.functions import FuncDef, _get_funcdef
from pymhf.core.memutils import _get_binary_info, find_pattern_in_binary, get_addressof, map_struct
from pymhf.utils.iced import HAS_ICED, generate_load_stack_pointer_bytes, get_first_jmp_addr

logger = logging.getLogger(__name__)


BITS = struct.calcsize("P") * 8


# Currently unused, but can maybe figure out how to utilise it.
# It currently doesn't work I think because we subclass from the cyminhook class
# which is cdef'd, and I guess ast falls over trying to get the actual source...
# Can possible use annotations and inspect the return type (return `None`
# explictly eg.) to give some hints. Maybe just raise warnings etc.
def _detour_is_valid(f):
    for node in ast.walk(ast.parse(inspect.getsource(f))):
        if isinstance(node, ast.Return):
            return True
    return False


_FunctionHook_overloads: dict = defaultdict(lambda: dict())


# TODO: Move to a different file with `Mod` from mod_loader.py
class FuncHook(cyminhook.MinHook):
    original: Callable[..., Any]
    target: int
    detour: Callable[..., Any]
    signature: Callable[..., Any]
    _name: str
    _invalid: bool = False
    _func_def: Optional[FUNCDEF]
    _offset_is_absolute: bool

    def __init__(
        self,
        detour_name: str,
        offset: int,
        func_def: FUNCDEF,
        overload: Optional[str] = None,
        binary: Optional[str] = None,
        offset_is_absolute: bool = False,
    ):
        # First, handle the binary so we can know what our base is.
        if binary is not None:
            if (hm := _get_binary_info(binary)) is not None:
                _, module = hm
                self._binary_base = module.lpBaseOfDll
                self._binary = binary
            else:
                self._binary = _internal.EXE_NAME
                self._binary_base = _internal.BASE_ADDRESS
        else:
            self._binary = _internal.EXE_NAME
            self._binary_base = _internal.BASE_ADDRESS

        # Next, handle determining the absolute offset in memory.
        self._offset_is_absolute = offset_is_absolute
        if self._offset_is_absolute:
            self.target = offset
            self._offset = offset - self._binary_base
        else:
            self.target = self._binary_base + offset
            self._offset = offset
        self._func_def = func_def
        self._binary = binary

        # Depending on the bitness, create the variable to hold the return address.
        if BITS == 64:
            self._rsp_addr = ctypes.c_ulonglong(0)
        else:
            self._rsp_addr = ctypes.c_ulong(0)

        self.signature = CFUNCTYPE(self._func_def.restype, *self._func_def.argtypes)

        self._has_noop = False
        self._before_detours: list[HookProtocol] = []
        self._after_detours: list[HookProtocol] = []
        self._after_detours_with_results: list[HookProtocol] = []
        # Disabled detours will go here. This will include hooks disabled by the
        # @disable decorator, as well as hooks which are one-shots and have been
        # run.
        self._disabled_detours: set[HookProtocol] = set()
        self._oneshot_detours: dict[HookProtocol, Callable] = {}
        self.overload = overload
        self.state = None
        self._name = detour_name

    @property
    def caller_address(self):
        if self._rsp_addr.value:
            return self._rsp_addr.value - _internal.BASE_ADDRESS
        return 0

    @property
    def name(self):
        if self.overload is not None:
            return f"{self._name}({self.overload})"
        else:
            return self._name

    def _determine_detour_list(self, detour: HookProtocol) -> Optional[list[HookProtocol]]:
        # Determine when the hook should be run. Don't add the detour yet
        # because if the hook is a one-shot then we need to know when to run it.
        detour_list = None
        if detour._hook_time == DetourTime.BEFORE:
            detour_list = self._before_detours
        elif detour._hook_time == DetourTime.AFTER:
            # Check to see if the detour has the `_result_` argument.
            # This will have been determined already when the function was
            # decorated
            # TODO: Ensure this works if there is some other funky decoration
            # shenanigans (eg. with a one-shot decorator...)
            if getattr(detour, "_has__result_", False):
                detour_list = self._after_detours_with_results
            else:
                detour_list = self._after_detours
        else:
            logger.error(f"Detour {detour} has an invalid detour time: {detour._hook_time}")
        return detour_list

    def add_detour(self, detour: HookProtocol):
        """Add the provided detour to this FuncHook."""
        # If the hook has the `_disabled` attribute, then don't add the detour.
        if getattr(detour, "_disabled", False):
            self._disabled_detours.add(detour)
            return

        if getattr(detour, "_noop", False):
            self._has_noop = True
            logger.warning(
                f"The hook {detour._hook_func_name} has been marked as NOOP. If there are multiple detours "
                "registered for this hook they may behave weirdly and the game may crash if this hook is not "
                "defined well."
            )

        # Determine the detour list to use. If none, then return.
        if (detour_list := self._determine_detour_list(detour)) is None:
            logger.error(
                f"Unable to assign {detour} to a detour type. Please check it. It has not been added."
            )
            return

        if not getattr(detour, "_is_one_shot", False):
            # If we aren't a one-shot detour, then add it to the list.
            detour_list.append(detour)

        # If the hook is a one-shot, wrap it so that it can remove itself once
        # it's executed.
        if getattr(detour, "_is_one_shot", False):

            def _one_shot(
                *args,
                detour: HookProtocol = detour,
                detour_list: list[HookProtocol] = detour_list,
            ):
                # NOTE: This may not work well if the code is called from multiple threads at the same time.
                try:
                    detour(*args)
                    self._disabled_detours.add(detour)
                    detour_list.remove(self._oneshot_detours[detour])
                except ValueError:
                    logger.warning(
                        f"Had an issue removing one-shot {detour._hook_func_name} from detour list."
                    )
                except Exception:
                    logger.error(traceback.format_exc())

            self._oneshot_detours[detour] = _one_shot
            detour_list.append(_one_shot)

        # If the detour needs the `caller_address` property, add it.
        if getattr(detour, "_get_caller", False) is True:
            # We need to get the type of the class and assign the attribute to the class function itself.
            detour.__func__.caller_address = lambda: self.caller_address

    def remove_detour(self, detour: HookProtocol):
        """Remove the provided detour from this FuncHook."""
        # Determine the detour list to use. If none, then return.
        if (detour_list := self._determine_detour_list(detour)) is None:
            return

        if detour in detour_list:
            detour_list.remove(detour)
        # Try and remove the hook from the diabled list also in case it's there.
        if detour in self._disabled_detours:
            self._disabled_detours.remove(detour)
        # Also check for one-shot detours. They may or may not have been called,
        # but we don't really care.
        # If it has been called then it will be in the disabled detours and so
        # we will have handled it already.
        # If it hasn't then we will look up the mapping now and remove it.
        if detour in self._oneshot_detours:
            one_shot_detour = self._oneshot_detours.pop(detour)
            if one_shot_detour in detour_list:
                detour_list.remove(one_shot_detour)

        # If we have no more detours remaining, then we disable and close this hook so that we may free it to
        # allow us to correctly re-create it later if need be.
        if not detour_list:
            self.disable()
            self.close()

        # Check to see if we have any detours marked as NOOP. If not, make sure the flag is set to false.
        # We can always just check the before detours since only a before detour can be marked as NOOP.
        self._has_noop == any([getattr(d, "_noop", False) for d in self._before_detours])

    @property
    def _should_enable(self):
        return (
            len(self._before_detours) > 0
            or len(self._after_detours) > 0
            or len(self._after_detours_with_results)
        )

    def bind(self) -> bool:
        """Actually initialise the base class. Returns whether the hook is bound."""
        if not self._should_enable or self._invalid:
            return False

        self.detour = self._compound_detour

        try:
            super().__init__(signature=self.signature, target=self.target)
        except cyminhook._cyminhook.Error as e:  # type: ignore
            if e.status == cyminhook._cyminhook.Status.MH_ERROR_ALREADY_CREATED:
                logger.error("Hook is already created")
            logger.error(f"Failed to initialize hook {self._name} at 0x{self.target:X}")
            logger.error(e.status.name[3:].replace("_", " ") + f" ({e})")
            self.state = "failed"
            return False
        self.state = "initialized"
        return True

    def _compound_detour(self, *args):
        ret = None

        # Loop over the before detours, keeping the last none-None return value.
        try:
            for i, func in enumerate(self._before_detours):
                r = func(*args)
                if r is not None:
                    ret = r
        except Exception:
            bad_detour = self._before_detours.pop(i)
            logger.error(f"There was an error with detour {bad_detour}. It has been disabled.")
            logger.error(traceback.format_exc())
            self._disabled_detours.add(bad_detour)

        # If we don't have any decorators which NOOP the original function then run as usual.
        if not self._has_noop:
            # If we get a return value that is not None, then pass it through.
            if ret is not None:
                result = self.original(*ret)
            else:
                result = self.original(*args)
            after_ret = None
        # If we have any NOOP's, then we don't want to run the original, and instead will have the last result
        # returned from our functions as the "result".
        else:
            result = ret
            after_ret = ret

        # Now loop over the after functions. We'll need to handle the cases of
        # functions which take the `_result_` kwarg, and those that don't.
        try:
            for i, func in enumerate(self._after_detours):
                after_ret = func(*args)
            i = None
            for j, func in enumerate(self._after_detours_with_results):
                after_ret = func(*args, _result_=result)
            j = None
        except Exception:
            if i is not None:
                bad_detour = self._after_detours.pop(i)
            else:
                bad_detour = self._after_detours_with_results.pop(j)
            logger.error(f"There was an error with detour {bad_detour}. It has been disabled.")
            logger.error(traceback.format_exc())
            self._disabled_detours.add(bad_detour)

        if after_ret is not None:
            return after_ret
        return result

    def close(self):
        super().close()
        self.state = "closed"

    def queue_enable(self):
        if self._should_enable:
            cyminhook.queue_enable(self)
            self.state = "enabled"

    def enable(self):
        if self._should_enable:
            super().enable()
            self.state = "enabled"

    def disable(self):
        if self.state == "enabled":
            super().disable()
            self.state = "disabled"

    @property
    def offset(self) -> int:
        """The relative offset of the target to the binary base."""
        return self.target - self._binary_base


@deprecated("Use @function_hook(signature=...) instead", category=DeprecationWarning)
class HookFactory:
    _name: str
    _templates: Optional[tuple[str]] = None
    _overload: Optional[str] = None

    @classmethod
    def overload(cls, overload_args):
        # TODO: Improve type hinting and possible make this have a generic arg
        # type to simplify the logic...
        raise NotImplementedError

    @staticmethod
    def _set_detour_as_funchook(
        detour: Callable[..., Any],
        cls: Optional["HookFactory"] = None,
        detour_name: Optional[str] = None,
    ):
        """Set all the standard attributes required for a function hook."""
        setattr(detour, "_is_funchook", True)
        setattr(detour, "_is_manual_hook", False)
        setattr(detour, "_is_imported_func_hook", False)
        setattr(detour, "_is_exported_func_hook", False)
        setattr(detour, "_has__result_", False)
        setattr(detour, "_noop", False)
        if cls:
            if hasattr(cls, "_overload"):
                setattr(detour, "_func_overload", cls._overload)
            else:
                setattr(detour, "_func_overload", None)
            if hasattr(cls, "_name"):
                setattr(detour, "_hook_func_name", cls._name)
        else:
            if detour_name is None:
                raise ValueError("class used as detour must have a name")
            else:
                setattr(detour, "_hook_func_name", detour_name)

    @classmethod
    def after(cls, detour: Callable[..., Any]) -> HookProtocol:
        """
        Run the detour *after* the original function.
        An optional `_result_` argument can be added as the final argument.
        If this argument is provided it will be the result of calling the original function.
        """
        HookFactory._set_detour_as_funchook(detour, cls)
        setattr(detour, "_hook_time", DetourTime.AFTER)
        if "_result_" in inspect.signature(detour).parameters.keys():
            setattr(detour, "_has__result_", True)
        return detour

    @classmethod
    def before(cls, detour: Callable[..., Any]) -> HookProtocol:
        """
        Run the detour *before* the original function.
        If this detour returns any values they must be the same types and order as the original arguments to
        the function. If this happens these values will be passed into the original function instead of the
        original arguments.
        """
        HookFactory._set_detour_as_funchook(detour, cls)
        setattr(detour, "_hook_time", DetourTime.BEFORE)
        return detour


@deprecated(
    "Use @function_hook(signature=...) or @function_hook(offset=...) instead",
    category=DeprecationWarning,
)
def manual_hook(
    name: str,
    offset: Optional[int] = None,
    pattern: Optional[str] = None,
    func_def: Optional[FUNCDEF] = None,
    detour_time: str = "before",
    binary: Optional[str] = None,
):
    """Manually hook a function.

    Parameters
    ----------
    name:
        The name of the function to hook. This doesn't need to be known, but any two manual hooks sharing the
        same name will be combined together so one should remember to keep the name/offset combination unique.
    offset:
        The offset in bytes relative to the start of the binary.
        To determine this, you normally subtract off the exe Imagebase value from the address in IDA (or
        similar program.)
    pattern:
        A pattern which can be used to unqiuely find the function to be hooked within the binary.
        The pattern must have a format like "01 23 45 67 89 AB CD EF".
        The format is what is provided by the IDA plugin `SigMakerEx` and the `??` values indicate a wildcard.
    func_def:
        The function arguments and return value. This is provided as a `pymhf.FUNCDEF` object.
        This argument is only optional if another function with the same offset and name has already been
        hooked in the same mod.
    detour_time:
        When the detour should run ("before" or "after")
    binary:
        If provided, this will be the name of the binary which the function being hooked is within.
        `offset` and `pattern` are found relative to/within the memory region of this binary.
    """

    def inner(detour: Callable[..., Any]) -> ManualHookProtocol:
        # if offset is None and pattern is None:
        #     raise ValueError(f"One of pattern or offset must be set for the manual hook: {detour}")
        HookFactory._set_detour_as_funchook(detour, None, name)
        if detour_time == "before":
            setattr(detour, "_hook_time", DetourTime.BEFORE)
        elif detour_time == "after":
            setattr(detour, "_hook_time", DetourTime.AFTER)
        # Set some manual values which can be retrieved when the func hook gets parsed.
        setattr(detour, "_is_manual_hook", True)
        setattr(detour, "_hook_offset", offset)
        setattr(detour, "_hook_pattern", pattern)
        setattr(detour, "_hook_binary", binary)
        setattr(detour, "_hook_func_def", func_def)
        if "_result_" in inspect.signature(detour).parameters.keys():
            setattr(detour, "_has__result_", True)
        return detour

    return inner


def NOOP(detour: HookProtocol) -> HookProtocol:
    """
    Specify the hook to not run the original function.
    This decorator must be used with extreme caution as it can cause the hooked program to not run correctly
    if not used right.
    The decorated function MUST return something of the same type as the original function if the hooked
    function normally returns something otherwise the hooked program will almost certainly crash.
    """
    if getattr(detour, "_hook_time", None) == DetourTime.BEFORE:
        setattr(detour, "_noop", True)
    else:
        logger.warning(
            "NOOP decorator can only be applied to 'before' hooks."
            "Either change the detour to a before detour, or, if it is, ensure that this decorator is "
            "applied above the hook decorator."
        )
    return detour


def disable(obj):
    """
    Disable the current hook or mod.
    """
    setattr(obj, "_disabled", True)
    return obj


@deprecated("Use @function_hook(imported_name=...) instead", category=DeprecationWarning)
def imported(dll_name: str, func_name: str, func_def: FUNCDEF, detour_time: str = "after"):
    """Hook an imported function in `dll_name` dll.

    Parameters
    ----------
    dll_name:
        The name of the dll which contains the function.
    func_name:
        The name of the function in the dll which is to be hooked.
    func_def:
        The function signature.
    detour_time:
        Whether to run the detour before or after the original function.
    """

    def inner(detour: Callable[..., Any]) -> HookProtocol:
        HookFactory._set_detour_as_funchook(detour, None, func_name)
        setattr(detour, "_dll_name", dll_name)
        setattr(detour, "_is_imported_func_hook", True)
        setattr(detour, "_hook_func_def", func_def)
        if detour_time == "before":
            setattr(detour, "_hook_time", DetourTime.BEFORE)
        else:
            setattr(detour, "_hook_time", DetourTime.AFTER)
            if "_result_" in inspect.signature(detour).parameters.keys():
                setattr(detour, "_has__result_", True)
        return detour

    return inner


@deprecated("Use @function_hook(exported_name=...) instead", category=DeprecationWarning)
def exported(func_name: str, func_def: FUNCDEF, detour_time: str = "after"):
    """Hook an exported function.

    Parameters
    ----------
    func_name:
        The name of the function which is to be hooked.

        .. note::
            It is recommended that the function name is the "mangled" version.
            Ie. do not "demangle" the function name.
    func_def:
        The function signature.
    detour_time:
        Whether to run the detour before or after the original function.
    """

    def inner(detour: Callable[..., Any]) -> HookProtocol:
        HookFactory._set_detour_as_funchook(detour, None, func_name)
        setattr(detour, "_is_exported_func_hook", True)
        setattr(detour, "_hook_func_def", func_def)
        if detour_time == "before":
            setattr(detour, "_hook_time", DetourTime.BEFORE)
        else:
            setattr(detour, "_hook_time", DetourTime.AFTER)
        return detour

    return inner


def one_shot(func: HookProtocol) -> HookProtocol:
    """Run this detour once only."""
    setattr(func, "_is_one_shot", True)
    return func


def get_caller(func: HookProtocol) -> CallerHookProtocol:
    """Capture the address this hooked function was called from.
    This address will be acessible by the `caller_address()` method which will belong to the function that is
    decorated by this.

    Examples
    --------
    .. code:: py

        @get_caller
        @manual_hook("test_function", 0x12345678, FUNCDEF(restype=ctypes.void, argtypes=[ctypes.c_ulonglong]))
        def something(self, *args):
            logger.info(f"'test_function' called with {args} from 0x{self.something.caller_address():X}")
    """
    func._get_caller = True
    return func  # type: ignore


def on_key_pressed(event: str):
    """Register the provided event as a key press handler.
    When the key is pressed, the decorated function will be called.

    Parameters
    ----------
    event:
        The string representing the key which is to trigger the event.
    """

    def wrapped(func: Callable[..., Any]) -> KeyPressProtocol:
        setattr(func, "_hotkey", event)
        setattr(func, "_hotkey_press", "down")
        return func  # type: ignore

    return wrapped


def on_key_release(event: str):
    """Register the provided event as a key release handler.
    When the key is released, the decorated function will be called.

    Parameters
    ----------
    event:
        The string representing the key which is to trigger the event.
    """

    def wrapped(func: Callable[..., Any]) -> KeyPressProtocol:
        setattr(func, "_hotkey", event)
        setattr(func, "_hotkey_press", "up")
        return func  # type: ignore

    return wrapped


class HookManager:
    def __init__(self):
        self.hooks: dict[FunctionIdentifier, FuncHook] = {}
        # Keep a mapping of any hooks that try to be registered but fail.
        # These hooks will not be instances of classes, but the class type.
        self.failed_hooks: dict[str, Type[FuncHook]] = {}
        # A mapping of the custom event hooks which can be registered by modules
        # for individual mods.
        self.custom_callbacks: dict[str, dict[DetourTime, set[CustomTriggerProtocol]]] = {}
        self._uninitialized_hooks: set[FunctionIdentifier] = set()
        self._hook_id_mapping: dict[HookProtocol, FunctionIdentifier] = {}
        self._get_caller_detours: set[FunctionIdentifier] = set()

    def _get_funchook(self, hook: HookProtocol) -> Optional[FuncHook]:
        """Return the associated function hook for the provided hook."""
        if (hook_id := self._hook_id_mapping.get(hook)) is not None:
            return self.hooks.get(hook_id)

    def _resolve_dependencies(self):
        """Resolve dependencies of hooks.
        This will get all the functions which are to be hooked and construct
        compound hooks as required.
        """
        # TODO: Make work.
        pass

    def _add_custom_callbacks(self, callbacks: set[CustomTriggerProtocol]):
        """Add the provided function to the specified callback type."""
        for cb in callbacks:
            if (cb_type := cb._custom_trigger) is None:
                continue
            if cb_type not in self.custom_callbacks:
                self.custom_callbacks[cb_type] = {}
            detour_time = getattr(cb, "_hook_time", DetourTime.NONE)
            if detour_time not in self.custom_callbacks[cb_type]:
                self.custom_callbacks[cb_type][detour_time] = {
                    cb,
                }
            else:
                self.custom_callbacks[cb_type][detour_time].add(cb)

    def _remove_custom_callbacks(self, callbacks: set[CustomTriggerProtocol]):
        # Remove the values in the list which correspond to the data in `callbacks`
        for cb in callbacks:
            if (cb_type := cb._custom_trigger) is None:
                continue
            if cb_type in self.custom_callbacks:
                # Remove the functions from the set and then check whether it's
                # empty.
                self.custom_callbacks[cb_type][getattr(cb, "_hook_time", DetourTime.NONE)].discard(cb)
                if all(not x for x in self.custom_callbacks[cb_type].values()):
                    del self.custom_callbacks[cb_type]

    def call_custom_callbacks(
        self,
        callback_key: str,
        detour_time: DetourTime = DetourTime.NONE,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        alert_nonexist: bool = False,
    ):
        """Call the specified custom callback with the given detour_time.

        Parameters
        ----------
        callback_key:
            The key which is used to reference the custom callback.
        detour_time:
            Whether to call the ``before`` or ``after`` detour.
        args:
            An optional list of args to be passed to the function(s) if found.
        kwargs:
            An optional dictionary of keyword arguments to be passed to the function(s) if found.
        alert_nonexistant:
            If True, raise a ``ValueError`` if no function is found for the ``callback_key`` value.

        Notes
        -----
            If there is no callback registered for the key and detour_time combination nothing will happen.
        """
        callbacks = self.custom_callbacks.get(callback_key, {})
        if callbacks:
            if args is None:
                args = []
            if kwargs is None:
                kwargs = {}
            for cb in callbacks.get(detour_time, set()):
                try:
                    cb(*args, **kwargs)
                except Exception:
                    logger.exception(f"There was an issue calling custom callback {cb}. It has been removed.")
                    self._remove_custom_callbacks(
                        {
                            cb,
                        }
                    )
        elif alert_nonexist:
            raise ValueError(f"Custom callback {callback_key} cannot be found.")

    def try_remove_hook(self, hook: HookProtocol):
        """Remove the provided hook from the internal store only if it's already closed."""
        if (hook_id := self._hook_id_mapping.get(hook)) is not None:
            if (func_hook := self.hooks.get(hook_id)) is not None:
                if func_hook.state == "closed":
                    del self.hooks[hook_id]

    def register_hook(self, hook: HookProtocol):
        """Register the provided hook.
        This will determine the offset of the function being hooked."""
        if getattr(hook, "_disabled", False) is True:
            # Do nothing, exit immediately.
            return
        hook_func_name = hook._hook_func_name
        # If the hook has an overload, add it here so that we can disambiguate them.
        if getattr(hook, "_func_overload", None) is not None:
            hook_func_name += f"({hook._func_overload})"

        # First, try and look up some info about the hook.
        # We can't trust the name of the hook as this may not be correct or mean anything.
        # The only thing we can trust is a relative offset within a particular binary.

        hook_binary = _internal.EXE_NAME
        hook_offset = None
        hook_offset_is_absolute = False

        # First, if we have an offset then look it up.
        if hook._hook_offset is not None:
            hook_offset = hook._hook_offset
        # Otherwise, try lookup the pattern if we have one.
        elif (hook_pattern := hook._hook_pattern) is not None:
            hook_offset = find_pattern_in_binary(hook_pattern, False, hook_binary)
        elif hook._is_imported_func_hook:
            hook_binary = hook._dll_name.lower()
            if (dll_func_ptrs := _internal.imports.get(hook_binary)) is not None:
                func_ptr = dll_func_ptrs.get(hook_func_name)
                # For now, cast the func_ptr object back to the target location in memory.
                # This is wasteful, but simple for now for testing...
                hook_offset = ctypes.cast(func_ptr, ctypes.c_void_p).value
                hook_offset_is_absolute = True
            else:
                logger.error(f"Cannot find {hook_binary} in the import list")
                return
        elif hook._is_exported_func_hook:
            if _internal.BINARY_PATH is None:
                logger.error("Current running binary path unknown. Cannot hook exported functions")
                return
            # TODO: This is inefficient. We should only instantiate the "dll" once.
            own_dll = ctypes.WinDLL(_internal.BINARY_PATH)
            func_ptr = getattr(own_dll, hook._hook_func_name)
            hook_offset = ctypes.cast(func_ptr, ctypes.c_void_p).value
            hook_offset_is_absolute = True

        if hook_offset is not None:
            func_id = FunctionIdentifier(hook_func_name, hook_offset, hook_binary, hook_offset_is_absolute)
        else:
            logger.error(f"Unable to find offset for {hook_func_name}. Hook will not be registered.")
            return

        if func_id not in self.hooks:
            try:
                self.hooks[func_id] = FuncHook(
                    func_id.name,
                    offset=func_id.offset,
                    func_def=hook._hook_func_def,
                    binary=hook_binary,
                    offset_is_absolute=func_id.is_absolute,
                )
            except Exception:
                logger.exception(f"There was an issue creating the func hook for {func_id}")
                return
            self._uninitialized_hooks.add(func_id)
            self._hook_id_mapping[hook] = func_id
        self.hooks[func_id].add_detour(hook)

        if getattr(hook, "_get_caller", False):
            self._get_caller_detours.add(func_id)

    def initialize_hooks(self) -> int:
        """Initialize any uninitialized hooks.
        This will also enable the hooks so that they become active.
        """
        count = 0
        for hook_func_id in self._uninitialized_hooks:
            hook = self.hooks[hook_func_id]
            bound = hook.bind()
            if bound:
                count += 1
            else:
                # If the mod didn't get bound, we don't try and enable it!
                continue
            # Try and enable the hook.
            try:
                hook.queue_enable()
                if hook._offset_is_absolute:
                    offset = hook.target
                    prefix = ""
                else:
                    offset = hook.offset
                    prefix = f"{hook._binary}+"
                logger.debug(f"Enabled hook for {hook_func_id.name} at {prefix}0x{offset:X}")
            except Exception:
                logger.error(f"Unable to enable {hook_func_id.name} because:")
                logger.error(traceback.format_exc())

        # Now, bulk enable all hooks.
        cyminhook.apply_queued()

        for hook_func_id in self._uninitialized_hooks:
            # If any of the hooked functions want to log where they were called from, we need to overwrite
            # part of the trampoline bytes to capture the RSP register.
            if hook_func_id in self._get_caller_detours:
                hook = self.hooks[hook_func_id]
                if not HAS_ICED:
                    logger.error(
                        f"Cannot get calling address of {hook_func_id.name} as `iced_x86` package is not "
                        "installed.\nPlease install and try again."
                    )
                    continue
                # First, get the first jump so we can go to the trampoline bytes.
                jmp_data = (ctypes.c_char * 0x10).from_address(hook.target)
                jmp_addr = get_first_jmp_addr(jmp_data.raw, hook.target)
                if jmp_addr:
                    # minhook seems to have only gotten 0x20 bytes for the trampoline. Would be nice to have
                    # more but this is all we have to work with. It's luckily *just* enough.
                    # If we ever need more we'll need to make our own little detour somewhere else.
                    data_at_detour = (ctypes.c_char * 0x20).from_address(jmp_addr)

                    rsp_buff_addr = get_addressof(hook._rsp_addr)

                    rsp_load_bytes = generate_load_stack_pointer_bytes(rsp_buff_addr, jmp_addr, BITS)
                    # Get the original bytes written by minhook so that we can restore them.
                    orig_bytes = data_at_detour.raw[:0xE]
                    for i in range(len(rsp_load_bytes)):
                        data_at_detour[i] = rsp_load_bytes[i]
                    for j in range(len(orig_bytes)):
                        data_at_detour[i + j + 1] = orig_bytes[j]
                    logger.info(
                        f"The function {hook_func_id.name} has a modified hook to get the calling address."
                    )

        # There are no uninitialized hooks.
        self._uninitialized_hooks = set()
        return count

    def _debug_show_states(self):
        # Return the states of all the registered hooks
        for hook_func_id, hook in self.hooks.items():
            logger.info(f"Functions registered for {hook_func_id.name}:")
            if hook._before_detours:
                logger.info("  Before Detours:")
                for func in hook._before_detours:
                    logger.info(f"    {func}")
            if hook._after_detours:
                logger.info("  After Detours:")
                for func in hook._after_detours:
                    logger.info(f"    {func}")


class Structure(ctypes.Structure):
    """Simple wrapper around ctypes.Structure."""

    def __getattribute__(self, name: str):
        # Hook the instance attribute lookup so that we may "bind" the instance to the returned FunctionHook
        # instance.
        # We need to do this because the decorator has no knowledge of the actual bound instance at run-time.
        res = super().__getattribute__(name)
        if isinstance(res, FunctionHook):
            res._bound_class = self
        return res

    @classmethod
    def new_empty(cls) -> Self:
        """Create a new empty instance of the structure. This will have ALL of its data as empty bytes.
        The purpose of this is to allocate enough bytes to fit the object in memory so that it may then be
        populated with real data, or passed to some function to have its' data populated.
        """
        buffer = ctypes.create_string_buffer(ctypes.sizeof(cls))
        addr = get_addressof(buffer)
        return map_struct(addr, cls)


P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S", bound=Structure)
THIS = TypeVar(
    "THIS",
    bound=Union[
        ctypes.c_uint32,  # 32 bit "pointer" types.
        ctypes.c_ulong,
        ctypes.c_uint64,  # 64 bit "pointer" types.
        ctypes.c_ulonglong,
        ctypes._Pointer,  # Actual pointer type.
    ],
)


class FunctionHook(Generic[P, R]):
    def __init__(
        self,
        func: Union[Callable[P, R], Callable[Concatenate[S, THIS, P], R]],
        signature: Optional[str] = None,
        offset: Optional[int] = None,
        exported_name: Optional[str] = None,
        imported_name: Optional[str] = None,
        overload_id: Optional[str] = None,
        is_static: bool = False,
    ):
        self._func = func
        self._signature = signature
        self._offset = offset
        self._exported_name = exported_name
        self._imported_name = imported_name
        self._overload_id = overload_id
        self._is_static = is_static
        self._this_is_pointer: Optional[bool] = None
        self._bound_class: Optional[ctypes.Structure] = None
        self._funcdef: Optional[FuncDef] = None

    @property
    def this_is_pointer(self):
        """Only valid for bound methods. Returns True if the first argument is a pointer type."""
        if self._this_is_pointer is not None:
            return self._this_is_pointer
        if self._funcdef is None:
            self._funcdef = _get_funcdef(self._func)
        self._this_is_pointer = issubclass(self._funcdef.arg_types[0], ctypes._Pointer) | issubclass(
            self._funcdef.arg_types[0], ctypes._Pointer_orig
        )
        return self._this_is_pointer

    def _call(self, *args, **kwargs) -> Optional[R]:
        """Call the actual function. This will do some work to find where the function is in memory and then
        call it with the provided arguments.
        """
        try:
            # Get the FUNCDEF. This will have named arguments with types so that we may construct a function
            # prototype which allows kwargs.
            if self._funcdef is None:
                self._funcdef = _get_funcdef(self._func)
            # Unfortunately the ctypes function prototype can only be called with kwargs if its a function
            # which is in a remote library.
            # We can do this for imported and exported functions, but to have the logic the same for all, it's
            # better to just flatten the kwargs and args into a single set of args and pass into the function
            # prototype defined by an offset.
            _args = self._funcdef.flatten(*args, **kwargs)
            sig = CFUNCTYPE(self._funcdef.restype, *self._funcdef.arg_types)
            binary_base = _internal.BASE_ADDRESS
            # Depending on what kind of function we are calling, we change how we find the offset of the func.
            offset = None
            if self._offset is not None:
                offset = binary_base + self._offset
            elif self._signature is not None:
                rel_offset = find_pattern_in_binary(self._signature, False, _internal.EXE_NAME)
                if rel_offset is not None and isinstance(rel_offset, int):
                    offset = binary_base + rel_offset
            elif self._exported_name is not None:
                own_dll = ctypes.WinDLL(_internal.BINARY_PATH)
                func_ptr = getattr(own_dll, self._exported_name)
                offset = ctypes.cast(func_ptr, ctypes.c_void_p).value
            # Finally, call the function.
            if offset is not None:
                cfunc = sig(offset)
                try:
                    val = cfunc(*_args)
                except ctypes.ArgumentError:
                    logger.error(
                        f"{self._func.__qualname__!r} has function signature {self._funcdef.arg_types} "
                        f"but was called with {_args}"
                    )
                    raise
                return val
            else:
                logger.error(f"Unable to call {self._func.__qualname__!r} - Cannot find function.")
        except Exception:
            logger.exception(f"There was an exception calling {self._func.__qualname__!r}")
            return None

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Optional[R]:
        # This initial check is to check if the first argument was a function.
        # This will only happen if the function is being used as a decorator.
        # if this check fails, then we are calling the function under "normal" usage.
        if args and inspect.isfunction(args[0]):
            # In this case the decorator was used without a .before or .after -> raise error
            raise ValueError(
                f"Hook for detour {self._func.__qualname__!r} must be specified as either `before` or `after`"
            )

        if self._is_static:
            # For a static method, we don't need to worry about any binding, we can just call it with the
            # provided arguments.
            return self._call(*args, **kwargs)
        else:
            # For a non-static method, we need to do more work since we need to get the instance the method is
            # bound to, and then get the address of it and pass it in as the first argument.
            if self._bound_class is not None:
                try:
                    if self.this_is_pointer:
                        return self._call(ctypes.byref(self._bound_class), *args, **kwargs)
                    else:
                        # If it's not a pointer, then we'll assume it's an int and pass the address...
                        return self._call(ctypes.addressof(self._bound_class), *args, **kwargs)
                except Exception:
                    logger.exception(f"Failed to call {self._func.__qualname__} with args {args}")
            else:
                raise ValueError("Not bound to anything...")

    def _decorate_detour(self, detour, hook_time: Optional[DetourTime] = None) -> HookProtocol:
        if hook_time is None:
            raise ValueError(
                f"Hook for detour {detour.__qualname__!r} must be specified as either `before` or `after`"
            )

        self._funcdef = _get_funcdef(self._func)

        setattr(detour, "_is_funchook", True)
        setattr(detour, "_hook_time", hook_time)
        if self._exported_name is None:
            setattr(detour, "_hook_func_name", self._func.__qualname__)
        else:
            setattr(detour, "_hook_func_name", self._exported_name)
        if self._imported_name is not None:
            split_name = self._imported_name.split(".", maxsplit=1)
            if len(split_name) != 2:
                raise ValueError(
                    f"imported name {self._imported_name!r} is invalid. Please ensure it has the following "
                    "structure: dll_name.dll_function"
                )
            dll_name, function_name = split_name
            setattr(detour, "_dll_name", dll_name)
            setattr(detour, "_is_imported_func_hook", True)
            setattr(detour, "_hook_func_name", function_name)
        else:
            setattr(detour, "_is_imported_func_hook", False)
            setattr(detour, "_dll_name", None)
        setattr(detour, "_hook_func_def", self._funcdef.to_FUNCDEF())
        setattr(detour, "_hook_offset", self._offset)
        setattr(detour, "_hook_pattern", self._signature)
        setattr(detour, "_is_manual_hook", False)
        setattr(detour, "_is_exported_func_hook", self._exported_name is not None)
        setattr(detour, "_has__result_", False)
        setattr(detour, "_noop", False)
        setattr(detour, "_func_overload", self._overload_id)
        return detour

    def after(self, detour: Callable) -> HookProtocol:
        """Mark the detour as running after the original function."""
        decorated_detour = self._decorate_detour(detour, DetourTime.AFTER)
        if "_result_" in inspect.signature(detour).parameters.keys():
            setattr(detour, "_has__result_", True)
        return decorated_detour

    def before(self, detour: Callable) -> HookProtocol:
        """Mark the detour as running before the original function."""
        decorated_detour = self._decorate_detour(detour, DetourTime.BEFORE)
        return decorated_detour

    def overload(self, overload_id: str) -> Self:
        """Get an instance of the class which corresponds to the specified overload id.
        This overload id should be provided as the ``overload_id`` argument for ``function_hook``"""
        if overload_id == self._overload_id:
            return self
        else:
            fh = _FunctionHook_overloads.get(self._func.__qualname__, {}).get(overload_id, None)
            if fh is not None:
                return fh
            else:
                raise ValueError(f"Unknown overload {overload_id!r} for {self._func.__qualname__}")


class _function_hook:
    def __init__(
        self,
        signature: Optional[str] = None,
        offset: Optional[int] = None,
        exported_name: Optional[str] = None,
        imported_name: Optional[str] = None,
        overload_id: Optional[str] = None,
    ):
        self.signature = signature
        self.offset = offset
        self.exported_name = exported_name
        self.imported_name = imported_name
        self.overload_id = overload_id


class static_function_hook(_function_hook):
    """Mark the decorated function as a static function hook.

    .. note::
        Only of the arguments of this function is required.
        The order the arguments are respected is ``signature``, ``offset``, then ``exported_name``.

    .. note::
        You do not need to apply the ``@staticmethod`` decorator to functions if you use this decorator,
        however your static type checker may complain, so this decorator is safe to apply on top of the
        ``@staticmethod`` decorator.

    Parameters
    ----------
    signature:
        A string representing the bytes which can be used to uniquely find the function within the binary.
    offset:
        The relative offset within the binary where the start of the function can be found.
    exported_name:
        The name of the exported function which is to be hooked.

        .. note::
            It is recommended that the function name is the "mangled" version.
            Ie. do not "demangle" the function name.

    imported_name:
        The full name of the function within the imported dll to be hooked. For example, this could be
        ``"Kernel32.ReadFile"``.
    overload_id:
        A unique name within each set of overloaded functions which can be used to identify the overload for
        calling and hooking purposes.
    """

    def __call__(self, func: Callable[P, R]) -> FunctionHook[P, R]:
        if not self.signature and not self.offset and not self.exported_name and not self.imported_name:
            raise ValueError(
                f"One of the `function_hook` arguments must be provided for {func.__qualname__!r}"
            )
        # Pass the function in directly so that we may defer the usage of inspect until the actual decorator
        # is called.
        # This will mean that only functions which are used are inspected which will massively reduce the
        # amount of work required.
        if isinstance(func, staticmethod):
            # Unwrap the static method to get the underlying function since staticmethods aren't callable
            # cf. https://bugs.python.org/issue20309
            func = func.__func__
        return FunctionHook[P, R](
            func,
            self.signature,
            self.offset,
            self.exported_name,
            self.imported_name,
            is_static=True,
        )


class function_hook(_function_hook):
    """Mark the decorated function as a function hook.

    .. note::
        Only of the arguments of this function is required.
        The order the arguments are respected is ``signature``, ``offset``, then ``exported_name``.

    .. important::
        This decorator must only be applied to non-static methods.
        This means that the first two arguments MUST be `self` (the usual python one), and `this` (the c
        one.)
        Because of how this decorator works, the function arguments will be determined from all the
        arguments proceeding these two mandatory ones.

    .. important::
        For this decorator to work, the class the method belongs to MUST be a
        :class:`~pymhf.core.hooking.Structure` instead of the usual `ctypes.Structure`.

    Parameters
    ----------
    signature:
        A string representing the bytes which can be used to uniquely find the function within the binary.
    offset:
        The relative offset within the binary where the start of the function can be found.
    exported_name:
        The name of the exported function which is to be hooked.

        .. note::
            It is recommended that the function name is the "mangled" version.
            Ie. do not "demangle" the function name.

    imported_name:
        The full name of the function within the imported dll to be hooked. For example, this could be
        ``"Kernel32.ReadFile"``.
    overload_id:
        A unique name within each set of overloaded functions which can be used to identify the overload for
        calling and hooking purposes.
    """

    def __call__(self, func: Callable[Concatenate[S, THIS, P], R]) -> FunctionHook[P, R]:
        if not self.signature and not self.offset and not self.exported_name and not self.imported_name:
            raise ValueError(
                f"One of the `function_hook` arguments must be provided for {func.__qualname__!r}"
            )
        # Pass the function in directly so that we may defer the usage of inspect until the actual decorator
        # is called.
        # This will mean that only functions which are used are inspected which will massively reduce the
        # amount of work required.
        fh = FunctionHook[P, R](
            func,
            self.signature,
            self.offset,
            self.exported_name,
            self.imported_name,
            self.overload_id,
            is_static=False,
        )
        _FunctionHook_overloads[func.__qualname__][self.overload_id] = fh
        return fh


hook_manager = HookManager()
