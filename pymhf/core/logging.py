import subprocess
from multiprocessing.connection import Connection

import psutil


class stdoutSocket:
    def __init__(self, connection: Connection):
        self.connection = connection

    def write(self, val):
        self.connection.send_bytes(val.encode())

    def flush(self):
        pass


def open_log_console(log_script: str, log_dir: str, name_override: str = "pymhf console") -> int:
    """Open the logging console and return the pid of it.

    Parameters
    ----------
    log_script
        Path to the logging script to be run.
    log_dir:
        Path where the log files will be written to.
    name_override:
        Name to override the default "pymhf console" window title.
    """
    # TODO: The following doesn't quite work... Need to figure out why.
    # The issue it is meant to fix is passing in non-ascii name overrides.
    # if '"' not in name_override:
    #     # Wrap the string explicitly in double quotation marks so that it will be used correctly in the case
    #     # of non-ascii characters.
    #     name_override = f'''"{name_override}"'''
    #     print(f"name override: {name_override!r}")
    # else:
    #     # For now, leave this as an edge case...
    #     pass
    cmd = ["cmd.exe", "/c", "start", name_override, "python", log_script, log_dir]
    with subprocess.Popen(cmd) as proc:
        log_ppid = proc.pid
    for proc in psutil.process_iter(["pid", "name", "ppid"]):
        if proc.info["ppid"] == log_ppid:
            return proc.info["pid"]
