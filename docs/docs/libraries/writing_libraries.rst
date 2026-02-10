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

``pymhf_rtfunc`` entry-point
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Because of how python imports code, it is generally recommended that developers do not include any code which will be run when importing which relies on any particular state.
Because of this, we need some way to specify functions in the library which are to be run once the code has been injected into the target process, but before any mods are instantiated so that any data can be accessed as soon as possible in the mods.
To facilitate this, ``pyMHF`` has the ability to pick up functions which are defined as being run at run-time by the library.

For example, we may have some function which searches the binary for some data and then assigns it to a variable in a class like so:

.. code-block:: python
    :caption: library/data.py

    class Data:
        x: int

        def find_variable(self):
            # Some code to find the value of x
            x = 42

    data = Data()

We can now define the following end-point:

.. code-block:: toml

    [project.entry-points.pymhf_rtfunc]
    data = "library.data:data.find_variable"

The syntax of this entry-point is very similar to that of normal python entry-points, but this function will be found and then run before any mods are instantiated.

.. note::
    The specified function or method cannot take any arguments.
