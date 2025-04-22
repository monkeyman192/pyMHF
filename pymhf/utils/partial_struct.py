import ctypes
from dataclasses import dataclass
from typing import Annotated, Optional, Type, TypeVar, cast

StructType = TypeVar("StructType", bound=Type[ctypes.Structure])


@dataclass
class Field:
    datatype: ctypes.Structure
    offset: Optional[int] = None


def partial_struct(cls: StructType):
    _fields_ = []
    curr_position = 0
    for field_name, annotation in cls.__annotations__.items():
        if len(annotation.__metadata__) == 1:
            field_data = annotation.__metadata__[0]
        else:
            raise ValueError(f"The field {field_name} has an invalid annotation: {annotation}")
        field_data = cast(Field, field_data)
        field_type = field_data.datatype
        field_offset = field_data.offset
        if field_offset and field_offset > curr_position:
            padding_bytes = field_offset - curr_position
            _fields_.append((f"_padding_{curr_position:X}", ctypes.c_ubyte * padding_bytes))
            curr_position += padding_bytes
        _fields_.append((field_name, field_type))
        curr_position += ctypes.sizeof(field_type)
    cls._fields_ = _fields_
    return cls


if __name__ == "__main__":

    @partial_struct
    class Test(ctypes.Structure):
        a: Annotated[int, Field(ctypes.c_uint32)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

    print(Test._fields_)
    data = bytearray(b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00")
    t = Test.from_buffer(data)
    print(t.a)
    print(t.b)

    print(bytes(t))
