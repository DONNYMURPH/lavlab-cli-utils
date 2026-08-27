

from __future__ import annotations

import os
import sys

_BUNDLE_DIRNAME = "lavlab_native_libs"
_SEARCH_PATH_ENV_VAR = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"


def ensure_bundled_libraries_on_search_path() -> None:
    """Re-exec this process once with the bundled native-libs directory on
    the dynamic linker's search path, if this build has one.

    A no-op when running from a source checkout (``python -m lavlab``) or
    any build that didn't bundle native libraries -- there's nothing to
    add, and plain ``pyvips`` will find a system-installed libvips on its
    own in that case. Also a no-op if the search path already contains the
    bundle directory, which is what prevents this from re-exec'ing forever
    once it's already taken effect.
    """
    bundle_dir = os.path.join(os.path.dirname(sys.executable), _BUNDLE_DIRNAME)
    if not os.path.isdir(bundle_dir):
        return

    current = os.environ.get(_SEARCH_PATH_ENV_VAR, "")
    if bundle_dir in current.split(os.pathsep):
        return

    os.environ[_SEARCH_PATH_ENV_VAR] = (
        f"{bundle_dir}{os.pathsep}{current}" if current else bundle_dir
    )
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
