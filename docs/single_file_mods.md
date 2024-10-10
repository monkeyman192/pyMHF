# Single-file mods

While `pymhf` is designed to be used to create libraries upon which mods can be made, for smaller scale projects or small tests, this is not convenient.
To accomodate this, `pymhf` can run a single file containing a mod.

This file **MAY** have the following attributes defined in it to simplify the defintions:

`__pymhf_func_binary__` (`str`): The name of the binary all the function offsets/patterns are to be found relative to/in. If provided this will be the default for all functions, however any `manual_hook` with a different value provided will supersede this value.
`__pymhf_func_offsets__` (`dict[str, Union[int, dict[str, int]]]`): A lookup containing the function names and offsets. Generally the keys will be the function names that you want to call the function by, and the values will simply be the offset relative to the start of the binary. For overloads the value can be another dictionary with keys being some identifier for the overload (eg. the argument types), and the values being the offsets.
`__pymhf_func_call_sigs__` (`dict[str, Union[FUNCDEF, dict[str, FUNCDEF]]]`): A lookup containing the function names and function call signatures. The keys will be the function names that you want to call the function by, and the values will either be the `FUNCDEF` itself, or a dictionary similar to the `__pymhf_func_offsets__` mapping.
`__pymhf_func_patterns__` (`dict[str, Union[str, dict[str, str]]]`): A lookup containing the function names and byte patterns to find the functions at. The keys will be the function names that you want to call the function by, and the values will be either a string containing the pattern, or a dictionary similar to the `__pymhf_func_offsets__` mapping.

Note that none of these are mandatory, however they do simplify the code in the file a decent amount and keep the file more easy to maintain.
