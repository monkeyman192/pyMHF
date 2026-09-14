Partial Structs
===============

Often when reverse engineering a program you may figure out a struct, but not the entire layout of it.
Often this would then require adding many ``unknown`` fields or adding padding bytes manually.

pyMHF aims to simplify this process by providing the :py:class:`~pymhf.core.structs.PartialStruct` class, as well as the :py:class:`~pymhf.core.structs.Field` type which is used to annotate the type of field.

The ``Field`` class is defined as follows:

.. code-block:: python

    @dataclass
    class Field:
        datatype: CTYPES
        offset: int

Where ``CTYPES`` is a union of the following types:

.. code-block:: python

    CTYPES = Union[
        ctypes._SimpleCData,
        ctypes.Structure,
        ctypes._Pointer,
        ctypes._Pointer_orig,
        ctypes.Array,
        ctypes.Union,
        c_enum8,
        c_enum16,
        c_enum32,
    ]

When using the ``Field`` class, the ``datatype`` and ``offset`` values must both be provided.
This ``offset`` value is relative to the start of any bases classes which may be inherited from (so an absolute position within the struct when considering inheritence).

Usage
-----

Below is an example of a struct which we have mapped out that we know has a 32 bit int at the start, 12 bytes of unknown contents, and then another 32 bit int.

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import Field, PartialStruct

    class Test(PartialStruct):
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

It is also possible to specify the total size of the struct in bytes by assigning the ``_total_size_`` attribute to the class like so:

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import Field, PartialStruct

    class Test(PartialStruct):
        _total_size_ = 0x20
        a: Annotated[int, Field(ctypes.c_uint32, 0x0)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

This adds extra padding bytes to the end of the definition so that if the struct appears in an array for example it will be deserialized correctly.

Inheritence
===========

It is possible to have a partial struct as the base class of another like so:

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import PartialStruct

    class Base(PartialStruct):
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_bool, 0x8]

    class Parent(Base):
        c: Annotated[ctypes.c_uint32, 0x10]
        d: Annotated[ctypes.c_uint32, 0x14]

In this case, if we look at the ``_fields_`` attribute of the ``Parent`` class it will be generated like so:

.. code-block:: python

    _fields_ = [
        ("a", ctypes.c_uint32),  # Offset = 0x0
        ("_padding_0x4", ctypes.c_ubyte * 4),
        ("b", ctypes.c_bool),    # Offset = 0x8
        ("_padding_0x9", ctypes.c_ubyte * 7),
        ("c", ctypes.c_uint32),    # Offset = 0x10
        ("d", ctypes.c_uint32),    # Offset = 0x14
    ]

From this we can see that (as with c++), the base class will have its fields serialized before the parent class.

.. note::
    The offsets for parent classes MUST be relative to the start of the entire struct, NOT from the start of the definition after the base class(es).
    This can be clearly seen in the above example.

In the above example, if we knew the size of the child class, we could also type it as follows and get the same result.

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import PartialStruct

    class Base(PartialStruct):
        _total_size_ = 0x10
        a: Annotated[ctypes.c_uint32, 0x0]
        b: Annotated[ctypes.c_bool, 0x8]

    class Parent(Base):
        c: Annotated[ctypes.c_uint32, 0x10]
        d: Annotated[ctypes.c_uint32, 0x14]


Composition
===========

As well as behaving like ``ctypes.Structure`` objects in terms of allowing extra fields to be appended using class inheritence, ``PartialStruct`` classes also allow for fields to be overwritten, or to be added in the middle of a gap.

Consider the following scenario:
A tool using pyMHF has partially mapped out some struct for use:

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import Field, PartialStruct

    class CameraSettings(PartialStruct):
        _total_size_ = 0x100
        FOV: Annotated[float, Field(ctypes.c_float, 0x0)]
        DOF: Annotated[float, Field(ctypes.c_float, 0x50)]


A modder is doing their own reverse engineering work and discovers a few more fields that they want to use which lie between the ``FOV`` and ``DOF`` values.
They can subclass the above class in their own mod (meaning they get the benefits of reloadability) for testing ans personal usage like so:

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import Field
    import game_library.types as game_types

    class CameraSettings(game_types.CameraSettings):
        offset_x: Annotated[float, Field(ctypes.c_float, 0x20)]
        offset_y: Annotated[float, Field(ctypes.c_float, 0x24)]
        offset_z: Annotated[float, Field(ctypes.c_float, 0x28)]


In this case the resulting object will now have both base fields (``FOV`` and ``DOF``), as well as the 3 newly added ones, all in the correct offsets.

This functionality allows mod authors to much more easily extend these partial classes provided by library authors.

On the other hand, the authors of a library may know that they have completely mapped out a struct in its' entirity and that no more fields need to be added to it anywhere.
In this case, they can mark the class with the :py:func:`~pymhf.core.structs.final_fields` decorator which indicates that the fields cannot be overwritten.
You can think of this decorator as converting the behaviour of the class from the composable class we have above, to the usual ``ctypes.Structure`` behaviour where only new fields can be added to the end (since a base class may have been fully mapped out, but not an inheriting class.)

Finally, modders can also override the names of fields in subclasses in case they are making local improvements.

This would look something like the following for example:

In the library there would be the following definition:

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import Field, PartialStruct

    class CameraSettings(PartialStruct):
        _total_size_ = 0x100
        FOV: Annotated[float, Field(ctypes.c_float, 0x0)]
        unknown0x10: Annotated[float, Field(ctypes.c_float, 0x10)]
        DOF: Annotated[float, Field(ctypes.c_float, 0x50)]

And in the mod file there would be:

.. code-block:: python

    import ctypes
    from typing import Annotated
    from pymhf.core.structs import Field
    import game_library.types as game_types

    class CameraSettings(game_types.CameraSettings):
        movement_speed: Annotated[float, Field(ctypes.c_float, 0x10)]

In this case ``unknown0x10`` would no longer be an attribute of ``CameraSettings`` (in the mod file), but would instead be ``movement_speed``.

Advantages
==========

There are a few main advantages to using partial structs:

1. Type hints - Standard ``ctypes.Structure`` objects do not have type hints, so you often need to add them manually after defining the ``_field_`` attribute, or you don't bother with them. Since the ``partial_struct`` creates the ``_field_`` attribute automatically based on the class annotations, you don't need to worry about defining it manually.
2. Ease of updating - If you are reversing a binary which changes regularly, it can sometimes mean that the structs need regular updates. If these are large you might not always need all the fields, so by using a partial struct, you can save effort by only mapping and updating the fields you care about.
3. Easy extendability - Modders can easily fill in the gaps in structs which may only be partially defined by the library authors. This also allows for easy testing since these definitions can be reloaded with the mod. These extra fields can then potentially make their way back into the library if mod authors choose to make a PR with these improvements.
