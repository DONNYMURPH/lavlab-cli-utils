"""ROI shape gathering and rasterization into either an RGB color mask or a
single-channel palette (label) mask.

Rasterization uses scikit-image instead of OpenCV per project conventions.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from omero_model_EllipseI import EllipseI
from omero_model_PolygonI import PolygonI
from omero_model_RectangleI import RectangleI
from skimage import draw

log = logging.getLogger(__name__)


def uint_to_rgba(uint: int) -> tuple[int, int, int, int]:
    """Convert OMERO's packed signed-32-bit RGBA color integer to (r, g, b, a)."""
    if uint < 0:
        uint = uint + 2**32

    red = (uint >> 24) & 0xFF
    green = (uint >> 16) & 0xFF
    blue = (uint >> 8) & 0xFF
    alpha = uint & 0xFF

    return red, green, blue, alpha


def get_rois(img, roi_service=None):
    """Gather OMERO RoiI objects for an image."""
    close_roi = roi_service is None
    if roi_service is None:
        roi_service = img._conn.getRoiService()

    rois = roi_service.findByImage(img.getId(), None, img._conn.SERVICE_OPTS).rois

    if close_roi:
        roi_service.close()

    return rois


def get_shapes_as_points(
    img,
    point_downsample: int = 4,
    img_downsample: int = 1,
    roi_service=None,
    include_all: bool = False,
    text_filter: Optional[list[str]] = None,
) -> Optional[list[tuple[int, tuple[int, int, int], Optional[str], list[tuple[float, float]]]]]:
    """Gather Rectangles, Polygons, and Ellipses as shape id, RGB color, matched
    text label (lowercased, or None), and a list of (x, y) boundary points.

    Selection rules:
      - include_all=True: every shape is included.
      - otherwise a shape is only included if its textValue (lowercased)
        is present in text_filter.
    """
    text_filter = text_filter or []

    size_x = img.getSizeX() / img_downsample
    size_y = img.getSizeY() / img_downsample
    yx_shape = (size_y, size_x)

    shapes = []
    for roi in get_rois(img, roi_service):
        for shape in roi.copyShapes():
            text_value = shape.getTextValue()
            text_label = text_value.getValue().lower() if text_value is not None else None

            if not include_all:
                if text_label is None or text_label not in text_filter:
                    continue

            points = None

            if type(shape) == RectangleI:
                x = float(shape.getX().getValue()) / img_downsample
                y = float(shape.getY().getValue()) / img_downsample
                w = float(shape.getWidth().getValue()) / img_downsample
                h = float(shape.getHeight().getValue()) / img_downsample
                points = draw.rectangle_perimeter((y, x), (y + h, x + w), shape=yx_shape)
                points = [(points[1][i], points[0][i]) for i in range(len(points[0]))]

            elif type(shape) == EllipseI:
                points = draw.ellipse_perimeter(
                    float(shape._y._val / img_downsample),
                    float(shape._x._val / img_downsample),
                    float(shape._radiusY._val / img_downsample),
                    float(shape._radiusX._val / img_downsample),
                    shape=yx_shape,
                )
                points = [(points[1][i], points[0][i]) for i in range(len(points[0]))]

            elif type(shape) == PolygonI:
                point_str_arr = shape.getPoints()._val.split(" ")
                xy = []
                for coord_str in point_str_arr:
                    coord_list = coord_str.split(",")
                    xy.append(
                        (float(coord_list[0]) / img_downsample, float(coord_list[1]) / img_downsample)
                    )
                if xy:
                    points = xy

            if points is not None:
                color_val = shape.getStrokeColor()._val
                rgb = uint_to_rgba(color_val)[:-1]  # ignore alpha
                points = points[::point_downsample]
                shapes.append((shape.getId()._val, rgb, text_label, points))

    if not shapes:
        return None

    return sorted(shapes)


def _fill_polygon(mask: np.ndarray, points_xy: list[tuple[float, float]], value) -> None:
    if len(points_xy) < 3:
        return
    xs = np.array([p[0] for p in points_xy])
    ys = np.array([p[1] for p in points_xy])
    rr, cc = draw.polygon(ys, xs, shape=mask.shape[:2])
    mask[rr, cc] = value


def get_roi_mask(
    image,
    downsample: int,
    include_all: bool,
    text_filter: list[str],
    palette: bool = False,
    point_downsample: int = 4,
) -> np.ndarray:
    """Render ROI shapes into an image mask.

    Returns an (H, W, C) RGB mask by default, or an (H, W) single-channel
    label mask (background 0, shapes numbered 1..N in text_filter order) when
    palette=True.
    """
    height = int(image.getSizeY() / downsample)
    width = int(image.getSizeX() / downsample)

    if palette:
        mask = np.zeros((height, width), dtype=np.uint8)
    else:
        mask = np.zeros((height, width, image.getSizeC()), dtype=np.uint8)
        mask[:] = 255

    shapes = get_shapes_as_points(
        image,
        point_downsample=point_downsample,
        img_downsample=downsample,
        include_all=include_all,
        text_filter=text_filter,
    )
    if shapes is None:
        return np.array([])

    for _shape_id, rgb, text_label, points in shapes:
        if palette:
            if text_label not in text_filter:
                continue
            _fill_polygon(mask, points, text_filter.index(text_label) + 1)
        else:
            _fill_polygon(mask, points, rgb)

    return mask
