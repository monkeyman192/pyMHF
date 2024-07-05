import importlib
import importlib.util
import logging
import os.path as op
import traceback
from types import ModuleType
from typing import Optional
import string
import sys


logger = logging.getLogger("pymfh.core.importing")


VALID_CHARS = string.ascii_letters + string.digits + "_"


def _clean_name(name: str) -> str:
    """ Remove any disallowed characters from the filename so that we get a
    valid module name."""
    out = ''
    for char in name:
        if char not in VALID_CHARS:
            out += "_"
        else:
            out += char
    return out


def import_file(fpath: str) -> Optional[ModuleType]:
    try:
        module_name = _clean_name(op.splitext(op.basename(fpath))[0])
        if op.isdir(fpath):
            # If a directory is passed in, then add __init__.py to it so that
            # we may correctly import it.
            fpath = op.join(fpath, "__init__.py")
        if spec := importlib.util.spec_from_file_location(module_name, fpath):
            module = importlib.util.module_from_spec(spec)
            module.__name__ = module_name
            module.__spec__ = spec
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        else:
            print("failed")
    except Exception:
        logger.error(f"Error loading {fpath}")
        logger.exception(traceback.format_exc())
