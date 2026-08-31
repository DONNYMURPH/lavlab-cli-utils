# lavlab-cli-utils

LavLab's CLI toolbox for OMERO: pulling large-recon and ROI mask images,
moving QuPath GeoJSON annotations in and out of OMERO, filling in ROI
metadata, and converting between DICOM SEG and NIfTI segmentation masks.

More documentation lives in [`docs/`](docs/index.md):
[`docs/API.md`](docs/API.md) is the exhaustive flag-by-flag CLI reference
plus the importable Python API; [`CONTRIBUTING.md`](CONTRIBUTING.md) covers
development conventions.

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

**From a built wheel** (recommended for end users, i.e. lab members who
just want the `lavlab` command):

```sh
pip install lavlab_cli_utils-<version>-<platform>.whl
lavlab --help
```

The wheel itself isn't published anywhere automatic -- Someone with a working build environment runs
[the build](#building-the-compiled-wheel) and hands the resulting
`dist/*.whl` file to whoever needs it directly -- however's convenient
(shared drive, direct transfer, attached to an internal message). It is
**not** something to commit to this git repo: `dist/`, `build/`, and
`lavlab/bin/` (where the compiled binary lands) are all in `.gitignore`,
deliberately -- a ~100+ MB compiled binary has no business in git history,
and it's a build artifact that's trivially reproducible from source
whenever it's actually needed. Once you have the `.whl` file, `pip install`
works exactly like installing from any other source (a local path, a URL,
whatever fits).

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
Output filenames follow `LR${downsample}_${stem}.${format}`, where `stem`
is the image name with everything after the *first* `.` stripped (so
`foo.ome.tiff` -> `foo` -- this matters for OME-TIFFs specifically) and
`format` defaults to `jp2` (`--format jpg`/`jpeg`/`png`/`tif`/`tiff` picks
a different one).

**Three tiers, tried in order, so `lr` works from any workstation -- not
just the cluster:**

1. **Cached OMERO annotation.** If a `LargeRecon.${downsample}` file
   annotation already exists on the image in the requested format,
   download it directly. Fast, works from anywhere.
2. **Locally-mounted source file.** If OMERO's managed repository happens
   to be mounted where `lr` is running (true on the cluster, not on a
   workstation), generate the recon straight from the source file.
3. **OMERO's tile API, over the network.** Otherwise, fetch tiles directly
   from the server and assemble the image locally. Slower (minutes, for a
   large slide) but works from any machine with just OMERO credentials --
   this is what makes `lr` usable off-cluster at all.

Whatever tier 2 or 3 produces gets uploaded back to OMERO under the same
`LargeRecon.${downsample}` namespace, as `LR${downsample}_${image
name}.${format}` -- independent of wherever `-o` points locally -- so a
later run at the same downsample and format hits tier 1 instead of
regenerating. Only an annotation matching the requested format is ever
touched or replaced; an existing attachment in some other format (e.g. an
older, manually-uploaded `.png`) is left alone. `--regenerate` skips the
tier-1 lookup and forces a fresh tier-2/3 fetch, re-uploading the result;
`--skip-upload` fetches without writing anything back to OMERO at all.

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
for "everything." Output format defaults to `jp2` (`--format
jpg`/`jpeg`/`png`/`tif`/`tiff` picks a different one) -- except with
`--palette`, which refuses to combine with `jpg`/`jpeg`: a palette mask's
pixel values are exact integer labels (`0`, `1`, `2`, ...), and JPEG's
lossy compression would silently corrupt them.

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

This is the one command that writes to OMERO by default. Run it with
`--dry-run` first -- it reports exactly what would change (each matched
shape's ID and label included) without touching anything -- especially
since a plausible-but-wrong match is easy to get: many drawing tools
default an unset stroke color to plain black, which is indistinguishable
from an intentionally-black palette entry once it's in OMERO. Spot-check a
few matched shape IDs in OMERO.web before re-running without the flag.

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
  specifically want the raw bridged shape back. Detecting a genuine bridge
  vs. an ordinary duplicate point (e.g. a dense freehand trace revisiting
  the same rounded pixel at its own closing seam) is the fiddly part --
  `unbridge_ring` drops consecutive duplicate points before looking for a
  bridge, specifically so a shape like that doesn't get misread as "one
  giant hole" and silently dropped for having under 3 points left.
- **Mixed shape kinds in one ROI.** An OMERO ROI can hold shapes of
  different kinds together -- a Polygon and a Point, say -- but a plain
  GeoJSON geometry can only be one type. `export` falls back to a
  `GeometryCollection` feature for those ROIs instead of dropping them;
  `import` reads `GeometryCollection`, `Point`/`MultiPoint`, and
  `LineString`/`MultiLineString` features right back into the matching
  shape kinds (not just `Polygon`/`MultiPolygon`), so nothing that a
  from-scratch export can produce fails to come back on import.
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
python setup.py bdist_wheel
```

**Use `setup.py bdist_wheel` directly, not `pip wheel .`.** `pip wheel`
builds in an isolated PEP 517 environment that (a) can't see the
manually-installed Ice wheel and tries to rebuild `zeroc-ice` from source
instead, and (b) fails with `ModuleNotFoundError: No module named
'build_native'`, since the repo root isn't on `sys.path` under pip's build
hooks even with `--no-build-isolation`. Running `setup.py` directly puts
its own directory on the path and uses the environment you already set up.

This shells out to Nuitka (`setup.py`'s `build_py` override, or run
`build_native.py` standalone if you just want the compiled binary without
a full wheel) to compile `lavlab/__main__.py` into a single standalone
executable, bundled into the wheel as `lavlab/bin/lavlab-bin`; the
`lavlab` console-script just execs it. `[tool.cibuildwheel]` in
`pyproject.toml` is already configured to build this for
`linux-x86_64`/`macos-arm64` across `cp310`-`cp314` (Windows and
musllinux are skipped), but isn't wired into any CI yet -- see
[Install](#install) above for how a wheel actually gets to a lab member
today.

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
  automatically (`dcmseg_to_nifti` falls back to the reference NIfTI's
  geometry when `sitk.ReadImage` can't read a `LABELMAP` SEG's directly --
  see the `try`/`except RuntimeError` in `lavlab/seg.py`) -- it only
  matters if you're trying to open the file with some *other* tool that
  goes through SimpleITK.
- **`pip install -e ".[dev]"` fails on `omero-py`.** You need the Ice
  wheel installed first -- see the Install section above.
