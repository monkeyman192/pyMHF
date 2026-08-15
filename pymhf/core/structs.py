import ctypes
import inspect
from dataclasses import dataclass
from logging import getLogger
from typing import Literal, Optional, Type, TypeVar, Union, _AnnotatedAlias, get_args

from typing_extensions import get_type_hints

from pymhf.core._internal import BASE_ADDRESS, IS_INJECTED
from pymhf.core.memutils import find_pattern_in_binary, map_struct
from pymhf.extensions.ctypes import CTYPES

_C = TypeVar("_C")
_T = TypeVar("_T", bound=Type[ctypes.Structure])

logger = getLogger(__name__)


@dataclass
class Field:
    datatype: CTYPES
    offset: Optional[int] = None


@dataclass
class Pattern:
    pattern: str
    address_offset: int = 3
    address_dtype: Union[
        type[ctypes.c_uint16],  # for 32 bit binaries... Maybe?
        type[ctypes.c_uint32],  # For 64 bit binaries normally.
        type[ctypes.c_uint64],
    ] = ctypes.c_uint32
    address_type: Literal["relative", "absolute"] = "relative"


class ContainerStruct:
    """
    Base class which, when inherited will automatically find any fields which are
    This will also utilise the pattern cache so the lookup within the binary only occurs once per unique
    exe."""

    def __init_subclass__(cls):
        if not IS_INJECTED:
            # If the class is getting initialised but we aren't running within an injected process then we
            # won't actually be able to find any of the fields.
            # Simply return and this will be called again automatically once injected.
            return
        # Loop over the fields defined on the class and determine the offsets from the cache as required.
        for field_name, annotation in get_type_hints(cls, include_extras=True).items():
            if not isinstance(annotation, _AnnotatedAlias):
                # In this case it's just the
                pass
            else:
                # If the annotation is a Field object, get info from it, otherwise it must be an integer
                # specifying the offset.
                metadata = annotation.__metadata__
                if len(metadata) != 1:
                    raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")
                metadata = metadata[0]
                if isinstance(metadata, Pattern):
                    pattern = metadata.pattern
                    address_offset = metadata.address_offset
                    address_dtype = metadata.address_dtype
                    address_type = metadata.address_type

                    # Find the pattern in the binary
                    patt_addr = find_pattern_in_binary(pattern, False)
                    if patt_addr:
                        start_addr = BASE_ADDRESS + patt_addr
                        rel_offset = address_dtype.from_address(start_addr + address_offset)
                        if address_type == "relative":
                            abs_offset = (
                                start_addr + rel_offset.value + address_offset + ctypes.sizeof(address_dtype)
                            )
                        else:
                            abs_offset = rel_offset.value
                        setattr(cls, field_name, map_struct(abs_offset, annotation.__origin__))
                    else:
                        logger.error(f"Unable to find the field {cls}.{field_name} with pattern {pattern!r}")
                else:
                    raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")


def partial_struct(cls: _T) -> _T:
    """Mark the decorated class as a partial struct.
    This will automatically construct the ``_field_`` attribute for this class
    """
    # Always get the calling frame and add the locals so that if we have any annotated fields they won't fail.
    # In the case of a struct which has no annotations this will be ever so slightly slower than if we did a
    # try... except.
    # However in the case of annotated fields, it's much faster, so it's beneficial to always do this.
    calling_frame = None
    _locals = locals()
    if (cframe := inspect.currentframe()) is not None:
        calling_frame = cframe.f_back
    if calling_frame is not None:
        _locals.update(calling_frame.f_locals)

    # Also add the class to the locals so that it can find itself in the case it references itself.
    _locals.update({cls.__name__: cls})

    _fields_ = []
    curr_position = 0
    total_size = getattr(cls, "_total_size_", 0)
    # If there are no annotations, it's just an empty ctypes.Structure class.
    if not hasattr(cls, "__annotations__"):
        cls._fields_ = _fields_
        return cls

    # Do some analysis on the closest base class to find the last non-padding bytes and size.
    subclass_fields = set()
    subclass_size = 0

    for subclass in cls.__mro__[1:]:
        if hasattr(subclass, "_fields_"):
            for field in subclass._fields_:
                subclass_fields.add(field[0])
            if hasattr(subclass, "_total_size_"):
                subclass_size = subclass._total_size_
            else:
                subclass_size = ctypes.sizeof(subclass)

    _in_subclass = True

    for field_name, annotation in get_type_hints(cls, include_extras=True, localns=_locals).items():
        # Ingore any fields which we have picked up from any subclasses.
        if _in_subclass and field_name in subclass_fields:
            continue
        elif _in_subclass:
            # Fields are always in order. Once we have a name which isn't in the subclass then we swap this
            # flag and set our current position to be the size of the subclass.
            _in_subclass = False
            curr_position = subclass_size
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
            # Check to make sure that the `field_type` is not a string(as can happen when we have a
            # self-reference).
            if isinstance(field_type, str):
                field_type = getattr(annotation, "__origin__", None)
                if field_type is None:
                    raise ValueError(
                        f"The provided metadata {metadata} for field {field_name!r} is invalid. "
                        "If the type in the `Field` component of the annotation is a string, please ensure "
                        "the first argument of the Annotation is also the same string so that the type can "
                        "be resolved."
                    )
        if not issubclass(field_type, get_args(CTYPES)):
            raise ValueError(f"The field {field_name!r} has an invalid type: {field_type}")
        if field_offset is not None and not isinstance(field_offset, int):
            raise ValueError(f"The field {field_name!r} has an invalid offset: {field_offset!r}")
        # Correct the field offset by the size of the subclass.
        if field_offset and field_offset > curr_position:
            padding_bytes = field_offset - curr_position
            _fields_.append((f"_padding_0x{curr_position:X}", ctypes.c_ubyte * padding_bytes))
            curr_position += padding_bytes
        field_alignment = ctypes.alignment(field_type)
        if field_alignment and (curr_position % field_alignment != 0):
            # If the field is not aligned to the correct position, then move the current position forward
            # to ensure it's right.
            # Don't bother adding this as padding since it will just add extra unnecessary fields.
            diff = field_alignment - (curr_position % field_alignment)
            curr_position += diff
        _fields_.append((field_name, field_type))
        curr_position += ctypes.sizeof(field_type)
    if total_size and curr_position < total_size:
        padding_bytes = total_size - curr_position
        _fields_.append((f"_padding_0x{curr_position:X}", ctypes.c_ubyte * padding_bytes))
    cls._fields_ = _fields_
    return cls
