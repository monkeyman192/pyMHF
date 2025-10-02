import ctypes
import re
import types
from enum import IntEnum
from typing import Annotated, Generic, Type, TypeVar, Union

import pytest

from pymhf.extensions.ctypes import c_enum32
from pymhf.utils.partial_struct import Field, partial_struct


def test_simple_structure():
    @partial_struct
    class Test(ctypes.Structure):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
    ]

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00")
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b == 5
    assert bytes(t) == bytes(data)

    # Also test modifying a value.
    t.a = 42
    assert bytes(t) == b"\x2a\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00"


def test_simple_structure_with_enum():
    class Alphabet(IntEnum):
        A = 0
        B = 1
        C = 2
        D = 3
        E = 4

    @partial_struct
    class Test(ctypes.Structure):
        a: Annotated[c_enum32[Alphabet], 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]

    assert Test._fields_ == [
        ("a", c_enum32[Alphabet]),
        ("_padding_4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
    ]

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00")
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.a == Alphabet.B
    assert t.b == 5
    assert bytes(t) == bytes(data)

    # Test modifying the enum value
    t.a = Alphabet.D
    assert bytes(t) == b"\x03\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00"


def test_simple_structure_with_total_size():
    # Test case for the partial struct having a _total_size_ attribute.
    @partial_struct
    class Test(ctypes.Structure):
        _total_size_ = 0x18
        a: Annotated[int, Field(ctypes.c_uint32)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
        ("_padding_14", ctypes.c_ubyte * 0x4),
    ]

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x00"
    )
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b == 5
    assert bytes(t) == bytes(data)


def test_nested_structs():
    # Test for one of the fields being a struct nested within the currently defined one.
    @partial_struct
    class Test(ctypes.Structure):
        class Sub(ctypes.Structure):
            _fields_ = [
                ("sub_a", ctypes.c_uint16),
                ("sub_b", ctypes.c_uint16),
            ]

        _total_size_ = 24
        a: ctypes.c_uint32
        b_sub: Sub
        c: Annotated[ctypes.c_uint32, 0x8]
        d: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("b_sub", Test.Sub),
        ("c", ctypes.c_uint32),
        ("_padding_C", ctypes.c_ubyte * 0x4),
        ("d", ctypes.c_uint32),
        ("_padding_14", ctypes.c_ubyte * 0x4),
    ]

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x00"
    )
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b_sub.sub_a == 2
    assert t.b_sub.sub_b == 0
    assert t.c == 3
    assert t.d == 5

    assert bytes(t) == bytes(data)


def test_annotated_struct():
    # Test the case of the type being an annotation.

    class Sub(ctypes.Structure):
        _fields_ = [
            ("sub_a", ctypes.c_uint16),
            ("sub_b", ctypes.c_uint16),
        ]

    @partial_struct
    class Test(ctypes.Structure):
        _total_size_ = 24
        a: ctypes.c_uint32
        b_sub: "Sub"
        c: Annotated["Sub", 0x8]
        d: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("b_sub", Sub),
        ("c", Sub),
        ("_padding_C", ctypes.c_ubyte * 0x4),
        ("d", ctypes.c_uint32),
        ("_padding_14", ctypes.c_ubyte * 0x4),
    ]

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x00"
    )
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b_sub.sub_a == 2
    assert t.b_sub.sub_b == 0
    assert t.c.sub_a == 3
    assert t.c.sub_b == 0
    assert t.d == 5

    assert bytes(t) == bytes(data)


