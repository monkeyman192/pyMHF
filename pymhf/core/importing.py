import ast
import importlib.util
import logging
import os.path as op
import string
import sys
from types import ModuleType
from typing import NamedTuple, Optional

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


class ModInfo(NamedTuple):
    """Details of a mod class which can be determined without importing the file it's defined in."""

    name: str
    disabled: bool


def _is_disable_decorator(decorator: ast.expr, disable_names: set[str]) -> bool:
    if isinstance(decorator, ast.Name):
        return decorator.id in disable_names
    if isinstance(decorator, ast.Attribute):
        return _fully_unpack_ast_attr(decorator) in disable_names
    return False


def get_mod_infos(data: str) -> list[ModInfo]:
    """Parse the provided data and return the details of every mod class defined in it.

    This allows the name of each mod, and whether it has been decorated with ``@disable``, to be determined
    without importing the file they are defined in.
    """
    tree = ast.parse(data)
    # A file may import the names we are looking for in more than one way, so keep track of every name each
    # object may be referred to as.
    mod_class_names: set[str] = set()
    disable_names: set[str] = set()
    mods: list[ModInfo] = []
    for node in tree.body:
        # First, determine the names the Mod class and the disable decorator are imported as. Both node
        # types list the aliases they bind in `names`, so the name each object is referred to by is found
        # the same way for either of them.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for node_ in node.names:
                if not isinstance(node_, ast.alias):
                    continue
                name = node_.asname or node_.name
                if isinstance(node, ast.Import):
                    if node_.name in ("pymhf", "pymhf.core.mod_loader"):
                        mod_class_names.add(f"{name}.Mod")
                    if node_.name == "pymhf":
                        # `disable` isn't exposed at the top level, but the submodule it's in is reachable.
                        disable_names.add(f"{name}.core.hooking.disable")
                    elif node_.name == "pymhf.core.hooking":
                        disable_names.add(f"{name}.disable")
                else:
                    if node_.name == "Mod" and node.module in ("pymhf", "pymhf.core.mod_loader"):
                        mod_class_names.add(name)
                    elif node_.name == "disable" and node.module == "pymhf.core.hooking":
                        disable_names.add(name)
        # Now, when we go over the class nodes, check the base classes.
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                # For a simple name, it's easy - just match it.
                if isinstance(base, ast.Name):
                    resolved_base = base.id
                # If it's an attribute it's a bit trickier...
                elif isinstance(base, ast.Attribute):
                    resolved_base = _fully_unpack_ast_attr(base)
                else:
                    continue
                if resolved_base in mod_class_names:
                    disabled = any(_is_disable_decorator(d, disable_names) for d in node.decorator_list)
                    mods.append(ModInfo(node.name, disabled))
                    break
    return mods


def parse_file_for_mod(data: str) -> bool:
    """Parse the provided data and determine if there is at least one mod class in it."""
    return len(get_mod_infos(data)) != 0


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
