import ctypes
import logging
import os.path as op
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TypedDict, Union, cast

import dearpygui.dearpygui as dpg
import win32gui

import pymhf.core._internal as _internal
import pymhf.core.caching as cache
from pymhf.core._types import pymhfConfig
from pymhf.core.mod_loader import Mod, ModManager
from pymhf.gui.hexview import HexView
from pymhf.gui.widget_data import (
    ButtonWidgetData,
    CustomWidgetData,
    GroupWidgetData,
    GUIElementProtocol,
    VariableType,
    VariableWidgetData,
    WidgetData,
)
from pymhf.gui.widgets import CustomWidget, Group, Variable, Widget
from pymhf.utils.winapi import set_window_transparency

SETTINGS_NAME = "_pymhf_gui_settings"
HEX_NAME = "_pymhf_gui_hex"
DETAILS_NAME = "_pymhf_gui_details"
WINDOW_TITLE = "pyMHF"

FONT_DIR = op.join(op.dirname(__file__), "fonts")

# TODO:
# - add keyboard shortcut to show or hide the GUI
# - Add support for mod states


logger = logging.getLogger(__name__)
rootLogger = logging.getLogger("")


@dataclass
class VariableData:
    mod: Mod
    variable_name: str
    variable_type: VariableType
    has_setter: bool


class Widgets(TypedDict):
    buttons: dict[str, GUIElementProtocol[ButtonWidgetData]]
    variables: dict[str, GUIElementProtocol[VariableWidgetData]]


class WidgetDiff(TypedDict):
    type: str


def toggle_on_top(item: int, value: bool):
    dpg.set_viewport_always_top(value)


def get_id(widget: Union[GUIElementProtocol[WidgetData], GroupWidgetData]) -> str:
    if isinstance(widget, GroupWidgetData):
        return widget.id_
    else:
        return widget._widget_data.id_


