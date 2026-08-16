Container Structs
=================

A "Container Struct" or "Run-time Struct" as we are calling them is essentially just a struct with a number of fields which need to be found at runtime based on a byte pattern.

These are not truly structs in any real sense, however they exist to contain a number of fields (whether they are that way in binary in question or not).

The best way to understand this is with an example:

.. code-block:: python

    from typing import Annotated
    from pymhf.core.structs import CntainerStruct, Pattern

    class GlobalData(ContainerStruct):
        memory_manager: Annotated[MemManager, Pattern("48 8D 0D ? ? ? ? 44 88 35 ? ? ? ? C7 05")]
        ui_manager: Annotated[UIManager, Pattern("48 8D 0D ? ? ? ? E8 ? ? ? ? B2 ? 48 8D 0D")]

In the above example ``MemManager`` and ``UIManager`` would be classes which subclass from :py:class:`~pymhf.core.hooking.Structure` (which itself just subclasses from ``ctypes.Structure``).

The byte pattern for each field generally will have the following structure:

.. code-block::

    48 8D 0D      ? ? ? ?               44 88 35 ? ? ? ? C7 05
    Operator      Relative offset       Extra bytes

As with the byte patterns for functions, this can be found using one of a few plugins for Ghidra or IDA.

If the operator isn't 3 bytes, and the relative offset isn't 4 bytes, these values can be modified as arguments to the ``Pattern`` dataclass, but generally the defaults will suffice.