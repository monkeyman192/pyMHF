import ctypes
import re
import types
from enum import IntEnum
from typing import Annotated, Generic, Type, TypeVar, Union

import pytest

import pymhf.core.structs
from pymhf.core.structs import Field, PartialStruct, final_fields, finalize_pending_structs, partial_struct
from pymhf.extensions.ctypes import c_enum32


@pytest.fixture(autouse=True)
def cleanup_pending_structs():
    # Clean up the pending structs so one test case failure won't affect any others.
    yield
    pymhf.core.structs._pending_structs = []


def test_simple_structure():
    class Test(PartialStruct):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
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


def test_simple_structure2():
    # Test the case of a partial struct which has a field which has its own intrinsic alignment which has the
    # wrong offset specified. In this case it should still end up correct.
    class Test(PartialStruct):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_uint64, 0x4]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("b", ctypes.c_uint64),
    ]

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00")
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b == 0x4_00_00_00_03
    assert bytes(t) == bytes(data)

    # Also test modifying a value.
    t.a = 42
    assert bytes(t) == b"\x2a\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00"


def test_simple_structure_with_enum():
    class Alphabet(IntEnum):
        A = 0
        B = 1
        C = 2
        D = 3
        E = 4

    class Test(PartialStruct):
        a: Annotated[c_enum32[Alphabet], 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]

    assert Test._fields_ == [
        ("a", c_enum32[Alphabet]),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
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
    class Test(PartialStruct):
        _total_size_ = 0x18
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
        ("_padding_0x14", ctypes.c_ubyte * 0x4),
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
    class Test(PartialStruct):
        class Sub(ctypes.Structure):
            _fields_ = [
                ("sub_a", ctypes.c_uint16),
                ("sub_b", ctypes.c_uint16),
            ]

        _total_size_ = 24
        a: Annotated[ctypes.c_uint32, 0x0]
        b_sub: Annotated[Sub, 0x4]
        c: Annotated[ctypes.c_uint32, 0x8]
        d: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("b_sub", Test.Sub),
        ("c", ctypes.c_uint32),
        ("_padding_0xC", ctypes.c_ubyte * 0x4),
        ("d", ctypes.c_uint32),
        ("_padding_0x14", ctypes.c_ubyte * 0x4),
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

    class Test(PartialStruct):
        _total_size_ = 24
        a: Annotated[ctypes.c_uint32, 0x0]
        b_sub: Annotated["Sub", 0x4]
        c: Annotated["Sub", 0x8]
        d: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("b_sub", Sub),
        ("c", Sub),
        ("_padding_0xC", ctypes.c_ubyte * 0x4),
        ("d", ctypes.c_uint32),
        ("_padding_0x14", ctypes.c_ubyte * 0x4),
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
    class Test(PartialStruct):
        a: Annotated[ctypes.c_uint32, 0x0]
        a_bool: Annotated[ctypes.c_bool, 0xA]
        b: Annotated[ctypes._Pointer[ctypes.c_uint32], 0xB]
        c: Annotated[ctypes.c_uint32, 0x18]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0x6),
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

    class Test(PartialStruct):
        a: Annotated[ctypes._Pointer[Sub], 0x0]
        b: Annotated["ctypes._Pointer[Sub]", 0x8]

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


def test_structure_with_pointer_after_def():
    # Test a struct which has an annotated pointer in it.
    class Test(PartialStruct):
        a: Annotated["ctypes._Pointer[Sub]", 0x0]

    class Sub(ctypes.Structure):
        _fields_ = [
            ("sub_a", ctypes.c_uint16),
            ("sub_b", ctypes.c_uint16),
        ]

    finalize_pending_structs()

    assert Test._fields_ == [("a", ctypes.POINTER(Sub))]

    assert ctypes.sizeof(Test) == 8

    # Check all of our offsets are also correct in the type.
    assert Test.a.offset == 0

    data = bytearray(b"\x00\x00\x00\x00\x00\x00\x00\x00")
    t = Test.from_buffer(data)
    with pytest.raises(ValueError, match="NULL pointer access"):
        t.a.contents
    assert bytes(t) == bytes(data)


def test_annotated_arrays():
    # Test the case of an array of some other type.

    class Sub(ctypes.Structure):
        _fields_ = [
            ("sub_a", ctypes.c_uint16),
            ("sub_b", ctypes.c_uint16),
        ]

    class Test(PartialStruct):
        _total_size_ = 24
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated["Sub * 2", 0x4]
        c: Annotated[list[Sub], Field(Sub * 3, 0xC)]

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
    class Base(PartialStruct):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_bool, 0x8]

    class Parent(Base):
        c: Annotated[ctypes.c_uint32, 0x10]
        d: Annotated[ctypes.c_uint32, 0x14]

    class GrandParent(Parent):
        e: Annotated[ctypes.c_bool, 0x18]

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
        d: Annotated[ctypes.c_uint32, 0x14]

    class GrandParent(Parent):
        e: Annotated[ctypes.c_bool, 0x18]

    data_base = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00")
    data_parent = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00"
    )
    data_grandparent = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x04\x00"
        b"\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00\x01\x00\x00\x00"
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

    gparent = GrandParent.from_buffer(data_grandparent)
    assert gparent.a == 1
    assert gparent.b is True
    assert gparent.c == 5
    assert gparent.d == 6
    assert gparent.e is True


