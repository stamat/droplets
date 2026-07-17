"""Headless tests for Manifest (no GTK required)."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets.manifest import Manifest  # noqa: E402


def _write(dir_, name, obj):
    path = os.path.join(dir_, name)
    with open(path, "w") as f:
        json.dump(obj, f)
    return path


def test_defaults_and_overrides():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "manifest.json", {"width": 640, "height": 480, "title": "hi"})
        m = Manifest(path)
        assert m.width == 640            # overridden
        assert m.height == 480           # overridden (mandatory)
        assert m.title == "hi"
        assert m.origin == "local"       # default from pattern


def test_missing_mandatory_raises():
    with tempfile.TemporaryDirectory() as d:
        # width & height are mandatory in manifest_pattern; omit them.
        path = _write(d, "manifest.json", {"title": "no size"})
        try:
            Manifest(path)
        except ValueError as e:
            assert "width" in str(e) and "height" in str(e)
        else:
            raise AssertionError("expected ValueError for missing mandatory fields")


def test_set_updates_attr_and_dict():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "manifest.json", {"width": 100, "height": 100})
        m = Manifest(path)
        m.set("x", 42)
        assert m.x == 42 and m.dict["x"] == 42


def test_no_shared_mandatory_between_instances():
    # Regression: mandatory used to be a class attr mutated in place.
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "manifest.json", {"width": 1, "height": 1})
        Manifest(path)
        m2 = Manifest(path)
        assert "width" in m2.mandatory and "height" in m2.mandatory


if __name__ == "__main__":
    test_defaults_and_overrides()
    test_missing_mandatory_raises()
    test_set_updates_attr_and_dict()
    test_no_shared_mandatory_between_instances()
    print("ok")
