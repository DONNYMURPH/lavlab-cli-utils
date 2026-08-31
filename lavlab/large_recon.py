# SPDX-FileCopyrightText: 2026-present LavLab <domurphy@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""Three-tier large-recon fetch orchestrator.

Tries, in order: an existing OMERO ``LargeRecon.{downsample}`` file
annotation matching the requested format; a locally-mounted source file;
OMERO's tile API. Whichever of the latter two produces an image is written
out and (unless skipped) uploaded back to OMERO under the same namespace,
under a canonical ``LR{downsample}_{image name}.{ext}`` filename independent
of wherever it was written locally, so later calls at the same
downsample+format hit tier one.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Literal

from lavlab.imaging import load_downsampled, write_recon
from lavlab.naming import build_filename
from lavlab.omero_client import get_source_file_path
from lavlab.omero_tiles import generate_over_network

log = logging.getLogger(__name__)

_NAMESPACE_PREFIX = "LargeRecon."

_MIMETYPES = {
    "jp2": "image/jp2",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}

Tier = Literal["annotation", "local", "network"]


def _namespace(downsample: int) -> str:
    return f"{_NAMESPACE_PREFIX}{downsample}"


def _ext_of(output_path: str) -> str:
    return os.path.splitext(output_path)[1].lstrip(".").lower()


def _mimetype_for_ext(ext: str) -> str:
    return _MIMETYPES.get(ext, "application/octet-stream")


def _find_annotation(image, namespace: str, ext: str):
    """Return the FileAnnotation in *namespace* whose file ends in
    ``.{ext}``, searching every annotation under the namespace (not just
    OMERO's arbitrary "first" match) so a namespace holding more than one
    format -- e.g. both a .jp2 and a .jpg at the same downsample -- still
    finds the one that actually matches what was asked for."""
    for ann in image.listAnnotations(ns=namespace):
        if not hasattr(ann, "getFile"):
            continue
        f = ann.getFile()
        if f is not None and f.getName().lower().endswith(f".{ext}"):
            return ann
    return None


def _download_annotation(ann, output_path: str) -> None:
    """Download *ann*'s bytes to *output_path*, atomically.

    Writes to a '.part' sibling and only replaces output_path once the
    full download succeeds, so a partial/aborted download can never be
    mistaken for a completed output by a later exists-skip check.
    """
    tmp_path = output_path + ".part"
    try:
        with open(tmp_path, "wb") as fh:
            for chunk in ann.getFileInChunks():
                fh.write(chunk)
        os.replace(tmp_path, output_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def _upload_and_replace(
    conn, image, namespace: str, output_path: str, ext: str, remote_name: str
) -> None:
    """Remove any stale annotation(s) in *namespace* matching *ext* -- i.e.
    ones this function itself could have written in this same format --
    then upload *output_path* as the new one, named *remote_name* (the
    canonical ``LR{downsample}_{image name}.{ext}``, independent of
    whatever local path it was written to). Annotations in other formats
    sharing the namespace (e.g. an older, manually-uploaded PNG/JPG large
    recon) are left untouched; only what tier one itself would accept as
    "ours" for this format is treated as replaceable.
    """
    for ann in image.listAnnotations(ns=namespace):
        if not hasattr(ann, "getFile"):
            continue
        f = ann.getFile()
        if f is None or not f.getName().lower().endswith(f".{ext}"):
            continue
        image.removeAnnotations([ann])
        conn.deleteObject(ann._obj)
    file_ann = conn.createFileAnnfromLocalFile(
        output_path, origFilePathAndName=remote_name,
        mimetype=_mimetype_for_ext(ext), ns=namespace,
    )
    image.linkAnnotation(file_ann)


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def fetch_large_recon(
    conn,
    image,
    downsample: int,
    output_path: str,
    *,
    regenerate: bool = False,
    skip_upload: bool = False,
) -> Tier:
    """Fetch or generate a large-recon for *image* at *downsample*, writing
    it to *output_path*. The requested format is whatever *output_path*'s
    extension is -- that's the single source of truth for what gets
    written, what the annotation cache is searched/uploaded as, and what
    mimetype is recorded.

    :param regenerate: Skip the annotation-tier lookup entirely and
        regenerate fresh.
    :param skip_upload: Don't write the result back to OMERO as an
        annotation.
    :return: which tier satisfied the request.
    :raises lavlab.omero_tiles.LargeReconError: propagated unwrapped from
        tier "network".
    """
    image_id = image.getId()
    _ensure_parent_dir(output_path)
    namespace = _namespace(downsample)
    ext = _ext_of(output_path)
    cache_eligible = bool(ext)

    if cache_eligible and not regenerate:
        ann = _find_annotation(image, namespace, ext)
        if ann is not None:
            log.info(
                "Image %d: found cached .%s large-recon (namespace %s); downloading...",
                image_id, ext, namespace,
            )
            _download_annotation(ann, output_path)
            log.info("Image %d: downloaded cached recon to %s.", image_id, output_path)
            return "annotation"

    src_path = get_source_file_path(conn, image_id)
    if src_path is not None and os.path.exists(src_path):
        log.info("Image %d: no usable cache; generating from local source %s...",
                  image_id, src_path)
        img = load_downsampled(src_path, downsample)
        tier: Tier = "local"
    else:
        log.info(
            "Image %d: no usable cache or local source; generating over the "
            "network (this can take several minutes)...", image_id,
        )
        img = generate_over_network(conn, image, downsample)
        tier = "network"

    log.info("Image %d: writing recon to %s...", image_id, output_path)
    write_recon(img, output_path, lossless=True)
    del img
    log.info("Image %d: wrote %s.", image_id, output_path)

    if not skip_upload and cache_eligible:
        remote_name = build_filename(downsample, image.getName(), ext=ext)
        log.info("Image %d: uploading recon to OMERO as %s (namespace %s)...",
                  image_id, remote_name, namespace)
        try:
            _upload_and_replace(conn, image, namespace, output_path, ext, remote_name)
        except Exception:
            log.warning(
                "Image %d: large-recon written to '%s' but upload to OMERO "
                "failed; future runs will regenerate instead of reusing it.",
                image_id, output_path, exc_info=True,
            )
        else:
            log.info("Image %d: uploaded and linked as %s.", image_id, remote_name)

    return tier
