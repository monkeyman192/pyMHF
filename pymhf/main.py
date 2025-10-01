import asyncio
import concurrent.futures
import glob
import os
import os.path as op
import subprocess
import time
import webbrowser
from functools import partial
from signal import SIGTERM
from threading import Event
from typing import Optional

import psutil
import pymem
import pymem.exception
import pymem.process
import pymem.ressources.kernel32
import pyrun_injected.dllinject as dllinject

from pymhf.core._types import LoadTypeEnum, pymhfConfig
from pymhf.core.hashing import hash_bytes_from_file, hash_bytes_from_memory
from pymhf.core.importing import parse_file_for_mod
from pymhf.core.log_handling import open_log_console
from pymhf.core.process import start_process
from pymhf.core.protocols import ESCAPE_SEQUENCE, TerminalProtocol
from pymhf.utils.config import canonicalize_setting
from pymhf.utils.parse_toml import read_pymhf_settings
from pymhf.utils.winapi import get_exe_path_from_pid

CWD = op.dirname(__file__)
PYMHF_DIR = op.dirname(CWD)
APPDATA_DIR = os.environ.get("APPDATA", op.expanduser("~"))

# Flag indicating whether to kill our own pid.
# This should generally be true except when running tests otherwise it will kill the test runner.
REMOVE_SELF = True
END_EVENT = Event()


class WrappedProcess:
    def __init__(self, proc: Optional[psutil.Process] = None, thread_handle: Optional[int] = None):
        self.proc = proc
        self.thread_handle = thread_handle
        self._is_self_started = False
        if self.thread_handle is not None:
            self._is_self_started = True

    def suspend(self):
        if self.proc is not None:
            self.proc.suspend()

    def resume(self):
        if self.proc is not None:
            self.proc.resume()
        else:
            pymem.ressources.kernel32.ResumeThread(self.thread_handle)  # type: ignore


class pymhfExitException(Exception):
    pass


def _wait_until_process_running(target: str):
    run = True
    while run:
        try:
            for p in psutil.process_iter(["name", "pid"]):
                if p.name().lower() == target.lower():
                    return WrappedProcess(proc=p)
        except KeyboardInterrupt:
            return None


def get_process_when_ready(
    cmd: list[str],
    target: str,
    required_assemblies: Optional[list[str]] = None,
    is_steam: bool = True,
    start_paused: bool = False,
) -> tuple[Optional[dllinject.pyRunner], Optional[WrappedProcess]]:
    target_process: Optional[WrappedProcess] = None
    parent_process = None
    # If we are running something which is under steam, make sure steam is
    # running first.
    if is_steam:
        for p in psutil.process_iter(["name", "pid"]):
            if p.name().lower() == "steam.exe":
                parent_process = p
                break
        if parent_process is None:
            raise ProcessLookupError("Steam not running! For now, start it yourself and try again...")

    run = True
    found_pid = None
    if parent_process is not None:
        if is_steam:
            # For steam games, if we have the game ID then the cmd will be
            # steam://rungameid/{game id} which we need to invoke this way.
            print("Running from steam")
            # We can only run the first argument in the list with steam unfortunately...
            webbrowser.open(cmd[0])
        else:
            subprocess.run(cmd)
        while run:
            try:
                if target_process is None:
                    for child in parent_process.children(recursive=True):
                        if child.name() == target:
                            target_process = WrappedProcess(proc=child)
                else:
                    binary = pymem.Pymem(target, exact_match=True)
                    modules = list(pymem.process.enum_process_module(binary.process_handle))
                    if len(modules) > 0 and required_assemblies is not None:
                        if set(required_assemblies) <= set(x.name for x in modules):
                            run = False
                            break
            except KeyboardInterrupt:
                raise
            except psutil.NoSuchProcess:
                # Race-condition case where steam creates some short-lived process which dies before psutil
                # can handle it properly.
                pass
    else:
        creationflags = 0x4 if start_paused else 0
        process_handle, thread_handle, found_pid, tid = start_process(  # noqa
            cmd, creationflags=creationflags
        )
        target_process = WrappedProcess(thread_handle=thread_handle)

    if target_process is not None:
        if found_pid is not None:
            binary = pymem.Pymem(found_pid)
        else:
            binary = pymem.Pymem(target, exact_match=True)
        injected = dllinject.pyRunner(binary)
        if start_paused:
            target_process.suspend()

        return injected, target_process
    else:
        return None, None


