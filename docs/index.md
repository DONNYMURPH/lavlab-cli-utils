# lavlab-cli-utils docs

`lavlab-cli-utils` is LavLab's CLI toolbox for OMERO -- pulling large-recon
and ROI mask images, filling in ROI metadata, moving QuPath GeoJSON
annotations in and out of OMERO, and converting between DICOM SEG and
NIfTI segmentation masks. It ships as a single `lavlab` command, either as
a self-contained [Nuitka](https://nuitka.net)-compiled binary (no Python
environment needed on the target machine) or run directly from source.

## Where to go

- **[../README.md](../README.md)** -- start here. Install instructions,
  every command with examples, the Docker build environment, and
  troubleshooting.
- **[API.md](API.md)** -- exhaustive reference: every CLI flag, and the
  importable Python API (`lavlab.geojson`, `lavlab.seg`) for use outside
  the CLI, e.g. from a notebook.
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** -- setting up a dev
  environment, running tests, the pattern to follow when adding a new
  command group, and the conventions this codebase expects.
- **[handoff/](handoff/)** -- a detailed record of how the `geojson` and
  `seg` command groups came to exist: what the repo looked like before,
  every non-obvious decision and why, two real bugs found while testing
  the DICOM SEG rewrite, and what's still left before this ships to the
  lab. Read this if something looks like an odd choice and you want to
  know whether it was deliberate.
