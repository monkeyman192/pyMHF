from concurrent.futures import ThreadPoolExecutor

CWD: str = ""
MODULE_PATH: str = ""
HANDLE = None
MAIN_HWND = None
PID: int = -1
BINARY_HASH: str = ""
BASE_ADDRESS: int = -1
SIZE_OF_IMAGE: int = -1
CFG_DIR: str = ""
EXE_NAME: str = ""

_executor: ThreadPoolExecutor = None  # type: ignore


class _GameState:
    def __init__(self):
        self._game_loaded = False

    @property
    def game_loaded(self):
        return self._game_loaded

    @game_loaded.setter
    def game_loaded(self, val: bool):
        # The game can become loaded, but it can't become unloaded...
        if val is True:
            self._game_loaded = val


GameState: _GameState = _GameState()
