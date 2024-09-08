# Change Log

## Current

### 0.1.6 (08/09/2024)

- Add ability for GUI widgets to reload when their associated mod gets reloaded ([gh-4](https://github.com/monkeyman192/pyMHF/issues/4))
- Add `extra_args` option to GUI field type decorators (eg, `FLOAT`) which are passed through to DearPyGui ([gh-8](https://github.com/monkeyman192/pyMHF/issues/8))
- Fix issues with hooking multiple functions which are overloads of the same base function.
- Add the ability for patterns to be hooked up using the `FUNC_PATTERNS` data in implementing libraries ([gh-14](https://github.com/monkeyman192/pyMHF/issues/14))

### 0.1.5 (26/08/2024)

- Allow overriding of function return values.
- Fixed issue with `after` manual hooks with a `_result_` argument.
- Implement pattern scanning functionality ([gh-1](https://github.com/monkeyman192/pyMHF/issues/1))

### 0.1.4 (14/08/2024)

- Overhauled config system to provide a more user-friendly experience.
- Fixed a critical bug in hooking which meant that no result was returned.
- Fixed an issue injecting variables into pymhf.

### 0.1.3 (31/07/2024)

- Implemented manual hooks. These are a decorator which have the can take an offset, name, and function definition, and allow for hooking a function without having to rely on the underlying library which utilises pymhf.
- Made changes so that libraries can be installed as plugins to pymhf so that they can be run like `pymhf <libname>`

### 0.1.2 (15/07/2024)

- Made improvements to config reading

### 0.1.1 (05/07/2024)

- Fixed issues loading applications which aren't loaded with steam.
- Fixed logging number of mods loaded.
- Implemented custom triggers. They can be implemented by libraries which use this framework to enable custom triggers which are specific to the game/application.
- Fixed some issues with reloading of mods when there are multiple mods all contributing to compound hooks, including hooks with completely disabled detours.
- Added `@no_gui` decorator which can be applied to a `Mod` class to indicate that it doesn't need to be shown in the GUI.

## Previous

### 0.1.0 (30/06/2024)

- Initial release. Much of the functionality has been copied over from NMS.py which was how this project started.
