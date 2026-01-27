from abc import ABC, abstractmethod
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Type, TypedDict, Union, cast

import dearpygui.dearpygui as dpg

from pymhf.gui.widget_data import (
    ButtonWidgetData,
    CustomWidgetData,
    EnumVariableWidgetData,
    GroupWidgetData,
    GUIElementProtocol,
    VariableType,
    VariableWidgetData,
    WidgetData,
)

if TYPE_CHECKING:
    from pymhf.core.mod_loader import Mod
    from pymhf.gui.gui import GUI

INDENT = 32


class WidgetSurrounds(TypedDict, total=False):
    """Simple container for info about the surrounding widgets."""

    after: Optional[str]
    before: Optional[str]
    parent: Optional[str]


class WidgetBehaviour(Enum):
    UNDEFINED = -1
    CONTINUOUS = 0
    SEPARATE = 1


class Widget(ABC):
    widget_behaviour: WidgetBehaviour

    def __init__(self, id_: str):
        self.ids: dict[str, Union[int, str]] = {}
        self.id_ = id_
        # This is the root DearPyGUI id of the widget. It will be either the group containing the widget, or
        # the id of the row depending on the widget behaviour.
        self._root_dpg_id = 0
        if (
            not hasattr(self, "widget_behaviour")
            or getattr(self, "widget_behaviour") == WidgetBehaviour.UNDEFINED
        ):
            raise TypeError(
                f"Widget {self.__class__.__qualname__!r} does not have a valid widget_behaviour defined."
            )

    @staticmethod
    def _get_parent_table(item: Union[str, int, None] = None):
        """Get the first table containing the current widget."""
        if not item:
            return None
        item_ = item
        while True:
            if parent := dpg.get_item_info(item_).get("parent"):
                if dpg.get_item_info(parent).get("type") == "mvAppItemType::mvTable":
                    return parent
                item_ = parent
            return None

    @contextmanager
    def handle_widget_behaviour(
        self,
        widget_mapping: dict[str, "Widget"],
        surrounding_widgets: Optional[WidgetSurrounds] = None,
    ):
        """Based on the widget behaviour, clean up from the previous widgets, or attach to them, and then
        retrn some (optional) extra information which may be required later.
        """
        extra = {}
        manual_parent_id = None
        if self.widget_behaviour == WidgetBehaviour.CONTINUOUS:
            after_dpg_id = 0
            parent_dpg_id = 0
            before = None
            after = None
            parent = None
            if surrounding_widgets:
                before = surrounding_widgets.get("before")
                after = surrounding_widgets.get("after")
                parent = surrounding_widgets.get("parent")
            if before is not None:
                # Lookup the widget.
                if (before_widget := widget_mapping.get(before)) is not None:
                    extra["before"] = before_widget._root_dpg_id
            if after is not None:
                if (after_widget := widget_mapping.get(after)) is not None:
                    after_dpg_id = after_widget._root_dpg_id
            if parent is not None:
                if (parent_widget := widget_mapping.get(parent)) is not None:
                    parent_dpg_id = parent_widget._root_dpg_id

            self._join_or_create_new_table(after_dpg_id, parent_dpg_id)
        elif self.widget_behaviour == WidgetBehaviour.SEPARATE:
            self._force_end_table()
            if surrounding_widgets:
                if (before := surrounding_widgets.get("before")) is not None:
                    # Lookup the widget.
                    if (before_widget := widget_mapping.get(before)) is not None:
                        extra["before"] = Widget._get_parent_table(before_widget._root_dpg_id)
                # Check to see if we have a specific parent (eg. a group) and push it to the stack if so.
                if (parent := surrounding_widgets.get("parent")) is not None:
                    if (parent_widget := widget_mapping.get(parent)) is not None:
                        if manual_parent_id := parent_widget._root_dpg_id:
                            dpg.push_container_stack(manual_parent_id)
        yield extra
        # Now do clean up if required
        if self.widget_behaviour == WidgetBehaviour.SEPARATE:
            if manual_parent_id:
                # Remove it from the stack. This may be wasteful but it is much simpler than trying to keep it
                # around just in case something else needs it.
                if manual_parent_id == dpg.top_container_stack():
                    dpg.pop_container_stack()

    def _join_or_create_new_table(self, after: int, parent: int):
        prev_type = None

        # Check the top of the stack and get its' type.
        if top_stack := dpg.top_container_stack():
            prev_type = dpg.get_item_info(top_stack).get("type")
        # If the top of the stack is a table, then we just add directly to it.
        if prev_type == "mvAppItemType::mvTable":
            return
        else:
            if after:
                # Find the table which contained the last object and push it to the stack.
                if parent_table := Widget._get_parent_table(after):
                    dpg.push_container_stack(parent_table)
                    return
            if parent:
                dpg.push_container_stack(parent)
            # If we get there then we either don't have an previous items, or they don't belong to a table, so
            # we create one.
            table = dpg.add_table(
                show=True,
                header_row=False,
                borders_outerH=False,
                borders_outerV=False,
                borders_innerV=False,
                borders_innerH=False,
                width=-1,
            )
            dpg.push_container_stack(table)
            dpg.add_table_column()
            dpg.add_table_column()

    def _force_end_table(self):
        if top_stack := dpg.top_container_stack():
            item_info = dpg.get_item_info(top_stack)
            if item_info["type"] == "mvAppItemType::mvTable":
                # Remove the previous table from the container stack.
                dpg.pop_container_stack()

    @classmethod
    def create(
        cls,
        func: Union[GUIElementProtocol[WidgetData], GroupWidgetData],
        widget_mapping: dict[str, "Widget"],
    ):
        if isinstance(func, GroupWidgetData):
            data = func
        else:
            data = func._widget_data
        widget_id = data.id_
        """ Create an instance based on the widget data passed in and register it with the widget mapping. """
        widget = None
        if isinstance(data, ButtonWidgetData):
            widget = Button(widget_id, data.label, cast(GUIElementProtocol[ButtonWidgetData], func))
        elif isinstance(data, VariableWidgetData):
            func = cast(GUIElementProtocol[WidgetData], func)
            # Extract all the info we need and then pass it into the various constructors.
            dict_data = data.asdict()
            label = dict_data["label"]
            has_setter = dict_data.get("has_setter", False)
            extra_args = dict_data.get("extra_args", {})
            is_slider = dict_data.get("is_slider", False)
            mod = cast("Mod", func.__self__)
            variable_name = func.__name__

            if data.variable_type == VariableType.INTEGER:
                widget = IntVariable(widget_id, label, mod, variable_name, has_setter, is_slider, extra_args)
            elif data.variable_type == VariableType.FLOAT:
                widget = FloatVariable(
                    widget_id,
                    label,
                    mod,
                    variable_name,
                    has_setter,
                    is_slider,
                    extra_args,
                )
            elif data.variable_type == VariableType.BOOLEAN:
                widget = BoolVariable(widget_id, label, mod, variable_name, has_setter, extra_args)
            elif data.variable_type == VariableType.STRING:
                widget = StringVariable(widget_id, label, mod, variable_name, has_setter, extra_args)
            elif data.variable_type == VariableType.ENUM:
                data = cast(EnumVariableWidgetData, data)
                widget = EnumVariable(widget_id, label, mod, variable_name, data.enum, has_setter, extra_args)
        elif isinstance(data, GroupWidgetData):
            child_widgets: list[Widget] = []
            for cw in data.child_widgets:
                if (widget := Widget.create(cw, widget_mapping)) is not None:
                    child_widgets.append(widget)
            widget = Group(widget_id, data.label, child_widgets)
        elif isinstance(data, CustomWidgetData):
            func = cast(GUIElementProtocol[CustomWidgetData], func)
            widget = cast(CustomWidget, data.widget_cls)
            # Set the widget id as it won't have been set
            widget.id_ = widget_id
            widget._set_property_values(cast("Mod", func.__self__), func.__name__, data.has_setter)
        else:
            raise TypeError(f"Unknown widget type: {type(data)}")
        if not widget:
            raise TypeError(f"Unknown widget type: {type(data)}")
        widget_mapping[widget_id] = widget
        return widget

    def _draw(
        self,
        widget_mapping: dict[str, "Widget"],
        surrounding_widgets: Optional[WidgetSurrounds] = None,
    ):
        # This is the actual draw entry point.
        # It will wrap the draw call so that the widget behaviour is respected and any extra data is applied.
        with self.handle_widget_behaviour(widget_mapping, surrounding_widgets) as extra:
            if self.widget_behaviour == WidgetBehaviour.SEPARATE:
                with dpg.group(**extra) as grp:
                    self._root_dpg_id = grp
                    if isinstance(self, Group):
                        self.draw(widget_mapping)
                    else:
                        self.draw()
            else:
                with dpg.table_row(**extra) as row:
                    self._root_dpg_id = row
                    self.draw()

    @abstractmethod
    def draw(self):
        """This is the main draw command which will be called once when the widget it to be drawn for the
        first time. This should create any DearPyGUI widgets which are to be drawn as part of this, as well
        as creating any variables and binding any callbacks."""
        pass

    @abstractmethod
    def reload(self, mod: "Mod", new_widget: GUIElementProtocol[WidgetData]):
        pass

    def remove(self):
        # Auto-delete all the dpg widgets associated with this custom widget.
        # We can simply delete the root id and it will cascade and delete all children, however, in the off
        # chance that this is None, fallback to deleting all the widgets manually.
        if self._root_dpg_id is not None:
            dpg.delete_item(self._root_dpg_id)
        else:
            for widget_id in self.ids.values():
                try:
                    dpg.delete_item(widget_id)
                except SystemError:
                    # We don't care. It may have already been deleted.
                    pass


