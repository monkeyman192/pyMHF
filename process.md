- Call the main entry point with the path to the module
- Load the module. Some info will be needed:
    - data directory
    - mod directory

What do we need to have exposed at the top level?
- function offsets
- function definitions

- Need to pass in the path for the mods? so that it can be loaded
- have some kind of "initialisation sequence" for modules which are run before mods are loaded.