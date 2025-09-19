# /// script
# dependencies = ["pymhf[gui]==0.1.11"]
#
# [tool.uv.sources]
# pymhf = { index = "pypi_test" }
#
# [[tool.uv.index]]
# name = "pypi_test"
# url = "https://test.pypi.org/simple/"
# explicit = true
# 
# [tool.pymhf]
# exe = "NMS.exe"
# steam_gameid = 275850
# start_paused = false
#
# [tool.pymhf.gui]
# always_on_top = true
# 
# [tool.pymhf.logging]
# log_dir = "."
# log_level = "info"
# window_name_override = "NMS audio thing"
# ///
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
from dataclasses import dataclass
from typing import Annotated, Optional, overload

import pymhf.core._internal as _internal
from pymhf import Mod
from pymhf.core.hooking import (
    Structure,
    disable,
    function_hook,
    get_caller,
    on_key_pressed,
    static_function_hook,
)
from pymhf.core.memutils import get_addressof, map_struct
from pymhf.core.mod_loader import ModState
from pymhf.core.utils import set_main_window_active
from pymhf.gui.decorators import BOOLEAN, STRING, gui_button, gui_combobox
from pymhf.utils.partial_struct import Field, partial_struct

logger = logging.getLogger("AudioNames")

FUNC_NAME = "?PostEvent@SoundEngine@AK@@YAII_KIP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXIPEAUAkExternalSourceInfo@@I@Z"
REGISTER_FUNC = "?RegisterGameObj@SoundEngine@AK@@YA?AW4AKRESULT@@_KPEBD@Z"


@static_function_hook(exported_name="multiply")
def multiply(a: ctypes.c_int32, b: ctypes.c_int64) -> ctypes.c_int64:
    ...


@dataclass
class AudioState(ModState):
    event_id: int = 0
    obj_id: int = 0
    play_sounds: bool = True
    log_sounds: bool = True


class AppMod(Mod):
    __author__ = "monkeyman192"
    __description__ = "Log (almost) all audio events when they happen"
    __version__ = "0.1"

    state = AudioState()

    def __init__(self):
        super().__init__()
        self.audio_manager = None
        self.count = 0

    @multiply.before
    def before_multiply(self, a: int, b: int):
        print(a, b)

    @multiply.after
    def after_play_attenuated(self, a: int, b: int, _result_: int):
        print(a, b, _result_)
