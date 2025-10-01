import os
import os.path as op
import tempfile

import pytest

import pymhf

pytestmark = pytest.mark.skipif(os.environ.get("CI") is not None, reason="Flaky on CI")

MODS_DIR = op.realpath(op.join(op.dirname(__file__), "..", "test_mods"))
APPS_DIR = op.realpath(op.join(op.dirname(__file__), "..", "programs"))


def test_default_args():
    with tempfile.TemporaryDirectory() as tempdir:
        config = {
            "exe": op.join(APPS_DIR, "app.exe"),
            "start_paused": True,
            "start_exe": True,
            "interactive_console": False,
            "logging": {"log_dir": tempdir},
        }
        pymhf.main.REMOVE_SELF = False
        pymhf.load_mod_file(op.join(MODS_DIR, "app_test_mod.py"), config)

        log_files = os.listdir(tempdir)
        assert len(log_files) == 1
        log_file = log_files[0]
        important_lines = []
        with open(op.join(tempdir, log_file), "r") as f:
            for line in f:
                if "TestLogger" in line:
                    idx = line.find("INFO")
                    actual_val = line[idx + 4 :]
                    important_lines.append(actual_val.strip())
        assert important_lines == ["Doubling the inputs 2 and 3", "(2 * 2) * (3 * 2) = 24"]
