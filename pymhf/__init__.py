from importlib.metadata import version, PackageNotFoundError

from .main import load_module  # noqa
from .core.hooking import FuncHook  # noqa
from .core.mod_loader import Mod, ModState  # noqa


try:
    __version__ = version("pymhf")
except PackageNotFoundError:
    pass

