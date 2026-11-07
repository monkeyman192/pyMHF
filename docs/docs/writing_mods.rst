Writing Mods
============

pyMHF is designed to make writing mods as simple as possible.

It should be noted however that to write any mods which hook any specific functions which are neither imported or exported functions requires some amount of experience in reverse engineering binaries. This is not within the scope of this documentation and it is assumed that you have some experience in this.

Mod class
---------

The main body of the mod file is the :class:`pymhf.core.mod_loader.Mod` class which can also be directly imported as ``from pymhf import Mod``.

Without any hooks or functions defined, this mod won't do very much, so the first thing to do is determine what the contents of the mod should be.
We can break this up into two categories; hooking functionality and non-hooking functionality.

.. _writing_mods_hooking_functionality:

Hooking Functionality
^^^^^^^^^^^^^^^^^^^^^

Hooking functionality is, as the name suggests, related to any functions which are run as part of a function hook. These functions are technically known as "detours".
pyMHF provides functionality to allow these detours to be run *before* or *after* the original function. Deciding on when the detour should be run will depend on what the detour does.

*Before* detours
""""""""""""""""

A *before* detour is used when you want to have something occur before the original function has been run. This may be to change the value in some internal struct/class so that when the original function runs it is run on some different value, or it may be to pass in different arguments to the original function.

You can indicate to pyMHF that you want to change the arguments the original function is called with by simply returning the new values you want.

.. note::
    The values passed must be a complete set of arguments. So if a function has 3 arguments, but you only want to modify 1 of them, you still need to return all 3 arguments (with the one replaced with the value required) in their original order.

*After* detours
"""""""""""""""

An *after* detour is used when you want to have something occur after the original function has been run. This may be to change the return value of the function, or set the state of an internal struct/class so that some function which was calling the original function has the struct/class in a different state.

Full details on how to provide the information so that pyMHF can find and hook the function can be found :doc:`here </docs/creating_hook_definitions>`.

In short we use the :class:`~pymhf.core.hooking.function_hook` and :class:`~pymhf.core.hooking.static_function_hook` decorators to define functions which themselves can then be used as decorators for the detour in the Mod instance.


Non-hooking functionality
^^^^^^^^^^^^^^^^^^^^^^^^^

Non-hooking functionality relates to GUI widget definitions, as well as defining functions which can be run on a keypress.

GUI widget definitions
""""""""""""""""""""""

When running pyMHF on a 64 bit version of python, pyMHF will auto-generate a GUI which provides multiple functionalities. For a full list of available decorators for widget types see the :doc:`gui documentation <gui/gui>`.

Elements in the gui will be rendered in the order that they are defined within the ``Mod`` class.

.. _key-binding-definitions:

Key-binding definitions
"""""""""""""""""""""""

pyMHF utilises the (unfortunately unmaintained) `keyboard <https://github.com/boppreh/keyboard>`_ library to handle keypresses.

To define a keypress of release action, we have the following two functions; :py:func:`pymhf.core.hooking.on_key_pressed` and :py:func:`pymhf.core.hooking.on_key_release`.

Both of these functions take a single string argument ``event`` which is the keypress to register to the event.

.. note::
    Due to current limitations, complex keybindings cannot be done (ie. ``"Ctrl+K"`` can't be used as an event string, only ``"K"``).


Hook modifiers
^^^^^^^^^^^^^^

There is one final set of decorators which are useful to apply to the various methods defined within a ``Mod`` class and these are ones which will augment or add some functionality to the defined detour.

:py:func:`one_shot(...) <pymhf.core.hooking.one_shot>`
""""""""""""""""""""""""""""""""""""""""""""""""""""""

This decorator will cause the detour to only be called once then disabled.

.. warning::
    For functions that are called potentially multiple times by multiple threads within the running process, the detour may in fact be run more than once. If it is critical that the detour be run exactly once then extra care should be added to the contents of the detour to ensure the business logic is only able to run once.

:py:func:`get_caller(...) <pymhf.core.hooking.get_caller>`
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

When applied to a function this decorator will cause the function hook to determine where it was called from.
To access this information, you can call a function on the detour method itself. This is seen more clearly by example:

.. code-block:: python

    class MyHook(Mod):
        @get_caller
        @pymhf.core.hooking.manual_hook(...)
        def do_something(self, *args):
            logging.info(f"I was called from 0x{self.do_something.caller_address():X}")

This address will be the address relative to the start of the binary the hook is called from.

.. note::
    The address returned will be one expression later than the ``call`` instruction used to call the original function. This is because to get this caller address we are looking for the value of the ``RSP`` register which is where the program will resume operation from after running the function.


Enabling and disabling detours at runtime
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is sometimes convenient to be able to be able to enable or disable a detour at runtime (eg. if you want to toggle some functionality on or off based on some condition).

Similar to how the ``@get_caller`` decorator above works, all detours have the following functions:

``enable()``
""""""""""""

    Enable the detour. Will do nothing if the detour is already enabled.

``disable()``
"""""""""""""

    Disable the detour. Will do nothing if the detour is already disabled.

``is_enabled() -> bool``
""""""""""""""""""""""""

    Return True if the detour is currently enabled. False otherwise.

Consider the following example on how to use them:

.. code-block:: python

    class MyHook(Mod):
        @gui_button("Toggle")
        def toggle_state(self):
            if self.do_something.is_enabled():
                self.do_something.disable()
            else:
                self.do_something.enable()

        @pymhf.core.hooking.manual_hook(...)
        def do_something(self, *args):
            logging.info(f"I was called from 0x{self.do_something.caller_address():X}")

Whenever the ``Toggle`` button in the gui is pressed, the detour will be toggled between the enabled and disabled states.

.. note::
    This will not work for one-shot detours currently, and detours which are disabled by way of the ``@disabled`` decorator will also not be able to be re-enabled this way.

