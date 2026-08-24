#!/usr/bin/env python3
"""
Batch large-recon JP2 generator and OMERO uploader for project 51.

For every image in the project:
  1. Resolve the expected output paths from the image name.
  2. Skip if both the .jp2 and .omero.id files already exist locally.
  3. Generate the large recon, save as lossless JP2.
  4. Write a blank <omero_id>.omero.id sidecar file next to the JP2.
  5. Upload the JP2 back to the OMERO image as a file annotation.

Runs ~10 worker processes in parallel; each worker opens its own OMERO
connection so connections are never shared across process boundaries.

apt-get install -y libvips libvips-tools libopenjp2-7 openslide-tools
"""

import glob
import json
import logging
import os
import re
import time
import random
import multiprocessing

import omero.sys
import numpy as np
import tifffile
import pyvips as pv
from omero.gateway import BlitzGateway
from tqdm import tqdm

# ── Configuration ──────────────────────────────────────────────────────────────
OMERO_HOST = "ws://omero-server.omero-system.svc"
OMERO_PORT = 4065
OMERO_USER = "mjbarrett"
OMERO_PASS = "gzyxby01"

PROJECT_ID = 51
BASE_PATH = "/Volumes/Siren/Prostate_data/"
NUM_WORKERS = 12

# Set True to regenerate and re-upload every image, replacing any existing
# JP2 file and OMERO annotation (use this to fix the grayscale batch).
OVERWRITE = False

# Print completed image IDs and paths to stdout when True.
PRINT_COMPLETED = True

# Namespace tag applied to the file annotation so it can be found later
FILE_ANN_NS = "LargeRecon.10"

NAME_RE = re.compile(r"N(\d+)_S(\d+)(_Deeper\d*)?_(\w+)\.ome\.tiff")
BIOPSY_RE = re.compile(r"N(\d+)_(.+)_([^_]+)_(Biopsy|TURP)\.ome\.tiff")

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.ERROR,
    format="%(processName)-20s %(asctime)s %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _connect() -> BlitzGateway:
    retries = 5
    base_delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            conn = BlitzGateway(
                OMERO_USER, OMERO_PASS,
                host=OMERO_HOST, port=OMERO_PORT, secure=True,
            )
            if conn.connect():
                return conn
            log.info("Failed to create session. Attempt %d/%d", attempt, retries)
            try:
                conn.close()
            except Exception:
                pass
        except Exception as exc:
            log.info("Failed to create session. Attempt %d/%d: %s", attempt, retries, exc)

        if attempt < retries:
            sleep_time = base_delay * (2 ** (attempt - 1)) + random.random()
            time.sleep(sleep_time)

    raise RuntimeError("Failed to connect to OMERO after %d attempts" % retries)


# ── Per-worker persistent connection ──────────────────────────────────────────
_worker_conn: "BlitzGateway | None" = None


def _init_worker() -> None:
    """Pool initializer: open one OMERO connection per worker process."""
    global _worker_conn
    # Disable pyvips operation/tile cache — without this, pyvips accumulates
    # decoded tiles across images and worker RAM grows without bound.
    pv.cache_set_max(0)
    pv.cache_set_max_mem(0)
    pv.cache_set_max_files(0)
    _worker_conn = _connect()


def _get_worker_conn() -> BlitzGateway:
    """Return the worker-local connection, reconnecting if the session dropped."""
    global _worker_conn
    if _worker_conn is None or not _worker_conn.isConnected():
        if _worker_conn is not None:
            try:
                _worker_conn.close()
            except Exception:
                pass
        _worker_conn = _connect()
    return _worker_conn


def _is_rgb(jp2_path: str) -> bool:
    """Return True if the JP2 at *jp2_path* has 3 bands (RGB)."""
    try:
        return pv.Image.new_from_file(jp2_path, access="sequential").bands == 3
    except Exception:
        return False


