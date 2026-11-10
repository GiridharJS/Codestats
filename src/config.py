"""Simple `.env` config for a handful of codestats' internal
tunables: default PDF filename, memory budget per worker, the
file-count threshold for parallel processing, extra ignore dirs.

No python-dotenv dependency -- just a minimal KEY=VALUE parser since
the needs here are small.

Precedence: a real env var always wins, `.env` only fills in what's
not already set (setdefault), built-in default is the fallback.

Which `.env` gets loaded: `CODESTATS_ENV_FILE` if set, else `.env` in
the cwd. Missing file is fine, everything just uses its default. This
is read via an env var rather than a CLI flag so it resolves before
argparse runs (some defaults, like the PDF filename, feed into how
the CLI args themselves are defined).

Recognised keys, all optional:
    CODESTATS_DEFAULT_PDF_FILENAME   (default: codestats_report.pdf)
    CODESTATS_WORKER_MEMORY_MB       (default: 300)
    CODESTATS_MIN_FILES_FOR_PARALLEL (default: 1000)
    CODESTATS_EXTRA_IGNORE_DIRS      (comma-separated, default: none)
    CODESTATS_DEFAULT_SORT_BY        (default: code)
    CODESTATS_MAX_PROJECTS_DISPLAYED (default: 7)
    CODESTATS_CACHE_FILE             (exact path for the cache DB; default
                                       is an auto-named file under the cache
                                       dir below -- see default_cache_path)
    CODESTATS_CACHE_DIR              (base dir for that auto-named file,
                                       if CACHE_FILE isn't set -- default is
                                       the OS temp dir; see default_cache_dir)
"""

import os
from pathlib import Path


def load_env_file(path=None):
    """Parse a KEY=VALUE .env file into os.environ (setdefault, so a
    real env var always wins). No-op if the file's missing/unreadable.

    Supports '#' comments, blank lines, quoted values. No variable
    expansion or multi-line values -- kept intentionally simple.
    """
    candidate = Path(path) if path else Path(".env")
    try:
        if not candidate.is_file():
            return
        text = candidate.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _get_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_pdf_filename():
    return os.environ.get("CODESTATS_DEFAULT_PDF_FILENAME") or "codestats_report.pdf"


def worker_memory_budget_mb():
    """Assumed MB per worker process, used to cap auto-detected
    parallelism on memory-constrained machines.
    """
    return _get_int("CODESTATS_WORKER_MEMORY_MB", 300)


def min_files_for_parallel():
    """Below this many files, skip the process pool and just run
    sequentially -- spinning up workers isn't worth it for a small repo.
    """
    return _get_int("CODESTATS_MIN_FILES_FOR_PARALLEL", 1000)


def max_projects_displayed():
    """Cap on how many project roots --projects lists at once. Large
    monorepos can have a lot of them; shallowest ones are kept first.
    """
    return _get_int("CODESTATS_MAX_PROJECTS_DISPLAYED", 7)


def default_cache_dir():
    """Base dir for the auto-named cache file, when neither
    --cache-file nor CODESTATS_CACHE_FILE gives an exact path.

    C:\\tmp on Windows (the real default temp dir is a long, buried,
    version-dependent path -- this is just easier to find), OS temp
    dir everywhere else. Created automatically if it doesn't exist.

    Override with CODESTATS_CACHE_DIR if you want the cache to live
    somewhere more permanent than a temp dir.
    """
    import sys
    import tempfile

    override = os.environ.get("CODESTATS_CACHE_DIR")
    if override:
        return override
    if sys.platform.startswith("win"):
        return "C:\\tmp"
    return tempfile.gettempdir()


def default_cache_path(repo_root):
    """Default cache DB path when --cache-file isn't given. Caching is
    always on -- this just decides where the file lives.

    CODESTATS_CACHE_FILE, if set, wins outright and is used as-is.

    Otherwise: a file under default_cache_dir(), named from a hash of
    the repo's resolved path. Keeps the cache out of the repo itself,
    keeps different repos from colliding, and is deterministic so the
    same repo always maps to the same cache file.

    Note the OS temp dir isn't guaranteed to survive a reboot -- fine
    here, worst case a scan just starts with an empty cache again.
    Use CODESTATS_CACHE_DIR or --cache-file if you want it to persist.
    """
    override = os.environ.get("CODESTATS_CACHE_FILE")
    if override:
        return override
    import hashlib

    try:
        resolved = str(Path(repo_root).expanduser().resolve())
    except OSError:
        resolved = str(Path(repo_root))
    repo_key = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    filename = f"codestats_cache_{repo_key}.db"
    return str(Path(default_cache_dir()) / filename)


def extra_ignore_dirs():
    """Extra directory names to skip, on top of the built-in list."""
    raw = os.environ.get("CODESTATS_EXTRA_IGNORE_DIRS")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def default_sort_by():
    valid = {"code", "lines", "files", "comment", "blank"}
    value = os.environ.get("CODESTATS_DEFAULT_SORT_BY")
    return value if value in valid else "code"
