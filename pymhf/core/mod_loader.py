# Main functionality for loading mods.

# Mods will consist of a single file which will generally contain a number of
# hooks.

import ctypes
import importlib
import importlib.util
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
from typing import TYPE_CHECKING, Any, Optional, Union

import keyboard
from packaging.version import InvalidVersion
from packaging.version import parse as parse_version

import pymhf.core._internal as _internal
from pymhf.core._types import HookProtocol
from pymhf.core.errors import NoSaveError
from pymhf.core.hooking import HookManager
from pymhf.core.importing import import_file
from pymhf.core.memutils import get_addressof, map_struct
from pymhf.core.module_data import module_data
from pymhf.core.utils import does_pid_have_focus, saferun
from pymhf.gui.protocols import ButtonProtocol, ComboBoxProtocol, VariableProtocol

if TYPE_CHECKING:
    from pymhf.gui.gui import GUI


mod_logger = logging.getLogger("ModManager")


def _is_mod_predicate(obj, ref_module) -> bool:
    if inspect.getmodule(obj) == ref_module and inspect.isclass(obj):
        return issubclass(obj, Mod) and getattr(obj, "_should_enable", True)
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

    def object_hook(seld, obj: dict):
        if (module := obj.get("module")) is not None:
            if module == "__main__":
                return globals()[obj["struct"]](**obj["fields"])
            else:
                try:
                    module_ = importlib.import_module(module)
                    return getattr(module_, obj["struct"])(**obj["fields"])
                except ImportError:
                    mod_logger.error(f"Cannot import {module}")
                    return
                except AttributeError:
                    mod_logger.error(f"Cannot find {obj['struct']} in {module}")
                    return
        return obj


class ModState(ABC):
    """A class which is used as a base class to indicate that the class is to be used as a mod state.

    Mod State classes will persist across mod reloads so any variables set in it
    will have the same value after the mod has been reloaded.
    """

    _save_fields_: tuple[str]

    def save(self, name: str):
        """Save the current mod state to file."""
        _data = {}
        if hasattr(self, "_save_fields_") and self._save_fields_:
            for field in self._save_fields_:
                _data[field] = getattr(self, field)
        else:
            try:
                for f in fields(self):
                    _data[f.name] = getattr(self, f.name)
            except TypeError:
                mod_logger.error(
                    "To save a mod state it must either be a dataclass or "
                    "have the _save_fields_ attribute. State was not saved"
                )
                return
        if not _internal.MOD_SAVE_DIR:
            _internal.MOD_SAVE_DIR = op.join(_internal.MODULE_PATH, "MOD_SAVES")
            mod_logger.warning(
                f"No mod_save_dir config value set. Please set one. Falling back to {_internal.MOD_SAVE_DIR}"
            )
        if not op.exists(_internal.MOD_SAVE_DIR):
            os.makedirs(_internal.MOD_SAVE_DIR)
        with open(op.join(_internal.MOD_SAVE_DIR, name), "w") as fobj:
            json.dump(_data, fobj, cls=StructEncoder, indent=1)

    def load(self, name: str):
        """Load the mod state from file."""
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
    # Minimum required pyMHF version for this mod.
    __pymhf_required_version__: Optional[str] = None

    custom_callbacks: dict[str, set[HookProtocol]]

    def __init__(self):
        # Find all the hooks defined for the mod.
        self.hooks: set[HookProtocol] = self.get_members(_funchook_predicate)
        self.custom_callbacks = self.get_members(_callback_predicate)
        self._hotkey_funcs = self.get_members(_has_hotkey_predicate)
        self._gui_buttons: dict[str, ButtonProtocol] = {
            x[1].__qualname__: x[1] for x in inspect.getmembers(self, _gui_button_predicate)
        }
        self._gui_comboboxes: dict[str, ComboBoxProtocol] = {
            x[1].__qualname__: x[1] for x in inspect.getmembers(self, _gui_combobox_predicate)
        }
        self._gui = None
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


