# This file includes various functions which use any of the various windows dlls to determine things.

import ctypes
import ctypes.wintypes

import pymem

GetModuleFileNameExA = ctypes.windll.psapi.GetModuleFileNameExA
GetModuleFileNameExA.restype = ctypes.wintypes.DWORD
GetModuleFileNameExA.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HMODULE,
    ctypes.wintypes.LPSTR,
    ctypes.wintypes.DWORD,
]
MAX_EXE_NAME_SIZE = 1024


def get_exe_path_from_pid(proc: pymem.Pymem) -> str:
    """Get the name of the exe which was run to create the pymem process."""
    name_buffer = ctypes.create_string_buffer(b"", MAX_EXE_NAME_SIZE)
    GetModuleFileNameExA(proc.process_handle, None, name_buffer, MAX_EXE_NAME_SIZE)
    return name_buffer.value.decode()
