import ast
from collections.abc import Callable
from ctypes import CFUNCTYPE
from _ctypes import CFuncPtr
from functools import partial
import inspect
import logging
from typing import Any, Optional, Type, cast
import traceback

import cyminhook

import pymhf.core._internal as _internal
from pymhf.core.module_data import module_data
# from pymhf.core.errors import UnknownFunctionError
from pymhf.core.memutils import find_pattern_in_binary
from pymhf.core._types import FUNCDEF, DetourTime, HookProtocol, ManualHookProtocol
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


ORIGINAL_MAPPING = dict()

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
    _call_func: Optional[FUNCDEF]

    def __init__(
        self,
        detour_name: str,
        *,
        offset: Optional[int] = None,
        pattern: Optional[int] = None,
        call_func: Optional[FUNCDEF] = None,
        overload: Optional[str] = None,
        binary: Optional[str] = None,
    ):
        self._offset = offset
        self._pattern = pattern
        self._call_func = call_func
        self._binary = binary
        # TODO: This probably needs to be a dictionary so that we may add and
        # remove function hooks without duplication and allow lookup based on
        # name. Name will probably have to be be mod class name . func name.
        self._before_detours: list[HookProtocol] = []
        self._after_detours: list[HookProtocol] = []
        self._after_detours_with_results: list[HookProtocol] = []
        # Disabled detours will go here. This will include hooks disabled by the
        # @disable decorator, as well as hooks which are one-shots and have been
        # run.
        self._disabled_detours: list[HookProtocol] = []
        self._oneshot_detours: dict[HookProtocol, HookProtocol] = {}
        self.overload = overload
        self.state = None
        self._name = detour_name
        self._initialised = False

    def _init(self):
        """ Actually initialise all the data. This is defined separately so that
        any function which is marked with @disable doesn't get initialised. """

        # First, let's see if we have a pattern and no offset. If so we need to find our offset.
        if self._pattern is not None and self._offset is None:
            # Lookup the pattern in the pattern cache. If that fails find it in the binary.
            if (offset := pattern_cache.get(self._pattern)) is None:
                offset = find_pattern_in_binary(self._pattern, False, self._binary)
            if offset is not None:
                self._offset = offset
                hook_logger.debug(f"Found {self._pattern} at 0x{offset:X}")
            else:
                hook_logger.error(f"Could not find pattern {self._pattern}...")
                self._invalid = True
                return

        if not self._offset and not self._call_func:
            _offset = module_data.FUNC_OFFSETS.get(self._name)
            if _offset is not None:
                if isinstance(_offset, int):
                    self.target = _internal.BASE_ADDRESS + _offset
                else:
                    # This is an overload
                    if self.overload is not None:
                        self.target = _internal.BASE_ADDRESS + _offset[self.overload]
                    else:
                        # Need to fallback on something. Raise a warning that no
                        # overload was defined and that it will fallback to the
                        # first entry in the dict.
                        first = list(_offset.items())[0]
                        hook_logger.warning(
                            f"No overload was provided for {self._name}. "
                        )
                        hook_logger.warning(
                            f"Falling back to the first overload ({first[0]})")
                        self.target = _internal.BASE_ADDRESS + first[1]
            else:
                hook_logger.error(f"{self._name} has no known address (base: 0x{_internal.BASE_ADDRESS:X})")
                self._invalid = True
        else:
            # This is a "manual" hook, insofar as the offset and function argument info is all provided
            # manually.
            if not self._offset and self._call_func:
                raise ValueError("Both offset and call_func MUST be provided if defining hooks manually")
            self.target = _internal.BASE_ADDRESS + self._offset
            self.signature = CFUNCTYPE(self._call_func.restype, *self._call_func.argtypes)
            self._initialised = True
            return
        if (sig := module_data.FUNC_CALL_SIGS.get(self._name)) is not None:
            if isinstance(sig, FUNCDEF):
                self.signature = CFUNCTYPE(sig.restype, *sig.argtypes)
                hook_logger.debug(f"Function {self._name} return type: {sig.restype} args: {sig.argtypes}")
                if self.overload is not None:
                    hook_logger.warning(
                        f"An overload was provided for {self._name} but no overloaded"
                         " function definitions exist. This function may fail."
                    )
            else:
                # Look up the overload:
                if (osig := sig.get(self.overload)) is not None:  # type: ignore
                    self.signature = CFUNCTYPE(osig.restype, *osig.argtypes)
                    hook_logger.debug(f"Function {self._name} return type: {osig.restype} args: {osig.argtypes}")
                else:
                    # Need to fallback on something. Raise a warning that no
                    # overload was defined and that it will fallback to the
                    # first entry in the dict.
                    first = list(sig.items())[0]
                    hook_logger.warning(
                        f"No function arguments overload was provided for {self._name}. "
                    )
                    hook_logger.warning(
                        f"Falling back to the first overload ({first[0]})")
                    self.signature = CFUNCTYPE(first[1].restype, *first[1].argtypes)
        else:
            hook_logger.error(f"{self._name} has no known call signature")
            self._invalid = True
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
        """ Add the provided detour to this FuncHook. """
        # If the hook has the `_disabled` attribute, then don't add the detour.
        if getattr(detour, "_disabled", False):
            self._disabled_detours.append(detour)
            return

        # Determine the detour list to use. If none, then return.
        if (detour_list := self._determine_detour_list(detour)) is None:
            hook_logger.error(f"Unable to assign {detour} to a detour type. Please check it. It has not been added.")
            return

        if not getattr(detour, "_is_one_shot", False):
            # If we aren't a one-shot detour, then add it to the list.
            detour_list.append(detour)

        # If the hook is a one-shot, wrap it so that it can remove itself once
        # it's executed.
        if getattr(detour, "_is_one_shot", False):
            def _one_shot(*args, detour=detour, detour_list=detour_list):
                try:
                    detour(*args)
                    self._disabled_detours.append(detour)
                    detour_list.remove(self._oneshot_detours[detour])
                except:
                    hook_logger.exception(traceback.format_exc())
            self._oneshot_detours[detour] = _one_shot
            detour_list.append(_one_shot)

    def remove_detour(self, detour: HookProtocol):
        """ Remove the provided detour from this FuncHook. """
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
            len(self._before_detours) > 0 or
            len(self._after_detours) > 0 or
            len(self._after_detours_with_results)
        )

    def bind(self) -> bool:
        """ Actually initialise the base class. Returns whether the hook is bound. """
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
        ORIGINAL_MAPPING[self._name] = self.original
        self.state = "initialized"
        return True

    def __call__(self, *args, **kwargs):
        return self.detour(*args, **kwargs)

    def __get__(self, instance, owner=None):
        # Pass the instance through to the __call__ function so that we can use
        # this decorator on a method of a class.
        return partial(self.__call__, instance)

    def _compound_detour(self, *args):
        ret = None
        # Loop over the before detours, keeping the last none-None return value.
        for func in self._before_detours:
            r = func(*args)
            if r is not None:
                ret = r
        # If we get a return value that is not None, then pass it through.
        if ret is not None:
            result = self.original(*ret)
        else:
            result = self.original(*args)

        # Now loop over the after functions. We'll need to handle the cases of
        # functions which take the `_result_` kwarg, and those that don't.
        after_ret = None
        for func in self._after_detours:
            after_ret = func(*args)
        for func in self._after_detours_with_results:
            after_ret = func(*args, _result_=result)

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
    def offset(self):
        return self.target - _internal.BASE_ADDRESS


