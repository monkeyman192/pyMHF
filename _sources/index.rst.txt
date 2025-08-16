pyMHF documentation
===================
pyMHF is a python Modding and Hooking Framework.
It is designed to make it very easy to create libraries for any game or application which can then be used to make mods.
pyMHF is also able to run single python files as a mod `uv <https://docs.astral.sh/uv/>`_ recommended. See `here <single_file_mods>`_ for more details

.. important::
   When using uv as a package manager, it's very important that you DO NOT let uv use its managed python installs with pyMHF. These python builds do not seem to like being injected and will cause the target process to crash.
   It is recommended that you have a python version between 3.9+ installed from the official python source, and you can potentially even set the ``UV_NO_MANAGED_PYTHON`` environment variable to ``false`` on your system to force uv to use the system installs.

Features
--------

Pure python hooking
^^^^^^^^^^^^^^^^^^^

Write complex function hooks and mod completely in python, no need for c or c++ (some knowledge and experience of these languages however is useful!)

Live mod reloading
^^^^^^^^^^^^^^^^^^

Any mod which is loaded by pyMHF is automatically able to be reloaded via the GUI.
When a mod is loaded, it will have its own tab in the GUI, and at the top of the tab is a "reload" button. Pressing this will unload the currently loaded ``Mod`` instance from the mod file and reload the file from disk, re-hooking any functions required, and updating the tab for the mod if any gui elements have been added, removed or modified.

Multi-detour capability
^^^^^^^^^^^^^^^^^^^^^^^

pyMHF is able to support multiple detours for a single hooked function by enforcing detours to either be run before or after the original function.
This means that multiple mods can hook the same function and the only contention issues are those of the order in which the mods are instanitated. All valid hooks will be run from all loaded mods on the same hooked function.

.. note::
   Detours should generally be written such that their order doesn't matter.

.. tip::
   If you want to write a detour that does something both before and after the original function is run, write two detours! One *before* detour, and one *after*.


.. toctree::
   :maxdepth: 2
   :caption: Documentation:

   docs/index
   api/index
