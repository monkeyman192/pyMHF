import os.path as op
from subprocess import Popen

from pymhf import run_module

if __name__ == "__main__":
    # Run a mod by creating the process and then attaching pymhf later.
    # It is generally recommended that you just use pyMHF's built-in functionality for doing this.
    proc = Popen("notepad.exe")
    CONFIG = {
        "pid": proc.pid,
        "start_paused": False,
        "start_exe": False,
    }
    run_module(op.join(op.dirname(__file__), "test_mod.py"), CONFIG, None, None)
