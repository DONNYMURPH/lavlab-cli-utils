# lavlab-cli-utils

LavLab's CLI toolbox for OMERO: pulling large-recon and ROI mask images,
moving QuPath GeoJSON annotations in and out of OMERO, filling in ROI
metadata, and converting between DICOM SEG and NIfTI segmentation masks.

## Install

**From a built wheel** (recommended -- ships a self-contained compiled
binary via [Nuitka](https://nuitka.net), no Python environment or OMERO
dependencies needed on the target machine):

```sh
pip install lavlab_cli_utils-<version>-<platform>.whl
lavlab --help
```

**From source, for development** (runs the plain Python CLI; slower, but no
compile step):

```sh
pip install -e ".[dev]"
python -m lavlab --help
```

The `dev` extra installs everything `lavlab` needs to run: `numpy`,
`pyvips`, `tifffile`, `scikit-image`, `PyYAML`, `tqdm`, `omero-py`,
`highdicom`, `nibabel`, `SimpleITK`, `pydicom`, `pytest`. `omero-py` needs
the Glencoe/ZeroC Ice wheel for your platform installed separately first --
see `build-requirements.txt`.

## Connecting to OMERO

Every command that talks to OMERO takes `-u/--user`, `-w/--password`,
`-s/--host`, `-p/--port`, or reads `OMERO_USER`, `OMERO_PASSWORD`,
`OMERO_HOST`, `OMERO_PORT` from the environment. CLI flags win when both are
given.

## Commands

### `lavlab lr` -- pull large-recon (downsampled) images

```sh
lavlab lr 12345 -o ./out/slide.jp2 --downsample 10 -s omero.example.edu -u you
lavlab lr batch -g 3 --workers 8 -s omero.example.edu -u you
```

### `lavlab roi` -- pull ROI mask images

```sh
lavlab roi 12345 --all -o ./out/mask.jp2 -s omero.example.edu -u you
lavlab roi batch -g 3 -t tumor -t stroma --palette -s omero.example.edu -u you
```

### `lavlab meta roi textvalue` -- fill blank ROI comments from a color palette

```sh
lavlab meta roi textvalue default 12345 12346 -s omero.example.edu -u you
lavlab meta roi textvalue ./my_palette.yaml -g 3 -s omero.example.edu -u you
```

### `lavlab geojson import` / `export` -- QuPath GeoJSON <-> OMERO ROIs

```sh
lavlab geojson import slide.geojson --image 12345 -s omero.example.edu -u you
lavlab geojson import ./backups/ --dataset 5 -s omero.example.edu -u you
lavlab geojson import --map restore.csv -s omero.example.edu -u you

lavlab geojson export --project 2 --out ./archive/ --datestamp -s omero.example.edu -u you
```

`import` accepts one of `--image` (a single file), `--dataset` (match files
to images by filename), or `--map` (an explicit `path,image_id` CSV --
the auditable choice for a real restore). `export` accepts one of `--image`,
`--dataset`, or `--project`.

### `lavlab seg dcm2nii` / `nii2dcm` -- DICOM SEG <-> NIfTI

Local file conversion; neither direction talks to OMERO.

```sh
lavlab seg dcm2nii segmentation.dcm reference.nii.gz --out ./out/
lavlab seg nii2dcm mask.nii.gz ./dicom_series/ --out ./mask_seg.dcm --label "Tumor"
```

`nii2dcm` writes a `LABELMAP`-type DICOM SEG object using
`lavlab/data/default_seg_template.json` unless `--template` points at a
custom one (see that file for the schema: a list of segments, each with a
label and a `SegmentedPropertyCategoryCodeSequence`/
`SegmentedPropertyTypeCodeSequence` pair).

## Development

```sh
pip install -e ".[dev]"
pytest
```

Tests that need the imaging/DICOM stack (`SimpleITK`, `pydicom`) are
skipped automatically if those packages aren't installed; the GeoJSON tests
have no such dependency and always run.

## Building the compiled wheel

```sh
pip install -r build-requirements.txt  # plus the Ice wheel for omero-py, see that file
pip wheel . -w dist/
```

This shells out to Nuitka (see `setup.py`/`build_native.py`) to compile
`lavlab/__main__.py` into a single standalone binary bundled into the wheel;
the `lavlab` console-script just execs it. `cibuildwheel` (configured in
`pyproject.toml`) builds this for linux-x86_64 and macos-arm64 in CI.
