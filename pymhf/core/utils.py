from ctypes import windll, create_unicode_buffer, byref, c_ulong
from configparser import ConfigParser
from typing import Optional
import pywinctl as pwc
import win32gui
import win32process
import pymem
import pprint
import logging
import keyboard
import mouse
import pymhf.core._internal as _internal
from pymhf.core._internal import PID, EXE_NAME
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

def getHandleByPid(pid):
   hwnds = get_hwnds_for_pid(pid)
   return hwnds[0]

def getWindowByHandle(pid, handle):
    windows = {x.getHandle(): x for x in pwc.getAllWindows()}
    if windows[handle]:
        return windows[handle]
    else:
        return None
        

def set_main_window_focus()->bool:
    logging.info("--set_main_window_focus()")
    foreground = False
    try:
        pm_process = pymem.Pymem( _internal.EXE_NAME)
        main_window = getWindowByHandle(pm_process.process_id, _internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file 
        if main_window:
            if main_window.activate():
                logging.info("----Main window is foreground window")
                foreground = True
            else:
                logging.info("----Main window is NOT foreground window")
        else:
            logging.info("----noKey")
    except Exception as e:
        logging.error(e)
    return foreground

def debug_set_main_window_focus(write, delay, restore):
    logging.info("--debug_set_main_window_focus()")
    pid = get_foreground_pid()
    title = get_foreground_window_title()
    focused_hwnd = win32gui.GetFocus()
    logging.info(f'----Foreground: title->{title}, pid->{pid}')
    logging.info(f'----Keyboard focus: {focused_hwnd}')
    pm_process = pymem.Pymem( _internal.EXE_NAME)
    main_window = getWindowByHandle(pm_process.process_id, _internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file 
    logging.info(f'Monitor: {main_window.getDisplay()}')
    if win32gui.IsWindowEnabled(main_window.getHandle()):
        logging.info("----Main window is enabled for input")
    else:
        logging.info("----Main window is NOT enabled for input")
    if main_window:
        if main_window.activate():
            logging.info("----Main window is foreground window")
        else:
            logging.info("----Main window is NOT foreground window")
            """ logging.info(f'Main window maximized: {main_window.isMaximized()}')
            logging.info(f'Main window is Alive: {main_window.isAlive()}') """
            #logging.info(f'Active window: {pwc.getActiveWindowTitle()}')
            """ keyboard.write(write,delay=delay,restore_state_after=restore)
            windll.user32. """

    else:
        logging.info("----noKey")
    pid = get_foreground_pid()
    title = get_foreground_window_title()
    focused_hwnd = win32gui.GetFocus()
    logging.info(f'----Foreground: title->{title}, pid->{pid}')
    logging.info(f'----Keyboard focus: {focused_hwnd}')

def eval_foreground():
    logging.info("--eval_foreground()")
    pid = get_foreground_pid()
    title = get_foreground_window_title()
    focused_hwnd = win32gui.GetFocus()
    logging.info(f'----Foreground: title->{title}, pid->{pid}, handle->{_internal.MAIN_HWND}')
    logging.info(f'----Keyboard focus: {focused_hwnd}')
    try:
        pm_process = pymem.Pymem( _internal.EXE_NAME)
        main_window = getWindowByHandle(pm_process.process_id, _internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file 
        display = main_window.getDisplay()
        logging.info(f'----Monitor: {display}')
        handle = main_window.getHandle()
        pid = pm_process.process_id
        win_title = win32gui.GetWindowText(handle)
        logging.info(f'----Main Window: title->{win_title}, pid->{pid}, handle->{handle}')
        if win32gui.IsWindowEnabled(handle):
            logging.info("----Main window is enabled for input")
        else:
            logging.info("----Main window is NOT enabled for input")
        if win_title == title:
            logging.info("----Main window is foreground window")
        else:
            logging.info("----Main window is NOT foreground window")
    except Exception as e:
        logging.error(e)


def get_main_window():
    pm_process = pymem.Pymem( _internal.EXE_NAME)
    main_window = getWindowByHandle(pm_process.process_id, _internal.MAIN_HWND) #Window class methods and properties detailed at https://github.com/Kalmat/PyWinCtl?tab=readme-ov-file 
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
