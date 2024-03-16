import ast
from collections.abc import Callable
from ctypes import CFUNCTYPE
from _ctypes import CFuncPtr
from enum import Enum
from functools import wraps, update_wrapper, partial
import inspect
import logging
from typing import Any, Optional, Type, Union
import traceback

import cyminhook

import pymhf.core._internal as _internal
from pymhf.core.module_data import module_data
from pymhf.core.errors import UnknownFunctionError
from pymhf.core.memutils import find_bytes
from pymhf.core._types import FUNCDEF
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


class DetourTime(Enum):
    NONE = 0
    BEFORE = 1
    AFTER = 2


ORIGINAL_MAPPING = dict()


class FuncHook(cyminhook.MinHook):
    original: Callable[..., Any]
    target: int
    detour: Callable[..., Any]
    signature: CFuncPtr
    _name: str
    _should_enable: bool
    _invalid: bool = False
    _call_func: Optional[FUNCDEF]
    _is_one_shot: bool = False

    def __init__(
        self,
        detour: Callable[..., Any],
        *,
        name: Optional[str] = None,
        offset: Optional[int] = None,
        call_func: Optional[FUNCDEF] = None,
        detour_time: DetourTime = DetourTime.NONE,
        overload: Optional[str] = None,
        should_enable: bool = True,
    ):
        self._mod = None
        self._should_enable = should_enable
        self._offset = offset
        self._call_func = call_func
        # TODO: This probably needs to be a dictionary so that we may add and
        # remove function hooks without duplication and allow lookup based on
        # name. Name will probably have to be be mod class name . func name.
        self._before_detours = []
        self._after_detours = []
        self._after_detours_with_results = []
        if detour_time == DetourTime.BEFORE:
            self._before_detours.append(detour)
        elif detour_time == DetourTime.AFTER:
            self._after_detours.append(detour)
        self._original_detour = detour
        self.detour_time = detour_time
        self.overload = overload
        self.state = None
        if name is not None:
            self._name = name
        else:
            raise ValueError(
                "name cannot be none. This should only happen if this class was"
                " instantiated manually which you should NOT be doing."
            )
        self._initialised = False
        if self._should_enable:
            self._init()

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

    def add_detour(
        self,
        detour: Callable[..., Any],
        detour_time: DetourTime = DetourTime.NONE
    ):
        # TODO: Handle one-shot detours too...
        """ Add the provided detour to this FuncHook. """
        if detour_time == DetourTime.BEFORE:
            self._before_detours.append(detour)
        elif detour_time == DetourTime.AFTER:
            # For an "after" hook, we need to determine if "_result_" is in the
            # function arguments.
            func_sig = inspect.signature(detour)
            if "_result_" in func_sig.parameters.keys():
                self._after_detours_with_results.append(detour)
            else:
                self._after_detours.append(detour)

    def bind(self, cls = None) -> bool:
        # TODO: Change how this binding works. We need to iterate over the before
        # and after hooks and then create a function which will run them
        # appropriately.
        """ Actually initialise the base class. Returns whether the hook is bound. """
        # Associate the mod now whether or not we get one. This way if the
        # function is actually disabled, we may enable it later with no issues.
        self._mod = cls
        if not self._should_enable:
            return False

        # TODO: Apply this logic to the detour funcs...
        if cls is not None:
            self._detour_func = partial(self._original_detour, cls)
        else:
            self._detour_func = self._original_detour

        # Check the detour time and create an approriately "wrapped" function
        # which will run instead of the original function.
        if self.detour_time == DetourTime.BEFORE:
            self.detour = self._before_detour
        elif self.detour_time == DetourTime.AFTER:
            # For an "after" hook, we need to determine if "_result_" is in the
            # function arguments.
            func_sig = inspect.signature(self._original_detour)
            if "_result_" in func_sig.parameters.keys():
                self.detour = self._after_detour_with_return
            else:
                self.detour = self._after_detour
        else:
            self.detour = self._normal_detour

        # Check to see if it's a one shot and wrap this detour one more to be
        # one-shot.
        if self._is_one_shot:
            self._non_oneshot_detour = self.detour
            self.detour = self._oneshot_detour

        try:
            super().__init__(signature=self.signature, target=self.target)
        except cyminhook._cyminhook.Error as e:  # type: ignore
            if e.status == cyminhook._cyminhook.Status.MH_ERROR_ALREADY_CREATED:
                # In this case, we'll get the already created hook, and add it
                # to a list so that we can construct a compound hook.
                hook_logger.info("ALREADY CREATED!!!")
            hook_logger.error(f"Failed to initialize hook {self._name}")
            hook_logger.error(e)
            hook_logger.error(e.status.name[3:].replace("_", " "))
            self.state = "failed"
            return False
        ORIGINAL_MAPPING[self._name] = self.original
        self.state = "initialized"
        if not hasattr(self, "_should_enable"):
            self._should_enable = True
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
            return self.original(*ret)
        else:
            return self.original(*args)

        # Now loop over the after functions. We'll need to handle the cases of
        # functions which take the `_result_` kwarg, and those that don't.
        pass

    def _normal_detour(self, *args):
        # Run a detour as provided by the user.
        return self._detour_func(*args)

    def _before_detour(self, *args):
        # A detour to be run instead of the normal one when we are registered as
        # a "before" hook.
        ret = self._detour_func(*args)
        # If we get a return value that is not None, then pass it through.
        if ret is not None:
            return self.original(*ret)
        else:
            return self.original(*args)

    def _after_detour(self, *args):
        # Detour which will be run instead of the normal one.
        # The original function will be run before.
        ret = self.original(*args)
        self._detour_func(*args)
        return ret

    def _after_detour_with_return(self, *args):
        # Detour which will be run instead of the normal one.
        # The original function will be run before.
        # The return value of the original function will be passed in.
        ret = self.original(*args)
        new_ret = self._detour_func(*args, _result_=ret)
        if new_ret is not None:
            return new_ret
        return ret

    def close(self):
        super().close()
        self.state = "closed"

    def enable(self):
        super().enable()
        self.state = "enabled"
        self._should_enable = True

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

    def __init__(self, func):
        self.func = func
        self._after = False
        self._before = False
        update_wrapper(self, func)

    def __new__(
            cls,
            detour: Callable[..., Any],
            detour_time: DetourTime = DetourTime.NONE
    ) -> FuncHook:
        should_enable = getattr(detour, "_should_enable", True)
        f = FuncHook(
            detour,
            name=cls._name,
            detour_time=detour_time,
            overload=cls._overload,
            should_enable=should_enable,
        )
        f._fake_thing = f"Generating function hook for {detour}"
        return f

    def __class_getitem__(cls: type["HookFactory"], key: Union[tuple[Any], Any]):
        """ Create a new instance of the class with the data in the _templates
        field used to generate the correct _name property based on the type
        pass in to the __getitem__ lookup."""
        if cls._templates is not None and cls._name is not None:
            if isinstance(key, tuple):
                fmt_key = dict(zip(cls._templates, [x.__name__ for x in key]))
            else:
                fmt_key = {cls._templates[0]: key.__name__}
            cls._name = cls._name.format(**fmt_key)
        return cls

    @classmethod
    def overload(cls, overload_args):
        # TODO: Improve type hinting and possible make this have a generic arg
        # arg type to simplify the logic...
        raise NotImplementedError

    @classmethod
    def original(cls, *args):
        """ Call the original function with the given arguments. """
        return ORIGINAL_MAPPING[cls._name](*args)

    @classmethod
    def before(cls, detour: Callable[..., Any]) -> FuncHook:
        """
        Run the decorated function before the original function is run.
        This function in general should not call the original function, and does
        not need to return anything.
        If you wish to modify the values being passed into the original
        function, return a tuple which has values in the same order as the
        original function.
        """
        should_enable = getattr(detour, "_should_enable", True)
        # Check to see if this class has any functions associated with it
        # already.
        # If so, then we will get the existing `FuncHook` instance, add this
        # detour to it, and then return it.
        hook_logger.info(cls)
        if hasattr(cls, "_func_hook"):
            funcHook: FuncHook = cls._func_hook.func.__self__
            hook_logger.info(f"funchook: {funcHook}")
            funcHook.add_detour(detour, DetourTime.BEFORE)
            return funcHook
        else:
            f = FuncHook(
            detour,
            name=cls._name,
            detour_time=DetourTime.BEFORE,
            overload=cls._overload,
            should_enable=should_enable,
        )
            setattr(cls, "_func_hook", f)
            return f

    @classmethod
    def after(cls, detour: Callable[..., Any]) -> FuncHook:
        """ Mark the hook to be only run after the original function.
        This function may have the keyword argument `_result_`. If it does, then
        this value will be the result of the call of the original function
        """
        should_enable = getattr(detour, "_should_enable", True)
        # Check to see if this class has any functions associated with it
        # already.
        # If so, then we will get the existing `FuncHook` instance, add this
        # detour to it, and then return it.
        hook_logger.info(cls)
        if hasattr(cls, "_func_hook"):
            funcHook: FuncHook = cls._func_hook.func.__self__
            hook_logger.info(f"funchook: {funcHook}")
            funcHook.add_detour(detour, DetourTime.AFTER)
            return funcHook
        else:
            f = FuncHook(
            detour,
            name=cls._name,
            detour_time=DetourTime.AFTER,
            overload=cls._overload,
            should_enable=should_enable,
        )
            setattr(cls, "_func_hook", f)
            return f


