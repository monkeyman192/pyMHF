from __future__ import annotations

import ctypes
import inspect
import sys
from collections import defaultdict
from collections.abc import Callable
from ctypes import CFUNCTYPE
from dataclasses import dataclass
from logging import getLogger
from typing import (
    Annotated,
    ForwardRef,
    Literal,
    Type,
    Union,
    get_args,
)

from typing_extensions import (
    Concatenate,
    Generic,
    ParamSpec,
    Self,
    TypeVar,
    evaluate_forward_ref,
    get_origin,
    get_type_hints,
)

import pymhf.core._internal as _internal
from pymhf.core._internal import BASE_ADDRESS, IS_INJECTED
from pymhf.core._types import (
    DetourTime,
    HookProtocol,
)
from pymhf.core.functions import FuncDef, _get_funcdef
from pymhf.core.memutils import find_pattern_in_binary, get_addressof, map_struct
from pymhf.extensions.ctypes import CTYPES

logger = getLogger(__name__)

# A list of attibutes we never want to copy over from the base class.
_IGNORABLE_ATTRIBUTES = {
    "__annotations__",
    "__dict__",
    "__weakref__",
    "__module__",
    "__qualname__",
    "_fields_",
    "_pack_",
    "_partial_fields_",
    "_partial_attributes_",
    "_ctypes_root_",
    "__classcell__",
}

# A list of structs pending definition.
# This is used to implement the functionality in ctypes where the defintion of _fields_ is deferred until
# class construction to allow for self-referential and forward-referenced structs.
_pending_structs: list["PartialStructMeta"] = []


_FunctionHook_overloads: dict = defaultdict(lambda: dict())


@dataclass
class Field:
    datatype: CTYPES
    offset: int


@dataclass
class Pattern:
    pattern: str
    address_offset: int = 3
    address_dtype: Union[
        type[ctypes.c_uint16],  # for 32 bit binaries... Maybe?
        type[ctypes.c_uint32],  # For 64 bit binaries normally.
        type[ctypes.c_uint64],
    ] = ctypes.c_uint32
    address_type: Literal["relative", "absolute"] = "relative"


# TODO: Fix the issue of the address_offset not being 3 not getting the right offsets.
class ContainerStruct:
    """
    Base class which, when inherited will automatically find any fields which are
    This will also utilise the pattern cache so the lookup within the binary only occurs once per unique
    exe."""

    def __init_subclass__(cls):
        if not IS_INJECTED:
            # If the class is getting initialised but we aren't running within an injected process then we
            # won't actually be able to find any of the fields.
            # Simply return and this will be called again automatically once injected.
            return
        # Loop over the fields defined on the class and determine the offsets from the cache as required.
        for field_name, annotation in get_type_hints(cls, include_extras=True).items():
            if get_origin(annotation) is not Annotated:
                # In this case it's just some other field.
                continue
            else:
                # If the annotation is a Field object, get info from it, otherwise it must be an integer
                # specifying the offset.
                field_type, field_meta, *extra = get_args(annotation)
                if extra:
                    raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")
                if isinstance(field_meta, Pattern):
                    pattern = field_meta.pattern
                    address_offset = field_meta.address_offset
                    address_dtype = field_meta.address_dtype
                    address_type = field_meta.address_type

                    # Find the pattern in the binary
                    patt_addr = find_pattern_in_binary(pattern, False)
                    if patt_addr:
                        start_addr = BASE_ADDRESS + patt_addr
                        rel_offset = address_dtype.from_address(start_addr + address_offset)
                        if address_type == "relative":
                            abs_offset = (
                                start_addr + rel_offset.value + address_offset + ctypes.sizeof(address_dtype)
                            )
                        else:
                            abs_offset = rel_offset.value
                        setattr(cls, field_name, map_struct(abs_offset, field_type))
                    else:
                        logger.error(f"Unable to find the field {cls}.{field_name} with pattern {pattern!r}")
                else:
                    raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")


