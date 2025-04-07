# This file includes various functions which use any of the various windows dlls to determine things.

import ctypes
from ctypes import wintypes
from typing import Protocol

import pymem
import pymem.ressources.structure

GetModuleFileNameExA = ctypes.windll.psapi.GetModuleFileNameExA
GetModuleFileNameExA.restype = wintypes.DWORD
GetModuleFileNameExA.argtypes = [
    wintypes.HANDLE,
    wintypes.HMODULE,
    wintypes.LPSTR,
    wintypes.DWORD,
]

GetWindowLongA = ctypes.windll.user32.GetWindowLongA
GetWindowLongA.restype = wintypes.LONG
GetWindowLongA.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
]

SetWindowLongA = ctypes.windll.user32.SetWindowLongA
SetWindowLongA.restype = wintypes.LONG
SetWindowLongA.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    wintypes.LONG,
]

SetLayeredWindowAttributes = ctypes.windll.user32.SetLayeredWindowAttributes
SetLayeredWindowAttributes.restype = wintypes.BOOL
SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,
    wintypes.COLORREF,
    wintypes.BYTE,
    wintypes.DWORD,
]


SetLastError = ctypes.windll.kernel32.SetLastError
SetLastError.argtypes = [wintypes.DWORD]


GetLastError = ctypes.windll.kernel32.GetLastError
GetLastError.restype = wintypes.DWORD


VirtualQuery = ctypes.windll.kernel32.VirtualQuery
VirtualQuery.argtypes = [
    wintypes.LPCVOID,
    ctypes.c_void_p,
    ctypes.c_size_t,
]
VirtualQuery.restype = ctypes.c_size_t


MAX_EXE_NAME_SIZE = 1024
WS_EX_LAYERED = 0x00080000  # layered window
GWL_EXSTYLE = -20  # "extended window style"

LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002


def get_exe_path_from_pid(proc: pymem.Pymem) -> str:
    """Get the name of the exe which was run to create the pymem process."""
    name_buffer = ctypes.create_string_buffer(b"", MAX_EXE_NAME_SIZE)
    GetModuleFileNameExA(proc.process_handle, None, name_buffer, MAX_EXE_NAME_SIZE)
    return name_buffer.value.decode()


def set_window_transparency(hwnd: int, alpha: float):
    SetWindowLongA(hwnd, GWL_EXSTYLE, GetWindowLongA(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED)
    rgb = wintypes.RGB(10, 10, 10)
    SetLayeredWindowAttributes(hwnd, rgb, int(255 * alpha), LWA_ALPHA)


class MemoryInfo(Protocol):
    BaseAddress: int
    AllocationBase: int
    AllocationProtect: int
    RegionSize: int
    State: int
    Protect: int
    Type: int


def QueryAddress(address: int) -> MemoryInfo:
    mbi = pymem.ressources.structure.MEMORY_BASIC_INFORMATION()
    SetLastError(0)
    VirtualQuery(address, ctypes.byref(mbi), ctypes.sizeof(mbi))
    if errcode := GetLastError():
        raise ValueError(f"There was an error accessing address 0x{address:X}: {errcode}")
    return mbi
