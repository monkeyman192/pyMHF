import re
from typing import Optional

import tomlkit

REGEX = r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"


def read_inline_metadata(script: str) -> Optional[tomlkit.TOMLDocument]:
    """Read a file and extract the toml info contained in the script if there is one.
    This is taken directly from the reference implementation in https://peps.python.org/pep-0723/
    and modified to use `tomlkit` to ensure compatibility for python 3.9+
    """
    name = "script"
    matches = list(filter(lambda m: m.group("type") == name, re.finditer(REGEX, script)))
    if len(matches) > 1:
        raise ValueError(f"Multiple {name} blocks found")
    elif len(matches) == 1:
        content = "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in matches[0].group("content").splitlines(keepends=True)
        )
        return tomlkit.parse(content)
    else:
        return None


def _parse_toml(fpath: str, standalone: bool = False) -> dict:
    settings = {}
    with open(fpath, "r") as f:
        if standalone:
            settings = read_inline_metadata(f.read())
        else:
            settings = tomlkit.loads(f.read())
    return settings


def read_pymhf_settings(fpath: str, standalone: bool = False) -> dict:
    settings = _parse_toml(fpath, standalone)
    if not settings:
        return {}
    if standalone:
        return settings.get("tool", {}).get("pymhf", {})
    else:
        return settings.get("pymhf", {})


def write_pymhf_settings(settings: dict, fpath: str):
    """Write the pymhf settings to disk as a toml file.
    This will automatically add the `pymhf` top section.
    """
    with open(fpath, "w") as f:
        tomlkit.dump({"pymhf": settings}, f)
