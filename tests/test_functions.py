import ctypes
import re

import pytest
from typing_extensions import Self

from pymhf.core.functions import ArgData, FuncDef, _get_funcdef


def test_funcdef_flatten():
    """Test flattening arguments."""
    fd = FuncDef(
        ctypes.c_uint32,
        [ArgData("a", ctypes.c_uint32), ArgData("b", ctypes.c_uint64), ArgData("c", ctypes.c_float)],
    )
    assert fd.restype == ctypes.c_uint32
    assert fd.arg_names == ["a", "b", "c"]
    assert fd.arg_types == [ctypes.c_uint32, ctypes.c_uint64, ctypes.c_float]
    with pytest.raises(ValueError, match=re.escape("Missing argument(s): ['b', 'c']")):
        fd.flatten(1)
    with pytest.raises(ValueError, match=re.escape("Missing argument(s): ['c']")):
        fd.flatten(1, b=2)
    with pytest.raises(ValueError, match=re.escape("Missing argument(s): ['b']")):
        fd.flatten(1, c=2)
    assert fd.flatten(1, 2, 3) == [1, 2, 3]
    assert fd.flatten(a=1, b=3, c=5) == [1, 3, 5]


def test_funcdef_flatten_with_defaults():
    """Test flattening arguments when the FuncDef has default values."""
    fd = FuncDef(
        ctypes.c_uint32,
        [ArgData("a", ctypes.c_uint32), ArgData("b", ctypes.c_uint64), ArgData("c", ctypes.c_float)],
        {"b": 5, "c": 3.5},
    )
    assert fd.restype == ctypes.c_uint32
    assert fd.arg_names == ["a", "b", "c"]
    assert fd.arg_types == [ctypes.c_uint32, ctypes.c_uint64, ctypes.c_float]
    assert fd.flatten(1) == [1, 5, 3.5]
    assert fd.flatten(1, b=2) == [1, 2, 3.5]
    assert fd.flatten(1, c=2) == [1, 5, 2]
    assert fd.flatten(a=1, b=3, c=7) == [1, 3, 7]

    fd = FuncDef(
        ctypes.c_uint32,
        [ArgData("a", ctypes.c_uint32), ArgData("b", ctypes.c_uint64), ArgData("c", ctypes.c_float)],
        {"a": 99, "b": 5, "c": 3.5},
    )
    assert fd.flatten() == [99, 5, 3.5]


def test_get_funcdef_function():
    """Test getting the FuncDef for functions."""

    # Function with normal args and a None return.
    def func(x: ctypes.c_uint32, y: ctypes.c_uint64 = 1234) -> None:
        pass

    fd = _get_funcdef(func)
    assert fd.restype is None
    assert fd.arg_names == ["x", "y"]
    assert fd.arg_types == [ctypes.c_uint32, ctypes.c_uint64]
    assert fd.defaults == {"y": 1234}

    # Function with no args.
    def func2() -> ctypes.c_uint32:
        pass

    fd = _get_funcdef(func2)
    assert fd.restype == ctypes.c_uint32
    assert fd.arg_names == []
    assert fd.arg_types == []
    assert fd.defaults == {}

    class ID(ctypes.Structure):
        _fields_ = []

    # Function with an argument which is a pointer.
    def func3(id_: ctypes._Pointer[ID]) -> ctypes.c_bool:
        pass

    fd = _get_funcdef(func3)
    assert fd.restype == ctypes.c_bool
    assert fd.arg_names == ["id_"]
    assert fd.arg_types == [ctypes.POINTER(ID)]
    assert fd.defaults == {}

    # Function with mixed stringified and non-stringified args.
    # (emulates `from __future__ import annotations`)
    def func4(a: "ctypes.c_int32" = 42, b: ctypes.c_uint16 = 4):
        pass

    fd = _get_funcdef(func4)
    assert fd.restype is None
    assert fd.arg_names == ["a", "b"]
    assert fd.arg_types == [ctypes.c_int32, ctypes.c_uint16]
    assert fd.defaults == {"a": 42, "b": 4}

    # Function with an invalid argument types.
    def func5(a: int):
        pass

    with pytest.raises(TypeError, match=re.escape("Invalid type <class 'int'> for argument 'a'")):
        _get_funcdef(func5)

    def func6(a, b: ctypes.c_int64):
        pass

    with pytest.raises(
        TypeError,
        match=re.escape("The argument(s) ['a'] for 'func6' do not have type hints provided."),
    ):
        _get_funcdef(func6)

    def func7() -> int:
        pass

    with pytest.raises(
        TypeError,
        match="Return type must be a subclass of a ctypes.Structure or a simple ctypes type",
    ):
        _get_funcdef(func7)


def test_get_funcdef_method():
    """Test getting the FuncDef for methods."""

    class MyClass:
        def thing(self):
            # Very boring method with no args or return value.
            pass

        def thing2(self, x: ctypes.c_uint32, y: ctypes.c_uint16 = 7) -> ctypes.c_uint32:
            # Fairly boring method with some args and a default value.
            pass

        @staticmethod
        def thing3(x: ctypes.c_float = 999):
            # Static method.
            pass

        def thing4(self: Self, x: "ctypes.c_uint32"):
            # Valid "stringified" type.
            pass

        def thing5(self, x: "int"):
            # Invalid "stringified" type.
            pass

        def thing6(self, x: ctypes.c_uint32, y=7, z=None) -> ctypes.c_uint32:
            # Argument missing type hint.
            pass

        def thing7(self) -> "int":
            # Invalid "stringified" return type.
            pass

    fd = _get_funcdef(MyClass.thing)
    assert fd.restype is None
    assert fd.arg_names == []
    assert fd.arg_types == []
    assert fd.defaults == {}

    fd = _get_funcdef(MyClass.thing2)
    assert fd.restype == ctypes.c_uint32
    assert fd.arg_names == ["x", "y"]
    assert fd.arg_types == [ctypes.c_uint32, ctypes.c_uint16]
    assert fd.defaults == {"y": 7}

    fd = _get_funcdef(MyClass.thing3)
    assert fd.restype is None
    assert fd.arg_names == ["x"]
    assert fd.arg_types == [ctypes.c_float]
    assert fd.defaults == {"x": 999}

    fd = _get_funcdef(MyClass.thing4)
    assert fd.restype is None
    assert fd.arg_names == ["x"]
    assert fd.arg_types == [ctypes.c_uint32]
    assert fd.defaults == {}

    with pytest.raises(TypeError, match=re.escape("Invalid type <class 'int'> for argument 'x'")):
        fd = _get_funcdef(MyClass.thing5)

    with pytest.raises(
        TypeError,
        match=re.escape("The argument(s) ['y', 'z'] for 'thing6' do not have type hints provided."),
    ):
        fd = _get_funcdef(MyClass.thing6)

    with pytest.raises(
        TypeError,
        match="Return type must be a subclass of a ctypes.Structure or a simple ctypes type",
    ):
        fd = _get_funcdef(MyClass.thing7)