class CustomWidget(Widget, ABC):
    widget_behaviour = WidgetBehaviour.UNDEFINED
    is_property: bool

    has_setter: bool
    mod: "Mod"
    variable_name: str

    def __init__(self, id_: Optional[str] = None):
        super().__init__(id_ or "")
        self.variable_type = VariableType.CUSTOM

    def __call__(self, func):
        func = cast(GUIElementProtocol, func)
        func._widget_data = CustomWidgetData(func.__qualname__, "", self)
        self.func = func
        return func

    def _set_property_values(self, mod: "Mod", variable_name: str, has_setter: bool = False):
        """Called if this custom widget is a property"""
        self.mod = mod
        self.variable_name = variable_name
        self.has_setter = has_setter

    def reload(self, mod: "Mod", new_widget: GUIElementProtocol[CustomWidgetData]):  # type: ignore
        # It's unlikely any inheriting class will override this, so just implement this and then instead
        # we will remove the instance of the custom widget and draw it again upon reload.
        pass

    @abstractmethod
    def redraw(self, *args: Any, **kwargs: Any) -> Optional[dict[str, Any]]:
        """Redraw the widget. This will be called each frame.
        This method is guaranteed not to be called before the original `draw` method.
        This method can be defined with any number of arguments but the function decorated by this class MUST
        return a dict which doesn't contain any keys which aren't function arguments.
        If this decorated a property which also has a setter, the returned dictionary (if any) is passed into
        that setter by value (ie. it's not spread out - the values must be unpacked from the dictionary
        inside the setter).
        """
        pass


