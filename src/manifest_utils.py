"""Shared helpers for finding and reading a repo's manifest files
(package.json, go.mod, pyproject.toml, etc). Used by runtime.py and
aws_sdk.py, which both need to answer "does this manifest declare X".
"""

import re
from pathlib import Path

# manifest files under these dirs belong to a dependency, not the
# project itself, so we skip them when searching recursively
NOISE_DIRS = {
    "node_modules", "vendor", "vendored", ".git", ".hg", ".svn",
    "target", "build", "dist", "out", "bin", "obj",
    "venv", ".venv", "env", "__pycache__", ".tox",
    ".mypy_cache", ".pytest_cache", "site-packages",
}


def read(path):
    """Return a manifest file's text, or None if it's missing/unreadable."""
    try:
        if path is None or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def find_manifest(repo_path, filename):
    """Find `filename` under repo_path. Root-level match wins; otherwise
    search recursively and take the shallowest hit outside NOISE_DIRS.
    """
    direct = repo_path / filename
    if direct.is_file():
        return direct

    try:
        candidates = [p for p in repo_path.glob(f"**/{filename}") if p.is_file()]
    except (OSError, ValueError):
        return None

    candidates = [
        p for p in candidates
        if not any(part in NOISE_DIRS for part in p.relative_to(repo_path).parts[:-1])
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda p: len(p.relative_to(repo_path).parts))
    return candidates[0]


def label(repo_path, path):
    """Manifest path relative to the repo root, as a posix string."""
    return path.relative_to(repo_path).as_posix()


def search(pattern, text, flags=0):
    """First capture group of `pattern` in `text`, or None."""
    if not text:
        return None
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

