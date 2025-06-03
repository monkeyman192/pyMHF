import asyncio
import concurrent.futures
import os
import os.path as op
import subprocess
import time
import webbrowser
from functools import partial
from signal import SIGTERM
from typing import Any, Optional

import psutil
import pymem
import pymem.exception
import pymem.process

from pymhf.core._internal import LoadTypeEnum
from pymhf.core.caching import hash_bytes
from pymhf.core.logging import open_log_console
from pymhf.core.process import start_process
from pymhf.core.protocols import ESCAPE_SEQUENCE, TerminalProtocol
from pymhf.utils.config import canonicalize_setting
from pymhf.utils.parse_toml import read_pymhf_settings
from pymhf.utils.winapi import get_exe_path_from_pid

CWD = op.dirname(__file__)
PYMHF_DIR = op.dirname(CWD)
APPDATA_DIR = os.environ.get("APPDATA", op.expanduser("~"))


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
            pymem.ressources.kernel32.ResumeThread(self.thread_handle)


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
    cmd: str,
    target: str,
    required_assemblies: Optional[list[str]] = None,
    is_steam: bool = True,
    start_paused: bool = False,
):
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
    if parent_process is not None:
        if is_steam:
            # For steam games, if we have the game ID then the cmd will be
            # steam://rungameid/{game id} which we need to invoke this way.
            print("Running from steam")
            webbrowser.open(cmd)
        else:
            subprocess.run(cmd)
        while run:
            try:
                if target_process is None:
                    for child in parent_process.children(recursive=True):
                        if child.name() == target:
                            target_process = WrappedProcess(proc=child)
                else:
                    binary = pymem.Pymem(target)
                    modules = list(pymem.process.enum_process_module(binary.process_handle))
                    if len(modules) > 0:
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
        process_handle, thread_handle, pid, tid = start_process(  # noqa
            cmd, creationflags=creationflags
        )
        target_process = WrappedProcess(thread_handle=thread_handle)

    if target_process is not None:
        binary = pymem.Pymem(target)
        # TODO: We can inject python in really early since any loaded dll's will persist through steam's
        # forking process.
        try:
            binary.inject_python_interpreter()
        except pymem.exception.MemoryWriteError:
            print("Failed to inject python for some reason... Trying again in 2 seconds")
            time.sleep(2)
            binary.inject_python_interpreter()
        print(f"Python injected into pid {binary.process_id}")
        if start_paused:
            target_process.suspend()

        return binary, target_process
    else:
        return None, None


def load_mod_file(filepath):
    """Load an individual file as a mod."""
    pymhf_settings = read_pymhf_settings(filepath, True)
    _run_module(filepath, pymhf_settings, None, None)


def load_module(plugin_name: str, module_path: str):
    """Load the module."""
    config_dir = op.join(APPDATA_DIR, "pymhf", plugin_name)
    local_cfg_file = op.join(config_dir, "pymhf.local.toml")
    if op.exists(local_cfg_file):
        local_cfg = read_pymhf_settings(local_cfg_file).get("local_config", {})
    else:
        local_cfg = {}
    module_cfg_file = op.join(module_path, "pymhf.toml")
    module_cfg = read_pymhf_settings(module_cfg_file)
    module_cfg.update(local_cfg)
    _run_module(module_path, module_cfg, plugin_name, config_dir)


def _required_config_val(config: dict[str, str], key: str) -> Any:
    if (val := config.get(key)) is not None:
        return val
    raise ValueError(f"[tool.pymhf] missing config value: {key}")


