# SPDX-FileCopyrightText: 2026-present LavLab <domurphy@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""Build the standalone Nuitka executable with OMERO's dynamic Ice modules."""

from __future__ import annotations

import os
import shutil
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


def restore_unpatched_vips(dist_dir: Path) -> None:
    """Undo Nuitka's RPATH rewrite of pyvips' bundled libvips.

    Nuitka runs ``patchelf --set-rpath '$ORIGIN'`` over every shared object it
    bundles. On Linux that rewrite corrupts pyvips' statically linked libvips:
    the patched library segfaults inside its ELF constructor as soon as
    anything dlopens it, which takes down every command that imports pyvips.
    Copying the pristine wheel copy back over Nuitka's patched one fixes it.
    Dropping the RPATH costs nothing: libvips links only against system
    libraries (libc, libstdc++, libm, libdl, libpthread, libgcc_s, libresolv),
    so it has nothing to resolve out of the dist directory in the first place.

    macOS is unaffected. Nuitka rewrites ``libvips.42.dylib`` there too, but
    the Mach-O rewrite produces a library that still loads, so this is a
    deliberate no-op on Darwin rather than an unhandled platform.
    """
    if sys.platform == "darwin":
        print("Skipping libvips restore: macOS rewrite is not corrupting.")
        return

    patched = sorted(dist_dir.glob("libvips*.so.*"))
    if not patched:
        return

    # pyvips[binary] has shipped its libraries under both names.
    pristine = [
        path
        for search_path in map(Path, sys.path)
        if search_path.is_dir()
        for libs_dir in ("pyvips_binary.libs", "pyvips.libs")
        for path in search_path.glob(f"{libs_dir}/libvips*.so.*")
    ]
    if not pristine:
        # Failing loudly matters here: silently shipping the patched library is
        # exactly the bug this function exists to prevent, and a corrupt
        # libvips only shows up as a crash at runtime on the user's machine.
        raise RuntimeError(
            f"Nuitka bundled {patched[0].name} but no pristine copy was found in "
            "pyvips_binary.libs/ or pyvips.libs/ to restore it from. Refusing to "
            "ship a libvips that patchelf may have corrupted."
        )

    by_name = {path.name: path for path in pristine}
    for target in patched:
        source = by_name.get(target.name, pristine[0])
        shutil.copy2(source, target)
        print(f"Restored unpatched {target.name} from {source}")


def main() -> None:
    project_dir = Path(__file__).parent
    output_dir = Path(os.environ.get("LAVLAB_OUTPUT_DIR", project_dir / "native"))
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
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
    restore_unpatched_vips(output_dir / "__main__.dist")


if __name__ == "__main__":
    main()