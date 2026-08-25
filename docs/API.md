# API reference

Two halves: the **CLI** (what you get from `lavlab ...` / `python -m lavlab
...`) and the **Python API** (what you get importing `lavlab.geojson` /
`lavlab.seg` directly, e.g. from a notebook). Every command/function here
is exhaustive as of this doc's writing -- if it drifts from the actual
`add_parser()` definitions in `lavlab/commands/*.py`, those source files
are the ground truth, not this page.

---

## CLI reference

### Global flags

Apply before the subcommand name:

| Flag | Meaning |
|---|---|
| `--override` | Write over existing output files. Default: off. |
| `-v`, `--verbose` | Enable INFO-level logging. |

### OMERO credential flags

Every command that talks to OMERO (`lr`, `roi`, `meta`, `geojson`) accepts
these, added via `lavlab/commands/_shared.py`'s `add_creds_args`:

| Flag | Env var fallback |
|---|---|
| `-u`, `--user` | `OMERO_USER` |
| `-w`, `--password` | `OMERO_PASSWORD` |
| `-s`, `--host` | `OMERO_HOST` |
| `-p`, `--port` | `OMERO_PORT` |

A CLI flag always overrides its environment variable. Missing a required
value from both raises `ConfigError` -> `SystemExit`, not a prompt.

---

### `lavlab lr <target>` -- pull large-recon images

```
lavlab lr <image-id | batch> [-o OUTPUT] [-g GROUP] [--workers N]
                              [--downsample N] [--fs-map PATH]
                              [creds...]
```

| Flag | Meaning |
|---|---|
| `target` (positional) | An OMERO image ID, or the literal `batch` |
| `-o`, `--output` | Output file (single mode) or directory (batch mode) |
| `-g`, `--group` | OMERO group ID -- batch mode only |
| `--workers` | Parallel workers for batch mode (default: 8) |
| `--downsample` | Downsample factor (default: 10) |
| `--fs-map` | Path to a custom `fs_map` YAML (default: the bundled lab map) |

### `lavlab roi <target>` -- pull ROI mask images

```
lavlab roi <image-id | batch> [-o OUTPUT] [-g GROUP] [--workers N]
                               [-a | -t TEXT ...] [--suffix SUFFIX]
                               [--palette] [--downsample N] [--fs-map PATH]
                               [creds...]
```

| Flag | Meaning |
|---|---|
| `target` (positional) | An OMERO image ID, or the literal `batch` |
| `-o`, `--output` | Output file (single mode) or directory (batch mode) |
| `-g`, `--group` | OMERO group ID -- batch mode only |
| `--workers` | Parallel workers for batch mode (default: 8) |
| `-a`, `--all` | Include every annotation regardless of `textValue` |
| `-t`, `--text-filter` | Whitelist a `textValue` (repeatable). Mutually exclusive with `--all` |
| `--suffix` | Filename suffix (default: `_annot`) |
| `--palette` | Single-channel label mask instead of RGB color mask. Incompatible with `--all` |
| `--downsample` | Downsample factor (default: 10) |
| `--fs-map` | Path to a custom `fs_map` YAML |

Exactly one of `--all` or at least one `--text-filter` is required.

### `lavlab meta roi textvalue <text_mapping> [image_ids...]`

```
lavlab meta roi textvalue <mapping> [image_id ...] [-g GROUP]
                                     [--tolerance N] [creds...]
```

| Flag | Meaning |
|---|---|
| `text_mapping` (positional) | Built-in palette name (e.g. `default`) or a path to a YAML/JSON palette file |
| `image_ids` (positional, `*`) | OMERO image IDs to process. Omit and use `-g` instead to process a whole group |
| `-g`, `--group` | Process every image in this OMERO group |
| `--tolerance` | Per-channel color-match tolerance (default: 10) |

Exactly one of `image_ids` or `-g` must be given.

### `lavlab geojson import [paths...]`

```
lavlab geojson import [paths...] [--image ID | --dataset ID | --map CSV]
                       [--fill-alpha N] [--stroke-width N]
                       [--dry-run] [creds...]
```

| Flag | Meaning |
|---|---|
| `paths` (positional, `*`) | `.geojson` files or directories to import |
| `--image` | Target image ID -- requires exactly one input file |
| `--dataset` | Match files to images in this dataset by filename |
| `--map` | CSV of `geojson_path,image_id` rows -- the auditable choice for a real restore. Do not also pass `paths` |
| `--fill-alpha` | 0-255, or 0 for outline only (default: 90) |
| `--stroke-width` | Outline width in pixels (default: 2.0) |
| `--dry-run` | Report only; never contacts OMERO |

Exactly one of `--image`, `--dataset`, `--map` is required.

### `lavlab geojson export`

```
lavlab geojson export --out DIR [--image ID | --dataset ID | --project ID]
                       [--skip-empty] [--compact] [--ellipse-points N]
                       [--keep-bridges] [--datestamp] [--overwrite]
                       [--dry-run] [creds...]
```

| Flag | Meaning |
|---|---|
| `--out` | Directory to write into (required) |
| `--image` / `--dataset` / `--project` | Exactly one required -- what to export |
| `--skip-empty` | No file written for images with zero ROIs |
| `--compact` | Minified JSON output |
| `--ellipse-points` | Vertices used to approximate an ellipse (default: 64) |
| `--keep-bridges` | Leave keyhole slits in place instead of restoring holes as real interior rings |
| `--datestamp` | Write into `<out>/YYYY-MM-DD/` so repeated runs don't collide |
| `--overwrite` | Allow replacing an existing output file |
| `--dry-run` | Report only; nothing written |

