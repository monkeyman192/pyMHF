import ctypes
import os.path as op
import sys
from logging import getLogger

import pefile

imports = {}

logger = getLogger(__name__)


SPHINX_AUTODOC_RUNNING = "sphinx.ext.autodoc" in sys.modules


def get_imports(binary_path: str) -> dict[str, ctypes._CFuncPtr]:
    directory, binary = op.split(binary_path)
    pe = pefile.PE(op.join(directory, binary), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    if not hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        return {}
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        dll_name: str = entry.dll.decode()
        if dll_name.lower().endswith(".dll"):
            dll_name = dll_name.lower()[:-4]
        dll_imports = []
        for imp in entry.imports:
            if imp.name:
                dll_imports.append(imp.name.decode())
        imports[dll_name] = dll_imports

    funcptrs = {}
    for _dll, dll_imports in imports.items():
        try:
            dll = ctypes.WinDLL(_dll)
        except FileNotFoundError:
            # Re-add .dll to the end since absolute paths require the full path.
            fullpath = op.join(directory, _dll) + ".dll"
            try:
                dll = ctypes.WinDLL(fullpath)
            except FileNotFoundError:
                logger.error(f"Cannot find dll {_dll} (even at {fullpath})")
                continue
        _funcptrs = {}
        for name in dll_imports:
            func_ptr = getattr(dll, name, None)
            if func_ptr is None:
                logger.error(f"Cannot find function {_dll}.{name}")
                continue
            _funcptrs[name] = func_ptr
        funcptrs[_dll] = _funcptrs

    return funcptrs
