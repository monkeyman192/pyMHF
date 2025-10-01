import argparse
import logging
import logging.handlers
import os
import os.path as op
import pickle
import platform
import select
import socketserver
import struct
import time

import pymhf

# Logo generated using https://patorjk.com/software/taag/
# Options:
# Font: Varsity
# Character Width: Full
# Character Height: Full
LOGO = r"""
 _______    ____  ____   ____    ____   ____  ____   ________  
|_   __ \  |_  _||_  _| |_   \  /   _| |_   ||   _| |_   __  | 
  | |__) |   \ \  / /     |   \/   |     | |__| |     | |_ \_| 
  |  ___/     \ \/ /      | |\  /| |     |  __  |     |  _|    
 _| |_        _|  |_     _| |_\/_| |_   _| |  | |_   _| |_     
|_____|      |______|   |_____||_____| |____||____| |_____|    
                                                               
"""


# NB: This code is mostly taken from the python stdlib docs.


class LogRecordStreamHandler(socketserver.StreamRequestHandler):
    """Handler for a streaming logging request.

    This basically logs the record using whatever logging policy is
    configured locally.
    """

    def handle(self):
        """
        Handle multiple requests - each expected to be a 4-byte length,
        followed by the LogRecord in pickle format. Logs the record
        according to whatever policy is configured locally.
        """
        try:
            while True:
                chunk = self.connection.recv(4)
                if len(chunk) < 4:
                    break
                slen = struct.unpack(">L", chunk)[0]
                chunk = self.connection.recv(slen)
                while len(chunk) < slen:
                    chunk = chunk + self.connection.recv(slen - len(chunk))
                obj = self.unPickle(chunk)
                record = logging.makeLogRecord(obj)
                self.handleLogRecord(record)
        except ConnectionResetError:
            return

    def unPickle(self, data):
        return pickle.loads(data)

    def handleLogRecord(self, record):
        # If a name is specified, we use the named logger rather than the one
        # implied by the record.
        if self.server.logname is not None:
            name = self.server.logname
        else:
            name = record.name
        logger = logging.getLogger(name)
        # N.B. EVERY record gets logged. This is because Logger.handle
        # is normally called AFTER logger-level filtering. If you want
        # to do filtering, do it at the client end to save wasting
        # cycles and network bandwidth!
        logger.handle(record)


class LogRecordSocketReceiver(socketserver.ThreadingTCPServer):
    """
    Simple TCP socket-based logging receiver suitable for testing.
    """

    allow_reuse_address = True

    def __init__(
        self,
        host="localhost",
        port=logging.handlers.DEFAULT_TCP_LOGGING_PORT,
        handler=LogRecordStreamHandler,
    ):
        socketserver.ThreadingTCPServer.__init__(self, (host, port), handler)
        self.abort = 0
        self.timeout = 1
        self.logname = None

    def serve_until_stopped(self):
        abort = 0
        try:
            while not abort:
                rd, _, _ = select.select([self.socket.fileno()], [], [], self.timeout)
                if rd:
                    self.handle_request()
                abort = self.abort
        except KeyboardInterrupt:
            print("Ending logging server...")


def main(logdir: str):
    formatter = logging.Formatter("%(asctime)s %(name)-24s %(levelname)-6s %(message)s")
    os.makedirs(logdir, exist_ok=True)
    # TODO: Need to make this strip the ANSI escape chars from the written log
    file_handler = logging.FileHandler(
        op.join(logdir, f"pymhf-{time.strftime('%Y%m%dT%H%M%S')}.log"), encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    tcpserver = LogRecordSocketReceiver()
    print(LOGO)
    print(f"pyMHF Version: {pymhf.__version__}")
    print(f"Python version: {platform.python_version()}")
    print("Logger waiting for backend process... Please wait...")
    tcpserver.serve_until_stopped()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to place the log files")
    args = parser.parse_args()
    main(args.path)