### `lavlab seg dcm2nii <dicom_seg> <reference_nifti>`

```
lavlab seg dcm2nii DICOM_SEG REFERENCE_NIFTI -o OUTPUT_DIR
```

Splits a DICOM SEG file into one NIfTI file per segment, aligned to
`REFERENCE_NIFTI`. Does not talk to OMERO -- no credential flags.

### `lavlab seg nii2dcm <nifti_mask> <reference_dicom_dir>`

```
lavlab seg nii2dcm NIFTI_MASK REFERENCE_DICOM_DIR -o OUTPUT_PATH
                    [--template PATH] [--label TEXT] [--comment TEXT]
```

| Flag | Meaning |
|---|---|
| `nifti_mask` (positional) | Path to the NIfTI label mask |
| `reference_dicom_dir` (positional) | Directory of `.dcm` files the mask was drawn against |
| `-o`, `--out` | Path to write the DICOM SEG object to (required) |
| `--template` | Segment-attributes JSON template. Default: `lavlab/data/default_seg_template.json` |
| `--label` | Overrides the template's label for segment 1 |
| `--comment` | Sets `PatientComments` on the written object |

Writes a `LABELMAP`-type DICOM SEG object. Does not talk to OMERO -- no
credential flags. See the template schema below.

---

## `--template` schema (`lavlab seg nii2dcm`)

```json
{
  "series_description": "Segmentation",
  "series_number": 1,
  "instance_number": 1,
  "body_part_examined": "NA",
  "content_label": "SEGMENTATION",
  "content_description": "Image segmentation",
  "manufacturer": "LavLab",
  "manufacturer_model_name": "lavlab-cli-utils",
  "software_versions": "0.1.0",
  "device_serial_number": "NA",
  "segments": [
    {
      "label": "Segmentation",
      "category": {"value": "123037004", "scheme": "SCT", "meaning": "Anatomical Structure"},
      "type": {"value": "123037004", "scheme": "SCT", "meaning": "Anatomical Structure"},
      "algorithm_type": "MANUAL"
    }
  ]
}
```

`category`/`type` become `pydicom.sr.coding.Code(value, scheme, meaning)`
objects fed into `highdicom.seg.SegmentDescription`. This is **not** the
dcmqi metainfo format -- if you have dcmqi-format templates from other
tooling, they need converting to this schema first.

---

## Python API reference

Both of these modules are importable directly, independent of the CLI --
useful from a notebook or another script.

### `lavlab.geojson`

```python
from lavlab.geojson import convert_file, import_annotations
from lavlab.omero_client import connect
```

Public API (`lavlab/geojson/__init__.py`):

| Name | What it is |
|---|---|
| `convert_file(path)` | Read a `.geojson` file -> `ConversionResult(annotations, warnings)` |
| `load_features(path)` | Lower-level: file -> list of raw GeoJSON feature dicts |
| `feature_to_annotation(feature, warnings)` | One feature -> `Annotation` or `None` |
| `annotation_to_feature(annotation, fallback_id, unbridge=True)` | Reverse of the above |
| `shapes_to_geometry(shapes, unbridge=True)` | `list[ShapeSpec]` -> a GeoJSON geometry dict |
| `dump_geojson(features, indent=1)` | Serialize features as a `FeatureCollection` string |
| `summarise_annotations(annotations)` / `summarise_features(features)` | Reporting stats dicts |
| `Annotation`, `ShapeSpec` | The OMERO-agnostic intermediate representation |
| `ConversionResult`, `ConversionError` | Result/error types |
| `bridge_hole(outer, hole)` / `unbridge_ring(ring)` | The keyhole-slit hole-folding functions |
| `rgb_to_omero_color(r, g, b, alpha=255)` / `omero_color_to_rgb(packed)` | Color packing |
| `ring_to_points(ring)` / `points_to_ring(text)` | OMERO `Shape.points` string conversion |

OMERO-talking functions live in `lavlab.geojson.omero_io` specifically
(not re-exported from the package root, since importing them requires
`omero` to be installed): `import_annotations(conn, image_id, annotations,
fill_alpha=90, stroke_width=2.0)`, `export_image(conn, image_id,
ellipse_segments=64, unbridge=True)`, `build_roi(...)`, `read_shape(...)`,
`match_by_name(conn, dataset_id, paths)`, `iter_images(conn, image=,
dataset=, project=)`, `safe_filename(name)`.

### `lavlab.seg`

```python
from lavlab.seg import dcmseg_to_nifti, nifti_to_dcmseg
```

| Function | Signature |
|---|---|
| `dcmseg_to_nifti` | `(dicom_seg_path, nii_path, output_dir) -> list[str]` |
| `nifti_to_dcmseg` | `(nifti_mask_path, reference_dicom_dir, output_path, template_path=None, segment_label=None, patient_comment=None) -> str` |

Both raise `FileNotFoundError` for missing inputs and `ValueError` for
shape/size mismatches or malformed templates, rather than letting a lower
library's traceback surface. Lower-level helpers (also exported, see
`lavlab/seg.py`'s `__all__`): `format_output_path`, `read_nii`, `read_seg`,
`get_affine_from_sitk`, `flip_based_on_affine`, `format_nifti`,
`write_nifti`, `split_seg_channels`, `copy_sitk_image_info`.
