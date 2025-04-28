import logging
from enum import Enum
from typing import Optional, TypedDict, Union

# import win32con
import dearpygui.dearpygui as dpg
import win32gui

import pymhf.core._internal as _internal
import pymhf.core.caching as cache
from pymhf.core.mod_loader import Mod, ModManager
from pymhf.gui.hexview import HexView
from pymhf.gui.protocols import ButtonProtocol, ComboBoxProtocol, VariableProtocol, VariableType
from pymhf.utils.winapi import set_window_transparency

SETTINGS_NAME = "_pymhf_gui_settings"
HEX_NAME = "_pymhf_gui_hex"
DETAILS_NAME = "_pymhf_gui_details"
WINDOW_TITLE = "pyMHF"

# TODO:
# - add keyboard shortcut to show or hide the GUI
# - Add support for mod states


logger = logging.getLogger("GUILogger")
rootLogger = logging.getLogger("")


class WidgetType(Enum):
    BUTTON = 0
    VARIABLE = 1
    TEXT = 2
    COMBOBOX = 3


class Widgets(TypedDict):
    buttons: dict[str, Union[int, str]]
    comboboxes: dict[str, Union[int, str]]
    variables: dict[str, list[tuple[Union[int, str], WidgetType]]]


def toggle_on_top(item: int, value: bool):
    dpg.set_viewport_always_top(value)


