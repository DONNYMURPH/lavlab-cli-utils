# SPDX-FileCopyrightText: 2026-present LavLab <domurphy@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""``lavlab tile`` -- cut whole-slide images into fixed-size training tiles."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
from collections import Counter

from lavlab.commands._shared import (
    add_creds_args,
    connect_from_args,
    group_of,
    parse_target,
)

log = logging.getLogger(__name__)

DEFAULT_MPP = 0.5
DEFAULT_SIZE = 224
DEFAULT_MIN_COVERAGE = 0.5
DEFAULT_TISSUE_THRESH = 0.5
DEFAULT_BACKGROUND_LABEL = "benign"
DEFAULT_BACKGROUND_MARGIN = 200
DEFAULT_MAX_BACKGROUND_TILES = 2000
DEFAULT_EXCLUDE_TEXT = ("exclusion roi",)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "tile", help="Cut whole-slide images into fixed-size tiles for training."
    )
    parser.add_argument("target", help="An OMERO image ID, or 'batch' to tile a whole group.")
    parser.add_argument("-o", "--out", required=True, metavar="DIR",
                        help="Output root directory (required).")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--whole", action="store_true",
                      help="Tile the whole slide (tissue only), under a flat 'whole/' label. "
                           "For inference or unannotated slides -- its output is never "
                           "treated as a benign class.")
    mode.add_argument("--roi", action="store_true",
                      help="Tile only inside ROIs, labelling each tile by the annotation "
                           "it falls in.")

    parser.add_argument("-a", "--all", action="store_true",
                        help="--roi: include every annotation regardless of textValue.")
    parser.add_argument("-t", "--text-filter", type=str.lower, action="append", default=[],
                        help="--roi: whitelist a textValue or class folder name "
                             "(repeatable, case-insensitive). Mutually exclusive with --all.")

    scale = parser.add_mutually_exclusive_group()
    scale.add_argument("--mpp", type=float, default=None,
                       help=f"Target micrometres per pixel (default: {DEFAULT_MPP}). Read "
                            "against the image's own pixel size to pick a pyramid level "
                            "and resize factor. Errors out if the image has no pixel "
                            "size recorded -- use --downsample instead.")
    scale.add_argument("--downsample", type=float, default=None, metavar="N",
                       help="Use an explicit level-0-pixels-per-output-pixel factor "
                            "instead of --mpp. The only option for an image with no "
                            "physical pixel size.")

    parser.add_argument("--size", type=int, default=DEFAULT_SIZE,
                        help=f"Tile edge in output pixels (default: {DEFAULT_SIZE}).")
    parser.add_argument("--overlap", type=int, default=0,
                        help="Overlap between neighbouring tiles in output pixels; stride "
                             "is size - overlap (default: 0).")
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE,
                        help="--roi: fraction of a tile that must lie inside one class's "
                             f"ROI area for it to take that class (default: {DEFAULT_MIN_COVERAGE}). "
                             "The highest-covering qualifying class wins.")
    parser.add_argument("--tissue-thresh", type=float, default=DEFAULT_TISSUE_THRESH,
                        help="Minimum tissue fraction to keep a tile, in both modes "
                             f"(default: {DEFAULT_TISSUE_THRESH}).")
    parser.add_argument("--format", choices=["png", "jpg"], default=None,
                        help="Tile image format (default: png). Rejected with "
                             "--coords-only, which writes no images at all.")
    parser.add_argument("--coords-only", action="store_true",
                        help="Write only the manifest and parameters, no image files. A "
                             "40x whole-mount grids to 80-100k tiles, so this is how you "
                             "survey a slide without materialising them.")
    parser.add_argument("--labels", metavar="PATH",
                        help="Custom textValue -> class folder YAML (default: the bundled "
                             "lavlab/data/default_tile_labels.yaml).")

    parser.add_argument("--exclude-text", type=str.lower, action="append", default=None,
                        help="textValue marking an exclusion region; any tile overlapping "
                             "one at all is dropped, in both modes (repeatable, default: "
                             f"{', '.join(DEFAULT_EXCLUDE_TEXT)}).")

    parser.add_argument("--background-label", default=None, metavar="NAME",
                        help="--roi: folder for tissue tiles inside no ROI on an annotated "
                             f"slide (default: {DEFAULT_BACKGROUND_LABEL}). Annotators mark "
                             "everything, so such tissue is genuinely benign -- but only on "
                             "a slide that has ROIs, so slides with none are skipped instead.")
    parser.add_argument("--no-background", action="store_true",
                        help="--roi: don't emit background tiles at all.")
    parser.add_argument("--background-margin", type=int, default=None, metavar="UM",
                        help="--roi: keep background tiles this many micrometres clear of "
                             f"every ROI (default: {DEFAULT_BACKGROUND_MARGIN}), so tiles "
                             "straddling an annotation edge aren't called benign.")
    parser.add_argument("--max-background-tiles", type=int, default=None, metavar="N",
                        help="--roi: cap background tiles per slide, sampled at random "
                             f"(default: {DEFAULT_MAX_BACKGROUND_TILES}). Background "
                             "otherwise vastly outnumbers every graded class.")

    parser.add_argument("--max-tiles", type=int, default=None, metavar="N",
                        help="Cap tiles per slide, sampled at random. Handy for a quick test run.")
    parser.add_argument("--max-tiles-per-label", type=int, default=None, metavar="N",
                        help="Cap tiles per class per slide, sampled at random.")
    parser.add_argument("--seed", type=int, default=0,
                        help="Seed for every random sample, so a slide tiled twice with the "
                             "same settings yields the same tiles (default: 0).")

    parser.add_argument("--force-local", action="store_true",
                        help="Read a JPEG-2000 source locally anyway. By default a bare .jp2 "
                             "falls forward to the network tier, because the bundled libvips "
                             "has no jp2k loader and every tile would decode the whole "
                             "codestream through Pillow.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip slides whose manifest.csv and tile_params.json show a "
                             "finished run with these same parameters. A slide tiled with "
                             "*different* parameters is warned about and skipped too, unless "
                             "the global --override is given (which re-tiles it).")

    parser.add_argument("-g", "--group", type=int, help="OMERO group ID (batch mode only).")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel workers for batch mode (default: 8).")
    add_creds_args(parser)
    parser.set_defaults(handler=run)


