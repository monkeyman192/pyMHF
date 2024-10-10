import re
from typing import Optional

import tomlkit

REGEX = r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"


def read_toml(script: str) -> Optional[dict]:
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
        return tomlkit.loads(content)
    else:
        return None


def get_pymhf_settings(script: str) -> dict:
    settings = read_toml(script)
    return settings.get("tool", {}).get("pymhf", {})
