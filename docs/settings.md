# pyMHF settings file [OBSOLETE]

**TODO: Update these settings**

*pyMHF* contains a file called `pymhf.cfg` which (currently) must be situated within the root directory of the modding library (cf. [here](../writing_libraries.md))
This file has a number of properties in different sections. Some are required and others are not:

## `binary` section:

This section handles properties which relate to the game or program that the library will be for.

- **path**: The full path of the binary to be run.

- **mod_dir**: The full path to the directory containing the mods to be run.

- **hash**: The `SHA1` hash of the exe. This is used to ensure that the binary matches what is expected by the library exactly.

- **steam_guid** [optional]: If the game is run through steam, this should set to the Steam App ID. This can be found by right clicking on the game in your library and selecting "Properties...". The value can be found under the "Updates" option on the left.

- **required_assemblies**: [optional]: A list of assemblies that are required to be loaded by the binary at `path` for the game to be considered "loaded". For now, if this is provided, it will also be the binary within which offsets are found relative to, however this will be relaxed in the future as better functionality regarding this is developed.

## `pymhf` section:

- **log_level**: Whether to log at the standard level (`INFO`), or more in-depth (`DEBUG`).

## `gui` section:

This section related to properties specifically for the GUI which is auto-generated.

- **shown**: Whether or not to show the GUI (`True` or `False`).

- **scale**: The scale of the GUI. For some high-resolution monitors the GUI may end up scaled down when running from within a process, so sometimes this may need to be set to 1.5 for the GUI to look correct.

- **log_window_name_override** The text to display at the top of the log window.