def _validate_args(args: argparse.Namespace) -> None:
    """Reject flag combinations that cannot mean anything, before connecting."""
    if args.whole:
        if args.all or args.text_filter:
            raise SystemExit(
                "error: --all and --text-filter select annotations, which --whole "
                "ignores; use --roi, or drop them."
            )
        for flag, value in (
            ("--background-label", args.background_label),
            ("--background-margin", args.background_margin),
            ("--max-background-tiles", args.max_background_tiles),
        ):
            if value is not None:
                raise SystemExit(
                    f"error: {flag} only applies to --roi; --whole writes every tissue "
                    "tile under 'whole/' and has no background class."
                )
        if args.no_background:
            raise SystemExit(
                "error: --no-background only applies to --roi; --whole has no "
                "background class to turn off."
            )
    else:
        if args.all and args.text_filter:
            raise SystemExit(
                "error: --all and --text-filter are contradictory -- one takes every "
                "annotation, the other a whitelist. Pick one."
            )
        if not args.all and not args.text_filter:
            raise SystemExit(
                "error: --roi needs to know which annotations to use: pass --all or at "
                "least one --text-filter value."
            )
        if args.no_background and args.background_label is not None:
            raise SystemExit(
                "error: --no-background and --background-label are contradictory -- one "
                "turns the background class off, the other names it."
            )

    if args.size <= 0:
        raise SystemExit(f"error: --size must be positive, got {args.size}.")
    if not 0 <= args.overlap < args.size:
        raise SystemExit(
            f"error: --overlap must be at least 0 and less than --size ({args.size}), "
            f"got {args.overlap}."
        )
    if not 0.0 <= args.min_coverage <= 1.0:
        raise SystemExit(
            f"error: --min-coverage is a fraction between 0 and 1, got {args.min_coverage}."
        )
    if not 0.0 <= args.tissue_thresh <= 1.0:
        raise SystemExit(
            f"error: --tissue-thresh is a fraction between 0 and 1, got {args.tissue_thresh}."
        )
    if args.coords_only and args.format is not None:
        raise SystemExit(
            "error: --coords-only writes no image files, so --format has nothing to "
            "apply to; drop one or the other."
        )
    if args.mpp is not None and args.mpp <= 0:
        raise SystemExit(f"error: --mpp must be positive, got {args.mpp}.")
    if args.downsample is not None and args.downsample <= 0:
        raise SystemExit(f"error: --downsample must be positive, got {args.downsample}.")
    if args.background_margin is not None and args.background_margin < 0:
        raise SystemExit(
            f"error: --background-margin must be zero or greater, got {args.background_margin}."
        )
    for flag, value in (
        ("--max-tiles", args.max_tiles),
        ("--max-tiles-per-label", args.max_tiles_per_label),
        ("--max-background-tiles", args.max_background_tiles),
    ):
        if value is not None and value < 0:
            raise SystemExit(f"error: {flag} must be zero or greater, got {value}.")