_T = TypeVar("_T", bound=Type[ctypes.Structure])


def partial_struct(cls: _T) -> _T:
    """Mark a class as a partial Struct. This is only needed when you want to define a class which subclasses
    a plain ``ctypes.Structure`` class but overwrite some of the existing fields."""
    if isinstance(cls, PartialStructMeta):
        return cls
    return PartialStructMeta(cls.__name__, cls.__bases__, dict(cls.__dict__))  # type: ignore[return-value]


def _extract_ctypes_fields(cls):
    """Extract the _fields_ for the class so that we may merge them up into our metaclass."""
    fields = {}
    for base_cls in reversed(cls.__mro__):
        if (base_fields := getattr(base_cls, "_fields_", None)) is not None:
            for field_name, field_type in base_fields:
                if field_name.startswith("_padding"):
                    # Skip any existing padding as we only want actual fields.
                    continue
                fields[field_name] = (field_type, getattr(cls, field_name).offset)
    return fields


class PartialStructMeta(type(ctypes.Structure)):
    """Metaclass to hijack class creation so that we may create a new ctypes.Structure instance when we
    instantiate the class.
    This will iterate through any base classes and construct the _fields_ based on the union of all the fields
    of all base classes.
    Methods are also retained so that we still get normal inheritence."""

    # Internal list of fields to assign to _fields_ on initialisation (or afterwards in the case of structs
    # which have unresolved fields).
    # This is required because in python 3.13 ctypes objects were changed so that you couldn't set _fields_
    # before the __init__ was called on the class, cf. https://github.com/python/cpython/issues/124520
    _fields: list[tuple[str, CTYPES]]
    _fields_: list[tuple[str, CTYPES]]
    _partial_fields_: dict
    _partial_attributes_: dict[str, tuple]
    _ctypes_root_: CTYPES
    _partial_unresolved_: dict[str, tuple[ForwardRef, int]]
    _fields_are_final: bool

    def __new__(mcls, name: str, bases: tuple, namespace: dict, **kwargs):
        own_fields = {}
        unresolved_fields: dict[str, tuple[ForwardRef, int]] = {}
        # The namespace contains the annotations for the class.
        # We will iterate over it and extract the actual field info from it.
        for field_name, annotation in namespace.get("__annotations__", {}).items():
            if get_origin(annotation) is Annotated:
                field_type, field_meta, *extra = get_args(annotation)
                if extra:
                    raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")
                if isinstance(field_meta, Field):
                    field_type = field_meta.datatype
                    field_offset = field_meta.offset
                elif isinstance(field_meta, int):
                    field_offset = field_meta
                else:
                    raise ValueError(f"The field {field_name!r} has an invalid annotation: {annotation}")

                # Handle forward references:
                if isinstance(field_type, ForwardRef):
                    unresolved_fields[field_name] = (field_type, field_offset)
                else:
                    if isinstance(field_type, type) and not issubclass(field_type, get_args(CTYPES)):
                        raise ValueError(f"The field {field_name!r} has an invalid type: {field_type}")
                    if field_offset is not None and not isinstance(field_offset, int):
                        raise ValueError(f"The field {field_name!r} has an invalid offset: {field_offset!r}")

                    own_fields[field_name] = (field_type, field_offset)

        inherited_fields = {}
        inherited_attributes = {}

        # Loop over the base fields and extract any fields and methods from any bases classes which are
        # already partial structs, and extract just the fields from any ctypes.Structure bases classes.
        finalised_base_found = False
        for base in bases:
            if isinstance(base, PartialStructMeta):
                if getattr(base, "_fields_are_final", False) is True:
                    finalised_base_found = True
                inherited_fields.update(getattr(base, "_partial_fields_", {}))
                inherited_attributes.update(getattr(base, "_partial_attributes_", {}))
            elif isinstance(base, type) and issubclass(base, ctypes.Structure):
                inherited_fields.update(_extract_ctypes_fields(base))

        # Check that, if we have a finalised base in the stack, that we aren't trying to override any fields.
        # we may extend as per the usual ctypes.Structure inheritence, but we can't replace.
        if finalised_base_found and (overlap := set(own_fields.keys()) & set(inherited_fields.keys())):
            raise TypeError(
                f"{name!r} defines new fields which would be overriding existing fields: {overlap}, but a "
                "base is marked with the @final_fields decorator. New fields can only be added to the end as "
                "per usual ctypes.Structure inheritence, or new methods added."
            )

        # Check to see if any old fields have the same offset as the new ones.
        inherited_offsets = {v[1]: k for k, v in inherited_fields.items()}
        # If the offset is found in the inherited offsets, then remove it.
        for field_data in own_fields.values():
            if (old_field_name := inherited_offsets.get(field_data[1])) is not None:
                inherited_fields.pop(old_field_name)
        inherited_fields.update(own_fields)

        # If we have found this finalised base, we'll just return the normal subclass without doing any
        # merging of anything. That's only required when we build a new instance.
        if finalised_base_found:
            cls = super().__new__(mcls, name, bases, namespace, **kwargs)
            cls._fields_are_final = True
        else:
            # Determine what our own attributes are by getting anything from the namespace we don't want to
            # ignore and that isn't a field.
            own_attributes = {
                key: value
                for key, value in namespace.items()
                if key not in own_fields and key not in _IGNORABLE_ATTRIBUTES
            }
            inherited_attributes.update(own_attributes)

            # Merge the base attributes into the current namespace.
            # We do this since the methods otherwise won't be inherited.
            for key, value in inherited_attributes.items():
                namespace.setdefault(key, value)

            namespace.pop("_fields_", None)
            namespace.pop("__dict__", None)
            namespace.pop("__weakref__", None)

            cls = super().__new__(mcls, name, (ctypes.Structure,), namespace, **kwargs)

            cls._partial_fields_ = inherited_fields
            cls._partial_attributes_ = inherited_attributes
            cls._partial_unresolved_ = unresolved_fields

        # Generate the actual _fields_ attribute based on some criteria.
        # If we have no fields to generate, just return
        if unresolved_fields:
            _pending_structs.append(cls)
        else:
            if finalised_base_found:
                # Generate the fields at least but only for the ones added here.
                base_size = ctypes.sizeof(bases[0])
                cls._fields = _generate_fields(own_fields, getattr(cls, "_total_size_", 0), base_size)
            else:
                cls._fields = _generate_fields(inherited_fields, getattr(cls, "_total_size_", 0))

        return cls

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _resolve_pending(True)
        if hasattr(self, "_fields"):
            self._fields_ = self._fields
            # Delete it since we no longer need it and it's just duplicated memory at this point.
            del self._fields


