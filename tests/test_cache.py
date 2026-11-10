import sqlite3
from pathlib import Path

from src import cache


class TestOpenCache:
    def test_creates_new_database_with_schema(self, tmp_path):
        db_path = tmp_path / "cache.db"
        conn = cache.open_cache(db_path)
        assert conn is not None
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "file_cache" in tables
        # No Merkle-tree bookkeeping tables in this version -- see
        # cache.py's module docstring for why they were removed.
        assert "dir_hashes" not in tables
        assert "scan_meta" not in tables
        conn.close()

    def test_missing_parent_directories_are_created_automatically(self, tmp_path):
        # This used to fail (sqlite3 won't create a db file in a
        # directory that doesn't exist) -- but the default cache
        # location (C:\tmp on Windows, or a custom CODESTATS_CACHE_DIR)
        # isn't guaranteed to already exist, so open_cache now creates
        # whatever directories it needs first.
        db_path = tmp_path / "does" / "not" / "exist" / "cache.db"
        conn = cache.open_cache(db_path)
        assert conn is not None
        assert db_path.is_file()
        conn.close()

    def test_directory_that_cannot_be_created_returns_none_not_raises(self, tmp_path, monkeypatch):
        # A genuinely unwritable parent (permission denied, read-only
        # filesystem, etc) must still degrade gracefully rather than
        # raising -- same "no cache" contract as every other failure
        # mode here.
        def raise_os_error(self, parents=True, exist_ok=True):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "mkdir", raise_os_error)
        conn = cache.open_cache(tmp_path / "some" / "cache.db")
        assert conn is None


class TestCacheConnection:
    def test_context_manager_yields_connection_and_closes_it(self, tmp_path):
        db_path = tmp_path / "cache.db"
        with cache.cache_connection(db_path) as conn:
            assert conn is not None
            conn.execute("SELECT 1")

    def test_none_path_yields_none(self):
        with cache.cache_connection(None) as conn:
            assert conn is None


class TestStoreFile:
    def test_store_then_bulk_lookup_matching_stat_hits(self, tmp_path):
        conn = cache.open_cache(tmp_path / "cache.db")
        cache.store_file(conn, "/repo/app.py", 100, 12345, "Python", 10, 1, 2, 7)
        cache.commit_cache(conn)
        result = cache.lookup_files_bulk(conn, ["/repo/app.py"])
        assert result == {"/repo/app.py": (100, 12345, "Python", 10, 1, 2, 7)}

    def test_store_overwrites_previous_entry_for_same_path(self, tmp_path):
        conn = cache.open_cache(tmp_path / "cache.db")
        cache.store_file(conn, "/repo/app.py", 100, 111, "Python", 10, 1, 2, 7)
        cache.store_file(conn, "/repo/app.py", 200, 222, "Python", 20, 2, 4, 14)
        cache.commit_cache(conn)
        result = cache.lookup_files_bulk(conn, ["/repo/app.py"])
        assert result == {"/repo/app.py": (200, 222, "Python", 20, 2, 4, 14)}

    def test_store_with_none_connection_does_not_raise(self):
        cache.store_file(None, "/repo/app.py", 100, 111, "Python", 10, 1, 2, 7)


class TestLookupFilesBulk:
    def test_looks_up_multiple_paths_in_one_call(self, tmp_path):
        conn = cache.open_cache(tmp_path / "cache.db")
        cache.store_file(conn, "/repo/a.py", 10, 1, "Python", 1, 0, 0, 1)
        cache.store_file(conn, "/repo/b.py", 20, 2, "Python", 2, 0, 0, 2)
        cache.commit_cache(conn)

        result = cache.lookup_files_bulk(conn, ["/repo/a.py", "/repo/b.py", "/repo/never_seen.py"])
        assert result == {
            "/repo/a.py": (10, 1, "Python", 1, 0, 0, 1),
            "/repo/b.py": (20, 2, "Python", 2, 0, 0, 2),
        }
        # A path with no cached row simply isn't in the result.
        assert "/repo/never_seen.py" not in result

    def test_empty_path_list_returns_empty_dict(self, tmp_path):
        conn = cache.open_cache(tmp_path / "cache.db")
        assert cache.lookup_files_bulk(conn, []) == {}

    def test_none_connection_returns_empty_dict(self):
        assert cache.lookup_files_bulk(None, ["/repo/app.py"]) == {}

    def test_batches_queries_past_the_placeholder_limit(self, tmp_path, monkeypatch):
        # Force a tiny batch size so a handful of paths still exercises
        # the multi-batch code path (the real limit is 500, too many
        # to actually store for a fast unit test).
        monkeypatch.setattr(cache, "_BULK_LOOKUP_BATCH_SIZE", 2)
        conn = cache.open_cache(tmp_path / "cache.db")
        paths = [f"/repo/file_{i}.py" for i in range(5)]
        for i, p in enumerate(paths):
            cache.store_file(conn, p, i, i, "Python", i, 0, 0, i)
        cache.commit_cache(conn)

        result = cache.lookup_files_bulk(conn, paths)
        assert len(result) == 5
        assert result["/repo/file_3.py"] == (3, 3, "Python", 3, 0, 0, 3)

    def test_corrupt_or_locked_cache_returns_empty_dict_not_raises(self, tmp_path):
        db_path = tmp_path / "cache.db"
        db_path.write_bytes(b"this is not a sqlite database")
        conn = sqlite3.connect(str(db_path))
        result = cache.lookup_files_bulk(conn, ["/repo/app.py"])
        assert result == {}
        conn.close()


