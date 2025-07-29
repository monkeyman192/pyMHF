# /// script
# dependencies = ["pymhf[gui]>=0.1.15"]
# 
# [tool.pymhf]
# exe = "notepad.exe"
# start_paused = false
# start_exe = false
#
# [tool.pymhf.gui]
# always_on_top = false
# 
# [tool.pymhf.logging]
# log_dir = "."
# log_level = "info"
# window_name_override = "pyMHF Test Mod"
# ///
from logging import getLogger

from pymhf import Mod

logger = getLogger("TestMod")


class TestMod(Mod):
    __author__ = "monkeyman192"
    __description__ = "Test mod to check if pyMHF works"

    def __init__(self):
        super().__init__()
        logger.info("Loaded Test mod!")
