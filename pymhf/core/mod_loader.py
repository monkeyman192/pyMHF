# Main functionality for loading mods.

# Mods will consist of a single file which will generally contain a number of
# hooks.

import ctypes
import importlib
import inspect
import json
import logging
import os
import os.path as op
import sys
import traceback
from abc import ABC
from dataclasses import fields
from functools import partial
from types import ModuleType
from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar, Union, overload

import keyboard
from packaging.version import InvalidVersion
from packaging.version import parse as parse_version

import pymhf.core._internal as _internal
from pymhf.core._types import CustomTriggerProtocol, HookProtocol, KeyPressProtocol
from pymhf.core.errors import NoSaveError
from pymhf.core.hooking import HookManager
from pymhf.core.importing import import_file
from pymhf.core.memutils import get_addressof, map_struct
from pymhf.core.utils import does_pid_have_focus, saferun
from pymhf.gui.protocols import ButtonProtocol, ComboBoxProtocol, VariableProtocol

if TYPE_CHECKING:
    from pymhf.gui.gui import GUI


logger = logging.getLogger(__name__)


def _is_mod_predicate(obj, ref_module) -> bool:
    if inspect.getmodule(obj) == ref_module and inspect.isclass(obj):
        return issubclass(obj, Mod) and not getattr(obj, "_disabled", False)
    return False


def _is_mod_state_predicate(obj) -> bool:
    return isinstance(obj, ModState)


def _funchook_predicate(value: Any) -> bool:
    return getattr(value, "_is_funchook", False)


def _callback_predicate(value: Any) -> bool:
    return hasattr(value, "_custom_trigger")


def _has_hotkey_predicate(value: Any) -> bool:
    """Determine if the object has the _is_main_loop_func property.
    This will only be methods on Mod classes which are decorated with either
    @main_loop.before or @main_loop.after
    """
    return getattr(value, "_hotkey", False)


def _gui_button_predicate(value) -> bool:
    return getattr(value, "_is_button", False) and hasattr(value, "_button_text")


def _gui_combobox_predicate(value) -> bool:
    return getattr(value, "_is_combobox", False) and hasattr(value, "_combobox_text")


def _gui_variable_predicate(value) -> bool:
    # Variables are properties which have the .fset function defined with
    # _is_variable and _label_text attributes, and a .fset function too.
    if isinstance(value, property):
        return (
            getattr(value.fget, "_is_variable", False)
            and hasattr(value.fget, "_label_text")
            and hasattr(value.fget, "_variable_type")
        )
    return False


class StructEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "__json__"):
            return {
                "struct": obj.__class__.__qualname__,
                "module": obj.__class__.__module__,
                "fields": obj.__json__(),
            }
        return json.JSONEncoder.default(self, obj)


class StructDecoder(json.JSONDecoder):
    def __init__(self):
        json.JSONDecoder.__init__(self, object_hook=self.object_hook)

    def object_hook(self, obj: dict):
        if (module := obj.get("module")) is not None:
            if module == "__main__":
                return globals()[obj["struct"]](**obj["fields"])
            else:
                try:
                    module_ = importlib.import_module(module)
                    return getattr(module_, obj["struct"])(**obj["fields"])
                except ImportError:
                    logger.error(f"Cannot import {module}")
                    return
                except AttributeError:
                    logger.error(f"Cannot find {obj['struct']} in {module}")
                    return
        return obj


