# Setup

1. Ensure that python 3.9+ is installed
1. Install the required dependencies. Run the following in the current directory: `python -m pip install .`
1. Modify `pymhf.cfg` to have the correct binary path. Note that currently the only supported binary is the one which has the hash listed in the file. You can check the hash of your NMS binary by running `certutil -hashfile "NMS.exe" SHA1` in the directory with the NMS.exe binary.
1. in a terminal run `python main.py`

You should have another popup appear with the pyMHF logo at the top, and then a series of log messages.
If this doesn't occur then your firewall may be blocking the port 6770, so make sure that a TCP connection is allowed on this port on your local network (ie. 127.0.0.0, or possibly 0.0.0.)

If all goes well you should see `"Serving on executor ('127.0.0.1', 6770)"`
Once you see this message you are fine to press anything in the other window where you entered `python main.py`.

Any exceptions will be logged to a file named `CRITICAL_ERROR.txt`, and logs will be placed in a `logs` directory.

- If you want to stop the application, you can press `ctrl + C` in the window you started the process in to kill it.