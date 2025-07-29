Writing Libraries
=================

.. attention::
    This page is not yet complete and some details may not be correct.

One of the most powerful features of pyMHF is to facilitate writing python libraries which can then be used to write mods.
pyMHF provides all the tools required to make setting up a library easy, so that one only has to provide the definitions and all the hooking and mod complexity will be handled automatically.

Follow the next steps to get your library project set up.

``pyproject.toml`` contents
---------------------------

``pymhflib`` entry-point
~~~~~~~~~~~~~~~~~~~~~~~~

In order to register a library so that it can be run with pymhf easily, it is strongly recommended that the following is put into the project's `pyproject.toml` file:

.. code-block:: toml

    [project.entry-points.pymhflib]
    plugin_name = "plugin_name"

Where ``plugin_name`` is the name of the plugin you want to register it as.
For example, the `NMS.py` plugin has the following:

.. code-block:: toml

    [project.entry-points.pymhflib]
    nmspy = "nmspy"

With this configuration, the library can be ran like ``pymhf run nmspy``.

``pymhfcmd`` entry-point
~~~~~~~~~~~~~~~~~~~~~~~~

Libraries can also register commands which can be run so that they may provide some extra functionality in a simple way. An example might be to have some function which checks whether the patterns the library provides is correct for the current version of the game.

For example, this is implemented in NMS.py as:

.. code-block:: toml

    [project.entry-points.pymhfcmd]
    check = "check"

In this case the key is the name of the command to call when doing ``pymhf cmd <command> <library name>``, and the value is the name of the function to be run.
Note that this function must be importable at a top level of the library. To check this you can load python and then do ``from <library name> import <function name>``. If this imports, then the command will be able to be found.
This function MUST take one argument which will be a list of extra commands the pymhf command line parser receives. It is then up to the library developer to parse these (generally with argparse).

For the above example of checking to see if the patterns are valid, we may want to call it like this:

.. code::

    pymhf cmd check --exe="NMS.exe" nmspy

The ``check`` function will receive ``['--exe="NMS.exe"']`` as an argument which we can then parse.