def _run_module(
    module_path: str,
    config: dict[str, str],
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
    binary_exe = _required_config_val(config, "exe")
    required_assemblies = []
    required_assemblies = config.get("required_assemblies", [])
    start_exe = config.get("start_exe", True)
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
        cmd = f"steam://rungameid/{steam_gameid}"
        is_steam = True
    else:
        if op.isabs(binary_exe):
            cmd = binary_path = binary_exe
            # We only need the binary_exe to be the name from here on.
            binary_exe = op.basename(binary_exe)
        else:
            # TODO: Allow support for running local binaries or binaries which are on the path.
            raise ValueError("[tool.pymhf].exe must be a full path if no steam_gameid is provided.")

    if start_exe:
        # Check to see fi the binary is already running... Just in case.
        # If it is, we use it, otherwise start it.
        try:
            pm_binary = pymem.Pymem(binary_exe)
            print(f"Found an already running instance of {binary_exe!r}")
            pm_binary.inject_python_interpreter()
            print("Python injected")
            proc = None
        except pymem.exception.ProcessNotFound:
            pm_binary, proc = get_process_when_ready(
                cmd,
                binary_exe,
                required_assemblies,
                is_steam,
                start_paused,
            )
    else:
        # If we aren't starting the exe then by the time we have run we expect the process to already exist,
        # so just find it with pymem.
        pm_binary = pymem.Pymem(binary_exe)
        pm_binary.inject_python_interpreter()
        print("Python injected")
        proc = None

    if not pm_binary and not proc:
        # TODO: Raise better error messages/reason why it couldn't load.
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
    log_dir = logging_config.get("log_dir", "{CURR_DIR}")
    log_dir = canonicalize_setting(log_dir, plugin_name, _module_path, binary_dir, "LOGS")

    mod_save_dir = config.get("mod_save_dir", "{CURR_DIR}")
    mod_save_dir = canonicalize_setting(mod_save_dir, plugin_name, _module_path, binary_dir, "MOD_SAVES")

    executor = None
    futures = []
    loop = asyncio.get_event_loop()

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
        log_pid = open_log_console(op.join(CWD, "log_terminal.py"), log_dir, log_window_name_override)
        # Have a small nap just to give it some time.
        time.sleep(0.5)
        print(f"Opened the console log with PID: {log_pid}")
        if binary_path:
            with open(binary_path, "rb") as f:
                binary_hash = hash_bytes(f)
            print(f"Exe hash is: {binary_hash}")
        else:
            binary_hash = 0

        def close_callback(x):
            print("pyMHF exiting...")
            for _pid in {pm_binary.process_id, log_pid}:
                try:
                    os.kill(_pid, SIGTERM)
                except Exception:
                    # If we can't kill it, it's probably already dead. Just continue.
                    pass
            # Finally, send a SIGTERM to ourselves...
            os.kill(os.getpid(), SIGTERM)

        # Wait some time for the data to be written to memory.
        time.sleep(3)

        print(f"proc id from pymem: {pm_binary.process_id}")
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

            saved_path = [x.replace("\\", "\\\\") for x in _path]
            pm_binary.inject_python_shellcode(
                f"""
import sys
sys.path = {saved_path}
                """
            )

            with open(op.join(CWD, "_preinject.py"), "r") as f:
                _preinject_shellcode = f.read()
            pm_binary.inject_python_shellcode(_preinject_shellcode)
            # Inject the common NMS variables which are required for general use.
            module_path = op.realpath(module_path)
            module_path = module_path.replace("\\", "\\\\")
            pm_binary.inject_python_shellcode(
                f"""
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
                """
            )
        except Exception as e:
            import traceback

            print(e)
            print(traceback.format_exc())
        # Inject the script
        with open(op.join(CWD, "injected.py"), "r") as f:
            shellcode = f.read()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        print(f"Injecting hooking code into proc id {pm_binary.process_id}")
        fut = executor.submit(pm_binary.inject_python_shellcode, shellcode)
        fut.add_done_callback(lambda x: close_callback(x))
        futures.append(fut)

        # Wait for a user input to start the process.
        # TODO: Send a signal back up from the process to trigger this automatically.
        if start_paused and start_exe is not False:
            try:
                #     # print("Checking to see if we are ready to run...")
                #     # client_completed = asyncio.Future()
                #     # client_factory = partial(
                #     #     TerminalProtocol,
                #     #     message=READY_ASK_SEQUENCE,
                #     #     future=client_completed
                #     # )
                #     # print("A")
                #     # factory_coroutine = loop.create_connection(
                #     #     client_factory,
                #     #     '127.0.0.1',
                #     #     6770,
                #     # )
                #     # print("B")
                #     # loop.run_until_complete(factory_coroutine)
                #     # print("C")
                #     # loop.run_until_complete(client_completed)

                input("Press something to start binary")
            except KeyboardInterrupt:
                # Kill the injected code so that we don't wait forever for the future to end.
                kill_injected_code(loop)
                raise
            proc.resume()

        print("pyMHF interactive python command prompt")
        print("Type any valid python commands to execute them within the games' process")
        # TODO: change this to use a threading.Event object, and in a separate thread, poll every second or so
        # the running game process to see if it's still running (using psutil?)
        # Might need to modify the WrappedProcess object to always create the pstuil.Process object to make it
        # work easier...

        # TODO: This should become False when we exit form the program...
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
                kill_injected_code(loop)
                raise
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
            for future in concurrent.futures.as_completed(futures, timeout=5):
                print(future)
        except TimeoutError:
            # Don't really care.
            print("Got a time out error...")
            pass
        if executor is not None:
            executor.shutdown(wait=False)
        try:
            with open(op.join(CWD, "end.py"), "r") as f:
                close_shellcode = f.read()
            pm_binary.inject_python_shellcode(close_shellcode)
            print("Just injected the close command?")
            # Kill the process.
        except Exception:
            pass
        finally:
            print("Forcibly shutting down process")
            time.sleep(1)
            for _pid in {pm_binary.process_id, log_pid}:
                if _pid:
                    try:
                        os.kill(_pid, SIGTERM)
                        print(f"Just killed process {_pid}")
                    except Exception:
                        # If we can't kill it, it's probably already dead. Just continue.
                        print(f"Failed to kill process {_pid}. It was likely already dead...")
                        pass
