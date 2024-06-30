# Main functionality for loading mods.

# Mods will consist of a single file which will generally contain a number of
# hooks.

from abc import ABC
from dataclasses import fields
from functools import partial
import inspect
import importlib
import importlib.util
import json
import logging
import os.path as op
import os
import traceback
from types import ModuleType
from typing import Any, Optional, Callable
import sys

from pymhf.core.importing import import_file
from pymhf.core.errors import NoSaveError
import pymhf.core._internal as _internal
from pymhf.core.hooking import HookManager, FuncHook
import pymhf.core.common as common
from pymhf.core.utils import does_pid_have_focus
from pymhf.core._types import HookProtocol

import keyboard
import semver


mod_logger = logging.getLogger("ModManager")


def _is_mod_predicate(obj, ref_module) -> bool:
    if inspect.getmodule(obj) == ref_module and inspect.isclass(obj):
        return issubclass(obj, Mod) and getattr(obj, "_should_enable", True)
    return False


def _is_mod_state_predicate(obj) -> bool:
    return isinstance(obj, ModState)


def _funchook_predicate(value: Any) -> bool:
    return getattr(value, "_is_funchook", False)


def _has_hotkey_predicate(value: Any) -> bool:
    """ Determine if the object has the _is_main_loop_func property.
    This will only be methods on Mod classes which are decorated with either
    @main_loop.before or @main_loop.after
    """
    return getattr(value, "_hotkey", False)


def _gui_button_predicate(value) -> bool:
    return getattr(value, "_is_button", False) and hasattr(value, "_button_text")


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
                "fields": obj.__json__()
            }
        return json.JSONEncoder.default(self, obj)


class StructDecoder(json.JSONDecoder):
    def __init__(self):
        json.JSONDecoder.__init__(self, object_hook=self.object_hook)

    def object_hook(seld, obj: dict):
        if (module := obj.get("module")) is not None:
            mod_logger.info(module)
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
                    mod_logger.error(
                        f"Cannot find {obj['struct']} in {module}"
                    )
                    return
        return obj


class ModState(ABC):
    """A class which is used as a base class to indicate that the class is to be
    used as a mod state.
    Mod State classes will persist across mod reloads so any variables set in it
    will have the same value after the mod has been reloaded.
    """
    _save_fields_: tuple[str]

    def save(self, name: str):
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
        with open(op.join(common.mod_save_dir, name), "w") as fobj:
            json.dump(_data, fobj, cls=StructEncoder, indent=1)

    def load(self, name: str):
        try:
            with open(op.join(common.mod_save_dir, name), "r") as f:
                data = json.load(f, cls=StructDecoder)
        except FileNotFoundError as e:
            raise NoSaveError from e
        for key, value in data.items():
            setattr(self, key, value)


class Mod(ABC):
    __author__: str = "Name(s) of the mod author(s)"
    __description__: str = "Short description of the mod"
    __version__: str = "Mod version"
    # Minimum required pyMHF version for this mod.
    __pymhf_required_version__: Optional[str] = None

    callback_funcs: dict[str, set[Callable]]

    def __init__(self):
        # Find all the hooks defined for the mod.
        self.hooks: set[HookProtocol] = self.get_members(_funchook_predicate)
        self.callback_funcs = {}
        self._hotkey_funcs = self.get_members(_has_hotkey_predicate)
        self._gui_buttons = {x[1] for x in inspect.getmembers(self, _gui_button_predicate)}
        # For variables, unless there is a better way, store just the name so we
        # can our own special binding of the name to the GUI.
        self._gui_variables = {}
        for x in inspect.getmembers(self.__class__, _gui_variable_predicate):
            if x[1].fset is not None:
                x[1].fget._has_setter = True
            self._gui_variables[x[0]] = x[1].fget

    @property
    def _mod_name(self):
        return self.__class__.__name__

    def get_members(self, predicate):
        return {x[1] for x in inspect.getmembers(self, predicate)}


