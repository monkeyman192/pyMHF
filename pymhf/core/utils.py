from ctypes import windll, create_unicode_buffer, byref, c_ulong
from configparser import ConfigParser
import logging
from typing import Optional
import pywinctl as pwc
import win32gui
import win32process
import pymem
import logging
import keyboard
import mouse
import pymhf.core._internal as _internal
#from pymhf.core._internal import EXE_NAME, MAIN_HWND
import ctypes



def get_hwnds_for_pid(pid):
    def callback(hwnd, hwnds):
        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)

        if found_pid == pid:
            hwnds.append(hwnd)
        return True
    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds 
            
"""def getWindowTitleByHandleAndPid(pid, handle):
        windows = {x.getHandle(): x for x in pwc.getAllWindows()}
        print(f'{windows}')
        hwnds = get_hwnds_for_pid(pid)
        print(f'{hwnds}')
        for hwnd in hwnds:
            try:
                if windows[hwnd]:
                    print(f'{windows[hwnd]}')
            except Exception:
                print("noKey")

def set_main_window_focus():
    getWindowTitleByHandleAndPid(16256, pymem.Pymem(EXE_NAME).process_handle)  #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file """
 

def getWindowByHandle(handle):
    windows = {}
    try:
        windows = {x.getHandle(): x for x in pwc.getAllWindows()}
        if windows[handle]:
            return windows[handle]
        else:
            return None       
    except Exception as e:
        logging.info("getwindowbyhandle")
        logging.info(f'handle: {handle}')
        logging.info(f'windows: {windows}')        
        logging.error(e)

def set_main_window_focus()->bool:
    logging.info("set_main_window_focus")
    status = is_main_window_foreground()
    main_window = None
    if not status:       
        main_window = getWindowByHandle(_internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file       
        if main_window:
            if main_window.activate():
                status = True
    return status

def is_main_window_foreground():
    return win32gui.GetForegroundWindow() == _internal.MAIN_HWND

def get_main_window():
    main_window = getWindowByHandle(_internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file 
    return main_window   




logger = logging.getLogger(__name__)


# def dump_resource(res, fname):
#     with open(op.join(_internal.CWD, fname), "w") as f:
#         f.write(json.dumps(res, indent=2))


def safe_assign_enum(enum, index: int):
    """ Safely try and get the enum with the associated integer value.
    If the index isn't one in the enum return the original index."""
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


class AutosavingConfig(ConfigParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filename: str
        self._encoding: Optional[str]

    def read(self, filenames, encoding=None):
        super().read(filenames, encoding)
        self._filename = filenames
        self._encoding = encoding

    def set(self, section: str, option: str, value=None):
        if value is not None:
            val = str(value)
        else:
            val = value
        try:
            super().set(section, option, val)
            with open(self._filename, "w", encoding=self._encoding) as f:
                self.write(f, space_around_delimiters=True)
        except Exception as e:
            logger.exception("Error saving file")


def saferun(func, *args, **kwargs):
    """ Safely run the specified function with args and kwargs. Any exception raised will be shown and """
    ret = None
    try:
        ret = func(*args, **kwargs)
    except:
        logger.exception(f"There was an exception while calling {func}:")
    return ret
