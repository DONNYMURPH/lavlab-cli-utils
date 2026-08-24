# What was built, file by file

## `lavlab/geojson/` — new subpackage

Moved in from the standalone `omero_geojson` project, with one substantive
change (see below) plus import-path updates.

| File | Origin | Changes from the original |
|---|---|---|
| `lavlab/geojson/geometry.py` | `geometry.py` | None — copied verbatim (no `omero` import in the original) |
| `lavlab/geojson/geojson_io.py` | `geojson_io.py` | None functionally — only the module-path reference in the docstring (`omero_geojson.omero_io` → `lavlab.geojson.omero_io`) |
| `lavlab/geojson/omero_io.py` | `omero_io.py` | **`connect()` deleted entirely.** Every other function (`build_roi`, `import_annotations`, `read_shape`, `export_image`, `match_by_name`, `iter_images`, `safe_filename`, `unwrap`) unchanged. `__all__` updated to drop `connect`. |
| `lavlab/geojson/__init__.py` | `__init__.py` | Re-exports the same public API (`__all__` unchanged in content); dropped the `__version__`/`__about__` import since `lavlab` already has one version in `pyproject.toml`; the module docstring's usage example now shows `from lavlab.omero_client import connect` instead of a local `connect()`. |
| — | `__about__.py` | **Dropped entirely** — redundant with `lavlab/__init__.py`'s `__version__`. |

## `lavlab/commands/geojson.py` — new CLI adapter

Rewritten from the standalone `cli.py`, following the exact structural
pattern of `lavlab/commands/roi_cmd.py`:

- `add_parser(subparsers)` registers `geojson` with two nested subparsers
  (`import`, `export`), carrying over every flag from the original
  `build_parser()` **unchanged in name and meaning**: `--image`,
  `--dataset`, `--map`, `--fill-alpha`, `--stroke-width`, `--out`,
  `--skip-empty`, `--compact`, `--ellipse-points`, `--keep-bridges`,
  `--datestamp`, `--overwrite`, `--dry-run`.
- The bespoke `--server/--user/--password/--port` flags and `getpass`
  prompt are **gone**, replaced by `_shared.add_creds_args` (`-u/-w/-s/-p`,
  `OMERO_USER/PASSWORD/HOST/PORT` env fallback, no interactive prompt) —
  see [04-key-decisions.md](04-key-decisions.md) for why.
- `run_import`/`run_export` are near-verbatim ports of the original CLI's
  functions, with `_connect(args)` replaced by `connect_from_args(args)`
  from `_shared.py`, and error paths changed from `return <exit code>` to
  `raise SystemExit("error: ...")`, matching how `lr.py`/`roi_cmd.py`
  signal failure (`lavlab/cli.py`'s `main()` calls `args.handler(args)` and
  ignores any return value — it doesn't do `sys.exit(main())` the way the
  standalone CLI's `__main__` block did).
- Helper functions carried over near-verbatim: `_exactly_one`,
  `_collect_paths`, `_pairs_from_map`, `_report_conversion`.

Registered in `lavlab/cli.py`:
```python
from lavlab.commands import geojson, lr, meta, roi_cmd, seg
...
geojson.add_parser(subparsers)
```

## `lavlab/seg.py` — new logic module

Two independent public functions, both raising `FileNotFoundError`/
`ValueError` on bad input rather than letting a lower-level library's
traceback surface directly:

- **`dcmseg_to_nifti(dicom_seg_path, nii_path, output_dir)`** — ported from
  `dcmseg2nii.py`'s `main()` (renamed, returns the output paths instead of
  just being a script entry point). Every helper function from the original
  script carried over as a public function of the same name:
  `format_output_path`, `read_nii`, `read_seg`, `get_affine_from_sitk`,
  `flip_based_on_affine`, `format_nifti`, `write_nifti`,
  `split_seg_channels`, `copy_sitk_image_info`. Two real bugs were found and
  fixed in this function during testing — see
  [05-bugs-found-and-fixed.md](05-bugs-found-and-fixed.md).
- **`nifti_to_dcmseg(nifti_mask_path, reference_dicom_dir, output_path,
  template_path=None, segment_label=None, patient_comment=None)`** —
  generalized from the hardcoded `test.ipynb` cell. **Not** a direct port —
  it was rewritten mid-session to use `highdicom` instead of `pydicom_seg`
  after discovering a real dependency conflict; see
  [04-key-decisions.md](04-key-decisions.md) for the full story. Internally
  builds a `LABELMAP`-type `highdicom.seg.Segmentation`, reading segment
  descriptions from a JSON template (`_load_segment_descriptions`) and
  sorting the reference DICOM series into slice order by
  `ImagePositionPatient`/`InstanceNumber` (`_read_series_in_slice_order`).

## `lavlab/commands/seg.py` — new CLI adapter

Follows the same `add_parser(subparsers)` pattern as the other command
modules. Registers `seg` with two nested subparsers:

