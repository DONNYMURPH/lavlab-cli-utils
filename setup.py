"""Build the dependency-free wheel containing the Nuitka executable."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

from build_native import omero_ice_modules


class build_py(_build_py):
    """Compile lavlab before setuptools copies package data into the wheel."""

    def run(self):
        output_dir = Path(__file__).parent / "lavlab" / "bin"
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
            str(Path(__file__).parent / "lavlab" / "__main__.py"),
        ]
        command[3:3] = [f"--include-module={name}" for name in omero_ice_modules()]

        extra_args = os.environ.get("LAVLAB_NUITKA_ARGS", "")
        if extra_args:
            command[3:3] = extra_args.split()

        subprocess.run(command, check=True)
        super().run()

        compiled_binary = output_dir / "lavlab-bin"
        if not compiled_binary.is_file():
            raise RuntimeError(f"Nuitka did not produce the expected binary: {compiled_binary}")


setup(cmdclass={"build_py": build_py})