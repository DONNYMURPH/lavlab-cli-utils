# Bugs found and fixed

Both of these were only caught because the `highdicom` rewrite (see
[04-key-decisions.md](04-key-decisions.md), item 5) was actually *run*
end-to-end with real conversions, not just reviewed as code. Writing tests
that only exercise error paths (missing file, missing directory) would not
have caught either of these — both required a synthetic-but-real DICOM
series and an actual round trip to surface. This is worth internalizing for
any future work on `lavlab/seg.py`: **test the happy path with real data
shapes, not just the failure paths.**

## Bug 1: segment metadata looked up by list position instead of `SegmentNumber`

**Location:** `lavlab/seg.py`, `dcmseg_to_nifti`.

**The bug:** The original code (ported directly from `dcmseg2nii.py`) did:
```python
for i, seg_channel in enumerate(split_seg_channels(dicom_seg)):
    ...
    nii_code = (
        dicom_seg.SegmentSequence[i]
        .SegmentedPropertyTypeCodeSequence[0]
        .CodeMeaning
    )
```
This assumes `SegmentSequence[i]` corresponds to the segment processed at
loop index `i` — i.e., that segment numbering starts at 1 and
`SegmentSequence` is ordered to match. That assumption breaks the moment
anything inserts an extra entry at the front of `SegmentSequence` — which
is exactly what happened once `nifti_to_dcmseg` started writing
`LABELMAP`-type segmentations: `highdicom` auto-inserts a `SegmentNumber=0`
"Background" entry as `SegmentSequence[0]`, shifting every real segment's
positional index by one. The failure mode is silent — no exception, just
every output file mislabeled with the wrong segment's `CodeMeaning`.

**Why it wasn't specific to the highdicom rewrite:** this was a latent bug
in the *original* `dcmseg2nii.py` too, for any DICOM SEG producer that puts
a non-real entry first in `SegmentSequence` or otherwise doesn't number
segments in strict `1, 2, 3, ...` list order. It just happened to not be
triggered by whatever produced the SEG files `dcmseg2nii.py` was originally
tested against.

**The fix:** Build a lookup by actual `SegmentNumber` and use the real
segment number (yielded by `split_seg_channels`, see Bug 2 below) instead
of the loop index:
```python
segments_by_number = {
    segment.SegmentNumber: segment for segment in dicom_seg.SegmentSequence
}
...
for segment_number, seg_channel in split_seg_channels(dicom_seg):
    ...
    segment = segments_by_number.get(segment_number)
    if segment is None:
        raise ValueError(
            f"DICOM SEG has no SegmentSequence entry for segment number "
            f"{segment_number}"
        )
    nii_code = segment.SegmentedPropertyTypeCodeSequence[0].CodeMeaning
```
Now if a segment number genuinely has no matching `SegmentSequence` entry,
it's a loud `ValueError` instead of a silently wrong label.

## Bug 2: `highdicom`'s `number_of_segments` returns 0 for LABELMAP segmentations

**Location:** `lavlab/seg.py`, `split_seg_channels`.

**The bug:** The original code iterated:
```python
for i in range(seg_data.number_of_segments):
    yield seg_data.get_pixels_by_source_instance(
        uids, segment_numbers=[i + 1], ...
    )[..., 0]
```
Confirmed directly against the installed `highdicom==0.28.1`: reading back
a `LABELMAP`-type segmentation this code itself had just written,
`seg_data.number_of_segments` returned **`0`**, even though
`seg_data.segment_numbers` correctly returned `[1]` (the one real segment;
segment `0`/Background isn't counted, consistent with Bug 1's finding that
it's an auto-inserted extra entry). Since the loop is `range(0)`, it never
executes — `split_seg_channels` silently yields nothing, and
`dcmseg_to_nifti` returns an empty list with no error at all. This is the
worse of the two bugs: no exception, no wrong output, just *zero* output
files and no indication anything went wrong.

**The fix:** Iterate `seg_data.segment_numbers` directly instead of
`range(seg_data.number_of_segments)`, and yield the segment number alongside
its pixel array so the caller doesn't have to re-derive it (which is also
what enabled the Bug 1 fix above):
```python
def split_seg_channels(seg_data):
    segment_numbers = list(seg_data.segment_numbers)
    log.info("Number of segments: %d", len(segment_numbers))
    uids = [x[2] for x in seg_data.get_source_image_uids()]
    for segment_number in segment_numbers:
        pixels = seg_data.get_pixels_by_source_instance(
            uids, segment_numbers=[segment_number], ...
        )[..., 0]
        yield segment_number, pixels
```
This also makes the function correct for non-contiguous segment numbering
in general, not just the LABELMAP-background-offset case.

## A related non-bug worth knowing about: SimpleITK can't read LABELMAP SEGs directly

Not a bug in the code written this session, but a real interoperability gap
discovered alongside the two bugs above, and worked around defensively:
`SimpleITK`/GDCM's `sitk.ReadImage()` cannot parse the newer LABELMAP-type
multiframe SEG at all (raises `RuntimeError: ... Unable to determine
ImageIO reader ...`), even though `highdicom.seg.segread()` reads the exact
same file fine. `dcmseg_to_nifti` only used `sitk.ReadImage(dicom_seg_path)`
for one purpose — copying spacing/origin/direction metadata via
`copy_sitk_image_info` — and that metadata is, by construction, identical
to the reference NIfTI's own geometry (the segmentation shares physical
space with the series it was drawn against). The fix wraps that call:
```python
try:
    sitk_dcm_seg = sitk.ReadImage(dicom_seg_path)
except RuntimeError:
    log.info(
        "SimpleITK could not read geometry directly from %s "
        "(expected for LABELMAP-type SEGs); using the reference "
        "NIfTI's geometry instead.", dicom_seg_path,
    )
    sitk_dcm_seg = nii
```
This keeps `dcmseg_to_nifti` working both for whatever DICOM SEG files it
was originally handling (wherever `sitk.ReadImage` does succeed) and for
`lavlab seg nii2dcm`'s own LABELMAP output.

## How this was caught

A synthetic test was built specifically to exercise the real path, not just
error handling: `tests/test_seg.py`'s
`test_nifti_to_dcmseg_round_trips_through_dcmseg_to_nifti` constructs a
valid minimal 3-slice CT series with `pydicom` (proper
`SOPClassUID`/`FrameOfReferenceUID`/`ImagePositionPatient`/patient-module
tags — `highdicom` validates these strictly and will raise
`AttributeError`/`ValueError` for anything missing, which is itself how the
fixture was iteratively built up to something valid), writes a small NIfTI
mask with one 3×3 voxel region set on the middle slice, converts it to
DICOM SEG via `nifti_to_dcmseg`, converts that back to NIfTI via
`dcmseg_to_nifti`, and asserts the recovered voxel mask matches the
original exactly (`np.array_equal`). Before the fixes above, this test
would have either produced zero output files (Bug 2, caught first) or
produced a file with the wrong segment-name suffix (Bug 1, caught after
fixing Bug 2 and rerunning). This test is now permanent — see
`tests/test_seg.py`.