- `seg dcm2nii <dicom_seg> <reference_nifti> -o <output_dir>`
- `seg nii2dcm <nifti_mask> <reference_dicom_dir> -o <output_path>
  [--template ...] [--label ...] [--comment ...]`

Neither uses `_shared.add_creds_args` — this command group never talks to
OMERO.

Registered in `lavlab/cli.py` alongside `geojson`:
```python
seg.add_parser(subparsers)
```

## `lavlab/data/default_seg_template.json` — new bundled config

Replaces `legacy/test.json` (which was in dcmqi metainfo format, tied to
`pydicom_seg`). New schema (see the file itself for the full example):

```json
{
  "series_description": "...",
  "series_number": 1,
  "instance_number": 1,
  "body_part_examined": "...",
  "content_label": "...",
  "content_description": "...",
  "manufacturer": "...",
  "manufacturer_model_name": "...",
  "software_versions": "...",
  "device_serial_number": "...",
  "segments": [
    {
      "label": "...",
      "category": {"value": "...", "scheme": "SCT", "meaning": "..."},
      "type": {"value": "...", "scheme": "SCT", "meaning": "..."},
      "algorithm_type": "MANUAL"
    }
  ]
}
```
`category`/`type` become `pydicom.sr.coding.Code` objects fed into
`highdicom.seg.SegmentDescription`. The bundled default is intentionally
generic (not prostate-specific like the old `test.json`) — see
[07-next-steps.md](07-next-steps.md) about reviewing this for real lab use.

Loaded via `importlib.resources` (`lavlab/seg.py`'s
`_default_seg_template_path()`), matching the existing pattern in
`lavlab/config.py`'s `_default_fs_map_path()`.

`pyproject.toml`'s `[tool.setuptools.package-data]` was updated to include
`data/*.json` alongside the existing `data/*.yaml`.

## `tests/` — new, didn't exist before

- `tests/test_geometry.py` — `bridge_hole`/`unbridge_ring` round-trips,
  `rgb_to_omero_color`/`omero_color_to_rgb` round-trips,
  `points_to_ring`/`ring_to_points` round-trips, open/close ring behavior.
  No dependencies beyond stdlib.
- `tests/test_geojson_io.py` — feature→annotation→feature round-trips,
  hole-bridging warnings, unsupported-geometry warnings, mixed-shape-kind
  handling, malformed/wrong-type GeoJSON raising `ConversionError`. No
  dependencies beyond stdlib.
- `tests/test_seg.py` — `pytest.importorskip("SimpleITK")` /
  `importorskip("pydicom")` at the top, so this file's tests are skipped
  (not failed) if the imaging stack isn't installed. Covers
  `format_output_path`, `get_affine_from_sitk`, `flip_based_on_affine`
  against synthetic in-memory images, `FileNotFoundError` cases for both
  conversion directions, and — the important one —
  `test_nifti_to_dcmseg_round_trips_through_dcmseg_to_nifti`, which builds
  a real synthetic 3-slice DICOM series with `pydicom`, writes a NIfTI mask
  through `nifti_to_dcmseg`, reads it back through `dcmseg_to_nifti`, and
  asserts the recovered voxel data matches the original exactly. This test
  is what caught both bugs in
  [05-bugs-found-and-fixed.md](05-bugs-found-and-fixed.md).

`pytest` was added to `pyproject.toml`'s `dev` extra.

## Root-level repo hygiene — new

- **`README.md`** — install instructions (wheel vs. `pip install -e
  ".[dev]"`), OMERO credential flag/env-var table, one example per command
  group, dev/build instructions.
- **`LICENSE`** — MIT, matching the `SPDX-License-Identifier: MIT` headers
  already present in the geojson source files. Copyright line: "LavLab,
  Medical College of Wisconsin" — **this should be confirmed**, see
  [07-next-steps.md](07-next-steps.md).
- **`.gitignore`** — Python bytecode/caches, `build/`, `dist/`, `native/`,
  `wheelhouse/`, `lavlab/bin/`, venvs, editor/OS cruft.
- **`legacy/`** — the superseded root-level scripts and notebooks
  (`batch_lr.py`, `batch_roi.py`, `getLargeRecon.py`, `single_roi.py`,
  `dcmseg2nii.py`, `omero_roi_comment.ipynb`, `test.ipynb`, `testing.ipynb`,
  `test.json`) moved here rather than deleted, with a `legacy/README.md`
  mapping each old file to what superseded it.

## `pyproject.toml` / `build-requirements.txt` changes

- `[build-system].requires` and the new `[project.optional-dependencies].dev`
  extra both gained: `highdicom`, `nibabel`, `SimpleITK`, `pydicom`, and
  `pytest` (dev-only). **`pydicom-seg` was added, then removed** — see
  [04-key-decisions.md](04-key-decisions.md).
- `build-requirements.txt` mirrors the same additions/removal.
- `[project].description` updated to mention GeoJSON and DICOM SEG/NIfTI
  alongside the original large-recon/ROI description.
- `[tool.setuptools.package-data]` gained `data/*.json`.
