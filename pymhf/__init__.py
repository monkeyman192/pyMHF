import argparse
import os
import os.path as op
import shutil
import subprocess
from enum import Enum
from importlib.metadata import PackageNotFoundError, entry_points, version
from typing import Optional

import questionary

from .core._types import FUNCDEF  # noqa
from .core.hooking import FuncHook  # noqa
from .core.mod_loader import Mod, ModState  # noqa
from .main import load_mod_file, load_module  # noqa

try:
    __version__ = version("pymhf")
except PackageNotFoundError:
    pass

try:
    from tkinter import Tk, filedialog

    has_tkinter = True
except ModuleNotFoundError:
    has_tkinter = False


class ModeEnum(Enum):
    INVALID = 0
    RUN = 1
    CONFIG = 2
    INIT = 3
    COMMAND = 4
    # DATA = 5


def _is_int(val: str) -> bool:
    try:
        int(val)
    except (ValueError, TypeError):
        return False
    return True


def get_folder(title: str, q: questionary.Question, has_tkinter: bool, idir: Optional[str] = None) -> str:
    if has_tkinter:
        return filedialog.askdirectory(initialdir=idir, title=title)
    else:
        return q.ask()


IS_STEAM_Q = questionary.confirm("Is the game run via steam?", default=True)
START_PAUSED = questionary.confirm("Start the game paused?", default=True)
RUN_GAME = questionary.confirm("Run game?", default=True)
STEAM_ID_Q = questionary.text("Enter the steam game ID:", validate=_is_int)
EXE_PATH_Q = questionary.path("Enter the absolute path to the binary:")
MOD_DIR_Q = questionary.path("Enter the absolute path the mod directory")
MOD_SAVE_DIR_Q = questionary.path("Enter the absolute path the mod save directory")
LOG_DIR_Q = questionary.path("Enter the absolute path the logs directory")
CONTINUE_CONFIGURING_Q = questionary.confirm("Would you like to configure more options?", default=True)

CFG_OPT_BIN_PATH = "Set binary path"
CFG_OPT_MOD_PATH = "Set mod directory"
CFG_OPT_MOD_SAVE_PATH = "Set mod save directory"
CFG_OPT_STEAM_ID = "Configure steam game id"
CFG_OPT_LOG_PATH = "Set log directory"
CFG_OPT_START_PAUSED = "Set game to start paused"
CONFIG_SELECT_Q = questionary.select(
    "What would you like to configure?",
    choices=[
        CFG_OPT_BIN_PATH,
        CFG_OPT_MOD_PATH,
        CFG_OPT_STEAM_ID,
        CFG_OPT_LOG_PATH,
        CFG_OPT_MOD_SAVE_PATH,
        CFG_OPT_START_PAUSED,
    ],
)

# This is the name of the config file within the library.
CFG_FILENAME = "pymhf.toml"
# This is the name of the config file which will be sorted in the user data folder.
LOCAL_CFG_FILENAME = "pymhf.local.toml"


