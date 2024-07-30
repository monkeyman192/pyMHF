from importlib.metadata import version, PackageNotFoundError, entry_points
import os.path as op
import sys

from .main import load_module  # noqa
from .core.hooking import FuncHook  # noqa
from .core.mod_loader import Mod, ModState  # noqa
from .core._types import FUNCDEF  # noqa


try:
    __version__ = version("pymhf")
except PackageNotFoundError:
    pass


def run():
    """ Main entrypoint which can be used to run programs with pymhf.
    This will take the first argument as the name of a module which has been installed."""
    libname = sys.argv[-1]
    eps = entry_points()
    # This check is to ensure compatibility with multiple versions of python as the code 3.10+ isn't backward
    # compatible.
    if isinstance(eps, dict):
        loaded_libs = eps.get("pymhflib", [])
    else:
        loaded_libs = eps.select(group="pymhflib")
    required_lib = None
    for lib in loaded_libs:
        if lib.name.lower() == libname.lower():
            required_lib = lib
    if required_lib:
        loaded_lib = required_lib.load()
        load_module(op.dirname(loaded_lib.__file__))
    else:
        print(f"Cannot find {libname} as an installed plugin. "
              "Please ensure it has been installed and try again")