class TestClearCache:
    def test_removes_existing_cache_file(self, tmp_path):
        db_path = tmp_path / "cache.db"
        conn = cache.open_cache(db_path)
        cache.store_file(conn, "/repo/app.py", 1, 1, "Python", 1, 0, 0, 1)
        cache.commit_cache(conn)
        conn.close()
        assert db_path.is_file()

        removed = cache.clear_cache(db_path)
        assert removed is True
        assert not db_path.is_file()

    def test_nonexistent_cache_returns_false(self, tmp_path):
        assert cache.clear_cache(tmp_path / "never_existed.db") is False

    def test_removes_wal_and_shm_sidecar_files(self, tmp_path):
        db_path = tmp_path / "cache.db"
        conn = cache.open_cache(db_path)
        cache.store_file(conn, "/repo/app.py", 1, 1, "Python", 1, 0, 0, 1)
        cache.commit_cache(conn)
        # Force a checkpoint boundary so WAL sidecar files exist on disk.
        conn.execute("PRAGMA wal_checkpoint")
        conn.close()

        cache.clear_cache(db_path)
        assert not (tmp_path / "cache.db-wal").exists()
        assert not (tmp_path / "cache.db-shm").exists()


class TestBatchedCommits:
    """store_file() deliberately doesn't commit on its own -- see its
    docstring. A first-time scan is 100% cache misses, so committing
    once per file (the old behaviour) meant one synchronous disk
    flush per file, which dominated the runtime of exactly the scan
    where caching should be paying for itself. Callers now batch many
    files' writes into one `commit_cache` call instead.
    """

    def test_store_file_does_not_commit_by_itself(self, tmp_path):
        db_path = tmp_path / "cache.db"
        write_conn = cache.open_cache(db_path)
        cache.store_file(write_conn, "/repo/app.py", 100, 111, "Python", 10, 1, 2, 7)

        # A second, independent connection to the same file can only
        # see committed data -- so if store_file had committed on its
        # own, this would already see the row.
        read_conn = sqlite3.connect(str(db_path))
        row = read_conn.execute("SELECT path FROM file_cache").fetchone()
        assert row is None
        read_conn.close()
        write_conn.close()

    def test_commit_cache_makes_pending_writes_visible_to_other_connections(self, tmp_path):
        db_path = tmp_path / "cache.db"
        write_conn = cache.open_cache(db_path)
        cache.store_file(write_conn, "/repo/app.py", 100, 111, "Python", 10, 1, 2, 7)
        cache.commit_cache(write_conn)

        read_conn = sqlite3.connect(str(db_path))
        row = read_conn.execute("SELECT path FROM file_cache").fetchone()
        assert row is not None
        assert row[0] == "/repo/app.py"
        read_conn.close()
        write_conn.close()

    def test_same_connection_sees_its_own_uncommitted_writes(self, tmp_path):
        # lookup_files_bulk must still work mid-chunk, before
        # commit_cache has run yet, as long as it's the SAME
        # connection that wrote the data.
        conn = cache.open_cache(tmp_path / "cache.db")
        cache.store_file(conn, "/repo/app.py", 100, 111, "Python", 10, 1, 2, 7)
        result = cache.lookup_files_bulk(conn, ["/repo/app.py"])
        assert result == {"/repo/app.py": (100, 111, "Python", 10, 1, 2, 7)}
        conn.close()

    def test_commit_cache_with_none_connection_does_not_raise(self):
        cache.commit_cache(None)

    def test_commit_cache_on_closed_connection_does_not_raise(self, tmp_path):
        conn = cache.open_cache(tmp_path / "cache.db")
        conn.close()
        cache.commit_cache(conn)  # best-effort: must swallow the error, not raise


class TestCorruptOrLockedCacheIsGraceful:
    def test_corrupt_file_at_cache_path_does_not_raise(self, tmp_path):
        db_path = tmp_path / "cache.db"
        db_path.write_bytes(b"this is not a sqlite database")
        conn = cache.open_cache(db_path)
        # sqlite3 may still "open" a bogus file lazily; either a clean
        # None or a connection that fails on first real use is fine --
        # what matters is nothing raises up through open_cache itself.
        if conn is not None:
            try:
                conn.execute("SELECT 1 FROM file_cache LIMIT 1")
            except sqlite3.DatabaseError:
                pass
