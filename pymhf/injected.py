import asyncio
import builtins
from concurrent.futures import ThreadPoolExecutor
import ctypes
import ctypes.wintypes
from functools import partial
import locale
import logging
import logging.handlers
import os.path as op
import time
import traceback
from typing import Optional

import pymem
import pymem.process


socket_logger_loaded = False
executor = None
ready = False

try:
    rootLogger = logging.getLogger('')
    rootLogger.setLevel(logging.INFO)
    socketHandler = logging.handlers.SocketHandler(
        "localhost",
        logging.handlers.DEFAULT_TCP_LOGGING_PORT
    )
    rootLogger.addHandler(socketHandler)
    logging.info("Loading pyMHF...")
    socket_logger_loaded = True

    import pymhf.core._internal as _internal
    from pymhf.core.importing import import_file

    from pymhf.core.utils import AutosavingConfig

    # # Before any pymhf imports occur, set the os.environ value for the
    # # binary hash:
    # if _internal.BINARY_HASH:
    #     os.environ["PYMHF_BINARY_HASH"] = _internal.BINARY_HASH
    # else:
    #     # If there is no binary hash, something has gone wrong. Exit now since
    #     # we can't continue.
    #     sys.exit(-1)

    config = AutosavingConfig()
    cfg_file = op.join(_internal.CFG_DIR, "pymhf.cfg")
    read = config.read(cfg_file)
    log_level = config.get("pymhf", "log_level", fallback="info")

    internal_mod_folder = config.get("binary", "internal_mod_dir", fallback=None)
    mod_folder = config.get("binary", "mod_dir", fallback=None)

    debug_mode = log_level.lower() == "debug"
    if debug_mode:
        rootLogger.setLevel(logging.DEBUG)

    module = import_file(_internal.MODULE_PATH)

    from pymhf.core.module_data import module_data
    module_data.FUNC_OFFSETS = module.__pymhf_functions__.FUNC_OFFSETS
    module_data.FUNC_CALL_SIGS = module.__pymhf_functions__.FUNC_CALL_SIGS

    from pymhf.core.hooking import hook_manager
    from pymhf.core.protocols import (
        ExecutionEndedException,
        custom_exception_handler,
        ESCAPE_SEQUENCE,
        READY_ASK_SEQUENCE,
        READY_ACK_SEQUENCE
    )
    from pymhf.core.memutils import getsize
    from pymhf.core.mod_loader import ModManager
    import pymhf.core.caching as cache
    from pymhf.gui.gui import GUI
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    hook_logger = logging.getLogger("HookManager")

    # Since we are running inside a thread, `asyncio.get_event_loop` will
    # generally fail.
    # Detect this and create a new event loop anyway since we are running in a
    # thread under the process we have been injected into, and not the original
    # python thread that is running the show.
    try:
        loop = asyncio.get_event_loop()
    except (RuntimeError, ValueError) as e:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Set the custom exception handler on the loop
    loop.set_exception_handler(custom_exception_handler)

    # NOTE: This class MUST be defined here. If it's defined in a separate file
    # then the hack done to persist data to the current global context will not
    # work.
    class ExecutingProtocol(asyncio.Protocol):
        """ A protocol factory to be passed to a asyncio loop.create_server call
        which will accept requests, execute them and persist any variables to
        globals()."""
        def connection_made(self, transport: asyncio.transports.WriteTransport):
            self.transport: asyncio.transports.WriteTransport = transport
            # peername = transport.get_extra_info('peername')
            # self.write(f'Connection from {peername} ')
            # Overwrite print so that any `print` statements called in the commands
            # to be executed will be written back out of the socket they came in.
            globals()['print'] = partial(builtins.print, file=self)

        def write(self, value: str):
            """ Method to allow this protocol to be used as a file to write to.
            This allows us to have `print` write to this protocol."""
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
            except:
                print(traceback.format_exc())
            else:
                self.persist_to_globals(locals())

        def persist_to_globals(self, data: dict):
            """ Take the dictionary which was determined by calling `locals()`, and
            update `gloabsl()` with it."""
            data.pop("self")
            data.pop(f"_{type(self).__name__}__data")
            globals().update(data)

        def eof_received(self):
            # Do nothing.
            pass

        def connection_lost(self, exc):
            # Once the connection is lost. Restore `print` back to normal.
            globals()['print'] = builtins.print


    def top_globals(limit: Optional[int] = 10):
        """ Return the top N objects in globals() by size (in bytes). """
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

    binary = pymem.Pymem(_internal.EXE_NAME)
    cache.module_map = {x.name: x for x in pymem.process.enum_process_module(binary.process_handle)}

    mod_manager = ModManager(hook_manager)
    # First, load our internal mod before anything else.
    if internal_mod_folder is not None:
        logging.debug(f"Loading internal mods: {internal_mod_folder}")
        # If the mod folder isn't absolute, assume it's relative to the library directory.
        if not op.isabs(internal_mod_folder):
            internal_mod_folder = op.join(_internal.MODULE_PATH, internal_mod_folder)
        if not op.exists(internal_mod_folder):
            logging.warning(
                f"Cannot load internal mod directory: {internal_mod_folder}. "
                "Please make sure it exists or that the path is correct in the pymhf.cfg file."
            )
        mod_manager.load_mod_folder(internal_mod_folder, bind=False)

    logging.info("pyMHF injection complete!")

    # Also load any mods after all the internal hooks:
    start_time = time.time()
    bold = "\u001b[4m"
    reset = "\u001b[0m"
    logging.info(bold + "Loading mods" + reset)
    _loaded_mods = 0
    _loaded_hooks = 0
    try:
        if mod_folder is not None:
            _loaded_mods, _loaded_hooks = mod_manager.load_mod_folder(mod_folder)
        else:
            logging.warning(
                """You have not configured the `binary.mod_dir` variable in the pymhf.cfg file.
                Please do so so that you can load mods."""
            )
    except:
        logging.exception(traceback.format_exc())
    logging.info(f"Loaded {_loaded_mods} mods and {_loaded_hooks} hooks in {time.time() - start_time:.3f}s")

    # hook_manager.debug_show_states()

    for func_name, hook_class in hook_manager.failed_hooks.items():
        offset = hook_class.target
        _data = (ctypes.c_char * 0x20).from_address(offset)
        hook_logger.error(f"Hook {func_name} first 0x20 bytes: {_data.value.hex()}")

    # Each client connection will create a new protocol instance
    coro = loop.create_server(ExecutingProtocol, '127.0.0.1', 6770)
    server = loop.run_until_complete(coro)
    # logging.info("Executing protocol is ready to go!")

    futures = []
    if config.getboolean("gui", "shown", fallback=True):
        gui = GUI(mod_manager, config)
        # For each mod, add the corresponding tab to the gui.
        for mod in mod_manager.mods.values():
            gui.add_tab(mod)
        # Add the settings tab so that we may configure various settings.
        gui.add_settings_tab()

        # TODO: This needs to have some exception handling because if something
        # goes wrong in here it will just fail "silently".
        futures.append(executor.submit(gui.run))

    logging.info(f'Serving on executor {server.sockets[0].getsockname()}')
    loop.run_forever()

    # Close the server.
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()

except Exception as e:
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
                logging.exception(traceback.format_exc())
    except:
        with open(op.join(op.expanduser("~"), "CRITICAL_ERROR.txt"), "w") as f:
            traceback.print_exc(file=f)
finally:
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)

