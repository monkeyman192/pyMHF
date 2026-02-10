import os
import os.path as op
import re
from logging import getLogger
from typing import Optional

from pymhf.core._types import pymhfConfig

PATH_RE = re.compile(r"^\{(?P<tag>EXE_DIR|USER_DIR|CURR_DIR)\}(?P<rest>[^{}]*)$")


logger = getLogger(__name__)


def canonicalize_settings_inline(
    config: pymhfConfig,
    plugin_name: Optional[str],
    module_dir: str,
    exe_dir: Optional[str] = None,
    suffix: Optional[str] = None,
    filter: Optional[list[str]] = None,
):
    """Canonicalize all the settings in a config file. This will mutate the original config object.

    To only modify values containing a particular value, specify this in the `filter` argument."""

    def allow_value(value: str, filter: Optional[list[str]]):
        if filter is not None:
            return any(f in value for f in filter)
        else:
            return True

    for key, value in config.items():
        if isinstance(value, str):
            if allow_value(value, filter):
                config[key] = canonicalize_setting(value, plugin_name, module_dir, exe_dir, suffix)
        elif isinstance(value, dict):
            subdata = {}
            for subkey, subvalue in value.items():
                if isinstance(subvalue, str):
                    if allow_value(subvalue, filter):
                        subdata[subkey] = canonicalize_setting(
                            subvalue,
                            plugin_name,
                            module_dir,
                            exe_dir,
                            suffix,
                        )
                else:
                    subdata[subkey] = subvalue
            config[key] = subdata
        else:
            config[key] = value


def canonicalize_setting(
    value: Optional[str],
    plugin_name: Optional[str],
    module_dir: str,
    exe_dir: Optional[str] = None,
    suffix: Optional[str] = None,
) -> Optional[str]:
    """Convert the "magic" names into real values.

    Possible keys:
    - EXE_DIR
    - USER_DIR / "~"
    - CURR_DIR / "."
    """

    # This can receive None as the value.
    # In this case we simply return as we don't want to do anything with it.
    if not isinstance(value, str):
        return None

    # Parse the value to determine what directory type we are asking for.
    tag = None
    rest = tuple()
    if (m := re.match(PATH_RE, value)) is not None:
        tag = m["tag"]
        if m["rest"]:
            rest = op.split(m["rest"].strip("/\\"))
    else:
        if value == ".":
            tag = "CURR_DIR"
        elif value == "~":
            tag = "USER_DIR"
        elif not op.exists(value):
            logger.error(f"Path doesn't exist: {value}")
            return None

    # If the path provided already exists, simply return it.
    if tag is None and op.exists(value):
        return value

    if suffix is None:
        _suffix = rest
    else:
        _suffix = rest + (suffix,)

    if tag == "USER_DIR":
        appdata_data = os.environ.get("APPDATA", op.expanduser("~"))
        if appdata_data == "~":
            # In this case the APPDATA environment variable isn't set and ~ also fails to resolve.
            # Raise a error and stop.
            print("Critical Error: Cannot find user directory. Ensure APPDATA environment variable is set")
            exit()
        if plugin_name is not None:
            return op.realpath(op.join(appdata_data, "pymhf", plugin_name, *_suffix))
        else:
            raise ValueError("{USER_DIR} cannot be used for single-file mods.")
    elif tag == "EXE_DIR":
        if exe_dir:
            return op.realpath(op.join(exe_dir, *_suffix))
        else:
            raise ValueError("Exe directory cannot be determined")
    elif tag == "CURR_DIR":
        return op.realpath(op.join(module_dir, *_suffix))


def merge_configs(src: pymhfConfig, dst: pymhfConfig):
    """Merge the source config into the dest config. Overwriting any values."""
    for key, value in src.items():
        if not isinstance(value, dict):
            dst[key] = value
        else:
            for subkey, subvalue in value.items():
                if key not in dst:
                    dst[key] = {}
                dst[key][subkey] = subvalue
