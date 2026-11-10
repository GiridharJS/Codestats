import json
import os
from pathlib import Path

import pytest

from src.cli import DEFAULT_PDF_FILENAME, build_parser, run


@pytest.fixture
def sample_repo(tmp_path):
    """A small synthetic (non-git) repo covering all 7 supported
    languages, with a nested subdirectory to confirm recursive scan.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Main.java").write_text(
        "// entry point\npublic class Main {\n    public static void main(String[] a) {}\n}\n"
    )
    (tmp_path / "src" / "nested").mkdir()
    (tmp_path / "src" / "nested" / "util.py").write_text(
        "# util\ndef add(a, b):\n    return a + b\n"
    )
    (tmp_path / "server.go").write_text("package main\n\nfunc main() {}\n")
    (tmp_path / "app.rb").write_text("# app\nputs 'hi'\n")
    (tmp_path / "lib.rs").write_text("// lib\nfn main() {}\n")
    (tmp_path / "core.c").write_text("int main() { return 0; }\n")
    (tmp_path / "engine.cpp").write_text("// engine\nint main() { return 0; }\n")
    (tmp_path / "README.md").write_text("# not a supported language\n")  # should be ignored
    return tmp_path


class TestBuildParser:
    def test_defaults(self):
        args = build_parser().parse_args([])
        assert args.path == "."
        assert args.exclude == []
        assert args.git is False
        assert args.sort_by == "code"
        assert args.json is False
        assert args.pdf is None  # no PDF unless --pdf is explicitly passed
        assert args.runtime is False  # no runtime detection unless --runtime is explicitly passed

    def test_custom_args(self):
        args = build_parser().parse_args(
            ["some/path", "--exclude", "*.md", "--git", "--sort-by", "lines",
             "--json", "--pdf", "out.pdf"]
        )
        assert args.path == "some/path"
        assert args.exclude == ["*.md"]
        assert args.git is True
        assert args.sort_by == "lines"
        assert args.json is True
        assert args.pdf == "out.pdf"

    def test_pdf_flag_present_when_passed(self):
        args = build_parser().parse_args(["--pdf"])
        assert args.pdf == DEFAULT_PDF_FILENAME

    def test_pdf_absent_by_default(self):
        args = build_parser().parse_args([])
        assert args.pdf is None

    def test_exclude_can_be_repeated(self):
        args = build_parser().parse_args(["--exclude", "*.md", "--exclude", "tests/*"])
        assert args.exclude == ["*.md", "tests/*"]


class TestRunTableOutput:
    def test_run_prints_table_with_supported_languages(self, sample_repo, capsys):
        exit_code = run([str(sample_repo)])
        captured = capsys.readouterr()

        assert exit_code == 0
        for lang in ["Java", "Python", "Go", "Ruby", "Rust", "C", "C++"]:
            assert lang in captured.out
        # README.md is now counted too, since Markdown is part of the
        # expanded language set (previously excluded when scope was 7).
        assert "Markdown" in captured.out
        assert "Total" in captured.out

    def test_run_recurses_into_nested_subdirectories(self, sample_repo, capsys):
        run([str(sample_repo)])
        captured = capsys.readouterr()
        # util.py lives in src/nested/ -- confirms recursive scanning
        assert "Python" in captured.out

    def test_run_respects_exclude_pattern(self, sample_repo, capsys):
        run([str(sample_repo), "--exclude", "src/*"])
        captured = capsys.readouterr()
        assert "Java" not in captured.out
        assert "Go" in captured.out  # server.go is outside src/, still counted

    def test_run_no_bar_suppresses_bar(self, sample_repo, capsys):
        run([str(sample_repo), "--no-bar"])
        captured = capsys.readouterr()
        assert "[" not in captured.out.split("Total")[-1]


class TestRunJsonOutput:
    def test_json_output_is_valid_and_complete(self, sample_repo, capsys):
        exit_code = run([str(sample_repo), "--json"])
        captured = capsys.readouterr()

        assert exit_code == 0
        payload = json.loads(captured.out)

        assert "summary" in payload
        assert "percentages" in payload
        assert "totals" in payload
        assert "Java" in payload["summary"]
        assert "JavaScript" not in payload["summary"]

    def test_json_percentages_sum_to_100(self, sample_repo, capsys):
        run([str(sample_repo), "--json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        total_pct = sum(payload["percentages"].values())
        assert round(total_pct, 5) == 100.0


class TestRunEmptyRepo:
    def test_empty_directory_reports_no_files(self, tmp_path, capsys):
        exit_code = run([str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No recognised source files found." in captured.out


class TestRunPathValidation:
    def test_nonexistent_path_returns_error_exit_code(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        exit_code = run([str(missing)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "does not exist" in captured.err

    def test_file_instead_of_directory_returns_error(self, tmp_path, capsys):
        f = tmp_path / "notadir.py"
        f.write_text("x = 1\n")
        exit_code = run([str(f)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "not a directory" in captured.err.lower()


class TestRunPdfGeneration:
    def test_no_pdf_by_default(self, sample_repo, capsys, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        exit_code = run([str(sample_repo)])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert not (tmp_path / "codestats_report.pdf").exists()
        assert "PDF report written to" not in captured.err

    def test_pdf_flag_generates_pdf(self, sample_repo, capsys, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        run([str(sample_repo), "--pdf"])
        pdf_path = tmp_path / "codestats_report.pdf"
        assert pdf_path.exists()
        assert "PDF report written to" in capsys.readouterr().err

    def test_custom_pdf_path(self, sample_repo, capsys, tmp_path):
        custom = tmp_path / "custom_name.pdf"
        run([str(sample_repo), "--pdf", str(custom)])
        assert custom.exists()


class TestGitFlag:
    def test_gitignore_respected_even_without_git_flag(self, tmp_path, capsys):
        # The manual (non-git) walker now parses .gitignore content
        # directly, so a gitignored file is excluded regardless of
        # whether --git is passed. --git only changes HOW discovery
        # happens (git ls-files vs manual walk); both paths now
        # respect .gitignore.
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
        (tmp_path / "tracked.py").write_text("x = 1\n")
        (tmp_path / "ignored.py").write_text("y = 2\n")
        (tmp_path / ".gitignore").write_text("ignored.py\n")
        subprocess.run(["git", "add", "tracked.py", ".gitignore"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        run([str(tmp_path), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["Python"]["files"] == 1  # ignored.py excluded

    def test_git_flag_respects_gitignore(self, tmp_path, capsys):
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
        (tmp_path / "tracked.py").write_text("x = 1\n")
        (tmp_path / "ignored.py").write_text("y = 2\n")
        (tmp_path / ".gitignore").write_text("ignored.py\n")
        subprocess.run(["git", "add", "tracked.py", ".gitignore"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        run([str(tmp_path), "--git", "--json"])
        payload = json.loads(capsys.readouterr().out)
        # only the tracked file counted -- ignored.py excluded via .gitignore
        assert payload["summary"]["Python"]["files"] == 1


class TestSkippedFilesReporting:
    def test_skipped_table_shown_with_filewise_flag(self, sample_repo, capsys):
        (sample_repo / "data.bin").write_bytes(b"\x00\x01binary")
        run([str(sample_repo), "--filewise"])
        out = capsys.readouterr().out
        assert "Skipped Files" in out
        assert "data.bin" in out
        assert "Total skipped:" in out

    def test_skipped_included_in_json_with_filewise_flag(self, sample_repo, capsys):
        (sample_repo / "data.bin").write_bytes(b"\x00\x01binary")
        run([str(sample_repo), "--json", "--filewise"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["skipped_count"] >= 1
        assert any(item["path"].endswith("data.bin") for item in payload["skipped"])

    def test_no_skipped_files_message_with_filewise_flag(self, tmp_path, capsys):
        (tmp_path / "main.py").write_text("x = 1\n")
        run([str(tmp_path), "--filewise"])
        out = capsys.readouterr().out
        assert "Skipped files: 0" in out


class TestFilewiseFlagDefault:
    def test_default_omits_per_file_tables_from_terminal(self, sample_repo, capsys):
        (sample_repo / "data.bin").write_bytes(b"\x00\x01binary")
        run([str(sample_repo)])  # no --filewise
        out = capsys.readouterr().out
        assert "Validated Files" not in out
        assert "Skipped Files" not in out
        assert "Total" in out  # summary table still present

    def test_default_omits_files_and_skipped_keys_from_json(self, sample_repo, capsys):
        (sample_repo / "data.bin").write_bytes(b"\x00\x01binary")
        run([str(sample_repo), "--json"])  # no --filewise
        payload = json.loads(capsys.readouterr().out)
        assert "files" not in payload
        assert "skipped" not in payload
        assert "skipped_count" not in payload
        assert "summary" in payload  # aggregated data still present

    def test_filewise_flag_defaults_to_false(self):
        args = build_parser().parse_args([])
        assert args.filewise is False

    def test_summary_identical_with_and_without_filewise(self, sample_repo, capsys):
        # --filewise and its absence go through genuinely different
        # code paths internally (per-file vs chunk-aggregated), so
        # this is an end-to-end guard that they never disagree.
        run([str(sample_repo), "--json"])
        without = json.loads(capsys.readouterr().out)
        run([str(sample_repo), "--json", "--filewise"])
        with_filewise = json.loads(capsys.readouterr().out)
        assert without["summary"] == with_filewise["summary"]
        assert without["totals"] == with_filewise["totals"]


class TestTiming:
    def test_timing_flag_no_longer_exists(self):
        # --timing used to be opt-in; the breakdown is now basic,
        # always-on output (same reasoning as --cache before it).
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--timing"])

    def test_timing_breakdown_always_appears_in_table_output(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        run([str(tmp_path)])
        out = capsys.readouterr().out
        assert "Timing Breakdown" in out
        assert "File discovery:" in out
        assert "Processing:" in out

    def test_timing_object_always_appears_in_json(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        run([str(tmp_path), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert "timing" in payload
        assert payload["timing"]["files_found"] == 2
        assert payload["timing"]["discovery_seconds"] >= 0
        assert payload["timing"]["processing_seconds"] >= 0

    def test_workers_used_appears_in_timing_breakdown_table(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        run([str(tmp_path)])
        out = capsys.readouterr().out
        assert "Workers used:" in out

    def test_workers_used_appears_in_timing_json_and_is_at_least_one(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        run([str(tmp_path), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["timing"]["workers_used"] >= 1

    def test_workers_used_is_one_for_a_small_repo(self, tmp_path, capsys):
        # Well under MIN_FILES_FOR_PARALLEL -- auto-detection should
        # run this sequentially, and report exactly that.
        (tmp_path / "app.py").write_text("x = 1\n")
        run([str(tmp_path), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["timing"]["workers_used"] == 1

    def test_workers_used_reflects_an_explicit_internal_override(self, sample_repo, capsys, monkeypatch):
        # _detect_worker_capacity might report more than 1 on this
        # machine, but forcing it down should be reflected exactly in
        # what gets reported -- confirms this is the REAL worker count
        # used, not just a repeat of whatever auto-detection alone
        # would have said.
        from src import cli as cli_module

        original = cli_module._process_files_parallel_cached

        def force_two_workers(files, workers=None, cache_db_path=None, filewise=False):
            return original(files, workers=2, cache_db_path=cache_db_path, filewise=filewise)

        monkeypatch.setattr(cli_module, "_process_files_parallel_cached", force_two_workers)
        run([str(sample_repo), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["timing"]["workers_used"] == 2


class TestCacheFlag:
    def test_cache_flag_no_longer_exists_caching_is_always_on(self):
        # Caching used to be opt-in via --cache; it's now basic,
        # always-on behavior -- there's no flag to turn it off.
        # --cache-file and --cache-clear remain as before.
        args = build_parser().parse_args([])
        assert not hasattr(args, "cache")
        assert args.cache_file is None
        assert args.cache_clear is False
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--cache"])

    def test_a_plain_run_with_no_flags_still_populates_the_cache(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        payload = json.loads(capsys.readouterr().out)
        assert payload["cache"]["cache_misses"] == 1
        assert db.is_file()

    def test_first_run_is_all_misses(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        payload = json.loads(capsys.readouterr().out)
        assert payload["cache"]["cache_hits"] == 0
        assert payload["cache"]["cache_misses"] == 1
        assert db.is_file()

    def test_second_run_on_unchanged_repo_is_all_hits(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        capsys.readouterr()

        run([str(tmp_path), "--json", "--cache-file", str(db)])
        payload = json.loads(capsys.readouterr().out)
        assert payload["cache"]["cache_hits"] == 1
        assert payload["cache"]["cache_misses"] == 0

    def test_modifying_a_file_causes_a_miss_on_the_next_scan(self, tmp_path, capsys):
        f = tmp_path / "app.py"
        f.write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        capsys.readouterr()

        f.write_text("x = 1\ny = 2\n")
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        second = json.loads(capsys.readouterr().out)

        assert second["cache"]["cache_hits"] == 0
        assert second["cache"]["cache_misses"] == 1
        assert second["totals"]["lines"] == 2

    def test_summary_matches_between_default_and_explicit_cache_file(self, tmp_path, capsys):
        # Both runs are cached now (there's no "uncached" mode any
        # more) -- this just confirms the auto-generated default
        # cache location and an explicit --cache-file produce the
        # same scan results, since each is a fresh, all-misses cache.
        (tmp_path / "app.py").write_text("# comment\nx = 1\n")
        (tmp_path / "main.go").write_text("package main\n")

        run([str(tmp_path), "--json"])
        default_location = json.loads(capsys.readouterr().out)

        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        explicit_location = json.loads(capsys.readouterr().out)

        assert default_location["summary"] == explicit_location["summary"]
        assert default_location["totals"] == explicit_location["totals"]

    def test_first_time_scan_batches_commits_instead_of_one_per_file(self, tmp_path, capsys, monkeypatch):
        # The whole point of batching: a first-time --cache scan is
        # 100% misses, so it must NOT call commit_cache once per file
        # -- that was the actual bottleneck this change fixes. With
        # workers=1 there's exactly one chunk, so exactly one commit
        # (plus the separate end-of-run root-hash commit) is correct.
        from src import cache as cache_module

        for i in range(25):
            (tmp_path / f"file_{i}.py").write_text(f"x = {i}\n")
        db = tmp_path / "cache.db"

        calls = []
        original_commit = cache_module.commit_cache

        def counting_commit(conn):
            calls.append(1)
            return original_commit(conn)

        monkeypatch.setattr(cache_module, "commit_cache", counting_commit)
        # No worker override needed: 25 files is well under
        # MIN_FILES_FOR_PARALLEL, so auto-detection already runs this
        # sequentially as a single chunk.
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        payload = json.loads(capsys.readouterr().out)

        assert payload["cache"]["cache_misses"] == 25
        # One commit for the (single) chunk's file writes -- NOT 25
        # (one per file, the old per-store_file behaviour). There's
        # no longer a second commit for dir-hashes/root-hash on top
        # of that (that bookkeeping no longer exists at all -- see
        # cache.py's module docstring).
        assert len(calls) == 1

    def test_cache_clear_forces_full_rescan(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--cache-file", str(db)])
        capsys.readouterr()

        run([str(tmp_path), "--json", "--cache-file", str(db), "--cache-clear"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["cache"]["cache_hits"] == 0
        assert payload["cache"]["cache_misses"] == 1

    def test_table_output_includes_cache_summary_section(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--cache-file", str(db)])
        out = capsys.readouterr().out
        assert "Cache Summary" in out
        assert "Files reused:" in out

    def test_works_with_filewise_combined(self, tmp_path, capsys):
        (tmp_path / "app.py").write_text("x = 1\n")
        db = tmp_path / "cache.db"
        run([str(tmp_path), "--json", "--filewise", "--cache-file", str(db)])
        payload = json.loads(capsys.readouterr().out)
        assert payload["cache"]["cache_misses"] == 1
        assert len(payload["files"]) == 1

        run([str(tmp_path), "--json", "--filewise", "--cache-file", str(db)])
        payload2 = json.loads(capsys.readouterr().out)
        assert payload2["cache"]["cache_hits"] == 1
        assert payload2["files"] == payload["files"]

    def test_default_cache_used_when_not_specified_lives_in_temp_dir(self, tmp_path, capsys, monkeypatch):
        # The default cache file now lives in the OS temp directory
        # (not inside the scanned repo -- nothing should be written
        # into the repo itself unless --cache-file says so), keyed by
        # a hash of the repo's own resolved path so different repos
        # still can't collide with each other.
        import tempfile

        from src import config

        monkeypatch.chdir(tmp_path.parent)  # CWD is deliberately NOT the scanned repo
        (tmp_path / "app.py").write_text("x = 1\n")
        run([str(tmp_path), "--json"])
        payload = json.loads(capsys.readouterr().out)

        expected = config.default_cache_path(str(tmp_path))
        assert payload["cache"]["cache_file"] == expected
        assert Path(expected).is_file()
        assert Path(expected).parent == Path(tempfile.gettempdir())
        # Nothing gets left behind inside the scanned repo.
        assert not (tmp_path / ".codestats_cache.db").exists()
        assert list(tmp_path.iterdir()) == [tmp_path / "app.py"]

    def test_default_cache_path_is_stable_across_runs_for_the_same_repo(self, tmp_path, capsys):
        # It has to be deterministic, not a fresh random temp name
        # each time -- otherwise --cache would never actually reuse
        # anything on a second run.
        (tmp_path / "app.py").write_text("x = 1\n")
        run([str(tmp_path), "--json"])
        first = json.loads(capsys.readouterr().out)
        run([str(tmp_path), "--json"])
        second = json.loads(capsys.readouterr().out)

        assert first["cache"]["cache_file"] == second["cache"]["cache_file"]
        assert second["cache"]["cache_hits"] == 1

    def test_two_different_repos_do_not_share_a_default_cache(self, tmp_path, capsys):
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "app.py").write_text("x = 1\n")
        repo_b = tmp_path / "repo_b"
        repo_b.mkdir()
        (repo_b / "app.py").write_text("y = 2\n")

        run([str(repo_a), "--json"])
        json.loads(capsys.readouterr().out)
        run([str(repo_b), "--json"])
        payload_b = json.loads(capsys.readouterr().out)

        # repo_b's first-ever scan must be a miss, not a false hit
        # borrowed from repo_a's cache.
        assert payload_b["cache"]["cache_misses"] == 1
        assert payload_b["cache"]["cache_hits"] == 0


class TestExecutionTiming:
    def test_json_includes_elapsed_seconds(self, sample_repo, capsys):
        run([str(sample_repo), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert "elapsed_seconds" in payload
        assert isinstance(payload["elapsed_seconds"], (int, float))
        assert payload["elapsed_seconds"] >= 0

    def test_table_output_shows_time_taken(self, sample_repo, capsys):
        run([str(sample_repo)])
        out = capsys.readouterr().out
        assert "Time taken:" in out

    def test_format_elapsed_sub_second_uses_milliseconds(self):
        from src.cli import _format_elapsed
        assert _format_elapsed(0.0021) == "2ms"

    def test_format_elapsed_seconds(self):
        from src.cli import _format_elapsed
        assert _format_elapsed(9.21) == "9.21s"

    def test_format_elapsed_minutes(self):
        from src.cli import _format_elapsed
        assert _format_elapsed(125.4) == "2m 5.4s"




class TestParallelProcessing:
    def test_workers_flag_no_longer_exists(self):
        # --workers used to be a manual override; it's been removed --
        # worker count is always auto-detected from this machine's
        # CPU affinity and available memory, the same way on every
        # run, with no per-machine tuning needed or possible.
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--workers", "4"])

    def test_run_always_passes_workers_none_letting_auto_detection_decide(self, sample_repo, monkeypatch):
        # run() itself should never hardcode or forward a worker
        # count -- it must always be None at this call site, so
        # _process_files_parallel_cached's own auto-detection is what
        # decides, every time.
        from src import cli as cli_module

        seen = {}
        original = cli_module._process_files_parallel_cached

        def spy(files, workers=None, cache_db_path=None, filewise=False):
            seen["workers"] = workers
            return original(files, workers=workers, cache_db_path=cache_db_path, filewise=filewise)

        monkeypatch.setattr(cli_module, "_process_files_parallel_cached", spy)
        run([str(sample_repo)])
        assert seen["workers"] is None

    def test_empty_file_list_reports_zero_workers_used(self, tmp_path):
        from src.cli import _process_files_parallel_cached

        result, skipped, hits, misses, workers_used = _process_files_parallel_cached([], cache_db_path=str(tmp_path / "cache.db"))
        assert result == {}
        assert workers_used == 0

    def test_workers_used_is_clamped_to_file_count(self, tmp_path):
        # Asking for more workers than there are files to hand out is
        # clamped down -- workers_used must reflect the clamped
        # number actually used, not the raw request.
        from src.cli import _process_files_parallel_cached

        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        files = [tmp_path / "a.py", tmp_path / "b.py"]

        result, skipped, hits, misses, workers_used = _process_files_parallel_cached(
            files, workers=8, cache_db_path=str(tmp_path / "cache.db"),
        )
        assert workers_used == 2  # clamped to len(files), not 8

    def test_workers_used_matches_an_explicit_request_within_bounds(self, tmp_path):
        from src.cli import _process_files_parallel_cached

        files = []
        for i in range(10):
            f = tmp_path / f"f{i}.py"
            f.write_text("x = 1\n")
            files.append(f)

        result, skipped, hits, misses, workers_used = _process_files_parallel_cached(
            files, workers=3, cache_db_path=str(tmp_path / "cache.db"),
        )
        assert workers_used == 3

    def test_process_files_parallel_cached_returns_a_5_tuple(self, tmp_path):
        from src.cli import _process_files_parallel_cached

        (tmp_path / "app.py").write_text("x = 1\n")
        result = _process_files_parallel_cached([tmp_path / "app.py"], workers=1)
        assert len(result) == 5
        summary, skipped, hits, misses, workers_used = result
        assert workers_used == 1

    def test_process_files_parallel_cached_empty_files_reports_zero_workers(self):
        from src.cli import _process_files_parallel_cached

        summary, skipped, hits, misses, workers_used = _process_files_parallel_cached([])
        assert workers_used == 0

    def test_process_files_parallel_cached_clamps_workers_to_file_count(self, tmp_path):
        # Asking for more workers than there are files should clamp
        # down, and the reported workers_used should reflect the
        # clamped (real) value, not the requested one.
        from src.cli import _process_files_parallel_cached

        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        files = [tmp_path / "a.py", tmp_path / "b.py"]
        _, _, _, _, workers_used = _process_files_parallel_cached(files, workers=50)
        assert workers_used == 2

    def test_worker_capacity_is_resource_based_and_at_least_one(self):
        from src.cli import _detect_worker_capacity
        capacity = _detect_worker_capacity()
        assert isinstance(capacity, int)
        assert capacity >= 1

    def test_worker_capacity_respects_cpu_affinity_over_cpu_count(self, monkeypatch):
        # Regression test for over-subscription inside containers/CI:
        # os.cpu_count() reports the HOST's full logical CPU count,
        # which can be much higher than what a cgroup/taskset actually
        # allows this process to use. sched_getaffinity reflects the
        # real restriction and must win when both are available.
        import os as os_module

        from src import cli as cli_module

        monkeypatch.setattr(os_module, "sched_getaffinity", lambda pid: set(range(2)), raising=False)
        monkeypatch.setattr(os_module, "cpu_count", lambda: 32)
        capacity = cli_module._detect_worker_capacity()
        assert capacity <= 2  # never above the affinity-restricted count

    def test_worker_capacity_falls_back_to_cpu_count_without_affinity_api(self, monkeypatch):
        # Windows/macOS: os.sched_getaffinity doesn't exist at all.
        import os as os_module

        from src import cli as cli_module

        monkeypatch.delattr(os_module, "sched_getaffinity", raising=False)
        monkeypatch.setattr(os_module, "cpu_count", lambda: 4)
        capacity = cli_module._detect_worker_capacity()
        assert capacity <= 4
        assert capacity >= 1

    def test_repeated_runs_produce_identical_results(self, sample_repo, capsys):
        # Auto-sized worker counts must never change the actual
        # counted results, run to run.
        run([str(sample_repo), "--json"])
        payload_1 = json.loads(capsys.readouterr().out)
        run([str(sample_repo), "--json"])
        payload_2 = json.loads(capsys.readouterr().out)
        assert payload_1["summary"] == payload_2["summary"]
        assert payload_1["totals"] == payload_2["totals"]

    def test_small_file_count_skips_pool_spawn_by_default(self, monkeypatch):
        # Below MIN_FILES_FOR_PARALLEL, spawning a process pool costs
        # more than it could ever save (especially on Windows, which
        # can't fork and must restart a full interpreter per worker)
        # -- auto-sizing should force sequential (workers=1) even if
        # the machine reports many CPUs.
        from src import cli as cli_module

        monkeypatch.setattr(cli_module, "_detect_worker_capacity", lambda: 8)
        files = [f"file_{i}.py" for i in range(10)]
        calls = []

        def fake_process_one(f):
            calls.append(f)
            return ("skipped", (f, None, "unsupported file type"))

        monkeypatch.setattr(cli_module, "_process_one_file", fake_process_one)
        cli_module._process_files_parallel(files)  # workers=None -> auto-sized
        assert len(calls) == len(files)  # sequential path still processes everything

    def test_explicit_workers_override_bypasses_the_threshold(self, sample_repo):
        # The threshold only applies to auto-sizing (workers=None);
        # an explicit override (as tests use to force real parallel
        # execution against small fixtures) is respected as-is.
        from src.cli import _process_files_parallel
        from src.walker import get_files

        files = get_files(str(sample_repo), use_git=False)
        # Just confirm this doesn't raise and returns sane results --
        # the actual worker count used isn't independently observable
        # from here, but this path must still work correctly.
        stats, skipped = _process_files_parallel(files, workers=4)
        assert len(stats) + len(skipped) == len(files)

    def test_aggregated_path_matches_per_file_path(self, sample_repo):
        # The chunk-aggregated fast path (used when --filewise isn't
        # requested) must produce byte-identical totals to the
        # original per-file path, just via fewer/larger IPC messages.
        from src.cli import _process_files_parallel, _process_files_parallel_aggregated
        from src.report import aggregate
        from src.walker import get_files

        files = get_files(str(sample_repo), use_git=False)

        file_stats, skipped_old = _process_files_parallel(files, workers=4)
        summary_old = aggregate(file_stats)

        summary_new, skipped_new = _process_files_parallel_aggregated(files, workers=4)

        assert summary_new == summary_old
        assert set(skipped_new) == set(skipped_old)

    def test_aggregated_path_single_worker(self, sample_repo):
        from src.cli import _process_files_parallel_aggregated
        from src.walker import get_files

        files = get_files(str(sample_repo), use_git=False)
        summary, skipped = _process_files_parallel_aggregated(files, workers=1)
        assert sum(v["files"] for v in summary.values()) + len(skipped) == len(files)

    def test_aggregated_path_empty_file_list(self):
        from src.cli import _process_files_parallel_aggregated
        assert _process_files_parallel_aggregated([]) == ({}, [])

    def test_process_chunk_aggregates_a_batch_correctly(self, tmp_path):
        from src.cli import _process_chunk

        (tmp_path / "a.py").write_text("# c\nx = 1\n")
        (tmp_path / "b.py").write_text("y = 2\nz = 3\n")
        (tmp_path / "c.go").write_text("package main\n")

        files = [tmp_path / "a.py", tmp_path / "b.py", tmp_path / "c.go"]
        summary, skipped = _process_chunk(files)

        assert summary["Python"]["files"] == 2
        assert summary["Python"]["code"] == 3  # x=1, y=2, z=3
        assert summary["Python"]["comment"] == 1
        assert summary["Go"]["files"] == 1
        assert skipped == []

    def test_process_chunk_tracks_skipped_files(self, tmp_path):
        from src.cli import _process_chunk

        f = tmp_path / "weird.xyz123unknown"
        f.write_text("hello\n")
        summary, skipped = _process_chunk([f])
        assert summary == {}
        assert len(skipped) == 1
        assert skipped[0][2] == "unsupported file type"

    def test_merge_partial_summaries_sums_correctly(self):
        from src.cli import _merge_partial_summaries

        a = {"Python": {"files": 2, "lines": 10, "blank": 1, "comment": 2, "code": 7}}
        b = {"Python": {"files": 1, "lines": 5, "blank": 0, "comment": 1, "code": 4},
             "Go": {"files": 3, "lines": 30, "blank": 5, "comment": 5, "code": 20}}

        merged = _merge_partial_summaries([a, b])

        assert merged["Python"] == {"files": 3, "lines": 15, "blank": 1, "comment": 3, "code": 11}
        assert merged["Go"] == {"files": 3, "lines": 30, "blank": 5, "comment": 5, "code": 20}

    def test_merge_partial_summaries_empty_list(self):
        from src.cli import _merge_partial_summaries
        assert _merge_partial_summaries([]) == {}

    def test_process_files_parallel_matches_sequential_result(self, sample_repo):
        from src.cli import _process_files_parallel, _process_one_file
        from src.walker import get_files

        files = get_files(str(sample_repo), use_git=False)

        sequential = [_process_one_file(f) for f in files]
        parallel_stats, parallel_skipped = _process_files_parallel(files, workers=4)

        seq_stats = [r for kind, r in sequential if kind == "counted"]
        for kind, r in sequential:
            if kind == "counted_multi":
                seq_stats.extend(r)  # Markdown files expand into multiple FileStats
        seq_skipped = [r for kind, r in sequential if kind == "skipped"]

        assert len(parallel_stats) == len(seq_stats)
        assert len(parallel_skipped) == len(seq_skipped)
        assert {fs.path for fs in parallel_stats} == {fs.path for fs in seq_stats}

    def test_empty_file_list_returns_empty_results(self):
        from src.cli import _process_files_parallel
        stats, skipped = _process_files_parallel([])
        assert stats == []
        assert skipped == []


class TestProjectRoots:
    def test_projects_flag_default_is_false(self):
        args = build_parser().parse_args([])
        assert args.projects is False

    def test_finds_multiple_sub_projects_with_different_runtimes(self, tmp_path, capsys):
        api = tmp_path / "services" / "api"
        api.mkdir(parents=True)
        (api / "pom.xml").write_text(
            "<project><properties><maven.compiler.release>17</maven.compiler.release></properties></project>"
        )
        (api / "Api.java").write_text("class Api {}\n")

        legacy = tmp_path / "services" / "legacy"
        legacy.mkdir(parents=True)
        (legacy / "build.gradle").write_text("sourceCompatibility = '1.8'\n")
        (legacy / "Legacy.java").write_text("class Legacy {}\n")

        run([str(tmp_path), "--json", "--projects"])
        payload = json.loads(capsys.readouterr().out)
        roots = {p["root"]: p["languages"] for p in payload["project_roots"]}

        assert roots["services/api"]["Java"] == "Java 17 (declared in pom.xml)"
        assert roots["services/legacy"]["Java"] == "Java 1.8 (declared in build.gradle)"

    def test_does_not_report_kotlin_for_pure_java_gradle_project(self, tmp_path, capsys):
        # Regression test: Kotlin and Java share the same Gradle/Maven
        # manifest filenames, so a naive implementation would flag
        # every Java project as ALSO being a spurious Kotlin project
        # with "no version specified". Cross-referencing against the
        # scan's actually-detected languages must prevent that.
        proj = tmp_path / "app"
        proj.mkdir()
        (proj / "build.gradle").write_text("sourceCompatibility = '17'\n")
        (proj / "App.java").write_text("class App {}\n")

        run([str(tmp_path), "--json", "--projects"])
        payload = json.loads(capsys.readouterr().out)
        roots = {p["root"]: p["languages"] for p in payload["project_roots"]}

        assert "Kotlin" not in roots.get("app", {})
        assert "Java" in roots.get("app", {})

    def test_table_output_shows_project_roots_section(self, tmp_path, capsys):
        (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.21\n")
        (tmp_path / "main.go").write_text("package main\n")
        run([str(tmp_path), "--projects"])
        out = capsys.readouterr().out
        assert "Detected Project Roots" in out
        assert "go.mod" in out

    def test_no_projects_flag_omits_section(self, sample_repo, capsys):
        run([str(sample_repo)])
        out = capsys.readouterr().out
        assert "Detected Project Roots" not in out

    def test_empty_repo_with_no_manifests(self, tmp_path, capsys):
        (tmp_path / "readme.txt").write_text("hello\n")
        run([str(tmp_path), "--json", "--projects"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["project_roots"] == []

    def test_table_shows_truncation_notice_when_capped(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("CODESTATS_MAX_PROJECTS_DISPLAYED", "1")
        for i in range(3):
            d = tmp_path / f"service-{i}"
            d.mkdir()
            (d / "go.mod").write_text(f"module service{i}\n\ngo 1.2{i}\n")
            (d / "main.go").write_text("package main\n")
        run([str(tmp_path), "--projects"])
        out = capsys.readouterr().out
        assert "Showing 1 of 3 projects found" in out

    def test_json_includes_total_project_roots_found_when_capped(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("CODESTATS_MAX_PROJECTS_DISPLAYED", "1")
        for i in range(3):
            d = tmp_path / f"service-{i}"
            d.mkdir()
            (d / "go.mod").write_text(f"module service{i}\n\ngo 1.2{i}\n")
            (d / "main.go").write_text("package main\n")
        run([str(tmp_path), "--json", "--projects"])
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["project_roots"]) == 1
        assert payload["total_project_roots_found"] == 3


class TestRuntimeColumn:
    def test_runtime_column_hidden_by_default(self, sample_repo, capsys):
        run([str(sample_repo)])
        out = capsys.readouterr().out
        assert "Runtime" not in out

    def test_runtime_flag_shows_column(self, sample_repo, capsys):
        run([str(sample_repo), "--runtime"])
        out = capsys.readouterr().out
        assert "Runtime" in out

    def test_runtime_omitted_from_json_by_default(self, sample_repo, capsys):
        run([str(sample_repo), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert "runtimes" not in payload

    def test_runtime_flag_includes_in_json(self, sample_repo, capsys):
        run([str(sample_repo), "--json", "--runtime"])
        payload = json.loads(capsys.readouterr().out)
        assert "runtimes" in payload
        assert "Python" in payload["runtimes"]

    def test_runtime_flag_default_is_false(self):
        args = build_parser().parse_args([])
        assert args.runtime is False

    def test_runtime_reads_declared_version_from_manifest(self, sample_repo, capsys):
        # Runtime info now comes from the scanned project's own
        # manifest file, not whatever happens to be installed on the
        # machine running codestats.
        (sample_repo / "pyproject.toml").write_text(
            '[project]\nrequires-python = ">=3.11"\n'
        )
        run([str(sample_repo), "--json", "--runtime"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["runtimes"]["Python"] == "Python >=3.11 (declared in pyproject.toml)"

    def test_runtime_none_when_no_manifest_declares_it(self, sample_repo, capsys):
        run([str(sample_repo), "--json", "--runtime"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["runtimes"]["Python"] is None


class TestAwsSdkColumn:
    def test_aws_sdk_column_hidden_by_default(self, sample_repo, capsys):
        run([str(sample_repo)])
        out = capsys.readouterr().out
        assert "AWS SDK" not in out

    def test_aws_sdk_flag_shows_column(self, sample_repo, capsys):
        run([str(sample_repo), "--aws-sdk"])
        out = capsys.readouterr().out
        assert "AWS SDK" in out
        assert "Manifest" in out

    def test_aws_sdk_omitted_from_json_by_default(self, sample_repo, capsys):
        run([str(sample_repo), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert "aws_sdk" not in payload

    def test_aws_sdk_flag_includes_in_json(self, sample_repo, capsys):
        run([str(sample_repo), "--json", "--aws-sdk"])
        payload = json.loads(capsys.readouterr().out)
        assert "aws_sdk" in payload
        assert "Python" in payload["aws_sdk"]

    def test_aws_sdk_flag_default_is_false(self):
        args = build_parser().parse_args([])
        assert args.aws_sdk is False

    def test_aws_sdk_reads_declared_dependency_from_manifest(self, sample_repo, capsys):
        (sample_repo / "requirements.txt").write_text("boto3==1.34.100\n")
        run([str(sample_repo), "--json", "--aws-sdk"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["aws_sdk"]["Python"] == {"sdk": "boto3 1.34.100", "manifest": "requirements.txt"}

    def test_aws_sdk_column_and_manifest_column_appear_in_table(self, sample_repo, capsys):
        (sample_repo / "requirements.txt").write_text("boto3==1.34.100\n")
        run([str(sample_repo), "--aws-sdk"])
        out = capsys.readouterr().out
        assert "boto3 1.34.100" in out
        assert "requirements.txt" in out
        # The old combined "(declared in ...)" wording should be gone
        # now that the manifest path has its own column.
        assert "declared in" not in out

    def test_aws_sdk_none_when_no_manifest_declares_it(self, sample_repo, capsys):
        run([str(sample_repo), "--json", "--aws-sdk"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["aws_sdk"]["Python"] is None

    def test_aws_sdk_and_runtime_columns_can_appear_together(self, sample_repo, capsys):
        (sample_repo / "requirements.txt").write_text("boto3==1.34.100\n")
        run([str(sample_repo), "--runtime", "--aws-sdk"])
        out = capsys.readouterr().out
        assert "Runtime" in out
        assert "AWS SDK" in out

    def test_aws_sdk_detection_does_not_add_a_separate_scan_pass(self, sample_repo, capsys, monkeypatch):
        # Detection must come from manifest files already read for
        # --runtime-style detection, not from re-walking or
        # re-reading every source file -- confirm the processing
        # function (the per-file counting loop) is called exactly
        # once regardless of --aws-sdk.
        from src import cli as cli_module

        calls = []
        original = cli_module._process_files_parallel_cached

        def counting_wrapper(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(cli_module, "_process_files_parallel_cached", counting_wrapper)
        run([str(sample_repo), "--aws-sdk"])
        assert len(calls) == 1

