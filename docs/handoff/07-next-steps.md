# Next steps

Roughly in priority order. None of these were done this session — they're
exactly what's left before this can be confidently shipped to the lab.

## 1. Get this into git

Deliberately not done — the user is handling `git init` and the first
commit manually. Once that happens, everything from this session (and
`docs/handoff/` itself) becomes part of the repo's history.

## 2. Run a real Nuitka build and test the compiled binary

Nothing this session actually invoked Nuitka. On a machine with
`omero-py` + the lab's Ice wheel installed:
```sh
pip install -r build-requirements.txt   # + the Ice wheel, separately, per that file's comment
pip wheel . -w dist/
```
Then install the resulting wheel and confirm:
```sh
lavlab --help
lavlab geojson --help
lavlab seg --help
lavlab seg dcm2nii --help
lavlab seg nii2dcm --help
```
all work from the **compiled binary**, not just `python -m lavlab`. Pay
particular attention to `SimpleITK`/`highdicom`/`pydicom` — these are
partly-compiled packages with native shared libraries, and Nuitka's static
import-following can miss a dynamic library dependency that only manifests
as a runtime crash in the compiled binary, not an import error during
`python -m lavlab`. If that happens, `LAVLAB_NUITKA_ARGS` (read from the
environment in both `setup.py` and `build_native.py`) is the escape hatch
for adding extra `--include-package=...`/`--include-data-dir=...` flags
without editing the build scripts.

## 3. Actually test `lavlab geojson import`/`export` against a real OMERO server

This was only verified structurally (argparse wiring with stubbed `omero`
module) — see [06-testing-and-verification.md](06-testing-and-verification.md).
Before trusting it in production: import a real small GeoJSON file onto a
test image, confirm the ROIs render correctly in OMERO.web/iviewer
(especially anything with holes, to confirm the keyhole-bridging renders
right), then export that same image and confirm the round trip recovers
the holes correctly.

## 4. Confirm the LICENSE copyright holder

`LICENSE` currently says "LavLab, Medical College of Wisconsin" — this was
inferred from the `SPDX-FileCopyrightText` headers already present in the
geojson source files (`LavLab <domurphy@mcw.edu>`) and the general MCW/lab
context, not confirmed directly with anyone who has authority over it.
Worth a quick check before this goes out the door.

## 5. Review `lavlab/data/default_seg_template.json` for real use

The bundled default was deliberately made generic (not prostate-specific
like the old `legacy/test.json`) since this is now a shared default for the
whole lab, not one project. Whoever actually uses `lavlab seg nii2dcm` for
real segmentation work should either always pass `--template
their_own.json`, or the bundled default should be replaced with something
that reflects real common lab use cases. See
[03-what-was-built.md](03-what-was-built.md) for the current schema.

## 6. Set up CI to actually run `cibuildwheel`

`pyproject.toml`'s `[tool.cibuildwheel]` section is already configured
(targets `cp310`–`cp314` on `linux-x86_64`/`macos-arm64`), but nothing
invokes it. A `.github/workflows/build.yml` (or equivalent) triggered on
tags/releases is what turns this config into actual downloadable wheels.
Also worth adding a workflow that runs `pytest` on every push/PR, now that
`tests/` exists.

## 7. Decide on a distribution channel

Left open during planning ("not sure yet" when asked): internal package
index vs. `pip install git+https://...` vs. public PyPI. This affects
whether package name collisions on PyPI matter (`lavlab-cli-utils` should
be checked for availability if PyPI is the plan) and how lab members are
told to install it in practice.

## 8. Verify `pip install -e ".[dev]"` resolves cleanly on a real machine

This session's sandbox already had some scientific-Python packages
pre-installed (via an FSL Python distribution) and is not representative of
a clean environment. In particular:
- `omero-py` + Ice was never actually installed anywhere this session — its
  resolution alongside everything else in the `dev` extra is unverified.
- The pip dependency resolver in the sandbox surfaced several *unrelated*
  conflict warnings from pre-existing packages in that environment (xnat,
  fsleyes, jupyterlab-server, etc.) — none of those are `lavlab`'s problem,
  but they're a reminder to actually test `pip install -e ".[dev]"` in a
  clean virtualenv, not just trust that the sandbox's resolution "mostly
  worked."

## 9. Consider adding CI for the pytest suite specifically around `lavlab/seg.py`

Given that this module needed two real bug fixes discovered only by
integration-testing it (see
[05-bugs-found-and-fixed.md](05-bugs-found-and-fixed.md)), and that DICOM
SEG tooling in general (LABELMAP support especially) is a young and rapidly
changing part of the ecosystem, pin exact `highdicom`/`pydicom`/`SimpleITK`
versions somewhere (currently unpinned in `pyproject.toml`/
`build-requirements.txt`) and re-run `tests/test_seg.py` before ever
bumping them — a `highdicom` update could plausibly change LABELMAP
behavior again given how new that segmentation type is.
