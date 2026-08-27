"""Three-tier large-recon fetch orchestrator.

Tries, in order: an existing OMERO ``LargeRecon.{downsample}`` file
annotation; a locally-mounted source file; OMERO's tile API. Whichever of
the latter two produces an image is written out and (unless skipped)
uploaded back to OMERO under the same namespace so later calls hit tier one.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Literal

from lavlab.imaging import load_downsampled, write_recon
from lavlab.omero_client import get_source_file_path
from lavlab.omero_tiles import generate_over_network

log = logging.getLogger(__name__)

_NAMESPACE_PREFIX = "LargeRecon."

Tier = Literal["annotation", "local", "network"]


def _namespace(downsample: int) -> str:
    return f"{_NAMESPACE_PREFIX}{downsample}"


def _find_jp2_annotation(image, namespace: str):
    """Return the FileAnnotation for *namespace* iff its file ends in
    '.jp2'; otherwise None -- including a stale legacy '.jpg' hit, which
    must be treated as 'not found', not surfaced as an error."""
    ann = image.getAnnotation(namespace)
    if ann is None or not hasattr(ann, "getFile"):
        return None
    f = ann.getFile()
    if f is None or not f.getName().lower().endswith(".jp2"):
        return None
    return ann


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


def _upload_and_replace(conn, image, namespace: str, output_path: str) -> None:
    """Remove any stale *.jp2* annotation(s) in *namespace* -- i.e. ones this
    function itself could have written -- then upload *output_path* as the
    new one. Any other-format annotation sharing the namespace (e.g. an
    older, manually-uploaded PNG/JPG large recon) is left untouched; only
    what tier one itself would accept as "ours" is treated as replaceable.
    """
    for ann in image.listAnnotations(ns=namespace):
        if not hasattr(ann, "getFile"):
            continue
        f = ann.getFile()
        if f is None or not f.getName().lower().endswith(".jp2"):
            continue
        image.removeAnnotations([ann])
        conn.deleteObject(ann._obj)
    file_ann = conn.createFileAnnfromLocalFile(output_path, mimetype="image/jp2", ns=namespace)
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
    it to *output_path*.

    The OMERO annotation cache (both tiers) only ever holds ``.jp2`` --
    that's the canonical format `lr` shares across the lab. If *output_path*
    doesn't end in ``.jp2`` (an explicit ``-o`` naming some other format),
    the annotation tier is skipped on read (downloading raw JP2 bytes into
    a wrongly-named file would produce a corrupt file) and on write
    (uploading, say, JPEG bytes mislabeled as ``image/jp2`` would corrupt
    the shared cache for everyone). Local/network generation still honors
    whatever format *output_path* names.

    :param regenerate: Skip the annotation-tier lookup entirely and
        regenerate fresh.
    :param skip_upload: Don't write the result back to OMERO as an
        annotation.
    :return: which tier satisfied the request.
    :raises lavlab.omero_tiles.LargeReconError: propagated unwrapped from
        tier "network".
    """
    _ensure_parent_dir(output_path)
    namespace = _namespace(downsample)
    is_jp2_output = output_path.lower().endswith(".jp2")

    if not regenerate and is_jp2_output:
        ann = _find_jp2_annotation(image, namespace)
        if ann is not None:
            _download_annotation(ann, output_path)
            return "annotation"

    src_path = get_source_file_path(conn, image.getId())
    if src_path is not None and os.path.exists(src_path):
        img = load_downsampled(src_path, downsample)
        tier: Tier = "local"
    else:
        img = generate_over_network(conn, image, downsample)
        tier = "network"

    write_recon(img, output_path, lossless=True)
    del img

    if not skip_upload and is_jp2_output:
        try:
            _upload_and_replace(conn, image, namespace, output_path)
        except Exception:
            log.warning(
                "Image %d: large-recon written to '%s' but upload to OMERO "
                "failed; future runs will regenerate instead of reusing it.",
                image.getId(), output_path, exc_info=True,
            )

    return tier
