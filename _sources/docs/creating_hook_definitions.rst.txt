Creating hook definitions
=========================

Whether you are writing a library, or writing a single-file mod, pyMHF provides a convenient way of declaring the information required to hook or call any given function relating to a binary, whether it be imported, exported or a function defined within the binary.

This functionality is provided by the :class:`~pymhf.core.hooking.function_hook` and :class:`~pymhf.core.hooking.static_function_hook` functions, to decorate non-static and static methods/functions respectively.

These decorators do a few things when applied:

1. The decorated function/method is inspected and the argument names and type hints are collected and used to construct a ``FuncDef`` object which is used by pyMHF to tell minhook how to hook the required function.
2. It also enables calling the function or method directly (more on that below).
3. Finally, the decorators transform the function or method into a decorator which can be applied to the method in our mod which we wish to use as a detour.

Because of this first point, the decorated function MUST have correct type hints. If they are not correct, then the hook will likely fail, produce incorrect results, or even cause the program to crash.

The best way to see how these decorators are used is with a few code examples.

*Imported function* hooks
-------------------------

.. code-block:: py
    :caption: imported_hook_mod.py
    :linenos:

    import ctypes.wintypes as wintypes
    from logging import getLogger

    from pymhf import Mod
    from pymhf.core.hooking import static_function_hook

    logger = getLogger()


    @static_function_hook(imported_name="Kernel32.ReadFile")
    def ReadFile(
        hFile: wintypes.HANDLE,
        lpBuffer: wintypes.LPVOID,
        nNumberOfBytesToRead: wintypes.DWORD,
        lpNumberOfBytesRead: wintypes.LPDWORD,
        lpOverlapped: wintypes.LPVOID,
    ) -> wintypes.BOOL:
        pass


    class ReadFileMod(Mod):
        @ReadFile.after
        def after_read_file(self, *args):
            logger.info(f"after readfile: {args}")

Here we can see that we have defined a function ``ReadFile`` which has the same definition as the function with the same name in the ``Kernel32`` windows system dll.

As seen here, the ``static_function_hook`` decorator transforms the ``ReadFile`` itself into a decorator which we then used to specify that the ``after_read_file`` method is to be used as the detour run after the ``Kernel32.ReadFile`` function.

*Exported function* hooks
-------------------------

Exported functions are those which are provided by the binary itself. There are often not many, and often less which may be useful, but if you get lucky there may be some where are useful to hook or even call.

.. _exported_hook_mod_code:

.. code-block:: py
    :caption: exported_hook_mod.py
    :linenos:

    import ctypes
    import logging

    from pymhf import Mod
    from pymhf.core.hooking import static_function_hook
    from pymhf.core.utils import set_main_window_active
    from pymhf.gui.decorators import gui_button

    logger = logging.getLogger()

    FUNC_NAME = "?PostEvent@SoundEngine@AK@@YAII_KIP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXIPEAUAkExternalSourceInfo@@I@Z"


    class AK():
        class SoundEngine():
        @static_function_hook(exported_name=FUNC_NAME)
        def PostEvent(
            in_ulEventID: ctypes.c_uint32,
            in_GameObjID: ctypes.c_uint64,
            in_uiFlags: ctypes.c_uint32 = 0,
            callback: ctypes.c_uint64 = 0,
            in_pCookie: ctypes.c_void_p = 0,
            in_cExternals: ctypes.c_uint32 = 0,
            in_pExternalSources: ctypes.c_uint64 = 0,
            in_PlayingID: ctypes.c_uint32 = 0,
        ) -> ctypes.c_uint64:
            pass


    class AudioNames(Mod):
        def __init__(self):
            super().__init__()
            self.event_id = None
            self.obj_id = None

        @gui_button("Play sound")
        def play_sound(self):
            if self.event_id and self.obj_id:
                set_main_window_active()
                AK.SoundEngine.PostEvent(self.event_id, self.obj_id, 0, 0, 0, 0, 0, 0)

        @AK.SoundEngine.PostEvent.after
        def play_event(self, *args):
            self.event_id = args[0]
            self.obj_id = args[1]
            logger.info(f"{args}")

In the above example, we are hooking the ``AK::SoundEngine::PostEvent`` function which the No Man's Sky binary includes as an export (as many games which use the AudioKinetic library likely also do).
The mod will also provide a button which, when pressed will play the last played audio by the game.

There are a few thihngs to note in this example:

- The ``exported_name`` argument to ``static_function_hook`` is the "mangled" name. This is the recommended way to provide this and it should be used over the "unmangled" version since it means there is no ambiguity or confusion when doing a lookup by name in the exe.
- The ``static_function_hook`` decorator is applied to a method of the nested classes. For static methods this isn't really required, however it is nice since it adds some structure to these function calls (this point is NOT true for non-static methods as you will see in the next section!).
- We can call the static method by caling the method directly despite there being no function body. The actual implementation of the calling is done by pyMHF itself so you don't need to worry about it.

*Normal function* hooks
-----------------------

Normal functions are just functions which are provided by the binary but not exported. It is these functions that would generally require a bit of reverse engineering experience to determine the function signature of so that they can be hooked correctly.

Defining functions to hook is done in much the same way as above, however, we simply provide either the relative offset within the binary, or a byte pattern known as a *signature* which can be used to uniquely find the start of the function within the binary.

.. hint::
    When to use ``signature`` or ``offset``?

    If your binary never changes (ie. is never updated by the developers etc), then use ``offset`` as it's trivial to obtain for every single function in a binary.
    If the binary receives updates, then the ``signature`` is the only option as ``offset`` values will change as the binary does.


.. code-block:: py
    :caption: normal_hook_mod.py
    :linenos:

    import ctypes
    import logging
    from typing import Annotated, Optional

    from pymhf import Mod
    from pymhf.core.hooking import Structure, function_hook
    from pymhf.core.utils import set_main_window_active
    from pymhf.gui.decorators import gui_button
    from pymhf.utils.partial_struct import Field, partial_struct

    logger = logging.getLogger()


    @partial_struct
    class TkAudioID(ctypes.Structure):
        mpacName: Annotated[Optional[str], Field(ctypes.c_char_p)]
        muID: Annotated[int, Field(ctypes.c_uint32)]
        mbValid: Annotated[bool, Field(ctypes.c_bool)]


    class cTkAudioManager(Structure):
        @function_hook("48 83 EC ? 33 C9 4C 8B D2 89 4C 24 ? 49 8B C0 48 89 4C 24 ? 45 33 C9")
        def Play(
            self,
            this: "ctypes._Pointer[cTkAudioManager]",
            event: ctypes._Pointer[TkAudioID],
            object: ctypes.c_int64,
        ) -> ctypes.c_bool:
            pass


    class AudioNames(Mod):
        def __init__(self):
            super().__init__()
            self.event_id = 0
            self.obj_id = 0
            self.audio_manager = None
            self.count = 0

        @gui_button("Play sound")
        def play_sound(self):
            if self.event_id and self.obj_id and self.audio_manager:
                set_main_window_active()
                audioid = TkAudioID()
                audioid.muID = self.event_id
                self.audio_manager.Play(event=ctypes.addressof(audioid), object=self.obj_id)

        @cTkAudioManager.Play.after
        def after_play(
            self,
            this: ctypes._Pointer[cTkAudioManager],
            event: ctypes._Pointer[TkAudioID],
            object_,
        ):
            audioID = event.contents
            logger.info(f"After play; this: {this}, {audioID.muID}, object: {object_}")
            self.audio_manager = this.contents
            self.event_id = audioID.muID
            self.obj_id = object_

In the above we have defined the ``cTkAudioManager`` class with the ``Play`` method.
This method uses the ``function_hook`` decorator, not the ``static_function_hook`` decorator for the simple fact that this is not a static method. This means that if you want to call the method you need to call it on the *instance* of the class, not the class type (see line 47).

One implication of the above is that the first argument of the method decorated with the ``function_hook`` decorator should always be ``this`` (generally typed as ``ctypes._Pointer[<class type>]``. For more details see :ref:`here <hint_specify_this_type>`). On the other hand, any function decorated with ``static_function_hook`` will not have ``this`` as an argument.

.. important::
    The ``function_hook`` decorator MUST be applied to methods of a :class:`~pymhf.core.hooking.Structure`. This class is a thin wrapper around the ``ctypes.Structure`` class, but we require this for the calling functionality to work correctly (check out the source code if you are curious why!)
    The ``static_function_hook`` doesn't have this restriction (but it is permissible)

    Because of this, you cannot use the ``function_hook`` decorator on a plain function, it MUST be used on a method!

We can see that when we call the function we can either use positional arguments or keyword arguments. This function can be called the exact same way any function would be called, and we can in fact define default values for some arguments so that we don't need to specify the arguments when calling (see for example :ref:`exported_hook_mod_code` lines 20-25).

.. note::
    When calling functions we DO NOT provide the ``this`` argument to non-static functions. Your IDE will only show the arguments after that argument, and the value is automatically added by pyMHF internally.

.. note::
    Often one of the trickiest things when writing a mod is getting a pointer to the instance of the class that you are interested in. You generally will get this from the first argument of some function that you hook (as it is the ``this`` argument), but sometimes other structs may contain this pointer. It is really up the binary in question.