class ModState(ABC):
    """A class which is used as a base class to indicate that the class is to be used as a mod state.

    Mod State classes will persist across mod reloads so any variables set in it
    will have the same value after the mod has been reloaded.
    """

    _save_fields_: tuple[str]

    def save(self, name: str):
        """Save the current mod state to a file.

        Parameters
        ----------
        name:
            The name of the file this ``ModState`` will be saved to.
            Note that this will be a json file saved within the ``MOD_SAVE_DIR`` directory.
        """
        _data = {}
        if hasattr(self, "_save_fields_") and self._save_fields_:
            for field in self._save_fields_:
                _data[field] = getattr(self, field)
        else:
            try:
                for f in fields(self):
                    _data[f.name] = getattr(self, f.name)
            except TypeError:
                logger.error(
                    "To save a mod state it must either be a dataclass or "
                    "have the _save_fields_ attribute. State was not saved"
                )
                return
        if not _internal.MOD_SAVE_DIR:
            _internal.MOD_SAVE_DIR = op.join(_internal.MODULE_PATH, "MOD_SAVES")
            logger.warning(
                f"No mod_save_dir config value set. Please set one. Falling back to {_internal.MOD_SAVE_DIR}"
            )
        if not op.exists(_internal.MOD_SAVE_DIR):
            os.makedirs(_internal.MOD_SAVE_DIR)
        with open(op.join(_internal.MOD_SAVE_DIR, name), "w") as fobj:
            json.dump(_data, fobj, cls=StructEncoder, indent=1)

    def load(self, name: str):
        """Load the mod state from a file.

        Parameters
        ----------
        name:
            The name of the file this ``ModState`` will be loaded from.
            Note that this will be a json file loaded from the ``MOD_SAVE_DIR`` directory.
        """
        try:
            with open(op.join(_internal.MOD_SAVE_DIR, name), "r") as f:
                data = json.load(f, cls=StructDecoder)
        except FileNotFoundError as e:
            raise NoSaveError from e
        for key, value in data.items():
            setattr(self, key, value)


class Mod(ABC):
    __author__: Union[str, list[str]] = "Name(s) of the mod author(s)"
    __description__: str = "Short description of the mod"
    __version__: str = "Mod version"
    __dependencies__: list[str] = []
    # Minimum required pyMHF version for this mod.
    __pymhf_required_version__: Optional[str] = None

    _custom_callbacks: set[CustomTriggerProtocol]
    pymhf_gui: "GUI"
    _disabled: bool = False

    def __init__(self):
        self._abc_initialised = True
        # Find all the hooks defined for the mod.
        self.hooks: set[HookProtocol] = self.get_members(_funchook_predicate)
        self._custom_callbacks = self.get_members(_callback_predicate)
        self._hotkey_funcs: set[KeyPressProtocol] = self.get_members(_has_hotkey_predicate)
        self._gui_buttons: dict[str, ButtonProtocol] = {
            x[1].__qualname__: x[1] for x in inspect.getmembers(self, _gui_button_predicate)
        }
        self._gui_comboboxes: dict[str, ComboBoxProtocol] = {
            x[1].__qualname__: x[1] for x in inspect.getmembers(self, _gui_combobox_predicate)
        }
        # TODO: If this isn't initialised and a call is made to it before it is we have an issue...
        self.pymhf_gui = None
        # For variables, unless there is a better way, store just the name so we
        # can our own special binding of the name to the GUI.
        self._gui_variables: dict[str, VariableProtocol] = {}
        for x in inspect.getmembers(self.__class__, _gui_variable_predicate):
            if x[1].fset is not None:
                x[1].fget._has_setter = True
            self._gui_variables[x[0]] = x[1].fget

    @property
    def _mod_name(self):
        return self.__class__.__name__

    def get_members(self, predicate):
        return {x[1] for x in inspect.getmembers(self, predicate)}


ModClass = TypeVar("ModClass", bound=Mod)


class _Proxy:
    """A dummy class which is just used for mocking calls to a mod which hasn't been loaded."""

    def __init__(self, class_name):
        self.mod_class_name = class_name

    def __getattr__(self, name):
        return lambda *args, **kwargs: logger.warning(
            f"Called {self.mod_class_name}.{name} with args: {args} and kwargs: {kwargs}"
        )


