Usage
=====

There are a number of convenient ways to use pyMHF:

Command line
------------

pyMHF registers ``pymhf`` as a command which can be called from your shell. This command has a number of options (call ``pymhf --help`` for more details).

From code
---------

pyMHF may also be invoked from code in the case of a more complex situation (eg, needing to hook some dynamically generated subprocess).

.. code-block:: py

    import os.path as op
    from subprocess import Popen

    from pymhf import run_module

    if __name__ == "__main__":
        # Run a mod by creating the process and then attaching pymhf later.
        proc = Popen("notepad.exe")
        CONFIG = {
            "pid": proc.pid,
            "start_paused": False,
            "start_exe": False,
        }
        run_module(op.join(op.dirname(__file__), "test_mod.py"), CONFIG, None, None)

In the above we are passing the absolute path to the file (or it could be mod folder) to be loaded, as well as the explicit configuration to be loaded.

.. note::
    See :doc:`/docs/settings` for details on the keys which the config can have. Keep in mind that the keys under the ``pymhf`` section are top level keys, and keys under the subsections (eg. ``pymhf.logging``) will have a top-level key of ``logging`` and then the keys are under that.

.. note::
    See :py:func:`~pymhf.main.run_module` for details on the other arguments (they are only required if you are calling a library which is VERY unlikely from code...)