Overloads
---------

It is possible to define function overloads however there are two methods, each with their own pro's and con's.

Using the ``overload`` method and ``overload_id`` argument
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``static_function_hook`` and ``function_hook`` decorators both have an ``overload_id`` argument which is used to uniquely identify the overload (this will be required later when we want to call or hook this function).
The methods also need the ``typing.overload`` decorator. Note that pyMHF actually monkeypatches this decorator so that it doesn't remove information from the original function that we need.

To hook or call a function with an overload, append ``.overload(overload_id: str)`` to the original function. This will refer to the overloaded function.

.. code-block:: py
    :caption: overloaded_mod.py
    :linenos:

    import ctypes
    import logging
    from typing import Annotated, Optional, overload

    import pymhf.core._internal as _internal
    from pymhf import Mod
    from pymhf.core.hooking import Structure, function_hook
    from pymhf.core.utils import set_main_window_active
    from pymhf.gui.decorators import gui_button
    from pymhf.utils.partial_struct import Field, partial_struct

    logger = logging.getLogger()


    @partial_struct
    class TkAudioID(ctypes.Structure):
        mpacName: Annotated[Optional[str], Field(ctypes.c_char_p)]
        muID: Annotated[int, Field(ctypes.c_uint32)]
        mbValid: Annotated[bool, Field(ctypes.c_bool)]


    @partial_struct
    class cTkAudioManager(Structure):
        @function_hook("48 89 5C 24 ? 48 89 6C 24 ? 56 48 83 EC ? 48 8B F1 48 8B C2", overload_id="attenuated")
        @overload
        def Play(
            self,
            this: "ctypes._Pointer[cTkAudioManager]",
            event: ctypes._Pointer[TkAudioID],
            position: ctypes.c_uint64,
            object: ctypes.c_int64,
            attenuationScale: ctypes.c_float,
        ) -> ctypes.c_bool:
            pass

        @function_hook("48 83 EC ? 33 C9 4C 8B D2 89 4C 24 ? 49 8B C0 48 89 4C 24 ? 45 33 C9", overload_id="normal")
        @overload
        def Play(
            self,
            this: "ctypes._Pointer[cTkAudioManager]",
            event: ctypes._Pointer[TkAudioID],
            object: ctypes.c_int64,
        ) -> ctypes.c_bool:
            pass


    class AudioNames(Mod):
        def __init__(self):
            super().__init__()
            self.audio_manager = None
            self.event_id = None
            self.obj_id = None

        @gui_button("Play sound")
        def play_sound(self):
            if self.event_id and self.obj_id and self.audio_manager:
                set_main_window_active()
                audioid = TkAudioID()
                audioid.muID = self.event_id
                self.audio_manager.Play.overload("normal")(event=ctypes.addressof(audioid), object=self.obj_id)

        @cTkAudioManager.Play.overload("normal").after
        def after_play(
            self,
            this: ctypes._Pointer[cTkAudioManager],
            event: ctypes._Pointer[TkAudioID],
            object_,
        ):
            audioID = event.contents
            logger.info(f"After play; this: {this}, {audioID.muID}, object: {object_}")
            self.audio_manager = this.contents
            self.event_id = audioID.muID
            self.obj_id = object_

        @cTkAudioManager.Play.overload("attenuated").after
        def after_play_attenuated(self, *args):
            logger.info(f"Just played an attenuated sound: {args}")


Pros:
 - It provides a nice clean way to reference the overloaded functions.

Cons:
 - Type hinting is lost when doing function calls.

Name overloaded functions differently
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The other option for overloaded functions is to simply give them different names. So for example if you had two functions ``play_song(id: int, volume: float)`` and ``play_song(id: int, volume: float, position: vector3)``, you might call one ``play_song``, and then call the other ``play_song_at_pos``.

Pro's:
 - No need to use the ``.overload`` method or ``overload_id``.
 - Function calls are type hinted.

Con's:
 - Doesn't stay accurate to actual function names (if known).


Tips and hints
--------------

The above can see a bit daunting at first, but once you get a handle on it it can be very easy to create new functions, and this can even potentially be automated to some degree with scripts for IDA or ghidra.

There are a few useful things to consider or keep in mind however:

.. _hint_specify_this_type:

How to specify the type for ``this``?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is recommended for extra ease of use that the ``this`` parameter be typed as ``"ctypes._Pointer[<class type>]"``. This has the benefit that it's easier to see the type of the parameter without having to know what type to map it to, and it also simplifies the code required to get the actual object (``obj = this.contents`` compared to ``obj = map_struct(this, <type>)``).
Typing ``this`` as an integer should be considered "bad-practice" however it is supported as it can be useful in some cases.