def test_total_size_inheritence():
    # Test the case of a base and parent class having different _total_size_'s.
    class Base(PartialStruct):
        _total_size_ = 0x10

        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        b: Annotated[bool, Field(ctypes.c_bool, 0x8)]

    class Parent(Base):
        _total_size_ = 0x40
        c: Annotated[ctypes.c_uint32, 0x20]
        d: Annotated[ctypes.c_uint32, 0x24]
        e: Annotated[bool, Field(ctypes.c_bool, 0x30)]

    # Check the sizes and reading for the base class.
    data_too_small = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00")
    with pytest.raises(
        ValueError, match=re.escape("Buffer size too small (12 instead of at least 16 bytes)")
    ):
        Base.from_buffer(data_too_small)

    data_just_right = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00")
    obj = Base.from_buffer(data_just_right)
    assert obj.a == 1
    assert obj.b is True

    # Check sizes and reading parent class.
    data_too_small2 = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00"
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00"
        b"\x01\x00\x00\x00\x02\x00\x00\x00"
    )
    with pytest.raises(
        ValueError, match=re.escape("Buffer size too small (40 instead of at least 64 bytes)")
    ):
        Parent.from_buffer(data_too_small2)

    # Read the entire blob in to make sure it's read in correctly.
    data_correct = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00"
        b"\x02\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00"
        b"\x03\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    p = Parent.from_buffer(data_correct)
    assert ctypes.sizeof(p) == 0x40
    assert p.a == 1
    assert p.b is True
    assert p.c == 3
    assert p.d == 2
    assert p.e is True


def test_invalid_cases():
    # Invalid type
    with pytest.raises(
        ValueError,
        match=re.escape("The field 'a' has an invalid annotation: typing.Annotated[int, <class 'int'>]"),
    ):

        class Test2(PartialStruct):
            a: Annotated[int, int]

    # Invalid annotation
    with pytest.raises(
        ValueError,
        match=re.escape(
            "The field 'a' has an invalid annotation: typing.Annotated[int, <class 'str'>, <class 'float'>]"
        ),
    ):

        class Test3(PartialStruct):
            a: Annotated[int, str, float]

    # Invalid offset
    with pytest.raises(
        ValueError,
        match=re.escape("The field 'a' has an invalid annotation: typing.Annotated[ctypes.c_long, 'hi']"),
    ):

        class Test4(PartialStruct):
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
    class SelfRef(PartialStruct):
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


def test_misordered_fields():
    class Test(PartialStruct):
        b: Annotated[ctypes.c_uint32, 0x10]
        a: Annotated[ctypes.c_uint32, 0x0]

    assert Test._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
    ]

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00")
    t = Test.from_buffer(data)
    assert t.a == 1
    assert t.b == 5
    assert bytes(t) == bytes(data)


def test_added_field_in_subclass():
    # one scenario we'd like to support is having subclasses which add new fields in the middle of fields
    # defined in the parent class.
    class Parent(PartialStruct):
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        c: Annotated[ctypes.c_uint32, 0x10]

    class ImprovedParent(Parent):
        _total_size_ = 0x20
        b: Annotated[ctypes.c_uint32, 0x8]

    assert Parent._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
        ("c", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(Parent) == 0x14

    assert ImprovedParent._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0x4),
        ("b", ctypes.c_uint32),
        ("_padding_0xC", ctypes.c_ubyte * 0x4),
        ("c", ctypes.c_uint32),
        ("_padding_0x14", ctypes.c_ubyte * 0xC),
    ]
    assert ctypes.sizeof(ImprovedParent) == 0x20

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00"
        b"\x05\x00\x00\x00\x06\x00\x00\x00\x07\x00\x00\x00\x08\x00\x00\x00"
    )
    t = ImprovedParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 3
    assert bytes(t) == bytes(data)


def test_added_field_in_subclass2():
    # Test the case of having subclasses which add new fields after the fields defined in the parent class.
    class Parent(PartialStruct):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]

        def callme(self):
            return 2

    class ImprovedParent(Parent):
        c: Annotated[ctypes.c_uint32, 0x18]

    assert Parent._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(Parent) == 0x14

    assert ImprovedParent._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0xC),
        ("b", ctypes.c_uint32),
        ("_padding_0x14", ctypes.c_ubyte * 0x4),
        ("c", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(ImprovedParent) == 0x1C

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00")
    t = Parent.from_buffer(data)
    assert t.a == 1
    assert t.b == 5
    assert bytes(t) == bytes(data)

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00"
        b"\x05\x00\x00\x00\x06\x00\x00\x00\x07\x00\x00\x00"
    )
    t = ImprovedParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 5
    assert t.c == 7
    assert bytes(t) == bytes(data)

    assert t.callme() == 2


