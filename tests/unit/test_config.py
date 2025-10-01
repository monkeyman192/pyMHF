import os.path as op
import tempfile

from pymhf.utils.config import canonicalize_setting

CWD = op.dirname(__file__)


def test_canonicalize_setting():
    # Create log directory in the current directory.
    assert canonicalize_setting(".", None, CWD, CWD, "logs") == op.join(CWD, "logs")
    assert canonicalize_setting("{CURR_DIR}", None, CWD, CWD, "logs") == op.join(CWD, "logs")

    with tempfile.TemporaryDirectory() as temp_dir:
        assert canonicalize_setting(temp_dir, None, CWD, CWD, "logs") == temp_dir
