Extension types
===============

pyMHF provides a number of extra types which can be used to either extend the built-in python ctypes library, or interface with c++ code more easily.

.. note::
    These types should be considered experimental unless otherwise specified.


ctypes extensions
-----------------

:py:class:`~pymhf.extensions.ctypes.c_enum32`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This class is a wrapper around the ``ctypes.c_uint32`` type, but it's able to be subscripted to provide a concrete type based on the ``IntEnum`` used.

For example, consider the following code:

.. code-block:: py

    from pymhf.utils.partial_struct import partial_struct
    import ctypes
    from enum import IntEnum
    from typing import Annotated

    class States(IntEnum):
        OFF = 0
        ON = 1
        UNDEFINED = 2

    @partial_struct
    class Test(ctypes.Structure):
        a: Annotated[c_enum32[States], 0x0]
        b: Annotated[ctypes.c_uint32, 0x10]

In the above we have cretated an enum which is mapped to a ``ctypes.c_uint32`` variable. We can assign the value of ``a`` to an enum member after the struct has been instantiated with data, as well as being able to "see" the value of the int as an enum member instead.
