from enum import IntEnum

import pytest

from pymhf.extensions.ctypes import c_enum32


def test_invalid_c_enum32_cases():
    with pytest.raises(TypeError):
        c_enum32[22]


def test_c_enum_members():
    class Alphabet(IntEnum):
        A = 0
        B = 1
        C = 2
        D = 3
        E = 4

    assert c_enum32[Alphabet]._members() == ["A", "B", "C", "D", "E"]
