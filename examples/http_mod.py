# /// script
# dependencies = ["pymhf[gui,http_api]"]
#
# [tool.pymhf]
# exe = "Notepad.exe"
# start_paused = false
# start_exe = false
# interactive_console = false
#
# [tool.pymhf.logging]
# log_dir = "."
# log_level = "info"
# ///

from pymhf import Mod, load_mod_file
from pymhf.core.http_api import endpoint


class HTTPMod(Mod):
    def __init__(self):
        super().__init__()
        self.value = 0

    @property
    @endpoint()
    def money(self):
        return self.value

    @money.setter
    def money(self, value):
        self.value = value


if __name__ == "__main__":
    load_mod_file(__file__)
