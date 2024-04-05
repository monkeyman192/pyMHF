import asyncio
import concurrent.futures
import configparser
from functools import partial
import os
import os.path as op
from signal import SIGTERM
import subprocess
import time
from typing import Optional
import webbrowser

import psutil
import pymem
import pymem.process
import pymem.exception

from pymhf.core.caching import hash_bytes
from pymhf.core.process import start_process
from pymhf.core.protocols import ESCAPE_SEQUENCE, TerminalProtocol
from pymhf.core.logging import open_log_console


CWD = op.dirname(__file__)


def get_process_when_ready(
    cmd: str,
    target: Optional[str] = None,
    required_assemblies: Optional[list[str]] = None,
    is_steam: bool = True,
):
    target_process = None
    parent_process = None
    # If we are running something which is under steam, make sure steam is
    # running first.
    if is_steam:
        for p in psutil.process_iter(["name", "pid"]):
            if p.name().lower() == "steam.exe":
                parent_process = p
                break
        if parent_process is None:
            print("Steam not running! For now, start it yourself and try again...")

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
            if target_process is None:
                for child in parent_process.children():
                    if child.name() == target:
                        target_process = child
            else:
                binary = pymem.Pymem(target)
                modules = list(pymem.process.enum_process_module(binary.process_handle))
                if len(modules) > 0:
                    if set(required_assemblies) <= set(x.name for x in modules):
                        run = False
                        break
    else:
        # process_handle, thread_handle, pid, tid = start_process(binary_path, creationflags=0x4)
        pass

    if target_process is not None:
        binary = pymem.Pymem('Kamiko.exe')
        # TODO: We can inject python in really early since any loaded dll's will persist through steam's forking process.
        try:
            binary.inject_python_interpreter()
        except pymem.exception.MemoryWriteError:
            print("Failed to inject python for some reason... Trying again in 2 seconds")
            time.sleep(2)
            binary.inject_python_interpreter()
        print("Python injected")
        target_process.suspend()

        return binary, target_process
    else:
        return None, None


