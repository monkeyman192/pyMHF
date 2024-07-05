# Change Log

## Current

### 0.1.1 (05/07/2024)

- Fixed issues loading applications which aren't loaded with steam.
- Fixed logging number of mods loaded.
- Implemented custom triggers. They can be implemented by libraries which use this framework to enable custom triggers which are specific to the game/application.
- Fixed some issues with reloading of mods when there are multiple mods all contributing to compound hooks, including hooks with completely disabled detours.
- Added `@no_gui` decorator which can be applied to a `Mod` class to indicate that it doesn't need to be shown in the GUI.

## Previous

### 0.1.0 (30/06/2024)

- Initial release. Much of the functionality has been copied over from NMS.py which was how this project started.
