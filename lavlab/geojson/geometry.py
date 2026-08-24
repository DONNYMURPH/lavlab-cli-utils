# SPDX-FileCopyrightText: 2026-present LavLab <domurphy@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""
Geometry helpers shared by the import and export paths.

Nothing here imports ``omero``, so all of it can be exercised without a
server. The two interesting pieces are :func:`bridge_hole` and
:func:`unbridge_ring`, which work around OMERO's polygon model having no
concept of an interior ring.
"""

from __future__ import annotations

import math

#: Fewer points than this cannot describe a polygon.
MIN_RING_POINTS = 3

Point = "list[float]"
Ring = "list[list[float]]"


# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------


def rgb_to_omero_color(r: int, g: int, b: int, alpha: int = 255) -> int:
    """Pack an RGBA colour into the signed 32-bit integer OMERO stores.

    OMERO keeps shape colours in a single ``int`` column rather than separate
    red/green/blue fields, using the top byte for red and the bottom byte for
    alpha. Values above the signed range wrap negative.

    :param r: red channel, 0-255
    :type r: int
    :param g: green channel, 0-255
    :type g: int
    :param b: blue channel, 0-255
    :type b: int
    :param alpha: alpha channel, 0-255
    :type alpha: int
    :return: packed signed 32-bit colour
    :rtype: int
    """
    packed = (int(r) << 24) + (int(g) << 16) + (int(b) << 8) + int(alpha)
    if packed > 2**31 - 1:
        packed -= 2**32
    return packed


def omero_color_to_rgb(packed: int | None) -> tuple[int, int, int] | None:
    """Unpack an OMERO colour integer back to ``(r, g, b)``.

    :param packed: the stored signed 32-bit colour, or ``None``
    :type packed: int | None
    :return: red/green/blue triple, or ``None`` if nothing was stored
    :rtype: tuple[int, int, int] | None
    """
    if packed is None:
        return None
    if packed < 0:
        packed += 2**32
    return ((packed >> 24) & 255, (packed >> 16) & 255, (packed >> 8) & 255)


def qupath_colorrgb_to_rgb(packed: int) -> tuple[int, int, int]:
    """Unpack the packed ARGB integer QuPath 0.3 wrote as ``colorRGB``.

    :param packed: java.awt.Color style ARGB integer, often negative
    :type packed: int
    :return: red/green/blue triple
    :rtype: tuple[int, int, int]
    """
    if packed < 0:
        packed += 2**32
    return ((packed >> 16) & 255, (packed >> 8) & 255, packed & 255)


# --------------------------------------------------------------------------
# points strings
# --------------------------------------------------------------------------


def format_coord(value: float, ndigits: int = 2) -> str:
    """Format a single coordinate for OMERO's ``points`` string.

    Deliberately avoids ``f"{value:g}"``. ``%g`` means six *significant*
    digits, not six decimal places, so a whole-slide coordinate such as
    ``82515.98`` is written as ``82516`` and every vertex shifts by up to
    half a pixel. On a typical slide export that silently affects over 90%
    of coordinates.

    :param value: the coordinate to format
    :type value: float
    :param ndigits: decimal places to keep
    :type ndigits: int
    :return: compact decimal text with no exponent
    :rtype: str
    """
    rounded = round(float(value), ndigits)
    if rounded == int(rounded):
        return str(int(rounded))
    return repr(rounded)


def ring_to_points(ring: list[list[float]], ndigits: int = 2) -> str:
    """Convert ``[[x, y], ...]`` to the ``"x,y x,y"`` string OMERO stores.

    The repeated closing point GeoJSON uses is dropped, since OMERO's polygon
    closes itself.

    :param ring: coordinate pairs
    :type ring: list[list[float]]
    :param ndigits: decimal places to keep per coordinate
    :type ndigits: int
    :return: OMERO ``Shape.points`` text
    :rtype: str
    """
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return " ".join(
        f"{format_coord(x, ndigits)},{format_coord(y, ndigits)}" for x, y in points
    )


def points_to_ring(points: str | None) -> list[list[float]]:
    """Parse an OMERO ``points`` string back into ``[[x, y], ...]``.

    Commas and whitespace are treated alike, because some clients write
    ``"x1,y1, x2,y2"`` with a separator between pairs as well as within them.
    A shape can legitimately be stored with its points unset, so ``None`` and
    unparseable tokens yield an empty list rather than raising.

    :param points: stored points text, or ``None``
    :type points: str | None
    :return: coordinate pairs
    :rtype: list[list[float]]
    """
    if not points:
        return []
    numbers = []
    for token in points.replace(",", " ").split():
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    if len(numbers) % 2:
        numbers = numbers[:-1]
    return [[numbers[i], numbers[i + 1]] for i in range(0, len(numbers), 2)]


def close_ring(ring: list[list[float]]) -> list[list[float]]:
    """Repeat the first point at the end, as GeoJSON requires.

    :param ring: coordinate pairs
    :type ring: list[list[float]]
    :return: the ring with its closing point present
    :rtype: list[list[float]]
    """
    if ring and ring[0] != ring[-1]:
        return [*ring, list(ring[0])]
    return ring


def open_ring(ring: list[list[float]]) -> list[list[float]]:
    """Drop the repeated closing point, as OMERO expects.

    :param ring: coordinate pairs
    :type ring: list[list[float]]
    :return: the ring without its closing point
    :rtype: list[list[float]]
    """
    if len(ring) > 1 and ring[0] == ring[-1]:
        return [list(point) for point in ring[:-1]]
    return [list(point) for point in ring]


def drop_consecutive_duplicates(ring: list[list[float]]) -> list[list[float]]:
    """Remove neighbouring identical points.

    Splicing a hole out of a bridged ring leaves the cut vertex sitting next
    to itself. That is geometrically harmless but would accumulate a little
    more on every export/import cycle, so clearing it keeps repeated archive
    runs byte-stable.

    :param ring: coordinate pairs
    :type ring: list[list[float]]
    :return: the ring with adjacent duplicates collapsed
    :rtype: list[list[float]]
    """
    if not ring:
        return []
    cleaned = [ring[0]]
    for point in ring[1:]:
        if point != cleaned[-1]:
            cleaned.append(point)
    return cleaned


def signed_area(ring: list[list[float]]) -> float:
    """Return twice-the-shoelace area, positive when the ring winds CCW.

    :param ring: coordinate pairs, closing point optional
    :type ring: list[list[float]]
    :return: signed area
    :rtype: float
    """
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return total / 2.0


# --------------------------------------------------------------------------
# holes
# --------------------------------------------------------------------------


def bridge_hole(outer: list[list[float]], hole: list[list[float]]) -> list[list[float]]:
    """Fold a hole into its outer ring as one self-touching ring.

    OMERO's polygon is a flat list of points with no interior rings, so the
    hole is joined to the outline by a zero-width "keyhole" slit: cut from
    the outer ring to the nearest hole vertex, walk the hole, and cut back
    out along the same line. Because the two cut edges coincide, the nonzero
    fill rule used by OMERO.web and iviewer renders the hole as a hole.

    The hole is reversed when needed so it winds against the outline; without
    that the fill rule adds its area instead of subtracting it.

    Bridging between nearest vertices can self-intersect on pathologically
    concave outlines. It behaves for the tissue and tumour boundaries this is
    aimed at, and :func:`unbridge_ring` reverses it exactly.

    :param outer: the outer ring
    :type outer: list[list[float]]
    :param hole: the interior ring to fold in
    :type hole: list[list[float]]
    :return: a single ring, closing point omitted
    :rtype: list[list[float]]
    """
    outer_points = open_ring(outer)
    hole_points = open_ring(hole)

    if (signed_area(hole) >= 0) == (signed_area(outer) >= 0):
        hole_points = hole_points[::-1]

    best_distance = None
    cut_outer = cut_hole = 0
    for i, (outer_x, outer_y) in enumerate(outer_points):
        for j, (hole_x, hole_y) in enumerate(hole_points):
            distance = (outer_x - hole_x) ** 2 + (outer_y - hole_y) ** 2
            if best_distance is None or distance < best_distance:
                best_distance, cut_outer, cut_hole = distance, i, j

    loop = [
        *hole_points[cut_hole:],
        *hole_points[:cut_hole],
        list(hole_points[cut_hole]),
    ]
    return [*outer_points[: cut_outer + 1], *loop, *outer_points[cut_outer:]]


def find_bridge(ring: list[list[float]]) -> tuple[int, int] | None:
    """Locate a keyhole slit in a ring.

    :func:`bridge_hole` produces ``outer[:i+1] + hole_loop + outer[i:]``,
    where the hole loop starts and ends on the same vertex. That leaves two
    signatures at once: a vertex appearing twice, *and* the run between those
    occurrences being itself closed. Requiring both is what stops an ordinary
    repeated vertex being mistaken for a slit.

    :param ring: coordinate pairs, closing point omitted
    :type ring: list[list[float]]
    :return: ``(start, end)`` bounding the spliced hole, or ``None``
    :rtype: tuple[int, int] | None
    """
    seen: dict[tuple[float, float], list[int]] = {}
    for index, point in enumerate(ring):
        seen.setdefault((point[0], point[1]), []).append(index)

    for positions in seen.values():
        if len(positions) < 2:
            continue
        for start in positions:
            for end in positions:
                if end - start < 4:
                    continue
                inner = ring[start + 1 : end]
                if len(inner) >= 4 and inner[0] == inner[-1]:
                    return start, end
    return None


def unbridge_ring(
    ring: list[list[float]],
) -> tuple[list[list[float]], list[list[list[float]]]]:
    """Split a bridged ring back into an outer ring and its holes.

    Repeats until no slit remains, so a shape carrying several bridged holes
    comes apart fully. A ring with no slit is returned unchanged with no
    holes, which is what makes this safe to run over every polygon.

    :param ring: a possibly-bridged ring, closing point omitted
    :type ring: list[list[float]]
    :return: ``(outer ring, [closed hole rings])``
    :rtype: tuple[list[list[float]], list[list[list[float]]]]
    """
    outer = list(ring)
    holes: list[list[list[float]]] = []

    while True:
        found = find_bridge(outer)
        if found is None:
            break
        start, end = found
        hole = outer[start + 1 : end]
        # Reverse the winding back: GeoJSON does not care, but it keeps
        # exports looking like what QuPath itself writes.
        holes.append(close_ring(drop_consecutive_duplicates(hole[::-1])))
        outer = drop_consecutive_duplicates([*outer[: start + 1], *outer[end:]])

    return outer, holes


# --------------------------------------------------------------------------
# shapes OMERO has that GeoJSON does not
# --------------------------------------------------------------------------


def rectangle_to_ring(
    x: float, y: float, width: float, height: float
) -> list[list[float]]:
    """Convert an OMERO rectangle to a four-point ring.

    :param x: left edge
    :type x: float
    :param y: top edge
    :type y: float
    :param width: rectangle width
    :type width: float
    :param height: rectangle height
    :type height: float
    :return: the corner ring, closing point omitted
    :rtype: list[list[float]]
    """
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def ellipse_to_ring(
    cx: float, cy: float, rx: float, ry: float, segments: int = 64
) -> list[list[float]]:
    """Approximate an OMERO ellipse as a polygon ring.

    GeoJSON has no curve primitive, so this is lossy: an ellipse that makes a
    round trip comes back as a polygon and stays one.

    :param cx: centre x
    :type cx: float
    :param cy: centre y
    :type cy: float
    :param rx: x radius
    :type rx: float
    :param ry: y radius
    :type ry: float
    :param segments: number of vertices to generate
    :type segments: int
    :return: the approximating ring, closing point omitted
    :rtype: list[list[float]]
    """
    return [
        [
            round(cx + rx * math.cos(2 * math.pi * i / segments), 2),
            round(cy + ry * math.sin(2 * math.pi * i / segments), 2),
        ]
        for i in range(segments)
    ]
