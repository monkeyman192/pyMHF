from concurrent.futures import ThreadPoolExecutor
import os
import os.path as op

import pymhf.core._internal as _internal

# TODO: Move somewhere else? Not sure where but this doesn't really fit here...
executor: ThreadPoolExecutor = None  # type: ignore

mod_save_dir = op.join(_internal.CFG_DIR, "MOD_SAVES")
if not op.exists(mod_save_dir):
    os.makedirs(mod_save_dir)
