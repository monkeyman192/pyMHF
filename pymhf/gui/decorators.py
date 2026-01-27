from contextlib import contextmanager
from enum import Enum
from hashlib import md5
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Optional, Type, Union, cast

from pymhf.gui.widget_data import (
    ButtonWidgetData,
    EnumVariableWidgetData,
    GroupData,
    GUIElementProtocol,
    VariableType,
    VariableWidgetData,
    ctx_group,
    ctx_group_counter,
)

logger = getLogger(__name__)

if TYPE_CHECKING:
    from pymhf.core.mod_loader import Mod


@contextmanager
def gui_group(group_label: Optional[str] = None):
    """Add all the gui elements defined within this context manager to the same group.
    This can be nested to create sub-groups to arbitrary depth."""
    # Generate a group id based on the index of the group in the mod.
    # This can change if the order of a group changes which will mean that if two groups change order they
    # will be deleted and redrawn rather than simply moved, but this is an unlikely case to happen too often.
    group_id = md5(str(ctx_group_counter.get()).encode()).hexdigest()
    ctx_group_counter.set(ctx_group_counter.get() + 1)
    if (curr_ctx_group := ctx_group.get()) is None:
        meta = GroupData(group_id, group_label)
    else:
        meta = GroupData(curr_ctx_group.group_id + "." + group_id, group_label)
    ctx_group.set(meta)
    yield
    ctx_group.set(curr_ctx_group)


def gui_button(label: str):
    def inner(func: Callable[..., Any]) -> GUIElementProtocol[ButtonWidgetData]:
        func = cast(GUIElementProtocol, func)
        func._widget_data = ButtonWidgetData(func.__qualname__, label)
        return func

    return inner


def gui_combobox(label: str, items: Union[list[str], None] = None):
    logger.warning("@gui_combobox is no longer supported. Use @ENUM instead to bind to an enum or list.")


def no_gui(cls: "Mod"):
    """Mark the mod as not requiring a tab in the gui."""
    cls._no_gui = True
    return cls


class gui_variable:
    @staticmethod
    def _clean_extra_args(args: dict):
        """Remove any keywords from the args so that they don't override the values we need to provide."""
        args.pop("tag", None)
        args.pop("source", None)
        args.pop("user_data", None)
        args.pop("callback", None)
        args.pop("use_internal_label", None)

    @classmethod
    def ENUM(cls, label: str, enum: Type[Enum], **extra_args):
        """Create an enum entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_combo>`__.

        Note: This decorator MUST be applied closer to the decorated function than the ``@property`` decorator
        """

        def inner(func: Callable[..., Any]) -> GUIElementProtocol[EnumVariableWidgetData]:
            func = cast(GUIElementProtocol, func)
            gui_variable._clean_extra_args(extra_args)
            func._widget_data = EnumVariableWidgetData(func.__qualname__, label, enum, extra_args)
            return func

        return inner

    @classmethod
    def INTEGER(cls, label: str, is_slider: bool = False, **extra_args):
        """Create an integer entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_int>`__.
        If ``is_slider`` is ``True``, a slider will be used to render the widget instead.
        The allowed extra argument for this case can be found
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_slider_int>`__.

        Note: This decorator MUST be applied closer to the decorated function than the ``@property`` decorator
        """

        def inner(func: Callable[..., Any]) -> GUIElementProtocol[VariableWidgetData]:
            func = cast(GUIElementProtocol, func)
            gui_variable._clean_extra_args(extra_args)
            func._widget_data = VariableWidgetData(
                func.__qualname__,
                label,
                VariableType.INTEGER,
                is_slider,
                extra_args,
            )
            return func

        return inner

    @classmethod
    def STRING(cls, label: str, **extra_args):
        """Create a string entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_text>`__.

        Note: This decorator MUST be applied closer to the decorated function than the ``@property`` decorator
        """

        def inner(func: Callable[..., Any]) -> GUIElementProtocol[VariableWidgetData]:
            func = cast(GUIElementProtocol, func)
            gui_variable._clean_extra_args(extra_args)
            func._widget_data = VariableWidgetData(
                func.__qualname__,
                label,
                VariableType.STRING,
                False,
                extra_args,
            )
            return func

        return inner

    @classmethod
    def FLOAT(cls, label: str, is_slider: bool = False, **extra_args):
        """Create a float entry field which can take extra arguments.
        Internally this uses double precision when interfacing with DearPyGUI to minimise loss of accuracy.
        To see what extra arguments are available, see the DearPyGUI documentation
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_double>`__.
        If ``is_slider`` is ``True``, a slider will be used to render the widget instead.
        The allowed extra argument for this case can be found
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_slider_double>`__.

        Note: This decorator MUST be applied closer to the decorated function than the ``@property`` decorator
        """

        def inner(func: Callable[..., Any]) -> GUIElementProtocol[VariableWidgetData]:
            func = cast(GUIElementProtocol, func)
            gui_variable._clean_extra_args(extra_args)
            func._widget_data = VariableWidgetData(
                func.__qualname__,
                label,
                VariableType.FLOAT,
                is_slider,
                extra_args,
            )
            return func

        return inner

    @classmethod
    def BOOLEAN(cls, label: str, **extra_args):
        """Create a boolean entry field in the form of a checkbox which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation
        `here <https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_checkbox>`__.

        Note: This decorator MUST be applied closer to the decorated function than the ``@property`` decorator
        """

        def inner(func: Callable[..., Any]) -> GUIElementProtocol[VariableWidgetData]:
            func = cast(GUIElementProtocol, func)
            gui_variable._clean_extra_args(extra_args)
            func._widget_data = VariableWidgetData(
                func.__qualname__,
                label,
                VariableType.BOOLEAN,
                False,
                extra_args,
            )
            return func

        return inner


INTEGER = gui_variable.INTEGER
BOOLEAN = gui_variable.BOOLEAN
STRING = gui_variable.STRING
FLOAT = gui_variable.FLOAT
ENUM = gui_variable.ENUM