class GUI:
    hex_view: HexView

    def __init__(self, mod_manager: ModManager, config: pymhfConfig):
        self.config = config
        self.always_on_top = config.get("gui", {}).get("always_on_top", False)
        self.is_debug = config.get("logging", {}).get("log_level") == "debug"
        self.scale = config.get("gui", {}).get("scale", 1)
        dpg.create_context()
        dpg.create_viewport(
            title=WINDOW_TITLE,
            width=int(800 * self.scale),
            height=int(800 * self.scale),
            decorated=True,
            always_on_top=self.always_on_top,
        )
        dpg.setup_dearpygui()

        with dpg.font_registry():
            self.default_font = dpg.add_font(op.join(FONT_DIR, "JetBrainsMono[wght].ttf"), 32)

        self.tracking_variables: dict[str, dict[str, VariableData]] = defaultdict(lambda: {})
        self.redrawing_widgets: dict[str, dict[str, CustomWidget]] = defaultdict(lambda: {})
        self.broken_widgets: dict[str, list[VariableData]] = {}
        self.tabs: dict[Union[int, str], str] = {}
        self._shown = True
        self._handle = None
        self._current_tab = ""
        self.mod_manager = mod_manager

        self.widget_data: dict[str, list[Union[GUIElementProtocol[WidgetData], GroupWidgetData]]] = {}
        self.widget_mapping: dict[str, dict[str, Widget]] = {}

        self.collapsing_header_theme = dpg.add_theme()
        collapsing_header_theme_component = dpg.add_theme_component(
            dpg.mvCollapsingHeader, parent=self.collapsing_header_theme
        )
        dpg.add_theme_color(
            dpg.mvThemeCol_WindowBg, [100, 50, 150, 255], parent=collapsing_header_theme_component
        )
        # dpg.add_theme_color(
        #     dpg.mvThemeCol_ChildBg,
        #     [150, 150, 150, 255],
        #     parent=collapsing_header_theme_component
        # )

        # Keep track of the viewport dimensions and position.
        # NOTE: These are ONLY updated when the viewport is minimised by the `hide_window` method.
        # TODO: Maybe set a max height and width?
        self._window_dimensions = [0, 0]
        self._window_position: list[float] = [0, 0]

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
        if "logging" in self.config:
            self.config["logging"]["log_level"] = is_debug and "debug" or "info"
        else:
            self.config["logging"] = {"log_level": is_debug and "debug" or "info"}

        if is_debug:
            rootLogger.setLevel(logging.DEBUG)
        else:
            rootLogger.setLevel(logging.INFO)

    def toggle_show_gui(self, _sender, show_gui):
        if "gui" in self.config:
            self.config["gui"]["shown"] = show_gui
        else:
            self.config["gui"] = {"shown": show_gui}

    def add_hex_tab(self):
        dpg.add_tab(label="Hex View", tag=HEX_NAME, parent="tabbar")
        tab_alias = dpg.get_alias_id(HEX_NAME)
        self.tabs[tab_alias] = HEX_NAME

        self.hex_view = HexView(HEX_NAME)
        self.hex_view._setup()

    def add_settings_tab(self):
        """Add a settings tab to configure the gui and other things."""
        with dpg.value_registry():
            dpg.add_bool_value(tag="always_on_top", default_value=self.always_on_top)
            dpg.add_bool_value(tag="is_debug", default_value=self.is_debug)
            dpg.add_bool_value(tag="show_gui", default_value=True)
        dpg.add_tab(label="Settings", tag=SETTINGS_NAME, parent="tabbar")
        tab_alias = dpg.get_alias_id(SETTINGS_NAME)
        self.tabs[tab_alias] = SETTINGS_NAME

        with dpg.table(
            header_row=False,
            parent=SETTINGS_NAME,
            no_pad_innerX=True,
            width=-1,
        ):
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
                    min_value=0.25,
                    callback=self.alpha_callback,
                    width=-1,
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
        dpg.add_tab(label="Details", tag=DETAILS_NAME, parent="tabbar")
        tab_alias = dpg.get_alias_id(DETAILS_NAME)
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

    def reload_tab(self, mod: Mod):
        """Reload the tab for the specific mod."""
        mod_name = mod._mod_name
        mod.pymhf_gui = self
        widgets = self.widget_data.pop(mod_name, [])

        changes, deletions = self.diff_widgets(widgets, mod._gui_widgets)

        # Handle the deletes first.
        for line in deletions:
            self.handle_diff_row(mod, line)

        # Then any changes.
        for line in changes:
            self.handle_diff_row(mod, line)

        self.widget_data[mod_name] = mod._gui_widgets

    def diff_widgets(
        self,
        old_widgets: list[Union[GUIElementProtocol[WidgetData], GroupWidgetData]],
        new_widgets: list[Union[GUIElementProtocol[WidgetData], GroupWidgetData]],
        parent: Optional[str] = None,
    ) -> tuple[list[dict], list[dict]]:
        # Calculate the diff between the old widgets and the new widgets
        changes = []
        deletions = []
        old_widget_map = {get_id(x): x for x in old_widgets}
        removed_widgets = set(old_widget_map.keys()) - set(get_id(x) for x in new_widgets)

        # Loop over the new widgets and compare to the old ones.
        prev_existing_widget = None
        for widget in new_widgets:
            widget_id = get_id(widget)
            # Check to see if the previous result is a new widget and inject our own id so it knows what it is
            # before.
            if changes and "surrounding_widgets" in changes[-1]:
                changes[-1]["surrounding_widgets"]["before"] = widget_id
            # If there is an existing old widget we're going to just change its configuration.
            if (old_widget := old_widget_map.get(widget_id)) is not None:
                # For group widgets we need to get a sub diff (recursively)
                if isinstance(widget, GroupWidgetData):
                    old_widget = cast(GroupWidgetData, old_widget)
                    sub_changes, sub_deletions = self.diff_widgets(
                        old_widget.child_widgets,
                        widget.child_widgets,
                        old_widget.id_,
                    )
                    changes.append(
                        {
                            "type": "change",
                            "old": old_widget.id_,
                            "new": widget,
                            "children": {"changes": sub_changes, "deletions": sub_deletions},
                        }
                    )
                # Otherwise we just write the plain change.
                elif isinstance(widget._widget_data, CustomWidgetData):
                    # TODO: Potentially make this smarter to use the reload method if there is one.
                    # For now, we will remove the widget and then redraw it.
                    deletions.append({"type": "remove", "old": widget_id})
                    changes.append(
                        {
                            "type": "add",
                            "new": widget,
                            "surrounding_widgets": {
                                "after": prev_existing_widget,
                                "before": None,
                                "parent": parent,
                            },
                        }
                    )
                else:
                    # Other types we generally just pass the old and new data and let the handler handle it.
                    # The one exception is for variables when their type changes.
                    # We could handle this at least partially, but it's much simpler to just delete and add
                    # the variable again as a different type.
                    # We also do the same if the WidgetData type changes too since there are too many ways
                    # this could break...
                    if isinstance(old_widget, GroupWidgetData):
                        logger.warning(
                            "A widget was somehow changed from a group to an actual widget. This will be "
                            "ignored."
                        )
                        continue
                    delete_redraw = False
                    if type(old_widget._widget_data) is not type(widget._widget_data):
                        delete_redraw = True
                    elif (
                        isinstance(old_widget._widget_data, VariableWidgetData)
                        and isinstance(widget._widget_data, VariableWidgetData)
                    ) and (old_widget._widget_data.variable_type != widget._widget_data.variable_type):
                        delete_redraw = True

                    if delete_redraw:
                        deletions.append({"type": "remove", "old": widget_id})
                        changes.append(
                            {
                                "type": "add",
                                "new": widget,
                                "surrounding_widgets": {
                                    "after": prev_existing_widget,
                                    "before": None,
                                    "parent": parent,
                                },
                            }
                        )
                    else:
                        changes.append({"type": "change", "old": get_id(old_widget), "new": widget})
                prev_existing_widget = widget_id
            # If the widget doesn't exist in the old set then we add it as a new widget.
            else:
                changes.append(
                    {
                        "type": "add",
                        "new": widget,
                        "surrounding_widgets": {
                            "after": prev_existing_widget,
                            "before": None,
                            "parent": parent,
                        },
                    }
                )
                prev_existing_widget = widget_id
        # Finally, delete all the old widgets which don't exist any more.
        for widget_id in removed_widgets:
            deletions.append({"type": "remove", "old": widget_id})

        return changes, deletions

    def handle_diff_row(self, mod: Mod, line: dict):
        mod_name = mod._mod_name
        widget_mapping = self.widget_mapping[mod_name]
        if line["type"] == "remove":
            if (widget := widget_mapping.get(line["old"])) is not None:
                widget.remove()
                # Try remove the widget from any tracking or redrawing data.
                self.tracking_variables[mod_name].pop(widget.id_, None)
                self.redrawing_widgets[mod_name].pop(widget.id_, None)
        elif line["type"] == "change":
            if (widget := widget_mapping.get(line["old"])) is not None:
                if "children" in line:
                    cast(Group, widget).reload(mod, line["new"], line["children"], self)
                else:
                    widget.reload(mod, line["new"])
                    # Update the mod instance pointed to by the tracking variables.
                    if widget.id_ in self.tracking_variables[mod_name]:
                        widget_data = cast(VariableWidgetData, line["new"]._widget_data)
                        tracking_data = self.tracking_variables[mod_name][widget.id_]
                        tracking_data.mod = mod
                        tracking_data.has_setter = widget_data.has_setter
                        tracking_data.variable_name = cast(Variable, widget).variable_name
                        tracking_data.variable_type = widget_data.variable_type

        elif line["type"] == "add":
            widget = Widget.create(line["new"], widget_mapping)
            widget._draw(widget_mapping, surrounding_widgets=line["surrounding_widgets"])
            # Add the new widget to the tracking or redrawing data if required.
            if isinstance(widget, Variable) or isinstance(widget, CustomWidget):
                self.tracking_variables[mod_name][widget.id_] = VariableData(
                    mod,
                    widget.variable_name,
                    widget.variable_type,
                    widget.has_setter,
                )
                if isinstance(widget, CustomWidget):
                    self.redrawing_widgets[mod_name][widget.id_] = widget

    def add_tab(self, mod: Mod):
        """Add the mod as a new tab in the GUI."""
        # Check to see if the `no_gui` decorator has been applied to the class.
        # If so, don't add it now.
        if getattr(mod, "_no_gui", False) is True:
            return

        mod_name = mod._mod_name
        mod.pymhf_gui = self

        dpg.add_tab(label=mod_name, tag=mod_name, parent="tabbar")
        tab_alias = dpg.get_alias_id(mod_name)
        dpg.set_item_user_data(mod_name, mod)
        self.tabs[tab_alias] = mod_name
        self.widget_mapping[mod_name] = {}

        dpg.add_button(
            label="Reload Mod",
            callback=self.mod_manager._gui_reload,
            user_data=(mod._mod_name, self),
            parent=mod_name,
        )

        dpg.add_separator(parent=mod_name)

        # Push the mod name to the container stack so that we can draw everthing under it.
        dpg.push_container_stack(mod_name)

        # Go over all the widget data and create the actual widget instances for the gui.
        self.widget_data[mod_name] = mod._gui_widgets
        widget_mapping = self.widget_mapping[mod_name]
        for func in mod._gui_widgets:
            widget = Widget.create(func, widget_mapping)
            widget._draw(widget_mapping)
        dpg.pop_container_stack()

        # Parse the widgets and extract any tracking info out.
        for widget_id, widget in self.widget_mapping[mod_name].items():
            if isinstance(widget, Variable) or isinstance(widget, CustomWidget):
                self.tracking_variables[mod_name][widget_id] = VariableData(
                    mod,
                    widget.variable_name,
                    widget.variable_type,
                    widget.has_setter,
                )
                if isinstance(widget, CustomWidget):
                    self.redrawing_widgets[mod_name][widget_id] = widget

    def change_tab(self, _: str, app_data: int):
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

    def remove_tab(self, mod: Mod):
        """Remove the tab associated with the provided class."""
        name = mod.__class__.__name__
        self.tabs.pop(dpg.get_alias_id(name))
        dpg.delete_item(name)

    def run(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            dpg.bind_font(self.default_font)
            dpg.show_viewport()
            dpg.set_primary_window(WINDOW_TITLE, True)
            self.hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
            if self.tabs:
                self._current_tab = list(self.tabs.values())[0]
            while dpg.is_dearpygui_running():
                # For each tracking variable, update the value.
                for tag, vars in self.tracking_variables.get(self._current_tab, {}).items():
                    if vars in self.broken_widgets.get(self._current_tab, []):
                        continue
                    try:
                        # Handle custom widgets first since they may also satisfy the other conditions.
                        if vars.variable_type == VariableType.CUSTOM:
                            # Call redraw on the widget.
                            values = getattr(vars.mod, vars.variable_name)
                            widget = self.redrawing_widgets[self._current_tab][tag]
                            res = widget.redraw(**values)
                            # If we get a return value from redraw and the property has a setter, pass the
                            # value through to complete the cycle.
                            if vars.has_setter and res:
                                setattr(vars.mod, vars.variable_name, res)
                        # Enum with setter.
                        elif vars.variable_type == VariableType.ENUM and vars.has_setter:
                            val = cast(Enum, getattr(vars.mod, vars.variable_name))
                            dpg.set_value(tag, val.name)
                        # Read-only variable.
                        elif vars.variable_type == VariableType.STRING or not vars.has_setter:
                            dpg.set_value(tag, repr(getattr(vars.mod, vars.variable_name)))
                        # "Normal" variable.
                        else:
                            dpg.set_value(tag, getattr(vars.mod, vars.variable_name))
                    except Exception:
                        # If we can't set the value, don't crash the whole program.
                        logger.exception(
                            f"There was an exception handling the variable {vars.variable_name}. It will be "
                            "removed from the pool of variables which get updated."
                        )
                        if self._current_tab not in self.broken_widgets:
                            self.broken_widgets[self._current_tab] = []
                        self.broken_widgets[self._current_tab].append(vars)
                dpg.render_dearpygui_frame()
            dpg.destroy_context()
        except Exception:
            logger.exception("Unable to create GUI window!")

    def exit(self):
        dpg.stop_dearpygui()
