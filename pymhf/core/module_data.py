# TODO: This is imported already by some things. We maybe need to create an
# object which contains this data as attributes so that we may set them after
# import more easily.
from typing import Union

from pymhf.core._types import FUNCDEF

# Load order:
# 1. Look up offsets based on binary hash in offset cache (#TODO: implement)
# 2. Look up patterns
# 3. Use offsets

# NOTE: The above is just temporary. Need to figure out a more robust way to specify this.
# (Well, the order of 2 and 3 should be swapped likely. Need a way to specify which to use...)


class ModuleData:
    FUNC_OFFSETS: dict[str, Union[int, dict[str, int]]]
    FUNC_PATTERNS: dict[str, Union[str, dict[str, str]]]
    FUNC_CALL_SIGS: dict[str, Union[FUNCDEF, dict[str, FUNCDEF]]]


module_data = ModuleData()
