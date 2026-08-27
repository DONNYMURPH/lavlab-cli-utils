"""``lavlab roi`` -- pull ROI mask images (RGB color mask or single-channel
palette) from OMERO."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
from typing import Optional

import numpy as np
import pyvips as pv

from lavlab.commands._shared import (
    add_common_output_args,
    add_creds_args,
    connect_from_args,
    ensure_parent_dir,
    group_of,
    load_fs_map_from_args,
    parse_target,
)
from lavlab.config import ConfigError
from lavlab.imaging import write_recon
from lavlab.naming import resolve_output_path
from lavlab.omero_client import get_source_file_path, is_conn_error, iter_image_ids
from lavlab.roi import get_roi_mask

log = logging.getLogger(__name__)

DEFAULT_SUFFIX = "_annot"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("roi", help="Pull ROI mask images from OMERO.")
    parser.add_argument("target", help="An OMERO image ID, or 'batch' to pull all images.")
    parser.add_argument("-o", "--output", help="Output file (single) or directory (batch).")
    parser.add_argument("-g", "--group", type=int, help="OMERO group ID (batch mode only).")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for batch mode (default: 8).")
    parser.add_argument("-a", "--all", action="store_true", help="Include every annotation, regardless of textValue.")
    parser.add_argument(
        "-t", "--text-filter",
        type=str.lower, action="append", default=[],
        help="Whitelist of textValue annotations to include (repeatable).",
    )
    parser.add_argument("--suffix", default=DEFAULT_SUFFIX, help=f"Filename suffix (default: '{DEFAULT_SUFFIX}').")
    parser.add_argument(
        "--palette", action="store_true",
        help="Emit a single-channel label mask ordered by --text-filter instead of an RGB color mask.",
    )
    add_common_output_args(parser)
    add_creds_args(parser)
    parser.set_defaults(handler=run)


def _validate_selection(args: argparse.Namespace) -> None:
    if args.all and args.palette:
        raise SystemExit(
            "error: --all is not supported with --palette; manually define --text-filter values instead."
        )
    if not args.all and not args.text_filter:
        raise SystemExit("error: specify --all or at least one --text-filter value.")


def run(args: argparse.Namespace) -> None:
    _validate_selection(args)
    target = parse_target(args.target)
    if target == "batch":
        _run_batch(args)
    else:
        _run_single(args, target)


def _render_and_write(image, args: argparse.Namespace, output_path: str) -> Optional[int]:
    """Render and write the ROI mask; returns how many shapes were
    rendered, or None if nothing matched the given filters."""
    mask, shape_count = get_roi_mask(
        image, args.downsample, include_all=args.all, text_filter=args.text_filter, palette=args.palette
    )
    if mask.size == 0:
        log.info("Image %d: no ROIs matched the given filters.", image.getId())
        return None
    ensure_parent_dir(output_path)
    roi_img = pv.Image.new_from_array(mask)
    del mask
    write_recon(roi_img, output_path, lossless=True)
    return shape_count


def _run_single(args: argparse.Namespace, image_id: int) -> None:
    conn = connect_from_args(args)
    try:
        image = conn.getObject("Image", image_id)
        if image is None:
            raise SystemExit(f"error: image {image_id} not found.")
        group_id = group_of(conn, image)
        name = image.getName()

        fs_map = load_fs_map_from_args(args)
        try:
            output_path = resolve_output_path(
                args.output, fs_map, group_id, name, args.downsample,
                suffix=args.suffix, ext="jp2", batch=False,
            )
        except ConfigError as exc:
            raise SystemExit(f"error: {exc}")

        if os.path.exists(output_path) and not args.override:
            print(f"Already exists, skipping (use --override to replace): {output_path}")
            return

        shape_count = _render_and_write(image, args, output_path)
        if shape_count is None:
            raise SystemExit(f"error: no ROIs found for image {image_id} under the given filters.")
        print(f"Completed ROI for image {image_id}: {output_path} ({shape_count} shape(s))")
    finally:
        conn.close()


_WORKER_STATE: dict = {}


def _init_worker(args: argparse.Namespace, fs_map) -> None:
    global _WORKER_STATE
    _WORKER_STATE = {
        "conn": connect_from_args(args),
        "args": args,
        "fs_map": fs_map,
    }


def _process_one(image_id: int):
    args = _WORKER_STATE["args"]
    fs_map = _WORKER_STATE["fs_map"]
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            conn = _WORKER_STATE["conn"]
            if not conn.isConnected():
                conn = connect_from_args(args)
                _WORKER_STATE["conn"] = conn

            image = conn.getObject("Image", image_id)
            if image is None:
                log.warning("Image %d not found, skipping.", image_id)
                return None

            group_id = args.group if args.group is not None else group_of(conn, image)
            name = image.getName()

            output_path = resolve_output_path(
                args.output, fs_map, group_id, name, args.downsample,
                suffix=args.suffix, ext="jp2", batch=True,
            )
            if output_path is None:
                log.warning("Image %d: no usable output directory, skipping.", image_id)
                return None

            if os.path.exists(output_path) and not args.override:
                return (image_id, output_path)

            shape_count = _render_and_write(image, args, output_path)
            if shape_count is None:
                return None

            print(f"Completed ROI for image {image_id}: {output_path} ({shape_count} shape(s))")
            return (image_id, output_path)
        except ConfigError:
            raise
        except Exception as exc:
            if is_conn_error(exc) and attempt < max_attempts:
                log.warning("Image %d: connection error, retrying: %s", image_id, exc)
                _WORKER_STATE["conn"] = connect_from_args(args)
                continue
            log.exception("Image %d: unhandled error.", image_id)
            return None
    return None


def _run_batch(args: argparse.Namespace) -> None:
    fs_map = load_fs_map_from_args(args)
    conn = connect_from_args(args)
    try:
        image_ids = list(iter_image_ids(conn, args.group))
    finally:
        conn.close()

    log.info("Found %d images. Starting %d workers.", len(image_ids), args.workers)

    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(args.workers, initializer=_init_worker, initargs=(args, fs_map)) as pool:
        results = list(pool.imap_unordered(_process_one, image_ids))

    completed = [r for r in results if r is not None]
    print(f"Batch complete: {len(completed)}/{len(image_ids)} images processed.")
