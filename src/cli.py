"""Command line entry point for codestats."""

import argparse
import functools
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from src import cache, config
from src.counter import FileStats, count_file, count_markdown_file
from src.languages import detect_language
from src.report import (
    aggregate, compute_percentages, format_bar, format_cache_summary,
    format_files_table, format_projects_table, format_skipped_table, format_table,
    format_timing_summary, generate_pdf, totals,
)
from src.aws_sdk import detect_aws_sdks
from src.runtime import detect_runtimes, find_project_roots
from src.walker import NotADirectoryPathError, PathNotFoundError, get_files

# Loaded once at import time, before any config getter below is ever
# called, so a `.env` file's values are in place before build_parser()
# reads any of them for an argument's default. See config.py for the
# lookup order (CODESTATS_ENV_FILE env var, else ".env" in the CWD)
# and why real environment variables always take priority.
config.load_env_file(os.environ.get("CODESTATS_ENV_FILE"))

DEFAULT_PDF_FILENAME = config.default_pdf_filename()


def _process_one_file(f):
    """Detect language and count a single file. Pure function with no
    shared state, so it's safe to run across many worker processes at
    once -- each file is completely independent of every other file.
    Must stay a top-level, picklable function: ProcessPoolExecutor
    sends this function (by reference) and its arguments to each
    worker process, which requires it to be importable by name.

    Every file is counted under a single detected language only.

    Returns one of:
      ("counted", FileStats)
      ("skipped", (path, language_or_None, reason))
    """
    language = detect_language(f)
    if language is None:
        return ("skipped", (str(f), None, "unsupported file type"))

    if language == "Markdown":
        stats = count_markdown_file(f)
    else:
        stats = count_file(f, language)

    if stats is None:
        return ("skipped", (str(f), language, "binary or unreadable file"))
    return ("counted", stats)


# Below this many files, a process pool's own spin-up cost isn't
# worth paying -- skip straight to sequential and save it entirely.
# This matters far more on Windows than on Linux/macOS: POSIX systems
# can fork() a worker (near-instant, shares the already-loaded
# interpreter's memory), but Windows can't fork at all, so Python's
# multiprocessing falls back to "spawn" there -- every single worker
# has to start a BRAND NEW Python interpreter from scratch and
# re-import the whole codestats package (and its dependencies) before
# it can process even one file. That's genuinely slow (can easily be
# several hundred ms per worker) compared to the now-fast per-file
# scan itself, so for anything but a large scan, spawning a pool can
# cost more than it ever saves.
MIN_FILES_FOR_PARALLEL = config.min_files_for_parallel()