class Group(Widget):
    widget_behaviour = WidgetBehaviour.SEPARATE

    def __init__(self, id_: str, label: Optional[str], child_widgets: Optional[list[Widget]]):
        super().__init__(id_)
        self.label = label
        self.child_widgets = child_widgets or []

    def draw(self, widget_mapping: dict[str, Widget]):  # type: ignore
        if not widget_mapping:
            raise ValueError("widget_mapping must not be None for a Group.")
        with dpg.collapsing_header(
            label=self.label or "",
            default_open=False,
            tag=self.id_,
        ) as ch:
            with dpg.group(indent=INDENT):
                self.dpg_id = ch
                self.ids["SELF"] = ch
                for widget in self.child_widgets:
                    widget._draw(widget_mapping)
                self._force_end_table()

    def reload(  # type: ignore
        self,
        mod: "Mod",
        new_widget: GroupWidgetData,
        new_sub_config: dict[str, list[dict]],
        gui: "GUI",
    ):
        if new_widget.label != self.label:
            dpg.configure_item(
                self.ids["SELF"],
                label=new_widget.label,
            )
        for line in new_sub_config["deletions"]:
            gui.handle_diff_row(mod, line)
        for line in new_sub_config["changes"]:
            gui.handle_diff_row(mod, line)

    def remove(self):
        for widget in self.child_widgets:
            widget.remove()
        super().remove()


