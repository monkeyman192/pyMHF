Extension types
===============

pyMHF provides a number of extra types which can be used to either extend the built-in python ctypes library, or interface with c++ code more easily.

.. note::
    These types should be considered experimental unless otherwise specified.


ctypes extensions
-----------------

:py:class:`~pymhf.extensions.ctypes.c_char_p32`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This class is a wrapper around the ``ctypes.c_uint32`` type to emulate the ``ctypes.c_char_p`` type. This is required because using ``ctypes.c_char_p`` as the type of a function argument can cause issues when the hooked function is called.

:py:class:`~pymhf.extensions.ctypes.c_char_p64`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This class is a wrapper around the ``ctypes.c_uint64`` type to emulate the ``ctypes.c_char_p`` type. This is required because using ``ctypes.c_char_p`` as the type of a function argument can cause issues when the hooked function is called.

Both of these above types have the ``__str__`` method defined on them, so the values can be logged directly (see example below).
The ``value`` property of these classes is still the original integer in case that is needed for passing in to other functions.

.. code-block:: python

    import ctypes
    import logging
    from pymhf import Mod
    from pymhf.extensions.ctypes import c_char_p64
    from pymhf.core.hooking import static_function_hook

    @static_function_hook("48 89 5C 24 ? 48 89 7C 24 ? 48 8B 05")
    @staticmethod
    def GetLookup(lpacName: c_char_p64) -> ctypes.c_uint64:
        ...

    class ExampleMod(Mod):
        @GetLookup.before
        def log_lookup(self, lpacName: c_char_p64):
            logger.info(f"Got the lookup {lpacName}")


:py:class:`~pymhf.extensions.ctypes.c_enum16`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This class is a wrapper around the ``ctypes.c_int32`` type, but it's able to be subscripted to provide a concrete type based on the ``IntEnum`` used.


:py:class:`~pymhf.extensions.ctypes.c_enum32`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This class is a wrapper around the ``ctypes.c_int32`` type, but it's able to be subscripted to provide a concrete type based on the ``IntEnum`` used.

For example, consider the following code:

.. code-block:: python

    from pymhf.utils.partial_struct import partial_struct
    from pymhf.extensions.ctypes import c_enum32
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
