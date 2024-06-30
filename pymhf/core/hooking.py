import ast
from collections.abc import Callable
from ctypes import CFUNCTYPE
from _ctypes import CFuncPtr
from functools import wraps, partial
import inspect
import logging
from typing import Any, Optional, Type
import traceback

import cyminhook

import pymhf.core._internal as _internal
from pymhf.core.module_data import module_data
from pymhf.core.errors import UnknownFunctionError
from pymhf.core.memutils import find_bytes
from pymhf.core._types import FUNCDEF, DetourTime, HookProtocol
from pymhf.core.caching import function_cache, pattern_cache

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
        call_func: Optional[FUNCDEF] = None,
        overload: Optional[str] = None,
    ):
        self._offset = offset
        self._call_func = call_func
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
            # This is a "manual" hook, insofar as the offset and function
            # argument info is all provided manually.
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
        hook_logger.info(f"Initialized hook for function {self._name}")

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
                    hook_logger.info(detour_list)
                    detour(*args)
                    self._disabled_detours.append(detour)
                    detour_list.remove(self._oneshot_detours[detour])
                except:
                    hook_logger.exception(traceback.format_exc())
            self._oneshot_detours[detour] = _one_shot
            detour_list.append(_one_shot)

    def remove_detour(self, detour: Callable[..., Any]):
        """ Remove the provided detour from this FuncHook. """
        # Determine the detour list to use. If none, then return.
        if (detour_list := self._determine_detour_list(detour)) is None:
            hook_logger.info("Nothing to do!")
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
        if not self._should_enable:
            hook_logger.info(f"No need to enable {self._name}")
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

    def _oneshot_detour(self, *args):
        ret = self._non_oneshot_detour(*args)
        self.disable()
        hook_logger.debug(f"Disabling a one-shot hook ({self._name})")
        return ret

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
        for func in self._after_detours:
            func(*args)
        for func in self._after_detours_with_results:
            func(*args, _result_=result)

    def close(self):
        super().close()
        self.state = "closed"

    def enable(self):
        super().enable()
        self.state = "enabled"
        # self._should_enable = True

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
    def _set_detour_as_funchook(detour: Callable[..., Any], cls: Optional["HookFactory"] = None, detour_name: Optional[str] = None):
        """ Set all the standard attributes required for a function hook. """
        setattr(detour, "_is_funchook", True)
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


def hook_function_manual(
    detour: Callable[..., Any],
    name: str,
    offset: int,
    restype,
    argtypes: list,
):
    HookFactory._set_detour_as_funchook(detour, None, name)
    # TODO: Lots of work to be done here. Need to wrap this in an extra function
    # since the outer one needs to take the arguments and the inner one just the
    # function which takes `detour`.


def disable(obj):
    """
    Disable the current function or class.
    """
    obj._disabled = True
    return obj


def one_shot(func: Callable[..., Any]):
    func._is_one_shot = True
    return func


def on_key_pressed(event: str):
    def wrapped(func):
        func._hotkey = event
        func._hotkey_press = "down"
        return func
    return wrapped


def on_key_release(event: str):
    def wrapped(func):
        func._hotkey = event
        func._hotkey_press = "up"
        return func
    return wrapped


# TODO: Rework/move this functionality into `hook_function` as that name is
# better for this.
# This function should basically allow inline/dynamic/runtime hooking of
# functions. We want to use the current mechanism for registering hooks so that
# this plays well with everything else that currently exists.
def manual_hook(
    name: str,
    offset: int,
    func_def: FUNCDEF,
):
    def _hook_function(detour):
        should_enable = getattr(detour, "_should_enable", True)
        return FuncHook(
            detour,
            name=name,
            detour_time=DetourTime.AFTER,
            should_enable=should_enable,
            offset=offset,
            call_func=func_def,
        )
    return _hook_function


def hook_function(
    function_name: str,
    *,
    offset: Optional[int] = None,
    pattern: Optional[str] = None
):
    """ Specify parameters for the function to hook.

    Parameters
    ----------
    function_name:
        The name of the function to hook. This will be looked up against the
        known functions for the game and hooked if found.
    offset:
        The offset relative to the base address of the exe where the function
        starts.
        NOTE: Currently doesn't work.
    pattern:
        A byte pattern in the form `"AB CD ?? EF ..."`
        This will be the same pattern as used by IDA and cheat engine.
        NOTE: Currently doesn't work.
    """
    def _hook_function(klass: FuncHook):
        klass._pattern = None
        klass.target = 0
        if not offset and not pattern:
            if function_name in module_data.FUNC_OFFSETS:
                klass.target = _internal.BASE_ADDRESS + module_data.FUNC_OFFSETS[function_name]
            else:
                raise UnknownFunctionError(f"{function_name} has no known address")
        else:
            if pattern:
                klass._pattern = pattern
        if function_name in module_data.FUNC_CALL_SIGS:
            signature = module_data.FUNC_CALL_SIGS[function_name]
        else:
            raise UnknownFunctionError(f"{function_name} has no known call signature")
        klass.signature = signature
        klass._name = function_name
        return klass
    return _hook_function


class HookManager():
    def __init__(self):
        self.hooks: dict[str, FuncHook] = {}
        # Keep a mapping of any hooks that try to be registered but fail.
        # These hooks will not be instances of classes, but the class type.
        self.failed_hooks: dict[str, Type[FuncHook]] = {}
        # A mapping of the custom event hooks which can be registered by modules
        # for individual mods.
        self.callback_funcs: dict[str, set[Callable]] = {}
        self.hook_registry: dict[Callable, FuncHook] = {}

    def resolve_dependencies(self):
        """ Resolve dependencies of hooks.
        This will get all the functions which are to be hooked and construct
        compound hooks as required."""
        # TODO: Make work.
        pass

    def add_custom_callbacks(self, callbacks: dict[str, set[Callable]]):
        """ Add the provided function to the specified callback type. """
        for cb_type, funcs in callbacks.items():
            if cb_type not in self.callback_funcs:
                self.callback_funcs[cb_type] = funcs
            else:
                self.callback_funcs[cb_type].update(funcs)

    def remove_custom_callbacks(self, callbacks: dict[str, set[Callable]]):
        # Remove the values in the list which correspond to the data in `callbacks`
        for cb_type, funcs in callbacks.items():
            if cb_type in self.callback_funcs:
                # Remove the functions from the set and then check whether it's
                # empty.
                self.callback_funcs[cb_type].difference_update(funcs)
                if not self.callback_funcs[cb_type]:
                    del self.callback_funcs[cb_type]

    def register_hook(self, hook: HookProtocol):
        hook_func_name = hook._hook_func_name
        if hook_func_name not in self.hooks:
            self.hooks[hook_func_name] = FuncHook(hook_func_name)
        self.hooks[hook_func_name].add_detour(hook)
        self.hook_registry[hook] = self.hooks[hook_func_name]

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

    def enable_all(self):
        for func_name, hook in self.hooks.items():
            try:
                hook.enable()
                hook_logger.info(f"Enabled hook for {func_name}")
            except:
                hook_logger.error(f"Unable to enable {func_name} because:")
                hook_logger.exception(traceback.format_exc())


hook_manager = HookManager()
