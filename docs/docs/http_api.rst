HTTP API
========

pyMHF is able to automatically create HTTP API's for mods, including Swagger API docs, all powered by `FastAPI <https://fastapi.tiangolo.com/>`_.

To utilise this functionality, the `http_api` optional dependency needs to be installed with pyMHF (this is typed as ``pymhf[http_api]`` in your pyproject.toml.)

Decorators
----------

The functionality is implemented using the following decorator:

:py:func:`endpoint(route: Optional[str] = None, method: Optional[Literal["GET", "PUT", "WEBSOCKET"]] = None, dont_extend: bool = False) <pymhf.core.http_api.endpoint>`:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This decorator marks the function or property as one which will be exposed as a HTTP endpoint.

The ``route`` is an optional parameter which, if not provided will fall-back to the name of the function or property being decorated.
This value will be prefixed with the name of the mod, so in the following code, the endpoint will be ``GET MyMod/location``:

.. code-block:: python

    from pymhf import Mod
    from pymhf.core.http_api import endpoint

    class MyMod(Mod):
        @property
        @endpoint()
        def location(self):
            return "(0, 0, 0)"

The ``method`` is one of ``"GET"``, ``"PUT"`` or ``"WEBSOCKET"``.
If not provided the method will be selected based on the following logic:
If the function or method takes no arguments (other than ``self``), it will be a ``GET`` endpoint, otherwise it will be ``PUT``.

Finally, the ``dont_extend`` argument is for property endpoints. By default if a property has a setter, and the getter is decorated as a ``GET`` endpoint,
then the setter will linked up as a ``PUT`` endpoint. Setting this option to ``False`` will disable this.

.. note::
    It is possible to decorate a method which is already used by the gui as an endpoint as well. See the following example:

.. code-block:: python

    from pymhf import Mod
    from pymhf.gui.decorators import gui_button
    from pymhf.core.http_api import endpoint

    class MyMod(Mod):
        def __init__(self):
            super().__init__()
            self.money = 0

        @endpoint()
        @gui_button("Add $10")
        def add_money(self):
            self.money += 10

Websockets
----------

Websockets are created using the above decorator, and are currently read-only. This means that they can only be applied to properties.

.. warning::
    Since websockets can poll very frequently, care must be taken to not allow anything which can take any appreciable amount of time to return,
    otherwise you may see a performance hit.