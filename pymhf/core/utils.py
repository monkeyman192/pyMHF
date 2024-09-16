from ctypes import windll, create_unicode_buffer, byref, c_ulong, addressof
from configparser import ConfigParser
from typing import Optional
import logging
import pywinctl as pwc
import win32gui
import win32process
import pymhf.core._internal as _internal
 
def get_hwnds_for_pid(pid):
    def callback(hwnd, hwnds):
        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)

        if found_pid == pid:
            hwnds.append(hwnd)
        return True
    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds 

def getHandleByPid(pid):
   hwnds = get_hwnds_for_pid(pid)
   return hwnds

def get_main_window_handle() -> Optional[int]:
    windows = {x.getHandle(): x for x in pwc.getAllWindows()}
    main_pid_hwnds = get_hwnds_for_pid(_internal.PID)
    wins = [x for x, y in windows.items() if (x in main_pid_hwnds and y.title != "pyMHF")]
    if len(wins) == 0:
        logging.error(f"Cannot find window handle for PID {_internal.PID}")
        return None
    elif len(wins) > 1:
        logging.error(f"Found multiple windows for PID {_internal.PID}: {main_pid_hwnds}.\n"
                     "Picking the first arbitrarily but this may not be correct.")
        return wins[0]
    else:
        return wins[0]

def getWindowByHandle(handle):
    windows = {}
    windows = {x.getHandle(): x for x in pwc.getAllWindows()}
    if windows.get(handle):
        return windows[handle]
    else:
        return None       

def set_main_window_focus()->bool:
    status = is_main_window_foreground()
    main_window = None
    current_hwnd = win32gui.GetCapture()
    logging.info(f'GetCapture: {current_hwnd}')
    #check = win32gui.EnableWindow(_internal.MAIN_HWND, True)            
    #logging.info(f'EnableWindow: {check}')
    if not status:       
        main_window = getWindowByHandle(_internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file       
        if main_window:
            if main_window.activate():
                status = True
    #capture_hwnd = win32gui.SetCapture(_internal.MAIN_HWND)  

    current_hwnd = win32gui.GetCapture()
    logging.info(f'GetCapture: {current_hwnd}')
    return status

def enable_main_window():
    win32gui.EnableWindow(_internal.MAIN_HWND, True)


def is_main_window_foreground():
    return win32gui.GetForegroundWindow() == _internal.MAIN_HWND

def get_main_window():
    main_window = getWindowByHandle(_internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file 
    return main_window   




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
            import logging
            logging.exception(e)