def _build_params(args: argparse.Namespace):
    """Turn the parsed arguments into a :class:`lavlab.tiling.TileParams`."""
    from lavlab.tiling import TileParams

    if args.downsample is not None:
        mpp = None
        downsample = float(args.downsample)
    else:
        mpp = DEFAULT_MPP if args.mpp is None else float(args.mpp)
        downsample = None

    if args.whole:
        background_label = None
        background_margin = 0.0
        max_background_tiles = None
    elif args.no_background:
        background_label = None
        background_margin = 0.0
        max_background_tiles = None
    else:
        background_label = args.background_label or DEFAULT_BACKGROUND_LABEL
        background_margin = float(
            DEFAULT_BACKGROUND_MARGIN if args.background_margin is None
            else args.background_margin
        )
        max_background_tiles = (
            DEFAULT_MAX_BACKGROUND_TILES if args.max_background_tiles is None
            else args.max_background_tiles
        )

    exclude_text = (
        list(DEFAULT_EXCLUDE_TEXT) if args.exclude_text is None else list(args.exclude_text)
    )

    return TileParams(
        mode="whole" if args.whole else "roi",
        include_all=bool(args.all),
        text_filter=list(args.text_filter),
        mpp=mpp,
        downsample=downsample,
        size=args.size,
        overlap=args.overlap,
        min_coverage=args.min_coverage,
        tissue_thresh=args.tissue_thresh,
        fmt=args.format or "png",
        coords_only=bool(args.coords_only),
        labels=args.labels,
        exclude_text=exclude_text,
        background_label=background_label,
        background_margin_um=background_margin,
        max_background_tiles=max_background_tiles,
        max_tiles=args.max_tiles,
        max_tiles_per_label=args.max_tiles_per_label,
        seed=args.seed,
    )


def run(args: argparse.Namespace) -> None:
    _validate_args(args)
    target = parse_target(args.target)
    if target == "batch":
        _run_batch(args)
    else:
        _run_single(args, target)


def _tile_one(conn, image, args: argparse.Namespace, params):
    from lavlab.tiling import tile_slide

    return tile_slide(
        conn, image, params, args.out,
        override=args.override,
        skip_existing=args.skip_existing,
        force_local=args.force_local,
    )


def _run_single(args: argparse.Namespace, image_id: int) -> None:
    from lavlab.tiling import TilingError

    params = _build_params(args)
    conn = connect_from_args(args)
    try:
        image = conn.getObject("Image", image_id)
        if image is None:
            raise SystemExit(f"error: image {image_id} not found.")
        group_of(conn, image)

        try:
            result = _tile_one(conn, image, args, params)
        except TilingError as exc:
            raise SystemExit(f"error: image {image_id}: {exc}")

        if result.status == "skipped":
            print(f"Image {image_id}: skipped ({result.reason}).")
        elif result.status == "unannotated":
            print(f"Image {image_id}: no ROIs, nothing tiled.")
        else:
            counts = ", ".join(f"{k}={v}" for k, v in sorted(result.label_counts.items()))
            print(
                f"Completed tile for image {image_id}: {result.slide_dir} "
                f"({counts or 'no tiles'}, tier {result.tier})"
            )
    finally:
        conn.close()


