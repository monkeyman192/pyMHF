Configuring pyMHF
=================

pyMHF configuration is written in the `toml <https://toml.io/en/>`_ format.
These can be provided in one of two ways, depending on whether you are providing them as part of a library, or as part of a single-file mod.

For a library, the settings MUST be provided in a ``pymhf.toml`` file within the root directory of the library (ie. not the top level, but the named directory which contains all the files relevant to the library, cf. :doc:`/docs/libraries/writing_libraries`)
For a single-file mod, the settings are provided in the inline metadata (see :doc:`here </docs/single_file_mods>`).

Configuration sections and values
---------------------------------

In the following we shall name the sections as how they must be typed in the ``pymhf.toml`` file. To use these in the inline metadata for a single-file mod, simply prepend ``tool.`` to the section name.

``pymhf`` section:
^^^^^^^^^^^^^^^^^^

This section handles properties which relate to the game or program that the library will be for.

.. _settings-pymhf.exe:

``exe``
"""""""

*Required unless ``pid`` specified*

If :ref:`settings-pymhf.start_exe` is ``True`` (the default) - either the absolute path to the binary being run, or the name of the exe which is being run by steam.

If :ref:`settings-pymhf.start_exe` is ``False`` - the exe name (ie. ``notepad.exe``) of an already running process to attach to.

.. _settings-pymhf.pid:

``pid``
"""""""

*Optional*

The process id to attach pyMHF to. This will have no effect if :ref:`settings-pymhf.exe` is specified and also if :ref:`settings-pymhf.start_exe` is False.

.. _settings-pymhf.steam_guid:

``steam_guid``
""""""""""""""

*Optional*

If the game is run through steam, this should set to the Steam App ID. This can be found by right clicking on the game in your library and selecting "Properties...". The value can be found under the "Updates" option on the left.

.. _settings-pymhf.required_assemblies:

``required_assemblies``
"""""""""""""""""""""""

*Optional*

A list of assemblies that are required to be loaded by the binary at ``path`` for the game to be considered "loaded". For now, if this is provided, it will also be the binary within which offsets are found relative to, however this will be relaxed in the future as better functionality regarding this is developed.

.. _settings-pymhf.start_paused:

``start_paused``
""""""""""""""""

*Optional* - default ``true``

Whether or not to start the binary paused. Some programs do no like being started paused, however, if you can start paused it is preferred so that all hooks are created before any code is executed, ensuring no potential detours to be run are missed.

.. _settings-pymhf.default_mod_save_dir:

``default_mod_save_dir``
""""""""""""""""""""""""

*Can use magic path*

The path to the directory within which mod saves are to be placed. If this is not an absolute path and instead a "magic" path, ``MOD_SAVES`` will be appended to the magic path for the final path.

.. _settings-pymhf.internal_mod_dir:

``internal_mod_dir``
""""""""""""""""""""

*Optional* - *Can use magic path* - *Library only*

The path to the directory which contains the mods to be run by the library.

.. _settings-pymhf.start_exe:

``start_exe``
"""""""""""""

*Optional*

By default pyMHF will start the configured binary so that it may attach itself and start hooking functions as soon as possible.
This can sometimes have issues, or you may want to only attach at some later time.
By setting this value to ``false``, pyMHF will not attempt to start the binary and will instead find the process based on the :ref:`settings-pymhf.exe` value.

``interactive_console``
"""""""""""""""""""""""

*Optional* - Default ``true``

If set to ``false`` then there will be no interactive python terminal created in the initial terminal.

``pymhf.logging`` section:
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. _settings-pymhf.logging.default_log_dir:

``default_log_dir``
"""""""""""""""""""

*Can use magic path*

The path to save the logs under. If not an absolute path, a subdirectory called ``logs`` will be created under this directory.

.. _settings-pymhf.logging.log_level:

``log_level``
"""""""""""""

Whether to log at the standard level (``INFO``), or more in-depth (``DEBUG``).

.. _settings-pymhf.logging.window_name_override:

``window_name_override``
""""""""""""""""""""""""

A string to override the default log window name. Note: This has some limitation currently such as only ascii characters being supported. This will be fixed some time in the future.

``shown``
"""""""""

*Optional* - Default ``true``

If set to ``false``, then the log window will not be created and logs will be written by default to configured ``log_dir`` location if possible, otherwise they will be placed in the same directory as the module is determined to be loaded from.

``pymhf.gui`` section:
^^^^^^^^^^^^^^^^^^^^^^

This section related to properties specifically for the GUI which is auto-generated.

.. _settings-pymhf.gui.shown:

``shown``
"""""""""

Whether or not to show the GUI (``True`` or ``False``).

.. _settings-pymhf.gui.scale:

``scale``
"""""""""

The scale of the GUI. For some high-resolution monitors the GUI may end up scaled down when running from within a process, so sometimes this may need to be set to 1.5 for the GUI to look correct.

.. _settings-pymhf.gui.always_on_top:

``always_on_top``
"""""""""""""""""

Whether or not the GUI is always on top (``True`` or ``False``).

Magic path variables
--------------------

pyMHF has a few "magic" path variables which can be used to make setting up configs more generic and flexible.

To use the "name" versions of the magic strings, they must be surrounded by braces (ie. ``{EXE_DIR}``) as part of the path.

These path variables get resolved as part of a path, so we can provide a path like so ``{EXE_PATH}/../MyMods`` to place things in a folder called ``MyMods`` in the parent directory of the location of the main binary.

``EXE_DIR``
^^^^^^^^^^^

This is the absolute path to directory which contains the main binary being run.

``USER_DIR`` / ``"~"``
^^^^^^^^^^^^^^^^^^^^^^

This is a directory within your user folder. This will often look something like ``C:/Users/<username>/pymhf/<plugin name>``. For a single-file mod there is no ``plugin name`` so the folder will just be the ``pymhf`` folder.

``CURR_DIR`` / ``"."``
^^^^^^^^^^^^^^^^^^^^^^

The current working directory, ie. the directory the single-file mod or modding library is located in. For the modding library it will be the main directory of the project which contains the `pymhf.toml` file.


Local-only variables and sections
---------------------------------

The above configuration settings are the defaults as set by the library or single-file mod. However, there are some settings which will need to be configured before running any libraries since the location of mod folders will very for each user.

``pymhf.local_config`` section:
-------------------------------

These settings are set by calling ``pymhf --config <libraryname>`` or on first run of ``pymhf <libraryname>``.

- **mod_dir**: [Can use magic path] [Library only] The path to the directory which contains the mods to be run by the library.

- **mod_save_dir**: [Can use magic path] [Overrides ``default_mod_save_dir``] The path to the directory within which mod saves are to be placed. If this is not an absolute path and instead a "magic" path, ``MOD_SAVES`` will be appended to the magic path for the final path.

- **log_dir** [Can use magic path] [Overrides ``default_log_dir``] The path to save the logs under. If not an absolute path, a subdirectory called ``LOGS`` will be created under this directory.
