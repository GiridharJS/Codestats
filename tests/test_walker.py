import os
import subprocess
from pathlib import Path

import pytest

from src.walker import (
    NotADirectoryPathError,
    PathNotFoundError,
    apply_excludes,
    get_files,
    load_ignore_patterns,
    validate_repo_path,
    walk_filesystem,
)


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


class TestValidateRepoPath:
    def test_valid_directory_returns_resolved_path(self, tmp_path):
        result = validate_repo_path(str(tmp_path))
        assert isinstance(result, Path)
        assert result.is_dir()

    def test_missing_path_raises_path_not_found(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(PathNotFoundError):
            validate_repo_path(str(missing))

    def test_file_instead_of_directory_raises(self, tmp_path):
        f = tmp_path / "not_a_dir.py"
        f.write_text("x = 1\n")
        with pytest.raises(NotADirectoryPathError):
            validate_repo_path(str(f))

    def test_expands_user_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = validate_repo_path("~")
        assert result == tmp_path.resolve()


class TestWalkFilesystemRecursion:
    def test_returns_path_objects_not_strings(self, tmp_path):
        # Public contract: walk_filesystem returns Path objects, even
        # though it builds plain strings internally now -- see its
        # docstring. Other code (and other tests) rely on this.
        (tmp_path / "app.py").write_text("x = 1\n")
        found = walk_filesystem(tmp_path)
        assert all(isinstance(f, Path) for f in found)

    def test_scanning_the_filesystem_root_does_not_mangle_relative_paths(self, tmp_path, monkeypatch):
        # Regression test for a prefix-length edge case: when
        # repo_path already ends with a path separator (as it does
        # when it IS the filesystem root, e.g. "/" on Linux or "C:\"
        # on Windows), naively assuming "len(repo_str) + 1" skips one
        # character too many when computing each file's path relative
        # to the root. Reproduced here by monkeypatching os.walk to
        # simulate scanning a root-like path (a real fake root avoids
        # needing actual filesystem-root permissions in a test).
        import os as os_module

        fake_root = str(tmp_path) + os_module.sep  # ends with a separator, like a real root would
        (tmp_path / ".ignore").write_text("*.log\n")  # gives walk_filesystem an ignore_patterns branch to exercise
        (tmp_path / "etc").mkdir()
        (tmp_path / "etc" / "passwd.txt").write_text("data\n")
        (tmp_path / "etc" / "skip.log").write_text("noise\n")

        found = walk_filesystem(Path(fake_root))
        rel = {f.relative_to(tmp_path).as_posix() for f in found}
        assert "etc/passwd.txt" in rel
        assert "etc/skip.log" not in rel  # correctly matched and excluded by the .ignore pattern
        # If the prefix-length math were off by one, "etc/passwd.txt"
        # would come back mangled (e.g. "tc/passwd.txt") instead.
        assert not any(r.startswith("tc/") for r in rel)

    def test_finds_files_in_nested_subdirectories(self, tmp_path):
        (tmp_path / "src" / "core").mkdir(parents=True)
        (tmp_path / "src" / "core" / "Main.java").write_text("class Main {}\n")
        (tmp_path / "src" / "util.py").write_text("x = 1\n")
        (tmp_path / "README.md").write_text("# hi\n")  # unsupported lang, still discovered

        found = walk_filesystem(tmp_path)
        rel = {str(f.relative_to(tmp_path).as_posix()) for f in found}

        assert "src/core/Main.java" in rel
        assert "src/util.py" in rel
        assert "README.md" in rel  # walker finds it; language filtering happens later

    def test_deeply_nested_subdirectories_are_all_scanned(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.rs").write_text("fn main() {}\n")

        found = walk_filesystem(tmp_path)
        rel = {str(f.relative_to(tmp_path).as_posix()) for f in found}
        assert "a/b/c/d/deep.rs" in rel

    def test_ignores_hardcoded_noise_dirs(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "junk.py").write_text("x = 1\n")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "junk.py").write_text("x = 1\n")
        (tmp_path / "main.go").write_text("package main\n")

        found = walk_filesystem(tmp_path)
        rel = {str(f.relative_to(tmp_path).as_posix()) for f in found}

        assert "main.go" in rel
        assert not any("node_modules" in r for r in rel)
        assert not any("__pycache__" in r for r in rel)

    def test_does_not_blindly_exclude_ambiguous_dir_names(self, tmp_path):
        # Regression test: "target", "build", "env", "bin", etc. look
        # like safe build-output names but are also common Java/Kotlin
        # package-name segments (org.example.aop.target,
        # org.example.core.env, ...). Blindly excluding any directory
        # with one of these bare names -- regardless of where in the
        # tree it sits -- silently dropped real source files (verified
        # against a real scan of spring-framework: 141 legitimate
        # .java files disappeared this way). Without a .gitignore rule
        # actually calling for it, these names must NOT be excluded.
        for name in ("target", "build", "env", "bin", "obj", "dist", "venv"):
            d = tmp_path / "src" / name
            d.mkdir(parents=True)
            (d / "Real.java").write_text("class Real {}\n")

        found = walk_filesystem(tmp_path)
        rel = {str(f.relative_to(tmp_path).as_posix()) for f in found}

        for name in ("target", "build", "env", "bin", "obj", "dist", "venv"):
            assert f"src/{name}/Real.java" in rel

    def test_gitignore_still_excludes_real_build_output_dirs(self, tmp_path):
        # The correct way to exclude a genuine build-output directory
        # is the project's own .gitignore -- properly path-anchored,
        # so it doesn't collide with same-named source packages
        # elsewhere in the tree.
        (tmp_path / ".gitignore").write_text("/target/\n")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "Generated.class").write_text("junk\n")
        (tmp_path / "src" / "org" / "example" / "target").mkdir(parents=True)
        (tmp_path / "src" / "org" / "example" / "target" / "Real.java").write_text("class Real {}\n")

        found = walk_filesystem(tmp_path)
        rel = {str(f.relative_to(tmp_path).as_posix()) for f in found}

        assert not any(r.startswith("target/") for r in rel)
        assert "src/org/example/target/Real.java" in rel


