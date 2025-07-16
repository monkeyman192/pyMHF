import ctypes
import struct
from datetime import datetime
from logging import getLogger
from typing import Iterable, Optional, TypedDict, Union

import dearpygui.dearpygui as dpg
from pymem.ressources.structure import MEMORY_STATE

from pymhf.utils.winapi import MemoryInfo, QueryAddress

logger = getLogger(__name__)

BITS = struct.calcsize("P") * 8

COLUMNS = 0x10
MAX_DATA_CACHE_SIZE = 0x100  # 256
MAX_FRAME_SIZE = 0x1000  # 4kb of memory
# Combination of the above gives us up to 1Mb of memory cached.

INITIAL_DATA = b"\x00" * MAX_FRAME_SIZE


class CachedMemoryData(TypedDict):
    base_address: int
    address: int
    data: bytes
    timestamp: datetime


def chunks(lst: Iterable, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


class HexView:
    def __init__(self, parent: Union[str, int]):
        self.parent = parent
        self.prev_selected_coords = set()
        self.curr_selected_coords = set()
        self.data: bytes = INITIAL_DATA
        self._select_bytes_start_addr: int = 0
        self._selected_bytes: bytes = b""
        self._open_file = None
        self.base_address: int = 0

        # Basic forward and backward address stack
        self._address_stack = []
        self._address_stack_location: int = 0

        # Stored memory data
        self._memory_cache: dict[str, CachedMemoryData] = {}
        self._memory_cache_repeated_tags: dict[str, int] = {}
        self._selected_snapshot_tag = None

    def add_snapshot(self, address: int, size: Optional[int] = None, tag: Optional[str] = None) -> bool:
        """Add a snapshot of the data at the specified address to the hex viewer. These memory snapshots will
        be viewable later from a drop down in the hex viewer.

        Parameters
        ----------
        address:
            The absolute memory address to take a snapshot at.
            *Note*: The start address of the region will be aligned to a 0x10 byte boundary for convenience.
        size:
            The size of the region to take a snapshot of. Note that if this is larger than 0x1000 (4kb), it
            will be rounded down to 0x1000.
            *Note*: It is recommended to set this value just a bit larger than the expected size of the data.
        tag:
            An optional tag which can be used to identify the snapshot in the selector in the GUI.
            If not provided it will default to the hex representation of the provided memory address.
            *Note*: If the tag already exists, it won't be overwritten but will be suffixed by a number which
            automatically increments (this includes auto-generated tags as per above.)

        Returns
        -------
        bool:
            If a memory snapshot was sucessfully taken at the provided address and size this will return True.
            If the memory at the provided address was unable to be read or captured this will return False.
        """
        addr_data = self._inspect_memory_region(address)
        if addr_data is None:
            return False

        base_address, data = self._load_data_from_address(address, addr_data, size)

        # Either generate a tag, or use the provided one.
        # If the provided one already exists or the generated one already exists, then we'll add a number
        # which gets incremented to the end of it.
        _tag = tag
        if tag is not None:
            if tag in self._memory_cache:
                if tag not in self._memory_cache_repeated_tags:
                    self._memory_cache_repeated_tags[tag] = 1
                else:
                    self._memory_cache_repeated_tags[tag] += 1
                _tag = f"{tag}-{self._memory_cache_repeated_tags[tag]}"
        else:
            _tag = hex(address)
            if _tag in self._memory_cache:
                if _tag not in self._memory_cache_repeated_tags:
                    self._memory_cache_repeated_tags[_tag] = 1
                else:
                    self._memory_cache_repeated_tags[_tag] += 1
                _tag = f"{_tag}-{self._memory_cache_repeated_tags[_tag]}"

        self._memory_cache[_tag] = {
            "base_address": base_address,
            "address": address,
            "data": data,
            "timestamp": datetime.now(),
        }

        # Update the list of items in the combobox
        dpg.configure_item(
            "_snapshot_dropdown",
            items=list(self._memory_cache.keys()),
        )

        logger.debug(
            f"Added snapshot for the memory region 0x{base_address:X} -> 0x{base_address + len(data):X} "
            f"with the tag {_tag!r}"
        )

        return True

    def load_address(self, address: int, size: Optional[int] = None) -> bool:
        """Load the provided address into the hex viewer.

        Parameters
        ----------
        address:
            The absolute memory address to take a snapshot at.
            *Note*: The start address of the region will be aligned to a 0x10 byte boundary for convenience.
        size:
            The size of the region to take a snapshot of. Note that if this is larger than 0x1000 (4kb), it
            will be rounded down to 0x1000.
            *Note*: It is recommended to set this value just a bit larger than the expected size of the data.

        Returns
        -------
        bool:
            If a memory snapshot was sucessfully taken at the provided address and size this will return True.
            If the memory at the provided address was unable to be read or captured this will return False.
        """
        addr_data = self._inspect_memory_region(address)
        if addr_data is None:
            return False

        # Cache the previous data size so that we may optimize the redraw of the table if they are the same
        # size.
        prev_size = len(self.data)

        self.base_address, self.data = self._load_data_from_address(address, addr_data, size)
        new_size = len(self.data)

        logger.debug(f"Refreshing table to show {len(self.data)} bytes from 0x{self.base_address:X}")
        # Clear and re-populate the table.
        if new_size == prev_size:
            self._refresh_table()
        else:
            self._clear_table()
            self._populate_table()
        # Select the currently selected value.
        self._select_coord(0, address % 0x10)

        # Update the address stack
        if self._address_stack_location == len(self._address_stack) - 1:
            # If we're at the end, just append the value.
            self._address_stack.append(self.base_address)
        else:
            # If we're not at the end, then we need to remove the next addresses in the stack and push this
            # to the end.
            self._address_stack = self._address_stack[: self._address_stack_location + 1] + [
                self.base_address
            ]
        self._address_stack_location = len(self._address_stack) - 1

        return True

    def _change_address(self, sender, app_data):
        val = int(app_data, 0x10)
        self.load_address(val)

    def _change_selection_size(self, sender, app_data, user_data):
        if app_data == 2:
            dpg.configure_item("size_2_values", show=True)
            dpg.configure_item("size_4_values", show=False)
            dpg.configure_item("size_8_values", show=False)
            dpg.configure_item("size_inv_values", show=False)
        elif app_data == 4:
            dpg.configure_item("size_2_values", show=False)
            dpg.configure_item("size_4_values", show=True)
            dpg.configure_item("size_8_values", show=False)
            dpg.configure_item("size_inv_values", show=False)
        elif app_data == 8:
            dpg.configure_item("size_2_values", show=False)
            dpg.configure_item("size_4_values", show=False)
            dpg.configure_item("size_8_values", show=True)
            dpg.configure_item("size_inv_values", show=False)
        else:
            dpg.configure_item("size_2_values", show=False)
            dpg.configure_item("size_4_values", show=False)
            dpg.configure_item("size_8_values", show=False)
            dpg.configure_item("size_inv_values", show=True)

    def _clear_table(self):
        dpg.delete_item("main_table", children_only=True, slot=1)

    def _clicked_on(self, sender, app_data):
        if dpg.get_value(app_data[1]):
            dpg.configure_item("option_popup", show=True)

    def _delete_snapshot(self):
        curr_idx = list(self._memory_cache.keys()).index(self._selected_snapshot_tag)
        _data = self._memory_cache.pop(self._selected_snapshot_tag)
        dpg.configure_item(
            "_snapshot_dropdown",
            items=list(self._memory_cache.keys()),
        )
        if curr_idx > 0:
            new_snapshot_tag = list(self._memory_cache.keys())[curr_idx - 1]
            self._load_snapshot(new_snapshot_tag)
            dpg.set_value("_snapshot_dropdown", new_snapshot_tag)
        elif len(self._memory_cache) > 0:
            new_snapshot_tag = list(self._memory_cache.keys())[0]
            self._load_snapshot(new_snapshot_tag)
            dpg.set_value("_snapshot_dropdown", new_snapshot_tag)
        else:
            # no snapshots left...
            self.base_address, self.data = 0, INITIAL_DATA
            if len(_data) == MAX_FRAME_SIZE:
                self._refresh_table()
            else:
                self._clear_table()
                self._populate_table()
            self._select_coord(0, 0)

            dpg.configure_item("_snapshot_details_group", show=False)
            dpg.configure_item("_snapshot_details_text", show=False)
            dpg.set_value("_snapshot_dropdown", None)

    def _inspect_memory_region(self, address: int) -> Optional[MemoryInfo]:
        """Inspect a memory address and determine if its ok to store or display."""
        try:
            addr_data = QueryAddress(address)
        except ValueError as e:
            logger.error(f"Unable to load address 0x{address:X}: {e.args}")
            return None
        logger.debug(
            f"Info about 0x{address:X}:\n"
            f"\tBaseAddress: 0x{addr_data.BaseAddress:X}\n"
            f"\tAllocationBase: 0x{addr_data.AllocationBase:X}\n"
            f"\tAllocationProtect: 0x{addr_data.AllocationProtect:X}\n"
            f"\tRegionSize: 0x{addr_data.RegionSize:X}\n"
            f"\tState: 0x{addr_data.State:X}\n"
            f"\tProtect: 0x{addr_data.Protect:X}\n"
            f"\tType: 0x{addr_data.Type:X}\n"
        )

        if not addr_data.State == MEMORY_STATE.MEM_COMMIT:
            logger.error(
                f"Cannot load memory region containing address 0x{address:X}. "
                f"Memory state is {addr_data.State}"
            )
            return None

        return addr_data

    def _load_data_from_address(
        self,
        address: int,
        addr_data: MemoryInfo,
        size: Optional[int] = None,
    ) -> tuple[int, bytes]:
        """Load the data from the address."""
        # Align the requested address to the nearest 0x10 byte boundary before-hand, and then determine how
        # many bytes are afterwards.
        address_0x10_aligned = address - (address % 0x10)
        after_address_size = addr_data.RegionSize - (address_0x10_aligned - addr_data.BaseAddress)

        # We'll only read at most MAX_FRAME_SIZE bytes to keep it sensible, but we may not be able to read
        # more anyway, or may only request less.
        if size is None:
            _size = min(MAX_FRAME_SIZE, after_address_size)
        else:
            _size = min(MAX_FRAME_SIZE, min(size, after_address_size))

        # Finally, read the data at the address.
        _data = (ctypes.c_char * _size).from_address(address_0x10_aligned)
        return address_0x10_aligned, bytes(bytearray(_data))

    def _load_snapshot(self, tag):
        """Load snapshot data from the cache."""
        cache_data = self._memory_cache.get(tag)
        if cache_data is None:
            return

        prev_size = len(self.data)

        self.data = cache_data["data"]
        self.base_address = cache_data["base_address"]

        new_size = len(self.data)

        # Clear and re-populate the table.
        if new_size == prev_size:
            self._refresh_table()
        else:
            self._clear_table()
            self._populate_table()
        self._select_coord(0, cache_data.get("address", 0) % 0x10)

        dpg.configure_item("_snapshot_details_group", show=True)
        dpg.configure_item("_snapshot_details_text", show=True)
        dpg.configure_item(
            "_snapshot_details_timestamp",
            default_value=f"    Timestamp: {cache_data['timestamp']}",
        )

        self._selected_snapshot_tag = tag

    def _populate_table(self):
        data_chunks = list(chunks(self.data, COLUMNS))

        with dpg.table_row(parent="main_table"):
            with dpg.table(
                header_row=False,
                policy=dpg.mvTable_SizingFixedSame,
                no_host_extendX=True,
                borders_innerH=True,
                no_pad_innerX=True,
                no_pad_outerX=True,
                clipper=True,
            ):
                dpg.add_table_column()
                for i in range(len(data_chunks)):
                    with dpg.table_row():
                        dpg.add_selectable(
                            label=f"0x{self.base_address + COLUMNS * i:X}",
                            enabled=False,
                            tag=f"addr_{i}",
                        )

            with dpg.table(
                header_row=False,
                policy=dpg.mvTable_SizingFixedSame,
                no_host_extendX=True,
                borders_innerH=True,
                borders_outerH=True,
                borders_innerV=True,
                borders_outerV=True,
                clipper=True,
            ):
                for _ in range(COLUMNS):
                    dpg.add_table_column(no_resize=True)
                for i, chunk in enumerate(data_chunks):
                    with dpg.table_row():
                        for j, char_ in enumerate(chunk):
                            dpg.add_selectable(
                                label=f"{char_:02X}",
                                callback=self._select_byte,
                                tag=f"byte_{i}-{j}",
                                user_data=(i, j),
                            )
                            dpg.bind_item_handler_registry(f"byte_{i}-{j}", "byte_handler")

            with dpg.table(
                header_row=False,
                policy=dpg.mvTable_SizingFixedSame,
                no_host_extendX=True,
                borders_innerH=True,
                borders_outerH=True,
                borders_innerV=True,
                borders_outerV=True,
                clipper=True,
            ):
                for _ in range(COLUMNS):
                    dpg.add_table_column(no_resize=True)
                for i, chunk in enumerate(data_chunks):
                    with dpg.table_row():
                        for j, char_ in enumerate(chunk):
                            char_conv = chr(char_)
                            if not str.isprintable(char_conv):
                                char_conv = " "
                            dpg.add_selectable(
                                label=char_conv,
                                callback=self._select_str,
                                tag=f"str_{i}-{j}",
                                user_data=(i, j),
                            )

    def _popup_follow_pointer(self):
        # Get the bytes which correspond to the ptr value and then cast to an int.
        start_addr = self._select_bytes_start_addr - self.base_address
        ptr_bytes = self.data[start_addr : start_addr + BITS // 8]
        ptr = int.from_bytes(ptr_bytes, byteorder="little", signed=False)
        dpg.configure_item("option_popup", show=False)
        self.load_address(ptr)

    def _refresh_table(self):
        """Refresh the table with new data instead of removing the old data."""
        data_chunks = list(chunks(self.data, COLUMNS))
        for i, chunk in enumerate(data_chunks):
            dpg.configure_item(f"addr_{i}", label=f"0x{self.base_address + COLUMNS * i:X}")
            for j, char_ in enumerate(chunk):
                char_conv = chr(char_)
                if not str.isprintable(char_conv):
                    char_conv = " "
                dpg.configure_item(f"byte_{i}-{j}", label=f"{char_:02X}")
                dpg.configure_item(f"str_{i}-{j}", label=char_conv)

    def _select_byte(self, sender, app_data, user_data):
        self._select_coord(*user_data)

    def _select_coord(self, i: int, j: int):
        idx = i * COLUMNS + j
        selection_size = dpg.get_value("selection_size")
        self.prev_selected_coords = set(self.curr_selected_coords)
        self.curr_selected_coords = set()
        self._selected_bytes = self.data[idx : idx + selection_size]
        self._select_bytes_start_addr = self.base_address + idx
        dpg.set_value("address_input", hex(self._select_bytes_start_addr)[2:])
        if selection_size == 2:
            dpg.set_value(
                "_select_bytes_int16",
                str(int.from_bytes(self._selected_bytes, byteorder="little", signed=False)),
            )
            dpg.set_value(
                "_select_bytes_uint16",
                str(int.from_bytes(self._selected_bytes, byteorder="little", signed=True)),
            )
        elif selection_size == 4:
            dpg.set_value(
                "_select_bytes_int32",
                str(int.from_bytes(self._selected_bytes, byteorder="little", signed=False)),
            )
            dpg.set_value(
                "_select_bytes_uint32",
                str(int.from_bytes(self._selected_bytes, byteorder="little", signed=True)),
            )
        elif selection_size == 8:
            dpg.set_value(
                "_select_bytes_int64",
                str(int.from_bytes(self._selected_bytes, byteorder="little", signed=False)),
            )
            dpg.set_value(
                "_select_bytes_uint64",
                str(int.from_bytes(self._selected_bytes, byteorder="little", signed=True)),
            )
        for s in range(selection_size):
            x, y = ((idx + s) // COLUMNS, (idx + s) % COLUMNS)
            self.curr_selected_coords.add((x, y))
            try:
                dpg.set_value(f"byte_{x}-{y}", True)
                dpg.set_value(f"str_{x}-{y}", True)
            except SystemError:
                pass
        for coord in self.prev_selected_coords - self.curr_selected_coords:
            x, y = coord
            try:
                dpg.set_value(f"byte_{x}-{y}", False)
                dpg.set_value(f"str_{x}-{y}", False)
            except SystemError:
                pass

    def _select_snapshot(self, sender, app_data):
        self._load_snapshot(app_data)

    def _select_str(self, sender, app_data, user_data):
        self._select_coord(*user_data)

    def _setup(self):
        with dpg.theme() as table_theme:
            with dpg.theme_component(dpg.mvTable):
                dpg.add_theme_style(
                    dpg.mvStyleVar_SelectableTextAlign,
                    0.5,
                    0.5,
                    category=dpg.mvThemeCat_Core,
                )
                dpg.add_theme_color(
                    dpg.mvThemeCol_HeaderHovered,
                    (255, 0, 0, 100),
                    category=dpg.mvThemeCat_Core,
                )
                dpg.add_theme_color(
                    dpg.mvThemeCol_HeaderActive,
                    (0, 255, 0, 100),
                    category=dpg.mvThemeCat_Core,
                )
                dpg.add_theme_color(dpg.mvThemeCol_Header, (0, 0, 255, 100), category=dpg.mvThemeCat_Core)

        with dpg.value_registry():
            # Options
            dpg.add_string_value(tag="address_input", default_value="10")
            dpg.add_int_value(tag="selection_size", default_value=4)
            # Selected value values
            dpg.add_string_value(tag="_select_bytes_int16", default_value="N/A")
            dpg.add_string_value(tag="_select_bytes_uint16", default_value="N/A")
            dpg.add_string_value(tag="_select_bytes_int32", default_value="N/A")
            dpg.add_string_value(tag="_select_bytes_uint32", default_value="N/A")
            dpg.add_string_value(tag="_select_bytes_int64", default_value="N/A")
            dpg.add_string_value(tag="_select_bytes_uint64", default_value="N/A")

        self._setup_rightclick_handlers()

        # with dpg.handler_registry(tag="table_keypress_handlers"):
        #     dpg.add_key_press_handler(dpg.mvKey_Down, callback=self._press_down)
        #     dpg.add_key_press_handler(dpg.mvKey_Up, callback=self._press_up)
        #     dpg.add_key_press_handler(dpg.mvKey_Left, callback=self._press_left)
        #     dpg.add_key_press_handler(dpg.mvKey_Right, callback=self._press_right)

        with dpg.window(label="popup", tag="option_popup", popup=True, show=False, no_title_bar=True):
            dpg.add_button(label="Follow pointer", callback=self._popup_follow_pointer)

        with dpg.group(parent=self.parent, horizontal=True):
            dpg.add_text("Saved memory snapshots:")
            dpg.add_combo(
                items=list(self._memory_cache.keys()),
                callback=self._select_snapshot,
                tag="_snapshot_dropdown",
            )

        with dpg.group(parent=self.parent, show=False, tag="_snapshot_details_group"):
            dpg.add_text("Snapshot details:", show=False, tag="_snapshot_details_text")
            dpg.add_text("    Timestamp: N/A", tag="_snapshot_details_timestamp")
            dpg.add_button(label="Delete", callback=self._delete_snapshot)

        with dpg.group(parent=self.parent, horizontal=True):
            dpg.add_text("Address: 0x")
            dpg.add_input_text(
                source="address_input",
                callback=self._change_address,
                hexadecimal=True,
                on_enter=True,
            )

        with dpg.group(parent=self.parent, horizontal=True):
            dpg.add_text("Selection size:")
            dpg.add_input_int(
                source="selection_size",
                callback=self._change_selection_size,
                min_value=1,
                min_clamped=True,
            )

        _main_table = dpg.add_table(
            parent=self.parent,
            tag="main_table",
            header_row=True,
            borders_innerV=True,
            policy=dpg.mvTable_SizingFixedFit,
            scrollY=True,
            freeze_rows=1,
            context_menu_in_body=True,
            clipper=True,
        )

        dpg.add_table_column(
            label="Address",
            tag="col_address",
            no_resize=True,
            width_fixed=True,
            parent="main_table",
        )
        dpg.add_table_column(
            label="Hex",
            tag="col_bytes",
            parent="main_table",
        )
        dpg.add_table_column(
            label="Decoded",
            tag="col_string",
            parent="main_table",
            width_fixed=True,
        )

        self._populate_table()

        dpg.bind_item_theme(_main_table, table_theme)

        with dpg.group(parent=self.parent, horizontal=True, tag="size_2_values", show=False):
            dpg.add_text("int16:")
            dpg.add_text(source="_select_bytes_int16")
            dpg.add_text("uint16:")
            dpg.add_text(source="_select_bytes_uint16")
        with dpg.group(parent=self.parent, horizontal=True, tag="size_4_values", show=True):
            dpg.add_text("int32:")
            dpg.add_text(source="_select_bytes_int32")
            dpg.add_text("uint32:")
            dpg.add_text(source="_select_bytes_uint32")
        with dpg.group(parent=self.parent, horizontal=True, tag="size_8_values", show=False):
            dpg.add_text("int64:")
            dpg.add_text(source="_select_bytes_int64")
            dpg.add_text("uint64:")
            dpg.add_text(source="_select_bytes_uint64")
        dpg.add_text("Invalid size selected", parent=self.parent, tag="size_inv_values", show=False)

    def _setup_rightclick_handlers(self):
        with dpg.item_handler_registry(tag="byte_handler"):
            dpg.add_item_clicked_handler(dpg.mvMouseButton_Right, callback=self._clicked_on)
