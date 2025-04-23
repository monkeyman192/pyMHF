Custom Callbacks
================

pyMHF is able to register custom callbacks which are useful for libraries in that they can be used to declare decorators which perform some certain action which is linked to the executable being modded.

The best way to see this is by an example taken from the NMS.py source code:

.. code-block:: py
    :caption: decorators.py

    from pymhf.core import DetourTime

    class main_loop:
        @staticmethod
        def before(func):
            func._custom_trigger = "MAIN_LOOP"
            func._hook_time = DetourTime.BEFORE
            return func

        @staticmethod
        def after(func):
            func._custom_trigger = "MAIN_LOOP"
            func._hook_time = DetourTime.AFTER
            return func

    def on_fully_booted(func):
        """
        Configure the decorated function to be run once the game is considered
        "fully booted".
        This occurs when the games' internal state first changes to "mode selector"
        (ie. just before the game mode selection screen appears).
        """
        func._custom_trigger = "MODESELECTOR"
        return func


The critical piece of information to take away from the above is the assignment ``func._custom_trigger = <something>``. This line assigns the function as a custom trigger with the string value as the key.
We can define the hook time for this custom callback by specifying ``func._hook_time = DetourTime.BEFORE`` or ``func._hook_time = DetourTime.AFTER``.
If this isn't provided then the fallback time will be ``DetourTime.NONE`` which essentially means "it doesn't matter".

These above custom callbacks can then be applied to some function in a mod like so:

.. code-block:: py
    :caption: main_loop_mod.py

    import logging
    from decorators import main_loop, on_fully_booted
    from pymhf import Mod

    class MyMod(Mod):
        @main_loop.before
        def before_mainloop(self):
            logging.info("Before the main loop!")

        @on_fully_booted
        def booted(self):
            logging.info("Game is booted!")

.. note::
    The custom callback functions defined within the mod cannot take any arguments.

Now that we have defined the custom callbacks, and we have applied them to some functions in our mod, the last thing we need to do is write the actual code which will cause these callbacks to get triggered.

It is recommended that theses are implemented in "internal" mods which can be defined like so:

.. code-block:: py
    :caption: internal_mod.py
    :linenos:

    from pymhf import Mod
    from pymhf.core import DetourTime
    from pymhf.gui.decorators import no_gui
    from pymhf.core.hooking import hook_manager
    import pymhf.core._internal as _internal

    # Internal imports for various constants etc defined by the library.
    import hooks
    import StateEnum

    @no_gui
    class _INTERNAL_Main(Mod):

        @hooks.cTkFSMState.StateChange.after
        def state_change(self, this, lNewStateID, lpUserData, lbForceRestart):
            if lNewStateID == StateEnum.ApplicationGameModeSelectorState.value:
                curr_gamestate = _internal.GameState.game_loaded
                _internal.GameState.game_loaded = True
                if _internal.GameState.game_loaded != curr_gamestate:
                    # Only call this the first time the game loads
                    hook_manager.call_custom_callbacks("MODESELECTOR", DetourTime.AFTER)
                    hook_manager.call_custom_callbacks("MODESELECTOR", DetourTime.NONE)
            else:
                hook_manager.call_custom_callbacks(lNewStateID.decode(), DetourTime.AFTER)
                hook_manager.call_custom_callbacks(lNewStateID.decode(), DetourTime.NONE)

        @hooks.cGcApplication.Update.before
        def _main_loop_before(self, this):
            """ The main application loop. Run any before functions here. """
            hook_manager.call_custom_callbacks("MAIN_LOOP", DetourTime.BEFORE)

        @hooks.cGcApplication.Update.after
        def _main_loop_after(self, this):
            """ The main application loop. Run any after functions here. """
            hook_manager.call_custom_callbacks("MAIN_LOOP", DetourTime.AFTER)


The above shows off a few things.

The first thing to notice is that the :py:func:`~pymhf.gui.decorators.no_gui` decorator which indicates that the mod won't be displayed in the GUI. Since this is an internal mod we don't need it to be reloadable or need to expose anything to users. However, it may make sense for a library to provide this to users, so it's not something that necessarily needs to be applied.

The next thing to notice is that we are using hooks defined within the library (ie. ``hooks.cGcApplication.Update``). These make writing hooks significantly easier for users compared to having to use the :py:func:`~pymhf.core.hooking.manual_hook` decorator. In this case we have got hooks defined for the main update loop function, as well as a state change function.

Finally, we can see on a number of lines a call to :py:meth:`~pymhf.core.hooking.HookManager.call_custom_callbacks`.
This is the connection between the previous two code blocks.

We can read/understand this code as; when the ``_main_loop_before`` detour is run, it will call the ``"MAIN_LOOP"`` custom callback with the detour time being ``DetourTime.BEFORE``. This will call the ``MyMod.before_mainloop`` method which we can see in ``main_loop_mod.py`` as provided above.

Conclusion
----------

By utilising custom callbacks as shown above, library authors can create simple decorators to give mod authors a very easy way to hook into regularly used functions such are state changes or the main update loop of a game.

.. warning::
    Providing a decorator for the main game loop is very useful, but it should be remembered that we are using python, and while the overhead is fairly low in calling detours in this loop, it should be stressed that if you put too much in the functions that run before or after the main loop function it could easily cause performance issues.
