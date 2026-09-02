# Test functions in the pymhf.core.importing file
from typing import Optional

import pytest

from pymhf.core.importing import get_mod_name, parse_file_for_mod

# "files" which will pass.
STANDARD_IMPORT = """
import pymhf
class Thing(pymhf.Mod):
    pass
"""

STANDARD_FROM_IMPORT = """
from pymhf import Mod
class Thing(Mod):
    pass
"""

ALIAS_IMPORT = """
import pymhf as pmf
class Thing(pmf.Mod):
    pass
"""

ALIAS_FROM_IMPORT = """
from pymhf import Mod as mod
class Thing(mod):
    pass
"""

FULL_PATH_STANDARD_IMPORT = """
import pymhf.core.mod_loader
class Thing(pymhf.core.mod_loader.Mod):
    pass
"""

FULL_PATH_STANDARD_FROM_IMPORT = """
from pymhf.core.mod_loader import Mod
class Thing(Mod):
    pass
"""

FULL_PATH_ALIAS_IMPORT = """
import pymhf.core.mod_loader as pmf
class Thing(pmf.Mod):
    pass
"""

FULL_PATH_ALIAS_FROM_IMPORT = """
from pymhf.core.mod_loader import Mod as mod
class Thing(mod):
    pass
"""

# "files" which will fail.
NO_IMPORT = """
class Thing(Mod):
    pass
"""

NO_IMPORT2 = """
class Thing(pymhf.Mod):
    pass
"""

INCORRECT_IMPORT = """
from pymhf.core import Mod
class Thing(Mod):
    pass
"""

NO_MOD_CLASS = """
from pymhf import Mod
class Thing():
    pass
"""


@pytest.mark.parametrize(
    "data,result",
    [
        (STANDARD_IMPORT, True),
        (STANDARD_FROM_IMPORT, True),
        (ALIAS_IMPORT, True),
        (ALIAS_FROM_IMPORT, True),
        (FULL_PATH_STANDARD_IMPORT, True),
        (FULL_PATH_STANDARD_FROM_IMPORT, True),
        (FULL_PATH_ALIAS_IMPORT, True),
        (FULL_PATH_ALIAS_FROM_IMPORT, True),
        (NO_IMPORT, False),
        (NO_IMPORT2, False),
        (INCORRECT_IMPORT, False),
        (NO_MOD_CLASS, False),
    ],
)
def test_parse_file_for_mod(data: str, result: bool):
    assert parse_file_for_mod(data) is result


@pytest.mark.parametrize(
    "data,result",
    [
        (STANDARD_IMPORT, "Thing"),
        (STANDARD_FROM_IMPORT, "Thing"),
        (ALIAS_IMPORT, "Thing"),
        (ALIAS_FROM_IMPORT, "Thing"),
        (FULL_PATH_STANDARD_IMPORT, "Thing"),
        (FULL_PATH_STANDARD_FROM_IMPORT, "Thing"),
        (FULL_PATH_ALIAS_IMPORT, "Thing"),
        (FULL_PATH_ALIAS_FROM_IMPORT, "Thing"),
        (NO_IMPORT, None),
        (NO_IMPORT2, None),
        (INCORRECT_IMPORT, None),
        (NO_MOD_CLASS, None),
    ],
)
def test_get_mod_name(data: str, result: Optional[str]):
    assert get_mod_name(data) == result
