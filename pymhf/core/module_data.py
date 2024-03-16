# TODO: This is imported already by some things. We maybe need to create an
# object which contains this data as attributes so that we may set them after
# import more easily.
from typing import Union

from pymhf.core._types import FUNCDEF


class ModuleData:
    FUNC_OFFSETS: dict[str, Union[int, dict[str, int]]]
    FUNC_CALL_SIGS: dict[str, Union[FUNCDEF, dict[str, FUNCDEF]]]


module_data = ModuleData()
