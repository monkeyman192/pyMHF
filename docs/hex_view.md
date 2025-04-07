# Hex View

In the auto-generated `pyMHF` GUI, you will notice a tab called "Hex View".
This tab can be used to explore the memory of the running process that `pyMHF` is running within.

When you initially open this tab there will be no data, however you can enter an address (in hex) in the address bar and it will show the 4kb of memory from that address.
Note that the view can only access memory that the process has access to, so entering an invalid address will cause an error to display in the console, and nothing to happen in the editor.

## Methods

The `gui` property of the mod is a `pymhf.gui.gui.GUI` instance which has the `hex_view` property.

## `pymhf.gui.hex_view.HexView`

### add_snapshot(address: int, size: Optional[int] = None, tag: Optional[str] = None) -> bool:

Add a snapshot of the data at the specified address to the hex viewer. These memory snapshots will be viewable later from a drop down in the hex viewer.

#### Parameters

`address`:
    The absolute memory address to take a snapshot at.
    *Note*: The start address of the region will be aligned to a 0x10 byte boundary for convenience.

`size`:
    The size of the region to take a snapshot of. Note that if this is larger than 0x1000 (4kb), it will be rounded down to 0x1000.
    *Note*: It is recommended to set this value just a bit larger than the expected size of the data.

`tag`:
    An optional tag which can be used to identify the snapshot in the selector in the GUI.
    If not provided it will default to the hex representation of the provided memory address.
    *Note*: If the tag already exists, it won't be overwritten but will be suffixed by a number which automatically increments (this includes auto-generated tags as per above.)

#### Returns

`bool`:
    If a memory snapshot was sucessfully taken at the provided address and size this will return True.
    If the memory at the provided address was unable to be read or captured this will return False.

----

### load_address(address: int, size: Optional[int] = None) -> bool:

Load the provided address into the hex viewer.

#### Parameters

`address`:
    The absolute memory address to take a snapshot at. Note that the start address of the region will be aligned to a 0x10 byte boundary for convenience.

`size`:
    The size of the region to take a snapshot of. Note that if this is larger than 0x1000 (4kb), it will be rounded down to 0x1000.

#### Returns

`bool`:
    If a memory snapshot was sucessfully taken at the provided address and size this will return True.
    If the memory at the provided address was unable to be read or captured this will return False.