def load_module(module_path: str):

    # Parse the config file first so we can load anything we need to know.
    config = configparser.ConfigParser()
    # Currently it's in the same directory as this file...
    cfg_file = op.join(module_path, "pymhf.cfg")
    read = config.read(cfg_file)
    if not read:
        print(f"No pymhf.cfg file found in specified directory: {module_path}")
        print("Cannot proceed with loading")
        return
    binary_path = config["binary"]["path"]
    binary_exe = op.basename(binary_path)
    root_dir = config["binary"]["root_dir"]
    steam_gameid = config.getint("bninary", "steam_gameid", fallback=0)
    if steam_gameid:
        cmd = f"steam://rungameid/{steam_gameid}"
    else:
        cmd = binary_path

    pm_binary, proc = get_process_when_ready(cmd, "Kamiko.exe", ["GameAssembly.dll"], True)

    if not pm_binary or not proc:
        print("FATAL ERROR: Cannot start process!")
        return

    print(f"Found PID: {pm_binary.process_id}")

    executor = None
    futures = []
    loop = asyncio.get_event_loop()

    def kill_injected_code(loop: asyncio.AbstractEventLoop):
        # End one last "escape sequence" message:
        client_completed = asyncio.Future()
        client_factory = partial(
            TerminalProtocol,
            message=ESCAPE_SEQUENCE.decode(),
            future=client_completed
        )
        factory_coroutine = loop.create_connection(
            client_factory,
            '127.0.0.1',
            6770,
        )
        loop.run_until_complete(factory_coroutine)
        loop.run_until_complete(client_completed)


    try:
        log_pid = open_log_console(op.join(CWD, "log_terminal.py"))
        # Have a small nap just to give it some time.
        time.sleep(0.5)
        print(f"Opened the console log with PID: {log_pid}")
        with open(binary_path, "rb") as f:
            binary_hash = hash_bytes(f)
        print(f"Exe hash is: {binary_hash}")

        # Wait some time for the data to be written to memory.
        time.sleep(3)

        print(f"proc id from pymem: {pm_binary.process_id}")
        if (base_assembly := config.get("binary", "assembly", fallback=None)) is not None:
            modules = pm_binary.list_modules()
            found_module = None
            for m in modules:
                if m.name == base_assembly:
                    found_module = m
                    break
            if found_module is None:
                print(f"Cannot find specified assembly from config ({base_assembly})")
                return
            binary_base = found_module.lpBaseOfDll
            binary_size = found_module.SizeOfImage
        else:
            pb = pm_binary.process_base
            binary_base = pb.lpBaseOfDll
            binary_size = pb.SizeOfImage
        print(f"The handle: {pm_binary.process_handle}, base: 0x{binary_base:X}")

        # Inject some other dlls:
        # pymem.process.inject_dll(nms.process_handle, b"path")

        try:
            cwd = CWD.replace("\\", "\\\\")
            print(0)
            # TODO: This can fail sometimes.... Figure out why??
            pm_binary.inject_python_shellcode(f"CWD = '{cwd}'")
            print(0.5)
            pm_binary.inject_python_shellcode("import sys")
            pm_binary.inject_python_shellcode("sys.path.append(CWD)")
            print(1)
            # Inject _preinject AFTER modifying the sys.path for now until we have
            # nmspy installed via pip.
            with open(op.join(CWD, "_scripts", "_preinject.py"), "r") as f:
                _preinject_shellcode = f.read()
            pm_binary.inject_python_shellcode(_preinject_shellcode)
            print(2)
            # Inject the common NMS variables which are required for general use.
            module_path = module_path.replace("\\", "\\\\")
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.MODULE_PATH = '{module_path}'")
            print(3)
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.BASE_ADDRESS = {binary_base}")
            print(4)
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.SIZE_OF_IMAGE = {binary_size}")
            print(5)
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.CWD = '{cwd}'")
            print(6)
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.PID = {pm_binary.process_id}")
            print(7)
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.HANDLE = {pm_binary.process_handle}")
            print(8)
            pm_binary.inject_python_shellcode(f"pymhf.core._internal.BINARY_HASH = '{binary_hash}'")
            print(9)
            pm_binary.inject_python_shellcode(
                f"pymhf.core._internal.GAME_ROOT_DIR = \"{root_dir}\""
            )
        except Exception as e:
            print(e)
        # Inject the script
        with open(op.join(CWD, "injected.py"), "r") as f:
            shellcode = f.read()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        print("Injecting hooking code")
        futures.append(executor.submit(pm_binary.inject_python_shellcode, shellcode))

        try:
            input("Press something to start binary")
        except KeyboardInterrupt:
            # Kill the injected code so that we don't wait forever for the future to end.
            kill_injected_code(loop)
            raise
        if proc is None:
            print(f"Opening thread {thread_handle}")
            # thread_handle = pymem.process.open_thread(main_thread.thread_id)
            pymem.ressources.kernel32.ResumeThread(thread_handle)
        else:
            proc.resume()

        print("NMS.py interactive python command prompt")
        print("Type any valid python commands to execute them within the NMS process")
        while True:
            try:
                input_ = input(">>> ")
                client_completed = asyncio.Future()
                client_factory = partial(
                    TerminalProtocol,
                    message=input_,
                    future=client_completed
                )
                factory_coroutine = loop.create_connection(
                    client_factory,
                    '127.0.0.1',
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
        except:
            pass
        finally:
            print("Forcibly shutting down process")
            time.sleep(1)
            for _pid in {pm_binary.process_id, log_pid}:
                try:
                    os.kill(_pid, SIGTERM)
                    print(f"Just killed process {_pid}")
                except:
                    # If we can't kill it, it's probably already dead. Just continue.
                    print(f"Failed to kill process {_pid}. It was likely already dead...")
                    pass
