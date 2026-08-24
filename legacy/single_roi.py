import os
import sys
import time
import random
import re
import logging
import argparse

import numpy as np
import pyvips as pv
import cv2
from skimage import draw

import omero.sys
from omero.gateway import BlitzGateway
from omero_model_PolygonI import PolygonI
from omero_model_EllipseI import EllipseI
from omero_model_RectangleI import RectangleI


# ── Configuration ──────────────────────────────────────────────────────────────
OMERO_HOST = "wss://wsi.lavlab.mcw.edu/omero-wss"
OMERO_PORT = 443

# Default values
BASE_PATH = "/Volumes/Siren/Prostate_data/"

# Scale to downsample image for ROI mask generation.
DOWNSAMPLE = 10

# If True, treat new-style shape annotations (no text filtering) as included.
NEW_ANNOTS = True

# Text appended to the ROI mask annotation. Default: "_annot"
SUFFIX = "_annot"

# List of text annotations to include. If empty, or --all is added, all are included.
TEXT_FILTER = []

# Namespace tag applied to the file annotation so it can be found later
FILE_ANN_NS = "LargeRecon.10.roi"

NAME_RE = re.compile(r"N(\d+)_S(\d+)(_Deeper\d*)?_(\w+)\.ome\.tiff")


# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _connect(username: str, password: str) -> BlitzGateway:
    retries = 5
    base_delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            conn = BlitzGateway(
                username, password,
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


def uint_to_rgba(uint: int) -> int:
    """
    Return the color as an Integer in RGBA encoding.

    Parameters
    ----------
    int
        Integer encoding rgba value.

    Returns
    -------
    red: int
        Red color val (0-255)
    green: int
        Green color val (0-255)
    blue: int
        Blue color val (0-255)
    alpha: int
        Alpha opacity val (0-255)"""
    if uint < 0:  # convert from signed 32-bit int
        uint = uint + 2**32

    red = (uint >> 24) & 0xFF
    green = (uint >> 16) & 0xFF
    blue = (uint >> 8) & 0xFF
    alpha = uint & 0xFF

    return red, green, blue, alpha


def _resolve_paths(image_id: int, name: str, base_path: str) -> tuple[str, str] | None:
    """Return (jp2_path, omero_id_path) for an image name, or None if unparseable."""
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

    import glob
    subject_dirs = glob.glob(f"{base_path}*{subject}")
    if not subject_dirs:
        log.warning("Image %d: no directory found for subject %s, skipping.", image_id, subject)
        return None

    subject_dir = subject_dirs[0]

    # Slide folder incorporates optional _Deeper[N] suffix (e.g. "1" or "1_Deeper[2]")
    slide_folder = slide + deeper

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


def get_rois(img, roi_service=None):
    """
    Gathers OMERO RoiI objects.

    Parameters
    ----------
    img: omero.gateway.ImageWrapper
        Omero Image object from conn.getObjects()
    roi_service: omero.RoiService, optional
        Allows roiservice passthrough for performance
    """
    if roi_service is None:
        roi_service = img._conn.getRoiService()
        close_roi = True
    else:
        close_roi = False

    rois = roi_service.findByImage(img.getId(), None, img._conn.SERVICE_OPTS).rois

    if close_roi:
        roi_service.close()

    return rois


def get_shapes_as_points(
    img, point_downsample=4, img_downsample=1, roi_service=None, new_annots=False, text_filter=[]
) -> list[tuple[int, tuple[int, int, int], list[tuple[float, float]]]]:
    """
    Gathers Rectangles, Polygons, and Ellipses as a tuple containing the shapeId, its rgb val, and a tuple of yx points of its bounds.

    Parameters
    ----------
    img: omero.gateway.ImageWrapper
        Omero Image object from conn.getObjects().
    point_downsample: int, Default: 4
        Grabs every nth point for faster computation.
    img_downsample: int, Default: 1
        How much to scale roi points.
    roi_service: omero.RoiService, optional
        Allows roiservice passthrough for performance.

    Returns
    -------
    returns: list[ shape.id, (r,g,b), list[tuple(x,y)] ]
        list of tuples containing a shape's id, rgb value, and a tuple of row and column points
    """

    sizeX = img.getSizeX() / img_downsample
    sizeY = img.getSizeY() / img_downsample
    yx_shape = (sizeY, sizeX)

    shapes = []
    for roi in get_rois(img, roi_service):

        points = None

        for shape in roi.copyShapes():
            if shape.getTextValue() is not None and text_filter != []:
                if (shape.getTextValue().getValue().lower() not in text_filter):
                    continue

            elif new_annots is False:
                continue
            if type(shape) == RectangleI:
                x = float(shape.getX().getValue()) / img_downsample
                y = float(shape.getY().getValue()) / img_downsample
                w = float(shape.getWidth().getValue()) / img_downsample
                h = float(shape.getHeight().getValue()) / img_downsample
                points = draw.rectangle_perimeter(
                    (y, x), (y + h, x + w), shape=yx_shape
                )
                points = [
                    (points[1][i], points[0][i]) for i in range(0, len(points[0]))
                ]

            if type(shape) == EllipseI:
                points = draw.ellipse_perimeter(
                    float(shape._y._val / img_downsample),
                    float(shape._x._val / img_downsample),
                    float(shape._radiusY._val / img_downsample),
                    float(shape._radiusX._val / img_downsample),
                    shape=yx_shape,
                )
                points = [
                    (points[1][i], points[0][i]) for i in range(0, len(points[0]))
                ]

            if type(shape) == PolygonI:
                pointStrArr = shape.getPoints()._val.split(" ")

                xy = []
                for i in range(0, len(pointStrArr)):
                    coordList = pointStrArr[i].split(",")
                    xy.append(
                        (
                            float(coordList[0]) / img_downsample,
                            float(coordList[1]) / img_downsample,
                        )
                    )
                if xy:
                    points = xy

            if points is not None:
                color_val = shape.getStrokeColor()._val
                rgb = uint_to_rgba(color_val)[:-1]  # ignore alpha value for computation
                points = points[::point_downsample]

                shapes.append((shape.getId()._val, rgb, points))

    if not shapes:  # if no shapes in shapes return none
        return None

    # make sure is in correct order
    return sorted(shapes)


def get_roi_mask(image, downsample: int, new_annots: bool, text_filter: list) -> np.array:
    rgb_mask = np.zeros(
        (
            int(image.getSizeY() / downsample),
            int(image.getSizeX() / downsample),
            image.getSizeC(),
        ),
        dtype=np.uint8,
    )
    rgb_mask[:] = 255
    points = get_shapes_as_points(image, img_downsample=downsample,
                                  new_annots=new_annots, text_filter=text_filter)
    if points == None:
        return np.array([])
    for id, rgb, xy in points:
        yx = np.array(xy, np.int32)  # Ensure the points are of integer type
        yx = yx.reshape((-1, 1, 2))  # Reshape to (-1, 1, 2)
        cv2.fillPoly(rgb_mask, [yx], color=rgb)
    return rgb_mask


def link_file_annot(conn: BlitzGateway, image, path: str, image_id: int) -> None:
    for ann in image.listAnnotations(ns=FILE_ANN_NS):
        if hasattr(ann, "getFile"):
            orig_file = ann.getFile()
            if orig_file.getName() == os.path.basename(path):
                log.info("Existing ROI annotation for image %d", image_id)
                return

    file_ann = conn.createFileAnnfromLocalFile(
        path,
        mimetype="image/jp2",
        ns=FILE_ANN_NS,
    )
    image.linkAnnotation(file_ann)
    log.info("Image %d: uploaded ROI annotation to OMERO.", image_id)


def create_roi_image(
    conn: BlitzGateway,
    image_id: int,
    suffix: str = SUFFIX,
    text_filter: list = TEXT_FILTER,
    base_path: str = BASE_PATH,
    overwrite: bool = False,
    downsample: int = DOWNSAMPLE,
    new_annots: bool = NEW_ANNOTS,
) -> tuple[int, str] | None:
    image = conn.getObject("Image", image_id)
    if image is None:
        log.warning("Image %d not found in OMERO, skipping.", image_id)
        return None
    conn.c.sf.setSecurityContext(image.details.group)

    name = image.getName()
    paths = _resolve_paths(image_id, name, base_path)
    if paths is None:
        return None

    jp2_path, omero_id_path = paths
    roi_path = jp2_path.replace(".jp2", f"{suffix}.jp2")

    already_local = os.path.exists(roi_path) and os.path.exists(omero_id_path)
    if already_local and not overwrite:
        # Sidecar is written after upload, so its presence guarantees completion.
        log.info("ROI for image %d already created and uploaded, skipping.", image_id)
        link_file_annot(conn, image, roi_path, image_id)
        return (image_id, roi_path)

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

    os.makedirs(os.path.dirname(roi_path), exist_ok=True)

    # Create ROI mask and save to roi_path.
    roi_mask = get_roi_mask(image, downsample, new_annots, text_filter)
    if roi_mask.size == 0:
        log.info("Image %d: No ROIs under filters %s", image_id, text_filter)
        return None
    roi_img = pv.Image.new_from_array(roi_mask)
    del roi_mask  # new_from_array copies the buffer; release the numpy allocation now
    roi_img.write_to_file(roi_path)
    log.info("Image %d: saved ROI → %s", image_id, roi_path)

    link_file_annot(conn, image, roi_path, image_id)

    log.info("Completed ROI for image %d: %s", image_id, roi_path)
    return (image_id, roi_path)


# ── Entry point ────────────────────────────────────────────────────────────────
def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single-image ROI mask generation and upload to OMERO.")
    parser.add_argument(
        "-u", "--username",
        type=str,
        required=True,
        help="OMERO username."
    )
    parser.add_argument(
        "-p", "--password",
        type=str,
        required=True,
        help="OMERO password."
    )
    parser.add_argument(
        "image_id",
        type=int,
        help="OMERO image ID to process."
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Get all annotations regardless of text value."
    )
    parser.add_argument(
        "-s", "--suffix",
        type=str,
        default=SUFFIX,
        help=f"Change the text appended to the ROI mask annotation (default: '{SUFFIX}')."
    )
    parser.add_argument(
        "-t", "--text_filter",
        type=str.lower,
        action="append",
        default=[],
        help="List of text annotations to include, e.g. --text 'Transferred Annotation' --text 'mask_use'."
    )
    parser.add_argument(
        "-b", "--base-path",
        type=str,
        default=BASE_PATH,
        help="Base path for output directories."
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing ROI masks and annotations (default: False)."
    )
    parser.add_argument(
        "-d", "--downsample",
        type=int,
        default=DOWNSAMPLE,
        help="Downsample factor for ROI mask generation."
    )
    parser.add_argument(
        "-n", "--new-annots",
        action="store_true",
        default=NEW_ANNOTS,
        help=f"Use new annotations (default: {NEW_ANNOTS})."
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])

    text_filter = [] if args.all else args.text_filter

    conn = _connect(args.username, args.password)
    conn.SERVICE_OPTS.setOmeroGroup(-1)
    try:
        result = create_roi_image(
            conn,
            args.image_id,
            suffix=args.suffix,
            text_filter=text_filter,
            base_path=args.base_path,
            overwrite=args.overwrite,
            downsample=args.downsample,
            new_annots=args.new_annots,
        )
        if result is None:
            log.error("Failed to produce ROI for image %d.", args.image_id)
            sys.exit(1)
        image_id, roi_path = result
        print(f"Completed ROI for image {image_id}: {roi_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