If you specify the type as a pointer, the :func:`~pymhf.core.memutils.get_addressof` can be used to get the address pointed to: ``addr = get_addressof(this)``.

.. note::
    You will notice that the type of ``this`` is a string. This is not a mistake! At runtime python doesn't have access the type of the class the method is defined in (in a type-checking sense at least). To get around this issue the type is "annotated", ie. written as a string (cf. `PEP 484 <https://peps.python.org/pep-0484/#forward-references>`_).

When to use ``static_function_hook`` or ``function_hook``?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Often when you start to reverse engineer a program, you will not know whether or not some function is just a function, or a method bound to some class. Because of this you will often start out with a collection of plain functions with the ``static_function_hook`` decorator.
Once you start to realise that the functions are actually associated with some class, you will likely start to structure these methods so that they belong to this class which may have some known fields (as seen in the code examples above).

Using ``before`` and ``after`` methods
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``.before`` and ``.after`` method of the functions decorated by the ``function_hook`` or ``static_function_hook`` is required to be used when using this as a decorator to tell pyMHF whether to run the detour before or after the original function. If this is not included then an error will be raised.
Depending on whether you mark the hooks as ``before`` or ``after`` hook you may get some functionality. See :ref:`here <writing_mods_hooking_functionality>` for more details.

Function type hints
^^^^^^^^^^^^^^^^^^^

As mentioned at the start of this document, it is critical that the functions which are decorated with these two decorators have correct and complete type hints.
These types MUST be either a ctypes plain type (eg. ``ctypes.c_uint32``), a ctypes pointer to some type, or a class which inherits from ``ctypes.Structure``. Note that the :class:`~pymhf.core.hooking.Structure` inherits from this so a type inheriting from this type is also permissible.
Further, you will have seen above that none of these functions have any actual body. This is because even when we call this function, we don't actually execute the code contained within it.
Because of this it's recommended that you simply add ``pass`` to the body of the function as above.
Any docstrings which are included as part of the body will be shown in your IDE of choice, so if you are writing a library it's recommended that you add docstrings if convenient so that users may know what the function does.

.. warning::
    It seems to due to how the :py:class:`ctypes.c_char_p` is implemented, using it as an arg type is not recommended as it can cause issues with the data passed to the argument which can cause program crashes.
    Instead, use either :py:class:`ctypes.c_ulong` or :py:class:`ctypes.c_ulonglong` depending on whether you are hooking a 32 or 64 bit process respectively, then do ``arg_value = ctypes.c_char_p(addr).value``. This will get the value as a ``bytes`` object.

.. note::
    Variadic functions are not supported by pyMHF. You may attempt to hook them with some success, but they will generally end up causing the program to crash.

.. note::
    Python has issues with correctly type hinting ctypes pointers. The correct way to specify a pointer of some type is to use ``ctypes.POINTER(type)``, however static typing tools won't accept this as a correct type even though this returns a type. To get around this the recommended way to type pointers is to use ``ctypes._Pointer[type]``, and include ``from __future__ import annotations`` on the first line of your script.
    Internally pyMHF does fix this issue so if this line isn't included your code should still run.

Creating new empty instances of classes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Often when calling a function from the binary you'll need to pass in a pointer to a class which may be populated with some data.
pyMHF makes this easy by providing the :py:meth:`Structure.new_empty() <pymhf.core.hooking.Structure.new_empty>` classmethod class which will allocate enough memory for the structure as per its definition and return an instance of the class bound to this memory region.

We can see how to use this below:

.. code-block:: py

    import ctypes
    from typing import Annotated
    from pymhf.core.hooking import Structure
    from pymhf.utils.partial_struct import partial_struct

    @partial_struct
    class Vector(Structure):
        _total_size_ = 0x10
        x: Annotated[ctypes.c_float, 0x0]
        y: Annotated[ctypes.c_float, 0x4]
        z: Annotated[ctypes.c_float, 0x8]

    # Create an instance and pass it into some function...
    def function(self):
        vect = Vector.new_empty()
        # `get_position` is some made up function which we will say takes in a
        # pointer to a vector and sets the components to be the player location.
        get_position(ctypes.byref(vect))
        # Now afterwards we would see the components of the vector will have actual values
        print(f"I am at ({vect.x}, {vect.y}, {vect.z})")

.. note::
    In the above code snippet, ``vect`` will have all of the bytes in the associated memory region set to 0. For fields like ints and such this is fine, but for fields which are pointers care needs to be taken to not try and derefence the values. It is recommended that you only try and access data from this class once you have passed it into some function to set the data (or set the data yourself!).