_WORKER_STATE: dict = {}


def _init_worker(args: argparse.Namespace, params) -> None:
    global _WORKER_STATE
    _WORKER_STATE = {
        "conn": connect_from_args(args),
        "args": args,
        "params": params,
    }


def _process_one(image_id: int):
    from lavlab.omero_client import is_conn_error
    from lavlab.tiling import SlideResult, TilingError

    args = _WORKER_STATE["args"]
    params = _WORKER_STATE["params"]
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
                return SlideResult(image_id, "failed", reason="not found")
            group_of(conn, image)
            return _tile_one(conn, image, args, params)
        except TilingError as exc:
            log.warning("Image %d: %s", image_id, exc)
            return SlideResult(image_id, "failed", reason=str(exc))
        except Exception as exc:
            if is_conn_error(exc) and attempt < max_attempts:
                log.warning("Image %d: connection error, retrying: %s", image_id, exc)
                _WORKER_STATE["conn"] = connect_from_args(args)
                continue
            log.exception("Image %d: unhandled error.", image_id)
            return SlideResult(image_id, "failed", reason=type(exc).__name__)
    return SlideResult(image_id, "failed", reason="retries exhausted")


def _format_ids(results, status: str) -> str:
    return ", ".join(str(r.image_id) for r in results if r.status == status)


def _summarise_batch(image_ids, results) -> None:
    """Report what the batch achieved, and fail the run if it achieved nothing.

    Split out from ``_run_batch`` so the reporting and exit-code rules can be
    exercised without standing up a worker pool and an OMERO connection.

    *results* holds one :class:`lavlab.tiling.SlideResult` per image. The
    per-label totals matter as much as the per-slide ones: a run that
    "succeeded" on every slide while producing no G5 tiles at all is a
    broken run, and only the label line shows it.
    """
    by_status = Counter(r.status for r in results)
    done = by_status.get("done", 0)
    skipped = by_status.get("skipped", 0)
    unannotated = by_status.get("unannotated", 0)
    failed = by_status.get("failed", 0)

    log.info(
        "Batch complete: %d/%d slides tiled, %d skipped, %d unannotated, %d failed.",
        done, len(image_ids), skipped, unannotated, failed,
    )

    tiers = Counter(r.tier for r in results if r.status == "done" and r.tier)
    if tiers:
        log.info("Served by tier: %s",
                 ", ".join(f"{tier}={count}" for tier, count in sorted(tiers.items())))

    labels: Counter = Counter()
    for result in results:
        labels.update(result.label_counts)
    if labels:
        log.info("Tiles by label: %s",
                 ", ".join(f"{label}={count}" for label, count in sorted(labels.items())))
        log.info("Total tiles: %d", sum(labels.values()))

    for status, heading in (
        ("skipped", "Skipped"),
        ("unannotated", "Unannotated (no ROIs)"),
        ("failed", "Failed"),
    ):
        ids = _format_ids(results, status)
        if ids:
            log.info("%s image IDs: %s", heading, ids)

    if image_ids and failed == len(image_ids):
        raise SystemExit(
            f"error: all {len(image_ids)} images failed; see the per-image errors above."
        )


def _run_batch(args: argparse.Namespace) -> None:
    from lavlab.omero_client import iter_image_ids

    params = _build_params(args)
    log.info("Starting %d workers.", args.workers)
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(args.workers, initializer=_init_worker, initargs=(args, params)) as pool:
        conn = connect_from_args(args)
        try:
            image_ids = list(iter_image_ids(conn, args.group))
        finally:
            conn.close()

        log.info("Found %d images.", len(image_ids))
        results = list(pool.imap_unordered(_process_one, image_ids))

    _summarise_batch(image_ids, results)
