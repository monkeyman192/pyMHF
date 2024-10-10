import asyncio
import concurrent.futures
import configparser
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

from pymhf.core.caching import hash_bytes
from pymhf.core.logging import open_log_console
from pymhf.core.process import start_process
from pymhf.core.protocols import ESCAPE_SEQUENCE, TerminalProtocol
from pymhf.utils.parse_toml import get_pymhf_settings, read_toml

CWD = op.dirname(__file__)


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
        print("Python injected")
        if start_paused:
            target_process.suspend()

        return binary, target_process
    else:
        return None, None


def load_mod_file(filepath):
    with open(filepath, "r") as f:
        pymhf_settings = get_pymhf_settings(f.read())
    _run_module(filepath, pymhf_settings)


def new_load_module(plugin_name: str, module_path: str, is_local: bool = False):
    if not is_local:
        appdata_data = os.environ.get("APPDATA", op.expanduser("~"))
        cfg_folder = op.join(appdata_data, "pymhf", plugin_name)
        cfg_file = op.join(cfg_folder, "pymhf.toml")
    else:
        cfg_folder = module_path
        cfg_file = op.join(module_path, "pymhf.toml")
    _ = read_toml(cfg_file)


# TODO: Move most of the following code into a separate private function which can be called from
# `load_mod_file` and what `load_module` will become.
# This function needs an extra arg which relates to the fact that it's loading a single file potentailly?
# Or have it pass in some other info?
# Potentially we can disambiguate by checking to see if we are provided a module or a single file when called.
# That might just be pre-processing, and then once we have determined whether it's a module or single file
# then we can pass some piece of into into the subsequent function call.


def load_module(plugin_name: str, module_path: str, is_local: bool = False):
    """Load the module."""
    # Parse the config file first so we can load anything we need to know.
    config = configparser.ConfigParser()
    # If we are not running local, then we try find the config file in the user APPDATA directory.
    if not is_local:
        appdata_data = os.environ.get("APPDATA", op.expanduser("~"))
        cfg_folder = op.join(appdata_data, "pymhf", plugin_name)
        cfg_file = op.join(cfg_folder, "pymhf.cfg")
    else:
        cfg_folder = module_path
        cfg_file = op.join(module_path, "pymhf.cfg")
    read = config.read(cfg_file)
    if not read:
        print(f"No pymhf.cfg file found in specified directory: {module_path}")
        print("Cannot proceed with loading")
        return
    pymhf_config = {s: dict(config.items(s)) for s in config.sections()}
    _run_module(pymhf_config)


def _required_config_val(config: dict[str, str], key: str) -> Any:
    if (val := config.get(key)) is not None:
        return val
    raise ValueError(f"[tool.pymhf] missing config value: {key}")


def _run_module(module_path: str, config: dict[str, str]):
    """Run the module provided.

    Parameters
    ----------
    module_path
        The path to the module or single-file mod to be run.
    config
        A mapping of the associated pymhf config.
    """
    single_file_mod = False
    if op.isfile(module_path):
        single_file_mod = True

    binary_path = None
    binary_exe = _required_config_val(config, "exe")
    required_assemblies = []
    required_assemblies = config.get("required_assemblies", [])
    try:
        steam_gameid = int(config.get("steam_gameid", 0))
    except (ValueError, TypeError):
        steam_gameid = 0
    start_paused = config.get("start_paused", False)

    mod_save_dir = config.get("mod_save_dir", op.join(module_path, "MOD_SAVES"))
    if mod_save_dir == ".":
        mod_save_dir = op.join(module_path, "MOD_SAVES")

    logging_config = config.get("logging", {})
    log_window_name_override = logging_config.get("window_name_override", "pymhf console")
    log_dir = logging_config.get("log_dir", op.join(module_path, "LOGS"))
    if log_dir == ".":
        if op.isdir(module_path):
            log_dir = op.join(module_path, "LOGS")
        elif op.isfile(module_path):
            log_dir = op.join(op.dirname(module_path), "LOGS")

    is_steam = False
    if steam_gameid:
        cmd = f"steam://rungameid/{steam_gameid}"
        is_steam = True
    else:
        if op.isdir(binary_exe):
            cmd = binary_path = binary_exe
            # We only need the binary_exe to be the name from here on.
            binary_exe = op.basename(binary_exe)
        else:
            raise ValueError("[tool.pymhf].exe must be a full path if no steam_gameid is provided.")

    pm_binary, proc = get_process_when_ready(cmd, binary_exe, required_assemblies, is_steam, start_paused)

    if not pm_binary or not proc:
        # TODO: Raise better error messages/reason why it couldn't load.
        print("FATAL ERROR: Cannot start process!")
        return

    # When we start from steam, the binary path will be None, so retreive it from from the psutils Process
    # object.
    if binary_path is None:
        binary_path = proc.proc.exe()

    print(f"Found PID: {pm_binary.process_id}")

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
        if binary_path is not None:
            with open(binary_path, "rb") as f:
                binary_hash = hash_bytes(f)
            print(f"Exe hash is: {binary_hash}")
        else:
            binary_hash = 0

        # Wait some time for the data to be written to memory.
        time.sleep(3)

        print(f"proc id from pymem: {pm_binary.process_id}")
        offset_map = {}
        if required_assemblies:
            modules = pm_binary.list_modules()
            found_modules = list(filter(lambda x: x.name in required_assemblies, modules))
            if not found_modules:
                print(f"Cannot find specified assembly from config ({required_assemblies})")
                return
            for module in found_modules:
                offset_map[module.name] = (module.lpBaseOfDll, module.SizeOfImage)
        else:
            pb = pm_binary.process_base
            offset_map[binary_exe] = (pb.lpBaseOfDll, pb.SizeOfImage)
        # print(f"The handle: {pm_binary.process_handle}, base: 0x{binary_base:X}")

        if len(offset_map) == 1:
            # Only one thing. For now, we just set these as the `binary_base` and `binary_size`.
            # TODO: When we want to support offsets and hooks in multiple assemblies we need to pass the whole
            # dictionary in potentially, or do a lookup from inside the process.
            assem_name = list(offset_map.keys())[0]
            binary_base = offset_map[assem_name][0]
            binary_size = offset_map[assem_name][1]

        # Inject some other dlls:
        # pymem.process.inject_dll(nms.process_handle, b"path")

        try:
            cwd = CWD.replace("\\", "\\\\")
            import sys

            saved_path = [x.replace("\\", "\\\\") for x in sys.path]
            # TODO: This can fail sometimes.... Figure out why??
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
pymhf.core._internal.SINGLE_FILE_MOD = {single_file_mod!r}
pymhf.core._internal.MOD_SAVE_DIR = {mod_save_dir!r}
                """
            )
        except Exception as e:
            print(e)
        # Inject the script
        with open(op.join(CWD, "injected.py"), "r") as f:
            shellcode = f.read()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        print(f"Injecting hooking code into proc id {pm_binary.process_id}")
        futures.append(executor.submit(pm_binary.inject_python_shellcode, shellcode))

        # Wait for a user input to start the process.
        # TODO: Send a signal back up from the process to trigger this automatically.
        if start_paused:
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
        print(e)
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
                try:
                    os.kill(_pid, SIGTERM)
                    print(f"Just killed process {_pid}")
                except Exception:
                    # If we can't kill it, it's probably already dead. Just continue.
                    print(f"Failed to kill process {_pid}. It was likely already dead...")
                    pass
