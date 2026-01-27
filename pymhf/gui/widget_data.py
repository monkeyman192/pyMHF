from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, Optional, Protocol, Type, TypeVar, Union

if TYPE_CHECKING:
    from pymhf.gui.widgets import Widget


class GroupData(NamedTuple):
    # group_id is auto-generated
    group_id: str
    group_label: Optional[str]

    @property
    def indentation(self) -> int:
        return len(self.group_id.split("."))


ctx_group = ContextVar[Optional[GroupData]]("group", default=None)
ctx_group.set(None)
ctx_group_counter = ContextVar[int]("group_counter", default=0)
ctx_group_counter.set(0)


class WidgetType(Enum):
    NONE = -1
    BUTTON = 0
    VARIABLE = 1
    TEXT = 2
    CUSTOM = 3


class VariableType(Enum):
    NONE = -1
    INTEGER = 0
    FLOAT = 1
    STRING = 2
    BOOLEAN = 3
    ENUM = 4
    CUSTOM = 5


# Widget data - This is the info that we provide from the decorator and bind to our decorated function.


class WidgetData:
    def __init__(self, id_: str, label: str):
        self.id_ = id_
        self.label = label
        self.group = ctx_group.get()
        self.widget_type = WidgetType.NONE

    def asdict(self):
        return {"label": self.label}


class CustomWidgetData(WidgetData):
    def __init__(
        self,
        id_: str,
        label: str,
        widget_cls: "Widget",
    ):
        super().__init__(id_, label)
        self.widget_type = WidgetType.CUSTOM
        self.widget_cls = widget_cls
        self.is_property = False
        self.has_setter = False

    def asdict(self):
        return super().asdict()


class GroupWidgetData(WidgetData):
    def __init__(
        self,
        id_: str,
        label: Optional[str],
        child_widgets: list[Union["GUIElementProtocol[WidgetData]", "GroupWidgetData"]],
    ):
        super().__init__(id_, label or "")
        self.child_widgets = child_widgets

    def asdict(self):
        children = []
        for child in self.child_widgets:
            if isinstance(child, WidgetData):
                children.append(child.asdict())
            else:
                children.append(child)
        return {"id_": self.id_, "label": self.label, "child_widgets": children}


class ButtonWidgetData(WidgetData):
    def __init__(self, id_: str, label: str):
        super().__init__(id_, label)
        self.widget_type = WidgetType.BUTTON

    def asdict(self):
        return {**super().asdict()}


class VariableWidgetData(WidgetData):
    def __init__(
        self,
        id_: str,
        label: str,
        variable_type: VariableType = VariableType.NONE,
        is_slider: bool = False,
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label)
        self.variable_type = variable_type
        self.has_setter = False
        self.is_slider = is_slider
        self.extra_args = extra_args
        self.widget_type = WidgetType.VARIABLE

    def asdict(self):
        return {
            **super().asdict(),
            "variable_type": self.variable_type,
            "has_setter": self.has_setter,
            "is_slider": self.is_slider,
            "extra_args": self.extra_args,
        }


class EnumVariableWidgetData(VariableWidgetData):
    def __init__(
        self,
        id_: str,
        label: str,
        enum: Type[Enum],
        extra_args: Optional[dict] = None,
    ):
        super().__init__(id_, label, VariableType.ENUM, False, extra_args)
        self.enum = enum

    def asdict(self):
        return {
            **super().asdict(),
            "enum": self.enum,
        }


WD = TypeVar("WD", bound=WidgetData, covariant=True)


class GUIElementProtocol(Generic[WD], Protocol):
    """Base protocol for all GUI elements."""

    # All the widget data is contained within this object.
    _widget_data: WD

    @property
    def __self__(self) -> Type: ...

    @property
    def __name__(self) -> str: ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
