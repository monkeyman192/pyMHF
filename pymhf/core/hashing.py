import ctypes
import ctypes.wintypes as wintypes
import hashlib
import os
from io import BufferedReader

import psutil
import pymem
from pymem.ressources.structure import (
    MEMORY_BASIC_INFORMATION,
    MEMORY_BASIC_INFORMATION32,
    MEMORY_BASIC_INFORMATION64,
    MEMORY_PROTECTION,
    MEMORY_STATE,
    MEMORY_TYPES,
    MODULEINFO,
    SYSTEM_INFO,
)
from typing_extensions import Union, cast

from pymhf.utils.winapi import (
    IMAGE_DOS_HEADER,
    IMAGE_DOS_SIGNATURE,
    IMAGE_FILE_HEADER,
    IMAGE_NT_SIGNATURE,
    IMAGE_SCN_MEM_EXECUTE,
    IMAGE_SCN_MEM_WRITE,
    IMAGE_SECTION_HEADER,
    GetSystemInfo,
    VirtualQueryEx,
)


def _is_hashable_page(mbi: Union[MEMORY_BASIC_INFORMATION32, MEMORY_BASIC_INFORMATION64]) -> bool:
    """Check if a memory page is suitable for hashing. The page must not change during runtime and/or
    between runs."""
    if mbi.State != MEMORY_STATE.MEM_COMMIT:
        return False
    if mbi.Type != MEMORY_TYPES.MEM_IMAGE:
        return False
    if mbi.Protect & (
        MEMORY_PROTECTION.PAGE_GUARD
        | MEMORY_PROTECTION.PAGE_WRITECOPY
        | MEMORY_PROTECTION.PAGE_EXECUTE_WRITECOPY
    ):
        return False
    if mbi.Protect & (MEMORY_PROTECTION.PAGE_READWRITE | MEMORY_PROTECTION.PAGE_EXECUTE_READWRITE):
        return False
    if not (mbi.Protect & (MEMORY_PROTECTION.PAGE_EXECUTE | MEMORY_PROTECTION.PAGE_EXECUTE_READ)):
        return False
    return True


def _get_page_size() -> int:
    """Get the system page size. Defaults to 4096 if it cannot be determined."""
    sys_info = SYSTEM_INFO()
    GetSystemInfo(ctypes.byref(sys_info))
    return sys_info.dwPageSize or 4096


def _get_main_module(pm_binary: pymem.Pymem) -> MODULEINFO:
    binary_path = psutil.Process(pm_binary.process_id).exe().lower()
    binary_exe = os.path.basename(binary_path).lower()

    main_module = None
    modules = list(pm_binary.list_modules())
    for module in modules:
        if module.filename.lower() == binary_path or module.name.lower() == binary_exe:
            main_module = module
            break
    if not main_module:
        main_module = modules[0]  # Usually the first module is the main module
        # Maybe raising an error or returning `None` here instead would be safer
        # raise OSError(f"Could not find main module for process {pid}")

    return main_module


def _get_sections_info(pm_binary: pymem.Pymem, address: int) -> tuple[int, int]:
    """Get the base address and number of sections in the PE file at the given address."""
    dos_header = cast(IMAGE_DOS_HEADER, pm_binary.read_ctype(address, IMAGE_DOS_HEADER()))
    if dos_header.e_magic != IMAGE_DOS_SIGNATURE:
        raise ValueError(f"Invalid DOS header magic for address 0x{address:X}")

    address += dos_header.e_lfanew
    signature = pm_binary.read_ctype(address, wintypes.DWORD())
    if signature != IMAGE_NT_SIGNATURE:
        raise ValueError(f"Invalid PE header signature for address 0x{address:X}")

    address += ctypes.sizeof(wintypes.DWORD)
    file_header = cast(IMAGE_FILE_HEADER, pm_binary.read_ctype(address, IMAGE_FILE_HEADER()))

    num_sections = int(file_header.NumberOfSections)
    opt_header_size = int(file_header.SizeOfOptionalHeader)
    sections_base = address + ctypes.sizeof(IMAGE_FILE_HEADER) + opt_header_size

    return sections_base, num_sections


def _get_read_only_sections(
    pm_binary: pymem.Pymem,
    sections_base: int,
    num_sections: int,
    max_module_size: int,
):
    """Get a list of read-only sections in the PE file at the given address."""
    sections = []
    for i in range(num_sections):
        section_address = sections_base + i * ctypes.sizeof(IMAGE_SECTION_HEADER)
        section_header = cast(
            IMAGE_SECTION_HEADER, pm_binary.read_ctype(section_address, IMAGE_SECTION_HEADER())
        )

        characteristics = section_header.Characteristics
        if not (characteristics & IMAGE_SCN_MEM_EXECUTE) or (characteristics & IMAGE_SCN_MEM_WRITE):
            continue

        virtual_addr = int(section_header.VirtualAddress)
        virtual_size = int(section_header.Misc.VirtualSize) or int(section_header.SizeOfRawData)
        if virtual_addr == 0 or virtual_size == 0:
            continue

        end_addr = min(virtual_addr + virtual_size, max_module_size)
        if end_addr <= virtual_addr:
            continue

        section = (
            virtual_addr,
            end_addr - virtual_addr,
            bytes(bytearray(section_header.Name)).rstrip(b"\x00").decode(errors="ignore"),
        )
        sections.append(section)

    return sections


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


def hash_bytes_from_memory(pm_binary: pymem.Pymem, _bufsize: int = 2**18) -> str:
    """Hash the bytes of the main module of the given `pymem.Pymem` instance.
    In order to ensure that the hash is stable across runs, this only read from sections that are not expected
    to change between runs."""
    process_handle = pm_binary.process_handle
    pid = pm_binary.process_id
    if not process_handle or not pid:
        raise ValueError("Pymem instance does not have a valid process handle")

    main_module = _get_main_module(pm_binary)
    if not main_module:
        raise OSError(f"Could not find main module for process {pid}")

    base_address = main_module.lpBaseOfDll
    module_size = main_module.SizeOfImage
    if not base_address or not module_size:
        raise OSError("Failed to resolve main module base/size")

    sections_base, num_sections = _get_sections_info(pm_binary, base_address)
    sections = _get_read_only_sections(pm_binary, sections_base, num_sections, module_size)
    if not sections:
        raise ValueError("No read-only sections found in the main module")
    sections.sort(key=lambda s: s[0])

    page_size = _get_page_size()
    digest = hashlib.sha1()
    buffer = (ctypes.c_ubyte * _bufsize)()
    for rva, size, name in sections:
        start = base_address + rva
        end = start + size
        address = start

        while address < end:
            page = MEMORY_BASIC_INFORMATION()
            if not VirtualQueryEx(
                process_handle,
                ctypes.c_void_p(address),
                ctypes.byref(page),
                ctypes.sizeof(page),
            ):
                address += page_size
                continue

            region_end = min(end, address + page.RegionSize)
            if not _is_hashable_page(page):
                address = region_end
                continue

            current = address
            while current < region_end:
                to_read = min(_bufsize, region_end - current)
                buffer = pm_binary.read_bytes(current, to_read)
                if len(buffer) == 0:
                    current = (current + page_size) & ~(page_size - 1)
                    if current < address:
                        current = address + page_size
                    continue

                digest.update(memoryview(buffer)[: len(buffer)])
                current += len(buffer)

            address = region_end

    return digest.hexdigest()