def _resolve_paths(image_id: int, name: str) -> tuple[str, str] | None:
    """Return (jp2_path, omero_id_path) for an image name, or None if unparseable."""
    if "_Biopsy" in name or "_TURP" in name:
        match = BIOPSY_RE.match(name)
        if not match:
            log.warning("Image %d: biopsy name '%s' does not match biopsy pattern, skipping.", image_id, name)
            return None
        subject = match.group(1)
        slide_folder = match.group(2)
        stain = match.group(3)
    else:
        match = NAME_RE.match(name)
        if not match:
            log.warning("Image %d: name '%s' does not match expected pattern, skipping.", image_id, name)
            return None
        subject = match.group(1)
        slide_raw = match.group(2)
        deeper = match.group(3) or ""  # e.g. "_Deeper[2]" or ""
        stain = match.group(4)
        # Strip leading zeros but keep at least one digit
        slide = slide_raw.lstrip("0") or "0"
        # Slide folder incorporates optional _Deeper[N] suffix (e.g. "1" or "1_Deeper[2]")
        slide_folder = slide + deeper

    subject_dirs = glob.glob(f"{BASE_PATH}*{subject}")
    if not subject_dirs:
        log.warning("Image %d: no directory found for subject %s, skipping.", image_id, subject)
        return None

    subject_dir = subject_dirs[0]

    # Non-HE stains get their own subdirectory under the slide folder
    if stain == "HE":
        output_dir = os.path.join(subject_dir, "Hist", slide_folder, "Huron")
    else:
        output_dir = os.path.join(subject_dir, "Hist", slide_folder, "Huron", stain)

    # JP2 filename: LR10_ prepended to the stem of the original OMERO name
    stem = name.split(".")[0]
    jp2_path = os.path.join(output_dir, f"LR10_{stem}.jp2")
    omero_id_path = os.path.join(output_dir, f"{image_id}.omero.id")

    return jp2_path, omero_id_path


def _load_lr_image(src_path: str) -> pv.Image:
    """Return a pyvips Image at exactly 1/10th the full-resolution dimensions.

    Uses tifffile to read pyramid levels so that tiled separate-plane OME-TIFFs
    (which pyvips cannot load) are handled correctly.
    """
    with tifffile.TiffFile(src_path) as tif:
        if not tif.series:
            log.warning(
                "No TIFF series found in '%s'; falling back to pyvips for load.",
                src_path,
            )
            try:
                img = pv.Image.tiffload(src_path, access="sequential")
                target_w = max(1, round(img.width / 10))
                target_h = max(1, round(img.height / 10))
                return img.resize(target_w / img.width, vscale=target_h / img.height)
            except pv.Error:
                pass

            # pyvips tiffload failed (e.g. bad seek in BigTIFF); try openslide.
            log.warning(
                "pyvips tiffload failed for '%s'; falling back to openslide.", src_path
            )
            import openslide
            slide = openslide.OpenSlide(src_path)
            full_w, full_h = slide.dimensions
            target_w = max(1, round(full_w / 10))
            target_h = max(1, round(full_h / 10))
            best_level = slide.get_best_level_for_downsample(10)
            lw, lh = slide.level_dimensions[best_level]
            region = slide.read_region((0, 0), best_level, (lw, lh))
            arr = np.array(region.convert("RGB"))
            img = pv.Image.new_from_array(arr)
            del arr
            return img.resize(target_w / img.width, vscale=target_h / img.height)
        series = tif.series[0]
        axes = series.axes          # e.g. 'CZYX', 'CYX', 'YXC', 'YX'
        shape = series.shape

        y_ax = axes.index('Y')
        x_ax = axes.index('X')
        full_h, full_w = shape[y_ax], shape[x_ax]
        target_h = max(1, round(full_h / 10))
        target_w = max(1, round(full_w / 10))

        # Walk pyramid levels (index 0 = full res) and pick the smallest level
        # that is still >= the target so we always downsample, never upsample.
        best_idx = 0
        for i, lvl in enumerate(series.levels[1:], 1):
            if lvl.shape[y_ax] >= target_h and lvl.shape[x_ax] >= target_w:
                best_idx = i
            else:
                break

        log.debug(
            "Source %s: full=%dx%d target=%dx%d using level %d",
            src_path, full_w, full_h, target_w, target_h, best_idx,
        )

        arr = series.levels[best_idx].asarray()

    # Normalise arr to (H, W) or (H, W, C) for pyvips.
    # Drop singleton/unwanted axes (T, Z, …) from highest index to lowest
    # so earlier indices are not disturbed.
    # 'S' is the RGB sample axis used by brightfield WSI scanners; treat it
    # like 'C' so it is kept rather than collapsed to a single plane.
    drop = sorted(
        [i for i, a in enumerate(axes) if a not in ('Y', 'X', 'C', 'S')],
        reverse=True,
    )
    for i in drop:
        arr = np.take(arr, 0, axis=i)

    # Remaining axes are some permutation of 'YX', 'YXS', 'CYX', 'YXC', etc.
    # Normalise 'S' → 'C' so the rest of the logic is uniform.
    remaining = ''.join(a for a in axes if a in ('Y', 'X', 'C', 'S'))
    remaining = remaining.replace('S', 'C')
    target_axes = 'YX' + ('C' if 'C' in remaining else '')
    if remaining != target_axes:
        perm = [remaining.index(a) for a in target_axes]
        arr = arr.transpose(perm)

    img = pv.Image.new_from_array(arr)
    del arr  # new_from_array copies the buffer; release the numpy allocation now
    return img.resize(target_w / img.width, vscale=target_h / img.height)


