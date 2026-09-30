# Test functions in the pymhf.core.importing file
import pytest

from pymhf.core.importing import ModInfo, get_mod_infos, parse_file_for_mod

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


DISABLED_STANDARD_IMPORT = """
from pymhf import Mod
from pymhf.core.hooking import disable

@disable
class Thing(Mod):
    pass
"""

DISABLED_ALIAS_IMPORT = """
from pymhf import Mod
from pymhf.core.hooking import disable as off

@off
class Thing(Mod):
    pass
"""

DISABLED_MODULE_IMPORT = """
from pymhf import Mod
import pymhf.core.hooking

@pymhf.core.hooking.disable
class Thing(Mod):
    pass
"""

DISABLED_MODULE_ALIAS_IMPORT = """
from pymhf import Mod
import pymhf.core.hooking as hooking

@hooking.disable
class Thing(Mod):
    pass
"""

DISABLED_TOP_LEVEL_MODULE_IMPORT = """
import pymhf

@pymhf.core.hooking.disable
class Thing(pymhf.Mod):
    pass
"""

# The decorator is applied along with others, and isn't the one applied first.
DISABLED_MULTIPLE_DECORATORS = """
from pymhf import Mod
from pymhf.core.hooking import disable

@no_gui
@disable
class Thing(Mod):
    pass
"""

# A decorator which has nothing to do with disabling the mod.
OTHER_DECORATOR = """
from pymhf import Mod

@no_gui
class Thing(Mod):
    pass
"""

# `disable` is imported, but the mod isn't decorated with it.
DISABLE_IMPORTED_BUT_UNUSED = """
from pymhf import Mod
from pymhf.core.hooking import disable

class Thing(Mod):
    pass
"""

# Only one of the mods in the file is disabled, so the file still has to be imported.
MULTIPLE_MODS_ONE_DISABLED = """
from pymhf import Mod
from pymhf.core.hooking import disable

@disable
class OldThing(Mod):
    pass

class NewThing(Mod):
    pass
"""

MULTIPLE_MODS_ALL_DISABLED = """
from pymhf import Mod
from pymhf.core.hooking import disable

@disable
class OldThing(Mod):
    pass

@disable
class NewThing(Mod):
    pass
"""

# The `Mod` class is imported in two different ways, and both may be used.
MULTIPLE_MOD_IMPORT_STYLES = """
import pymhf
from pymhf import Mod

class Thing(pymhf.Mod):
    pass

class OtherThing(Mod):
    pass
"""


@pytest.mark.parametrize(
    "data,result",
    [
        (STANDARD_IMPORT, [ModInfo("Thing", False)]),
        (STANDARD_FROM_IMPORT, [ModInfo("Thing", False)]),
        (ALIAS_IMPORT, [ModInfo("Thing", False)]),
        (ALIAS_FROM_IMPORT, [ModInfo("Thing", False)]),
        (FULL_PATH_STANDARD_IMPORT, [ModInfo("Thing", False)]),
        (FULL_PATH_STANDARD_FROM_IMPORT, [ModInfo("Thing", False)]),
        (FULL_PATH_ALIAS_IMPORT, [ModInfo("Thing", False)]),
        (FULL_PATH_ALIAS_FROM_IMPORT, [ModInfo("Thing", False)]),
        (NO_IMPORT, []),
        (NO_IMPORT2, []),
        (INCORRECT_IMPORT, []),
        (NO_MOD_CLASS, []),
        (DISABLED_STANDARD_IMPORT, [ModInfo("Thing", True)]),
        (DISABLED_ALIAS_IMPORT, [ModInfo("Thing", True)]),
        (DISABLED_MODULE_IMPORT, [ModInfo("Thing", True)]),
        (DISABLED_MODULE_ALIAS_IMPORT, [ModInfo("Thing", True)]),
        (DISABLED_TOP_LEVEL_MODULE_IMPORT, [ModInfo("Thing", True)]),
        (DISABLED_MULTIPLE_DECORATORS, [ModInfo("Thing", True)]),
        (OTHER_DECORATOR, [ModInfo("Thing", False)]),
        (DISABLE_IMPORTED_BUT_UNUSED, [ModInfo("Thing", False)]),
        (MULTIPLE_MODS_ONE_DISABLED, [ModInfo("OldThing", True), ModInfo("NewThing", False)]),
        (MULTIPLE_MODS_ALL_DISABLED, [ModInfo("OldThing", True), ModInfo("NewThing", True)]),
        (MULTIPLE_MOD_IMPORT_STYLES, [ModInfo("Thing", False), ModInfo("OtherThing", False)]),
    ],
)
def test_get_mod_infos(data: str, result: list[ModInfo]):
    assert get_mod_infos(data) == result
