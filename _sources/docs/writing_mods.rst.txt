Writing Mods
============

pyMHF is designed to make writing mods as simple as possible.

It should be noted however that to write any mods which hook any specific functions which are neither imported or exported functions requires some amount of experience in reverse engineering binaries. This is not within the scope of this documentation and it is assumed that you have some experience in this.

Mod class
---------

The main body of the mod file is the :class:`pymhf.core.mod_loader.Mod` class which can also be directly imported as ``from pymhf import Mod``.

Without any hooks or functions defined, this mod won't do very much, so the first thing to do is determine what the contents of the mod should be.
We can break this up into two categories; hooking functionality and non-hooking functionality.

Hooking Functionality
^^^^^^^^^^^^^^^^^^^^^

Hooking functionality is, as the name suggests, related to any functions which are run as part of a function hook. These functions are technically known as "detours".
pyMHF provides functionality to allow these detours to be run *before* or *after* the original function. Deciding on when the detour should be run will depend on what the detour does.

*Before* detours
""""""""""""""""

A *before* detour is used when you want to have something occur before the original function has been run. This may be to change the value in some internal struct/class so that when the original function runs it is run on some different value, or it may be to pass in different arguments to the original function.

*After* detours
"""""""""""""""

An *after* detour is used when you want to have something occur after the original function has been run. This may be to change the return value of the function, or set the state of an internal struct/class so that some function which was calling the original function has the struct/class in a different state.


There are 3 types of hooks; *imported function* hooks, *exported function* hooks, and *normal function* hooks. Each of these is implemented as a decorator which is to be applied to a method in the `Mod` class which will act as the detour for that function.

*Imported function* hooks
"""""""""""""""""""""""""

Imported function are those which belong in a dll outside of the main process being run, but which are used by it (eg. windows32 dll's to provide functionality to create files, etc).
To hook an imported function use the :py:func:`pymhf.core.hooking.imported` decorator.

*Exported function* hooks
"""""""""""""""""""""""""

Exported functions are those which belong to main running process itself. There are often not too many, but if you are lucky they may be useful.
To hook an exported function use the :py:func:`pymhf.core.hooking.exported` decorator.

.. note::
    It is recommended that the function name is the "mangled" version. Ie. do not "demangle" the function name.

*Normal function* hooks
"""""""""""""""""""""""

Normal functions are just functions which are provided by the binary but not exported. It is these functions that would generally require a bit of reverse engineering experience to determine the function signature of so that they can be hooked correctly.

Depending on whether you are using a :doc:`library <writing_libraries>`, or using a :doc:`single-file mod <single_file_mods>` will often change which decorator you will use for normal function hooks.

If you are utilising an already written library, then the decorator should be exposed by the library and the function name will generally be the same as the name of the function you are hooking. The exact name and implementation will need to be checked based on the documentation provided by the library itself.

If you are writing a single-file mod which doesn't utilise a library, or if you just want to tinker and hook a function manually, the :py:func:`pymhf.core.hooking.manual_hook` decorator can be used.

.. warning::
    It is important that the ``func_def`` argument of the `manual_hook` decorator be correct, as this will be the main cause of crashes caused by hooking. If you find that your application is crashing upon hooking a certain function it's most likely that the arg types or return type of the function is wrong.

.. warning::
    It seems to due to how the :py:class:`ctypes.c_char_p` is implemented, using it as an arg type is not recommended as it can cause issues with the data passed to the argument which can cause program crashes.
    Instead, use either :py:class:`ctypes.c_ulong` or :py:class:`ctypes.c_ulonglong` depending on whether you are hooking a 32 or 63 bit process respectively, then cast the pointer to a string.

.. note::
    Variadic functions are not supported by pyMHF. You may attempt to hook them with some success, but they will generally end up causing the program to crash.


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

.. code-block:: py

    class MyHook(NMSMod):
        @get_caller
        @pymhf.core.hooking.manual_hook(...)
        def do_something(self, *args):
            logging.info(f"I was called from 0x{self.do_something.caller_address():X}")

This address will be the address relative to the start of the binary the hook is called from.

.. note::
    The address returned will be one expression later than the ``call`` instruction used to call the original function. This is because to get this caller address we are looking for the value of the ``RSP`` register which is where the program will resume operation from after running the function.
