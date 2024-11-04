import argparse
import os
import os.path as op
import shutil
from importlib.metadata import PackageNotFoundError, entry_points, version

import questionary

from .core._types import FUNCDEF  # noqa
from .core.hooking import FuncHook  # noqa
from .core.mod_loader import Mod, ModState  # noqa
from .main import load_mod_file, load_module  # noqa

try:
    __version__ = version("pymhf")
except PackageNotFoundError:
    pass


def _is_int(val: str) -> bool:
    try:
        int(val)
    except (ValueError, TypeError):
        return False
    return True


IS_STEAM_Q = questionary.confirm("Is the game run via steam?", default=True)
START_PAUSED = questionary.confirm("Start the game paused?", default=True)
RUN_GAME = questionary.confirm("Run game?", default=True)
STEAM_ID_Q = questionary.text("Enter the steam game ID:", validate=_is_int)
EXE_PATH_Q = questionary.path("Enter the absolute path to the binary:")
MOD_DIR_Q = questionary.path("Enter the absolute path the mod directory")
CONTINUE_CONFIGURING_Q = questionary.confirm("Would you like to configure more options?", default=True)

CFG_OPT_BIN_PATH = "Set binary path"
CFG_OPT_MOD_PATH = "Set mod directory"
CFG_OPT_STEAM_ID = "Configure steam game id"
CFG_OPT_START_PAUSED = "Set game to start paused"
CONFIG_SELECT_Q = questionary.select(
    "What would you like to configure?",
    choices=[
        CFG_OPT_BIN_PATH,
        CFG_OPT_MOD_PATH,
        CFG_OPT_STEAM_ID,
        CFG_OPT_START_PAUSED,
    ],
)

CFG_FILENAME = "pymhf.toml"


def run():
    """Main entrypoint which can be used to run programs with pymhf.
    This will take the first argument as the name of a module which has been installed.
    """
    from .utils.parse_toml import read_pymhf_settings, write_pymhf_settings

    parser = argparse.ArgumentParser(
        prog="pyMHF program runner",
        description="Run the registered plugin",
    )
    parser.add_argument("plugin_name")
    parser.add_argument(
        "-c",
        "--config",
        action="store_true",
        required=False,
        help="Enter the configuration manager for this library",
    )
    args = parser.parse_args()

    plugin_name: str = args.plugin_name
    is_config_mode: bool = args.config
    standalone = False

    if op.isfile(plugin_name) and op.exists(plugin_name):
        # In this case we are running in stand-alone mode
        standalone = True

    if standalone:
        load_mod_file(plugin_name)
        return

    # Get the location of app data, then construct the expected folder name.
    appdata_data = os.environ.get("APPDATA", op.expanduser("~"))
    if appdata_data == "~":
        # In this case the APPDATA environment variable isn't set and ~ also fails to resolve.
        # Raise a error and stop.
        print("Critical Error: Cannot find user directory. Ensure APPDATA environment variable is set")
        exit()
    cfg_folder = op.join(appdata_data, "pymhf", plugin_name)
    os.makedirs(cfg_folder, exist_ok=True)

    # PROCESS:
    """
    1. Check that the config file is in the correct location. If not, prompt the user to configure it.
    2. if no `--config` argument passed, then we just run the program as intented.
    3. If `--config` is provided, then we don't run the program and instead configure it.
    4. The arguments for config are the keys (this will need to be documented extensively) followed by values
        and separated by an `=`.
    """

    eps = entry_points()
    # This check is to ensure compatibility with multiple versions of python as the code 3.10+ isn't backward
    # compatible.
    if isinstance(eps, dict):
        loaded_libs = eps.get("pymhflib", [])
    else:
        loaded_libs = eps.select(group="pymhflib")
    required_lib = None
    for lib in loaded_libs:
        if lib.name.lower() == plugin_name.lower():
            required_lib = lib

    if required_lib is None:
        print(
            f"Cannot find {plugin_name} as an installed plugin. "
            "Please ensure it has been installed and try again"
        )
        return

    loaded_lib = required_lib.load()
    initial_config = False

    module_dir = op.dirname(loaded_lib.__file__)

    cfg_file = op.join(module_dir, CFG_FILENAME)
    config_progress_file = op.join(cfg_folder, ".config_in_progress")
    if not op.exists(cfg_file):
        print(
            f"Cannot find `pymhf.cfg` for {plugin_name}! This is likely an error on the maintainers' "
            "behalf.\nCannot continue loading until this is fixed."
        )
        return
    else:
        dst = op.join(cfg_folder, CFG_FILENAME)
        if not op.exists(dst) or op.exists(config_progress_file):
            # In this case we can prompt the user to enter the config values which need to be changed.
            initial_config = True

    if initial_config:
        # Copy the config file to the appdata directory.
        shutil.copyfile(cfg_file, dst)
        # Write the file which indicates we are in progress.
        with open(config_progress_file, "w") as f:
            f.write("")
        pymhf_settings = read_pymhf_settings(cfg_file)

        # Modify some of the values in the config file, allowing the user to enter the values they want.

        if (mod_dir := MOD_DIR_Q.ask()) is not None:
            pymhf_settings["mod_dir"] = mod_dir
        else:
            return

        # Write the config back and then delete the temporary file only once everything is ok.
        write_pymhf_settings(pymhf_settings, dst)
        os.remove(config_progress_file)
        initial_config = False
    elif is_config_mode:
        pymhf_settings = read_pymhf_settings(dst)
        keep_going = True
        while keep_going:
            config_choice = CONFIG_SELECT_Q.ask()
            if config_choice == CFG_OPT_BIN_PATH:
                if (exe_path := EXE_PATH_Q.ask()) is not None:
                    pymhf_settings["exe_path"] = exe_path
                    del pymhf_settings["steam_gameid"]
                else:
                    return
            elif config_choice == CFG_OPT_STEAM_ID:
                if (steam_id := STEAM_ID_Q.ask()) is not None:
                    pymhf_settings["steam_gameid"] = steam_id
                    del pymhf_settings["exe_path"]
                else:
                    return
            elif config_choice == CFG_OPT_MOD_PATH:
                if (mod_dir := MOD_DIR_Q.ask()) is not None:
                    pymhf_settings["mod_dir"] = mod_dir
                else:
                    return
            elif config_choice == CFG_OPT_START_PAUSED:
                if (start_paused := START_PAUSED.ask()) is not None:
                    pymhf_settings["start_paused"] = start_paused
                else:
                    return
            elif config_choice is None:
                keep_going = False

            keep_going = CONTINUE_CONFIGURING_Q.ask()
            if keep_going is None:
                return
        write_pymhf_settings(dst, pymhf_settings)

        if not RUN_GAME.ask():
            return
    # Final step: If we have either finished the initial config, or we didn't want to config at all, run the
    # binary.
    if not initial_config:
        load_module(plugin_name, module_dir, False)