def test_structure_with_pointer():
    # Test a struct which has a pointer in it.
    # Also implicitly test the case of putting an "invalid" offset.
    # In this case we put the pointer at 0xC, but because we're 64 bit it has to be aligned to 0x8 byte
    # boundary.
    @partial_struct
    class Test(ctypes.Structure):
        a: Annotated[ctypes.c_uint32, 0x0]
        a_bool: Annotated[ctypes.c_bool, 0xA]
        b: Annotated[ctypes._Pointer[ctypes.c_uint32], 0xB]
        c: Annotated[ctypes.c_uint32, 0x18]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_4", ctypes.c_ubyte * 0x6),
        ("a_bool", ctypes.c_bool),
        ("b", ctypes.POINTER(ctypes.c_uint32)),
        ("c", ctypes.c_uint32),
    ]

    assert ctypes.sizeof(Test) == 0x20  # 4 extra bytes at the end since the whole struct will be 0x8 aligned.

    # Check all of our offsets are also correct in the type.
    assert Test.a.offset == 0
    assert Test.a_bool.offset == 0xA
    assert Test.b.offset == 0x10
    assert Test.c.offset == 0x18

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x07\x00\x00\x00\x00\x00\x00\x00"
    )
    t = Test.from_buffer(data)
    assert t.a == 1
    with pytest.raises(ValueError, match="NULL pointer access"):
        t.b.contents
    assert t.c == 7
    assert bytes(t) == bytes(data)


def test_structure_with_annotated_pointer():
    # Test a struct which has an annotated pointer in it.
    class Sub(ctypes.Structure):
        _fields_ = [
            ("sub_a", ctypes.c_uint16),
            ("sub_b", ctypes.c_uint16),
        ]

    @partial_struct
    class Test(ctypes.Structure):
        a: ctypes._Pointer[Sub]
        b: "ctypes._Pointer[Sub]"

    assert Test._fields_ == [("a", ctypes.POINTER(Sub)), ("b", ctypes.POINTER(Sub))]

    assert ctypes.sizeof(Test) == 0x10

    # Check all of our offsets are also correct in the type.
    assert Test.a.offset == 0
    assert Test.b.offset == 0x8

    data = bytearray(b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    t = Test.from_buffer(data)
    with pytest.raises(ValueError, match="NULL pointer access"):
        t.a.contents
    with pytest.raises(ValueError, match="NULL pointer access"):
        t.b.contents
    assert bytes(t) == bytes(data)


def test_annotated_arrays():
    # Test the case of an array of some other type.

    class Sub(ctypes.Structure):
        _fields_ = [
            ("sub_a", ctypes.c_uint16),
            ("sub_b", ctypes.c_uint16),
        ]

    @partial_struct
    class Test(ctypes.Structure):
        _total_size_ = 24
        a: ctypes.c_uint32
        b: "Sub * 2"
        c: Annotated[list[Sub], Field(Sub * 3)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("b", Sub * 2),
        ("c", Sub * 3),
    ]

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00"
    )
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b[0].sub_a == 2
    assert t.b[0].sub_b == 0
    assert t.b[1].sub_a == 3
    assert t.b[1].sub_b == 0
    assert len(t.c) == 3
    assert t.c[0].sub_a == 4
    assert t.c[0].sub_b == 0

    assert bytes(t) == bytes(data)


def test_inheritence():
    # Test the case of a one partial struct inheriting from another.
    @partial_struct
    class Base(ctypes.Structure):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_bool, 0x8]

    @partial_struct
    class Parent(Base):
        c: Annotated[ctypes.c_uint32, 0x10]
        d: ctypes.c_uint32

    @partial_struct
    class GrandParent(Parent):
        e: ctypes.c_bool

    data_base = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00")
    data_parent = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00"
    )
    data_grandparent = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00"
        b"\x01\x00\x00\x00"
    )

    base = Base.from_buffer(data_base)
    assert base.a == 1
    assert base.b is True

    assert Base.a.offset == 0x0
    assert Base.b.offset == 0x8

    assert Parent.a.offset == 0x0
    assert Parent.b.offset == 0x8
    assert Parent.c.offset == 0x10
    assert Parent.d.offset == 0x14

    assert GrandParent.e.offset == 0x18

    parent = Parent.from_buffer(data_parent)
    assert parent.a == 1
    assert parent.b is True
    assert parent.c == 5
    assert parent.d == 6

    grandparent = GrandParent.from_buffer(data_grandparent)
    assert grandparent.a == 1
    assert grandparent.b is True
    assert grandparent.c == 5
    assert grandparent.d == 6
    assert grandparent.e is True


