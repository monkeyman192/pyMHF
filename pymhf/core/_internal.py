import ctypes
from concurrent.futures import ThreadPoolExecutor

from pymhf.core._types import LoadTypeEnum, pymhfConfig

CWD: str = ""
MODULE_PATH: str = ""
HANDLE = None
MAIN_HWND = None
DPG_HWND = None
PID: int = -1
BINARY_HASH: str = ""
BASE_ADDRESS: int = -1
SIZE_OF_IMAGE: int = -1
CONFIG: pymhfConfig = {}
EXE_NAME: str = ""
BINARY_PATH: str = ""
LOAD_TYPE: LoadTypeEnum = LoadTypeEnum.INVALID
MOD_SAVE_DIR: str = ""
INCLUDED_ASSEMBLIES: dict[str, str] = {}
CACHE_DIR: str = ""
_SENTINEL_PTR: int = 0

_executor: ThreadPoolExecutor = None  # type: ignore

imports: dict[str, dict[str, ctypes._CFuncPtr]] = {}