def _generate_fields(
    field_data: dict[str, tuple[CTYPES, int]],
    total_size: int | None,
    start_offset: int = 0,
):
    """Generate the actual _field_ definition for a struct. This will only be done once there are no forward
    references to be resolved."""
    _fields_ = []
    if not field_data:
        return _fields_
    curr_pos = start_offset
    ordered_fields = sorted(field_data.items(), key=lambda kv: kv[1][1])
    for field_name, (field_type, field_offset) in ordered_fields:
        # Check whether the offset of the field is at the current position.
        # If not, add padding.
        field_alignment = ctypes.alignment(field_type)
        if field_alignment and (curr_pos % field_alignment != 0):
            # If the field is not aligned to the correct position, then move the current position forward
            # to ensure it's right.
            # Don't bother adding this as padding since it will just add extra unnecessary fields.
            curr_pos += field_alignment - (curr_pos % field_alignment)
        if field_offset and curr_pos < field_offset:
            padding_bytes = field_offset - curr_pos
            _fields_.append((f"_padding_0x{curr_pos:X}", ctypes.c_ubyte * padding_bytes))
            curr_pos += padding_bytes
        _fields_.append((field_name, field_type))
        curr_pos += ctypes.sizeof(field_type)
    if total_size and curr_pos < total_size:
        padding_bytes = total_size - curr_pos
        _fields_.append((f"_padding_0x{curr_pos:X}", ctypes.c_ubyte * padding_bytes))
    return _fields_


