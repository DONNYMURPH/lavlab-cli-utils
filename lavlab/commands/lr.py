"""``lavlab lr`` -- pull large-recon (downsampled) images from OMERO."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os

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
from lavlab.imaging import load_downsampled
from lavlab.naming import resolve_output_path
from lavlab.omero_client import get_source_file_path, is_conn_error, iter_image_ids

log = logging.getLogger(__name__)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("lr", help="Pull large-recon downsampled images from OMERO.")
    parser.add_argument("target", help="An OMERO image ID, or 'batch' to pull all images.")
    parser.add_argument("-o", "--output", help="Output file (single) or directory (batch).")
    parser.add_argument("-g", "--group", type=int, help="OMERO group ID (batch mode only).")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for batch mode (default: 8).")
    add_common_output_args(parser)
    add_creds_args(parser)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    target = parse_target(args.target)
    if target == "batch":
        _run_batch(args)
    else:
        _run_single(args, target)


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
                args.output, fs_map, group_id, name, args.downsample, ext="jp2", batch=False
            )
        except ConfigError as exc:
            raise SystemExit(f"error: {exc}")

        if os.path.exists(output_path) and not args.override:
            print(f"Already exists, skipping (use --override to replace): {output_path}")
            return

        src_path = get_source_file_path(conn, image_id)
        if src_path is None or not os.path.exists(src_path):
            raise SystemExit(f"error: source file for image {image_id} is not accessible.")

        ensure_parent_dir(output_path)
        lossless = output_path.lower().endswith(".jp2")
        load_downsampled(src_path, args.downsample).write_to_file(output_path, lossless=lossless)
        print(f"Completed image {image_id}: {output_path}")
    finally:
        conn.close()


# Per-worker state, populated by the pool initializer since Pool.imap only
# forwards a single positional argument to the worker function.
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
                args.output, fs_map, group_id, name, args.downsample, ext="jp2", batch=True
            )
            if output_path is None:
                log.warning("Image %d: no usable output directory, skipping.", image_id)
                return None

            if os.path.exists(output_path) and not args.override:
                return (image_id, output_path)

            src_path = get_source_file_path(conn, image_id)
            if src_path is None or not os.path.exists(src_path):
                log.warning("Image %d: source file not accessible, skipping.", image_id)
                return None

            ensure_parent_dir(output_path)
            lossless = output_path.lower().endswith(".jp2")
            load_downsampled(src_path, args.downsample).write_to_file(output_path, lossless=lossless)
            print(f"Completed image {image_id}: {output_path}")
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
