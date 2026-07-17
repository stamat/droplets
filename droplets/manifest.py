"""Manifest: load/validate a droplet's manifest.json against manifest_pattern."""

import json
import os

# Pattern lives at the repo root (one level above this package).
_DEFAULT_PATTERN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest_pattern"
)


class Manifest:
    def __init__(self, path, pattern_path=_DEFAULT_PATTERN):
        pattern = self.load_manifest(pattern_path)
        # Defaults + which keys are mandatory (flag == 1), per instance.
        self.mandatory = [key for key, (_default, flag) in pattern.items() if flag == 1]
        for key, (default, _flag) in pattern.items():
            setattr(self, key, default)

        manifest = self.load_manifest(path)
        self.path = path
        self.dict = manifest
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

    def apply_values(self, manifest):
        missing = [key for key in self.mandatory if key not in manifest]
        if missing:
            raise ValueError(
                "Manifest mandatory fields %s were not supplied. "
                "Please check your manifest file: %s" % (missing, self.path)
            )
        for key, value in manifest.items():
            setattr(self, key, value)
