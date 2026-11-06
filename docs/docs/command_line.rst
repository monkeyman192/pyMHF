Command Line Usage
==================

pyMHF can be called in a number of different ways from the command line.
Most of these look something like ``pymhf <command> <plugin_name>``.

The most common values for ``command`` are described below.

The value of ``plugin_name`` will depend on what you are opening, but will generally be the name of a pyMHF library or path to a folder.

**Note** The following is a general overview of the options. Run ``pymhf --help`` to see the options and their descriptions in the terminal.

Commands
--------

``run``
^^^^^^^

The ``run`` command is the command you will use the most often and can be used to run either a library (see :doc:`here </docs/libraries/writing_libraries>`), a folder, or an individual mod file.
This command has a few optional flags which can be used to configure what extra debugging or dev tools are ran.

The following 3 flags enable certain features when included:

``--log-console``
"""""""""""""""""

    Enables showing the log console. If not enabled logs will go in the configured folder. (:doc:`Config settings </docs/settings>`)

``--gui``
"""""""""

    Enables showing the gui for developer use. (:doc:`Gui details </docs/gui/gui>`)

``--debug-log``
"""""""""""""""

    Enable debug logging for this particular run.

The Following 2 flags are mutually exclusive (so only one may be provided at a time) and are essentially shortcuts to enable the above in a more convenient manner.

``--dev``
"""""""""

    Enable all development features (enables --gui and --log_console).

``--dev-debug``
"""""""""""""""

    Enable all development and debugging features (enables --gui, --log_console, and --debug_log).

``config``
^^^^^^^^^^

The config command will bring up a set of options which will let you configure pyMHF or the library which is being loaded.
Any settings which are changed from the default ones in the ``pymhf.toml`` file will be saved in your user directory as a ``pymhf.local.toml`` file.

This has just the one flag:

``-o`` / ``--open``
^^^^^^^^^^^^^^^^^^^

Open the directory the local config is stored at.