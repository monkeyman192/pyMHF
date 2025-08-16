Single-file mods
================

While pyMHF is designed to be used to create libraries upon which mods can be made, for smaller scale projects or small tests, this is not convenient.
To accomodate this, pyMHF can run a single file containing a mod.

This document will be more focused on the aspects required specifically for a single-file mod.

For more general information regarding providing the data required for a mod see :doc:`here </docs/creating_hook_definitions>`.

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

In the above ensure that the ``python`` command runs a python version of at least 3.9.
Replace `script.py` with the name of the script as it was saved.

Note that the line ``load_mod_file(__file__)`` in the above script is what tells python to run the script with pyMHF.

Another way to run the script is

.. code-block:: bash

    uv run pymhf run script.py

This doesn't require the final line and is the recommended way since it also allows you to run a folder of mods by passing in a directory instead of a specific file.

To modify the above script, the only values that really need to be changed are the :ref:`settings-pymhf.steam_guid` and :ref:`settings-pymhf.exe` values.

If the game is being ran via steam, replace ``steam_gameid`` with the value found in steam, and set ``exe`` to be the name of the game binary.
If the game or program is not run through steam, remove the ``steam_gameid`` value and instead set ``exe`` and the absolute path to the binary.

Note that by default the GUI will not be installed by ``uv`` and is only available on 64-bit installations of Python due to DearPyGui lacking support for 32-bit. If you want the GUI to be included, add the ``[gui]`` extra to your script dependecies metadata, like so:

.. code-block:: py

    # /// script
    # dependencies = ["pymhf[gui]"]
    # 
    ... (truncated)
