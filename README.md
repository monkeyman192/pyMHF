# pyMHF

*pyMHF* is a python Modding and Hooking Framework.
It is designed to make it very easy to create libraries for any game or application which can then be used to make mods.

## Features

*pyMHF* contains a number of important features to make creatting a modding library as easy as possible:

### Simple hooking

To create a hook, the following pieces of information are required:
- The relative offset of the function from the start of the binary or the byte signature [WIP] of the function.
- The function call signature. This is the return and argument types, specified as would be expected by using Pythons' `ctypes` library.
- A class definition which can be used to indicate the hierarchy of functions to allow for simpler calling of functions from the code.

Once this is provided, hooks can be defined as methods within a `Mod` class, allowing for complex behaviour to be implemented with little effort.

### Ability to hook functions across multiple binaries

Whilst not fully feature complete yet, it will be possible to specify what loaded libraries or binaries the functions reside within, to allow for hook function in both the main executable as well as loaded ones.

### Automatically generated GUI

A GUI (using [DearPyGUI](https://github.com/hoffstadt/DearPyGui)) is automatically generated for the program. All mods will appear automatically as separate tabs, and widgets can be added by way of function decorators within the mod to easily create simple interfaces.

### "Compound hooks"

All hooks are defined as either being run **before** or **after** the original function. This allows *pyMHF* to construct what we call "compound hooks" which may consist of any number of detour methods across any number of mods. This means that two mods which affect the same function may coexist (generally) peacefully.

**Note**: The order of execution of detours is arbitrary, so one must not expect their detour to be run before or after any other detour of the same hook.

### Custom callbacks

Modding libraries can define custom callbacks which can be used to allow methods to be called whenever they are triggered. Examples include *every game tick* or *level change* for example.

### Keyboard callbacks

It is possible to declare methods to be run when a certain key is pressed or released.

### Reloadability

One major annoyance when testing and debugging mods at this level is the requirement to often have to reload the game to reload any mods and hooks which have been created. *pyMHF* has the ability to reload mods (either via the GUI, or via the injected python REPL). This will re-read the python file and reload any hooks or keyboard callbacks which are defined in it.

### Mod states

While reloading mods is great, sometimes objects are instantiated once when the game starts and that is it. To avoid losing these instances across reloads, there is the concept of a `ModState` object which will persist across reloads. These object are bound to the mod itself so it is generally recommended to use these to store any kind of state (and in fact, can be serialized and deserialized to json as a form of saving).