class ModManager():
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
        """ Load a mod from the provided module.
        This will be called when initially loading the mods, and also when we
        wish to reload a mod.
        """
        from pymhf import __version__ as _pymhf_version
        pymhf_version = semver.Version.parse(_pymhf_version)

        d: dict[str, type[Mod]] = dict(
            inspect.getmembers(
                module,
                partial(_is_mod_predicate, ref_module=module)
            )
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
            try:
                mod_version = semver.Version.parse(mod.__pymhf_required_version__)
            except ValueError:
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
            mod_states = list(
                inspect.getmembers(
                    mod,
                    _is_mod_state_predicate
                )
            )
            self.mod_states[mod_name] = mod_states
        if not mod_name.startswith("_INTERNAL_"):
            self._mod_paths[mod_name] = module
        return True

    def load_mod(self, fpath) -> bool:
        """ Load a mod from the given filepath. """
        module = import_file(fpath)
        if module is None:
            return False
        return self._load_module(module)

    def load_mod_folder(self, folder: str, quiet: bool = False):
        for file in os.listdir(folder):
            if file.endswith(".py"):
                self.load_mod(op.join(folder, file))
        # Once all the mods in the folder have been loaded, then parse the mod
        # for function hooks and register then with the hook loader.
        for mod in self._preloaded_mods.values():
            self.register_funcs(mod)

        self._preloaded_mods.clear()

        bound_hooks = 0

        for hook in self.hook_manager.hooks.values():
            hook._init()
            bound = hook.bind()
            if bound:
                bound_hooks += 1

        # TODO: This isn't actually the right metric. Need to get the number of
        # actual mods loaded.
        return bound_hooks

    def register_funcs(self, mod: type[Mod], quiet: bool = False):
        # Instantiate the mod object.
        _mod = mod()
        for hook in _mod.hooks:
            self.hook_manager.register_hook(hook)
        self._register_funcs(_mod, quiet)
        self.mods[_mod._mod_name] = _mod

    def _register_funcs(self, mod: Mod, quiet: bool):
        # TODO: Update how custom callbacks work/implement them.
        self.hook_manager.add_custom_callbacks(mod.callback_funcs)
        for hotkey_func in mod._hotkey_funcs:
            # Don't need to tell the hook manager, register the keyboard
            # hotkey here...
            # NOTE: The below is a "hack"/"solution" to an issue that the
            # keyboard library has.
            # cf. https://github.com/boppreh/keyboard/issues/584
            # NOTE: This solution breaks for keybindings where multiple keys
            # Are required. Will need a better solution for this case.

            cb = keyboard.hook(
                lambda e, func=hotkey_func, name=hotkey_func._hotkey, event_type=hotkey_func._hotkey_press: (
                    e.name == name and
                    e.event_type == event_type and
                    does_pid_have_focus(_internal.PID) and
                    func()
                )
            )
            self.hotkey_callbacks[
                (hotkey_func._hotkey, hotkey_func._hotkey_press)
            ] = cb

    def _gui_reload(self, _sender, _keyword, user_data):
        # Callback to register with the GUI to enable reloading of mods from there.
        self.reload(user_data)

    def reload(self, name: str):
        """ Reload a mod with the given name. """
        try:
            if (mod := self.mods.get(name)) is not None:
                # First, remove everything.
                for hook in mod.hooks:
                    fh: Optional[FuncHook] = self.hook_manager.hook_registry.get(hook)
                    if fh is not None:
                        mod_logger.info(f"Removing hook {hook}: {hook._hook_func_name}")
                        fh.remove_detour(hook)
                self.hook_manager.remove_custom_callbacks(mod.callback_funcs)
                for hotkey_func in mod._hotkey_funcs:
                    cb = self.hotkey_callbacks.pop(
                        (hotkey_func._hotkey, hotkey_func._hotkey_press),
                        None,
                    )
                    if cb is not None:
                        keyboard.unhook(cb)

                # Then, reload the module
                module = self._mod_paths[name]
                del sys.modules[module.__name__]
                # Then, add everything back.
                self.load_mod(module.__file__)
                for mod in self._preloaded_mods.values():
                    self.register_funcs(mod)

                self._preloaded_mods.clear()

                for hook in self.hook_manager.hooks.values():
                    hook._init()
                    hook.bind()

                mod_logger.info(self.mod_states)
                mod_logger.info("Mod states after finishing reloading...")

                # Get the mod states for the mod if there are any and reapply them to the new mod instance.
                if mod_state := self.mod_states.get(name):
                    for ms in mod_state:
                        field, state = ms
                        setattr(mod, field, state)

                # TODO: Add functionality for reloading the gui elements.

                mod_logger.info(f"Finished reloading {name}")
            else:
                mod_logger.error(f"Cannot find mod {name}")
        except:
            mod_logger.exception(traceback.format_exc())
