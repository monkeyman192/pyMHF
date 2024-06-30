from enum import Enum
from typing import Any, Protocol


class VariableType(Enum):
    INTEGER = 0
    FLOAT = 1
    STRING = 2
    BOOLEAN = 3


class ButtonProtocol(Protocol):
    _is_button: bool
    _button_text: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...


class VariableProtocol(Protocol):
    _is_variable: bool
    _variable_type: VariableType
    _label_text: str
    _has_setter: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...
