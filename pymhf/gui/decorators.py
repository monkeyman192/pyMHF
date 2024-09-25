from typing import Any, Callable, Optional

from pymhf.gui.protocols import ButtonProtocol, VariableProtocol, VariableType


def gui_button(text: str):
    def inner(func) -> ButtonProtocol:
        func._is_button = True
        func._button_text = text
        return func

    return inner


def no_gui(cls):
    """Mark the mod as not requiring a tab in the gui."""
    setattr(cls, "_no_gui", True)
    return cls


class gui_variable:
    @staticmethod
    def _set_default_attributes(func: Callable[..., Any], label: Optional[str] = None):
        func._is_variable = True
        func._label_text = label
        func._has_setter = False

    @staticmethod
    def _clean_extra_args(args: dict):
        """Remove any keywords from the args so that they don't override the values we need to provide."""
        args.pop("tag", None)
        args.pop("source", None)
        args.pop("user_data", None)
        args.pop("callback", None)
        args.pop("use_internal_label", None)

    @classmethod
    def INTEGER(cls, label: Optional[str] = None, **extra_args):
        """Create an integer entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation:
        https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_int
        """

        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.INTEGER
            gui_variable._clean_extra_args(extra_args)
            func._extra_args = extra_args
            return func

        return inner

    @classmethod
    def STRING(cls, label: Optional[str] = None, **extra_args):
        """Create an string entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation:
        https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_text
        """

        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.STRING
            gui_variable._clean_extra_args(extra_args)
            func._extra_args = extra_args
            return func

        return inner

    @classmethod
    def FLOAT(cls, label: Optional[str] = None, **extra_args):
        """Create an float entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation:
        https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_input_double
        """

        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.FLOAT
            gui_variable._clean_extra_args(extra_args)
            func._extra_args = extra_args
            return func

        return inner

    @classmethod
    def BOOLEAN(cls, label: Optional[str] = None, **extra_args):
        """Create an string entry field which can take extra arguments.
        To see what extra arguments are available, see the DearPyGUI documentation:
        https://dearpygui.readthedocs.io/en/latest/reference/dearpygui.html#dearpygui.dearpygui.add_checkbox
        """

        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.BOOLEAN
            gui_variable._clean_extra_args(extra_args)
            func._extra_args = extra_args
            return func

        return inner


INTEGER = gui_variable.INTEGER
BOOLEAN = gui_variable.BOOLEAN
STRING = gui_variable.STRING
FLOAT = gui_variable.FLOAT
