Mod States
==========

"Mod states" are a concept which were created to solve an issue that arises as a result of the mod reloading functionality of pyMHF.

When a mod is reloaded, the entire python file is reloaded from disk, allowing any changes to be applied without the process having to be restarted.
A side effect of this is that the ``Mod`` class instance in the file is recreated and so it will lose the state it had before the reload.

This problem is fixed by the :py:class:`~pymhf.core.mod_loader.ModState` which never gets re-instantiated when the file is re-read.

.. tip::
    It is recommended that the ``ModState`` is a ``dataclass`` as can be seen in the example below. By doing so it will allow the data to be saved and loaded to disk if required.

In the following example consider a function which is called once when the process is starting up (say, to instantiate some object that we are interested in).
We want to store this address as it will not change throughout the lifetime of the program, however if we don't store it in a ``ModState`` then if we reloaded the mod the value would be lost.

By setting the mod up as shown below we can experiment with adding extra hooks, or using the data we got from that initial function hook without having to restart the process every time.

.. code-block:: py
    :caption: mod1.py

    from dataclasses import dataclass
    from pymhf import Mod
    from pymhf.core.mod_loader import ModState
    from pymhf.core.hooking import manual_hook

    @dataclass
    class EventState(ModState):
        address: int = 0

    class EventProvider(Mod):
        state = EventState()

        @manual_hook("load_function")
        def load_function(self, load_address):
            # This function will be called once early on.
            self.state.address = load_address

Saving/Loading
--------------

The ``ModState`` class has some methods defined which allow the state to be written and read to disk which can be used to implement a simple save/load system for a mod.

To save the ``ModState`` instance use :py:meth:`~pymhf.core.mod_loader.ModState.save`, and to load an instance use :py:meth:`~pymhf.core.mod_loader.ModState.load`.

Saving and loading a ``ModState`` instance requires the class to be defined as a dataclass due to how fields are determined internally.

Generally the types of each field of the ``ModState`` should be a type which is `JSON serializable <https://docs.python.org/3/library/json.html#py-to-json-table>`_, however it is possible to use custom objects as field types as long as they define a ``__json__`` method. This method should take no arguments and should return a dictionary whose keys are the names of the fields of the structure, and the values are the JSON serializable values.

For example, we could implement a vector type as such:

.. code-block:: py
    :caption: vector_type.py

    import ctypes
    from dataclasses import dataclass

    from pymhf.core.mod_loader import ModState

    class Vector3f(ctypes.Structure):
    x: float
    y: float
    z: float

    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float),
    ]

    def __json__(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z}

    @dataclass
    class MyState(ModState):
        health: int = 0
        position: Vector3f = Vector3f(0, 0, 0)
