Partial Structs
===============

Often when reverse engineering a program you may figure out a struct, but not the entire layout of it.
Often this would then require adding many ``unknown`` fields or adding padding bytes manually.

pyMHF aims to simplify this process by providing the ``partial_struct`` class decorator, as well as the ``Field`` type which is used to annotate the type of field.

The ``Field`` class is defined as follows:

.. code-block:: py

    @dataclass
    class Field:
        datatype: ctypes.Structure
        offset: Optional[int] = None

When using this class, the ``datatype`` must be provided, however the ``offset`` doesn't need to be. If it isn't provided then the field will be placed directly after the field before it at a location determined based on the usual alignment and packing rules.
If the ``offset`` is provided, then the number of padding bytes required between this field and the previous one (if there is one) will be determined and inserted automatically.

Usage
-----

Below is an example of a struct which we have mapped out that we know has a 32 bit int at the start, 12 bytes of unknown contents, and then another 32 bit int.

.. code-block:: py

    import ctypes
    from typing import Annotated
    from pymhf.utils.partial_struct import partial_struct, Field
    
    @partial_struct
    class Test(ctypes.Structure):
        a: Annotated[int, Field(ctypes.c_uint32)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

It is also possible to specify the total size of the struct in bytes by assigning the ``_total_size_`` attribute to the class like so:

.. code-block:: py

    import ctypes
    from typing import Annotated
    from pymhf.utils.partial_struct import partial_struct, Field
    
    @partial_struct
    class Test(ctypes.Structure):
        _total_size_ = 0x20
        a: Annotated[int, Field(ctypes.c_uint32)]
        b: Annotated[int, Field(ctypes.c_uint32, 0x10)]

This adds any extra padding bytes to the end of the definition so that if the struct appears in an array for example it will be deserialized correctly.

Advantages
----------

There are 2 main advantages to using partial structs:

1. Type hints - Standard ``ctypes.Structure`` objects do not have type hints, so you often need to add them manually after defining the ``_field_`` attribute, or you don't bother with them. Since the ``partial_struct`` creates the ``_field_`` attribute automatically based on the class annotations, you don't need to worry about defining it manually.
2. Ease of updating - If you are reversing a binary which changes regularly, it can sometimes mean that the structs need regular updates. If these are large you might not always need all the fields, so by using a partial struct, you can save effort by only mapping and updating the fields you care about.
