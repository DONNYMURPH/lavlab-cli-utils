# SPDX-FileCopyrightText: 2026-present LavLab <domurphy@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""Build the standalone Nuitka executable with OMERO's dynamic Ice modules."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PYDICOM_NUITKA_FLAGS = [
    "--include-module=pydicom.pixels.decoders.gdcm",
    "--include-module=pydicom.pixels.decoders.pillow",
    "--include-module=pydicom.pixels.decoders.pyjpegls",
    "--include-module=pydicom.pixels.decoders.pylibjpeg",
    "--include-module=pydicom.pixels.decoders.rle",
    "--include-module=pydicom.pixels.encoders.gdcm",
    "--include-module=pydicom.pixels.encoders.native",
    "--include-module=pydicom.pixels.encoders.pyjpegls",
    "--include-module=pydicom.pixels.encoders.pylibjpeg",
    "--include-package-data=pydicom",
]


def omero_ice_modules() -> list[str]:
    """Find generated OMERO Ice modules that IceImport loads dynamically."""
    modules = set()
    for search_path in map(Path, sys.path):
        if not search_path.is_dir():
            continue
        modules.update(path.stem for path in search_path.glob("*_ice.py"))
    return sorted(modules)


def main() -> None:
    project_dir = Path(__file__).parent
    output_dir = Path(os.environ.get("LAVLAB_OUTPUT_DIR", project_dir / "native"))
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        "--assume-yes-for-downloads",
        f"--output-dir={output_dir}",
        "--output-filename=lavlab-bin",
        "--include-package=lavlab",
        "--include-package-data=lavlab",
        *PYDICOM_NUITKA_FLAGS,
        *[f"--include-module={name}" for name in omero_ice_modules()],
        str(project_dir / "lavlab" / "__main__.py"),
    ]

    extra_args = os.environ.get("LAVLAB_NUITKA_ARGS", "")
    if extra_args:
        command[3:3] = extra_args.split()

    print(f"Including {len(omero_ice_modules())} generated OMERO Ice modules.")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()