class Button(Widget):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(self, id_: str, label: str, callback: GUIElementProtocol):
        super().__init__(id_)
        self.label = label
        self.callback = callback

    def draw(self):
        button_id = dpg.add_button(
            tag=self.id_,
            label=self.label,
            callback=self.callback,
            width=-1,
        )
        self.ids["BUTTON"] = button_id

    def reload(self, mod: "Mod", new_widget: GUIElementProtocol[ButtonWidgetData]):  # type: ignore
        new_config = {}
        widget_data = new_widget._widget_data
        if widget_data.label != self.label:
            new_config["label"] = widget_data.label
        # The callback will ALWAYS change because we have a new instance of the Mod.
        new_config["callback"] = new_widget
        if new_config:
            dpg.configure_item(
                self.ids["BUTTON"],
                **new_config,
            )


class Variable(Widget):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(
        self,
        id_: str,
        label: str,
        mod: "Mod",
        variable_name: str,
        variable_type: VariableType = VariableType.NONE,
        has_setter: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_)
        self.label = label
        self.variable_type = variable_type
        self.has_setter = has_setter
        self.extra_args = extra_args
        self.mod = mod
        self.variable_name = variable_name
        self.initial_value = getattr(self.mod, self.variable_name)

    def update_variable(self, _, app_data, user_data):
        setattr(user_data[0], user_data[1], app_data)

    def draw(self):
        with dpg.value_registry():
            if not self.has_setter:
                dpg.add_string_value(tag=self.id_, default_value=repr(self.initial_value))
            else:
                self._add_variable_value(tag=self.id_, default_value=self.initial_value)

        self.ids["LABEL"] = dpg.add_text(self.label)
        if self.has_setter:
            extra_args: dict[str, Any] = {}
            extra_args.update(self.extra_args or {})
            self.ids["INPUT"] = self._add_editable_field(extra_args)
        else:
            self.ids["TEXT"] = dpg.add_text(source=self.id_)

    def _add_variable_value(self, tag: str, default_value: Any):
        raise NotImplementedError()

    def _add_editable_field(self, extra_args: dict[str, Any]):
        raise NotImplementedError()

    def reload(self, mod: "Mod", new_widget: GUIElementProtocol[VariableWidgetData]):  # type: ignore
        # Update variable label
        widget_data = new_widget._widget_data
        if widget_data.label != self.label:
            dpg.set_value(self.ids["LABEL"], widget_data.label)
        self.mod = mod

        # Handle the case of the variable having a setter change.
        # If it hasn't changed, then we can configure the existing data if it has a setter.
        if widget_data.has_setter != self.has_setter:
            # We need to push the root row element to the stack so that we can draw inside it.
            dpg.push_container_stack(self._root_dpg_id)
            if widget_data.has_setter:
                # Now has a setter:
                dpg.delete_item(self.ids["TEXT"])
                extra_args: dict[str, Any] = {}
                extra_args.update(self.extra_args or {})
                self.ids["INPUT"] = self._add_editable_field(extra_args)
            else:
                dpg.delete_item(self.ids["INPUT"])
                self.ids["TEXT"] = dpg.add_text(source=self.id_)
            self.has_setter = widget_data.has_setter
            dpg.pop_container_stack()
        else:
            if self.has_setter:
                dpg.configure_item(
                    self.ids["INPUT"],
                    user_data=(self.mod, self.variable_name),
                )

    def remove(self):
        super().remove()
        # Delete the value from the registry as well.
        dpg.delete_item(self.id_)