def _resolve_pending(pre_initialising: bool = False):
    """Resolve any pending struct _field_ definitions that we can by evaluating forward references."""
    still_pending = []

    # Inspect the call stack and go back up 2 frames to find any locals which were defined.
    calling_frame = None
    _locals = locals()
    if (cframe := inspect.currentframe()) is not None:
        if (calling_frame := cframe.f_back) is not None:
            if (calling_frame := calling_frame.f_back) is not None:
                _locals.update(calling_frame.f_locals)

    for cls in _pending_structs:
        # Get the module and determine the globals for that module so that we can pass it to the type eval.
        module_name = cls.__module__
        globalns = getattr(sys.modules.get(module_name), "__dict__", {})
        # Inject the class and its annotations so that it can resolve self-references.
        _locals.update({cls.__name__: cls})
        _locals.update(cls.__annotations__)

        # Loop over the unresolved fields and see if we can resolve them.
        # Do this by evaluating any forward references within the context of the globals in the module and
        # the locals in the type.
        still_unresolved = {}
        for field_name, (fwd, offset) in cls._partial_unresolved_.items():
            try:
                target = evaluate_forward_ref(fwd, globals=globalns, locals=_locals)
            except NameError:
                target = None
            if target is None:
                still_unresolved[field_name] = (fwd, offset)
                continue
            cls._partial_fields_.update({field_name: (target, offset)})

        cls._partial_unresolved_ = still_unresolved

        # If we have resolved all types, finally construct the _fields_
        if not still_unresolved:
            _fields = _generate_fields(cls._partial_fields_, getattr(cls, "_total_size_", 0))
            if pre_initialising:
                cls._fields = _fields
            else:
                cls._fields_ = _fields
        else:
            still_pending.append(cls)

    # Update the pending struct list with any we still need to resolve.
    _pending_structs[:] = still_pending


def finalize_pending_structs():
    """Do one final check of the pending structs to see if there are any which need to be resolved."""
    _resolve_pending()
    if _pending_structs:
        names = [c.__name__ for c in _pending_structs]
        raise NameError(f"unresolved forward references in: {names}")


class PartialStruct(ctypes.Structure, metaclass=PartialStructMeta):
    """Simple wrapper around ctypes.Structure."""

    def __getattribute__(self, name: str):
        # Hook the instance attribute lookup so that we may "bind" the instance to the returned FunctionHook
        # instance.
        # We need to do this because the decorator has no knowledge of the actual bound instance at run-time.
        res = object.__getattribute__(self, name)
        if isinstance(res, FunctionHook):
            res._bound_class = self
        return res

    @classmethod
    def new_empty(cls) -> Self:
        """Create a new empty instance of the structure. This will have ALL of its data as empty bytes.
        The purpose of this is to allocate enough bytes to fit the object in memory so that it may then be
        populated with real data, or passed to some function to have its' data populated.
        """
        buffer = ctypes.create_string_buffer(ctypes.sizeof(cls))
        addr = get_addressof(buffer)
        return map_struct(addr, cls)


Structure = PartialStruct


def final_fields(klass: type[PartialStruct]):
    """Mark a PartialStruct class as having complete fields. This will still allow new methods to be defined
    on inheriting classes, but no new fields can be added that overwrite any existing fields.
    The resulting class can be treated like a ``ctypes.Structure`` class."""
    klass._fields_are_final = True
    return klass


P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S", bound=PartialStruct)
THIS = TypeVar(
    "THIS",
    bound=Union[
        ctypes.c_uint32,  # 32 bit "pointer" types.
        ctypes.c_ulong,
        ctypes.c_uint64,  # 64 bit "pointer" types.
        ctypes.c_ulonglong,
        ctypes._Pointer,  # Actual pointer type.
    ],
)


