Inter-mod functionality
=======================

It's all well and good having mods, but sometimes one mod may exist which accesses certain data or exposes certain functions which other mods could benefit from using.
pyMHF provides a convenient way for one mod to access the properties and methods of other loaded mods by exposing the loaded mods such that any other mod can access them.

Usage
-----

To access other mods we use the :py:data:`~pymhf.core.mod_loader.mod_manager`:

.. code-block:: py

    from from pymhf.core.mod_loader import mod_manager


This class is an instance of the :py:class:`~pymhf.core.mod_loader.ModManager` class, and has a special method assigned to it so that the ``mod_manager`` object can be indexed by the ``type`` of the mod you wish to access.
The returned value is the currently valid *instance* of the mod requested.
This is seen more clearly below in the example.

Example
-------

A simple example is given below:

.. code-block:: py
    :caption: mod1.py

    import logging
    from dataclasses import dataclass
    from pymhf import Mod
    from pymhf.core.mod_loader import ModState
    from pymhf.gui.decorators import STRING

    logger = logging.getLogger("EventProvider")

    @dataclass
    class EventState(ModState):
        event_id: int = 0

    class EventProvider(Mod):
        state = EventState()

        @property
        @STRING("Event ID", decimal=True)
        def event_id(self):
            return self.state.event_id

        @event_id.setter
        def event_id(self, value):
            self.state.event_id = int(value)


This mod doesn't really do anything, however it utilises a few useful concepts; :doc:`ModState </docs/mod_states>`'s and :doc:`GUI elements </docs/gui/gui>`.
The above mod won't hook anything, but it will add a numeric field to its mod tab in the GUI where a number can be entered.

We'll have a second mod in the same folder as the above:

.. code-block:: py
    :caption: mod2.py

    import logging
    from typing import TYPE_CHECKING
    from pymhf import Mod
    from pymhf.core.hooking import on_key_pressed
    from pymhf.core.mod_loader import mod_manager

    if TYPE_CHECKING:
        from .mod1 import EventProvider

    logger = logging.getLogger("EventUser")

    class EventUser(Mod):
        __dependencies__ = ["EventProvider"]
        @on_key_pressed("k")
        def press_k(self):
            event_provider = mod_manager[EventProvider]
            logger.info(f"Currently selected event id in other mod: {event_provider.event_id}")


The above mod shows off another useful feature; :ref:`key binding events <key-binding-definitions>`.
As with the previous mod, it won't hook anything or do anything, however, when the ``k`` key is pressed in game, the value of the event id entered into the GUI for the other mod will be logged from ``EventUser``.

Note that the mod has a ``__dependencies__`` attribute. This is required so that pyMHF knows what dependencies to inject into the script. It's also an optimisation so that we don't inject every single mod into every single other mod.
In the future we may raise a warning or error if a mod has a dependency which has not been registered within the current pyMHF run.

Running multiple mods in a single folder
----------------------------------------

Similar to how single-file mods work. pyMHF can be pointed to a folder to run (ie. the path you provide to the ``pymhf run`` command is the folder.)
Currently, for this to work the folder must contain the ``pymhf.toml`` file as if it were a library (see :doc:`/docs/settings` for more details).

Caveats / Things to keep in mind
--------------------------------

- One must always do a lookup on the *type* of the mod being accessed, not an instance of it. We do this because internally, pyMHF manages the state of these mods, and these states and instances may change if some mod is reloaded, so one should always rely on pyMHF to do this lookup and not do it themselves.
- Never cache the result of ``mod_manager[<type>]``. Again, for the same reasons as above. If you cache this result, and then the mod you are accessing is reloaded, you will not have the updated value. The lookup os on a dictionary and will be quick so need to worry about getting the mod whenever necessary.
- Avoiding circular imports. You will notice in the ``mod2.py`` file that we have a pattern to import ``TYPE_CHECKING`` from ``typing``. This may look odd, but it's a convenient "trick" to get around circular imports. Because pyMHF handles all the importing logic of loading these python files, both initially and on reload, it is crucial that if you are importing any other mods it is done within a ``if TYPE_CHECKING`` branch, otherwise a circular import may occur and the mod will not function/may cause a crash. This is all necessary so that referenced mods can be correctly type-hinted.
- If two mods reference each other and call functions within each other a loop may occur where they call each other endlessly. This will obviously cause issues and should be avoided.
- It is possible to run a mod which has a dependency on another mod without it failing immediately, however care must be taken. When running the mod if there are any unsatisfied dependencies then a warning will be raised. Further, if the ``mod_manager[<type>]`` call is made with a ``Mod`` class type which hasn't been loaded by pyMHF, then it will instead return a proxy object which instead logs the function call. If you are relying on a result from the mod then you will need to ensure that the mod is also actually loaded by pyMHF.
