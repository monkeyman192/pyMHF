# Change Log

## Current (0.1.11-dev)

- Added the `gui_combobox(label: str, items: list[str])` decorator (partial work on [gh-15](https://github.com/monkeyman192/pyMHF/issues/15))
- Added the ability for mods to access each others' attributes and methods. ([gh-5](https://github.com/monkeyman192/pyMHF/issues/5)). See [this page](inter_mod_functionality.md) for more details.
- Fixed a few issues regarding running `pyMHF`. Thanks to [@Foundit3923](https://github.com/Foundit3923) for helping to figure out the issues.
- Fixed an issue where hooks of imported functions which have `_result_` as an argument work.
- Added `@pymhf.core.hooking.NOOP` decorator which indicates that the original game function shouldn't be called. See docstring for more details. ([gh-20](https://github.com/monkeyman192/pyMHF/issues/20))
- Added a hex editor to the `pyMHF` gui. This is accessible from the `Hex Viewer` tab of the gui and allows real time viewing of data, following pointer values, and capturing memory snapshots. ([gh-43](https://github.com/monkeyman192/pyMHF/issues/43))
- Fixed an issue with loading hooks. Thanks to [@cengelha](https://github.com/cengelha) for finding the bug.
- Added "always on top" gui setting to the config. Thanks to [@cengelha](https://github.com/cengelha) for adding it.

## 0.1.10 (26/02/2025)

- Added `pymhf.core.hooking.get_caller` decorator for detours. When added, this will determine the location the function was called from. ([gh-34](https://github.com/monkeyman192/pyMHF/issues/34)). NOTE: This currently will only work properly for 64bit applications.
- Added an `pymhf.core.hooking.exported` hook to allow hooking functions which are exported by the main exe.
- Added the `pymhf.core.calling.call_exported` function which allows exported functions by the game to be called.
- Added the ability to specify in the `pymhf.core.hooking.imported` decorator whether the detour time is `"before"` or `"after"`.
- Fixed an issue where hooks defined using the `manual_hook` decorator didn't use the `__pymhf_func_offsets__` etc. variables defined. (Thanks to [@hashcatHitman](https://www.github.com/hashcatHitman) for finding the bug.)
- Made improvements to the shutting down of `pyMHF` so that when the process it is attached to exits, so does `pyMHF`.
- Added a class decorator `partial_struct` in `pymhf.utils.partial_struct` which can be used to create `ctypes.Structure` types without needing to know the entire layout of the struct.

## 0.1.9 (23/01/2025)

- Added `cmd` mode to the configuration to run commands in any registered libraries.
- Added transparency slider and "always on top" options to the pymhf window.
- Made a fix to manual hooks which were being declared with a pattern and name only.

## 0.1.8 (26/12/2024)

- Add ability for single-file mods to be run by pymhf. ([gh-19](https://github.com/monkeyman192/pyMHF/issues/19))
- Changed the config system to use toml files. ([gh-27])(https://github.com/monkeyman192/pyMHF/issues/27)
- Added ability for pymhf to be attached to an already running process. ([gh-28])(https://github.com/monkeyman192/pyMHF/issues/28)

### 0.1.7 (10/10/2024)

- Implement ability to call overloaded functions which have patterns.
- Improve safety of hooking functions and keyboard bindings as well as GUI reload fix.
- Added functions to set the main window active ([gh-6](https://github.com/monkeyman192/pyMHF/issues/6)) - Contributed by `Foundit3923`

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
