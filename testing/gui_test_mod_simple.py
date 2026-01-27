import math

import dearpygui.dearpygui as dpg

from pymhf import Mod
from pymhf.gui.decorators import FLOAT
from pymhf.gui.widgets import CustomWidget, WidgetBehaviour


class MovingCircle(CustomWidget):
    # Specify that the widget will be drawn separately from the previous widget.
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
        # Create a DearPyGUI drawlist to draw a circle which follows the mouse when clicked.
        # This code is called when the widget is initially drawn in the GUI and when the
        # widget is reloded after the "reload" button is pressed.
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

        dpg.bind_item_handler_registry(self.ids["DRAWLIST"], ihr)

        with dpg.handler_registry():
            dpg.add_mouse_release_handler(callback=self.release_mouse)

    def redraw(self, theta: float, radius: float, center_pos: tuple[float, float]):
        # This function is called each frame the tab the widget belongs to is selected.
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

    def __init__(self):
        super().__init__()
        self._theta = 0
        self._radius = 10
        self.center_pos = (200, 200)

    @property
    @MovingCircle((255, 0, 123, 255))
    def circle_loc(self):
        return {
            "theta": self._theta,
            "radius": self._radius,
            "center_pos": self.center_pos
        }

    @circle_loc.setter
    def circle_loc(self, value):
        self.center_pos = value["center_pos"]

    @property
    @FLOAT("Theta", is_slider=True, min_value=0, max_value=2 * math.pi)
    def theta(self):
        return self._theta

    @theta.setter
    def theta(self, value):
        self._theta = value

    @property
    @FLOAT("Radius", is_slider=True, min_value=0, max_value=50)
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        self._radius = value
