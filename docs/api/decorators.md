# pyMHF decorators

A lot of the power and functionality of pyMHF comes from a set of decorators which can be applied to methods in a mod class.

## Hooking Decorators

### `manual_hook`:

Parameters
----------
`name`:
    The name of the function to hook. This doesn't need to be known, but any two manual hooks sharing the
    same name will be combined together so one should remember to keep the name/offset combination unique.

`offset`:
    The offset in bytes relative to the start of the binary.
    To determine this, you normally subtract off the exe Imagebase value from the address in IDA (or
    similar program.)

`pattern`:
    A pattern which can be used to unqiuely find the function to be hooked within the binary.
    The pattern must have a format like "01 23 45 67 89 AB CD EF".
    The format is what is provided by the IDA plugin `SigMakerEx` and the `??` values indicate a wildcard.

`func_def`:
    The function arguments and return value. This is provided as a `pymhf.FUNCDEF` object.
    This argument is only optional if another function with the same offset and name has already been hooked in the same mod.

`detour_time`:
    When the detour should run ("before" or "after")

`binary`:
    If provided, this will be the name of the binary which the function being hooked is within.
    `offset`~ and `pattern` are found relative to/within the memory region of this binary.

### `one_shot`:

If applied to a function, the detour will only be run once.

**Note**: If the hooked function is run in a multi-threaded environment in the binary, this may not work quite right. It will be deactivated eventually, but if the hooked function is called multiple times from different threads at the same time it may run more than once.

### `get_caller`:

When applied to a function this decorator will cause the function hook to determine where it was called from.
To access this information, you can call a function on the detour method itself. This is seen more clearly by example:

```py
class MyHook(NMSMod):
    @get_caller
    @pymhf.core.hooking.manual_hook(...)
    def do_something(self, *args):
        logging.info(f"I was called from 0x{self.do_something.caller_address():X}")
```

This address will be the address relative to the start of the binary the hook is called from.

**Note:** The address returned will be one expression later than the `call` instruction used to call the original function. This is because to get this caller address we are looking for the value of the `RSP` register which is where the program will resume operation from after running the function.

## Keyboard Decorators

### `on_key_pressed`:

This decorator is used to indicate that a function should be called when a specific key is pressed. Note that the key MUST be a single key (eg. "a") and is not case-sensitive.

### `on_key_release`:

This decorator is used to indicate that a function should be called when a specific key is released. Note that the key MUST be a single key (eg. "a") and is not case-sensitive.