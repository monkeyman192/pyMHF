import ctypes
import inspect
from dataclasses import dataclass
from typing import Optional, Type, TypeVar, Union, _AnnotatedAlias, get_args

from typing_extensions import get_type_hints

from pymhf.extensions.ctypes import c_enum32

_T = TypeVar("_T", bound=Type[ctypes.Structure])

CTYPES = Union[
    ctypes._SimpleCData,
    ctypes.Structure,
    ctypes._Pointer,
    ctypes._Pointer_orig,  # The original, un-monkeypatched ctypes._Pointer object
    ctypes.Array,
    ctypes.Union,
    c_enum32,
]


@dataclass
class Field:
    datatype: ctypes.Structure
    offset: Optional[int] = None


def partial_struct(cls: _T) -> _T:
    """Mark the decorated class as a partial struct.
    This will automatically construct the ``_field_`` attribute for this class
    """
    # Always get the calling frame and add the locals so that if we have any annotated fields they won't fail.
    # In the case of a struct which has no annotations this will be ever so slightly slower than if we did a
    # try... except.
    # However in the case of annotated fields, it's much faster, so it's beneficial to always do this.
    calling_frame = None
    if (cframe := inspect.currentframe()) is not None:
        calling_frame = cframe.f_back
    if calling_frame is not None:
        locals().update(calling_frame.f_locals)
    _fields_ = []
    curr_position = 0
    total_size = getattr(cls, "_total_size_", 0)
    # If there are no annotations, it's just an empty ctypes.Structure class.
    if not hasattr(cls, "__annotations__"):
        cls._fields_ = _fields_
        return cls
    # If there are, loop over the annotations and extract the info we need to construct the _fields_.
    for field_name, annotation in get_type_hints(cls, include_extras=True, localns=locals()).items():
        if not isinstance(annotation, _AnnotatedAlias):
            # In this case it's just the type.
            field_type = annotation
            field_offset = None
        else:
            # If the annotation is a Field object, get info from it, otherwise it must be an integer
            # specifying the offset.
            metadata = annotation.__metadata__
            if len(metadata) != 1:
                raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")
            metadata = metadata[0]
            if isinstance(metadata, Field):
                field_type = metadata.datatype
                field_offset = metadata.offset
            else:
                field_type = annotation.__origin__
                field_offset = metadata
        if not issubclass(field_type, get_args(CTYPES)):
            raise ValueError(f"The field {field_name!r} has an invalid type: {field_type}")
        if field_offset is not None and not isinstance(field_offset, int):
            raise ValueError(f"The field {field_name!r} has an invalid offset: {field_offset!r}")
        if field_offset and field_offset > curr_position:
            padding_bytes = field_offset - curr_position
            _fields_.append((f"_padding_{curr_position:X}", ctypes.c_ubyte * padding_bytes))
            curr_position += padding_bytes
        field_alignment = ctypes.alignment(field_type)
        if curr_position % field_alignment != 0:
            # If the field is not aligned to the correct position, then move the current position forward
            # to ensure it's right.
            # Don't bother adding this as padding since it will just add extra unnecessary fields.
            diff = field_alignment - (curr_position % field_alignment)
            curr_position += diff
        _fields_.append((field_name, field_type))
        curr_position += ctypes.sizeof(field_type)
    if total_size and curr_position < total_size:
        padding_bytes = total_size - curr_position
        _fields_.append((f"_padding_{curr_position:X}", ctypes.c_ubyte * padding_bytes))
    cls._fields_ = _fields_
    return cls
