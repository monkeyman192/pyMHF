import ctypes
from concurrent.futures import ThreadPoolExecutor
from enum import Enum


class LoadTypeEnum(Enum):
    INVALID = 0
    SINGLE_FILE = 1
    LIBRARY = 2
    MOD_FOLDER = 3


CWD: str = ""
MODULE_PATH: str = ""
HANDLE = None
MAIN_HWND = None
DPG_HWND = None
PID: int = -1
BINARY_HASH: str = ""
BASE_ADDRESS: int = -1
SIZE_OF_IMAGE: int = -1
CONFIG: dict = {}
EXE_NAME: str = ""
BINARY_PATH: str = ""
LOAD_TYPE: LoadTypeEnum = LoadTypeEnum.INVALID
MOD_SAVE_DIR: str = ""
INCLUDED_ASSEMBLIES: dict[str, str] = {}

_executor: ThreadPoolExecutor = None  # type: ignore

imports: dict[str, dict[str, ctypes._CFuncPtr]] = {}
