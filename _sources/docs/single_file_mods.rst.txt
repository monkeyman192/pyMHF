Single-file mods
================

While pyMHF is designed to be used to create libraries upon which mods can be made, for smaller scale projects or small tests, this is not convenient.
To accomodate this, pyMHF can run a single file containing a mod.

This file **MAY** have the following attributes defined in it to simplify the defintions:

``__pymhf_func_binary__`` (``str``)
    The name of the binary all the function offsets/patterns are to be found relative to/in. If provided this will be the default for all functions, however any ``manual_hook`` with a different value provided will supersede this value.

``__pymhf_func_offsets__`` (``dict[str, Union[int, dict[str, int]]]``)
    A lookup containing the function names and offsets. Generally the keys will be the function names that you want to call the function by, and the values will simply be the offset relative to the start of the binary. For overloads the value can be another dictionary with keys being some identifier for the overload (eg. the argument types), and the values being the offsets.

``__pymhf_func_call_sigs__`` (``dict[str, Union[FUNCDEF, dict[str, FUNCDEF]]]``)
    A lookup containing the function names and function call signatures. The keys will be the function names that you want to call the function by, and the values will either be the ``FUNCDEF`` itself, or a dictionary similar to the ``__pymhf_func_offsets__`` mapping.

``__pymhf_func_patterns__`` (``dict[str, Union[str, dict[str, str]]]``)
    A lookup containing the function names and byte patterns to find the functions at. The keys will be the function names that you want to call the function by, and the values will be either a string containing the pattern, or a dictionary similar to the ``__pymhf_func_offsets__`` mapping.

Note that none of these are mandatory, however they do simplify the code in the file a decent amount and keep the file more easy to maintain.

Below is an example single-file mod for the game No Man's Sky:

.. code-block:: py
    :caption: example_mod.py

    # /// script
    # dependencies = ["pymhf"]
    # 
    # [tool.pymhf]
    # exe = "NMS.exe"
    # steam_gameid = 275850
    # start_paused = false
    # 
    # [tool.pymhf.logging]
    # log_dir = "."
    # log_level = "info"
    # window_name_override = "NMS test mod"
    # ///

    from logging import getLogger

    from pymhf import Mod, load_mod_file
    from pymhf.core.hooking import on_key_pressed

    logger = getLogger("testmod")


    class MyMod(Mod):
        @on_key_pressed("p")
        def press_p(self):
            logger.info("Pressed P now!")


    if __name__ == "__main__":
        load_mod_file(__file__)

This mod clearly has very little functionality, but the above highlights the minimum requirements to make a single-file mod using pyMHF.

To run this mod it is **strongly** recommended to use `uv <https://github.com/astral-sh/uv>`_ as it has full support for inline script metadata.

The steps to run the above script from scratch (ie. with no ``uv`` installed) are as follows:

.. code-block:: bash

    python -m pip install uv
    uv run script.py

In the above ensure that the ``python`` command runs a python version between 3.9 and 3.11 INCLUSIVE.
Replace `script.py` with the name of the script as it was saved.

To modify the above script, the only values that really need to be changed are the :ref:`settings-pymhf.steam_guid` and :ref:`settings-pymhf.exe` values.

If the game is being ran via steam, replace ``steam_gameid`` with the value found in steam, and set ``exe`` to be the name of the game binary.
If the game or program is not run through steam, remove the ``steam_gameid`` value and instead set ``exe`` and the absolute path to the binary.

Note that by default the GUI will not be installed by ``uv`` and is only available on 64-bit installations of Python due to DearPyGui lacking support for 32-bit. If you want the GUI to be included, add the ``[gui]`` extra to your script dependecies metadata, like so:

.. code-block:: py

    # /// script
    # dependencies = ["pymhf[gui]"]
    # 
    ... (truncated)
