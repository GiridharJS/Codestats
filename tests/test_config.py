import os
from pathlib import Path

import pytest

from src import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every CODESTATS_* var starts unset for each test, regardless of
    what earlier tests (or a real .env file) might have set.
    """
    for key in list(os.environ):
        if key.startswith("CODESTATS_"):
            monkeypatch.delenv(key, raising=False)
    yield


class TestLoadEnvFile:
    def test_missing_file_does_nothing(self, tmp_path):
        config.load_env_file(tmp_path / "does_not_exist.env")
        assert "CODESTATS_DEFAULT_PDF_FILENAME" not in os.environ

    def test_parses_simple_key_value_pairs(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("CODESTATS_WORKER_MEMORY_MB=150\n")
        config.load_env_file(f)
        assert os.environ["CODESTATS_WORKER_MEMORY_MB"] == "150"

    def test_ignores_comments_and_blank_lines(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# a comment\n\nCODESTATS_WORKER_MEMORY_MB=200\n# another\n")
        config.load_env_file(f)
        assert os.environ["CODESTATS_WORKER_MEMORY_MB"] == "200"

    def test_strips_quotes_from_values(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('CODESTATS_DEFAULT_PDF_FILENAME="my report.pdf"\n')
        config.load_env_file(f)
        assert os.environ["CODESTATS_DEFAULT_PDF_FILENAME"] == "my report.pdf"

    def test_supports_export_prefix(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("export CODESTATS_WORKER_MEMORY_MB=250\n")
        config.load_env_file(f)
        assert os.environ["CODESTATS_WORKER_MEMORY_MB"] == "250"

    def test_real_env_var_always_wins_over_env_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODESTATS_WORKER_MEMORY_MB", "999")
        f = tmp_path / ".env"
        f.write_text("CODESTATS_WORKER_MEMORY_MB=150\n")
        config.load_env_file(f)
        assert os.environ["CODESTATS_WORKER_MEMORY_MB"] == "999"

    def test_unreadable_directory_path_does_not_raise(self, tmp_path):
        # Passing a directory instead of a file must fail gracefully.
        config.load_env_file(tmp_path)
        assert "CODESTATS_WORKER_MEMORY_MB" not in os.environ


class TestGetters:
    def test_defaults_when_nothing_set(self):
        assert config.default_pdf_filename() == "codestats_report.pdf"
        assert config.worker_memory_budget_mb() == 300
        assert config.min_files_for_parallel() == 1000
        assert config.extra_ignore_dirs() == []
        assert config.default_sort_by() == "code"
        assert config.max_projects_displayed() == 7

    def test_overrides_take_effect(self, monkeypatch):
        monkeypatch.setenv("CODESTATS_DEFAULT_PDF_FILENAME", "custom.pdf")
        monkeypatch.setenv("CODESTATS_WORKER_MEMORY_MB", "128")
        monkeypatch.setenv("CODESTATS_MIN_FILES_FOR_PARALLEL", "42")
        monkeypatch.setenv("CODESTATS_EXTRA_IGNORE_DIRS", "generated, third_party ,.cache")
        monkeypatch.setenv("CODESTATS_DEFAULT_SORT_BY", "lines")
        monkeypatch.setenv("CODESTATS_MAX_PROJECTS_DISPLAYED", "3")

        assert config.default_pdf_filename() == "custom.pdf"
        assert config.worker_memory_budget_mb() == 128
        assert config.min_files_for_parallel() == 42
        assert config.extra_ignore_dirs() == ["generated", "third_party", ".cache"]
        assert config.default_sort_by() == "lines"
        assert config.max_projects_displayed() == 3

    def test_invalid_int_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CODESTATS_WORKER_MEMORY_MB", "not-a-number")
        assert config.worker_memory_budget_mb() == 300

    def test_invalid_sort_by_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CODESTATS_DEFAULT_SORT_BY", "nonsense")
        assert config.default_sort_by() == "code"

    def test_empty_extra_ignore_dirs_string(self, monkeypatch):
        monkeypatch.setenv("CODESTATS_EXTRA_IGNORE_DIRS", "")
        assert config.extra_ignore_dirs() == []


class TestCacheDirAndPath:
    def test_default_cache_dir_is_the_os_temp_dir_on_non_windows(self, monkeypatch):
        import sys
        import tempfile

        monkeypatch.setattr(sys, "platform", "linux")
        assert config.default_cache_dir() == tempfile.gettempdir()

    def test_default_cache_dir_is_c_tmp_on_windows(self, monkeypatch):
        import sys

        monkeypatch.setattr(sys, "platform", "win32")
        assert config.default_cache_dir() == "C:\\tmp"

    def test_cache_dir_env_var_overrides_the_windows_default_too(self, monkeypatch, tmp_path):
        import sys

        monkeypatch.setattr(sys, "platform", "win32")
        custom_dir = tmp_path / "my_cache_dir"
        monkeypatch.setenv("CODESTATS_CACHE_DIR", str(custom_dir))
        assert config.default_cache_dir() == str(custom_dir)

    def test_cache_dir_env_var_overrides_the_default(self, monkeypatch, tmp_path):
        custom_dir = tmp_path / "my_cache_dir"
        monkeypatch.setenv("CODESTATS_CACHE_DIR", str(custom_dir))
        assert config.default_cache_dir() == str(custom_dir)

    def test_default_cache_path_lives_under_cache_dir(self, monkeypatch, tmp_path):
        custom_dir = tmp_path / "my_cache_dir"
        monkeypatch.setenv("CODESTATS_CACHE_DIR", str(custom_dir))
        path = config.default_cache_path(str(tmp_path / "some_repo"))
        assert Path(path).parent == custom_dir

    def test_default_cache_path_uses_os_temp_dir_when_cache_dir_unset(self, tmp_path):
        import tempfile

        path = config.default_cache_path(str(tmp_path / "some_repo"))
        assert Path(path).parent == Path(tempfile.gettempdir())

    def test_cache_file_env_var_still_wins_over_cache_dir(self, monkeypatch, tmp_path):
        # CODESTATS_CACHE_FILE is a full, exact path override -- it
        # takes priority over CODESTATS_CACHE_DIR (which only affects
        # the auto-generated, per-repo-hashed filename).
        exact_file = tmp_path / "one_fixed_cache.db"
        monkeypatch.setenv("CODESTATS_CACHE_FILE", str(exact_file))
        monkeypatch.setenv("CODESTATS_CACHE_DIR", str(tmp_path / "ignored_dir"))
        assert config.default_cache_path(str(tmp_path / "some_repo")) == str(exact_file)

    def test_different_repos_still_get_different_filenames_under_custom_dir(self, monkeypatch, tmp_path):
        custom_dir = tmp_path / "my_cache_dir"
        monkeypatch.setenv("CODESTATS_CACHE_DIR", str(custom_dir))
        path_a = config.default_cache_path(str(tmp_path / "repo_a"))
        path_b = config.default_cache_path(str(tmp_path / "repo_b"))
        assert path_a != path_b
        assert Path(path_a).parent == custom_dir
        assert Path(path_b).parent == custom_dir

    def test_same_repo_resolves_to_same_path_under_custom_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODESTATS_CACHE_DIR", str(tmp_path / "my_cache_dir"))
        repo = str(tmp_path / "some_repo")
        assert config.default_cache_path(repo) == config.default_cache_path(repo)


class TestWalkerHonorsExtraIgnoreDirs:
    def test_extra_ignore_dir_excludes_files_beneath_it(self, tmp_path, monkeypatch):
        from src.walker import walk_filesystem

        monkeypatch.setenv("CODESTATS_EXTRA_IGNORE_DIRS", "generated")
        (tmp_path / "generated").mkdir()
        (tmp_path / "generated" / "gen.py").write_text("x = 1\n")
        (tmp_path / "app.py").write_text("y = 2\n")

        found = walk_filesystem(tmp_path)
        rel = {f.relative_to(tmp_path).as_posix() for f in found}

        assert "app.py" in rel
        assert "generated/gen.py" not in rel
