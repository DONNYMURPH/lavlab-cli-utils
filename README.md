# lavlab-cli-utils

LavLab's CLI toolbox for OMERO: pulling large-recon and ROI mask images,
moving QuPath GeoJSON annotations in and out of OMERO, filling in ROI
metadata, and converting between DICOM SEG and NIfTI segmentation masks.

More documentation lives in [`docs/`](docs/index.md):
[`docs/API.md`](docs/API.md) is the exhaustive flag-by-flag CLI reference
plus the importable Python API; [`CONTRIBUTING.md`](CONTRIBUTING.md) covers
development conventions; [`docs/handoff/`](docs/handoff/README.md) is a
detailed record of how the `geojson`/`seg` command groups came to exist and
why, useful if something here looks like an odd choice.

## Architecture, in brief

One Python package, `lavlab`, with five subcommands
(`lr`/`roi`/`meta`/`geojson`/`seg`) sharing common OMERO-connection and
argparse plumbing:

```text
lavlab/
├── cli.py                 top-level argparse entry point
├── commands/               one module per subcommand -- argparse + orchestration only
│   └── _shared.py            shared creds/output-path/connection helpers
├── geojson/                 GeoJSON<->OMERO conversion logic (no argparse in here)
├── seg.py                   DICOM SEG<->NIfTI conversion logic
├── omero_client.py, config.py, naming.py, imaging.py, roi.py, palettes.py
└── data/                    bundled default config, loaded via importlib.resources
```

The package is built to run two different ways, and it matters which one
you're using:

