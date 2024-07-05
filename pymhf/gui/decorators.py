from typing import Any, Optional, Callable

from pymhf.gui.protocols import ButtonProtocol, VariableProtocol, VariableType


def gui_button(text: str):
    def inner(func) -> ButtonProtocol:
        func._is_button = True
        func._button_text = text
        return func
    return inner


def no_gui(cls):
    """ Mark the mod as not requiring a tab in the gui. """
    setattr(cls, "_no_gui", True)
    return cls


class gui_variable:
    @staticmethod
    def _set_default_attributes(func: Callable[..., Any], label: Optional[str] = None):
        func._is_variable = True
        func._label_text = label
        func._has_setter = False

    @classmethod
    def INTEGER(cls, label: Optional[str] = None):
        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.INTEGER
            return func
        return inner

    @classmethod
    def STRING(cls, label: Optional[str] = None):
        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.STRING
            return func
        return inner

    @classmethod
    def FLOAT(cls, label: Optional[str] = None):
        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.FLOAT
            return func
        return inner

    @classmethod
    def BOOLEAN(cls, label: Optional[str] = None):
        def inner(func: Callable[..., Any]) -> VariableProtocol:
            gui_variable._set_default_attributes(func, label)
            func._variable_type = VariableType.BOOLEAN
            return func
        return inner


INTEGER = gui_variable.INTEGER
BOOLEAN = gui_variable.BOOLEAN
STRING = gui_variable.STRING
FLOAT = gui_variable.FLOAT
