import ast
import importlib.util
import logging
import os.path as op
import string
import sys
from types import ModuleType
from typing import Optional

from pymhf.gui.widget_data import ctx_group, ctx_group_counter

logger = logging.getLogger(__name__)


VALID_CHARS = string.ascii_letters + string.digits + "_"


def _clean_name(name: str) -> str:
    """Remove any disallowed characters from the filename so that we get a
    valid module name.
    """
    out = ""
    for char in name:
        if char not in VALID_CHARS:
            out += "_"
        else:
            out += char
    return out


def _fully_unpack_ast_attr(obj: ast.Attribute) -> str:
    name = ""
    _obj = obj
    while isinstance(_obj, ast.Attribute):
        if name:
            name = f"{_obj.attr}.{name}"
        else:
            name = _obj.attr
        _obj = _obj.value
    else:
        if isinstance(_obj, ast.Name):
            name = f"{_obj.id}.{name}"
    return name


def library_path_from_name(name: str) -> Optional[str]:
    if (spec := importlib.util.find_spec(name)) is not None:
        if spec.origin is not None:
            return op.dirname(spec.origin)


def parse_file_for_mod(data: str) -> bool:
    """Parse the provided data and determine if there is at least one mod class in it."""
    tree = ast.parse(data)
    mod_class_name = None
    for node in tree.body:
        # First, determine the name the Mod object is imported as.
        if isinstance(node, ast.Import):
            for node_ in node.names:
                if isinstance(node_, ast.alias):
                    if node_.name in ("pymhf", "pymhf.core.mod_loader"):
                        mod_class_name = (node_.asname or node_.name) + ".Mod"
        if isinstance(node, ast.ImportFrom):
            if node.module in ("pymhf", "pymhf.core.mod_loader"):
                for node_ in node.names:
                    if isinstance(node_, ast.alias):
                        if node_.name == "Mod":
                            mod_class_name = node_.asname or node_.name
        # Now, when we go over the class nodes, check the base classes.
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                # For a simple name, it's easy - just match it.
                if isinstance(base, ast.Name):
                    if base.id == mod_class_name:
                        return True
                # If it's an attribute it's a bit trickier...
                elif isinstance(base, ast.Attribute):
                    resolved_base = _fully_unpack_ast_attr(base)
                    if resolved_base == mod_class_name:
                        return True
    return False


def import_file(fpath: str) -> Optional[ModuleType]:
    try:
        # Ensure the context variables relating to groups are reset before each import to ensure they are
        # clean before this next import
        ctx_group.set(None)
        ctx_group_counter.set(0)
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
            if spec.loader:
                spec.loader.exec_module(module)
                return module
        else:
            print("failed")
    except Exception:
        logger.exception(f"Error loading {fpath}")
