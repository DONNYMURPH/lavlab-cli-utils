"""Tests for lavlab.geojson.geojson_io -- pure-Python, no OMERO required."""

import json

import pytest

from lavlab.geojson.geojson_io import (
    Annotation,
    ConversionError,
    ShapeSpec,
    annotation_to_feature,
    feature_to_annotation,
    load_features,
    shapes_to_geometry,
)

SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
HOLE = [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]


def _polygon_feature(coordinates, feature_id="abc", classification=None):
    properties = {}
    if classification:
        properties["classification"] = classification
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Polygon", "coordinates": coordinates},
        "properties": properties,
    }


def test_feature_to_annotation_simple_polygon():
    feature = _polygon_feature([SQUARE], classification={"name": "tumor", "color": [255, 0, 0]})
    warnings = []
    annotation = feature_to_annotation(feature, warnings)

    assert annotation is not None
    assert annotation.label == "tumor"
    assert annotation.color == (255, 0, 0)
    assert len(annotation.shapes) == 1
    assert not warnings


def test_feature_to_annotation_bridges_hole_and_warns():
    feature = _polygon_feature([SQUARE, HOLE])
    warnings = []
    annotation = feature_to_annotation(feature, warnings)

    assert annotation is not None
    assert any("bridged" in w for w in warnings)


def test_feature_to_annotation_unsupported_geometry_warns_and_skips():
    feature = {
        "type": "Feature", "id": "x",
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        "properties": {},
    }
    warnings = []
    annotation = feature_to_annotation(feature, warnings)

    assert annotation is None
    assert any("unsupported geometry" in w for w in warnings)


def test_round_trip_feature_annotation_feature():
    original = _polygon_feature([SQUARE, HOLE], classification={"name": "tumor", "color": [1, 2, 3]})
    warnings = []
    annotation = feature_to_annotation(original, warnings)

    rebuilt = annotation_to_feature(annotation, fallback_id="fallback")
    assert rebuilt["geometry"]["type"] == "Polygon"
    # bridged-then-unbridged should recover an outer ring and one hole
    assert len(rebuilt["geometry"]["coordinates"]) == 2
    assert rebuilt["properties"]["classification"]["name"] == "tumor"


def test_shapes_to_geometry_mixed_kinds_returns_none():
    shapes = [
        ShapeSpec("polygon", SQUARE),
        ShapeSpec("point", [[1, 1]]),
    ]
    assert shapes_to_geometry(shapes) is None


def test_load_features_malformed_json_raises_conversion_error(tmp_path):
    bad_file = tmp_path / "bad.geojson"
    bad_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ConversionError):
        load_features(bad_file)


def test_load_features_wrong_top_level_type_raises(tmp_path):
    path = tmp_path / "wrong.geojson"
    path.write_text(json.dumps({"type": "Point", "coordinates": [0, 0]}), encoding="utf-8")

    with pytest.raises(ConversionError):
        load_features(path)


def test_load_features_accepts_feature_collection(tmp_path):
    path = tmp_path / "fc.geojson"
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [_polygon_feature([SQUARE])]}),
        encoding="utf-8",
    )
    features = load_features(path)
    assert len(features) == 1