class FunctionHook(Generic[P, R]):
    def __init__(
        self,
        func: Union[Callable[P, R], Callable[Concatenate[S, THIS, P], R]],
        signature: str | None = None,
        offset: int | None = None,
        exported_name: str | None = None,
        imported_name: str | None = None,
        overload_id: str | None = None,
        is_static: bool = False,
    ):
        self._func = func
        self._signature = signature
        self._offset = offset
        self._exported_name = exported_name
        self._imported_name = imported_name
        self._overload_id = overload_id
        self._is_static = is_static
        self._this_is_pointer: bool | None = None
        self._bound_class: ctypes.Structure | None = None
        self._funcdef: FuncDef | None = None

    @property
    def this_is_pointer(self):
        """Only valid for bound methods. Returns True if the first argument is a pointer type."""
        if self._this_is_pointer is not None:
            return self._this_is_pointer
        if self._funcdef is None:
            self._funcdef = _get_funcdef(self._func)
        self._this_is_pointer = issubclass(self._funcdef.arg_types[0], ctypes._Pointer) | issubclass(
            self._funcdef.arg_types[0],
            ctypes._Pointer_orig,  # type: ignore
        )
        return self._this_is_pointer

    def _call(self, *args, **kwargs) -> R | None:
        """Call the actual function. This will do some work to find where the function is in memory and then
        call it with the provided arguments.
        """
        try:
            # Get the FUNCDEF. This will have named arguments with types so that we may construct a function
            # prototype which allows kwargs.
            if self._funcdef is None:
                self._funcdef = _get_funcdef(self._func)
            # Unfortunately the ctypes function prototype can only be called with kwargs if its a function
            # which is in a remote library.
            # We can do this for imported and exported functions, but to have the logic the same for all, it's
            # better to just flatten the kwargs and args into a single set of args and pass into the function
            # prototype defined by an offset.
            _args = self._funcdef.flatten(*args, **kwargs)
            sig = CFUNCTYPE(self._funcdef.restype, *self._funcdef.arg_types)
            binary_base = _internal.BASE_ADDRESS
            # Depending on what kind of function we are calling, we change how we find the offset of the func.
            offset = None
            if self._offset is not None:
                offset = binary_base + self._offset
            elif self._signature is not None:
                rel_offset = find_pattern_in_binary(self._signature, False, _internal.EXE_NAME)
                if rel_offset is not None and isinstance(rel_offset, int):
                    offset = binary_base + rel_offset
            elif self._exported_name is not None:
                own_dll = ctypes.WinDLL(_internal.BINARY_PATH)
                func_ptr = getattr(own_dll, self._exported_name)
                offset = ctypes.cast(func_ptr, ctypes.c_void_p).value
            # Finally, call the function.
            if offset is not None:
                cfunc = sig(offset)
                try:
                    val = cfunc(*_args)
                except ctypes.ArgumentError:
                    logger.error(
                        f"{self._func.__qualname__!r} has function signature {self._funcdef.arg_types} "
                        f"but was called with {_args}"
                    )
                    raise
                except OSError:
                    logger.exception(f"There was an exception calling {self._func.__qualname__!r}")
                    arg_types = [type(x) for x in _args]
                    logger.error(
                        "Function details:\n"
                        f"Function Signature: {self._funcdef.arg_types}\n"
                        f"Call args: {_args} => {arg_types}\n"
                        f"Function offset: 0x{offset:X} => +0x{offset - _internal.BASE_ADDRESS:X}"
                    )
                    return None
                return val
            else:
                logger.error(f"Unable to call {self._func.__qualname__!r} - Cannot find function.")
        except Exception:
            logger.exception(f"There was an exception calling {self._func.__qualname__!r}")
            return None

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R | None:
        # This initial check is to check if the first argument was a function.
        # This will only happen if the function is being used as a decorator.
        # if this check fails, then we are calling the function under "normal" usage.
        if args and inspect.isfunction(args[0]):
            # In this case the decorator was used without a .before or .after -> raise error
            raise ValueError(
                f"Hook for detour {self._func.__qualname__!r} must be specified as either `before` or `after`"
            )

        if self._is_static:
            # For a static method, we don't need to worry about any binding, we can just call it with the
            # provided arguments.
            return self._call(*args, **kwargs)
        else:
            # For a non-static method, we need to do more work since we need to get the instance the method is
            # bound to, and then get the address of it and pass it in as the first argument.
            if self._bound_class is not None:
                try:
                    if self.this_is_pointer:
                        return self._call(ctypes.byref(self._bound_class), *args, **kwargs)
                    else:
                        # If it's not a pointer, then we'll assume it's an int and pass the address...
                        return self._call(ctypes.addressof(self._bound_class), *args, **kwargs)
                except Exception:
                    logger.exception(f"Failed to call {self._func.__qualname__} with args {args}")
            else:
                raise ValueError("Not bound to anything...")

    def _decorate_detour(self, detour, hook_time: DetourTime | None = None) -> HookProtocol:
        if hook_time is None:
            raise ValueError(
                f"Hook for detour {detour.__qualname__!r} must be specified as either `before` or `after`"
            )

        self._funcdef = _get_funcdef(self._func)

        setattr(detour, "_is_funchook", True)
        setattr(detour, "_hook_time", hook_time)
        if self._exported_name is None:
            setattr(detour, "_hook_func_name", self._func.__qualname__)
        else:
            setattr(detour, "_hook_func_name", self._exported_name)
        if self._imported_name is not None:
            split_name = self._imported_name.split(".", maxsplit=1)
            if len(split_name) != 2:
                raise ValueError(
                    f"imported name {self._imported_name!r} is invalid. Please ensure it has the following "
                    "structure: dll_name.dll_function"
                )
            dll_name, function_name = split_name
            setattr(detour, "_dll_name", dll_name)
            setattr(detour, "_is_imported_func_hook", True)
            setattr(detour, "_hook_func_name", function_name)
        else:
            setattr(detour, "_is_imported_func_hook", False)
            setattr(detour, "_dll_name", None)
        setattr(detour, "_hook_func_def", self._funcdef.to_FUNCDEF())
        setattr(detour, "_hook_offset", self._offset)
        setattr(detour, "_hook_pattern", self._signature)
        setattr(detour, "_is_manual_hook", False)
        setattr(detour, "_is_exported_func_hook", self._exported_name is not None)
        setattr(detour, "_has__result_", False)
        setattr(detour, "_noop", False)
        setattr(detour, "_func_overload", self._overload_id)
        return detour

    def after(self, detour: Callable) -> HookProtocol:
        """Mark the detour as running after the original function."""
        decorated_detour = self._decorate_detour(detour, DetourTime.AFTER)
        if "_result_" in inspect.signature(detour).parameters.keys():
            setattr(detour, "_has__result_", True)
        return decorated_detour

    def before(self, detour: Callable) -> HookProtocol:
        """Mark the detour as running before the original function."""
        decorated_detour = self._decorate_detour(detour, DetourTime.BEFORE)
        return decorated_detour

    def overload(self, overload_id: str) -> Self:
        """Get an instance of the class which corresponds to the specified overload id.
        This overload id should be provided as the ``overload_id`` argument for ``function_hook``"""
        if overload_id == self._overload_id:
            return self
        else:
            fh = _FunctionHook_overloads.get(self._func.__qualname__, {}).get(overload_id, None)
            if fh is not None:
                return fh
            else:
                raise ValueError(f"Unknown overload {overload_id!r} for {self._func.__qualname__}")