class GUI:
    hex_view: HexView

    def __init__(self, mod_manager: ModManager, config: dict):
        self.config = config
        self.always_on_top = config.get("gui", {}).get("always_on_top", False)
        self.is_debug = config.get("logging", {}).get("log_level") == "debug"
        self.scale = config.get("gui", {}).get("scale", 1)
        dpg.create_context()
        dpg.create_viewport(
            title=WINDOW_TITLE,
            width=int(600 * self.scale),
            height=int(800 * self.scale),
            decorated=True,
            always_on_top=self.always_on_top,
        )
        dpg.setup_dearpygui()
        dpg.set_global_font_scale(self.scale)
        self.tracking_variables: dict[str, list[tuple[str, Mod, str, bool]]] = {}
        self.tabs: dict[int, str] = {}
        self._shown = True
        self._handle = None
        self._current_tab: Optional[str] = None
        self.mod_manager = mod_manager

        self.widgets: dict[str, Widgets] = {}

        # Keep track of the viewport dimensions and position.
        # NOTE: These are ONLY updated when the viewport is minimised by the `hide_window` method.
        # TODO: Maybe set a max height and width?
        self._window_dimensions = [0, 0]
        self._window_position = [0, 0]

        # Some info related settings
        self._hide_pyd_modules = True

        self.add_window()

    def alpha_callback(self, sender, app_data):
        set_window_transparency(self.hwnd, app_data)

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
        try:
            self.config["logging"]["log_level"] = is_debug and "debug" or "info"
        except KeyError:
            pass
        if is_debug:
            rootLogger.setLevel(logging.DEBUG)
        else:
            rootLogger.setLevel(logging.INFO)

    def toggle_show_gui(self, _sender, show_gui):
        self.config["gui"]["shown"] = show_gui

    def add_hex_tab(self):
        tab = dpg.add_tab(label="Hex View", tag=HEX_NAME, parent="tabbar")
        tab_alias = dpg.get_alias_id(tab)
        self.tabs[tab_alias] = HEX_NAME

        self.hex_view = HexView(HEX_NAME)
        self.hex_view._setup()

    def add_settings_tab(self):
        """Add a settings tab to configure the gui and other things."""
        with dpg.value_registry():
            dpg.add_bool_value(tag="always_on_top", default_value=self.always_on_top)
            dpg.add_bool_value(tag="is_debug", default_value=self.is_debug)
            dpg.add_bool_value(tag="show_gui", default_value=True)
        tab = dpg.add_tab(label="Settings", tag=SETTINGS_NAME, parent="tabbar")
        tab_alias = dpg.get_alias_id(tab)
        self.tabs[tab_alias] = SETTINGS_NAME

        with dpg.table(header_row=False, parent=SETTINGS_NAME, policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column()
            dpg.add_table_column()

            # Toggle for debug mode
            with dpg.table_row():
                dpg.add_text("Enable debug mode")
                dpg.add_checkbox(
                    source="is_debug",
                    callback=self.toggle_debug_mode,
                )

            # Toggle for whether to show the gui at all.
            with dpg.table_row():
                dpg.add_text("Show GUI")
                dpg.add_checkbox(
                    source="show_gui",
                    callback=self.toggle_show_gui,
                )

            # Add a slider for the visibility.
            with dpg.table_row():
                dpg.add_text("Transparency")
                dpg.add_slider_float(
                    default_value=1,
                    max_value=1,
                    min_value=0,
                    callback=self.alpha_callback,
                )

            # Add a checkbox to toggle whether the window should stay always on top.
            with dpg.table_row():
                dpg.add_text("Always on top")
                dpg.add_checkbox(
                    source="always_on_top",
                    callback=toggle_on_top,
                )

    def _toggle_show_pyd(self, item: int, value: bool):
        self._hide_pyd_modules = value

    def add_details_tab(self):
        tab = dpg.add_tab(label="Details", tag=DETAILS_NAME, parent="tabbar")
        tab_alias = dpg.get_alias_id(tab)
        self.tabs[tab_alias] = DETAILS_NAME

        imports = _internal.imports
        tree = dpg.add_tree_node(label="Imports", parent=DETAILS_NAME)
        for dll_name, functions in imports.items():
            dll_branch = dpg.add_tree_node(label=dll_name, parent=tree)
            for func_name in functions.keys():
                dpg.add_tree_node(label=func_name, parent=dll_branch, leaf=True, bullet=True)

        # TODO: Add this toggle back and make it work.
        # with dpg.group(horizontal=True, parent=DETAILS_NAME):
        #     dpg.add_text("Hide *.pyd files")
        #     dpg.add_checkbox(callback=self._toggle_show_pyd, default_value=True)

        # Add in a section to show the actual list of loaded modules
        module_tree = dpg.add_tree_node(label="Loaded modules", parent=DETAILS_NAME)
        if self._hide_pyd_modules:
            names = (name for name in cache.module_map.keys() if not name.endswith(".pyd"))
        else:
            names = (name for name in cache.module_map.keys())
        for func_name in names:
            dpg.add_tree_node(label=func_name, parent=module_tree, leaf=True, bullet=True)

    def reload_tab(self, cls: Mod):
        """Reload the tab for the specific mod."""
        name = cls.__class__.__name__
        cls.pymhf_gui = self
        widgets = self.widgets.get(name, {})

        self.reload_buttons(cls, widgets)
        self.reload_comboboxes(cls, widgets)
        self.reload_variables(cls, widgets)

    def reload_buttons(self, cls: Mod, widgets: Widgets):
        """Reload all the buttons. Any new buttons will be added, any old ones will be removed, and any that
        remain will be reconfigured to point to the new bound method with any modified parameters (such as
        button label.)
        """
        button_widgets = widgets["buttons"]

        existing_button_names = set([b for b in button_widgets.keys()])
        mod_button_names = set([b for b in cls._gui_buttons.keys()])

        new_buttons = mod_button_names - existing_button_names
        for button_name in new_buttons:
            self.add_button(cls._gui_buttons[button_name])

        remaining_buttons = existing_button_names & mod_button_names
        for button_name in remaining_buttons:
            _button = cls._gui_buttons[button_name]
            dpg.configure_item(
                button_widgets[button_name],
                label=_button._button_text,
                callback=_button,
            )

        removed_buttons = existing_button_names - mod_button_names
        for button_name in removed_buttons:
            dpg.delete_item(button_widgets[button_name])
            button_widgets.pop(button_name)

    def reload_comboboxes(self, cls: Mod, widgets: Widgets):
        """Reload all the comboboxes. Any new combos will be added, any old ones will be removed, and any that
        remain will be reconfigured to point to the new bound method with any modified parameters (such as
        combo label and items).
        """
        combo_widgets = widgets["comboboxes"]

        existing_combo_names = set([c for c in combo_widgets.keys()])
        mod_combo_names = set([c for c in cls._gui_comboboxes.keys()])

        new_combos = mod_combo_names - existing_combo_names
        for combo_name in new_combos:
            self.add_combobox(cls._gui_comboboxes[combo_name])

        remaining_combos = existing_combo_names & mod_combo_names
        for combo_name in remaining_combos:
            _combo = cls._gui_comboboxes[combo_name]
            # Combo boxes have their text prepended.
            for var_id, var_type in combo_widgets[combo_name]:
                if var_type == WidgetType.TEXT:
                    dpg.set_value(var_id, _combo._combobox_text)
                else:
                    dpg.configure_item(var_id, items=_combo._items, callback=_combo)

        removed_combos = existing_combo_names - mod_combo_names
        for combo_name in removed_combos:
            for var_id, _ in combo_widgets[combo_name]:
                dpg.delete_item(var_id)
            combo_widgets.pop(combo_name)

    def reload_variables(self, cls: Mod, widgets: Widgets):
        """Reload all variables associated with a mod.
        Note that this will not work for changing an existing variables' type.
        To do this, remove (comment out) the property, reload the mod, and then uncomment, change the type and
        reload again to have it add it back.
        """
        variable_widgets = widgets["variables"]

        existing_variable_names = set([v for v in variable_widgets.keys()])
        mod_variable_names = set([v for v in cls._gui_variables.keys()])

        new_variables = mod_variable_names - existing_variable_names
        for variable_name in new_variables:
            self.add_variable(cls, variable_name, cls._gui_variables[variable_name])

        remaining_variables = existing_variable_names & mod_variable_names
        for variable_name in remaining_variables:
            # Loop over the text and variable ids so we may update them.
            for var_id, var_type in variable_widgets[variable_name]:
                if var_type == WidgetType.TEXT:
                    dpg.set_value(var_id, cls._gui_variables[variable_name]._label_text)
                else:
                    dpg.configure_item(var_id, user_data=(cls, variable_name))

        removed_variables = existing_variable_names - mod_variable_names
        for variable_name in removed_variables:
            # Remove the variable itself which dpg uses to store the value, as well as all widgets (text and
            # inputs) associated with it.
            name = cls.__class__.__name__
            tag = f"{name}.{variable_name}"
            dpg.delete_item(tag)
            for var_id, _ in variable_widgets[variable_name]:
                dpg.delete_item(var_id)
            variable_widgets.pop(variable_name)

    def add_tab(self, cls: Mod):
        """Add the mod as a new tab in the GUI."""
        # Check to see if the `no_gui` decorator has been applied to the class.
        # If so, don't add it now.
        if getattr(cls, "_no_gui", False) is True:
            return

        name = cls.__class__.__name__
        cls.pymhf_gui = self

        tab = dpg.add_tab(label=name, tag=name, parent="tabbar")
        tab_alias = dpg.get_alias_id(tab)
        dpg.set_item_user_data(name, cls)
        self.tabs[tab_alias] = name
        self.widgets[name] = {
            "buttons": {},
            "variables": {},
            "comboboxes": {},
        }

        dpg.add_button(
            label="Reload Mod",
            callback=self.mod_manager._gui_reload,
            user_data=(cls._mod_name, self),
            parent=name,
        )

        dpg.add_separator(parent=name)

        for _button in cls._gui_buttons.values():
            self.add_button(_button)

        for _combobox in cls._gui_comboboxes.values():
            self.add_combobox(_combobox)

        for variable_name, getter in cls._gui_variables.items():
            self.add_variable(cls, variable_name, getter)

    def change_tab(self, sender: str, app_data: int):
        self._current_tab = self.tabs[app_data]

    def add_window(self):
        with dpg.window(
            label="pyMHF",
            width=int(600 * self.scale),
            height=int(800 * self.scale),
            tag="pyMHF",
            on_close=self.exit,
        ):
            dpg.add_tab_bar(tag="tabbar", callback=self.change_tab)

    def add_button(self, callback: ButtonProtocol):
        name = callback.__self__.__class__.__name__
        meth_name = callback.__qualname__
        button = dpg.add_button(label=callback._button_text, callback=callback, parent=name)
        self.widgets[name]["buttons"][meth_name] = button

    def add_combobox(self, callback: ComboBoxProtocol):
        name = callback.__self__.__class__.__name__
        meth_name = callback.__qualname__

        with dpg.group(horizontal=True, parent=name):
            txt_id = dpg.add_text(callback._combobox_text)
            combobox = dpg.add_combo(
                items=callback._items,
                callback=callback,
            )
            self.widgets[name]["comboboxes"][meth_name] = [(txt_id, WidgetType.TEXT)]
            self.widgets[name]["comboboxes"][meth_name].append((combobox, WidgetType.COMBOBOX))

    def add_variable_gui_elements(self, cls: Mod, variable: str, getter: VariableProtocol):
        name = cls.__class__.__name__
        tag = f"{name}.{variable}"

        def on_update(_, app_data, user_data):
            setattr(user_data[0], user_data[1], app_data)

        with dpg.group(horizontal=True, parent=name):
            input_id = None
            txt_id = dpg.add_text(getter._label_text)
            self.widgets[name]["variables"][variable] = [(txt_id, WidgetType.TEXT)]
            if getter._has_setter:
                if getter._variable_type == VariableType.INTEGER:
                    extra_args = {"on_enter": False}
                    extra_args.update(getter._extra_args)
                    input_id = dpg.add_input_int(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        **extra_args,
                    )
                elif getter._variable_type == VariableType.STRING:
                    extra_args = {"on_enter": False}
                    extra_args.update(getter._extra_args)
                    input_id = dpg.add_input_text(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        **extra_args,
                    )
                elif getter._variable_type == VariableType.FLOAT:
                    extra_args = {"on_enter": False}
                    extra_args.update(getter._extra_args)
                    input_id = dpg.add_input_double(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        **extra_args,
                    )
                elif getter._variable_type == VariableType.BOOLEAN:
                    extra_args = {}
                    extra_args.update(getter._extra_args)
                    input_id = dpg.add_checkbox(
                        source=tag,
                        callback=on_update,
                        user_data=(cls, variable),
                        **extra_args,
                    )
                if input_id is not None:
                    self.widgets[name]["variables"][variable].append((input_id, WidgetType.VARIABLE))
            else:
                txt_id = dpg.add_text(source=tag)
                self.widgets[name]["variables"][variable].append((txt_id, WidgetType.TEXT))

    def add_variable(self, cls: Mod, variable: str, getter: VariableProtocol):
        name = cls.__class__.__name__
        tag = f"{name}.{variable}"
        value = getattr(cls, variable)
        with dpg.value_registry():
            # If there is no setter, the value type has to be a string
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
        if name not in self.tracking_variables:
            self.tracking_variables[name] = []
        self.tracking_variables[name].append(
            (
                tag,
                cls,
                variable,
                getter._variable_type == VariableType.STRING or not getter._has_setter,
            )
        )

    def remove_tab(self, cls: Mod):
        """Remove the tab associated with the provided class."""
        name = cls.__class__.__name__
        self.tabs.pop(dpg.get_alias_id(name))
        dpg.delete_item(name)

    def run(self):
        try:
            dpg.show_viewport()
            dpg.set_primary_window(WINDOW_TITLE, True)
            self.hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
            self._current_tab = list(self.tabs.values())[0]
            while dpg.is_dearpygui_running():
                # For each tracking variable, update the value.
                for vars in self.tracking_variables.get(self._current_tab, []):
                    tag, cls, var, is_str = vars
                    if is_str:
                        dpg.set_value(tag, str(getattr(cls, var)))
                    else:
                        dpg.set_value(tag, getattr(cls, var))
                dpg.render_dearpygui_frame()
            dpg.destroy_context()
        except Exception:
            logger.exception("Unable to create GUI window!")

    def exit(self):
        dpg.stop_dearpygui()