def run():
    """Main entrypoint which can be used to run programs with pymhf.
    This will take the first argument as the name of a module which has been installed.
    """
    from .utils.parse_toml import _parse_toml, read_pymhf_settings, write_pymhf_settings

    parser = argparse.ArgumentParser(
        prog="pyMHF program runner",
        description="Run the registered plugin",
    )

    command_parser = parser.add_subparsers(dest="_command")

    # `run` command parser
    run_parser = command_parser.add_parser(
        "run",
        help=(
            "Run the provided plugin name (if registered), or the provided path to a module or single-file "
            "mod."
        ),
    )
    run_parser.add_argument(
        "plugin_name",
        help=(
            "The name of the installed library to run, or the single-file script to run, or the path to a "
            "folder which contains a library to run locally."
        ),
    )

    config_parser = command_parser.add_parser(
        "config",
        help=(
            "Configure the provided plugin name (if registered), or the provided path to a module or "
            "single-file mod."
        ),
    )
    config_parser.add_argument(
        "-o",
        "--open",
        action="store_true",
        default=False,
        help="Open the directory the local config is stored at.",
    )
    config_parser.add_argument(
        "plugin_name",
        help=(
            "The name of the installed library to run, or the single-file script to run, or the path to a "
            "folder which contains a library to run locally."
        ),
    )

    init_parser = command_parser.add_parser(
        "init", help="[NOT YET IMPLEMENTED] Initialise a new empty project under the given name."
    )
    init_parser.add_argument(
        "plugin_name",
        help=(
            "The name of the installed library to run, or the single-file script to run, or the path to a "
            "folder which contains a library to run locally."
        ),
    )

    cmd_parser = command_parser.add_parser("cmd", help="Perform a registered command for the library")
    cmd_parser.add_argument(
        "command",
        help=(
            "The command to be run by the specified library. These are registered in the "
            "[project.entry-points.pymhfcmd] section of the pyproject.toml file."
        ),
    )
    cmd_parser.add_argument(
        "plugin_name",
        help=(
            "The name of the installed library to run, or the path to a folder which contains a library to "
            "run locally."
        ),
    )

    # data_parser = command_parser.add_parser(
    #     "data", help="Configure the data for the provided plugin name (if registered), or the provided path"
    #     " to a module."
    # )
    # data_parser.add_argument(
    #     "plugin_name",
    #     help=(
    #         "The name of the installed library to run, or the path to a folder which contains a library to "
    #         "run locally."
    #     ),
    # )
    # data_parser.add_argument(
    #     "-H",
    #     "--hash",
    #     action="store_true",
    #     help="Get the current binary hash",
    # )

    args, extras = parser.parse_known_args()  # noqa

    # TODO: The extras can be passed to the registered library in the future.

    plugin_name: str = args.plugin_name
    command = args._command
    if command == "run":
        mode = ModeEnum.RUN
    elif command == "config":
        mode = ModeEnum.CONFIG
    elif command == "init":
        mode = ModeEnum.INIT
    elif command == "cmd":
        mode = ModeEnum.COMMAND
    # elif command == "data":
    #     mode = ModeEnum.DATA
    else:
        mode = ModeEnum.INVALID
    standalone = False
    local = False

    if op.isfile(plugin_name) and op.exists(plugin_name):
        # In this case we are running in stand-alone mode
        standalone = True

    if op.isdir(plugin_name) and op.exists(plugin_name):
        # In this case we are running a library directly from pymhf.
        # This can be done for two reasons... We either want to actually run it, or we are configuring it.
        local = True

    if standalone:
        load_mod_file(plugin_name)
        return

    cmd_command = None
    if mode == ModeEnum.COMMAND:
        cmd_command = args.command

    if local:
        # Parse the pyproject.toml file to get some info...
        pyproject_toml = op.join(op.realpath(plugin_name), "pyproject.toml")
        local_plugin_dir = op.realpath(plugin_name)
        if not op.exists(pyproject_toml):
            print(
                f"Error: No pyproject.toml file in the directory {op.realpath(plugin_name)}. Please ensure "
                "the target project has one."
            )
            return
        settings = _parse_toml(pyproject_toml, False)
        plugin_name = None
        if (project_cfg := settings.get("project", {}).get("entry-points", {}).get("pymhflib")) is not None:
            plugin_name = list(project_cfg.keys())[0]
            if mode == ModeEnum.COMMAND:
                if (
                    command_cfg := settings.get("project", {}).get("entry-points", {}).get("pymhfcmd")
                ) is not None:
                    from .core.importing import import_file

                    if (resolved_command := command_cfg.get(cmd_command)) is not None:
                        mod = import_file(op.join(local_plugin_dir, plugin_name))
                        cmd = getattr(mod, resolved_command, None)
                        if cmd is not None:
                            cmd(extras)
                            return
                        else:
                            print(
                                f"Command {resolved_command!r} cannot be found in module {plugin_name}. "
                                "Please ensure the function exists and can be run from this module."
                            )
                            return
                    else:
                        print(f"No registered command {cmd_command!r}. Please check your configuration.")
                        return
                else:
                    print(
                        "No [project.entry-points.pymhfcmd] section found in the pyproject.toml. "
                        "Please create one to register and run custom commands."
                    )
                    return
        if plugin_name is None:
            print(
                f"Cannot determine the project at the path specified {plugin_name}.\n"
                "Please ensure the pyproject.toml file has the [project.entry-points.pymhflib] entry."
                "This process will not continue."
            )
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

    initial_config = False

    if not local:
        eps = entry_points()
        # This check is to ensure compatibility with multiple versions of python as the code 3.10+ isn't
        # backward compatible.
        if isinstance(eps, dict):
            pymhf_entry_points = eps.get("pymhflib", [])
        else:
            pymhf_entry_points = eps.select(group="pymhflib")
        if mode == ModeEnum.COMMAND:
            if isinstance(eps, dict):
                pymhf_commands = eps.get("pymhfcmd", [])
            else:
                pymhf_commands = eps.select(group="pymhfcmd")

            if not pymhf_commands:
                print(
                    "No [project.entry-points.pymhfcmd] section found in the pyproject.toml. "
                    "Please create one to register and run custom commands."
                )

        required_lib = None
        resolved_command = None

        for ep in pymhf_entry_points:
            if ep.name.lower() == plugin_name.lower():
                required_lib = ep
        if mode == ModeEnum.COMMAND:
            for cmd in pymhf_commands:
                # See if the library has a check command defined.
                if cmd.name.lower() == cmd_command:
                    resolved_command = cmd.value

        if required_lib is None:
            print(
                f"Cannot find {plugin_name} as an installed plugin. "
                "Please ensure it has been installed and try again"
            )
            return

        module_dir = op.dirname(required_lib.load().__file__)

        if mode == ModeEnum.COMMAND:
            if resolved_command is not None:
                # We can use importlib here since the library has to be installed if we have made it here.
                import importlib

                mod = importlib.import_module(plugin_name)
                cmd = getattr(mod, resolved_command, None)
                if cmd is not None:
                    cmd(extras)
                    return
                else:
                    print(
                        f"Command {resolved_command!r} cannot be found in module {plugin_name}. "
                        "Please ensure the function exists and can be run from this module."
                    )
                    return
            else:
                print(f"No registered command {cmd_command!r}. Please check your configuration.")
                return

    else:
        module_dir = op.join(local_plugin_dir, plugin_name)

    cfg_file = op.join(module_dir, CFG_FILENAME)
    config_progress_file = op.join(cfg_folder, ".config_in_progress")
    if not op.exists(cfg_file):
        print(
            f"Cannot find `{CFG_FILENAME}` for {plugin_name}! This is likely an error on the maintainers' "
            "behalf.\nCannot continue loading until this is fixed."
        )
        return
    else:
        dst = op.join(cfg_folder, LOCAL_CFG_FILENAME)
        if not op.exists(dst) or op.exists(config_progress_file):
            # In this case we can prompt the user to enter the config values which need to be changed.
            initial_config = True

    if initial_config:
        local_config = {"local_config": {}}
        if not has_tkinter:
            print(
                "tkinter cannot be found. Please ensure it's installed as part of your python install.\n"
                "Falling back to the command-line method of providing an input."
            )
        # Copy the config file to the appdata directory.
        shutil.copyfile(cfg_file, dst)
        # Write the file which indicates we are in progress.
        with open(config_progress_file, "w") as f:
            f.write("")
        # pymhf_settings = read_pymhf_settings(cfg_file)

        # Modify some of the values in the config file, allowing the user to enter the values they want.
        if has_tkinter:
            root = Tk()
            root.withdraw()
        if (
            mod_folder := get_folder("Select folder where mods are located", MOD_DIR_Q, has_tkinter)
        ) is not None:
            local_config["local_config"]["mod_dir"] = mod_folder
        else:
            return None

        # Write the config back and then delete the temporary file only once everything is ok.
        write_pymhf_settings(local_config, dst)
        os.remove(config_progress_file)
        initial_config = False
    elif mode == ModeEnum.CONFIG:
        if args.open:
            print(f"Opening {cfg_folder!r} and exiting")
            subprocess.call(f'explorer "{cfg_folder}"')
            return
        local_config = read_pymhf_settings(dst)
        pymhf_settings = local_config["local_config"]
        keep_going = True
        if has_tkinter:
            root = Tk()
            root.withdraw()
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
                if (
                    mod_dir := get_folder("Select folder where mods can be found", MOD_DIR_Q, has_tkinter)
                ) is not None:
                    pymhf_settings["mod_dir"] = mod_dir
                else:
                    return None
            elif config_choice == CFG_OPT_START_PAUSED:
                if (start_paused := START_PAUSED.ask()) is not None:
                    pymhf_settings["start_paused"] = start_paused
                else:
                    return
            elif config_choice == CFG_OPT_LOG_PATH:
                if (
                    log_dir := get_folder("Select folder where logs are placed", LOG_DIR_Q, has_tkinter)
                ) is not None:
                    pymhf_settings["log_dir"] = log_dir
                else:
                    return None
            elif config_choice == CFG_OPT_MOD_SAVE_PATH:
                if (
                    msd := get_folder("Select folder where mod saves are placed", MOD_SAVE_DIR_Q, has_tkinter)
                ) is not None:
                    pymhf_settings["mod_save_dir"] = msd
                else:
                    return None
            elif config_choice is None:
                keep_going = False

            keep_going = CONTINUE_CONFIGURING_Q.ask()
            if keep_going is None:
                return
        local_config["local_config"] = pymhf_settings
        write_pymhf_settings(local_config, dst)

        if not RUN_GAME.ask():
            return
    # Final step: If we have either finished the initial config, or we didn't want to config at all, run the
    # binary.
    if not initial_config:
        load_module(plugin_name, module_dir)
