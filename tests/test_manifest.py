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


def test_settings_overlay_overrides_manifest():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "manifest.json", {"width": 300, "height": 300})
        _write(d, "settings.json", {"x": 10, "y": 20, "width": 640})
        m = Manifest(os.path.join(d, "manifest.json"))
        assert m.x == 10 and m.y == 20   # runtime state applied
        assert m.width == 640            # settings override authored default
        assert m.height == 300           # untouched by settings


def test_save_setting_writes_only_settings_file():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "manifest.json", {"width": 300, "height": 300})
        m = Manifest(os.path.join(d, "manifest.json"))
        m.save_setting(x=5, y=6)
        assert m.x == 5 and m.settings["x"] == 5
        with open(os.path.join(d, "settings.json")) as f:
            assert json.load(f) == {"x": 5, "y": 6}
        # authored manifest is never rewritten
        with open(os.path.join(d, "manifest.json")) as f:
            assert "x" not in json.load(f)


def test_bad_settings_rejected():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "manifest.json", {"width": 1, "height": 1})
        _write(d, "settings.json", {"origin": "remote"})  # not a settings key
        try:
            Manifest(os.path.join(d, "manifest.json"))
        except ValueError as e:
            assert "origin" in str(e)
        else:
            raise AssertionError("expected ValueError for unknown setting key")


def test_save_layout_writes_per_layout_and_top_level():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "manifest.json", {"width": 300, "height": 300})
        m = Manifest(os.path.join(d, "manifest.json"))
        m.save_layout("1512x982+0+0", x=5, y=6)
        m.save_layout("1512x982+0+0|2560x1440-2560+0", x=-1393, y=75)
        with open(os.path.join(d, "settings.json")) as f:
            saved = json.load(f)
        assert saved["layouts"] == {
            "1512x982+0+0": {"x": 5, "y": 6},
            "1512x982+0+0|2560x1440-2560+0": {"x": -1393, "y": 75},
        }
        # top level mirrors the last write, so a pre-layouts reader still restores
        assert (saved["x"], saved["y"]) == (-1393, 75)
        assert m.layout("1512x982+0+0") == {"x": 5, "y": 6}
        assert m.layout("nonexistent") == {}


def test_bad_layouts_rejected():
    bad = [
        {"layouts": []},
        {"layouts": {"1512x982+0+0": 5}},
        {"layouts": {"1512x982+0+0": {"opacity": 1}}},
        {"layouts": {"1512x982+0+0": {"x": "5"}}},
    ]
    for settings in bad:
        with tempfile.TemporaryDirectory() as d:
            _write(d, "manifest.json", {"width": 1, "height": 1})
            _write(d, "settings.json", settings)
            try:
                Manifest(os.path.join(d, "manifest.json"))
            except ValueError as e:
                assert "layout" in str(e)
            else:
                raise AssertionError("expected ValueError for %r" % settings)


def test_options_default_applied_and_overridden():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "manifest.json", {
            "width": 1, "height": 1,
            "options": {
                "city": {"type": "string", "default": "Belgrade"},
                "refresh": {"type": "int", "default": 60, "min": 5},
                "compact": {"type": "bool", "default": False},
            },
        })
        m = Manifest(os.path.join(d, "manifest.json"))
        # An option reads as an attribute whether or not the user ever set it.
        assert (m.city, m.refresh, m.compact) == ("Belgrade", 60, False)
        assert m.option_values() == {"city": "Belgrade", "refresh": 60, "compact": False}

        m.save_options({"city": "Novi Sad", "refresh": 300})
        again = Manifest(os.path.join(d, "manifest.json"))
        assert again.city == "Novi Sad" and again.refresh == 300
        assert again.compact is False          # untouched option keeps its default
        with open(os.path.join(d, "manifest.json")) as f:
            assert "Novi Sad" not in f.read()  # authored manifest never rewritten


def test_geometry_and_manifest_names_rejected_as_options():
    # The blacklist: an option may not claim a geometry key (it would fight the
    # window) or any manifest field (settings.json is user-editable, so an
    # option named `origin`/`allowed_methods` would be a way around the tier).
    for name in ("x", "y", "width", "height", "screen", "layouts", "enabled",
                 "origin", "allowed_methods", "options"):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "manifest.json", {
                "width": 1, "height": 1,
                "options": {name: {"type": "string", "default": "x"}},
            })
            try:
                Manifest(path)
            except ValueError as e:
                assert "reserved" in str(e), (name, str(e))
            else:
                raise AssertionError("option %r was allowed" % name)


def test_bad_option_schema_rejected():
    bad = [
        {"a": {"type": "colour"}},                               # unknown type
        {"a": {"type": "enum"}},                                 # enum without choices
        {"a": {"type": "enum", "choices": []}},                  # empty choices
        {"a": {"type": "enum", "choices": ["x"], "default": "y"}},  # default off-list
        {"a": {"type": "int", "default": "5"}},                  # default wrong type
        {"a": {"type": "int", "min": "5"}},                      # bound not a number
        {"a": "string"},                                         # spec not an object
    ]
    for options in bad:
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "manifest.json", {"width": 1, "height": 1, "options": options})
            try:
                Manifest(path)
            except ValueError as e:
                assert "option 'a'" in str(e), (options, str(e))
            else:
                raise AssertionError("expected ValueError for %r" % options)


def test_bad_option_values_rejected():
    schema = {
        "width_px": {"type": "int", "min": 5, "max": 50},
        "mode": {"type": "enum", "choices": ["a", "b"]},
        "on": {"type": "bool"},
    }
    bad = [
        {"width_px": "20"},   # wrong type
        {"width_px": True},   # a bool is not an int here
        {"width_px": 4},      # below min
        {"width_px": 51},     # above max
        {"mode": "c"},        # off the choice list
        {"on": 1},            # int is not a bool
        {"nope": 1},          # not declared at all
    ]
    for values in bad:
        with tempfile.TemporaryDirectory() as d:
            _write(d, "manifest.json", {"width": 1, "height": 1, "options": schema})
            m = Manifest(os.path.join(d, "manifest.json"))
            try:
                m.save_options(values)
            except ValueError:
                pass
            else:
                raise AssertionError("save_options accepted %r" % values)
            # ... and the same value is rejected when hand-written into settings.
            _write(d, "settings.json", values)
            try:
                Manifest(os.path.join(d, "manifest.json"))
            except ValueError:
                pass
            else:
                raise AssertionError("settings.json accepted %r" % values)


def test_enabled_is_a_setting():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "manifest.json", {"width": 1, "height": 1})
        m = Manifest(os.path.join(d, "manifest.json"))
        assert m.enabled is False           # nothing runs until the user says so
        m.save_setting(enabled=True)
        assert Manifest(os.path.join(d, "manifest.json")).enabled is True


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
    test_settings_overlay_overrides_manifest()
    test_save_setting_writes_only_settings_file()
    test_bad_settings_rejected()
    test_save_layout_writes_per_layout_and_top_level()
    test_bad_layouts_rejected()
    test_options_default_applied_and_overridden()
    test_geometry_and_manifest_names_rejected_as_options()
    test_bad_option_schema_rejected()
    test_bad_option_values_rejected()
    test_enabled_is_a_setting()
    test_shipped_manifests_are_valid()
    print("ok")
