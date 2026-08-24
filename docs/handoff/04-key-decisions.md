# Key decisions and why

These were either explicitly confirmed with the user via questions during
the session, or forced by something discovered while actually testing the
code (not assumed up front). Both kinds are recorded here so a future
session doesn't second-guess or accidentally reverse them without knowing
why they were made.

## 1. `geojson` became a 4th subcommand group, not a separate package

**Decision:** `lavlab geojson import/export`, living inside the `lavlab`
package, not a standalone `omero-geojson` distribution.

**Why:** The user chose this explicitly when asked. It reuses `lavlab`'s
existing argparse/creds/Nuitka plumbing instead of standing up a second
installable tool, entry point, and build pipeline for what is, from the
lab's perspective, one more thing this CLI does.

## 2. Nuitka stays one combined binary, not per-tool

**Decision:** Keep `setup.py`'s existing behavior — one `lavlab-bin`
covering `lr`/`roi`/`meta`/`geojson`/`seg` together, not a separate compiled
binary per command group.

**Why:** The user initially said they wanted "one binary per tool," but the
repo already had a working single-binary Nuitka build compiling all of
`lavlab/__main__.py` as one onefile executable. Splitting that into
per-tool binaries would mean reworking `setup.py`/`build_native.py` to
invoke Nuitka multiple times, multiple console-script entry points, more
build time in CI, and a larger total download for no clear benefit — the
existing single-binary approach was presented as the tradeoff and the user
picked it (recommended option) over rearchitecting the build.

## 3. Package stays named `lavlab`, not renamed to `omero_cli_utils`

**Decision:** No rename, despite the repo folder being called
`omero-cli-utils`.

**Why:** Renaming touches `pyproject.toml`, `setup.py`, every import across
the codebase, the compiled binary's output filename, and all documentation,
for zero functional benefit — it was presented as a tradeoff and the user
picked "keep `lavlab`" (recommended option).

## 4. geojson's OMERO connection was standardized on `lavlab`'s existing convention

**Decision:** Deleted the geojson project's own `connect()` (positional
`server, user, password, port` args, `enableKeepAlive(60)`) and its CLI's
`--server/--user/--password/--port` flags plus `getpass` prompt. Replaced
with `lavlab.omero_client.connect()` (retry/backoff, dummy-group lookup)
via `lavlab/commands/_shared.py`'s `add_creds_args`/`connect_from_args` —
the exact same helpers `lr` and `roi` already use.

**Why:** Two independently-built pieces of code had two different
conventions for the same thing (connecting to OMERO). Since `geojson` was
joining an existing multi-command CLI rather than staying standalone, using
the CLI's already-established convention was the consistent choice — a lab
member shouldn't have to remember that `geojson` alone uses `--server`
while every other command uses `-s`/`--host`. This was presented to the
user as part of the initial plan and approved as part of the overall
approach, not asked as a separate yes/no.

**User-facing effect:** the geojson subcommand's connection flags changed
from `--server/--user/--password/--port` (with an optional interactive
password prompt if omitted) to `-s/-u/-w/-p` matching `lr`/`roi`/`meta`,
with no interactive prompt — a missing credential is now a hard error
(`ConfigError` → `SystemExit`) telling the user to pass the flag or set the
env var, same as every other command.

## 5. `pydicom-seg` dropped in favor of `highdicom` for both SEG directions — the big one

**What happened:** The original plan (approved by the user) was to port the
`test.ipynb` NIfTI→DICOM-SEG cell using `pydicom_seg.MultiClassWriter`,
exactly as the notebook did, with a dcmqi-format JSON template. While
actually verifying this (installing the dependencies and running real
conversions, not just reading the code), it broke: `pydicom_seg` is
unmaintained and hard-imports `pydicom._storage_sopclass_uids`, an internal
module pydicom removed in its 3.x line. `highdicom` (needed for the
*other* direction, DICOM SEG→NIfTI, since `dcmseg2nii.py` uses it) requires
`pydicom>=3.0.1`. **The two required dependencies could not be installed in
the same environment.** This was confirmed directly, not assumed:
```
ERROR: Cannot install highdicom==0.24.0 and pydicom<3 and >=2.3 because
these package versions have conflicting dependencies.
```
and, going the other way, installing `pydicom<3` for `pydicom_seg` then
trying to import `highdicom` fails with:
```
ImportError: cannot import name 'parse_basic_offsets' from 'pydicom.encaps'
```

**Decision:** Rather than silently pinning versions and hoping, or leaving
a known-broken dependency pair in the packaging files, this was surfaced to
the user directly with a recommendation, and they approved it: **drop
`pydicom-seg` entirely** and rewrite `nifti_to_dcmseg` to use
`highdicom.seg.Segmentation` (which can itself write DICOM SEG objects, not
just read them) for both directions. This gives one well-maintained,
mutually-compatible dependency instead of two that can't coexist.

**User-facing consequence:** the `--template` file for `lavlab seg
nii2dcm` is **not** the dcmqi metainfo JSON format the original notebook
used. It's a simpler schema (see
[03-what-was-built.md](03-what-was-built.md) for the shape) built
specifically around `highdicom.seg.SegmentDescription`. If anyone in the
lab already has dcmqi-format templates from other tooling, those will
**not** work as-is with `lavlab seg nii2dcm --template` and would need
converting to the new schema.

**Segmentation type chosen:** `LABELMAP` (a newer part of the DICOM
standard, added ~2022) — a single multi-class label array, matching what
`pydicom_seg.MultiClassWriter` used to produce, as opposed to `BINARY` (one
frame stack per segment). This choice is what led directly to the two bugs
in [05-bugs-found-and-fixed.md](05-bugs-found-and-fixed.md) — LABELMAP is
new enough that both `highdicom` itself and `SimpleITK`/GDCM have rough
edges around it.

## 6. Legacy scripts moved to `legacy/`, not deleted

**Decision:** `batch_lr.py`, `batch_roi.py`, `getLargeRecon.py`,
`single_roi.py`, `dcmseg2nii.py`, and the scratch notebooks/`test.json`
moved into `legacy/` rather than being removed from the repo.

**Why:** Per general working practice (prefer reversible actions over
destructive ones when the user hasn't explicitly asked for deletion), and
because `legacy/` with a mapping README preserves the "what did this used
to be called / where did this logic go" history without cluttering the
repo root — a reasonable middle ground the user did not object to.

## 7. No git operations performed

**Decision:** Despite creating/moving many files, `git init` and all
commits were left entirely to the user.

**Why:** Explicit instruction — the user said "I do not want you to add
anything to git I will do that manually when we are all done" after an
earlier plan draft mentioned git steps. That instruction was carried
through the rest of the session; nothing in this repo has ever been
committed by Claude.
