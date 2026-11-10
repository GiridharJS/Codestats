"""SQLite cache of per-file line-count results, keyed by path. Lets a
repeat scan skip re-reading any file whose size and mtime haven't
changed since last time.

We use (size, mtime) instead of a content hash because hashing means
reading the whole file, which defeats the point of caching. This is
the same trade-off make/ccache/etc use: a file that changes content
but somehow keeps the same size and mtime would go undetected, but
that's rare enough to accept. `--cache-clear` is the escape hatch.

No content hashing or Merkle tree here anymore -- an earlier version
had one, but hashing every file (even on cache hits) turned out to
cost real time for a feature nothing downstream needed.

Every function here is best-effort: a broken/locked/corrupt cache
should never break an actual scan, just make it un-cached.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_cache (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    language TEXT,
    lines INTEGER NOT NULL,
    blank INTEGER NOT NULL,
    comment INTEGER NOT NULL,
    code INTEGER NOT NULL
);
"""

# SQLite's placeholder limit is 999 on most builds -- stay well under it
_BULK_LOOKUP_BATCH_SIZE = 500


def open_cache(db_path):
    """Open (or create) the cache DB. Returns None on any failure
    instead of raising, so callers can just treat that as "no cache".
    """
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn
    except sqlite3.Error:
        return None


@contextmanager
def cache_connection(db_path):
    """Open a connection (or yield None) and always close it after."""
    conn = open_cache(db_path) if db_path else None
    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def lookup_files_bulk(conn, paths):
    """Look up many paths in as few queries as possible, returning
    {path: (size, mtime_ns, language, lines, blank, comment, code)}.
    A path with no cached row just isn't in the result.
    """
    if conn is None or not paths:
        return {}
    result = {}
    try:
        for i in range(0, len(paths), _BULK_LOOKUP_BATCH_SIZE):
            batch = paths[i:i + _BULK_LOOKUP_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                "SELECT path, size, mtime_ns, language, lines, blank, comment, code "
                f"FROM file_cache WHERE path IN ({placeholders})",
                batch,
            ).fetchall()
            for row in rows:
                result[row[0]] = row[1:]
    except sqlite3.Error:
        return {}
    return result


def store_file(conn, path, size, mtime_ns, language, lines, blank, comment, code):
    """Insert/update one file's cached row. Doesn't commit -- see
    commit_cache. Committing per file would mean a disk flush per
    file, which dominates a first-time scan; batch it instead.
    """
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO file_cache (path, size, mtime_ns, language, lines, blank, comment, code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "size=excluded.size, mtime_ns=excluded.mtime_ns, language=excluded.language, "
            "lines=excluded.lines, blank=excluded.blank, comment=excluded.comment, "
            "code=excluded.code",
            (path, size, mtime_ns, language, lines, blank, comment, code),
        )
    except sqlite3.Error:
        pass


def commit_cache(conn):
    """Flush pending writes. Call once per batch of store_file calls,
    not after each one.
    """
    if conn is None:
        return
    try:
        conn.commit()
    except sqlite3.Error:
        pass


def clear_cache(db_path):
    """Delete the cache DB and its WAL/SHM sidecar files. Returns True
    if anything was actually removed.
    """
    removed = False
    base = Path(db_path)
    for candidate in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
        try:
            if candidate.is_file():
                candidate.unlink()
                removed = True
        except OSError:
            pass
    return removed
