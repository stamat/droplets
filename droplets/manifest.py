"""Manifest: load/validate a droplet's manifest.json against manifest_pattern.

manifest_pattern is the single source of truth: it gives every field's default
and whether it's mandatory. Types are inferred from each default (bool/int/str);
the few fields the default can't describe — enums (one member shown) and
allowed_methods (a list) — are pinned explicitly below.
"""

import json
import os

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
    return True


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

    @staticmethod
    def load_manifest(path):
        with open(path, "r") as mfile:
            return json.load(mfile)

    def dump_manifest(self, path):
        with open(path, "w") as mfile:
            json.dump(self.dict, mfile, indent=4)

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

        am = manifest.get("allowed_methods")
        if am is not None and not (
            isinstance(am, list) and all(isinstance(x, str) for x in am)
        ):
            errors.append("'allowed_methods' must be a list of strings")

        if errors:
            raise ValueError(
                "Invalid manifest %s:\n  - %s" % (self.path, "\n  - ".join(errors))
            )

    def apply_values(self, manifest):
        for key, value in manifest.items():
            setattr(self, key, value)
