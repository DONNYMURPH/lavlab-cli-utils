"""``lavlab meta roi textvalue`` -- fill in blank ROI shape comments by
matching each shape's stroke color against a palette."""

from __future__ import annotations

import argparse
import logging

from omero.rtypes import rstring

from lavlab.commands._shared import add_creds_args, connect_from_args, group_of
from lavlab.omero_client import iter_image_ids
from lavlab.palettes import load_color_mapping, match_color
from lavlab.roi import get_rois, uint_to_rgba

log = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 10


def add_parser(subparsers) -> None:
    meta_parser = subparsers.add_parser("meta", help="Metadata utilities.")
    meta_subparsers = meta_parser.add_subparsers(dest="meta_resource", required=True)

    roi_parser = meta_subparsers.add_parser("roi", help="ROI metadata utilities.")
    roi_subparsers = roi_parser.add_subparsers(dest="meta_roi_action", required=True)

    textvalue_parser = roi_subparsers.add_parser(
        "textvalue",
        help="Fill blank ROI shape comments from a stroke-color palette.",
    )
    textvalue_parser.add_argument(
        "text_mapping",
        help="A built-in palette name (e.g. 'default') or a path to a YAML/JSON palette file.",
    )
    textvalue_parser.add_argument(
        "image_ids", nargs="*", type=int,
        help="OMERO image IDs to process. Omit and use --group to process a whole group.",
    )
    textvalue_parser.add_argument("-g", "--group", type=int, help="Process every image in this OMERO group.")
    textvalue_parser.add_argument(
        "--tolerance", type=int, default=DEFAULT_TOLERANCE,
        help=f"Per-channel color match tolerance (default: {DEFAULT_TOLERANCE}).",
    )
    add_creds_args(textvalue_parser)
    textvalue_parser.set_defaults(handler=run)


def _shape_has_comment(shape) -> bool:
    tv = shape.getTextValue()
    if tv is None:
        return False
    return bool(tv.getValue().strip())


def _shape_color(shape):
    stroke = shape.getStrokeColor()
    if stroke is None:
        return None
    r, g, b, _a = uint_to_rgba(stroke.getValue())
    return r, g, b


def _process_image(conn, image_id: int, mapping, tolerance: int) -> tuple[int, int, int]:
    image = conn.getObject("Image", image_id)
    if image is None:
        log.warning("Image %d not found, skipping.", image_id)
        return (0, 0, 0)
    group_of(conn, image)

    updated = skipped_has_comment = skipped_no_match = 0
    for roi in get_rois(image):
        for shape in roi.copyShapes():
            if _shape_has_comment(shape):
                skipped_has_comment += 1
                continue

            rgb = _shape_color(shape)
            if rgb is None:
                skipped_no_match += 1
                continue

            label = match_color(rgb, mapping, tolerance)
            if label is None:
                skipped_no_match += 1
                continue

            shape.setTextValue(rstring(label))
            conn.getUpdateService().saveObject(shape)
            updated += 1

    return (updated, skipped_has_comment, skipped_no_match)


def run(args: argparse.Namespace) -> None:
    try:
        mapping = load_color_mapping(args.text_mapping)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")

    if args.image_ids:
        image_ids = args.image_ids
    elif args.group is not None:
        pass  # resolved below, after connecting
    else:
        raise SystemExit("error: specify one or more image IDs, or --group.")

    conn = connect_from_args(args)
    try:
        if not args.image_ids:
            image_ids = list(iter_image_ids(conn, args.group))

        total_updated = total_skip_comment = total_skip_no_match = 0
        for image_id in image_ids:
            updated, skip_comment, skip_no_match = _process_image(conn, image_id, mapping, args.tolerance)
            total_updated += updated
            total_skip_comment += skip_comment
            total_skip_no_match += skip_no_match
            print(f"Image {image_id}: updated={updated} had_comment={skip_comment} no_match={skip_no_match}")

        print(
            f"Done: {len(image_ids)} images, {total_updated} shapes updated, "
            f"{total_skip_comment} already commented, {total_skip_no_match} unmatched."
        )
    finally:
        conn.close()
