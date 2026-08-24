"""Execute the bundled native lavlab binary without importing runtime packages."""

from __future__ import annotations

import os
import sys
from importlib.resources import files


def main() -> None:
    binary = files("lavlab").joinpath("bin", "lavlab-bin")
    if not binary.is_file():
        raise RuntimeError(
            "The lavlab native binary is missing. This package must be installed "
            "from a platform wheel, not a source checkout."
        )

    os.execv(str(binary), [str(binary), *sys.argv[1:]])