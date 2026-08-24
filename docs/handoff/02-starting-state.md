# Starting state (before this session)

This matters because the first thing that happened in this session was
discovering the repo was **much further along than its folder name
suggested**. Don't assume a repo called `omero-cli-utils` with a vague name
is a blank scaffold — this one had a working package, a working (if
partially untested) Nuitka build, and a design spec.

## What already existed

- **A working `lavlab` package** at `lavlab/` (flat layout, not `src/`),
  with `lavlab lr`, `lavlab roi`, `lavlab meta` fully implemented:
  - `lavlab/cli.py` — argparse entry point
  - `lavlab/commands/{lr,roi_cmd,meta}.py` — one module per command group,
    following a consistent pattern: `add_parser(subparsers)` registers
    flags and a `handler`, a `run(args)` function does the work, batch modes
    use a `multiprocessing.Pool` with per-worker OMERO connections
  - `lavlab/commands/_shared.py` — shared argparse helpers
    (`add_creds_args`, `connect_from_args`, `load_fs_map_from_args`,
    `ensure_parent_dir`, `parse_target`, `group_of`)
  - `lavlab/config.py` — `OmeroCreds` resolution (CLI flag > env var >
    error) and `fs_map` YAML loading
  - `lavlab/omero_client.py` — `connect()` with retry/backoff, dummy-group
    (`-1`) lookup then per-object group switching, `iter_image_ids`,
    `get_source_file_path`
  - `lavlab/naming.py` — output filename convention:
    `LR${downsample}_${stem}(_${suffix}).${ext}`
  - `lavlab/imaging.py`, `lavlab/roi.py`, `lavlab/palettes.py` — the actual
    image-loading/rasterization/color-matching logic

- **A working Nuitka build**, already wired into `setup.py`
  (`build_py.run()` shells out to `python -m nuitka --standalone --onefile
  ... lavlab/__main__.py`, producing `lavlab/bin/lavlab-bin`) and
  `build_native.py` (a standalone script doing the same thing, plus a
  helper that discovers OMERO's dynamically-loaded `*_ice.py` modules so
  Nuitka's static analysis doesn't miss them).

- **`pyproject.toml`** with `[build-system]` already listing Nuitka +
  runtime deps, `[project]` name `lavlab-cli-utils` version `0.1.0`,
  `[project.scripts] lavlab = "lavlab.launcher:main"`, and
  `[tool.cibuildwheel]` configured for `cp310`–`cp314` on
  `linux-x86_64`/`macos-arm64`. **`dependencies = []`** — intentional, since
  the wheel ships a self-contained binary, but this meant there was no way
  to `pip install` what you'd need to run from source.

- **`design.md`** — the spec `lr`/`roi`/`meta` were built against. Contains
  the lab's naming convention, the `fs_map` YAML format, and explicit
  instructions like *"use the dummy group (-1) to get all objects, then
  switch to the group of a given object when operating on it"* and *"this
  will eventually be packaged in nuitka so make things proper python"* —
  both of which shaped decisions made this session too.

- **No git repo, no README, no LICENSE, no `.gitignore`, no CI, no
  `tests/`.**

- **Loose ad-hoc scripts at the repo root**, predating the `lavlab`
  package: `batch_lr.py`, `batch_roi.py`, `getLargeRecon.py`,
  `single_roi.py` (superseded by `lr`/`roi`), `dcmseg2nii.py` (DICOM
  SEG→NIfTI, **no** `lavlab` counterpart at the time), plus scratch
  notebooks (`omero_roi_comment.ipynb`, `test.ipynb`, `testing.ipynb`) and a
  `test.json` (a dcmqi segment-attributes template used by `test.ipynb`).

## The two pieces of raw material folded in this session

### 1. A separately-built `omero_geojson` project

The user had already built, independently, a complete small package for
moving QuPath GeoJSON annotations in and out of OMERO. It arrived as five
loose files (not yet part of this repo):

- `__about__.py` — a version string
- `__init__.py` — public API re-exports
- `geometry.py` — pure-Python geometry helpers (no `omero` import): RGB↔OMERO
  color packing, `points`-string↔ring conversion, and critically
  `bridge_hole`/`unbridge_ring`, which work around OMERO's polygon model
  having no concept of an interior ring by splicing a hole in as a
  zero-width "keyhole" slit
- `geojson_io.py` — GeoJSON reading/writing/conversion to and from an
  OMERO-agnostic `ShapeSpec`/`Annotation` representation (also no `omero`
  import — this is why `--dry-run` could work with no server)
- `omero_io.py` — the thin layer that actually imports `omero` and talks to
  the server (`build_roi`, `import_annotations`, `read_shape`,
  `export_image`, `match_by_name`, `iter_images`); had its own `connect()`
  taking `(server, user, password, port)` directly
- `cli.py` — a **standalone** argparse program (`omero-geojson import ...`
  / `omero-geojson export ...`) with its own `--server/--user/--password/
  --port` flags and a `getpass` prompt fallback — i.e., it duplicated
  functionality `lavlab` already had, just built independently.

This was a mature, well-documented, well-designed piece of code — the
docstrings throughout explain real design tradeoffs (why holes are bridged
rather than dropped, why coordinate precision needed explicit formatting
instead of `%g`, why provenance goes in `Roi.description` instead of a
`MapAnnotation`). Nothing about its actual conversion logic needed to
change; only its CLI/connection-handling surface needed to be reconciled
with `lavlab`'s existing conventions.

### 2. `dcmseg2nii.py` + a notebook cell

`dcmseg2nii.py` (DICOM SEG → NIfTI, splitting a segmentation object into one
NIfTI file per segment) was a clean, already-functional module — but a bare
script, never wired to any CLI, and with no `lavlab` counterpart.

The reverse direction (NIfTI mask → DICOM SEG) existed only as a single
hardcoded cell in `legacy/test.ipynb`, using `pydicom_seg.MultiClassWriter`
against a fixed local `test.json` dcmqi metainfo template, a fixed
"Prostate Mask" segment label, and a fixed `PatientComments` string — none
of it parameterized, none of it CLI-ready. This is the piece that required
real design work rather than a file move — see
[04-key-decisions.md](04-key-decisions.md) for what that became.
