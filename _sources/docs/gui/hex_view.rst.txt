Hex View
========

In the auto-generated pyMHF GUI, you will notice a tab called "Hex View".
This tab can be used to explore the memory of the running process that pyMHF is running within.

When you initially open this tab there will be no data, however you can enter an address (in hex) in the address bar and it will show the 4kb of memory from that address.
Note that the view can only access memory that the process has access to, so entering an invalid address will cause an error to display in the console, and nothing to happen in the editor.

Methods
-------

The ``pymhf_gui`` property of the mod is a :py:class:`~pymhf.gui.gui.GUI` instance which has the ``hex_view`` property.

This :py:class:`~pymhf.gui.hexview.HexView` instance has two methods which are useful:

:py:meth:`add_snapshot(address: int, size: Optional[int] = None, tag: Optional[str] = None) -> bool <pymhf.gui.hexview.HexView.add_snapshot>`

and

:py:meth:`load_address(address: int, size: Optional[int] = None) -> bool <pymhf.gui.hexview.HexView.load_address>`

The first method is useful to snapshot a memory region when a function is hooked.
For example, if you have a detour which takes the pointer to some class as an argument, you may want to snapshot a few 100 bytes of this class to see what it's structure is.

The second method is more likely to be used from a key binding so that the contents of the Hex View is updated with some data located at some previously determined pointer.
