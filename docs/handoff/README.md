# Handoff docs: lavlab-cli-utils

This folder is written for a **fresh Claude session with no memory of how
this repo got to its current state**. It exists because the repo went
through a working session that folded two new tools into an existing
package, hit and fixed real bugs along the way, and made several
non-obvious decisions — all of which matter if you're about to keep working
on this codebase.

If you're Claude (or a person) picking this up cold: read these in order.
Each file is self-contained but builds on the ones before it.

1. **[01-project-overview.md](01-project-overview.md)** — what this repo
   is, the goal, the five command groups at a glance.
2. **[02-starting-state.md](02-starting-state.md)** — what already existed
   before this session touched anything, and what raw material got folded
   in.
3. **[03-what-was-built.md](03-what-was-built.md)** — file-by-file account
   of everything added or changed.
4. **[04-key-decisions.md](04-key-decisions.md)** — the non-obvious calls
   made, and why, including one significant architecture change
   (`pydicom-seg` → `highdicom`) discovered mid-session.
5. **[05-bugs-found-and-fixed.md](05-bugs-found-and-fixed.md)** — two real
   bugs caught by actually testing the new code, not just writing it.
6. **[06-testing-and-verification.md](06-testing-and-verification.md)** —
   exactly what was run, what it proved, and what it *didn't* prove
   (environment caveats).
7. **[07-next-steps.md](07-next-steps.md)** — what's left before this ships
   to the lab, in priority order.
8. **[08-repo-map.md](08-repo-map.md)** — full current file tree with a
   one-line purpose per entry, for fast orientation.

## The one-paragraph version

`lavlab-cli-utils` is a lab toolbox CLI (`lavlab`) for OMERO, built as one
Python package compiled to a single standalone binary via Nuitka. This
session added two new command groups to it — `lavlab geojson` (QuPath
GeoJSON ↔ OMERO ROI conversion, from a project the user had already built
separately) and `lavlab seg` (DICOM SEG ↔ NIfTI conversion, assembled from
an existing ad-hoc script plus a notebook cell) — reconciled their
conventions with the rest of the codebase, found and fixed two real bugs in
the process, added tests, and added baseline repo hygiene (README, LICENSE,
`.gitignore`). No git operations were performed at any point — the user is
handling `git init`/commits themselves.
