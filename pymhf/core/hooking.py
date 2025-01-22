import ast
import ctypes
import inspect
import logging
import traceback
from _ctypes import CFuncPtr
from collections.abc import Callable
from ctypes import CFUNCTYPE
from typing import Any, Optional, Type, cast

import cyminhook

import pymhf.core._internal as _internal
from pymhf.core._types import (
    FUNCDEF,
    DetourTime,
    HookProtocol,
    ImportedHookProtocol,
    KeyPressProtocol,
    ManualHookProtocol,
)
from pymhf.core.memutils import _get_binary_info, find_pattern_in_binary
from pymhf.core.module_data import module_data

# from pymhf.core.caching import function_cache, pattern_cache

hook_logger = logging.getLogger("HookManager")


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


# A VERY rudimentary cache untill we implement gh-2.
pattern_cache: dict[str, int] = {}


# TODO: Move to a different file with `Mod` from mod_loader.py
class FuncHook(cyminhook.MinHook):
    original: Callable[..., Any]
    target: int
    detour: Callable[..., Any]
    signature: CFuncPtr
    _name: str
    _should_enable: bool
    _invalid: bool = False
    _func_def: Optional[FUNCDEF]
    _offset_is_absolute: bool

    def __init__(
        self,
        detour_name: str,
        *,
        offset: Optional[int] = None,
        pattern: Optional[int] = None,
        func_def: Optional[FUNCDEF] = None,
        overload: Optional[str] = None,
        binary: Optional[str] = None,
        offset_is_absolute: bool = False,
    ):
        self._offset_is_absolute = offset_is_absolute
        if self._offset_is_absolute:
            self.target = offset
            self._offset = None
        else:
            self._offset = offset
        self._pattern = pattern
        self._func_def = func_def
        self._binary = binary
        if self._binary is not None:
            if (hm := _get_binary_info(self._binary)) is not None:
                _, module = hm
                self._binary_base = module.lpBaseOfDll
        else:
            self._binary = _internal.EXE_NAME
            self._binary_base = _internal.BASE_ADDRESS

        self._before_detours: list[HookProtocol] = []
        self._after_detours: list[HookProtocol] = []
        self._after_detours_with_results: list[HookProtocol] = []
        # Disabled detours will go here. This will include hooks disabled by the
        # @disable decorator, as well as hooks which are one-shots and have been
        # run.
        self._disabled_detours: set[HookProtocol] = set()
        self._oneshot_detours: dict[HookProtocol, HookProtocol] = {}
        self.overload = overload
        self.state = None
        self._name = detour_name
        self._initialised = False

    @property
    def name(self):
        if self.overload is not None:
            return f"{self._name}({self.overload})"
        else:
            return self._name

    def _init(self):
        """Actually initialise all the data. This is defined separately so that any function which is marked
        with @disable doesn't get initialised.
        """
        offset = None
        # 1. Check to see if an offset is provided. If so, use this as the offset to find the address at.
        if self._offset is not None:
            self.target = self._binary_base + self._offset

        # 2. If there is no offset provided, check to see if a pattern is provided. If so use this to find
        #    the offset.
        elif self._pattern is not None:
            # Lookup the pattern in the pattern cache. If that fails find it in the binary.
            if (offset := pattern_cache.get(self._pattern)) is None:
                offset = find_pattern_in_binary(self._pattern, False, self._binary)
            if offset is not None:
                self._offset = offset
                pattern_cache[self._pattern] = offset
                self.target = self._binary_base + offset
                hook_logger.debug(f"Found {self._pattern} at 0x{offset:X}")
            else:
                hook_logger.error(f"Could not find pattern {self._pattern}... Hook won't be added")
                self._invalid = True
                return

        # 3. If there is still no offset, look up the pattern in the module_data to get offset
        elif (_pattern := module_data.FUNC_PATTERNS.get(self._name)) is not None:
            if isinstance(_pattern, str):
                if (offset := pattern_cache.get(_pattern)) is None:
                    offset = find_pattern_in_binary(_pattern, False, self._binary)
            else:
                if (overload_pattern := _pattern.get(self.overload)) is not None:
                    _pattern = overload_pattern
                    if overload_pattern in pattern_cache:
                        offset = pattern_cache[overload_pattern]
                    else:
                        offset = find_pattern_in_binary(overload_pattern, False, self._binary)
                else:
                    first = list(_pattern.items())[0]
                    _pattern = first
                    hook_logger.warning(f"No overload was provided for {self._name}. ")
                    hook_logger.warning(f"Falling back to the first overload ({first[0]})")
                    offset = find_pattern_in_binary(first[1], False, self._binary)
            if offset is not None:
                self._offset = offset
                pattern_cache[_pattern] = offset
                self.target = self._binary_base + offset
                hook_logger.debug(f"Found {self.name} with pattern {_pattern!r} at 0x{offset:X}")

        # 4. If there is still no offset, look up the offset in the module_data.
        # Note: If this is created by passing in an absolute offset, then the above 3 conditions will fail,
        # but this one will not as self.target will have already been assigned.
        if not self.target:
            _offset = module_data.FUNC_OFFSETS.get(self._name)
            if _offset is not None:
                if isinstance(_offset, int):
                    self.target = self._binary_base + _offset
                else:
                    # This is an overload
                    if (overload_offset := _offset.get(self.overload)) is not None:
                        self.target = self._binary_base + overload_offset
                    else:
                        # Need to fallback on something. Raise a warning that no
                        # overload was defined and that it will fallback to the
                        # first entry in the dict.
                        first = list(_offset.items())[0]
                        hook_logger.warning(f"No overload was provided for {self._name}. ")
                        hook_logger.warning(f"Falling back to the first overload ({first[0]})")
                        self.target = self._binary_base + first[1]
            else:
                hook_logger.error(f"Cannot find the function {self._name} in {_internal.EXE_NAME}")
                self._invalid = True
                return

        # 5. if func_sig is provided, use it, otherwise look it up.
        if self._func_def is not None:
            self.signature = CFUNCTYPE(self._func_def.restype, *self._func_def.argtypes)
        else:
            if (sig := module_data.FUNC_CALL_SIGS.get(self._name)) is not None:
                if isinstance(sig, FUNCDEF):
                    self.signature = CFUNCTYPE(sig.restype, *sig.argtypes)
                    hook_logger.debug(
                        f"Function {self._name} return type: {sig.restype} args: {sig.argtypes}"
                    )
                    if self.overload is not None:
                        hook_logger.warning(
                            f"An overload was provided for {self._name} but no overloaded"
                            " function definitions exist. This function may fail."
                        )
                else:
                    # Look up the overload:
                    if (osig := sig.get(self.overload)) is not None:  # type: ignore
                        self.signature = CFUNCTYPE(osig.restype, *osig.argtypes)
                        hook_logger.debug(
                            f"Function {self._name} return type: {osig.restype} args: {osig.argtypes}"
                        )
                    else:
                        # Need to fallback on something. Raise a warning that no overload was defined and that
                        # it will fallback to the first entry in the dict.
                        first = list(sig.items())[0]
                        hook_logger.warning(f"No function arguments overload was provided for {self._name}. ")
                        hook_logger.warning(f"Falling back to the first overload ({first[0]})")
                        self.signature = CFUNCTYPE(first[1].restype, *first[1].argtypes)
            else:
                hook_logger.error(f"{self._name} has no known call signature")
                self._invalid = True
                return

        self._initialised = True

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
            hook_logger.error(f"Detour {detour} has an invalid detour time: {detour._hook_time}")
        return detour_list

    def add_detour(self, detour: HookProtocol):
        """Add the provided detour to this FuncHook."""
        # If the hook has the `_disabled` attribute, then don't add the detour.
        if getattr(detour, "_disabled", False):
            self._disabled_detours.add(detour)
            return

        # Determine the detour list to use. If none, then return.
        if (detour_list := self._determine_detour_list(detour)) is None:
            hook_logger.error(
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
                    hook_logger.warning(
                        f"Had an issue removing one-shot {detour._hook_func_name} from detour list."
                    )
                except Exception:
                    hook_logger.error(traceback.format_exc())

            self._oneshot_detours[detour] = _one_shot
            detour_list.append(_one_shot)

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
                hook_logger.info(
                    "Hook is already created. This shouldn't be possible. "
                    "Please raise an issue on github..."
                )
            hook_logger.error(f"Failed to initialize hook {self._name} at 0x{self.target:X}")
            hook_logger.error(e)
            hook_logger.error(e.status.name[3:].replace("_", " "))
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
            hook_logger.error(f"There was an error with detour {bad_detour}. It has been disabled.")
            hook_logger.error(traceback.format_exc())
            self._disabled_detours.add(bad_detour)
        # If we get a return value that is not None, then pass it through.
        if ret is not None:
            result = self.original(*ret)
        else:
            result = self.original(*args)

        # Now loop over the after functions. We'll need to handle the cases of
        # functions which take the `_result_` kwarg, and those that don't.
        after_ret = None
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
            hook_logger.error(f"There was an error with detour {bad_detour}. It has been disabled.")
            hook_logger.error(traceback.format_exc())
            self._disabled_detours.add(bad_detour)

        if after_ret is not None:
            return after_ret
        return result

    def close(self):
        super().close()
        self.state = "closed"

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
        setattr(detour, "_has__result_", False)
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


def disable(obj):
    """
    Disable the current function or class.
    """
    setattr(obj, "_disabled", True)
    return obj


def imported(dll_name: str, func_name: str, func_def: FUNCDEF):
    def inner(detour: Callable[..., Any]) -> ImportedHookProtocol:
        HookFactory._set_detour_as_funchook(detour, None, func_name)
        setattr(detour, "_dll_name", dll_name)
        setattr(detour, "_is_imported_func_hook", True)
        setattr(detour, "_hook_func_def", func_def)
        setattr(detour, "_hook_time", DetourTime.AFTER)
        return detour

    return inner


def one_shot(func: HookProtocol) -> HookProtocol:
    """Run this detour once only."""
    setattr(func, "_is_one_shot", True)
    return func


def on_key_pressed(event: str):
    def wrapped(func: Callable[..., Any]) -> KeyPressProtocol:
        setattr(func, "_hotkey", event)
        setattr(func, "_hotkey_press", "down")
        return func

    return wrapped


def on_key_release(event: str):
    def wrapped(func: Callable[..., Any]) -> KeyPressProtocol:
        setattr(func, "_hotkey", event)
        setattr(func, "_hotkey_press", "up")
        return func

    return wrapped


class HookManager:
    def __init__(self):
        self.hooks: dict[str, FuncHook] = {}
        # Keep a mapping of any hooks that try to be registered but fail.
        # These hooks will not be instances of classes, but the class type.
        self.failed_hooks: dict[str, Type[FuncHook]] = {}
        # A mapping of the custom event hooks which can be registered by modules
        # for individual mods.
        self.custom_callbacks: dict[str, dict[DetourTime, set[HookProtocol]]] = {}
        self._uninitialized_hooks: set[str] = set()

    def resolve_dependencies(self):
        """Resolve dependencies of hooks.
        This will get all the functions which are to be hooked and construct
        compound hooks as required.
        """
        # TODO: Make work.
        pass

    def add_custom_callbacks(self, callbacks: set[HookProtocol]):
        """Add the provided function to the specified callback type."""
        for cb in callbacks:
            cb_type = cb._custom_trigger
            if cb_type not in self.custom_callbacks:
                self.custom_callbacks[cb_type] = {}
            detour_time = getattr(cb, "_hook_time", DetourTime.NONE)
            if detour_time not in self.custom_callbacks[cb_type]:
                self.custom_callbacks[cb_type][detour_time] = {
                    cb,
                }
            else:
                self.custom_callbacks[cb_type][detour_time].add(cb)

    def remove_custom_callbacks(self, callbacks: set[HookProtocol]):
        # Remove the values in the list which correspond to the data in `callbacks`
        for cb in callbacks:
            cb_type: str = cb._custom_trigger
            if cb_type in self.custom_callbacks:
                # Remove the functions from the set and then check whether it's
                # empty.
                self.custom_callbacks[cb_type][getattr(cb, "_hook_time", DetourTime.NONE)].discard(cb)
                if all(not x for x in self.custom_callbacks[cb_type].values()):
                    del self.custom_callbacks[cb_type]

    def call_custom_callbacks(self, callback_key: str, detour_time: DetourTime = DetourTime.NONE):
        callbacks = self.custom_callbacks.get(callback_key, {})
        if callbacks:
            for cb in callbacks.get(detour_time, set()):
                cb()

    def register_hook(self, hook: HookProtocol):
        """Register the provided hook."""
        hook_func_name = hook._hook_func_name
        # If the hook has an overload, add it here so that we can disambiguate them.
        if getattr(hook, "_func_overload", None) is not None:
            hook_func_name += f"({hook._func_overload})"
        # Check to see if this function hook name exists within the hook mapping.
        # If it doesn't then we need to initialise the FuncHook and then add the detour to it.
        # If it does then we simply add the detour to it.
        if hook_func_name not in self.hooks:
            # Check to see if it's a manual hook. If so, we initialize the FuncHook object differently.
            if hook._is_manual_hook:
                hook = cast(ManualHookProtocol, hook)
                funcdef = hook._hook_func_def
                if funcdef is None:
                    # If no funcdef is explicitly provided, look and see if we have one defined in the module
                    # data for this function name.
                    funcdef = module_data.FUNC_CALL_SIGS.get(hook_func_name)
                if funcdef is None:
                    raise SyntaxError(
                        "When creating a manual hook, the first detour for any given name MUST have a "
                        "func_def argument."
                    )
                if hook._hook_offset is None and hook._hook_pattern is None:
                    hook_logger.error(
                        f"The manual hook for {hook_func_name} was defined with no offset or pattern. One of"
                        "these is required to register a hook. The hook will not be registered."
                    )
                    return
                binary = hook._hook_binary or module_data.FUNC_BINARY
                self.hooks[hook_func_name] = FuncHook(
                    hook._hook_func_name,
                    offset=hook._hook_offset,
                    pattern=hook._hook_pattern,
                    func_def=funcdef,
                    binary=binary,
                )
            elif hook._is_imported_func_hook:
                hook = cast(ImportedHookProtocol, hook)
                dll_name = hook._dll_name.lower()
                hook_func_name = hook._hook_func_name
                hook_func_def = hook._hook_func_def
                hook_logger.info(
                    f"Trying to load imported hook: {dll_name}.{hook_func_name} with func def: "
                    f"{hook_func_def}"
                )
                if (dll_func_ptrs := _internal.imports.get(dll_name)) is not None:
                    func_ptr = dll_func_ptrs.get(hook_func_name)
                    # For now, cast the func_ptr object back to the target location in memory.
                    # This is wasteful, but simple for now for testing...
                    hook_logger.debug(func_ptr)
                    target = ctypes.cast(func_ptr, ctypes.c_void_p).value
                    hook_logger.info(f"{func_ptr} points to 0x{target:X}")
                    self.hooks[hook_func_name] = FuncHook(
                        hook._hook_func_name,
                        offset=target,
                        func_def=hook_func_def,
                        offset_is_absolute=True,
                    )
                else:
                    hook_logger.error(f"Cannot find {dll_name} in the import list")
            else:
                # TODO: have a way to differentiate the binary here.
                self.hooks[hook_func_name] = FuncHook(
                    hook._hook_func_name,
                    overload=getattr(hook, "_func_overload", None),
                )
            self._uninitialized_hooks.add(hook_func_name)
        self.hooks[hook_func_name].add_detour(hook)

    def initialize_hooks(self) -> int:
        """Initialize any uninitialized hooks.
        This will also enable the hooks so that they become active.
        """
        count = 0
        for hook_name in self._uninitialized_hooks:
            hook = self.hooks[hook_name]
            hook._init()
            bound = hook.bind()
            if bound:
                count += 1
            else:
                # If the mod didn't get bound, we don't try and enable it!
                continue
            # Try and enable the hook.
            try:
                hook.enable()
                if hook._offset_is_absolute:
                    offset = hook.target
                    prefix = ""
                else:
                    offset = hook.offset
                    prefix = f"{hook._binary}+"
                hook_logger.info(f"Enabled hook for {hook_name} at {prefix}0x{offset:X}")
            except Exception:
                hook_logger.error(f"Unable to enable {hook_name} because:")
                hook_logger.error(traceback.format_exc())
        # There are no uninitialized hooks.
        self._uninitialized_hooks = set()
        return count

    def enable(self, func_name: str):
        """Enable the hook for the provided function name."""
        if hook := self.hooks.get(func_name):
            hook.enable()
            hook_logger.info(f"Enabled hook for function '{func_name}'")
        else:
            hook_logger.error(f"Couldn't enable hook for function '{func_name}'")
            return

    def disable(self, func_name: str):
        """Disable the hook for the provided function name."""
        if hook := self.hooks.get(func_name):
            hook.disable()
            hook_logger.info(f"Disabled hook for function '{func_name}'")
        else:
            hook_logger.error(f"Couldn't disable hook for function '{func_name}'")
            return

    def _debug_show_states(self):
        # Return the states of all the registered hooks
        for func_name, hook in self.hooks.items():
            hook_logger.info(f"Functions registered for {func_name}:")
            if hook._before_detours:
                hook_logger.info("  Before Detours:")
                for func in hook._before_detours:
                    hook_logger.info(f"    {func}")
            if hook._after_detours:
                hook_logger.info("  After Detours:")
                for func in hook._after_detours:
                    hook_logger.info(f"    {func}")


hook_manager = HookManager()