class ModManager:
    def __init__(self):
        # Internal mapping of mods.
        # TODO: Probably change datatype
        self._preloaded_mods: dict[str, type[Mod]] = {}
        # Actual mapping of mods.
        self.mods: dict[str, Mod] = {}
        self._mod_hooks: dict[str, list] = {}
        self.mod_states: dict[str, list[tuple[str, ModState]]] = {}
        self._mod_paths: dict[str, ModuleType] = {}
        self.hook_manager: HookManager = None
        # Keep a mapping of the hotkey callbacks
        self.hotkey_callbacks: dict[tuple[str, str], Any] = {}

    @overload
    def __getitem__(self, key: str) -> _Proxy: ...

    @overload
    def __getitem__(self, key: Type[ModClass]) -> ModClass: ...

    def __getitem__(self, key):
        # If the key is a string then we are using it as a placeholder in the case of wanting to run a mod
        # which has dependencies, without the dependencies.
        # In this case we'll return a fake object which will just log what was called on it.
        if isinstance(key, str):
            return _Proxy(key)
        if not issubclass(key, Mod):
            raise TypeError("The lookup object must be the class type")
        # Set the fallback return object to be a proxy in the case of the mod not having been loaded by pyMHF.
        return self.mods.get(key.__name__, _Proxy(key.__name__))

    def _load_module(self, module: ModuleType) -> bool:
        """Load a mod from the provided module.

        This will be called when initially loading the mods, and also when we
        wish to reload a mod.
        """
        d: dict[str, type[Mod]] = dict(
            inspect.getmembers(module, partial(_is_mod_predicate, ref_module=module))
        )
        if len(d) == 0:
            # No mod in the file. Just return
            return False
        elif len(d) > 1:
            logger.error(
                f"The file {module.__file__} has more than one mod defined in it. "
                "Only define one mod per file."
            )
        mod_name = list(d.keys())[0]
        mod = d[mod_name]
        if mod.__pymhf_required_version__ is not None:
            from pymhf import __version__ as _pymhf_version

            try:
                pymhf_version = parse_version(_pymhf_version)
            except InvalidVersion:
                pymhf_version = None
            try:
                mod_version = parse_version(mod.__pymhf_required_version__)
            except InvalidVersion:
                logger.warning(
                    f"__pymhf_required_version__ defined on mod {mod.__name__} is not a valid version string"
                )
                mod_version = None
            if mod_version is None or mod_version <= pymhf_version:
                self._preloaded_mods[mod_name] = mod
            else:
                logger.error(
                    f"Mod {mod.__name__} requires a newer verison of "
                    f"pyMHF ({mod_version} ≥ {pymhf_version})! "
                    "Please update"
                )
        else:
            self._preloaded_mods[mod_name] = mod
        # Only get mod states if the mod name doesn't already have a cached
        # state, otherwise it will override it.
        if mod_name not in self.mod_states:
            mod_states = list(inspect.getmembers(mod, _is_mod_state_predicate))
            self.mod_states[mod_name] = mod_states
        if not mod_name.startswith("_INTERNAL_"):
            self._mod_paths[mod_name] = module
        return True

    def load_mod(self, fpath) -> Optional[ModuleType]:
        """Load a mod from the given filepath.

        This returns the loaded module if it contains a valid mod and can be loaded correctly.
        """
        module = import_file(fpath)
        if module is None:
            return None
        if self._load_module(module):
            return module

    # TODO: Can probably move the duplicated functionality between this and the next method into a single
    # function.
    def load_single_mod(self, fpath: str, bind: bool = True):
        """Load a single mod file.

        Params
        ------
        folder
            The path of the folder to be loaded. All mod files within this directory will be loaded and
            installed.
        bind
            Whether or not to actual bind and initialize the hooks within the mod.
            This should almost always be True except when loading the internal mods initially since it's not
            necessary.
            If this function is called with False, then it MUST be called again with True before the hooks
            are enabled.
        """
        self.load_mod(fpath)
        # Once all the mods in the folder have been loaded, then parse the mod
        # for function hooks and register then with the hook loader.
        loaded_mods = len(self._preloaded_mods)
        for _mod in self._preloaded_mods.values():
            self.instantiate_mod(_mod)

        self._preloaded_mods.clear()

        bound_hooks = 0
        if bind:
            bound_hooks = self.hook_manager.initialize_hooks()

        return loaded_mods, bound_hooks

    def load_mod_folder(self, folder: str, bind: bool = True, deep_search: bool = False) -> tuple[int, int]:
        """Load the mod folder.

        Params
        ------
        folder
            The path of the folder to be loaded. All mod files within this directory will be loaded and
            installed.
        bind
            Whether or not to actual bind and initialize the hooks within the mod.
            This should almost always be True except when loading the internal mods initially since it's not
            necessary.
            If this function is called with False, then it MUST be called again with True before the hooks
            are enabled.
        deep_search
            Whether to search down into sub-folders.
        """
        for file in os.listdir(folder):
            fullpath = op.join(folder, file)
            if file.endswith(".py"):
                self.load_mod(fullpath)
            elif deep_search:
                # Search down one more layer for mods and then stop.
                # Don't bind any since we'll always call bind later.
                if op.isdir(fullpath):
                    self.load_mod_folder(fullpath, False, False)

        # Once all the mods in the folder have been loaded, then parse the mod for function hooks and register
        # then with the hook loader.
        # We only do this if we are also binding the mods since we only want to do this once.
        loaded_mods = len(self._preloaded_mods)
        bound_hooks = 0

        if bind:
            for _mod in self._preloaded_mods.values():
                self.instantiate_mod(_mod)
            self._preloaded_mods.clear()

            bound_hooks = self.hook_manager.initialize_hooks()

        return loaded_mods, bound_hooks

    def instantiate_mod(self, mod: type[Mod], quiet: bool = False) -> Optional[Mod]:
        """Register all the functions within the mod as hooks."""
        _mod = mod()
        # Detect whether or not the mod has called __init__ on the parent class.
        if not getattr(_mod, "_abc_initialised", False):
            logger.error(
                f"The mod {mod} has an __init__ statement which doesn't call super().__init__\n"
                "This mod will not be loaded until this is fixed."
            )
            return None
        # First register each of the methods which are detours.
        for hook in _mod.hooks:
            self.hook_manager.register_hook(hook)
        # Add any custom callbacks which may be defined by the calling library.
        self.hook_manager._add_custom_callbacks(_mod._custom_callbacks)
        # Finally, set up any keyboard bindings.
        for hotkey_func in _mod._hotkey_funcs:
            # Don't need to tell the hook manager, register the keyboard
            # hotkey here...
            # NOTE: The below is a "hack"/"solution" to an issue that the
            # keyboard library has.
            # cf. https://github.com/boppreh/keyboard/issues/584
            # NOTE: This solution breaks for keybindings where multiple keys
            # Are required. Will need a better solution for this case.

            cb = keyboard.hook(
                lambda e, func=hotkey_func, name=hotkey_func._hotkey, event_type=hotkey_func._hotkey_press: (
                    e.name == name
                    and e.event_type == event_type
                    and does_pid_have_focus(_internal.PID)
                    and saferun(func)
                )
            )
            self.hotkey_callbacks[(hotkey_func._hotkey, hotkey_func._hotkey_press)] = cb
        self.mods[_mod._mod_name] = _mod
        return _mod

    def _gui_reload(self, _sender, _keyword, user_data: tuple[str, "GUI"]):
        # Callback to register with the GUI to enable reloading of mods from there.
        self.reload(*user_data)
        self._assign_mod_instances(user_data[0])

    def _assign_mod_instances(self, specific_mod: Optional[str] = None):
        """Assign the types of the mod classes in each mod to all of the mods which are loaded."""
        # Loop over the loaded mods. If it has any dependencies, get the module it belongs to and assign those
        # dependencies to it.
        if specific_mod is not None:
            iter_ = [(specific_mod, self.mods[specific_mod])]
        else:
            iter_ = self.mods.items()
        for _mod_name, mod in iter_:
            if dependencies := getattr(mod, "__dependencies__", []):
                module = self._mod_paths[_mod_name]
                for dependency in dependencies:
                    if dependency in self.mods:
                        setattr(module, dependency, self.mods[dependency].__class__)
                    else:
                        logger.warning(
                            f"Dependency {dependency!r} is unsatisfied. There may be issues when running."
                        )

    def reload(self, name: str, gui: "GUI"):
        """Reload a mod with the given name."""
        try:
            if (mod := self.mods.get(name)) is not None:
                # First, remove everything.
                for hook in mod.hooks:
                    if (fh := self.hook_manager._get_funchook(hook)) is not None:
                        logger.info(f"Removing hook {hook}: {hook._hook_func_name}")
                        fh.remove_detour(hook)
                        # Tell the hook manager to try and remove the hook if it can.
                        self.hook_manager.try_remove_hook(hook)

                self.hook_manager._remove_custom_callbacks(mod._custom_callbacks)
                for hotkey_func in mod._hotkey_funcs:
                    cb = self.hotkey_callbacks.pop(
                        (hotkey_func._hotkey, hotkey_func._hotkey_press),
                        None,
                    )
                    if cb is not None:
                        keyboard.unhook(cb)

                # Then, reload the module.
                module = self._mod_paths[name]
                del sys.modules[module.__name__]

                # Then, add everything back.
                new_module = self.load_mod(module.__file__)
                for _mod in self._preloaded_mods.values():
                    mod = self.instantiate_mod(_mod)
                    if mod is None:
                        # If the mod isn't instantiated for any reason, skip it.
                        continue
                    # Get the mod states for the mod if there are any and reapply them to the new mod
                    # instance.
                    if mod_state := self.mod_states.get(name):
                        for ms in mod_state:
                            field, state = ms
                            member_req_reinst = {}
                            for x in inspect.getmembers(state):
                                member, member_type = x
                                if not member.startswith("__"):
                                    if (
                                        _module := getattr(member_type.__class__, "__module__", None)
                                    ) is not None and isinstance(member_type, ctypes.Structure):
                                        if _module == module.__spec__.name:
                                            # In this case, the instance of the attribute in the ModState was
                                            # defined in the module that is being reloaded. We need to
                                            # re-instantiate it so that we can get any potential changes to
                                            # it.
                                            member_req_reinst[member] = member_type
                                            logger.debug(f"{member}: {_module}")
                            logger.debug(
                                f"Reinstantiating the following members: {list(member_req_reinst.keys())}"
                            )
                            deleted_types = set()
                            for _name, type_ in member_req_reinst.items():
                                data_offset = get_addressof(type_)
                                new_obj_type_name = type_.__class__.__name__
                                logger.debug(f"{_name} is of type {new_obj_type_name}")
                                new_obj_type = getattr(new_module, new_obj_type_name)
                                new_obj = map_struct(data_offset, new_obj_type)
                                setattr(state, _name, new_obj)
                                if new_obj_type_name not in deleted_types:
                                    del type_
                                    deleted_types.add(new_obj_type_name)
                            setattr(mod, field, state)

                    # Return to GUI land to reload the mod.
                    gui.reload_tab(mod)

                self._preloaded_mods.clear()

                self.hook_manager.initialize_hooks()

                # TODO: Add ability to check whether the attributes of the mod state have changed. If so,
                # remove or add these attributes as required. Might want to have some kind of "copy" method to
                # actually create a new instance each time but persist the data across.

                logger.info(f"Finished reloading {name}")
            else:
                logger.error(f"Cannot find mod {name}")
        except Exception:
            logger.error(traceback.format_exc())


mod_manager = ModManager()