class IntVariable(Variable):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(
        self,
        id_: str,
        label: str,
        mod: "Mod",
        variable_name: str,
        has_setter: bool = False,
        is_slider: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label, mod, variable_name, VariableType.INTEGER, has_setter, extra_args)
        self.is_slider = is_slider

    def _add_variable_value(self, tag: str, default_value: int):
        dpg.add_int_value(tag=tag, default_value=default_value)

    def _add_editable_field(self, extra_args: dict[str, Any]):
        if self.is_slider:
            return dpg.add_slider_int(
                source=self.id_,
                callback=self.update_variable,
                user_data=(self.mod, self.variable_name),
                width=-1,
                **extra_args,
            )
        else:
            extra_args.update({"on_enter": False})
            return dpg.add_input_int(
                source=self.id_,
                callback=self.update_variable,
                user_data=(self.mod, self.variable_name),
                width=-1,
                **extra_args,
            )


class FloatVariable(Variable):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(
        self,
        id_: str,
        label: str,
        mod: "Mod",
        variable_name: str,
        has_setter: bool = False,
        is_slider: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label, mod, variable_name, VariableType.FLOAT, has_setter, extra_args)
        self.is_slider = is_slider

    def _add_variable_value(self, tag: str, default_value: float):
        dpg.add_double_value(tag=tag, default_value=default_value)

    def _add_editable_field(self, extra_args: dict[str, Any]):
        if self.is_slider:
            return dpg.add_slider_double(
                source=self.id_,
                callback=self.update_variable,
                user_data=(self.mod, self.variable_name),
                width=-1,
                **extra_args,
            )
        else:
            extra_args.update({"on_enter": False})
            return dpg.add_input_double(
                source=self.id_,
                callback=self.update_variable,
                user_data=(self.mod, self.variable_name),
                width=-1,
                **extra_args,
            )


class StringVariable(Variable):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(
        self,
        id_: str,
        label: str,
        mod: "Mod",
        variable_name: str,
        has_setter: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label, mod, variable_name, VariableType.FLOAT, has_setter, extra_args)

    def _add_variable_value(self, tag: str, default_value: str):
        dpg.add_string_value(tag=tag, default_value=default_value)

    def _add_editable_field(self, extra_args: dict[str, Any]):
        extra_args.update({"on_enter": False})
        return dpg.add_input_text(
            source=self.id_,
            callback=self.update_variable,
            user_data=(self.mod, self.variable_name),
            width=-1,
            **extra_args,
        )


class BoolVariable(Variable):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(
        self,
        id_: str,
        label: str,
        mod: "Mod",
        variable_name: str,
        has_setter: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label, mod, variable_name, VariableType.BOOLEAN, has_setter, extra_args)

    def _add_variable_value(self, tag: str, default_value: bool):
        dpg.add_bool_value(tag=tag, default_value=default_value)

    def _add_editable_field(self, extra_args: dict[str, Any]):
        return dpg.add_checkbox(
            source=self.id_,
            callback=self.update_variable,
            user_data=(self.mod, self.variable_name),
            **extra_args,
        )


class EnumVariable(Variable):
    widget_behaviour = WidgetBehaviour.CONTINUOUS

    def __init__(
        self,
        id_: str,
        label: str,
        mod: "Mod",
        variable_name: str,
        enum: Type[Enum],
        has_setter: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label, mod, variable_name, VariableType.ENUM, has_setter, extra_args)
        self.enum = enum

    def _add_variable_value(self, tag: str, default_value: Enum):
        dpg.add_string_value(tag=tag, default_value=default_value.name)

    def _add_editable_field(self, extra_args: dict[str, Any]):
        # Get the names of the enum members and convert to a list to bind to the combo box.
        # We also need a specific on_update function for each enum so that we have have the
        # associated enum scoped to the function for casting the value to the enum itself.
        enum_names = [x.name for x in self.enum]

        return dpg.add_combo(
            items=enum_names,
            source=self.id_,
            callback=self.update_variable,
            user_data=(self.mod, self.variable_name),
            width=-1,
            **extra_args,
        )

    def update_variable(self, _, app_data, user_data):
        setattr(user_data[0], user_data[1], getattr(self.enum, app_data, None))
