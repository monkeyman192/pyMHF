# Inter-mod functionality

It's all well and good having mods, but sometimes one mod may exist which accesses certain data or exposes certain functions which other mods could benefit from using.
`pyMHF` provides a convenient way for one mod to access the properties and methods of other loaded mods by exposing the loaded mods such that any other mod can access them.

## Usage

To access other mods we use the `mod_manager` which is provided by `from pymhf.core.mod_loader`:
```py
from from pymhf.core.mod_loader import mod_manager
```

This class is an instance of the `ModManager` class, and has a special method assigned to it so that the `mod_manager` object can be indexed by the `type` of the mod you wish to access.
The returned value is the currently valid *instance* of the mod requested.
This is seen more clearly below in the example.

## Example

A simple example is given below:

`mod1.py`
```py
import logging
from dataclasses import dataclass
from pymhf import Mod
from pymhf.core.mod_loader import ModState
from pymhf.gui.decorators import STRING

logger = logging.getLogger("EventProvider")

@dataclass
class EventState(ModState):
    event_id: int = 0

class EventProvider(Mod):
    state = EventState()

    @property
    @STRING("Event ID", decimal=True)
    def event_id(self):
        return self.state.event_id

    @event_id.setter
    def event_id(self, value):
        self.state.event_id = int(value)
```

This mod doesn't really do anything, however it utilises a few useful concepts; `ModState`'s and GUI elements.
The above mod won't hook anything, but it will add a numeric field to its mod tab in the GUI where a number can be entered.

We'll have a second mod in the same folder as the above:

`mod2.py`
```py
import logging
from typing import TYPE_CHECKING
from pymhf import Mod
from pymhf.core.hooking import on_key_pressed
from pymhf.core.mod_loader import mod_manager

if TYPE_CHECKING:
    from .mod1 import EventProvider

logger = logging.getLogger("EventUser")

class EventUser(Mod):
    @on_key_pressed("k")
    def press_k(self):
        event_provider = mod_manager[EventProvider]
        logger.info(f"Currently selected event id in other mod: {event_provider.event_id}")
```

The above mod shows off a few other useful features; key binding events and inter-mod functionality.
As with the previous mod, it won't hook anything or do anything, however, when the `k` key is pressed in game, the value of the event id entered into the GUI for the other mod will be logged from `EventUser`.

## Caveats / Things to keep in mind

- One must always do a lookup on the *type* of the mod being accessed, not an instance of it. We do this because internally, `pyMHF` manages the state of these mods, and these states and instances may change if some mod is reloaded, so one should always rely on `pyMHF` to do this lookup and not do it themselves.
- Never cache the result of `mod_manager[<type>]`. Again, for the same reasons as above. If you cache this result, and then the mod you are accessing is reloaded, you will not have the updated value. The lookup os on a dictionary and will be quick so need to worry about getting the mod whenever necessary.
- Avoiding circular imports. You will notice in the `mod2.py` file that we have a pattern to import `TYPE_CHECKING` from `typing`. This may look odd, but it's a convenient "trick" to get around circular imports. Because `pyMHF` handles all the importing logic of loading these python files, both initially and on reload, it is crucial that if you are importing any other mods it is done within a `if TYPE_CHECKING` branch, otherwise a circular import may occur and the mod will not function/may cause a crash. This is all necessary so that referenced mods can be correclty type-hinted.
- If two mods reference each other and call functions within each other a loop may occur where they call each other endlessly. This will obviously cause issues and should be avoided.
