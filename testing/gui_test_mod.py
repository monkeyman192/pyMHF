import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import dearpygui.dearpygui as dpg

from pymhf import Mod, ModState
from pymhf.gui.decorators import BOOLEAN, ENUM, FLOAT, INTEGER, STRING, gui_button, gui_group
from pymhf.gui.widgets import CustomWidget, WidgetBehaviour


class eLanguageRegion(IntEnum):
    English = 0x0
    USEnglish = 0x1
    French = 0x2
    Italian = 0x3
    German = 0x4
    Spanish = 0x5
    Russian = 0x6
    Polish = 0x7
    Dutch = 0x8
    Portuguese = 0x9
    LatinAmericanSpanish = 0xA
    BrazilianPortuguese = 0xB
    Japanese = 0xC
    TraditionalChinese = 0xD
    SimplifiedChinese = 0xE
    TencentChinese = 0xF
    Korean = 0x10


@dataclass
class State(ModState):
    radius: float = 20
    theta: float = 0
    center_pos: tuple[float, float] = (200, 200)


class MovingCircle(CustomWidget):
    widget_behaviour = WidgetBehaviour.SEPARATE

    def __init__(self, colour: tuple[int, int, int, int] = (255, 0, 0, 255)):
        super().__init__()
        self.colour = colour
        self.center_pos = (200, 200)
        self.clicked_on = False

    def click_callback(self, sender, app_data, user_data):
        self.clicked_on = True

    def release_mouse(self, sender, app_data, user_data):
        self.clicked_on = False

    def draw(self):
        dpg.add_text("Example canvas:")
        with dpg.drawlist(width=500, height=300) as dl:
            self.ids["DRAWLIST"] = dl
            self.ids["BORDER"] = dpg.draw_rectangle(
                pmin=(0, 0),
                pmax=(500, 300),
                color=(255, 255, 255, 255),
                fill=(0, 0, 0, 0),
                thickness=1,
            )
            self.ids["DOT"] = dpg.draw_circle(
                center=self.center_pos,
                radius=2,
                color=self.colour,
                fill=self.colour,
            )
            self.ids["CIRCLE"] = dpg.draw_circle(
                center=(self.center_pos[0] + 100, self.center_pos[1] + 100),
                radius=20,
                color=self.colour,
                fill=self.colour,
            )
        dpg.add_text("Change the value for theta and \nradius below to move the circle.")

        with dpg.item_handler_registry() as ihr:
            # Triggers for the left mouse button clicked event within the drawlist bounds
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Left,
                callback=self.click_callback,
            )
        with dpg.handler_registry():
            dpg.add_mouse_release_handler(callback=self.release_mouse)

        dpg.bind_item_handler_registry(self.ids["DRAWLIST"], ihr)

    def redraw(self, theta: float, radius: float, center_pos: Optional[tuple[float, float]] = None):
        if self.clicked_on:
            self.center_pos = tuple(dpg.get_drawing_mouse_pos())
        elif center_pos:
            self.center_pos = center_pos
        x = self.center_pos[0] + 50 * math.cos(theta)
        y = self.center_pos[1] + 50 * math.sin(theta)

        # Update the circle's position using configure_item
        dpg.configure_item(self.ids["DOT"], center=self.center_pos)
        dpg.configure_item(self.ids["CIRCLE"], center=(x, y), radius=radius)
        return {"center_pos": self.center_pos}


class GUITest(Mod):
    __author__ = "monkeyman192"
    __description__ = "Test globals"
    mod_state = State()

    def __init__(self):
        super().__init__()
        self._enum_val = eLanguageRegion.Japanese
        self._walk_speed = 10
        self.t = 0
        self.r = 20

    @property
    @MovingCircle((255, 0, 123, 255))
    def circle_loc(self):
        return {
            "theta": self.mod_state.theta,
            "radius": self.mod_state.radius,
            "center_pos": self.mod_state.center_pos
        }

    @circle_loc.setter
    def circle_loc(self, value):
        self.mod_state.center_pos = value["center_pos"]

    @property
    @FLOAT("Theta", is_slider=True, min_value=0, max_value=2 * math.pi)
    def theta(self):
        return self.mod_state.theta

    @theta.setter
    def theta(self, value):
        self.mod_state.theta = value

    @property
    @FLOAT("Radius", is_slider=True, min_value=0, max_value=50)
    def radius(self):
        return self.mod_state.radius

    @radius.setter
    def radius(self, value):
        self.mod_state.radius = value

    with gui_group("Some a fields"):
        @property
        @FLOAT("Walk speed")
        def ground_walk_speed(self):
            return self._walk_speed

        @ground_walk_speed.setter
        def ground_walk_speed(self, value):
            self._walk_speed = value

        @property
        @FLOAT("Run speed")
        def ground_run_speed(self):
            return 2 * self._walk_speed

        @property
        @FLOAT("Jetpack fuel")
        def jetpack_fuel(self):
            return 42

        @property
        @MovingCircle((0, 0, 255, 255))
        def circle_loc2(self):
            return {
                "theta": 2 * self.mod_state.theta,
                "radius": 2 * self.mod_state.radius,
            }

        @property
        @INTEGER("Voxel X")
        def voxel_x(self):
            return 1

        with gui_group("Some subfields"):
            @property
            @MovingCircle((255, 0, 255, 255))
            def circle_loc3(self):
                return {
                    "theta": 3 * self.mod_state.theta,
                    "radius": 3 * self.mod_state.radius,
                }

            @gui_button("Do the thing? 77")
            def the_thing99(self):
                print("AABBA Doing the thing...???")

            @gui_button("Do the thing?")
            def the_thing(self):
                print("AAA Doing the thing...!!")

            @gui_button("Add 10 nanites")
            def add_nanites(self):
                print("Button pressed")

    @property
    @BOOLEAN("Player is running!!!")
    def player_is_running(self):
        return True

    @property
    @STRING("The language:")
    def readonly_enum(self):
        return self._enum_val.name

    @property
    @ENUM("Editable enum:", eLanguageRegion)
    def editable_enum(self):
        return self._enum_val

    @editable_enum.setter
    def editable_enum(self, value):
        print(f"Setting {self._enum_val} to {value!r}")
        self._enum_val = value