def disable(obj):
    """
    Disable the current function or class.
    This decorator MUST be the innermost decorator for it to work correctly.
    """
    obj._should_enable = False
    return obj


# TODO: See if we can make this work so that we may have a main loop decorator
# which doesn't require a .before or .after...
class _main_loop:
    def __init__(self, func, detour_time=DetourTime.BEFORE):
        self.func = func
        self.func._main_loop = True
        self.func._main_loop_detour_time = detour_time

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    @staticmethod
    def before(func):
        func._main_loop = True
        func._main_loop_detour_time = DetourTime.BEFORE
        return func

    @staticmethod
    def after(func):
        func._main_loop = True
        func._main_loop_detour_time = DetourTime.AFTER
        return func


def on_state_change(state):
    def _inner(func):
        func._trigger_on_state = state
        return func
    return _inner


def on_game_save(func):
    func._on_game_save = True
    return func


def on_game_load(func):
    func._on_game_load = True
    return func


def on_fully_booted(func):
    """
    Configure the decorated function to be run once the game is considered
    "fully booted".
    This occurs when the games' internal state first changes to "mode selector"
    (ie. just before the game mode selection screen appears).
    """
    func._trigger_on_state = "MODESELECTOR"
    return func


class main_loop:
    @staticmethod
    def before(func):
        func._is_main_loop_func = True
        func._main_loop_detour_time = DetourTime.BEFORE
        return func

    @staticmethod
    def after(func):
        func._is_main_loop_func = True
        func._main_loop_detour_time = DetourTime.AFTER
        return func


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


