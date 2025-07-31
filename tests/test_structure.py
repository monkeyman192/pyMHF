import ctypes
from typing import Annotated

from pymhf.core.hooking import Structure
from pymhf.core.memutils import get_addressof, map_struct
from pymhf.utils.partial_struct import partial_struct


def test_new_empty_struct():
    # Test creating a new empty struct.
    @partial_struct
    class Test(Structure):
        _total_size_ = 0x40
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]
        c: Annotated[ctypes.c_uint32, 0x20]
        d: Annotated[ctypes.c_uint32, 0x30]

    empty_obj = Test.new_empty()

    assert empty_obj.a == 0
    assert empty_obj.b == 0
    assert empty_obj.c == 0
    assert empty_obj.d == 0

    obj_addr = get_addressof(empty_obj)

    # Map the address to another instance of the object, change the values of that one and then check that the
    # values are shared by both instances.

    new_obj = map_struct(obj_addr, Test)
    new_obj.a = 1
    new_obj.b = 2
    new_obj.c = 3
    new_obj.d = 4

    assert empty_obj.a == 1
    assert empty_obj.b == 2
    assert empty_obj.c == 3
    assert empty_obj.d == 4
