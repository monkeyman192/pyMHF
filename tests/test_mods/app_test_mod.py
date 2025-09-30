# /// script
# dependencies = ["pymhf[gui]>=0.1.16"]
#
# [tool.pymhf]
# exe = "../programs/app.exe"
# start_exe = true
# start_paused = true
# interactive_console = false
# args = [2, 3]
#
# [tool.pymhf.gui]
# always_on_top = true
#
# [tool.pymhf.logging]
# log_dir = "."
# log_level = "info"
# window_name_override = "Test mod"
# ///
from __future__ import annotations

import ctypes
import logging

from pymhf import Mod
from pymhf.core.hooking import static_function_hook

logger = logging.getLogger("TestLogger")


@static_function_hook(exported_name="multiply")
def multiply(a: ctypes.c_int32, b: ctypes.c_int64) -> ctypes.c_int64: ...


class AppMod(Mod):
    @multiply.before
    def before_multiply(self, a: int, b: int):
        # Let's double the inputs
        logger.info(f"Doubling the inputs {a} and {b}")
        return 2 * a, 2 * b

    @multiply.after
    def after_multiply(self, a: int, b: int, _result_: int):
        logger.info(f"({a} * 2) * ({b} * 2) = {_result_}")