def _get_source_file_path(conn: BlitzGateway, image_id: int) -> str | None:
    """Return the absolute server-side path of the primary OME-TIFF for an image.

    Uses the fileset → usedFiles → originalFile relationship so the path is
    always what OMERO recorded on import — the same path visible from any pod
    that mounts the same storage.
    """
    qs = conn.getQueryService()
    params = omero.sys.ParametersI()
    params.addId(image_id)
    files = qs.findAllByQuery(
        "select f from Image i "
        "join i.fileset fs "
        "join fs.usedFiles fe "
        "join fe.originalFile f "
        "where i.id = :id",
        params,
        conn.SERVICE_OPTS,
    )
    if not files:
        return None

    # Prefer the largest file — that's the primary OME-TIFF in a multi-file set.
    files.sort(key=lambda f: f.size.val if f.size is not None else 0, reverse=True)
    f = files[0]
    return "/OMERO/ManagedRepository/" + f.path.val + f.name.val


# ── Per-image worker ───────────────────────────────────────────────────────────
def _is_conn_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a transient OMERO/Ice connection failure."""
    name = type(exc).__name__
    msg = str(exc)
    return (
        "Ice" in name
        or "omero" in name.lower()
        or "connect" in msg.lower()
        or "timeout" in msg.lower()
        or "session" in msg.lower()
    )


def process_image(image_id: int) -> tuple[int, str] | None:
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
      try:
        conn = _get_worker_conn()
        image = conn.getObject("Image", image_id)
        if image is None:
            log.warning("Image %d not found in OMERO, skipping.", image_id)
            return None

        name = image.getName()
        paths = _resolve_paths(image_id, name)
        if paths is None:
            return None

        jp2_path, omero_id_path = paths

        already_local = os.path.exists(jp2_path) and os.path.exists(omero_id_path)

        if already_local and not OVERWRITE:
            # Sidecar is written after upload, so its presence guarantees completion.
            log.info("Image %d already processed and uploaded, skipping.", image_id)
            if PRINT_COMPLETED:
                print(f"Completed image {image_id}: {jp2_path}")
            return (image_id, jp2_path)
        elif already_local and OVERWRITE and _is_rgb(jp2_path):
            # JP2 is already RGB — nothing to fix; skip overwrite.
            log.info("Image %d: existing JP2 is already RGB, skipping overwrite.", image_id)
            if PRINT_COMPLETED:
                print(f"Completed image {image_id}: {jp2_path}")
            return (image_id, jp2_path)
        else:
            log.info("Image %d (%s): generating large recon...", image_id, name)
            src_path = _get_source_file_path(conn, image_id)
            if src_path is None:
                log.error("Image %d: no source file found in fileset, skipping.", image_id)
                return None
            if not os.path.exists(src_path):
                log.error(
                    "Image %d: source file '%s' is not accessible from this pod, skipping.",
                    image_id, src_path,
                )
                return None

            os.makedirs(os.path.dirname(jp2_path), exist_ok=True)

            _load_lr_image(src_path).write_to_file(jp2_path, lossless=True)
            log.info("Image %d: saved JP2 → %s", image_id, jp2_path)

        # Remove any existing annotation in this namespace before uploading.
        # In OVERWRITE mode this includes existing JP2s (the whole point);
        # otherwise only remove stale non-JP2 annotations.
        for ann in image.listAnnotations(ns=FILE_ANN_NS):
            if hasattr(ann, "getFile"):
                orig_file = ann.getFile()
                if orig_file is not None and (OVERWRITE or not orig_file.getName().endswith(".jp2")):
                    log.info(
                        "Image %d: removing old annotation '%s' (id=%d).",
                        image_id, orig_file.getName(), ann.getId(),
                    )
                    image.removeAnnotations([ann])
                    conn.deleteObject(ann._obj)

        file_ann = conn.createFileAnnfromLocalFile(
            jp2_path,
            mimetype="image/jp2",
            ns=FILE_ANN_NS,
        )
        image.linkAnnotation(file_ann)
        log.info("Image %d: uploaded JP2 annotation to OMERO.", image_id)

        # Sidecar written after successful upload so its presence = upload done.
        with open(omero_id_path, "w") as f:
            f.write("")
        log.info("Image %d: wrote sidecar → %s", image_id, omero_id_path)

        if PRINT_COMPLETED:
            print(f"Completed image {image_id}: {jp2_path}")
        return (image_id, jp2_path)

      except Exception as exc:
        if _is_conn_error(exc) and attempt < max_attempts:
            global _worker_conn
            _worker_conn = None
            log.warning(
                "Image %d: connection error on attempt %d/%d, reconnecting: %s",
                image_id, attempt, max_attempts, exc,
            )
            time.sleep(1.0 * attempt)
            continue
        log.exception("Image %d: unhandled error.", image_id)
        return None
    return None


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    conn = _connect()
    try:
        project = conn.getObject("Project", PROJECT_ID)
        if project is None:
            raise RuntimeError(f"Project {PROJECT_ID} not found.")

        image_ids = [
            image.getId()
            for dataset in project.listChildren()
            for image in dataset.listChildren()
        ]
    finally:
        conn.close()

    log.info("Found %d images in project %d. Starting pool of %d workers.",
             len(image_ids), PROJECT_ID, NUM_WORKERS)

    ctx = multiprocessing.get_context('fork')
    with ctx.Pool(NUM_WORKERS, initializer=_init_worker) as pool:
        results = list(tqdm(
            pool.imap_unordered(process_image, image_ids),
            total=len(image_ids),
            desc="Images",
            unit="img",
        ))

    # Merge new mappings into any existing JSON file.
    mapping_path = os.path.join(BASE_PATH, "omero_id_mappings.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r") as f:
            mappings: dict[str, str] = json.load(f)
    else:
        mappings = {}

    for result in results:
        if result is not None:
            omero_id, jp2_path = result
            mappings[str(omero_id)] = jp2_path

    with open(mapping_path, "w") as f:
        json.dump(mappings, f, indent=2)
    log.info("Wrote %d mappings to %s", len(mappings), mapping_path)

    log.info("Batch complete.")


if __name__ == "__main__":
    main()
