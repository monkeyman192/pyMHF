import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from ctypes import byref, c_ulong, create_unicode_buffer, windll
from functools import wraps
from typing import Optional

import psutil
import pywinctl as pwc
import win32gui
import win32process

import pymhf.core._internal as _internal

logger = logging.getLogger(__name__)


def get_main_window_handle() -> Optional[int]:
    """Return the handle of the main running application window if possible.
    This will correspond to the HWND for the window belonging to the PID of the main running process.
    """
    windows = {x.getHandle(): x for x in pwc.getAllWindows()}
    main_pid_hwnds = get_hwnds_for_pid(_internal.PID)
    wins = [x for x, y in windows.items() if (x in main_pid_hwnds and y.title != "pyMHF")]
    if len(wins) == 0:
        logger.warning(f"Cannot find window handle for PID {_internal.PID}")
        return None
    elif len(wins) > 1:
        logger.error(
            f"Found multiple windows for PID {_internal.PID}: {main_pid_hwnds}.\n"
            "Picking the first arbitrarily but this may not be correct."
        )
        return wins[0]
    else:
        return wins[0]


def get_hwnds_for_pid(pid: int) -> list[int]:
    """Return all HWND's for the provided PID."""

    def callback(hwnd: int, hwnds: list[int]):
        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)

        if found_pid == pid:
            hwnds.append(hwnd)
        return True

    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds


def get_window_by_handle(handle: int) -> Optional[pwc.Window]:
    windows = {x.getHandle(): x for x in pwc.getAllWindows()}
    return windows.get(handle)


def set_main_window_active(callback: Optional[Callable[[], None]] = None):
    """Set the main window as active.
    If a callback is provided, it will be called after activating the window.
    This callback must not take any arguments and any return value will be ignored.
    """
    # Make sure that we have the MAIN_HWND in case it wasn't found earlier.
    if not _internal.MAIN_HWND:
        _internal.MAIN_HWND = get_main_window_handle()
        if not _internal.MAIN_HWND:
            logger.error("Cannot set main window active as we can't find it...")
    if not is_main_window_foreground():
        if main_window := get_window_by_handle(_internal.MAIN_HWND):
            main_window.activate()
            if callback is not None:
                callback()


def is_main_window_foreground() -> bool:
    return win32gui.GetForegroundWindow() == _internal.MAIN_HWND


def get_main_window():
    main_window = get_window_by_handle(_internal.MAIN_HWND)
    return main_window


# def dump_resource(res, fname):
#     with open(op.join(_internal.CWD, fname), "w") as f:
#         f.write(json.dumps(res, indent=2))


def safe_assign_enum(enum, index: int):
    """Safely try and get the enum with the associated integer value.
    If the index isn't one in the enum return the original index.
    """
    try:
        return enum(index)
    except ValueError:
        return index


def get_foreground_window_title() -> Optional[str]:
    hWnd = windll.user32.GetForegroundWindow()
    length = windll.user32.GetWindowTextLengthW(hWnd)
    buf = create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(hWnd, buf, length + 1)

    # 1-liner alternative: return buf.value if buf.value else None
    if buf.value:
        return buf.value
    else:
        return None


def get_foreground_pid():
    handle = windll.user32.GetForegroundWindow()
    pid = c_ulong()
    windll.user32.GetWindowThreadProcessId(handle, byref(pid))
    return pid.value


def does_pid_have_focus(pid: int) -> bool:
    return pid == get_foreground_pid()


# TODO: Do something about this...
# class AutosavingConfig(ConfigParser):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self._filename: str
#         self._encoding: Optional[str]

#     def read(self, filenames, encoding=None):
#         super().read(filenames, encoding)
#         self._filename = filenames
#         self._encoding = encoding

#     def set(self, section: str, option: str, value=None):
#         if value is not None:
#             val = str(value)
#         else:
#             val = value
#         try:
#             super().set(section, option, val)
#             with open(self._filename, "w", encoding=self._encoding) as f:
#                 self.write(f, space_around_delimiters=True)
#         except Exception:
#             logger.exception("Error saving file")


def saferun(func, *args, **kwargs):
    """Safely run the specified function with args and kwargs.

    Any exception raised will be shown and ignored
    """
    ret = None
    try:
        ret = func(*args, **kwargs)
    except Exception:
        logger.exception(f"There was an exception while calling {func}:")
    return ret


def saferun_decorator(func: Callable):
    """Safely run the decorated function so that any errors are caught and logged."""

    @wraps(func)
    def inner(*args, **kwargs):
        ret = None
        try:
            ret = func(*args, **kwargs)
        except Exception:
            logger.exception(f"There was an exception while calling {func}:")
        return ret

    return inner


# Some experimental functions. Private until they can be made to work...


def _pause_or_resume_process(pid: int, pause: bool):
    proc = psutil.Process(pid)
    if pause:
        proc.suspend()
    else:
        proc.resume()


def _pause_process(pid: Optional[int] = None):
    if not pid:
        pid = _internal.PID
    logger.info(f"Pausing process {pid}")
    with ThreadPoolExecutor(max_workers=1) as exc:
        exc.submit(_pause_or_resume_process, pid, True)


def _resume_process(pid: Optional[int] = None):
    if not pid:
        pid = _internal.PID
    logger.info(f"Resuming process {pid}")
    with ThreadPoolExecutor(max_workers=1) as exc:
        exc.submit(_pause_or_resume_process, pid, False)
