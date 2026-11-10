"""Finds every file to analyse in a repo, recursing into
subdirectories. Cross-platform via pathlib rather than raw string
concatenation for the public API.

Prefers `git ls-files` (gitignored files skipped for free) and falls
back to a manual walk when it's not a git repo or git isn't
available. The manual walk also respects .gitignore/.ignore/
.tokeignore at the repo root, so ignored content is skipped even
without an actual .git folder (e.g. a downloaded ZIP snapshot).
"""

import fnmatch
import os
import re
import subprocess
from pathlib import Path

from src import config

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__",
}
# Deliberately not "build", "target", "bin", "obj", "dist", "env",
# "venv" -- those are also common Java/Kotlin package-name segments
# (org.example.core.env is a real package), and hardcoding them by
# basename alone caused a real bug: scanning spring-framework
# silently dropped 141 legitimate .java files under directories named
# "env"/"target"/"build" that were just package names, not build
# output. Real build dirs get excluded via .gitignore instead, same
# as tokei does it.

IGNORE_FILENAMES = (".gitignore", ".ignore", ".tokeignore")


class PathNotFoundError(Exception):
    """Raised when the given repository path does not exist."""


class NotADirectoryPathError(Exception):
    """Raised when the given repository path exists but isn't a directory."""


def validate_repo_path(repo_path):
    """Resolve and validate the target path, expanding `~`. Raises a
    clear exception instead of silently returning nothing later.
    """
    p = Path(repo_path).expanduser()
    if not p.exists():
        raise PathNotFoundError(f"Path does not exist: {repo_path}")
    if not p.is_dir():
        raise NotADirectoryPathError(f"Path is not a directory: {repo_path}")
    return p.resolve()


