import ctypes
import ctypes.wintypes as wintypes
import hashlib
from io import BufferedReader
from os.path import basename, normcase
from typing import TYPE_CHECKING, Any, TypeAlias

import psutil

# Just doing this for type hinting purposes to avoid using "Any" for the ctypes objects
if TYPE_CHECKING:
    from ctypes import _CData, _Pointer, _SimpleCData
    from typing import TypeAlias

    CDataLike: TypeAlias = (
        _CData | _SimpleCData | _Pointer[Any] | ctypes.Structure | ctypes.Union | ctypes.Array[Any]
    )
else:
    CDataLike = Any

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

LIST_MODULES_ALL = 0x01 | 0x02  # LIST_MODULES_32BIT | LIST_MODULES_64BIT

IMAGE_DOS_SIGNATURE = 0x5A4D
IMAGE_NT_SIGNATURE = 0x00004550

IMAGE_SIZEOF_SHORT_NAME = 8

IMAGE_SCN_MEM_WRITE = 0x80000000


# ctypes/wintypes/kernel32/psapi struct definitions
class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", wintypes.LPVOID),
        ("SizeOfImage", wintypes.DWORD),
        ("EntryPoint", wintypes.LPVOID),
    ]


class IMAGE_DOS_HEADER(ctypes.Structure):
    _fields_ = [
        ("e_magic", wintypes.WORD),
        ("e_cblp", wintypes.WORD),
        ("e_cp", wintypes.WORD),
        ("e_crlc", wintypes.WORD),
        ("e_cparhdr", wintypes.WORD),
        ("e_minalloc", wintypes.WORD),
        ("e_maxalloc", wintypes.WORD),
        ("e_ss", wintypes.WORD),
        ("e_sp", wintypes.WORD),
        ("e_csum", wintypes.WORD),
        ("e_ip", wintypes.WORD),
        ("e_cs", wintypes.WORD),
        ("e_lfarlc", wintypes.WORD),
        ("e_ovno", wintypes.WORD),
        ("e_res", wintypes.WORD * 4),
        ("e_oemid", wintypes.WORD),
        ("e_oeminfo", wintypes.WORD),
        ("e_res2", wintypes.WORD * 10),
        ("e_lfanew", wintypes.LONG),
    ]


class IMAGE_FILE_HEADER(ctypes.Structure):
    _fields_ = [
        ("Machine", wintypes.WORD),
        ("NumberOfSections", wintypes.WORD),
        ("TimeDateStamp", wintypes.DWORD),
        ("PointerToSymbolTable", wintypes.DWORD),
        ("NumberOfSymbols", wintypes.DWORD),
        ("SizeOfOptionalHeader", wintypes.WORD),
        ("Characteristics", wintypes.WORD),
    ]


class IMAGE_SECTION_HEADER(ctypes.Structure):
    class _Misc(ctypes.Union):
        _fields_ = [("PhysicalAddress", wintypes.DWORD), ("VirtualSize", wintypes.DWORD)]

    _anonymous_ = ("Misc",)
    _fields_ = [
        ("Name", wintypes.BYTE * IMAGE_SIZEOF_SHORT_NAME),
        ("Misc", _Misc),
        ("VirtualAddress", wintypes.DWORD),
        ("SizeOfRawData", wintypes.DWORD),
        ("PointerToRawData", wintypes.DWORD),
        ("PointerToRelocations", wintypes.DWORD),
        ("PointerToLinenumbers", wintypes.DWORD),
        ("NumberOfRelocations", wintypes.WORD),
        ("NumberOfLinenumbers", wintypes.WORD),
        ("Characteristics", wintypes.DWORD),
    ]


class SYSTEM_INFO(ctypes.Structure):
    class _DUMMYUNIONNAME(ctypes.Union):
        class _DUMMYSTRUCTNAME(ctypes.Structure):
            _fields_ = [
                ("wProcessorArchitecture", wintypes.WORD),
                ("wReserved", wintypes.WORD),
            ]

        _fields_ = [("dwOemId", wintypes.DWORD), ("s", _DUMMYSTRUCTNAME)]

    _anonymous_ = ("u",)
    _fields_ = [
        ("u", _DUMMYUNIONNAME),
        ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", wintypes.LPVOID),
        ("lpMaximumApplicationAddress", wintypes.LPVOID),
        ("dwActiveProcessorMask", ctypes.POINTER(wintypes.DWORD)),
        ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD),
        ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD),
        ("wProcessorRevision", wintypes.WORD),
    ]


kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL

kernel32.GetSystemInfo.argtypes = [ctypes.POINTER(SYSTEM_INFO)]
kernel32.GetSystemInfo.restype = None


psapi.EnumProcessModulesEx.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HMODULE),
    wintypes.DWORD,
    wintypes.LPDWORD,
    wintypes.DWORD,
]
psapi.EnumProcessModulesEx.restype = wintypes.BOOL

psapi.GetModuleFileNameExW.argtypes = [
    wintypes.HANDLE,
    wintypes.HMODULE,
    wintypes.LPWSTR,
    wintypes.DWORD,
]
psapi.GetModuleFileNameExW.restype = wintypes.DWORD

psapi.GetModuleInformation.argtypes = [
    wintypes.HANDLE,
    wintypes.HMODULE,
    ctypes.POINTER(MODULEINFO),
    wintypes.DWORD,
]
psapi.GetModuleInformation.restype = wintypes.BOOL


def hash_bytes_from_file(fileobj: BufferedReader, _bufsize: int = 2**18) -> str:
    # Essentially implement hashlib.file_digest since it's python 3.11+
    # cf. https://github.com/python/cpython/blob/main/Lib/hashlib.py#L195
    digestobj = hashlib.sha1()
    buf = bytearray(_bufsize)  # Reusable buffer to reduce allocations.
    view = memoryview(buf)
    while True:
        size = fileobj.readinto(buf)
        if size == 0:
            break  # EOF
        digestobj.update(view[:size])
    return digestobj.hexdigest()


def _read_process_memory(
    process_handle: wintypes.HANDLE,
    address: int,
    out_obj: CDataLike,
    size: int | None = None,
    out_bytes_read: ctypes.c_size_t = ctypes.c_size_t(),
    raise_on_err: bool = True,
) -> wintypes.BOOL:
    if size is None:
        size = ctypes.sizeof(out_obj)
    res = kernel32.ReadProcessMemory(
        process_handle,
        ctypes.c_void_p(address),
        ctypes.byref(out_obj),
        size,
        ctypes.byref(out_bytes_read),
    )
    if raise_on_err and not res or out_bytes_read.value != size:
        raise OSError(f"Failed to read memory at 0x{address:X}: {ctypes.get_last_error()}")

    return res


def _get_page_size() -> int:
    sys_info = SYSTEM_INFO()
    kernel32.GetSystemInfo(ctypes.byref(sys_info))
    return sys_info.dwPageSize


