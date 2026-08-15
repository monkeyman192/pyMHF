# /// script
# dependencies = ["pymhf[gui,http_api]"]
#
# [tool.pymhf]
# exe = "Notepad.exe"
# start_paused = false
# start_exe = false
# interactive_console = false
#
# [tool.pymhf.logging]
# log_dir = "."
# log_level = "debug"
# ///

from dataclasses import dataclass
from logging import getLogger

from pydantic import BaseModel

from pymhf import Mod, ModState, load_mod_file
from pymhf.core.http_api import endpoint

logger = getLogger("http_mod")


class MoneyData(BaseModel):
    currency: str
    amount: float


@dataclass
class State(ModState):
    user: str = "unknown"
    currency: str = "None"
    amount: float = 0


class HTTPMod(Mod):
    state = State()

    @property
    @endpoint()
    def user(self):
        return self.state.user

    @user.setter
    def user(self, user: str):
        self.state.user = user

    @property
    @endpoint()
    def currency(self):
        logger.info("Getting currency")
        return self.state.currency

    @property
    @endpoint()
    def amount(self):
        return self.state.amount

    @endpoint(method="PUT")
    def set_money_data(self, payload: MoneyData):
        self.state.currency = payload.currency
        self.state.amount = payload.amount


if __name__ == "__main__":
    load_mod_file(__file__)
