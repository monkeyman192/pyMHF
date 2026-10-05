import os.path as op
from logging import StreamHandler, getLogger, DEBUG
import sys

from pymhf.core.hooking import hook_manager
from pymhf.core.mod_loader import mod_manager
from pymhf.gui.gui import GUI

logger = getLogger()
logger.addHandler(StreamHandler(sys.stdout))
logger.setLevel(DEBUG)


def run_gui():
    mod_manager.hook_manager = hook_manager
    mod_manager.load_single_mod(op.join(op.dirname(__file__), "gui_test_mod_simple.py"))
    gui = GUI(mod_manager, {"gui": {"scale": 1}})
    mod_manager._gui = gui
    for mod in mod_manager.mods.values():
        gui.add_tab(mod)
    gui.add_hex_tab()
    gui.add_settings_tab()
    gui.add_details_tab()
    gui.run()


if __name__ == "__main__":
    run_gui()
