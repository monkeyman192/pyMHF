import asyncio
import builtins
import ctypes
import locale
import logging
import logging.handlers
import os
import os.path as op
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Optional

import pymem
import pymem.process

from pymhf.core.utils import get_main_window_handle

socket_logger_loaded = False
executor = None
ready = False

try:
    import pymhf.core._internal as _internal
    from pymhf.utils.config import canonicalize_setting

    rootLogger = logging.getLogger("")

    logging_config = _internal.CONFIG.get("logging", {}) or {}

    log_level = logging_config.get("log_level", "info")
    if log_level.lower() == "debug":
        rootLogger.setLevel(logging.DEBUG)
    else:
        rootLogger.setLevel(logging.INFO)

    if not logging_config.get("shown", True):
        # In this case we just want to log to a file somewhere... For now, default to a folder called logs
        # where the module path is.
        formatter = logging.Formatter("%(asctime)s %(name)-24s %(levelname)-6s %(message)s")

        _log_dir = logging_config.get("log_dir", "{CURR_DIR}")
        if op.isdir(_internal.MODULE_PATH):
            module_dir = _internal.MODULE_PATH
        else:
            module_dir = op.join(_internal.MODULE_PATH, "..")
        log_dir = canonicalize_setting(_log_dir, None, module_dir, op.dirname(_internal.BINARY_PATH), "logs")
        # If this ends up not being able to be resolved, fallback to logs in the same directory as the module.
        if log_dir is None:
            if op.isdir(_internal.MODULE_PATH):
                log_dir = op.join(_internal.MODULE_PATH, "logs")
            else:
                log_dir = op.join(_internal.MODULE_PATH, "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(
            op.join(log_dir, f"pymhf-{time.strftime('%Y%m%dT%H%M%S')}.log"), encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        rootLogger.addHandler(file_handler)
    else:
        socketHandler = logging.handlers.SocketHandler("localhost", logging.handlers.DEFAULT_TCP_LOGGING_PORT)
        rootLogger.addHandler(socketHandler)
    logging.info("Loading pyMHF...")
    socket_logger_loaded = True

    from pymhf.core._types import LoadTypeEnum

    _internal.LOAD_TYPE = LoadTypeEnum(_internal.LOAD_TYPE)

    # Assign the sentinel and load it from the provided address which is allocated in this process by the
    # parent process. If the main process isn't actually waiting on this it won't ever be read, but it's
    # simpler to just allocate it anyway.
    sentinel = ctypes.c_bool(False)
    if _internal._SENTINEL_PTR:
        sentinel = ctypes.c_bool.from_address(_internal._SENTINEL_PTR)

    _module_path = _internal.MODULE_PATH
    if op.isfile(_module_path):
        _module_path = op.dirname(_module_path)
    _binary_dir = None
    if _internal.BINARY_PATH:
        _binary_dir = op.dirname(_internal.BINARY_PATH)

    internal_mod_folder = _internal.CONFIG.get("internal_mod_dir")
    internal_mod_folder = canonicalize_setting(internal_mod_folder, "pymhf", _module_path, _binary_dir)

    mod_folder = _internal.CONFIG.get("mod_dir")
    mod_folder = canonicalize_setting(mod_folder, "pymhf", _module_path, _binary_dir)

    import keyboard._winkeyboard as kwk

    # Prefill the key name tables to avoid taking a hit when hooking.
    kwk._setup_name_tables()

    import pymhf.core.caching as cache
    from pymhf.core.hooking import hook_manager
    from pymhf.core.memutils import getsize
    from pymhf.core.mod_loader import mod_manager
    from pymhf.core.protocols import (
        ESCAPE_SEQUENCE,
        READY_ACK_SEQUENCE,
        READY_ASK_SEQUENCE,
        ExecutionEndedException,
        custom_exception_handler,
    )

    try:
        from pymhf.gui.gui import GUI
    except ModuleNotFoundError:
        # If we can't import this, then DearPyGUI is missing, so we won't create the GUI.
        GUI = None
    from pymhf.utils.imports import get_imports

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Since we are running inside a thread, `asyncio.get_event_loop` will
    # generally fail.
    # Detect this and create a new event loop anyway since we are running in a
    # thread under the process we have been injected into, and not the original
    # python thread that is running the show.
    try:
        loop = asyncio.get_event_loop()
    except (RuntimeError, ValueError):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Set the custom exception handler on the loop
    loop.set_exception_handler(custom_exception_handler)

    # NOTE: This class MUST be defined here. If it's defined in a separate file
    # then the hack done to persist data to the current global context will not
    # work.
    class ExecutingProtocol(asyncio.Protocol):
        """A protocol factory to be passed to a asyncio loop.create_server call
        which will accept requests, execute them and persist any variables to
        globals().
        """

        def connection_made(self, transport: asyncio.transports.WriteTransport):
            self.transport: asyncio.transports.WriteTransport = transport
            # peername = transport.get_extra_info('peername')
            # self.write(f'Connection from {peername} ')
            # Overwrite print so that any `print` statements called in the commands
            # to be executed will be written back out of the socket they came in.
            globals()["print"] = partial(builtins.print, file=self)

        def write(self, value: str):
            """
            Method to allow this protocol to be used as a file to write to.

            This allows us to have `print` write to this protocol.
            """
            self.transport.write(value.encode())

        def data_received(self, __data: bytes):
            # Have an "escape sequence" which will force this to exit.
            # This way we can kill it if need be from the other end.
            if __data == ESCAPE_SEQUENCE:
                print("\nReceived exit command!")
                raise ExecutionEndedException
            elif __data == READY_ASK_SEQUENCE:
                print("\nReceived ready ask command")
                print(f"Are we ready? {ready}")
                self.transport.write(READY_ACK_SEQUENCE)
                return
            try:
                exec(__data.decode())
            except Exception:
                print(traceback.format_exc())
            else:
                self.persist_to_globals(locals())

        def persist_to_globals(self, data: dict):
            """Take the dict which was determined by calling `locals()`, and update `gloabsl()` with it."""
            data.pop("self")
            data.pop(f"_{type(self).__name__}__data")
            globals().update(data)

        def eof_received(self):
            # Do nothing.
            pass

        def connection_lost(self, exc):
            # Once the connection is lost. Restore `print` back to normal.
            globals()["print"] = builtins.print

    def top_globals(limit: Optional[int] = 10):
        """Return the top N objects in globals() by size (in bytes)."""
        globs = globals()
        data = []
        for key, value in globs.items():
            if not key.startswith("__"):
                try:
                    data.append((key, *getsize(value)))
                except TypeError:
                    pass
        data.sort(key=lambda x: x[1], reverse=True)
        if limit is not None:
            return data[:limit]
        else:
            return data

    # Patch the locale to make towupper work.
    # Python must change this so we change it back otherwise calls to `towupper`
    # in the various functions to set and get keypresses don't work correctly.
    locale.setlocale(locale.LC_CTYPE, "C")

    executor = ThreadPoolExecutor(2, thread_name_prefix="pyMHF_Internal_Executor")

    binary = pymem.Pymem(_internal.EXE_NAME, exact_match=True)
    cache.module_map = {x.name: x for x in pymem.process.enum_process_module(binary.process_handle)}

    # Read the imports
    if _internal.BINARY_PATH:
        _internal.imports = get_imports(_internal.BINARY_PATH)
    for fpath in _internal.INCLUDED_ASSEMBLIES.values():
        _internal.imports.update(get_imports(fpath))

    # Load the offset cache.
    if not cache.offset_cache.loaded:
        cache.offset_cache.load()

    mod_manager.hook_manager = hook_manager
    # First, load our internal mod before anything else.
    if internal_mod_folder is not None:
        logging.debug(f"Loading internal mods: {internal_mod_folder}")
        # If the mod folder isn't absolute, assume it's relative to the library directory.
        if not op.isabs(internal_mod_folder):
            internal_mod_folder = op.join(_internal.MODULE_PATH, internal_mod_folder)
        if op.exists(internal_mod_folder):
            mod_manager.load_mod_folder(internal_mod_folder, bind=False)
        else:
            logging.warning(
                f"Cannot load internal mod directory: {internal_mod_folder}. "
                "Please make sure it exists or that the path is correct in the pymhf.toml file."
            )

    logging.info("pyMHF injection complete!")

    # Also load any mods after all the internal hooks:
    start_time = time.time()
    bold = "\u001b[4m"
    reset = "\u001b[0m"
    logging.info(bold + "Loading mods" + reset)
    _loaded_mods = 0
    _loaded_hooks = 0
    try:
        if _internal.LOAD_TYPE == LoadTypeEnum.SINGLE_FILE:
            # For a single file mod, we just load that file.
            _loaded_mods, _loaded_hooks = mod_manager.load_single_mod(_internal.MODULE_PATH)
        elif _internal.LOAD_TYPE == LoadTypeEnum.MOD_FOLDER:
            _loaded_mods, _loaded_hooks = mod_manager.load_mod_folder(_internal.MODULE_PATH, deep_search=True)
        else:  # Loading a library.
            if mod_folder is not None:
                _loaded_mods, _loaded_hooks = mod_manager.load_mod_folder(mod_folder, deep_search=True)
            else:
                logging.warning(
                    """You have not configured the `mod_dir` variable in the pymhf.toml file.
                    Please do so so that you can load mods."""
                )
    except Exception:
        logging.error(traceback.format_exc())
    _mods_str = "mod"
    if _loaded_mods != 1:
        _mods_str = "mods"
    _hooks_str = "hook"
    if _loaded_hooks != 1:
        _hooks_str = "hooks"
    logging.info(
        f"Loaded {_loaded_mods} {_mods_str} and {_loaded_hooks} {_hooks_str} in "
        f"{time.time() - start_time:.3f}s"
    )

    mod_manager._assign_mod_instances()

    _internal.MAIN_HWND = get_main_window_handle()

    for func_name, hook_class in hook_manager.failed_hooks.items():
        offset = hook_class.target
        _data = (ctypes.c_char * 0x20).from_address(offset)
        rootLogger.error(f"Hook {func_name} first 0x20 bytes: {_data.value.hex()}")

    # Each client connection will create a new protocol instance
    coro = loop.create_server(ExecutingProtocol, "127.0.0.1", 6770)
    server = loop.run_until_complete(coro)

    futures = []
    if _internal.CONFIG.get("gui", {}).get("shown", True) and GUI is not None:
        gui = GUI(mod_manager, _internal.CONFIG)
        # For each mod, add the corresponding tab to the gui.
        for mod in mod_manager.mods.values():
            gui.add_tab(mod)
        # Add the settings tab so that we may configure various settings.
        gui.add_hex_tab()
        gui.add_settings_tab()
        gui.add_details_tab()

        # TODO: This needs to have some exception handling because if something
        # goes wrong in here it will just fail "silently".
        futures.append(executor.submit(gui.run))

    logging.info(f"Serving on executor {server.sockets[0].getsockname()}")

    # Finally, before we run forever, set the sentinel value to True so that if the main process was waiting
    # for the injected code to complete before starting the process it can now resume it.
    sentinel.value = True

    loop.run_forever()

    # Close the server.
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()

except Exception:
    # If we hit this, something has gone wrong. Log to the current directory.

    try:
        # Try and log to the current working directory.
        # Sometimes this may fail as the error is an "internal" one, so we will
        # add a fail-safe to log to the users' home directory so that it at
        # least is logged somewhere.
        # TODO: Document this behaviour.
        import pymhf.core._internal as _internal

        with open(op.join(_internal.CWD, "CRITICAL_ERROR.txt"), "w") as f:
            traceback.print_exc(file=f)
            if socket_logger_loaded:
                logging.error("An error occurred while loading pymhf:")
                logging.error(traceback.format_exc())
    except Exception:
        with open(op.join(op.expanduser("~"), "CRITICAL_ERROR.txt"), "w") as f:
            traceback.print_exc(file=f)
finally:
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