class HookFactory:
    _name: str
    _templates: Optional[tuple[str]] = None
    _overload: Optional[str] = None

    @classmethod
    def overload(cls, overload_args):
        # TODO: Improve type hinting and possible make this have a generic arg
        # arg type to simplify the logic...
        raise NotImplementedError

    @classmethod
    def original(cls, *args):
        """ Call the original function with the given arguments. """
        return ORIGINAL_MAPPING[cls._name](*args)

    @staticmethod
    def _set_detour_as_funchook(
        detour: Callable[..., Any],
        cls: Optional["HookFactory"] = None,
        detour_name: Optional[str] = None
    ):
        """ Set all the standard attributes required for a function hook. """
        setattr(detour, "_is_funchook", True)
        setattr(detour, "_is_manual_hook", False)
        setattr(detour, "_has__result_", False)
        if cls and hasattr(cls, "_name"):
            setattr(detour, "_hook_func_name", cls._name)
        else:
            if detour_name is None:
                raise ValueError("class used as detour must have a name")
            else:
                setattr(detour, "_hook_func_name", detour_name)

    @classmethod
    def after(cls, detour: Callable[..., Any]) -> HookProtocol:
        HookFactory._set_detour_as_funchook(detour, cls)
        setattr(detour, "_hook_time", DetourTime.AFTER)
        if "_result_" in inspect.signature(detour).parameters.keys():
            setattr(detour, "_has__result_", True)
        return detour

    @classmethod
    def before(cls, detour: Callable[..., Any]) -> HookProtocol:
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
    """ Manually hook a function.

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
        if offset is None and pattern is None:
            raise ValueError(f"One of pattern or offset must be set for the manual hook: {detour}")
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


def one_shot(func: Callable[..., Any]) -> HookProtocol:
    setattr(func, "_is_one_shot", True)
    return func


def on_key_pressed(event: str):
    def wrapped(func: Callable[..., Any]) -> HookProtocol:
        setattr(func, "_hotkey", event)
        setattr(func, "_hotkey_press", "down")
        return func
    return wrapped


def on_key_release(event: str):
    def wrapped(func: Callable[..., Any]) -> HookProtocol:
        setattr(func, "_hotkey", event)
        setattr(func, "_hotkey_press", "up")
        return func
    return wrapped


class HookManager():
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
        """ Resolve dependencies of hooks.
        This will get all the functions which are to be hooked and construct
        compound hooks as required."""
        # TODO: Make work.
        pass

    def add_custom_callbacks(self, callbacks: set[HookProtocol]):
        """ Add the provided function to the specified callback type. """
        for cb in callbacks:
            cb_type = cb._custom_trigger
            if cb_type not in self.custom_callbacks:
                self.custom_callbacks[cb_type] = {}
            detour_time = getattr(cb, "_hook_time", DetourTime.NONE)
            if detour_time not in self.custom_callbacks[cb_type]:
                self.custom_callbacks[cb_type][detour_time] = {cb, }
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
        """ Register a hook. There will be on of these for each function which is hooked and each one may
        have multiple methods assigned to it. """
        hook_func_name = hook._hook_func_name
        # Check to see if this function hook name exists within the hook mapping.
        # If it doesn't then we need to initialise the FuncHook and then add the detour to it.
        # If it does then we simply add the detour to it.
        if hook_func_name not in self.hooks:
            # Check to see if it's a manual hook. If so, we initialize the FuncHook object differently.
            if hook._is_manual_hook:
                hook = cast(ManualHookProtocol, hook)
                funcdef = hook._hook_func_def
                if funcdef is None:
                    raise SyntaxError(
                        "When creating a manual hook, the first detour for any given name MUST have a "
                        "func_def argument."
                    )
                self.hooks[hook_func_name] = FuncHook(
                    hook_func_name,
                    offset=hook._hook_offset,
                    pattern=hook._hook_pattern,
                    call_func=funcdef,
                    binary=hook._hook_binary,
                )
            else:
                # TODO: have a way to differentiate the binary here.
                self.hooks[hook_func_name] = FuncHook(hook_func_name)
            self._uninitialized_hooks.add(hook_func_name)
        self.hooks[hook_func_name].add_detour(hook)

    def initialize_hooks(self) -> int:
        """ Initialize any uninitialized hooks.
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
                hook_logger.info(f"Enabled hook for {hook_name}")
            except:
                hook_logger.error(f"Unable to enable {hook_name} because:")
                hook_logger.exception(traceback.format_exc())
        # There are no uninitialized hooks.
        self._uninitialized_hooks = set()
        return count

    def enable(self, func_name: str):
        """ Enable the hook for the provided function name. """
        if hook := self.hooks.get(func_name):
            hook.enable()
            hook_logger.info(f"Enabled hook for function '{func_name}'")
        else:
            hook_logger.error(f"Couldn't enable hook for function '{func_name}'")
            return

    def disable(self, func_name: str):
        """ Disable the hook for the provided function name. """
        if hook := self.hooks.get(func_name):
            hook.disable()
            hook_logger.info(f"Disabled hook for function '{func_name}'")
        else:
            hook_logger.error(f"Couldn't disable hook for function '{func_name}'")
            return

    def debug_show_states(self):
        # Return the states of all the registered hooks
        for func_name, hook in self.hooks.items():
            hook_logger.info(f"Functions registered for {func_name}:")
            if hook._before_detours:
                hook_logger.info(f"  Before Detours:")
                for func in hook._before_detours:
                    hook_logger.info(f"    {func}")
            if hook._after_detours:
                hook_logger.info(f"  After Detours:")
                for func in hook._after_detours:
                    hook_logger.info(f"    {func}")


hook_manager = HookManager()
