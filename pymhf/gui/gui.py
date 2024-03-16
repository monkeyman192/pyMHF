import dearpygui.dearpygui as dpg
from concurrent.futures import ThreadPoolExecutor
import time

from logging import getLogger


# logger = getLogger("GuiLogger")

def run():
    # logger.info("WELCOME!!!!")
    dpg.create_context()
    dpg.create_viewport(title='Custom Title', width=600, height=200)
    dpg.setup_dearpygui()

    with dpg.window(label="Example Window"):
        dpg.add_text("Hello, world")

    dpg.show_viewport()

    # below replaces, start_dearpygui()
    while dpg.is_dearpygui_running():
        # insert here any code you would like to run in the render loop
        # you can manually stop by using stop_dearpygui()
        # logger.info("this will run every frame")
        dpg.render_dearpygui_frame()

    dpg.destroy_context()

if __name__ == "__main__":
    gui_executor = ThreadPoolExecutor(1, thread_name_prefix="pyMHF_GUI")
    gui_future = gui_executor.submit(run)
    print("AAAA")
    print(gui_future)
    time.sleep(5)
    print("shutting down")
    gui_executor.shutdown(wait=False, cancel_futures=True)
    print("shut down?")
    print(gui_future)