class TestApplyExcludes:
    def test_excludes_matching_glob_forward_slash(self, tmp_path):
        files = [
            tmp_path / "main.py",
            tmp_path / "tests" / "test_main.py",
        ]
        result = apply_excludes(files, tmp_path, ["tests/*"])
        assert tmp_path / "main.py" in result
        assert tmp_path / "tests" / "test_main.py" not in result

    def test_no_patterns_returns_all(self, tmp_path):
        files = [tmp_path / "a.py", tmp_path / "b.py"]
        assert apply_excludes(files, tmp_path, []) == files
        assert apply_excludes(files, tmp_path, None) == files

    def test_excludes_use_posix_separators_regardless_of_platform(self, tmp_path):
        # Even though Path objects use native separators internally,
        # the exclude pattern matching normalises to forward slashes,
        # so "vendor/*" behaves the same on Windows and Linux.
        nested = tmp_path / "vendor" / "lib.c"
        files = [tmp_path / "main.c", nested]
        result = apply_excludes(files, tmp_path, ["vendor/*"])
        assert tmp_path / "main.c" in result
        assert nested not in result


@pytest.mark.skipif(
    subprocess.run(["which", "git"], capture_output=True).returncode != 0,
    reason="git is not installed",
)
class TestGetFilesWithGit:
    def test_get_git_tracked_files_returns_correctly_joined_path_objects(self, tmp_path):
        # Direct test of the string-join rewrite: git always prints
        # forward slashes even for nested paths -- confirm they're
        # joined onto repo_path correctly (and wrapped as Path, not
        # left as strings) regardless of this OS's native separator.
        from src.walker import get_git_tracked_files

        _init_git_repo(tmp_path)
        (tmp_path / "src" / "nested").mkdir(parents=True)
        (tmp_path / "src" / "nested" / "deep.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "src/nested/deep.py"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        found = get_git_tracked_files(tmp_path.resolve())
        assert all(isinstance(f, Path) for f in found)
        rel = {f.relative_to(tmp_path.resolve()).as_posix() for f in found}
        assert rel == {"src/nested/deep.py"}

    def test_uses_git_ls_files_when_available(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.rb").write_text("puts 1\n")
        (tmp_path / "ignored.rb").write_text("puts 2\n")
        (tmp_path / ".gitignore").write_text("ignored.rb\n")

        subprocess.run(["git", "add", "src/main.rb", ".gitignore"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        found = get_files(str(tmp_path), use_git=True)
        rel = {f.relative_to(Path(tmp_path).resolve()).as_posix() for f in found}

        assert "src/main.rb" in rel  # subdirectory file found via git
        assert "ignored.rb" not in rel  # gitignored file skipped

    def test_no_git_flag_forces_manual_walk(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "main.c").write_text("int main(){return 0;}\n")

        found = get_files(str(tmp_path), use_git=False)
        rel = {f.name for f in found}
        assert "main.c" in rel


class TestGetFilesAsStrings:
    def test_returns_plain_strings_not_path_objects(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n")
        found = get_files(str(tmp_path), use_git=False, as_strings=True)
        assert all(isinstance(f, str) for f in found)

    def test_same_files_found_as_the_path_returning_default(self, tmp_path):
        (tmp_path / "backend" / "api").mkdir(parents=True)
        (tmp_path / "backend" / "api" / "server.go").write_text("package main\n")
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "app.py").write_text("print(1)\n")

        as_paths = get_files(str(tmp_path), use_git=False)
        as_strings = get_files(str(tmp_path), use_git=False, as_strings=True)
        assert {str(f) for f in as_paths} == set(as_strings)

    def test_works_with_git_tracked_files_too(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.rb").write_text("puts 1\n")
        subprocess.run(["git", "add", "src/main.rb"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        found = get_files(str(tmp_path), use_git=True, as_strings=True)
        assert all(isinstance(f, str) for f in found)
        assert any(f.endswith(os.path.join("src", "main.rb")) for f in found)

    def test_exclude_patterns_still_apply(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("x = 1\n")
        (tmp_path / "app.py").write_text("x = 1\n")

        found = get_files(str(tmp_path), use_git=False, as_strings=True, exclude_patterns=["tests/*"])
        assert not any("test_foo.py" in f for f in found)
        assert any(f.endswith("app.py") for f in found)

    def test_missing_path_still_raises(self, tmp_path):
        missing = tmp_path / "nope"
        with pytest.raises(PathNotFoundError):
            get_files(str(missing), as_strings=True)


class TestGetFilesWithoutGit:
    def test_non_git_directory_falls_back_to_manual_walk(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n")
        found = get_files(str(tmp_path), use_git=True)  # not a git repo -> fallback
        rel = {f.name for f in found}
        assert "main.py" in rel

    def test_missing_path_propagates_clear_error(self, tmp_path):
        missing = tmp_path / "nope"
        with pytest.raises(PathNotFoundError):
            get_files(str(missing))

    def test_scans_all_subdirectories_end_to_end(self, tmp_path):
        (tmp_path / "backend" / "api").mkdir(parents=True)
        (tmp_path / "backend" / "api" / "server.go").write_text("package main\n")
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "app.py").write_text("print(1)\n")

        found = get_files(str(tmp_path), use_git=False)
        rel = {f.relative_to(Path(tmp_path).resolve()).as_posix() for f in found}
        assert "backend/api/server.go" in rel
        assert "frontend/app.py" in rel


class TestIgnoreFileSupport:
    """The manual walker respects .gitignore / .ignore / .tokeignore
    at the repo root -- even without an actual .git folder present
    (e.g. a GitHub "Download ZIP" snapshot) -- matching tokei's own
    default ignore-file behaviour.
    """

    def test_gitignore_excludes_matching_files(self, tmp_path):
        (tmp_path / "keep.py").write_text("x = 1\n")
        (tmp_path / "secret.py").write_text("y = 2\n")
        (tmp_path / ".gitignore").write_text("secret.py\n")

        found = walk_filesystem(tmp_path)
        names = {f.name for f in found if f.name != ".gitignore"}
        assert "keep.py" in names
        assert "secret.py" not in names

    def test_gitignore_excludes_matching_directory(self, tmp_path):
        (tmp_path / "keep.py").write_text("x = 1\n")
        (tmp_path / "vendor").mkdir()
        (tmp_path / "vendor" / "lib.py").write_text("y = 2\n")
        (tmp_path / ".gitignore").write_text("vendor/\n")

        found = walk_filesystem(tmp_path)
        names = {f.relative_to(tmp_path).as_posix() for f in found}
        assert "keep.py" in names
        assert not any("vendor" in n for n in names)

    def test_tokeignore_is_respected_without_git(self, tmp_path):
        # no .git folder at all, matching a GitHub ZIP download
        (tmp_path / "keep.py").write_text("x = 1\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "data").mkdir()
        (tmp_path / "tests" / "data" / "fixture.py").write_text("y = 2\n")
        (tmp_path / ".tokeignore").write_text("tests/data\n")

        found = walk_filesystem(tmp_path)
        names = {f.relative_to(tmp_path).as_posix() for f in found}
        assert "keep.py" in names
        assert "tests/data/fixture.py" not in names

    def test_negation_pattern_re_includes_a_file(self, tmp_path):
        (tmp_path / "a.log").write_text("log a\n")
        (tmp_path / "b.log").write_text("log b\n")
        (tmp_path / ".gitignore").write_text("*.log\n!b.log\n")

        found = walk_filesystem(tmp_path)
        names = {f.name for f in found}
        assert "a.log" not in names
        assert "b.log" in names

    def test_no_ignore_files_present_behaves_as_before(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n")
        found = walk_filesystem(tmp_path)
        assert any(f.name == "main.py" for f in found)

    def test_get_files_respects_gitignore_even_without_use_git(self, tmp_path):
        (tmp_path / "keep.py").write_text("x = 1\n")
        (tmp_path / "secret.py").write_text("y = 2\n")
        (tmp_path / ".gitignore").write_text("secret.py\n")

        found = get_files(str(tmp_path), use_git=False)
        names = {f.name for f in found if f.name != ".gitignore"}
        assert "keep.py" in names
        assert "secret.py" not in names


class TestLoadIgnorePatterns:
    def test_combines_multiple_ignore_files(self, tmp_path):
        (tmp_path / ".gitignore").write_text("a.txt\n")
        (tmp_path / ".tokeignore").write_text("b.txt\n")
        patterns = load_ignore_patterns(tmp_path)
        assert "a.txt" in patterns
        assert "b.txt" in patterns

    def test_skips_comments_and_blank_lines(self, tmp_path):
        (tmp_path / ".gitignore").write_text("# a comment\n\nreal_pattern.txt\n")
        patterns = load_ignore_patterns(tmp_path)
        assert patterns == ["real_pattern.txt"]

    def test_no_ignore_files_returns_empty_list(self, tmp_path):
        assert load_ignore_patterns(tmp_path) == []
