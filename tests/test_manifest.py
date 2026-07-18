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


def test_allowed_methods_default_and_override():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "manifest.json", {"width": 1, "height": 1})
        assert Manifest(path).allowed_methods is None          # default: no gate
        path2 = _write(d, "m2.json", {"width": 1, "height": 1, "allowed_methods": ["hello"]})
        assert Manifest(path2).allowed_methods == ["hello"]


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


def test_bad_enum_rejected():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "manifest.json", {"width": 1, "height": 1, "origin": "ftp"})
        try:
            Manifest(path)
        except ValueError as e:
            assert "origin" in str(e)
        else:
            raise AssertionError("expected ValueError for bad origin enum")


def test_bad_type_rejected():
    with tempfile.TemporaryDirectory() as d:
        # width must be an int; a string is rejected. bool for a bool field is fine.
        path = _write(d, "manifest.json", {"width": "big", "height": 1})
        try:
            Manifest(path)
        except ValueError as e:
            assert "width" in str(e)
        else:
            raise AssertionError("expected ValueError for wrong width type")


def test_bad_allowed_methods_rejected():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "m.json", {"width": 1, "height": 1, "allowed_methods": "hi"})
        try:
            Manifest(path)
        except ValueError as e:
            assert "allowed_methods" in str(e)
        else:
            raise AssertionError("expected ValueError for non-list allowed_methods")


def test_unknown_keys_pass_through():
    # Real widgets carry extras (e.g. handle_enabled) not in the pattern.
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "manifest.json", {"width": 1, "height": 1, "handle_enabled": False})
        m = Manifest(path)
        assert m.handle_enabled is False


def test_shipped_manifests_are_valid():
    # Every manifest in the repo must pass validation.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for base in ("apps", "system"):
        for dirpath, _dirs, files in os.walk(os.path.join(root, base)):
            if "manifest.json" in files:
                Manifest(os.path.join(dirpath, "manifest.json"))  # raises if invalid


if __name__ == "__main__":
    test_defaults_and_overrides()
    test_allowed_methods_default_and_override()
    test_missing_mandatory_raises()
    test_set_updates_attr_and_dict()
    test_no_shared_mandatory_between_instances()
    test_bad_enum_rejected()
    test_bad_type_rejected()
    test_bad_allowed_methods_rejected()
    test_unknown_keys_pass_through()
    test_shipped_manifests_are_valid()
    print("ok")
