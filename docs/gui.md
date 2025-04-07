# pyMHF auto-generated GUI

`pyMHF` provides a simple way to create GUI elements for your mod.

All components are implemented as decorators which can all be found in `pymhf.gui.decorators`:

## Clickable elements

### `gui_button(text: str)`
This decorator is to be applied to a method which takes no arguments.
The method will be called when the button is pressed.

### `gui_combobox(text: str, items: list[str] = [])`
This decorator is to be applied to a method which takes no arguments.
The method should have the arguments `sender` and `app_data`. `app_data` is the value of the combobox that is selected.
The method will be called when an element of the combobox is selected.

## Value elements

Each of these is applied to a property, however the `@property` decorator needs to applied later than this decorator (ie. the `@property` decorator should be on top of this one.)
If the property has a setter then the gui field created will be editable, otherwise it will not be, and for settable properties, changing the entry value will call the setter.

Note that these functions will take any of the extra arguments as listed in the link except the following:
`tag`, `source`, `user_data`, `callback`, `use_internal_label`.
These arguments are reserved by `pyMHF` for our own purposes and any values provided to the decorator will be ignored/removed.

### `INTEGER(label=str, **kwargs)`
Create an integer entry field which can take extra arguments.
To see what extra arguments are available, see the DearPyGUI documentation [here](https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_int).

### `BOOLEAN(label=str, **kwargs)`
Create an boolean entry field in the form of a checkbox which can take extra arguments.
To see what extra arguments are available, see the DearPyGUI documentation [here](https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_checkbox).

### `STRING(label=str, **kwargs)`
Create an string entry field which can take extra arguments.
To see what extra arguments are available, see the DearPyGUI documentation [here](https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_text).

### `FLOAT(label=str, **kwargs)`
Create an float entry field which can take extra arguments.
To see what extra arguments are available, see the DearPyGUI documentation [here](https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_double).

## Accessing the GUI via code

In general, you shouldn't need to access the gui via code within your mod, however, there are a few reasons for doing so (may want more control over what and how things are rendered), but the primary reason is to communicate with the "Hex View" tab.

Every instance of a mod has the `pymhf_gui` property which is the instance of the `pymhf.gui.gui.GUI` class which contains all the controls to the GUI.

For more details see [here](./hex_view.md).