def conditionally_enabled_hook(conditional: bool):
    """ Conditionally enable a hook.
    This conditional is checked at function definition time and will determine
    if the hook should actually be enabled when told to enable.

    Parameters
    ----------
    conditional:
        A statement which must resolve to True or False
        Eg. `some_variable == 42`
    """
    def _conditional_hook(klass: NMSHook):
        klass._should_enable = conditional
        return klass
    return _conditional_hook


def conditional_hook(conditional: str):
    """ Conditionally call the detour function when the provided conditional
    evaluates to true.
    This can be used to conditionally turn on or off the detouring automatically
    based on some condition.

    Parameters
    ----------
    conditional:
        String containing a statement which, when evaluated to be True, will
        cause the detour to be run.
    """
    def _conditional_hook(klass: NMSHook):
        orig_detour = klass.detour
        @wraps(klass.detour)
        def conditional_detour(self: NMSHook, *args, **kwargs):
            # Run the original function if the conditional evaluates to True.
            if eval(conditional) is True:
                ret = orig_detour(self, *args, **kwargs)
            else:
                ret = self.original(*args, **kwargs)
            return ret
        # Assign the decorated method to the `detour` attribute.
        klass.detour = conditional_detour
        return klass
    return _conditional_hook


def one_shot(klass: FuncHook):
    klass._is_one_shot = True
    return klass


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


class HookManager():
    def __init__(self):
        self.hooks: dict[str, FuncHook] = {}
        # Keep a mapping of any hooks that try to be registered but fail.
        # These hooks will not be instances of classes, but the class type.
        self.failed_hooks: dict[str, Type[FuncHook]] = {}
        # A mapping of the custom event hooks which can be registered by modules
        # for individual mods.
        self.callback_funcs: dict[str, set[Callable]] = {}

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

    def add_main_loop_func(self, func):
        if func._main_loop_detour_time == DetourTime.BEFORE:
            self.main_loop_before_funcs.append(func)
        else:
            self.main_loop_after_funcs.append(func)

    def remove_main_loop_func(self, func):
        try:
            if func._main_loop_detour_time == DetourTime.BEFORE:
                self.main_loop_before_funcs.remove(func)
            else:
                self.main_loop_after_funcs.remove(func)
        except ValueError:
            # In this case maybe there was an error starting the hook the last
            # time and so it won't be loaded. Just ignore as hopefully this
            # time when reloading it will go better!
            pass

    def add_state_change_func(self, state, func):
        self.on_state_change_funcs[state].append(func)

    def remove_state_change_func(self, state, func):
        self.on_state_change_funcs[state].remove(func)

    def register_function(
            self,
            hook: FuncHook,
            enable: bool = True,
            mod = None,
            quiet: bool = False
    ):
        """ Register the provided function as a callback. """
        if hook._invalid:
            # If the hook is invalid for any reason, then just return (for now...)
            return
        bound_ok = hook.bind(mod)
        if bound_ok:
            if not quiet:
                hook_logger.info(
                    f"Registered hook '{hook._name}' for function "
                    f"'{hook._original_detour.__name__}'"
                )
            self.hooks[hook._name] = hook
            if enable and hook._should_enable:
                try:
                    hook.enable()
                except:
                    hook_logger.info(traceback.format_exc())

    def enable(self, func_name: str):
        """ Enable the hook for the provided function name. """
        if hook := self.hooks.get(func_name):
            hook.enable()
        else:
            return
        hook_logger.info(f"Enabled hook for function '{func_name}'")

    def disable(self, func_name: str):
        """ Disable the hook for the provided function name. """
        if hook := self.hooks.get(func_name):
            hook.disable()
        else:
            return
        hook_logger.info(f"Disabled hook for function '{func_name}'")

    @property
    def states(self):
        # Return the states of all the registered hooks
        for func_name, hook in self.hooks.items():
            yield f"{func_name}: {hook.state}"


hook_manager = HookManager()