def load_mod_file(filepath: str, config_overrides: Optional[pymhfConfig] = None):
    """Load an individual file as a mod.

    Parameters
    ----------
    filepath
        The relative or absolute filepath to a single python file to be loaded as a mod.
        It is generally recommended to pass an absolute path as it will be more reliable.
    config_overrides
        An optional dictionary containing values which will override any existing config values read from the
        specified file.
    """
    pymhf_settings = read_pymhf_settings(filepath, True)
    if config_overrides:
        pymhf_settings.update(config_overrides)
    run_module(filepath, pymhf_settings, None, None)


def load_module(plugin_name: str, module_path: str):
    """Load a module.
    This should be used when loading an entire folder or a plugin based on name.
    """
    config_dir = op.join(APPDATA_DIR, "pymhf", plugin_name)
    local_cfg_file = op.join(config_dir, "pymhf.local.toml")
    if op.exists(local_cfg_file):
        local_cfg = read_pymhf_settings(local_cfg_file).get("local_config", {})
    else:
        local_cfg = {}
    module_cfg_file = op.join(module_path, "pymhf.toml")
    module_cfg = read_pymhf_settings(module_cfg_file)
    module_cfg.update(local_cfg)
    run_module(module_path, module_cfg, plugin_name, config_dir)


def run_module(
    module_path: str,
    config: pymhfConfig,
    plugin_name: Optional[str] = None,
    config_dir: Optional[str] = None,
):
    """Run the module provided.

    Parameters
    ----------
    module_path
        The path to the module or single-file mod to be run.
    config
        A mapping of the associated pymhf config.
    plugin_name
        The name of the plugin. This will only be provided if we are running a library.
    config_dir
        The local config directory. This will only be provided if we are running a library.
    """
    if plugin_name is None:
        if op.isfile(module_path):
            load_type = LoadTypeEnum.SINGLE_FILE
        if op.exists(op.join(module_path, "pymhf.toml")):
            load_type = LoadTypeEnum.MOD_FOLDER
    else:
        load_type = LoadTypeEnum.LIBRARY

    binary_path = None
    injected = None
    binary_exe = config.get("exe", None)
    required_assemblies = []
    cmd: list[str] = []
    required_assemblies = config.get("required_assemblies", [])
    start_exe = config.get("start_exe", True)
    cmd_args = config.get("args", [])
    if not isinstance(cmd_args, list):
        print(f"Warning: The provided args value {cmd_args!r} is not valid. It must be a list.")
        cmd_args = []
    # Ensure each value is a string.
    for i, _arg in enumerate(cmd_args):
        cmd_args[i] = str(_arg)
    to_load_pid: Optional[int] = config.get("pid", None)
    interactive_console = config.get("interactive_console", True)
    logging_config = config.get("logging", {}) or {}
    show_log_window = logging_config.get("shown", True)
    if to_load_pid is None and binary_exe is None:
        raise ValueError("[tool.pymhf] requires either an `exe` or `pid` value.")
    if binary_exe is None and start_exe is True:
        raise ValueError("[tool.pymhf] requires `exe` to be set if `start_exe = true`")
    try:
        steam_gameid = int(config.get("steam_gameid", 0))
    except (ValueError, TypeError):
        steam_gameid = 0
    start_paused = config.get("start_paused", False)

    if config_dir is None:
        cache_dir = op.join(module_path, ".cache")
    else:
        cache_dir = op.join(config_dir, ".cache")

    # Check if the module_path is a file or a folder.
    _module_path = module_path
    if op.isfile(module_path):
        _module_path = op.dirname(module_path)

    is_steam = False
    if steam_gameid:
        cmd = [f"steam://rungameid/{steam_gameid}"]
        is_steam = True
    elif binary_exe is not None:
        if op.isabs(binary_exe):
            binary_path = binary_exe
            cmd = [binary_path]
            # We only need the binary_exe to be the name from here on.
            binary_exe = op.basename(binary_exe)
        else:
            # Try and create the path relative to the provided module path.
            _trial_path = op.realpath(op.join(_module_path, binary_exe))
            if op.exists(_trial_path):
                binary_path = _trial_path
                cmd = [binary_path]
                binary_exe = op.basename(binary_path)
            else:
                if start_exe is True:
                    raise ValueError(
                        "[tool.pymhf].exe must be a full path or path relative to the running script if no "
                        "steam_gameid is provided and start_exe is not true"
                    )
                else:
                    pass

    if start_exe and binary_exe is not None:
        # Check to see fi the binary is already running... Just in case.
        # If it is, we use it, otherwise start it.
        try:
            pm_binary = pymem.Pymem(binary_exe, exact_match=True)
            print(f"Found an already running instance of {binary_exe!r}")
            injected = dllinject.pyRunner(pm_binary)
            print("Python injected")
            proc = None
        except (pymem.exception.ProcessNotFound, pymem.exception.CouldNotOpenProcess):
            injected, proc = get_process_when_ready(
                cmd + cmd_args,
                binary_exe,
                required_assemblies,
                is_steam,
                start_paused,
            )
    else:
        # If we aren't starting the exe then by the time we have run we expect the process to already exist,
        # so just find it with pymem.
        if binary_exe is not None:
            pm_binary = pymem.Pymem(binary_exe, exact_match=True)
            injected = dllinject.pyRunner(pm_binary)
            print("Python injected")
            proc = None
        else:
            pm_binary = pymem.Pymem(to_load_pid)  # type: ignore  (pymem has the wrong type...)
            injected = dllinject.pyRunner(pm_binary)
            print("Python injected")
            proc = None

    if injected is None:
        # TODO: Raise better error messages/reason why it couldn't load.
        print("FATAL ERROR: Cannot start process!")
        return
    if injected.pm is None:
        print("FATAL ERROR: Cannot start process!")
        return

    pm_binary = injected.pm
    if pm_binary.process_id is None:
        print("FATAL ERROR: Cannot start process!")
        return

    if binary_path is None:
        binary_path = get_exe_path_from_pid(pm_binary)

    binary_dir = None
    if binary_path is not None:
        binary_dir = op.dirname(binary_path)

    print(f"Found PID: {pm_binary.process_id}")

    log_pid = None
    logging_config = config.get("logging", {})
    log_window_name_override = logging_config.get("window_name_override", "pymhf console")
    _log_dir = logging_config.get("log_dir", "{CURR_DIR}")
    log_dir = canonicalize_setting(_log_dir, plugin_name, _module_path, binary_dir, "logs")
    if log_dir is None and binary_dir is not None:
        log_dir = op.join(binary_dir, "LOGS")
    if log_dir is None:
        print(f"Unable to determine a location to put logs from {_log_dir}. No logs will be saved!")

    mod_save_dir = config.get("mod_save_dir", "{CURR_DIR}")
    mod_save_dir = canonicalize_setting(mod_save_dir, plugin_name, _module_path, binary_dir, "MOD_SAVES")

    executor = None
    futures = []
    try:
        loop = asyncio.get_event_loop()
    except (RuntimeError, ValueError):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    def kill_injected_code(loop: asyncio.AbstractEventLoop):
        # End one last "escape sequence" message:
        client_completed = asyncio.Future()
        client_factory = partial(TerminalProtocol, message=ESCAPE_SEQUENCE.decode(), future=client_completed)
        factory_coroutine = loop.create_connection(
            client_factory,
            "127.0.0.1",
            6770,
        )
        loop.run_until_complete(factory_coroutine)
        loop.run_until_complete(client_completed)

    try:
        if log_dir and show_log_window:
            log_pid = open_log_console(op.join(CWD, "log_terminal.py"), log_dir, log_window_name_override)
        # Have a small nap just to give it some time.
        time.sleep(0.5)
        if binary_path:
            try:
                with open(binary_path, "rb") as f:
                    binary_hash = hash_bytes_from_file(f)
            except PermissionError:
                print(f"Cannot open {binary_path!r} to hash it. Trying to read from memory...")
                binary_hash = hash_bytes_from_memory(pm_binary)
            print(f"Exe hash is: {binary_hash}")
        else:
            binary_hash = 0

        def close_callback(x):
            print("pyMHF exiting...")
            for _pid in {pm_binary.process_id, log_pid}:
                if _pid:
                    try:
                        os.kill(_pid, SIGTERM)
                    except Exception:
                        # If we can't kill it, it's probably already dead. Just continue.
                        pass
            END_EVENT.set()
            # Finally, send a SIGTERM to ourselves...
            if REMOVE_SELF:
                os.kill(os.getpid(), SIGTERM)

        # Wait some time for the data to be written to memory only if we are starting the process ourselves.
        if start_exe:
            time.sleep(2)

        offset_map = {}
        # This is a mapping of the required assemblies to their filenames so we may do an import look up on
        # the inside.
        included_assemblies = {}
        modules = []
        if required_assemblies:
            modules = list(pm_binary.list_modules())
            found_modules = list(filter(lambda x: x.name in required_assemblies, modules))
            if not found_modules:
                print(f"Cannot find specified assembly from config ({required_assemblies})")
                return
            for module in found_modules:
                offset_map[module.name] = (module.lpBaseOfDll, module.SizeOfImage)
                included_assemblies[module.name] = module.filename
        else:
            pb = pm_binary.process_base
            offset_map[binary_exe] = (pb.lpBaseOfDll, pb.SizeOfImage)
        # if not modules:
        #     modules = pm_binary.list_modules()
        # for module in modules:
        #     included_assemblies[module.name] = module.filename
        # print(f"The handle: {pm_binary.process_handle}, bases: {offset_map}")

        if len(offset_map) == 1:
            # Only one thing. For now, we just set these as the `binary_base` and `binary_size`.
            # TODO: When we want to support offsets and hooks in multiple assemblies we need to pass the whole
            # dictionary in potentially, or do a lookup from inside the process.
            assem_name = list(offset_map.keys())[0]
            binary_base = offset_map[assem_name][0]
            binary_size = offset_map[assem_name][1]

        try:
            cwd = CWD.replace("\\", "\\\\")
            import sys

            _path = sys.path
            _path.insert(0, PYMHF_DIR)

            # Inject the folder the mod is in (or the folder being run) if it's not already in the sys.path
            if load_type == LoadTypeEnum.SINGLE_FILE:
                _mod_dir = op.dirname(module_path)
                if _mod_dir not in _path:
                    _path.insert(0, _mod_dir)
            if load_type == LoadTypeEnum.MOD_FOLDER:
                if module_path not in _path:
                    _path.insert(0, module_path)
            if load_type == LoadTypeEnum.LIBRARY:
                # For libraries, the module_path will be the directory where the pymhf.toml file is located
                # which is one path deeper than we want to inject into the path.
                if (mp := op.dirname(module_path)) not in _path:
                    _path.insert(0, mp)
                # Also add the mod directory to the path.
                _mod_folder = config.get("mod_dir")
                mod_folder = canonicalize_setting(_mod_folder, "pymhf", _module_path, binary_dir)
                if _mod_folder and not mod_folder:
                    # In this case the directory for the mod folder doesn't actually exist. Log the steps
                    # required to re-configure.
                    print(
                        f"[ERROR] Mod folder can't be found or resolved: {_mod_folder}.\n"
                        "[ERROR] Please reconfigure the path by running `pymhf config <library or path>` and "
                        "then selecting 'Set mod directory'."
                    )
                    sys.exit(0)
                if mod_folder:
                    if mod_folder not in _path:
                        _path.insert(0, mod_folder)
                    # Loop over each of the direct descendents of the mod folder and see if each folder
                    # contains any mods.
                    # If it does, then inject that directory into the path.
                    for _fpath in os.listdir(mod_folder):
                        fpath = op.join(mod_folder, _fpath)
                        if op.isdir(fpath):
                            for pyfile in glob.iglob(op.join(fpath, "*.py")):
                                with open(pyfile, "r") as f:
                                    if parse_file_for_mod(f.read()):
                                        # Once we know that at least one file contains a mod, stop iterating
                                        # and add the folder to the path.
                                        if fpath not in _path:
                                            _path.insert(0, fpath)
                                        break
            saved_path = [x.replace("\\", "\\\\") for x in _path]

            injected_data_list = []

            # Inject the new path
            sys_path_str = f"""
import sys
sys.path = {saved_path}
"""
            injected_data_list.append(dllinject.StringType(sys_path_str, False))

            # Inject our preinject script.
            injected_data_list.append(dllinject.StringType(op.join(CWD, "_preinject.py"), True))

            # Allocate a boolean value which will be set to True by the injected code once it has completed.
            sentinel_addr = pm_binary.allocate(4)
            pm_binary.write_bool(sentinel_addr, False)

            # Inject the common NMS variables which are required for general use.
            internals_str = f"""
pymhf.core._internal.MODULE_PATH = {module_path!r}
pymhf.core._internal.BASE_ADDRESS = {binary_base!r}
pymhf.core._internal.SIZE_OF_IMAGE = {binary_size!r}
pymhf.core._internal.CWD = {cwd!r}
pymhf.core._internal.PID = {pm_binary.process_id!r}
pymhf.core._internal.HANDLE = {pm_binary.process_handle!r}
pymhf.core._internal.BINARY_HASH = {binary_hash!r}
pymhf.core._internal.CONFIG = {config!r}
pymhf.core._internal.EXE_NAME = {binary_exe!r}
pymhf.core._internal.BINARY_PATH = {binary_path!r}
pymhf.core._internal.LOAD_TYPE = {load_type.value!r}
pymhf.core._internal.MOD_SAVE_DIR = {mod_save_dir!r}
pymhf.core._internal.INCLUDED_ASSEMBLIES = {included_assemblies!r}
pymhf.core._internal.CACHE_DIR = {cache_dir!r}
pymhf.core._internal._SENTINEL_PTR = {sentinel_addr!r}
                """
            injected_data_list.append(dllinject.StringType(internals_str, False))
        except Exception as e:
            import traceback

            print(e)
            print(traceback.format_exc())
        # Inject the script
        injected_data_list.append(dllinject.StringType(op.join(CWD, "injected.py"), True))
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        fut = executor.submit(injected.run_data, injected_data_list)
        fut.add_done_callback(lambda x: close_callback(x))
        futures.append(fut)

        # Wait for the injected process to indicate that it's ready to go.
        if start_paused and start_exe is not False:
            while True:
                try:
                    if pm_binary.read_bool(sentinel_addr) is True:
                        print("pyMHF injection complete!")
                        break
                except KeyboardInterrupt:
                    # Kill the injected code even though we are still waiting for it to start up.
                    kill_injected_code(loop)
                    raise
                except pymem.exception.MemoryReadError:
                    # In this case the process has probably already died for some reason...
                    # Set END_EVENT so that we just initiate the shutdown process.
                    END_EVENT.set()
            if proc is not None:
                proc.resume()
                print("Press CTRL+C to exit the process:\n")

        if interactive_console:
            print("pyMHF interactive python command prompt")
            print("Type any valid python commands to execute them within the games' process")
            # TODO: change this to use a threading.Event object, and in a separate thread, poll every second
            # or so the running game process to see if it's still running (using psutil?)
            # Might need to modify the WrappedProcess object to always create the pstuil.Process object to
            # make it work easier...

            # TODO: This should become False when we exit from the program...
            while True:
                try:
                    input_ = input(">>> ")
                    client_completed = asyncio.Future()
                    client_factory = partial(TerminalProtocol, message=input_, future=client_completed)
                    factory_coroutine = loop.create_connection(
                        client_factory,
                        "127.0.0.1",
                        6770,
                    )
                    loop.run_until_complete(factory_coroutine)
                    loop.run_until_complete(client_completed)
                except KeyboardInterrupt:
                    break
            kill_injected_code(loop)
        else:
            while True:
                # Wait until the end event is triggered. As soon as it is this loop will exit.
                try:
                    if END_EVENT.wait(2) is True:
                        break
                except KeyboardInterrupt:
                    break
            kill_injected_code(loop)
    except KeyboardInterrupt:
        # If it's a keyboard interrupt, just pass as it will have bubbled up from
        # below.
        pass
    except Exception as e:
        # Any other exception we want to actually know about.
        import traceback

        print(e)
        print(traceback.format_exc())
        raise
    finally:
        loop.close()
        try:
            for _ in concurrent.futures.as_completed(futures, timeout=5):
                pass
        except TimeoutError:
            # Don't really care.
            print("Got a time out error...")
            pass
        if executor is not None:
            executor.shutdown(wait=False)

        # Have a short nap and then finish trying to clean up.
        time.sleep(0.5)
        if REMOVE_SELF:
            pids = {pm_binary.process_id, log_pid}
        else:
            pids = {
                log_pid,
            }
        for _pid in pids:
            if _pid:
                try:
                    os.kill(_pid, SIGTERM)
                    print(f"Just killed process {_pid}")
                except Exception:
                    # If we can't kill it, it's probably already dead. Just continue.
                    print(f"Failed to kill process {_pid}. It was likely already dead...")
                    pass