def _get_git_tracked_files_strings(repo_path: Path):
    """Same as get_git_tracked_files but returns plain strings, no
    Path objects -- used by the as_strings fast path in get_files.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None

    # git always prints forward slashes even on Windows -- normalise
    # before joining, since os.path.join won't do that for us
    repo_str = str(repo_path)
    files = [line for line in result.stdout.splitlines() if line.strip()]
    return [os.path.join(repo_str, f.replace("/", os.sep)) for f in files]


def get_git_tracked_files(repo_path: Path):
    """List of absolute Paths for files tracked by git in repo_path,
    or None if it's not a git repo / git isn't on PATH.
    """
    raw = _get_git_tracked_files_strings(repo_path)
    if raw is None:
        return None
    return [Path(f) for f in raw]


def load_ignore_patterns(repo_path: Path):
    """Combined patterns from .gitignore/.ignore/.tokeignore at the
    repo root. Root-level only -- doesn't handle nested ignore files.
    """
    patterns = []
    for filename in IGNORE_FILENAMES:
        path = repo_path / filename
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


_glob_regex_cache = {}


def _glob_segment_to_regex(pattern):
    """One gitignore glob pattern -> anchored regex source. The part
    that matters: a bare `*` only matches within a path segment
    (never crosses `/`), only `**` crosses directories. fnmatch gets
    this wrong -- treats `*` as matching `/` too, which turned
    `/src/*.*/`'s `*` into something that also matched deep vendored
    paths like `src/cmd/vendor/github.com/`, silently dropping 962
    real .go files in a real clone of golang/go.
    """
    out = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    j += 1
                out.append("(?:.*/)?")
                i = j
                continue
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                out.append(pattern[i:j + 1])
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _compiled_pattern(pattern):
    if pattern not in _glob_regex_cache:
        _glob_regex_cache[pattern] = re.compile(_glob_segment_to_regex(pattern) + "$")
    return _glob_regex_cache[pattern]


def _pattern_matches(rel_posix, is_dir, pattern):
    """Simplified gitignore single-pattern match: dir-only (trailing
    /), root-anchored (leading /), ** across dirs, no-slash matches
    at any depth. Not full gitignore, but covers the common cases.
    """
    dir_only = pattern.endswith("/")
    if dir_only:
        pattern = pattern[:-1]
        if not is_dir:
            return False

    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]

    if anchored or "/" in pattern:
        return bool(_compiled_pattern(pattern).match(rel_posix))

    basename = rel_posix.rsplit("/", 1)[-1]
    regex = _compiled_pattern(pattern)
    return bool(regex.match(basename)) or bool(regex.match(rel_posix))


def is_ignored(rel_posix, is_dir, patterns):
    """Apply patterns in order, later ones win, "!" negates -- same as
    gitignore semantics.
    """
    ignored = False
    for raw in patterns:
        negate = raw.startswith("!")
        pattern = raw[1:] if negate else raw
        if _pattern_matches(rel_posix, is_dir, pattern):
            ignored = not negate
    return ignored


def _walk_filesystem_strings(repo_path: Path):
    """Same as walk_filesystem but returns plain strings, no Path
    objects -- used by the as_strings fast path in get_files.
    """
    ignore_patterns = load_ignore_patterns(repo_path)
    # read fresh each call so CODESTATS_EXTRA_IGNORE_DIRS from a .env
    # loaded later still applies
    ignore_dirs = DEFAULT_IGNORE_DIRS | set(config.extra_ignore_dirs())

    repo_str = str(repo_path)
    # +1 skips the separator too, unless repo_str is already just a
    # separator (repo_path is the filesystem root)
    prefix_len = len(repo_str) if repo_str.endswith(os.sep) else len(repo_str) + 1

    found = []
    for root, dirs, filenames in os.walk(repo_str):
        kept_dirs = []
        for d in dirs:
            if d in ignore_dirs or d.startswith("."):
                continue
            if ignore_patterns:
                rel = os.path.join(root, d)[prefix_len:].replace(os.sep, "/")
                if is_ignored(rel, True, ignore_patterns):
                    continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for fname in filenames:
            fpath_str = os.path.join(root, fname)
            if ignore_patterns:
                rel = fpath_str[prefix_len:].replace(os.sep, "/")
                if is_ignored(rel, False, ignore_patterns):
                    continue
            found.append(fpath_str)
    return found


def walk_filesystem(repo_path: Path):
    """Recursive fallback walk, used when the target isn't a git repo
    (or --git wasn't passed). Skips noise dirs and anything matched
    by a .gitignore/.ignore/.tokeignore at the root.
    """
    return [Path(f) for f in _walk_filesystem_strings(repo_path)]


def apply_excludes(files, repo_path: Path, exclude_patterns):
    """Drop files matching any --exclude glob (relative to repo_path,
    forward-slash normalised so patterns behave the same on Windows).
    """
    if not exclude_patterns:
        return files

    kept = []
    for f in files:
        try:
            rel = f.relative_to(repo_path)
        except ValueError:
            rel = f
        rel_posix = rel.as_posix()
        if any(fnmatch.fnmatch(rel_posix, pat) for pat in exclude_patterns):
            continue
        kept.append(f)
    return kept


def apply_excludes_strings(file_strs, repo_path: Path, exclude_patterns):
    """String-based apply_excludes, for the as_strings fast path."""
    if not exclude_patterns:
        return file_strs

    repo_str = str(repo_path)
    prefix_len = len(repo_str) if repo_str.endswith(os.sep) else len(repo_str) + 1

    kept = []
    for f in file_strs:
        rel_posix = f[prefix_len:].replace(os.sep, "/") if f.startswith(repo_str) else f.replace(os.sep, "/")
        if any(fnmatch.fnmatch(rel_posix, pat) for pat in exclude_patterns):
            continue
        kept.append(f)
    return kept


def get_files(repo_path, use_git=True, exclude_patterns=None, as_strings=False):
    """Final list of files to analyse for repo_path, honouring git
    tracking and exclude patterns. Raises PathNotFoundError /
    NotADirectoryPathError for a bad path.

    Returns Path objects by default. Pass as_strings=True to skip
    building Path objects entirely -- useful when the caller (cli.run)
    just needs strings anyway; building a Path per file only to
    immediately discard it costs the same as never avoiding it.
    """
    repo = validate_repo_path(repo_path)
    files = None

    if as_strings:
        if use_git:
            files = _get_git_tracked_files_strings(repo)
        if files is None:
            files = _walk_filesystem_strings(repo)
    else:
        if use_git:
            files = get_git_tracked_files(repo)
        if files is None:
            files = walk_filesystem(repo)

    # deliberately not filtering out nonexistent files with is_file()
    # here -- git ls-files can list a deleted-but-uncommitted path,
    # but checking costs a stat() per file, duplicating the stat the
    # cache lookup does moments later anyway. Missing/unreadable
    # files just come back as a normal skipped entry downstream.
    if as_strings:
        return apply_excludes_strings(files, repo, exclude_patterns)
    return apply_excludes(files, repo, exclude_patterns)
