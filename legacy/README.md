# legacy

The ad-hoc scripts and notebooks this package's `lavlab` CLI was built from.
Kept for reference; not installed, not tested, not maintained.

| File | Superseded by |
|---|---|
| `batch_lr.py`, `getLargeRecon.py` | `lavlab lr` (`lavlab/commands/lr.py`, `lavlab/imaging.py`) |
| `batch_roi.py`, `single_roi.py` | `lavlab roi` (`lavlab/commands/roi_cmd.py`, `lavlab/roi.py`) |
| `omero_roi_comment.ipynb` | `lavlab meta roi textvalue` (`lavlab/commands/meta.py`) |
| `dcmseg2nii.py` | `lavlab seg dcm2nii` (`lavlab/seg.py`) |
| `test.ipynb`'s NIfTI-to-DICOM-SEG cell | `lavlab seg nii2dcm` (`lavlab/seg.py`) |
| `test.json` | `lavlab/data/default_seg_template.json` (different schema -- see the README at the repo root) |
| `testing.ipynb` | scratch notebook, no CLI counterpart |
