"""Manifest: load/validate a droplet's manifest.json against manifest_pattern.

manifest_pattern is the single source of truth: it gives every field's default
and whether it's mandatory. Types are inferred from each default (bool/int/str);
the few fields the default can't describe — enums (one member shown) and
allowed_methods (a list) — are pinned explicitly below.
"""

import json
import os
import re

# Pattern lives at the repo root (one level above this package).
_DEFAULT_PATTERN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest_pattern"
)

# Enum-constrained fields. The pattern default shows only one member, so the
# full set lives here. Values outside these are rejected.
_ENUMS = {
    "type": ("widget", "app"),
    "origin": ("local", "remote", "hosted"),
    "shape": ("rect", "roundedrect", "circle", "mask"),
}

# Runtime state a running droplet writes back (window moved/resized, which
# screen it lives on). These live in a sibling settings.json, NOT the authored
# manifest.json, so store updates never clobber the user's placement. Every key
# is also in manifest_pattern, so its type is validated against that default --
# except 'layouts', which is settings-only (see layout()/save_layout()).
# Author-declared options (see 'options' below) are written here too, and are
# the only other keys accepted. (There is deliberately no per-droplet "enabled"
# flag: whether a droplet autostarts is a list the manager owns, never something
# a droplet's own file can assert -- see system/manager/main.py.)
_SETTINGS_KEYS = ("x", "y", "screen", "width", "height", "layouts")

# Geometry keys remembered per display layout inside 'layouts'.
_LAYOUT_KEYS = ("x", "y", "width", "height")

# Types an author may declare for a user-editable option. bool is listed
# separately from int because it is a subclass of it (see _option_value_ok).
_OPTION_TYPES = {
    "string": (str,),
    "int": (int,),
    "number": (int, float),
    "bool": (bool,),
    "enum": (str,),
}


def _type_ok(value, default):
    """Is value's type compatible with the pattern default's type?

    ponytail: type is inferred from the default; a null default (x, y, uid,
    allowed_methods, ...) carries no type, so those fields skip the check. A
    stricter per-field schema is the upgrade path if the store needs it.
    """
    if default is None or value is None:
        return True
    if isinstance(default, bool):  # bool before int: bool is a subclass of int
        return isinstance(value, bool)
    if isinstance(default, int):  # opacity/corner_radius accept floats too
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, (list, dict)):  # screenshots, options
        return isinstance(value, type(default))
    return True


def _option_value_ok(kind, value):
    """Does `value` match a declared option type?"""
    if kind == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # True is not an int/number/string as far as an option goes
    return isinstance(value, _OPTION_TYPES[kind])