def test_inheritence2():
    # Test the case of a one partial struct inheriting from another. In this case the base class will not be
    # a partial class but a concrete ctypes.Structure.
    class Base(ctypes.Structure):
        _fields_ = [
            ("a", ctypes.c_uint32),
            ("_padding0x4", ctypes.c_ubyte * 0x4),
            ("b", ctypes.c_bool),
        ]
        a: ctypes.c_uint32
        b: ctypes.c_bool

    @partial_struct
    class Parent(Base):
        c: Annotated[ctypes.c_uint32, 0x10]
        d: ctypes.c_uint32

    @partial_struct
    class GrandParent(Parent):
        e: ctypes.c_bool

    data_base = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00")
    data_parent = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00"
    )

    base = Base.from_buffer(data_base)
    assert base.a == 1
    assert base.b is True

    assert Parent.a.offset == 0x0
    assert Parent.b.offset == 0x8
    assert Parent.c.offset == 0x10
    assert Parent.d.offset == 0x14

    parent = Parent.from_buffer(data_parent)
    assert parent.a == 1
    assert parent.b is True
    assert parent.c == 5
    assert parent.d == 6


def test_invalid_cases():
    # Invalid type type
    with pytest.raises(ValueError, match=re.escape("The field 'a' has an invalid type: <class 'int'>")):

        @partial_struct
        class Test1(ctypes.Structure):
            a: int

    with pytest.raises(ValueError, match=re.escape("The field 'a' has an invalid type: <class 'int'>")):

        @partial_struct
        class Test2(ctypes.Structure):
            a: Annotated[int, int]

    # Invalid annotation
    with pytest.raises(
        ValueError,
        match=re.escape(
            "The field 'a' has an invalid annotation: typing.Annotated[int, <class 'str'>, <class 'float'>]"
        ),
    ):

        @partial_struct
        class Test3(ctypes.Structure):
            a: Annotated[int, str, float]

    # Invalid offset
    with pytest.raises(ValueError, match=re.escape("The field 'a' has an invalid offset: 'hi'")):

        @partial_struct
        class Test4(ctypes.Structure):
            a: Annotated[ctypes.c_int32, "hi"]


T = TypeVar("T", bound=Union[ctypes._SimpleCData, ctypes.Structure])


class cTkDynamicArray(ctypes.Structure, Generic[T]):
    _template_type: Type[T]
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("count", ctypes.c_uint32),
    ]

    offset: int
    count: int

    def value(self, source: bytearray) -> ctypes.Array[T]:
        # This is pretty hacky, but it does the job.
        # A more realistic implementation would be reading memory directly so would be implemented as a
        # property.
        if self.offset == 0 or self.count == 0:
            # Empty lists are stored as empty header bytes.
            return (self._template_type * 0)()
        type_ = self._template_type * self.count
        return type_.from_buffer(source, self.offset)

    def __class_getitem__(cls: type["cTkDynamicArray"], key: T):
        _cls: type["cTkDynamicArray"] = types.new_class(f"cTkDynamicArray<{key}>", (cls,))
        _cls._template_type = key
        return _cls


def test_self_referential_struct():
    # Test the case of the struct having a data type which is itself.
    # To do this we'll need to introduce a serializable list.
    @partial_struct
    class SelfRef(ctypes.Structure):
        a: Annotated[ctypes.c_uint32, 0x0]
        children: Annotated["cTkDynamicArray[SelfRef]", 0x4]

    data = bytearray(
        b"\x01\x00\x00\x00"  # 'a' for the parent.
        b"\x0c\x00\x00\x00\x02\x00\x00\x00"  # Child data "header"
        b"\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # Child 1. a = 2
        b"\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # Child 2. a = 3
    )

    obj = SelfRef.from_buffer(data)
    assert obj.a == 1
    assert obj.children.count == 2
    # Get the children
    children = obj.children.value(data)
    assert children[0].a == 2
    assert children[0].children.count == 0
    sub_child = children[0].children.value(data)
    assert sub_child._length_ == 0
    assert sub_child._type_ == SelfRef
    assert children[1].a == 3
    assert children[1].children.count == 0
