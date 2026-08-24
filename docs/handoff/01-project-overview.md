# Project overview

## What this is

`lavlab-cli-utils` (distribution name) / `lavlab` (import name and console
command) is a command-line toolbox for a research lab (LavLab, Medical
College of Wisconsin) that works with whole-slide imaging data stored in
[OMERO](https://www.openmicroscopy.org/omero/). It is meant to be handed to
lab members as a `pip install`-able tool — either as source (for
development) or as a **Nuitka-compiled standalone binary** bundled inside a
wheel (for end users, who shouldn't need to manage a Python environment or
OMERO's native Ice dependencies at all).

The repo folder is named `omero-cli-utils`, but the actual Python
package/distribution inside it is named `lavlab` / `lavlab-cli-utils`. This
mismatch is intentional and was a deliberate decision — see
[04-key-decisions.md](04-key-decisions.md).

## The five command groups

All are subcommands of one `lavlab` CLI (argparse-based, built in
`lavlab/cli.py`):

| Command | Talks to OMERO? | What it does |
|---|---|---|
| `lavlab lr` | yes | Pull large-recon (downsampled) whole-slide images from OMERO to disk |
| `lavlab roi` | yes | Render OMERO ROI annotations to a raster mask (RGB or single-channel palette) |
| `lavlab meta roi textvalue` | yes | Backfill blank ROI `textValue` comments by matching stroke color to a palette |
| `lavlab geojson import` / `export` | yes | Move QuPath GeoJSON annotations in and out of OMERO as ROIs |
| `lavlab seg dcm2nii` / `nii2dcm` | **no** | Convert between DICOM SEG objects and NIfTI segmentation masks (local files only) |

`lr`, `roi`, and `meta` existed before this session. `geojson` and `seg`
were added during this session — see
[02-starting-state.md](02-starting-state.md) for what they were built from,
and [03-what-was-built.md](03-what-was-built.md) for exactly what changed.

## High-level repo layout

```
omero-cli-utils/
├── lavlab/                  # the actual Python package
│   ├── cli.py                # top-level argparse entry point, wires up all 5 command groups
│   ├── __main__.py            # `python -m lavlab`, and Nuitka's compile target
│   ├── launcher.py            # console-script that execs the compiled binary (wheel install path)
│   ├── commands/               # one module per command group -- argparse + orchestration only
│   ├── geojson/                 # GeoJSON<->OMERO conversion logic (no argparse, no CLI concerns)
│   ├── seg.py                   # DICOM SEG<->NIfTI conversion logic
│   ├── config.py, omero_client.py, naming.py, imaging.py, roi.py, palettes.py
│   │                            # shared helpers used across command groups
│   └── data/                    # bundled default config (fs_map, seg template)
├── tests/                    # pytest suite
├── legacy/                   # superseded ad-hoc scripts/notebooks, kept for reference only
├── docs/handoff/              # <- you are here
├── pyproject.toml, setup.py, build_native.py, build-requirements.txt
│                            # packaging + the Nuitka build
├── design.md                 # the original spec lr/roi/meta were built against
├── README.md, LICENSE, .gitignore
```

See [08-repo-map.md](08-repo-map.md) for the complete file-by-file listing.

## The packaging/build model (why it matters)

This is not a typical "just `pip install` and get Python files" package.
`setup.py` overrides setuptools' `build_py` command to shell out to Nuitka
(`python -m nuitka --standalone --onefile ...`) and compile
`lavlab/__main__.py` into a single native executable, which gets bundled
into the wheel as package data (`lavlab/bin/lavlab-bin`). The `lavlab`
console-script entry point (`lavlab.launcher:main`) doesn't run Python code
at all in that installed wheel — it just `os.execv`s the compiled binary.
This is why a source checkout (`pip install -e ".[dev]"`) and a wheel
install behave differently: source checkouts run the real Python CLI via
`python -m lavlab`; wheel installs run the compiled binary via `lavlab`.

`cibuildwheel` is already configured in `pyproject.toml` to build this for
`linux-x86_64` and `macos-arm64`. No CI workflow actually invokes it yet —
that's on the next-steps list.