class ModManager:
    def __init__(self, hook_manager: HookManager):
        # Internal mapping of mods.
        # TODO: Probably change datatype
        self._preloaded_mods: dict[str, type[Mod]] = {}
        # Actual mapping of mods.
        self.mods: dict[str, Mod] = {}
        self._mod_hooks: dict[str, list] = {}
        self.mod_states: dict[str, list[tuple[str, ModState]]] = {}
        self._mod_paths: dict[str, ModuleType] = {}
        self.hook_manager = hook_manager
        # Keep a mapping of the hotkey callbacks
        self.hotkey_callbacks: dict[tuple[str, str], Any] = {}

    def _load_module(self, module: ModuleType) -> bool:
        """Load a mod from the provided module.

        This will be called when initially loading the mods, and also when we
        wish to reload a mod.
        """
        d: dict[str, type[Mod]] = dict(
            inspect.getmembers(module, partial(_is_mod_predicate, ref_module=module))
        )
        if not len(d) >= 1:
            mod_logger.error(
                f"The file {module.__file__} has more than one mod defined in it. "
                "Only define one mod per file."
            )
        if len(d) == 0:
            # No mod in the file. Just return
            return False
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
                mod_logger.warning(
                    "__pymhf_required_version__ defined on mod "
                    f"{mod.__name__} is not a valid version string"
                )
                mod_version = None
            if mod_version is None or mod_version <= pymhf_version:
                self._preloaded_mods[mod_name] = mod
            else:
                mod_logger.error(
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

    def load_mod_folder(self, folder: str, bind: bool = True) -> tuple[int, int]:
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
        """
        for file in os.listdir(folder):
            if file.endswith(".py"):
                self.load_mod(op.join(folder, file))
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

    def instantiate_mod(self, mod: type[Mod], quiet: bool = False) -> Mod:
        """Register all the functions within the mod as hooks."""
        _mod = mod()
        # First register each of the methods which are detours.
        for hook in _mod.hooks:
            self.hook_manager.register_hook(hook)
        # Add any custom callbacks which may be defined by the calling library.
        self.hook_manager.add_custom_callbacks(_mod.custom_callbacks)
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

    def _gui_reload(self, _sender, _keyword, user_data: tuple[Mod, "GUI"]):
        # Callback to register with the GUI to enable reloading of mods from there.
        self.reload(*user_data)

    def reload(self, name: str, gui: "GUI"):
        """Reload a mod with the given name."""
        try:
            if (mod := self.mods.get(name)) is not None:
                # First, remove everything.
                for hook in mod.hooks:
                    hook_name = hook._hook_func_name
                    fh = self.hook_manager.hooks.get(hook_name)
                    if fh is not None:
                        mod_logger.info(f"Removing hook {hook}: {hook._hook_func_name}")
                        fh.remove_detour(hook)
                        # If the hook has been closed it means that there are now no longer any methods
                        # assigned as detours to it. Remove the hook from the registry.
                        if fh.state == "closed":
                            del self.hook_manager.hooks[hook_name]

                self.hook_manager.remove_custom_callbacks(mod.custom_callbacks)
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
                                            logging.info(f"{member}: {_module}")
                            logging.info(
                                f"Reinstantiating the following members: {list(member_req_reinst.keys())}"
                            )
                            for name, type_ in member_req_reinst.items():
                                data_offset = get_addressof(type_)
                                new_obj_type_name = type_.__class__.__name__
                                mod_logger.info(f"{name} is of type {new_obj_type_name}")
                                new_obj_type = getattr(new_module, new_obj_type_name)
                                new_obj = map_struct(data_offset, new_obj_type)
                                setattr(state, name, new_obj)
                                del member_type
                            setattr(mod, field, state)

                    # Check also to see if the file had any module-level __pymhf attributes which we might
                    # to update the `module_data` with.
                    _new_binary = getattr(new_module, "__pymhf_func_binary__", None)
                    _new_offsets = getattr(new_module, "__pymhf_func_offsets__", {})
                    _new_patterns = getattr(new_module, "__pymhf_func_patterns__", {})
                    _new_func_call_sigs = getattr(new_module, "__pymhf_func_call_sigs__", {})

                    if _new_binary:
                        module_data.FUNC_BINARY = _new_binary
                    module_data.FUNC_OFFSETS.update(_new_offsets)
                    module_data.FUNC_PATTERNS.update(_new_patterns)
                    module_data.FUNC_CALL_SIGS.update(_new_func_call_sigs)

                    # Return to GUI land to reload the mod.
                    gui.reload_tab(mod)

                self._preloaded_mods.clear()

                self.hook_manager.initialize_hooks()

                # TODO: Add ability to check whether the attributes of the mod state have changed. If so,
                # remove or add these attributes as required. Might want to have some kind of "copy" method to
                # actually create a new instance each time but persist the data across.

                mod_logger.info(f"Finished reloading {name}")
            else:
                mod_logger.error(f"Cannot find mod {name}")
        except Exception:
            mod_logger.error(traceback.format_exc())
