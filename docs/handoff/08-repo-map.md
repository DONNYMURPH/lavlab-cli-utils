# Repo map

Full current file tree, one line of purpose per entry. `*` marks anything
new or changed this session; everything else predates this session
unchanged.

```
omero-cli-utils/
├── README.md *                    Install/usage docs for the whole toolbox
├── LICENSE *                       MIT
├── .gitignore *                    Python/build/venv/editor ignores
├── design.md                       Original spec lr/roi/meta were built against
├── pyproject.toml *                 Packaging config; * = gained dev extra + geojson/seg build deps
├── setup.py                        Custom build_py: shells out to Nuitka before packaging
├── build_native.py                 Standalone Nuitka build script (finds OMERO Ice modules)
├── build-requirements.txt *         Build-time deps; * = gained highdicom/nibabel/SimpleITK/pydicom
│
├── lavlab/                         The package
│   ├── __init__.py                   __version__ = "0.1.0"
│   ├── __main__.py                   `python -m lavlab`; Nuitka's compile entry point
│   ├── cli.py *                      Top-level argparse parser; * = wires up geojson + seg
│   ├── launcher.py                   Wheel-install console-script: execs the compiled binary
│   ├── config.py                     OmeroCreds resolution, fs_map YAML loading
│   ├── omero_client.py               connect(), dummy-group/per-object-group switching, iter_image_ids
│   ├── naming.py                     Output filename convention (LR${downsample}_${stem}...)
│   ├── imaging.py                    Downsampled image loading (tifffile/pyvips/openslide)
│   ├── roi.py                        ROI shape gathering + rasterization (skimage)
│   ├── palettes.py                   Color-to-label palette matching (used by lr, roi, meta)
│   ├── seg.py *                      NEW — DICOM SEG <-> NIfTI conversion logic
│   │
│   ├── commands/                    One module per command group; argparse + orchestration only
│   │   ├── __init__.py
│   │   ├── _shared.py                 add_creds_args, connect_from_args, load_fs_map_from_args, etc.
│   │   ├── lr.py                      `lavlab lr`
│   │   ├── roi_cmd.py                 `lavlab roi`
│   │   ├── meta.py                    `lavlab meta roi textvalue`
│   │   ├── geojson.py *                NEW — `lavlab geojson import/export`
│   │   └── seg.py *                    NEW — `lavlab seg dcm2nii/nii2dcm`
│   │
│   ├── geojson/ *                   NEW subpackage — GeoJSON<->OMERO conversion logic, no argparse
│   │   ├── __init__.py *              Public API re-exports
│   │   ├── geometry.py *              bridge_hole/unbridge_ring, color packing, points-string parsing
│   │   ├── geojson_io.py *            GeoJSON read/write, Annotation/ShapeSpec conversion
│   │   └── omero_io.py *              The only file in this subpackage that imports `omero`
│   │
│   └── data/                        Bundled default config, loaded via importlib.resources
│       ├── __init__.py
│       ├── default_fs_map.yaml        Lab's default OMERO-group -> filesystem-path mapping
│       └── default_seg_template.json * NEW — default DICOM SEG segment-attributes template
│
├── tests/ *                        NEW — pytest suite (24 tests total)
│   ├── test_geometry.py *            lavlab.geojson.geometry — no external deps
│   ├── test_geojson_io.py *          lavlab.geojson.geojson_io — no external deps
│   └── test_seg.py *                 lavlab.seg — skips if SimpleITK/pydicom not installed
│
├── legacy/ *                       NEW — superseded ad-hoc scripts/notebooks, kept for reference
│   ├── README.md *                    Maps each old file to what superseded it
│   ├── batch_lr.py                    -> lavlab lr
│   ├── batch_roi.py                   -> lavlab roi
│   ├── getLargeRecon.py               -> lavlab lr
│   ├── single_roi.py                  -> lavlab roi
│   ├── dcmseg2nii.py                  -> lavlab seg dcm2nii
│   ├── omero_roi_comment.ipynb        -> lavlab meta roi textvalue
│   ├── test.ipynb                     -> lavlab seg nii2dcm (the DICOM-SEG-writing cell)
│   ├── test.json                      -> lavlab/data/default_seg_template.json (different schema!)
│   └── testing.ipynb                  Scratch notebook, no CLI counterpart
│
└── docs/handoff/ *                 NEW — you are reading this right now
    ├── README.md
    ├── 01-project-overview.md
    ├── 02-starting-state.md
    ├── 03-what-was-built.md
    ├── 04-key-decisions.md
    ├── 05-bugs-found-and-fixed.md
    ├── 06-testing-and-verification.md
    ├── 07-next-steps.md
    └── 08-repo-map.md               This file
```

## Quick file-purpose lookup for the two new command groups

If you're about to touch `geojson` or `seg`, here's exactly which file owns
what:

| Concern | GeoJSON | Seg |
|---|---|---|
| Argparse flags / CLI entry | `lavlab/commands/geojson.py` | `lavlab/commands/seg.py` |
| Actual conversion logic (no OMERO) | `lavlab/geojson/geojson_io.py`, `lavlab/geojson/geometry.py` | `lavlab/seg.py` |
| OMERO I/O | `lavlab/geojson/omero_io.py` | n/a — seg never touches OMERO |
| Bundled default config | n/a | `lavlab/data/default_seg_template.json` |
| Tests | `tests/test_geometry.py`, `tests/test_geojson_io.py` | `tests/test_seg.py` |
| Registered in top-level CLI | `lavlab/cli.py` (`geojson.add_parser(subparsers)`) | `lavlab/cli.py` (`seg.add_parser(subparsers)`) |