def hash_bytes_from_memory(binary_path: str, _bufsize: int = 2**18) -> str:
    # Compute SHA-1 hash for the static parts of the given binary if it is currently running.
    # "Static parts" here refers to areas without "WRITE" permissions (e.g.: .text, .rdata, etc)
    pid = None
    normalized_path = normcase(binary_path)
    exe_name = basename(normalized_path).lower()

    # Find the PID of the process with the given binary path
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = process.info.get("exe", "")
            name = (process.info.get("name", "")).lower()
            if exe and normcase(exe) == normalized_path and name == exe_name:
                pid = process.info["pid"]
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not pid:
        raise ProcessLookupError(f"Could not find running process for {binary_path}")

    # Open the process with some basic read/query permissions
    access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
    process_handle = kernel32.OpenProcess(access, False, pid)
    if not process_handle:
        raise OSError(f"Failed to open process {pid}: {ctypes.get_last_error()}")

    # Find the main module of the opened process
    try:  # This try/finally ensures we always close the process handle
        modules = (wintypes.HMODULE * 256)()
        bytes_needed = wintypes.DWORD()
        res = psapi.EnumProcessModulesEx(
            process_handle, modules, ctypes.sizeof(modules), ctypes.byref(bytes_needed), LIST_MODULES_ALL
        )
        if not res:
            raise OSError(f"Failed to enumerate process modules for {pid}: {ctypes.get_last_error()}")

        num_modules = min(bytes_needed.value // ctypes.sizeof(wintypes.HMODULE), 256)
        main_module = None
        for i in range(num_modules):
            buffer = ctypes.create_unicode_buffer(1024)
            psapi.GetModuleFileNameExW(process_handle, modules[i], buffer, ctypes.sizeof(buffer))
            module_path = buffer.value
            if normcase(module_path) == normalized_path or basename(module_path).lower() == exe_name:
                main_module = modules[i]
                break
        if not main_module:
            main_module = modules[0]  # Usually the first module is the main module
            # If you want to be strict, maybe raise an error or return here instead
            # raise OSError(f"Could not find main module for process {pid}")

        # Read module information
        modinfo = MODULEINFO()
        res = psapi.GetModuleInformation(
            process_handle, main_module, ctypes.byref(modinfo), ctypes.sizeof(modinfo)
        )
        if not res:
            raise OSError(f"Failed to get module information for {pid}: {ctypes.get_last_error()}")

        base_address = int(modinfo.lpBaseOfDll)
        module_size = int(modinfo.SizeOfImage)

        # Parse PE headers to find sections
        dos_header = IMAGE_DOS_HEADER()
        _read_process_memory(process_handle, base_address, dos_header)
        if dos_header.e_magic != IMAGE_DOS_SIGNATURE:
            raise ValueError(f"Invalid DOS header magic for process {pid}")

        signature = wintypes.DWORD()
        _read_process_memory(process_handle, base_address + dos_header.e_lfanew, signature)
        if signature.value != IMAGE_NT_SIGNATURE:
            raise ValueError(f"Invalid PE header signature for process {pid}")

        header = IMAGE_FILE_HEADER()
        _read_process_memory(
            process_handle, base_address + dos_header.e_lfanew + ctypes.sizeof(wintypes.DWORD), header
        )

        num_sections = header.NumberOfSections
        opt_header_size = header.SizeOfOptionalHeader
        section_base = (
            base_address
            + dos_header.e_lfanew
            + ctypes.sizeof(wintypes.DWORD)
            + ctypes.sizeof(IMAGE_FILE_HEADER)
            + opt_header_size
        )

        # Build a list with all sections to be hashed
        sections = []
        for i in range(num_sections):
            section_header = IMAGE_SECTION_HEADER()
            _read_process_memory(
                process_handle, section_base + i * ctypes.sizeof(IMAGE_SECTION_HEADER), section_header
            )

            characteristics = section_header.Characteristics
            if characteristics & IMAGE_SCN_MEM_WRITE:
                continue

            virtual_address = int(section_header.VirtualAddress)
            virtual_size = int(section_header.Misc.VirtualSize) or int(section_header.SizeOfRawData)
            if virtual_address == 0 or virtual_size == 0:
                continue

            end_address = min(virtual_address + virtual_size, module_size)
            if end_address <= virtual_address:
                continue

            section = (
                virtual_address,
                end_address - virtual_address,
                bytes(bytearray(section_header.Name)).rstrip(b"\x00").decode(errors="ignore"),
            )
            sections.append(section)

        page_size = _get_page_size()
        if not page_size:
            page_size = 4096  # Usually Windows page size is 4KiB

        # Apply the hashing on all sections after sorting by address to ensure consistency
        if not sections:
            raise ValueError(f"No valid sections found to hash for process {pid}")

        sections.sort(key=lambda s: s[0])

        digest = hashlib.sha1()
        buffer = (ctypes.c_ubyte * _bufsize)()
        bytes_read = ctypes.c_size_t()
        for rva, size, name in sections:
            offset = 0
            while offset < size:
                to_read = min(_bufsize, size - offset)
                res = _read_process_memory(
                    process_handle,
                    base_address + rva + offset,
                    buffer,
                    to_read,
                    bytes_read,
                    raise_on_err=False,
                )
                if not res or bytes_read.value == 0:
                    offset += page_size
                    continue

                mem_view = memoryview(buffer)[: bytes_read.value]
                digest.update(mem_view)
                offset += bytes_read.value

        return digest.hexdigest()

    finally:
        kernel32.CloseHandle(process_handle)
