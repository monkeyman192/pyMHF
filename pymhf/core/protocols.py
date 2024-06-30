import asyncio
from typing import Union

# This escape sequence is arbitrarily the first 4 digits of Euler's number "e"
# written as bytes from left to right.
ESCAPE_SEQUENCE = b"\x02\x07\x01\x08"
# The "ready" sequence is arbitrarily the first 4 digits of pi written as bytes
# from left to right.
READY_ASK_SEQUENCE = b"\x01\x04\x01\x03"
READY_ACK_SEQUENCE = b"\x06\x02\x09\x05"


class ExecutionEndedException(Exception):
    pass


def custom_exception_handler(loop: asyncio.AbstractEventLoop, context: dict):
    # Simple custom exception handler to stop the loop if an
    # ExecutionEndedException exception is raised.
    exception = context.get("exception")
    if isinstance(exception, ExecutionEndedException):
        loop.stop()


class TerminalProtocol(asyncio.Protocol):
    def __init__(self, message: Union[str, bytes], future):
        super().__init__()
        self.message = message
        self._is_raw = isinstance(self.message, bytes)
        self.future = future
        self._ready_ackd = False

    def connection_made(self, transport):
        self.transport = transport
        if self._is_raw:
            transport.write(self.message)
        else:
            transport.write(self.message.encode())
        if transport.can_write_eof():
            transport.write_eof()

    def data_received(self, data: bytes):
        if data == READY_ACK_SEQUENCE:
            self._ready_ackd = True
            print("READY ACKNOWLEDGED!!!")
        else:
            print(data.decode(), end="")

    def eof_received(self):
        self.transport.close()
        if not self.future.done():
            self.future.set_result(True)

    def connection_lost(self, exc):
        self.transport.close()
        if not self.future.done():
            self.future.set_result(True)
        super().connection_lost(exc)
