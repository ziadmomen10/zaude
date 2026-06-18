"""tests/_helpers.py — shared fixtures for the split kernel test suite (finding E).
Imported by every test_*.py via `from _helpers import *`. Not a test module itself.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
import unittest

VROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VROOT)
from lib import paths, trace, state as st, gates, keys as _keys, vault  # noqa: E402

# repo root (in CI) or ~/.zaude (locally) — so generator/dist tests don't depend on a real ~/.zaude
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(VROOT)))
_POLICY = os.path.join(_REPO_ROOT, "policy", "policy.json")


def write_project(root, mode="enforce", marker=paths.ZAUDE_MARKER, schema=paths.SCHEMA_VERSION,
                  project_root=None):
    zd = os.path.join(root, ".zaude")
    os.makedirs(os.path.join(zd, "artifacts"), exist_ok=True)
    with open(os.path.join(zd, "project.json"), "w", encoding="utf-8") as f:
        json.dump({"zaude_marker": marker, "schema_version": schema,
                   "project_root": project_root if project_root is not None else paths._real(root),
                   "kernel_version": "0.2.0", "enforcement_mode": mode}, f)
    return zd


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="zaude test ")
        self.root = paths._real(self.tmp)
    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

__all__ = ['os', 'sys', 'json', 'time', 'shutil', 'tempfile', 'subprocess', 'unittest', 'paths', 'trace', 'st', 'gates', 'vault', '_keys', 'VROOT', '_REPO_ROOT', '_POLICY', 'write_project', 'TmpCase']