class _function_hook:
    def __init__(
        self,
        signature: str | None = None,
        offset: int | None = None,
        exported_name: str | None = None,
        imported_name: str | None = None,
        overload_id: str | None = None,
    ):
        self.signature = signature
        self.offset = offset
        self.exported_name = exported_name
        self.imported_name = imported_name
        self.overload_id = overload_id


class static_function_hook(_function_hook):
    """Mark the decorated function as a static function hook.

    .. note::
        Only of the arguments of this function is required.
        The order the arguments are respected is ``signature``, ``offset``, then ``exported_name``.

    .. note::
        You do not need to apply the ``@staticmethod`` decorator to functions if you use this decorator,
        however your static type checker may complain, so this decorator is safe to apply on top of the
        ``@staticmethod`` decorator.

    Parameters
    ----------
    signature:
        A string representing the bytes which can be used to uniquely find the function within the binary.
    offset:
        The relative offset within the binary where the start of the function can be found.
    exported_name:
        The name of the exported function which is to be hooked.

        .. note::
            It is recommended that the function name is the "mangled" version.
            Ie. do not "demangle" the function name.

    imported_name:
        The full name of the function within the imported dll to be hooked. For example, this could be
        ``"Kernel32.ReadFile"``.
    overload_id:
        A unique name within each set of overloaded functions which can be used to identify the overload for
        calling and hooking purposes.
    """

    def __call__(self, func: Callable[P, R]) -> FunctionHook[P, R]:
        if not self.signature and not self.offset and not self.exported_name and not self.imported_name:
            raise ValueError(
                f"One of the `function_hook` arguments must be provided for {func.__qualname__!r}"
            )
        # Pass the function in directly so that we may defer the usage of inspect until the actual decorator
        # is called.
        # This will mean that only functions which are used are inspected which will massively reduce the
        # amount of work required.
        if isinstance(func, staticmethod):
            # Unwrap the static method to get the underlying function since staticmethods aren't callable
            # cf. https://bugs.python.org/issue20309
            func = func.__func__
        return FunctionHook[P, R](
            func,
            self.signature,
            self.offset,
            self.exported_name,
            self.imported_name,
            is_static=True,
        )


