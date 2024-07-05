import traceback
from typing import TypedDict
# import win32gui
# import win32con

import dearpygui.dearpygui as dpg

from pymhf.core.mod_loader import Mod, ModManager
from pymhf.core.utils import AutosavingConfig
from pymhf.gui.protocols import ButtonProtocol, VariableProtocol, VariableType

SETTINGS_NAME = "_pymhf_gui_settings"

# TODO:
# - add keyboard shortcut to show or hide the GUI
# - Add support for mod states


class ModWidgets(TypedDict):
    buttons: list
    variables: list


class GUI:
    def __init__(self, mod_manager: ModManager, config: AutosavingConfig):
        self.config = config
        self.scale = config.getint("gui", "scale", fallback=1)
        dpg.create_context()
        dpg.create_viewport(
            title='pyMHF',
            width=int(400 * self.scale),
            height=int(400 * self.scale),
            decorated=True,
        )
        dpg.setup_dearpygui()
        dpg.set_global_font_scale(self.scale)
        self.tracking_variables = []
        self.tabs = []
        self._shown = True
        self._handle = None
        self.mod_manager = mod_manager

        self.mod_widgets: dict[str, ModWidgets] = {}

        # Keep track of the viewport dimensions and position.
        # NOTE: These are ONLY updated when the viewport is minimised by the `hide_window` method.
        # TODO: Maybe set a max height and width?
        self._window_dimensions = [0, 0]
        self._window_position = [0, 0]

        self.add_window()

    def show_window(self):
        # TODO: This needs to be called twice to run properly...
        # It might still be better to try and use the `win32gui` calls to get the system to handle this better
        if self._window_dimensions != [0, 0]:
            dpg.maximize_viewport()
            dpg.set_viewport_width(self._window_dimensions[0])
            dpg.set_viewport_height(self._window_dimensions[1])
            dpg.set_viewport_pos(self._window_position)
        # if not self._shown and self._handle:
        #     win32gui.ShowWindow(self._handle, win32con.SW_SHOW) 
        #     win32gui.SetWindowLong(self._handle, win32con.GWL_EXSTYLE, 0)
        #     self._shown = True

    def hide_window(self):
        self._window_dimensions = (dpg.get_viewport_width(), dpg.get_viewport_height())
        self._window_position = dpg.get_viewport_pos()
        dpg.minimize_viewport()
        # if self._shown and self._handle:
        #     win32gui.ShowWindow(self._handle, win32con.SW_HIDE) 
        #     self._shown = False

    def toggle_debug_mode(self, _sender, is_debug):
        self.config.set("pymhf", "log_level", is_debug and "debug" or "info")

    def toggle_show_gui(self, _sender, show_gui):
        self.config.set("gui", "shown", show_gui)

    def add_settings_tab(self):
        """ Add a settings tab to configure the gui and other things."""
        with dpg.value_registry():
            dpg.add_bool_value(tag="is_debug", default_value=False)
            dpg.add_bool_value(tag="show_gui", default_value=True)
        with dpg.tab(label="Settings", tag=SETTINGS_NAME, parent="tabbar"):
            self.tabs.append("Settings")

        # Toggle for debug mode
        with dpg.group(horizontal=True, parent=SETTINGS_NAME):
            dpg.add_text("Enable debug mode")
            dpg.add_checkbox(
                    source="is_debug",
                    callback=self.toggle_debug_mode,
                )
        # Toggle for whether to show the gui at all.
        with dpg.group(horizontal=True, parent=SETTINGS_NAME):
            dpg.add_text("Show GUI")
            dpg.add_checkbox(
                source="show_gui",
                callback=self.toggle_show_gui,
            )

    def add_tab(self, cls: Mod):
        """ Add the mod as a new tab in the GUI. """
        # Check to see if the `no_gui` decorator has been applied to the class.
        # If so, don't add it now.
        if getattr(cls, "_no_gui", False) == True:
            return

        name = cls.__class__.__name__
        cls._gui = self

        with dpg.tab(label=name, tag=name, parent="tabbar"):
            dpg.set_item_user_data(name, cls)
            self.tabs.append(name)
            self.mod_widgets[name] = {
                "buttons": [],
                "variables": [],
            }

        dpg.add_button(label="Reload Mod", callback=self.mod_manager._gui_reload, user_data=cls._mod_name, parent=name)

        for _button in cls._gui_buttons:
            self.add_button(_button)

        for _variable_name, _getter in cls._gui_variables.items():
            self.add_variable(cls, _variable_name, _getter)

    def add_window(self):
        with dpg.window(
            label="pyMHF",
            width=int(200 * self.scale),
            height=int(200 * self.scale),
            tag="pyMHF",
            on_close=self.exit
        ):
            dpg.add_tab_bar(tag="tabbar")

    def add_button(self, callback: ButtonProtocol):
        name = callback.__self__.__class__.__name__
        meth_name = callback.__qualname__
        but = dpg.add_button(label=callback._button_text, callback=callback, parent=name)
        self.mod_widgets[name]["buttons"].append((meth_name, but))

    def add_variable_gui_elements(self, cls, variable: str, getter: VariableProtocol):
        name = cls.__class__.__name__
        tag = f"{name}.{variable}"

        def on_update(_, app_data, user_data):
            setattr(user_data[0], user_data[1], app_data)

        with dpg.group(horizontal=True, parent=name):
            if getter._label_text is not None:
                dpg.add_text(getter._label_text)
            else:
                dpg.add_text(f"{variable}: ")
            if getter._has_setter:
                if getter._variable_type == VariableType.INTEGER:
                    dpg.add_input_int(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        on_enter=True,
                    )
                elif getter._variable_type == VariableType.STRING:
                    dpg.add_input_text(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        on_enter=True,
                    )
                elif getter._variable_type == VariableType.FLOAT:
                    dpg.add_input_double(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        on_enter=True,
                    )
                elif getter._variable_type == VariableType.BOOLEAN:
                    dpg.add_checkbox(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                    )
            else:
                dpg.add_text(source=tag)

    def add_variable(self, cls, variable: str, getter: VariableProtocol):
        tag = f"{cls.__class__.__name__}.{variable}"
        value = getattr(cls, variable)
        with dpg.value_registry():
            # If there is no setter, the value type has to be a string
            # TODO: Check on discord if it's possible to do this some other way.
            if not getter._has_setter:
                dpg.add_string_value(tag=tag, default_value=str(value))
            else:
                if getter._variable_type == VariableType.INTEGER:
                    dpg.add_int_value(tag=tag, default_value=value)
                elif getter._variable_type == VariableType.STRING:
                    dpg.add_string_value(tag=tag, default_value=value)
                elif getter._variable_type == VariableType.FLOAT:
                    dpg.add_double_value(tag=tag, default_value=value)
                elif getter._variable_type == VariableType.BOOLEAN:
                    dpg.add_bool_value(tag=tag, default_value=value)
        self.add_variable_gui_elements(cls, variable, getter)
        self.tracking_variables.append(
            (
                tag,
                cls,
                variable,
                getter._variable_type == VariableType.STRING or not getter._has_setter
            )
        )

    def remove_tab(self, cls):
        """ Remove the tab associated with the provided class. """
        name = cls.__class__.__name__
        self.tabs.remove(name)
        dpg.delete_item(name)

    def run(self):
        try:
            dpg.show_viewport()
            dpg.set_primary_window("pyMHF", True)
            while dpg.is_dearpygui_running():
                # For each tracking variable, update the value.
                for tag, cls, var, is_str in self.tracking_variables:
                    if is_str:
                        dpg.set_value(tag, str(getattr(cls, var)))
                    else:
                        dpg.set_value(tag, getattr(cls, var))
                dpg.render_dearpygui_frame()
            dpg.destroy_context()
        except:
            from logging import getLogger
            logger = getLogger("GuiLogger")
            logger.error("Unable to create GUI window!")
            logger.exception(traceback.format_exc())

    def exit(self):
        dpg.stop_dearpygui()