class Manifest:
    def __init__(self, path, pattern_path=_DEFAULT_PATTERN):
        pattern = self.load_manifest(pattern_path)
        # Defaults + which keys are mandatory (flag == 1), per instance.
        self.defaults = {key: default for key, (default, _flag) in pattern.items()}
        self.mandatory = [key for key, (_default, flag) in pattern.items() if flag == 1]
        for key, default in self.defaults.items():
            setattr(self, key, default)

        manifest = self.load_manifest(path)
        self.path = path
        self.dict = manifest
        self.validate(manifest)
        self.apply_values(manifest)

        # Author-declared options start at their declared default, so a widget
        # reads manifest.<option> whether or not the user ever changed it. The
        # settings overlay below is what replaces one with a user's value.
        for name, spec in self.options.items():
            setattr(self, name, spec.get("default"))

        # Overlay runtime settings (moved/resized/screen) on top of the authored
        # manifest. Missing file = first run, no overrides.
        self.settings_path = os.path.join(os.path.dirname(os.path.abspath(path)), "settings.json")
        settings = self.load_settings()
        self.validate_settings(settings)
        self.settings = settings
        self.apply_values(settings)

    @staticmethod
    def load_manifest(path):
        with open(path, "r") as mfile:
            return json.load(mfile)

    def load_settings(self):
        if not os.path.exists(self.settings_path):
            return {}
        with open(self.settings_path, "r") as sfile:
            return json.load(sfile)

    def save_setting(self, **values):
        """Persist runtime state to settings.json (never the authored manifest)."""
        self.settings.update(values)
        for key, value in values.items():
            setattr(self, key, value)
        with open(self.settings_path, "w") as sfile:
            json.dump(self.settings, sfile, indent=4)

    def layout(self, key):
        """Geometry remembered for one display layout, or {} if that layout is new.

        Positions are stored per monitor arrangement (see _layout_key in the
        pywebview backend): a widget dragged to a spot on the external display
        keeps that spot when you redock, and keeps its laptop-only spot when you
        undock, instead of the two fighting over one x/y.
        """
        return self.settings.get("layouts", {}).get(key, {})

    def save_layout(self, key, **values):
        """Persist geometry for one display layout.

        Also mirrors it to the top-level keys: that's what a settings.json
        written before layouts existed looks like, and what the loader falls back
        to when the current arrangement has no entry yet.
        """
        layouts = dict(self.settings.get("layouts", {}))
        layouts[key] = dict(layouts.get(key, {}), **values)
        self.save_setting(layouts=layouts, **values)

    def set(self, key, value):
        setattr(self, key, value)
        self.dict[key] = value

    def validate(self, manifest):
        """Check manifest against the pattern; raise ValueError listing all problems.

        Unknown keys are allowed (real widgets carry extras like handle_enabled),
        so this validates only the fields the pattern knows about.
        """
        errors = []

        missing = [key for key in self.mandatory if key not in manifest]
        if missing:
            errors.append("missing mandatory field(s): %s" % ", ".join(sorted(missing)))

        for key, value in manifest.items():
            if key not in self.defaults:
                continue  # forward-compatible: extra keys pass through untouched
            if not _type_ok(value, self.defaults[key]):
                errors.append(
                    "%r has wrong type: expected %s, got %s"
                    % (key, type(self.defaults[key]).__name__, type(value).__name__)
                )
            if key in _ENUMS and value is not None and value not in _ENUMS[key]:
                errors.append(
                    "%r must be one of %s, got %r" % (key, _ENUMS[key], value)
                )

        for key in ("allowed_methods", "screenshots"):
            value = manifest.get(key)
            if value is not None and not (
                isinstance(value, list) and all(isinstance(x, str) for x in value)
            ):
                errors.append("%r must be a list of strings" % key)

        errors.extend(self.validate_options(manifest.get("options", {})))

        # A hosted droplet loads its source as a URL. If it isn't an absolute
        # http(s) URL (e.g. an empty or relative string), pywebview treats it as
        # a path, spins up its own bottle server for it, and floods stderr with
        # `asset() missing ... 'file'` on every request. Catch it here so the
        # manager shows a broken droplet instead of a launched one crash-looping.
        if manifest.get("origin") == "hosted":
            source = manifest.get("source", self.defaults.get("source"))
            if not (isinstance(source, str) and re.match(r"^https?://", source)):
                errors.append(
                    "hosted 'source' must be an absolute http(s):// URL, got %r" % source
                )

        if errors:
            raise ValueError(
                "Invalid manifest %s:\n  - %s" % (self.path, "\n  - ".join(errors))
            )

    @property
    def reserved_option_names(self):
        """Names an author's option may NOT take.

        Option values are stored flat in settings.json and applied as attributes,
        exactly like the geometry the runtime writes -- so an option called `x`
        or `width` would fight the window's position, and one called `origin` or
        `allowed_methods` would let a user-editable file rewrite the security
        tier. Every manifest field and every settings/layout key is off limits.
        """
        return set(self.defaults) | set(_SETTINGS_KEYS) | set(_LAYOUT_KEYS)

    def validate_options(self, options):
        """Check the manifest's `options` schema. Returns a list of problems."""
        if not isinstance(options, dict):
            return ["'options' must be an object, got %s" % type(options).__name__]

        errors = []
        reserved = self.reserved_option_names
        for name, spec in options.items():
            where = "option %r" % name
            if name in reserved:
                errors.append(
                    "%s is a reserved name (geometry or manifest field)" % where
                )
            if not isinstance(spec, dict):
                errors.append(
                    "%s must be an object, got %s" % (where, type(spec).__name__)
                )
                continue
            kind = spec.get("type")
            if kind not in _OPTION_TYPES:
                errors.append(
                    "%s has unknown type %r (allowed: %s)"
                    % (where, kind, ", ".join(sorted(_OPTION_TYPES)))
                )
                continue
            if kind == "enum":
                choices = spec.get("choices")
                if not (
                    isinstance(choices, list)
                    and choices
                    and all(isinstance(c, str) for c in choices)
                ):
                    errors.append(
                        "%s needs 'choices': a non-empty list of strings" % where
                    )
                elif "default" in spec and spec["default"] not in choices:
                    errors.append(
                        "%s default %r is not one of its choices" % (where, spec["default"])
                    )
                continue
            for bound in ("min", "max"):
                if bound in spec and not _option_value_ok("number", spec[bound]):
                    errors.append("%s: %r must be a number" % (where, bound))
            if "default" in spec and not _option_value_ok(kind, spec["default"]):
                errors.append(
                    "%s default has wrong type: expected %s, got %s"
                    % (where, kind, type(spec["default"]).__name__)
                )
        return errors

    def option_errors(self, name, value):
        """Check one option *value* against its declared spec."""
        spec = self.options.get(name)
        if spec is None:
            return ["unknown option %r" % name]
        kind = spec["type"]
        if not _option_value_ok(kind, value):
            return [
                "%r has wrong type: expected %s, got %s"
                % (name, kind, type(value).__name__)
            ]
        if kind == "enum" and value not in spec["choices"]:
            return ["%r must be one of %s, got %r" % (name, spec["choices"], value)]
        errors = []
        if "min" in spec and value < spec["min"]:
            errors.append("%r must be >= %s, got %r" % (name, spec["min"], value))
        if "max" in spec and value > spec["max"]:
            errors.append("%r must be <= %s, got %r" % (name, spec["max"], value))
        return errors

    def option_values(self):
        """Every declared option's current value (user's, else the default)."""
        return {
            name: getattr(self, name, spec.get("default"))
            for name, spec in self.options.items()
        }

    def save_options(self, values):
        """Validate author-declared option values, then persist them.

        The manager writes user input through here rather than save_setting, so
        a bad value is rejected at the boundary instead of at the widget's next
        launch (settings.json is validated on load, and a widget that fails
        validation does not start).
        """
        errors = []
        for name, value in values.items():
            errors.extend(self.option_errors(name, value))
        if errors:
            raise ValueError(
                "Invalid options for %s:\n  - %s" % (self.path, "\n  - ".join(errors))
            )
        self.save_setting(**values)

    def validate_settings(self, settings):
        """Check settings.json: runtime keys and declared options, right types."""
        errors = []
        for key, value in settings.items():
            if key in self.options:
                errors.extend(self.option_errors(key, value))
            elif key not in _SETTINGS_KEYS:
                errors.append(
                    "unknown setting %r (allowed: %s)"
                    % (key, ", ".join(tuple(_SETTINGS_KEYS) + tuple(self.options)))
                )
            elif key == "layouts":
                errors.extend(self._layout_errors(value))
            elif not _type_ok(value, self.defaults.get(key)):
                errors.append(
                    "%r has wrong type: expected %s, got %s"
                    % (key, type(self.defaults.get(key)).__name__, type(value).__name__)
                )
        if errors:
            raise ValueError(
                "Invalid settings %s:\n  - %s" % (self.settings_path, "\n  - ".join(errors))
            )

    def _layout_errors(self, layouts):
        """'layouts' is {layout key: geometry}; geometry holds x/y/width/height ints.

        Validated one level deeper than the flat settings because a bad entry here
        is silent -- the widget just opens somewhere wrong -- rather than loud.
        """
        if not isinstance(layouts, dict):
            return ["'layouts' must be an object, got %s" % type(layouts).__name__]
        errors = []
        for key, geometry in layouts.items():
            if not isinstance(geometry, dict):
                errors.append(
                    "layout %r must be an object, got %s" % (key, type(geometry).__name__)
                )
                continue
            for field, value in geometry.items():
                if field not in _LAYOUT_KEYS:
                    errors.append(
                        "layout %r has unknown key %r (allowed: %s)"
                        % (key, field, ", ".join(_LAYOUT_KEYS))
                    )
                elif not isinstance(value, int) or isinstance(value, bool):
                    errors.append(
                        "layout %r: %r must be an int, got %s"
                        % (key, field, type(value).__name__)
                    )
        return errors

    def apply_values(self, manifest):
        for key, value in manifest.items():
            setattr(self, key, value)