class function_hook(_function_hook):
    """Mark the decorated function as a function hook.

    .. note::
        Only of the arguments of this function is required.
        The order the arguments are respected is ``signature``, ``offset``, then ``exported_name``.

    .. important::
        This decorator must only be applied to non-static methods.
        This means that the first two arguments MUST be `self` (the usual python one), and `this` (the c
        one.)
        Because of how this decorator works, the function arguments will be determined from all the
        arguments proceeding these two mandatory ones.

    .. important::
        For this decorator to work, the class the method belongs to MUST be a
        :class:`~pymhf.core.structs.PartialStruct` instead of the usual `ctypes.Structure`.

    Parameters
    ----------
    signature:
        A string representing the bytes which can be used to uniquely find the function within the binary.
    offset:
        The relative offset within the binary where the start of the function can be found.
    exported_name:
        The name of the exported function which is to be hooked.

        .. note::
            It is recommended that the function name is the "mangled" version.
            Ie. do not "demangle" the function name.

    imported_name:
        The full name of the function within the imported dll to be hooked. For example, this could be
        ``"Kernel32.ReadFile"``.
    overload_id:
        A unique name within each set of overloaded functions which can be used to identify the overload for
        calling and hooking purposes.
    """

    def __call__(self, func: Callable[Concatenate[S, THIS, P], R]) -> FunctionHook[P, R]:
        if not self.signature and not self.offset and not self.exported_name and not self.imported_name:
            raise ValueError(
                f"One of the `function_hook` arguments must be provided for {func.__qualname__!r}"
            )
        # Pass the function in directly so that we may defer the usage of inspect until the actual decorator
        # is called.
        # This will mean that only functions which are used are inspected which will massively reduce the
        # amount of work required.
        fh = FunctionHook[P, R](
            func,
            self.signature,
            self.offset,
            self.exported_name,
            self.imported_name,
            self.overload_id,
            is_static=False,
        )
        _FunctionHook_overloads[func.__qualname__][self.overload_id] = fh
        return fh