- **Compiled binary** (what a lab member installing a wheel gets): the
  `lavlab` console-script just `os.execv`s a self-contained native
  executable (`lavlab/launcher.py` -> `lavlab/bin/lavlab-bin`), compiled
  ahead of time with [Nuitka](https://nuitka.net). No Python environment,
  no `omero-py`, no Ice bindings needed on the machine running it.
- **Source checkout** (development): `python -m lavlab ...` runs the real
  Python CLI directly (`lavlab/__main__.py` -> `lavlab/cli.py`). This is
  what you use while developing, and it needs the full dependency stack
  installed (see below) since nothing is precompiled.

## Install

**From a built wheel** (recommended for end users):

```sh
pip install lavlab_cli_utils-<version>-<platform>.whl
lavlab --help
```

**From source, for development:**

```sh
pip install -e ".[dev]"
python -m lavlab --help
```

The `dev` extra (and the equivalent `requirements.txt`) installs everything
`lavlab` needs to run: `numpy`, `pyvips`, `tifffile`, `scikit-image`,
`PyYAML`, `tqdm`, `omero-py`, `highdicom`, `nibabel`, `SimpleITK`,
`pydicom`, `pytest`. **`omero-py` additionally needs the Glencoe/ZeroC Ice
wheel for your platform, installed separately first** -- it isn't on PyPI.
See `build-requirements.txt`'s comment for where to get it, or use the
[Docker build environment](#building-with-docker) below, which handles
this the same way.

## Connecting to OMERO

Every command that talks to OMERO (`lr`, `roi`, `meta`, `geojson` -- not
`seg`, which never touches OMERO) takes the same four flags, or reads the
same four environment variables:

| Flag | Env var | Meaning |
|---|---|---|
| `-u` / `--user` | `OMERO_USER` | your OMERO username |
| `-w` / `--password` | `OMERO_PASSWORD` | your OMERO password |
| `-s` / `--host` | `OMERO_HOST` | server hostname |
| `-p` / `--port` | `OMERO_PORT` | server port |

A CLI flag always wins over the matching environment variable. A missing
value from both is a hard error (`error: OMERO user was not provided: ...`)
-- there's no interactive password prompt.

**The OMERO group model:** object lookups happen in OMERO's "dummy group"
(`-1`), which makes objects visible across every group you belong to;
once a command is about to actually operate on a specific object, it
switches the connection into that object's real group. You don't need to
think about this day to day -- it's just why `lavlab lr 12345` works
regardless of which group image 12345 lives in, and why batch commands
accept `-g/--group` to scope a run to one group explicitly.

## Commands

The sections below give the shape of each command with the most common
flags; **[`docs/API.md`](docs/API.md) has every flag for every command**,
exhaustively.

### `lavlab lr` -- pull large-recon (downsampled) images

```sh
lavlab lr 12345 -o ./out/slide.jp2 --downsample 10 -s omero.example.edu -u you
lavlab lr batch -g 3 --workers 8 -s omero.example.edu -u you
```

"LR" is lab shorthand for a downsampled export of a whole-slide image.
Output filenames follow `LR${downsample}_${stem}.jp2`, where `stem` is the
image name with everything after the *first* `.` stripped (so
`foo.ome.tiff` -> `foo` -- this matters for OME-TIFFs specifically).

If you don't pass `-o`, output location falls back to `fs_map` -- a YAML
file mapping OMERO group -> filesystem destination by regex match on the
image name (`lavlab/data/default_fs_map.yaml` ships a lab default; `--fs-map
custom.yaml` overrides it). No match, or the mapped directory doesn't
exist on disk: single-image mode writes to the current directory instead;
batch mode skips that image and continues, warning rather than failing the
whole run. An `fs_map` entry whose `base_dir` doesn't exist at all *does*
abort the run -- that means the whole storage target is unmounted, not
just one path.

### `lavlab roi` -- pull ROI mask images

```sh
lavlab roi 12345 --all -o ./out/mask.jp2 -s omero.example.edu -u you
lavlab roi batch -g 3 -t tumor -t stroma --palette -s omero.example.edu -u you
```

Renders OMERO ROI annotations to a raster mask instead of pulling the
slide itself. You must pass either `--all` (every annotation) or one-or-more
`-t/--text-filter` values (a whitelist by the shape's `textValue`) --
"give me nothing" isn't a sensible default for a mask export, so the
command refuses to run with neither. `--palette` swaps the RGB color mask
for a single-channel label mask, numbered in the order your `-t` filters
were given; it's incompatible with `--all` since there's no sane numbering
for "everything."

### `lavlab meta roi textvalue` -- backfill ROI comments from stroke color

```sh
lavlab meta roi textvalue default 12345 12346 -s omero.example.edu -u you
lavlab meta roi textvalue ./my_palette.yaml -g 3 --tolerance 15 -s omero.example.edu -u you
```

The one command that edits ROIs in place rather than producing a file: for
each shape, it matches the stroke color against a palette (color -> label
name) and writes the label into `textValue` -- but only when that field is
currently blank, so it never overwrites something someone already typed.
`default` refers to a built-in palette; point it at your own YAML/JSON
instead if needed. `--tolerance` (default 10) is the per-channel color-match
slack, since colors don't always round-trip through OMERO's storage
byte-for-byte.

### `lavlab geojson import` / `export` -- QuPath GeoJSON <-> OMERO ROIs

```sh
lavlab geojson import slide.geojson --image 12345 -s omero.example.edu -u you
lavlab geojson import ./backups/ --dataset 5 -s omero.example.edu -u you       # match files to images by filename
lavlab geojson import --map restore.csv -s omero.example.edu -u you            # explicit path,image_id CSV -- the auditable choice

lavlab geojson export --project 2 --out ./archive/ --datestamp -s omero.example.edu -u you
```

QuPath draws annotations and exports them as GeoJSON; OMERO stores
annotations as ROI database rows. The two models disagree in ways that
lose data if you're not careful:

- **Holes.** OMERO's polygon has no concept of an interior ring -- a donut
  shape is just one flat point list. A hole gets "bridged" in as a
  zero-width slit cut from the outer ring to the nearest hole vertex,
  which renders correctly as a hole under the standard nonzero fill rule
  (`lavlab/geojson/geometry.py`'s `bridge_hole`). `export` reverses this
  automatically (`unbridge_ring`); `--keep-bridges` turns that off if you
  specifically want the raw bridged shape back.
- **Coordinate precision.** Whole-slide coordinates are large enough that
  naive `%g` formatting would silently round to 6 significant digits --
  on a slide past ~100,000px that's more than a pixel of drift on the
  majority of vertices. Coordinates are written out explicitly instead.
- **Provenance.** OMERO has nowhere to record "this ROI came from QuPath
  object such-and-such." A small JSON tag is stashed in `Roi.description`
  on import and read back out on export, so a round trip doesn't lose the
  original QuPath UUID.

`import` accepts exactly one of `--image` (single file), `--dataset`
(match files to images by filename), or `--map` (an explicit
`path,image_id` CSV -- reach for this one when it matters, since you can
eyeball it before running rather than trusting a filename match).
`export` accepts exactly one of `--image`, `--dataset`, or `--project`.
`--datestamp` writes into `<out>/YYYY-MM-DD/` so repeated archive runs
don't collide; without it, an existing output file blocks the run unless
you pass `--overwrite`.

### `lavlab seg dcm2nii` / `nii2dcm` -- DICOM SEG <-> NIfTI

```sh
lavlab seg dcm2nii segmentation.dcm reference.nii.gz --out ./out/
lavlab seg nii2dcm mask.nii.gz ./dicom_series/ --out ./mask_seg.dcm --label "Tumor" --comment "reviewed by X"
```

Local file conversion; neither direction talks to OMERO.

`dcm2nii` splits a DICOM SEG object into one NIfTI file per segment,
aligned to a reference NIfTI image, named
`<reference-stem>_<segment-name>.nii.gz`.

`nii2dcm` writes a NIfTI label mask back out as a DICOM SEG object.
Because a NIfTI file carries no patient/study/geometry metadata of its
own, you point it at the reference DICOM series the mask was drawn
against, and it borrows that. It writes a `LABELMAP`-type segmentation --
the modern multi-class variant of the DICOM SEG standard (one integer
label per voxel, `0` = background), as opposed to the older `BINARY`
variant (one frame stack per segment). What segments exist and how
they're described (label + SNOMED code) comes from a JSON template --
`lavlab/data/default_seg_template.json` unless you pass `--template
your.json`. **This is not the dcmqi metainfo format** if you've used
`dcmqi`/`pydicom-seg` templates before -- it's a simpler schema built
around `highdicom.seg.SegmentDescription`; see
[`docs/API.md`](docs/API.md#--template-schema-lavlab-seg-nii2dcm) for the
exact shape.

## Development

```sh
pip install -e ".[dev]"
pytest
```

Tests that need the imaging/DICOM stack (`SimpleITK`, `pydicom`) are
skipped automatically if those packages aren't installed; the GeoJSON
tests have no such dependency and always run. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the patterns to follow when
adding to this codebase.

## Building the compiled wheel

```sh
pip install -r build-requirements.txt   # + the Ice wheel for omero-py, see that file's comment
pip wheel . -w dist/
```

This shells out to Nuitka (`setup.py`'s `build_py` override, or run
`build_native.py` standalone if you just want the compiled binary without
a full wheel) to compile `lavlab/__main__.py` into a single standalone
executable, bundled into the wheel as `lavlab/bin/lavlab-bin`; the
`lavlab` console-script just execs it. `[tool.cibuildwheel]` in
`pyproject.toml` is already configured to build this for
`linux-x86_64`/`macos-arm64` across `cp310`-`cp314` (Windows and
musllinux are skipped) -- see `docs/handoff/07-next-steps.md` for wiring
this into actual CI.

**Both `setup.py` and `build_native.py` include a fixed set of extra
`--include-module=`/`--include-package-data=` flags for `pydicom`**
(`PYDICOM_NUITKA_FLAGS` in `build_native.py`), on top of the OMERO Ice
modules `omero_ice_modules()` already discovers dynamically. pydicom 3.x
loads its pixel data decoders/encoders as a plugin-style set of submodules
rather than through top-level imports, which Nuitka's static import
analysis misses -- without these flags, a compiled binary can build and
even launch fine, but fail the first time `lavlab seg` actually needs to
decode/encode DICOM pixel data. If you hit a similar "works from source,
breaks in the compiled binary" issue with some other dependency, that's
almost always this same class of problem: something doing dynamic/plugin
imports Nuitka can't see statically.

`LAVLAB_NUITKA_ARGS` (an environment variable) lets you pass additional
raw Nuitka flags for a one-off build without editing the build scripts --
e.g. `LAVLAB_NUITKA_ARGS="--include-package=some_other_thing" pip wheel .`.
`LAVLAB_OUTPUT_DIR` (read by `build_native.py` only) controls where the
standalone-script build writes its output (default: `./native/`).

## Building with Docker

A `Dockerfile` in the repo root provides a reproducible build environment
-- a pinned image with the C compiler, Nuitka, and the full dependency
stack (including the Ice wheel) pre-installed, so the build doesn't depend
on what happens to already be on your machine. It builds against your
*live* source tree (mounted in at `docker run` time), not a snapshot baked
into the image, so you don't need to rebuild the image after every source
change.

```sh
# once: get the lab's Ice wheel for linux-x86_64 into ./vendor/
mkdir -p vendor
curl -L -o vendor/zeroc_ice-<version>-<platform>.whl <lab-internal-URL>

# once (or after a dependency change): build the environment image
docker build -t lavlab-builder .

# every time you want a fresh wheel from your current source:
docker run --rm -v "$(pwd)":/src -v "$(pwd)/dist":/out lavlab-builder
```

The resulting wheel lands in `./dist/` on your host, same as running
`pip wheel . -w dist/` directly would -- this just guarantees the
environment it ran in. See the comments at the top of `Dockerfile` for
more detail. `.dockerignore` excludes `legacy/` from the build context for
the same reason `.gitignore` does (see below) -- nothing in there should
ever leave your machine.

## `legacy/` and secrets

`legacy/` holds the ad-hoc scripts and notebooks the `lavlab` CLI was
built from, kept for reference (see `legacy/README.md` for what maps to
what). **It is git-ignored and docker-ignored on purpose, not by
oversight** -- some notebook outputs in there contain a real OMERO
username and the real server hostname from having actually been run
against the lab server. Don't add new files to `legacy/`, don't remove it
from `.gitignore`/`.dockerignore`, and if you're ever unsure whether
something contains a real credential or real lab data before committing
it, err on the side of not committing it. `.gitignore` also excludes
common secret-file patterns (`.env`, `*.pem`, `*.key`, `credentials*.json`,
etc.) as a second line of defense.

## Troubleshooting

- **A compiled binary crashes on something `python -m lavlab` handled
  fine.** Almost always a Nuitka static-analysis miss -- some dependency
  doing dynamic/plugin-style imports that the build didn't know to
  include. See the pydicom example under "Building the compiled wheel"
  above, and `LAVLAB_NUITKA_ARGS` for the escape hatch while you figure out
  the right permanent flag to add to `PYDICOM_NUITKA_FLAGS`/the OMERO Ice
  discovery.
- **`SimpleITK`/GDCM can't read a DICOM SEG file `lavlab seg nii2dcm`
  wrote.** Expected for the `LABELMAP` segmentation type this command
  writes -- SimpleITK/GDCM doesn't support parsing it directly yet, even
  though `highdicom` (which `lavlab seg dcm2nii` uses) reads it fine. This
  doesn't affect `lavlab seg dcm2nii`'s own output, which works around it
  automatically (see `docs/handoff/05-bugs-found-and-fixed.md` for the
  detail) -- it only matters if you're trying to open the file with some
  *other* tool that goes through SimpleITK.
- **`pip install -e ".[dev]"` fails on `omero-py`.** You need the Ice
  wheel installed first -- see the Install section above.