def test_overwritten_field_in_subclass():
    # Test the case of a field being overwritten by a subclass.
    class Parent(PartialStruct):
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x8)]

    class ImprovedParent(Parent):
        b: Annotated[int, Field(ctypes.c_uint64, 0x8)]

    assert Parent._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0x4),
        ("b", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(Parent) == 0xC

    assert ImprovedParent._fields_ == [
        ("a", ctypes.c_uint32),
        # Note: Padding is not added because it doesn't need it.
        ("b", ctypes.c_uint64),
    ]
    assert ctypes.sizeof(ImprovedParent) == 0x10

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00")
    t = ImprovedParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 0x4_00_00_00_03
    assert bytes(t) == bytes(data)


def test_finalised_struct():
    @final_fields
    class Parent(PartialStruct):
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x8)]

    assert Parent._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0x4),
        ("b", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(Parent) == 0xC

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00")
    t = Parent.from_buffer(data)
    assert t.a == 1
    assert t.b == 3
    assert bytes(t) == bytes(data)

    # This should not be allowed.
    with pytest.raises(
        TypeError,
        match=re.escape("'BadParent' defines new fields which would be overriding existing fields: {'b'}"),
    ):

        class BadParent(Parent):
            b: Annotated[int, Field(ctypes.c_uint64, 0x8)]

    # We can subclass to add fields at the end like normal struct inheritence.
    # This also checks that if we specify a field type at the wrong alignment it will still get it right.
    class GoodParent(Parent):
        c: Annotated[int, Field(ctypes.c_uint64, 0xC)]

    data = bytearray(
        b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00"
    )
    t = GoodParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 3
    assert t.c == 0x6_00_00_00_05
    assert bytes(t) == bytes(data)

    class MethodParent(Parent):
        def something(self):
            return self.a

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00")
    t = MethodParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 3
    assert bytes(t) == bytes(data)
    assert t.something() == 1


def test_middle_finalised_struct():
    # Test a inheritence chain where the bottom class is not finalised, but the middle one is.
    class Child(PartialStruct):
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        c: Annotated[int, Field(ctypes.c_uint32, 0x8)]

    class Alphabet(IntEnum):
        A = 0
        B = 1
        C = 2
        D = 3
        E = 4

    @final_fields
    class Parent(Child):
        b: Annotated[int, Field(ctypes.c_uint32, 0x4)]
        # A type checker will complain about this, but we don't care because we are "correcting" it here.
        c: Annotated[c_enum32[Alphabet], 0x8]

    class GrandParent(Parent):
        d: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    # Test the Child data.
    assert Child._fields_ == [
        ("a", ctypes.c_uint32),
        ("_padding_0x4", ctypes.c_ubyte * 0x4),
        ("c", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(Child) == 0xC

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00")
    t = Child.from_buffer(data)
    assert t.a == 1
    assert t.c == 3
    assert bytes(t) == bytes(data)

    # Test the Parent data
    assert Parent._fields_ == [
        ("a", ctypes.c_uint32),
        ("b", ctypes.c_uint32),
        ("c", c_enum32[Alphabet]),
    ]
    assert ctypes.sizeof(Parent) == 0xC

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00")
    t = Parent.from_buffer(data)
    assert t.a == 1
    assert t.b == 2
    assert t.c == Alphabet.D
    assert bytes(t) == bytes(data)

    # Test the GrandParent data.
    # Can't check the `_fields_` attribute because it won't be a combination as per usual ctypes.Structure
    # inheritence.
    assert ctypes.sizeof(GrandParent) == 0x14

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00")
    t = GrandParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 2
    assert t.c == 3
    assert t.d == 5
    assert bytes(t) == bytes(data)


def test_override_name_in_subclass():
    # Test the case of a subclass defining a function at the same offset as a base class will retain the name
    # of the subclass, not the base class.
    class Parent(PartialStruct):
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        unknown: Annotated[ctypes.c_uint32, 0x4]

    class ImprovedParent(Parent):
        b: Annotated[ctypes.c_uint32, 0x4]
        c: Annotated[ctypes.c_uint32, 0x8]

    assert Parent._fields_ == [
        ("a", ctypes.c_uint32),
        ("unknown", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(Parent) == 0x8

    assert ImprovedParent._fields_ == [
        ("a", ctypes.c_uint32),
        ("b", ctypes.c_uint32),
        ("c", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(ImprovedParent) == 0xC

    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00")
    t = ImprovedParent.from_buffer(data)
    assert t.a == 1
    assert t.b == 2
    assert t.c == 3
    assert bytes(t) == bytes(data)
