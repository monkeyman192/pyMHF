import re
from enum import IntEnum

import pytest

from pymhf.extensions.ctypes import c_enum8, c_enum16, c_enum32


def test_c_enum8():
    class Alphabet(IntEnum):
        A = 0
        B = 1
        C = 2
        D = 3
        E = 4
        F = 5
        G = 6
        H = 7

    alpha = c_enum8[Alphabet]

    assert alpha._members() == ["A", "B", "C", "D", "E", "F", "G", "H"]
    letter = alpha.from_buffer(bytearray(b"\x06"))
    assert letter == Alphabet.G
    assert str(letter) == "G"
    assert repr(letter) == repr(Alphabet.G)
    # If the buffer is too big it won't care.
    assert alpha.from_buffer(bytearray(b"\x07\x01")) == Alphabet.H

    # Check passing something that isn't an enum as the type raises a TypeError.
    with pytest.raises(TypeError):
        c_enum8[22]

    # Check that passing an unknown value shows the right value
    bad_letter = alpha.from_buffer(bytearray(b"\x09"))
    assert str(bad_letter) == "INVALID ENUM VALUE: 9"

    # Check that passing something with values too big causes an error.
    with pytest.raises(ValueError, match="Assigned enum has a value too big to fit into 1 byte: 256."):

        class MyEnum(IntEnum):
            A = 0
            B = 0x0FF
            C = 0x100

        c_enum8[MyEnum]


def test_c_enum16():
    class Alphabet(IntEnum):
        A = 0x0
        B = 0x1
        C = 0x2
        D = 0x4
        E = 0x6
        F = 0x10
        G = 0x20
        H = 0x40
        I = 0x80  # noqa
        J = 0x100

    alpha = c_enum16[Alphabet]

    assert alpha._members() == ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    letter = alpha.from_buffer(bytearray(b"\x00\x01"))
    assert letter == Alphabet.J
    assert str(letter) == "J"
    assert repr(letter) == repr(Alphabet.J)

    # Check passing something that isn't an enum as the type raises a TypeError.
    with pytest.raises(TypeError):
        c_enum16[22]

    # Check that passing an unknown value shows the right value
    bad_letter = alpha.from_buffer(bytearray(b"\x09\x00"))
    assert str(bad_letter) == "INVALID ENUM VALUE: 9"

    with pytest.raises(ValueError, match=re.escape("Buffer size too small (1 instead of at least 2 bytes)")):
        alpha.from_buffer(bytearray(b"\x09"))

    # Check that passing something with values too big causes an error.
    with pytest.raises(ValueError, match="Assigned enum has a value too big to fit into 2 bytes: 65536."):

        class MyEnum(IntEnum):
            A = 0
            B = 0x0FFFF
            C = 0x10000

        c_enum16[MyEnum]


def test_c_enum32():
    class Alphabet(IntEnum):
        A = 0x0
        B = 0x10
        C = 0x1_00
        D = 0x10_00
        E = 0x1_00_00
        F = 0x10_00_00
        G = 0x1_00_00_00
        H = 0x10_00_00_00

    alpha = c_enum32[Alphabet]

    assert alpha._members() == ["A", "B", "C", "D", "E", "F", "G", "H"]
    letter = alpha.from_buffer(bytearray(b"\x00\x00\x00\x10"))
    assert letter == Alphabet.H
    assert str(letter) == "H"
    assert repr(letter) == repr(Alphabet.H)

    # Check passing something that isn't an enum as the type raises a TypeError.
    with pytest.raises(TypeError):
        c_enum32[22]

    # Check that passing an unknown value shows the right value
    bad_letter = alpha.from_buffer(bytearray(b"\x09\x00\x00\x00"))
    assert str(bad_letter) == "INVALID ENUM VALUE: 9"

    with pytest.raises(ValueError, match=re.escape("Buffer size too small (2 instead of at least 4 bytes)")):
        alpha.from_buffer(bytearray(b"\x09\x00"))

    # Check that passing something with values too big causes an error.
    with pytest.raises(
        ValueError, match="Assigned enum has a value too big to fit into 4 bytes: 4294967296."
    ):

        class MyEnum(IntEnum):
            A = 0
            B = 0x0FFFFFFFF
            C = 0x100000000

        c_enum32[MyEnum]
