# SPDX-FileCopyrightText: 2026-present LavLab <domurphy@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""Build the dependency-free wheel containing the Nuitka executable."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

from build_native import (
    IMAGECODECS_NUITKA_FLAGS,
    PYDICOM_NUITKA_FLAGS,
    omero_ice_modules,
    restore_unpatched_vips,
)


class build_py(_build_py):
    """Compile lavlab before setuptools copies package data into the wheel."""

    def run(self):
        project_dir = Path(__file__).parent
        # Build outside the package. Nuitka's --include-package-data=lavlab
        # sweeps everything under lavlab/, so building straight into
        # lavlab/bin/ lets a previous build's dist folder get swept into the
        # next one (observed locally as a nested lavlab/bin/__main__.dist/
        # inside the dist itself).
        build_root = project_dir / "build" / "nuitka"
        staged_dist = project_dir / "lavlab" / "bin" / "dist"
        # Both have to go before Nuitka starts, not just before they are
        # rewritten: a previous run's staged dist lives under lavlab/, so
        # leaving it in place would feed it straight back into this build.
        for stale in (build_root, staged_dist):
            if stale.exists():
                shutil.rmtree(stale)
        build_root.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            "-m",
            "nuitka",
            "--standalone",
            "--assume-yes-for-downloads",
            f"--output-dir={build_root}",
            "--output-filename=lavlab-bin",
            "--include-package=lavlab",
            "--include-package-data=lavlab",
            *PYDICOM_NUITKA_FLAGS,
            *IMAGECODECS_NUITKA_FLAGS,
            str(project_dir / "lavlab" / "__main__.py"),
        ]
        command[3:3] = [f"--include-module={name}" for name in omero_ice_modules()]

        extra_args = os.environ.get("LAVLAB_NUITKA_ARGS", "")
        if extra_args:
            command[3:3] = extra_args.split()

        subprocess.run(command, check=True)

        nuitka_dist = build_root / "__main__.dist"
        restore_unpatched_vips(nuitka_dist)

        compiled_binary = nuitka_dist / "lavlab-bin"
        if not compiled_binary.is_file():
            raise RuntimeError(f"Nuitka did not produce the expected binary: {compiled_binary}")

        # Stage the standalone dist under a stable name the launcher and the
        # package-data glob can both rely on, on every platform.
        staged_dist.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(nuitka_dist, staged_dist, symlinks=True)
        staged_in_build_lib = Path(self.build_lib) / "lavlab" / "bin"
        if staged_in_build_lib.exists():
            shutil.rmtree(staged_in_build_lib)

        super().run()


setup(cmdclass={"build_py": build_py})