from importlib.metadata import version, PackageNotFoundError


try:
    __version__ = version("pymhf")
except PackageNotFoundError:
    __version__ = "0.1.1"