def _detect_worker_capacity():
    """Decide how many worker processes to spawn from this machine's
    CPU and memory. No --workers flag -- always automatic.

    CPU count caps useful parallelism, memory then caps it further
    (~300MB budgeted per worker, since each is a full interpreter
    holding file buffers -- spawning "CPU count" workers on a
    memory-constrained box can thrash instead of help).

    Uses os.sched_getaffinity (Linux) instead of os.cpu_count() for
    the CPU count where available -- cpu_count() reports the host's
    total CPUs, not what this process is actually allowed to use.
    Inside a container capped to 2 cores, cpu_count() can still say
    16, spawning 16 workers that all fight over 2 cores -- slower
    than just using 2. sched_getaffinity reflects the real limit.
    """
    cpu_workers = None
    try:
        cpu_workers = len(os.sched_getaffinity(0))
    except AttributeError:
        pass  # not Linux -- os.sched_getaffinity doesn't exist here
    if not cpu_workers:
        cpu_workers = os.cpu_count() or 1

    mem_workers = cpu_workers
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        total_bytes = page_size * phys_pages
        mem_workers = max(1, total_bytes // (config.worker_memory_budget_mb() * 1024 * 1024))
    except (ValueError, OSError, AttributeError):
        # os.sysconf isn't available on Windows -- fall back to the
        # Win32 API directly so Windows machines still get a real
        # memory-based cap instead of none at all.
        total_bytes = _windows_total_memory_bytes()
        if total_bytes is not None:
            mem_workers = max(1, total_bytes // (config.worker_memory_budget_mb() * 1024 * 1024))

    return max(1, min(cpu_workers, mem_workers))


def _windows_total_memory_bytes():
    """Return total physical RAM in bytes on Windows via the Win32
    GlobalMemoryStatusEx API, or None if that's not possible (wrong
    platform, ctypes unavailable, API call failed). No extra
    dependency needed -- ctypes is part of the standard library.
    """
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) == 0:
            return None
        return status.ullTotalPhys
    except (ImportError, OSError, AttributeError, ValueError):
        return None


def _process_files_parallel(files, workers=None):
    """Run _process_one_file across a process pool.

    Processes, not threads: counting lines is CPU-bound (character
    scanning in counter.py), and the GIL means threads wouldn't
    actually run concurrently -- a thread pool would show ~zero
    speedup. Processes have no GIL contention between them.

    `workers` is an internal/testing override -- the CLI itself never
    sets it, always goes through _detect_worker_capacity().

    Result order matches `files` (executor.map preserves order).
    """
    file_stats = []
    skipped = []

    if not files:
        return file_stats, skipped

    if workers is None:
        workers = _detect_worker_capacity()
        if len(files) < MIN_FILES_FOR_PARALLEL:
            # Not enough work to amortise a process pool's own
            # spin-up cost -- see MIN_FILES_FOR_PARALLEL's docstring.
            # Only applies when the caller didn't explicitly request a
            # worker count (tests use that override to force real
            # parallel execution on small fixtures).
            workers = 1
    workers = max(1, min(workers, len(files)))

    if workers == 1:
        # Skip process-pool overhead entirely for the single-worker
        # case (and this is also what makes single-file/tiny-repo
        # runs fast, since spawning a process pool has real fixed cost).
        for f in files:
            kind, result = _process_one_file(f)
            if kind == "counted":
                file_stats.append(result)
            else:
                skipped.append(result)
        return file_stats, skipped

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for kind, result in executor.map(_process_one_file, files, chunksize=32):
            if kind == "counted":
                file_stats.append(result)
            else:
                skipped.append(result)

    return file_stats, skipped


def _process_chunk(files):
    """Process a whole batch of files in one worker call, aggregating
    to per-language totals before returning -- not one FileStats
    object per file.

    For the common case where only totals are needed (no --filewise).
    Every object executor.map returns has to be pickled across an OS
    pipe -- doing that per file is real overhead on a large repo.
    Aggregating each worker's chunk down to a handful of counters
    before sending it back cuts that IPC volume by orders of
    magnitude.

    Returns (partial_summary, skipped) -- partial_summary shaped like
    report.aggregate's return value, but only this chunk's files.
    """
    summary = defaultdict(lambda: {"files": 0, "lines": 0, "blank": 0, "comment": 0, "code": 0})
    skipped = []
    for f in files:
        kind, result = _process_one_file(f)
        if kind == "counted":
            bucket = summary[result.language]
            bucket["files"] += 1
            bucket["lines"] += result.lines
            bucket["blank"] += result.blank
            bucket["comment"] += result.comment
            bucket["code"] += result.code
        else:
            skipped.append(result)
    return dict(summary), skipped


def _merge_partial_summaries(summaries):
    """Combine several {language: totals} dicts (as returned by
    `_process_chunk`) into one, summing every counter per language.
    """
    merged = defaultdict(lambda: {"files": 0, "lines": 0, "blank": 0, "comment": 0, "code": 0})
    for summary in summaries:
        for language, counts in summary.items():
            bucket = merged[language]
            for key in ("files", "lines", "blank", "comment", "code"):
                bucket[key] += counts[key]
    return dict(merged)


def _process_files_parallel_aggregated(files, workers=None):
    """Like _process_files_parallel, but returns an already-merged
    {language: totals} summary instead of per-file FileStats -- for
    the common case where --filewise wasn't passed. See
    _process_chunk for why: one object sent back per worker, not one
    per file.

    Files are split into one contiguous chunk per worker (not many
    small chunks) since there's no load-balancing benefit once a
    worker no longer round-trips per file -- fewer/larger chunks
    means less IPC.

    Returns (summary, skipped) -- summary already fully aggregated.
    """
    if not files:
        return {}, []

    if workers is None:
        workers = _detect_worker_capacity()
        if len(files) < MIN_FILES_FOR_PARALLEL:
            workers = 1
    workers = max(1, min(workers, len(files)))

    if workers == 1:
        return _process_chunk(files)

    chunk_size = -(-len(files) // workers)  # ceiling division
    chunks = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]

    partial_summaries = []
    skipped = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for partial_summary, chunk_skipped in executor.map(_process_chunk, chunks):
            partial_summaries.append(partial_summary)
            skipped.extend(chunk_skipped)

    return _merge_partial_summaries(partial_summaries), skipped


def _scan_one_file_cached(path_str, conn, cached_rows):
    """Detect a file's language, check `cached_rows` (pre-fetched
    {path: (size, mtime_ns, language, lines, blank, comment, code)}),
    return (stats_or_None, skip_entry_or_None, was_cache_hit).

    A hit means path_str is cached AND size/mtime still match a
    fresh stat() -- provably unchanged, so the old FileStats is
    reused with no file read. A miss falls through to a real read via
    count_file/count_markdown_file, and writes the result back.

    Takes a plain string, not a Path -- the caller converts the whole
    chunk to strings once up front for the bulk lookup, and this
    reuses that same string instead of re-converting per file (a
    Path's str()/fspath() cost real overhead even on repeat calls).
    """
    language = detect_language(path_str)
    if language is None:
        return None, (path_str, None, "unsupported file type"), False

    size = mtime_ns = None
    if conn is not None:
        try:
            st = os.stat(path_str)
            size, mtime_ns = st.st_size, st.st_mtime_ns
        except OSError:
            pass
        if size is not None:
            row = cached_rows.get(path_str)
            if row is not None:
                cached_size, cached_mtime_ns, cached_language, lines, blank, comment, code = row
                if cached_size == size and cached_mtime_ns == mtime_ns and cached_language == language:
                    stats = FileStats(
                        path=path_str, language=language,
                        lines=lines, blank=blank, comment=comment, code=code,
                    )
                    return stats, None, True

    if language == "Markdown":
        stats = count_markdown_file(path_str)
    else:
        stats = count_file(path_str, language)
    if stats is None:
        return None, (path_str, language, "binary or unreadable file"), False

    if conn is not None and size is not None:
        cache.store_file(
            conn, path_str, size, mtime_ns, language,
            stats.lines, stats.blank, stats.comment, stats.code,
        )

    return stats, None, False


def _process_chunk_cached(files, cache_db_path=None):
    """Cache-aware counterpart to `_process_chunk`: same aggregated-
    summary output, but each file goes through `_scan_one_file_cached`
    first, and this also returns a (hits, misses) count. Opens exactly
    ONE cache connection for this whole chunk (not one per file), same
    reasoning as `_process_chunk` batching IPC -- and does exactly ONE
    (or a handful, for very large chunks -- see
    `cache.lookup_files_bulk`) bulk cache lookup for the WHOLE chunk up
    front, instead of one `SELECT` per file.
    """
    summary = defaultdict(lambda: {"files": 0, "lines": 0, "blank": 0, "comment": 0, "code": 0})
    skipped = []
    hits = 0
    misses = 0

    # Converted once, up front, for the WHOLE chunk -- and reused
    # for both the bulk cache lookup and every _scan_one_file_cached
    # call below, rather than converting each Path to a string twice
    # (once here, once again inside _scan_one_file_cached).
    file_strs = [os.fspath(f) for f in files]

    with cache.cache_connection(cache_db_path) as conn:
        cached_rows = cache.lookup_files_bulk(conn, file_strs) if conn is not None else {}
        for path_str in file_strs:
            stats, skip_entry, was_hit = _scan_one_file_cached(path_str, conn, cached_rows)
            if stats is not None:
                bucket = summary[stats.language]
                bucket["files"] += 1
                bucket["lines"] += stats.lines
                bucket["blank"] += stats.blank
                bucket["comment"] += stats.comment
                bucket["code"] += stats.code
                hits += was_hit
                misses += not was_hit
            else:
                skipped.append(skip_entry)
        # One flush for this whole chunk's writes, not one per file --
        # see cache.store_file's docstring for why that distinction is
        # the difference between a fast first-time cache build and a
        # very slow one.
        cache.commit_cache(conn)

    return dict(summary), skipped, hits, misses


def _process_chunk_detailed_cached(files, cache_db_path=None):
    """Cache-aware counterpart to `_process_files_parallel`'s per-file
    behaviour (full FileStats list, for --filewise), instead of the
    pre-aggregated totals `_process_chunk_cached` returns. Otherwise
    identical: one cache connection and one bulk lookup per chunk, a
    (hits, misses) count returned alongside.
    """
    file_stats = []
    skipped = []
    hits = 0
    misses = 0

    file_strs = [os.fspath(f) for f in files]

    with cache.cache_connection(cache_db_path) as conn:
        cached_rows = cache.lookup_files_bulk(conn, file_strs) if conn is not None else {}
        for path_str in file_strs:
            stats, skip_entry, was_hit = _scan_one_file_cached(path_str, conn, cached_rows)
            if stats is not None:
                file_stats.append(stats)
                hits += was_hit
                misses += not was_hit
            else:
                skipped.append(skip_entry)
        cache.commit_cache(conn)  # one flush per chunk, not one per file

    return file_stats, skipped, hits, misses


def _process_files_parallel_cached(files, workers=None, cache_db_path=None, filewise=False):
    """Cache-aware entry point used for every scan: one chunk per
    worker, routed through _process_chunk_cached or
    _process_chunk_detailed_cached depending on whether per-file
    detail is needed.

    Returns (result, skipped, hits, misses, workers_used). `result`
    is the aggregated summary dict or a FileStats list, matching
    filewise. `workers_used` is the actual worker count after
    auto-detection and clamping -- surfaced in the timing breakdown
    so it's visible what got picked for this run.
    """
    empty_result = {} if not filewise else []
    if not files:
        return empty_result, [], 0, 0, 0

    if workers is None:
        workers = _detect_worker_capacity()
        if len(files) < MIN_FILES_FOR_PARALLEL:
            workers = 1
    workers = max(1, min(workers, len(files)))

    chunk_fn = _process_chunk_detailed_cached if filewise else _process_chunk_cached

    if workers == 1:
        result, skipped, hits, misses = chunk_fn(files, cache_db_path)
        return result, skipped, hits, misses, 1

    chunk_size = -(-len(files) // workers)  # ceiling division
    chunks = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]

    bound_chunk_fn = functools.partial(chunk_fn, cache_db_path=cache_db_path)

    results = []
    skipped = []
    hits = 0
    misses = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for partial_result, chunk_skipped, chunk_hits, chunk_misses in executor.map(bound_chunk_fn, chunks):
            results.append(partial_result)
            skipped.extend(chunk_skipped)
            hits += chunk_hits
            misses += chunk_misses

    if filewise:
        merged_result = [stats for chunk_result in results for stats in chunk_result]
    else:
        merged_result = _merge_partial_summaries(results)

    return merged_result, skipped, hits, misses, workers


def build_parser():
    parser = argparse.ArgumentParser(
        prog="codestats",
        description=(
            "Count lines of code and show language composition of a local "
            "repository (Java, Python, Go, Ruby, Rust, C, C++). "
            "Scans all subdirectories. Works on Windows and Linux."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the repository / directory to analyse (default: current directory). "
             "Quote paths containing spaces on any OS.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern (relative to path, forward slashes) to exclude. Repeatable.",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Use `git ls-files` to discover files (respects .gitignore). "
             "If omitted, the filesystem is walked directly, ignoring any git tracking.",
    )
    parser.add_argument(
        "--sort-by",
        choices=["code", "lines", "files", "comment", "blank"],
        default="code",
        help="Metric to sort the table / percentages by (default: code).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of a formatted table.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour in the terminal language bar.",
    )
    parser.add_argument(
        "--no-bar",
        action="store_true",
        help="Suppress the terminal visual language bar (table only).",
    )
    parser.add_argument(
        "--pdf",
        nargs="?",
        const=DEFAULT_PDF_FILENAME,
        default=None,
        metavar="FILE",
        help=f"Generate a PDF report. With no value, writes to {DEFAULT_PDF_FILENAME} "
             "in the current directory; pass a path to use a custom filename. "
             "No PDF is generated unless this flag is passed.",
    )
    parser.add_argument(
        "--filewise",
        action="store_true",
        help="Include per-file 'Validated Files' and 'Skipped Files' tables "
             "(in terminal, JSON, and PDF output). Default: summary table only.",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Show each language's declared runtime/version requirement, read from the "
             "project's own manifest files (pom.xml, package.json, pyproject.toml, go.mod, "
             "Gemfile, Cargo.toml, *.csproj, .tool-versions, etc.) rather than what's "
             "installed locally. This reports ONE runtime per language (the shallowest "
             "manifest found) -- see --projects for multi-repo/monorepo layouts where "
             "different sub-projects declare different versions. Off by default.",
    )
    parser.add_argument(
        "--projects",
        action="store_true",
        help="List every distinct project root found in the scanned tree (every directory "
             "containing a recognised manifest -- pom.xml, package.json, go.mod, etc.), "
             "each with its own declared runtime. Use this for multi-repo/monorepo layouts "
             "where --runtime's single-value-per-language summary would hide the fact that "
             "different sub-projects declare different versions. Off by default.",
    )
    parser.add_argument(
        "--aws-sdk",
        action="store_true",
        help="Show each language's declared AWS SDK dependency (and version), read from the "
             "project's own manifest files (requirements.txt/pyproject.toml/Pipfile for "
             "Python, package.json for JavaScript/TypeScript, go.mod for Go, "
             "pom.xml/build.gradle for Java/Kotlin, Gemfile for Ruby, *.csproj for C#/F#, "
             "Cargo.toml for Rust, CMakeLists.txt for C++) -- same approach as --runtime, "
             "so this adds no per-file scanning cost: it reads a handful of manifest files "
             "once, not every source file's import statements. Off by default.",
    )
    parser.add_argument(
        "--cache-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to the SQLite cache database codestats uses for incremental scanning "
             "(on by default -- see the README's Performance section). Default, if omitted: "
             "a file in C:\\tmp (Windows) or the OS temp directory (elsewhere) -- override "
             "the directory with CODESTATS_CACHE_DIR, "
             "automatically named from a hash of the scanned repo's path (nothing is written "
             "inside the repo itself, and different repos never share a cache). Set "
             "CODESTATS_CACHE_FILE in a .env file for one fixed, persistent location instead.",
    )
    parser.add_argument(
        "--cache-clear",
        action="store_true",
        help="Delete the cache database before scanning, forcing a full fresh scan (still "
             "repopulates the cache for next time).",
    )
    return parser


def _format_elapsed(seconds):
    """Format an elapsed duration the way a person would say it: sub-
    second runs get millisecond precision (since most real repos scan
    fast enough that "0s" would be uninformative), anything under a
    minute gets one decimal of seconds, and anything longer gets a
    minutes+seconds breakdown.
    """
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}m {remaining:.1f}s"


def run(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    start_time = time.perf_counter()

    discovery_start = time.perf_counter()
    try:
        # as_strings=True: nothing past this point needs Path methods
        # (no relative-path computation happens anywhere in the
        # per-file processing loop anymore -- that was only ever
        # needed by the now-removed Merkle tree), so file discovery
        # itself skips constructing Path objects entirely rather than
        # building them and then immediately converting back to
        # strings -- see walker.get_files's docstring for why that
        # distinction actually matters (it's not just a style choice:
        # building a Path only to discard it costs the same as
        # building it during the walk in the first place). Every one
        # of these strings gets processed once per worker per scan,
        # so avoiding that construction here, exactly once per file,
        # means every worker never touches Path's lazy-parsing
        # machinery at all -- and as a side benefit, plain strings
        # are cheaper to pickle across the ProcessPoolExecutor's IPC
        # boundary than Path objects would have been.
        files = get_files(args.path, use_git=args.git, exclude_patterns=args.exclude, as_strings=True)
    except PathNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except NotADirectoryPathError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    discovery_seconds = time.perf_counter() - discovery_start

    # Caching is on by default -- see the README's Performance section
    # for why: a repeat scan reusing size/mtime-unchanged files from
    # the SQLite cache is the difference between re-reading every
    # file and re-reading only what actually changed. --cache-file
    # picks where that database lives; --cache-clear wipes it first.
    if args.cache_file:
        cache_db_path = args.cache_file
    else:
        # Default location: C:\tmp on Windows, the OS temp directory
        # elsewhere (or CODESTATS_CACHE_DIR, if set), keyed by a hash of the repo's
        # own resolved path (see config.default_cache_path's
        # docstring for why it has to be a stable hash, not a random
        # temp name -- and for the trade-off of temp directories not
        # always surviving a reboot). Nothing gets written inside the
        # scanned repo itself unless --cache-file says so.
        cache_db_path = config.default_cache_path(args.path)
    if args.cache_clear:
        cache.clear_cache(cache_db_path)

    # --filewise needs every individual file's own stats (for the
    # per-file table / PDF section); everything else only ever needs
    # the final per-language totals, so it goes through the
    # chunk-aggregated fast path instead -- see
    # _process_files_parallel_aggregated's docstring for why that
    # matters at scale. Either way, the cache-aware processing
    # functions check the SQLite-backed cache first and can skip
    # reading/re-scanning a file entirely if it's unchanged. Worker
    # count is always auto-detected from this machine's CPU affinity
    # and available memory (see _detect_worker_capacity) -- there's
    # no manual override; auto-detection already accounts for the
    # things that would make a fixed number wrong (container/VM CPU
    # limits, memory pressure), so a person tuning it by hand would
    # just be re-deriving what this already works out on its own.
    processing_start = time.perf_counter()
    result, skipped, hits, misses, workers_used = _process_files_parallel_cached(
        files, workers=None, cache_db_path=cache_db_path, filewise=args.filewise,
    )
    processing_seconds = time.perf_counter() - processing_start
    if args.filewise:
        file_stats = result
        summary = aggregate(file_stats)
    else:
        file_stats = []
        summary = result

    cache_info = {
        "cache_file": str(cache_db_path),
        "cache_hits": hits,
        "cache_misses": misses,
    }

    percentages = compute_percentages(summary, key=args.sort_by if args.sort_by != "files" else "code")
    runtimes = detect_runtimes(args.path, summary.keys()) if args.runtime else None
    aws_sdk_info = detect_aws_sdks(args.path, summary.keys()) if args.aws_sdk else None
    all_project_roots = (
        find_project_roots(args.path, detected_languages=summary.keys()) if args.projects else None
    )
    project_roots = None
    if all_project_roots is not None:
        cap = config.max_projects_displayed()
        project_roots = all_project_roots[:cap]

    elapsed_seconds = time.perf_counter() - start_time
    # Always computed and shown, same as the cache summary -- both
    # are basic, always-on parts of the output now, not something
    # someone has to know to ask for with a flag.
    timing_info = {
        "discovery_seconds": round(discovery_seconds, 3),
        "processing_seconds": round(processing_seconds, 3),
        "other_seconds": round(elapsed_seconds - discovery_seconds - processing_seconds, 3),
        "files_found": len(files),
        "workers_used": workers_used,
    }

    if args.json:
        payload = {
            "summary": summary,
            "percentages": percentages,
            "totals": totals(summary),
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
        if runtimes is not None:
            payload["runtimes"] = runtimes
        if aws_sdk_info is not None:
            # AwsSdkInfo is a namedtuple, which json.dumps would
            # otherwise serialize as a bare [sdk, manifest] array --
            # converted to an explicit {"sdk": ..., "manifest": ...}
            # object per language instead, so the two fields stay
            # clearly labelled in the JSON output too.
            payload["aws_sdk"] = {
                lang: ({"sdk": info.sdk, "manifest": info.manifest} if info else None)
                for lang, info in aws_sdk_info.items()
            }
        if project_roots is not None:
            payload["project_roots"] = project_roots
            payload["total_project_roots_found"] = len(all_project_roots)
        payload["cache"] = cache_info
        payload["timing"] = timing_info
        if args.filewise:
            payload["files"] = [
                {"path": fs.path, "language": fs.language, "lines": fs.lines,
                 "code": fs.code, "comment": fs.comment, "blank": fs.blank}
                for fs in file_stats
            ]
            payload["skipped"] = [{"path": p, "language": lang, "reason": r} for p, lang, r in skipped]
            payload["skipped_count"] = len(skipped)
        print(json.dumps(payload, indent=2))
    else:
        print(format_table(summary, percentages, sort_by=args.sort_by, runtimes=runtimes, aws_sdk_info=aws_sdk_info))
        if not args.no_bar and summary:
            print()
            print(format_bar(percentages, use_color=not args.no_color))
        if args.filewise:
            print()
            print(format_files_table(file_stats))
            print()
            print(format_skipped_table(skipped))
        if project_roots is not None:
            print()
            print(format_projects_table(project_roots, total_found=len(all_project_roots)))
        print()
        print(format_cache_summary(cache_info))
        print()
        print(format_timing_summary(timing_info))
        print(f"\nTime taken: {_format_elapsed(elapsed_seconds)}")

    if args.pdf is not None:
        try:
            repo_label = str(Path(args.path).expanduser().resolve())
        except OSError:
            repo_label = str(args.path)
        try:
            pdf_path = generate_pdf(
                summary, percentages, args.pdf,
                repo_label=repo_label, sort_by=args.sort_by,
                skipped=skipped, file_stats=file_stats, filewise=args.filewise,
                runtimes=runtimes, aws_sdk_info=aws_sdk_info,
            )
            print(f"\nPDF report written to: {pdf_path}", file=sys.stderr)
        except ImportError as exc:
            print(f"\nwarning: {exc}", file=sys.stderr)

    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
