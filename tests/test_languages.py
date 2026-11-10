import pytest

from src.languages import (
    COMMENT_SYNTAX,
    DEFAULT_COMMENT_SYNTAX,
    LANGUAGE_EXTENSIONS,
    SUPPORTED_LANGUAGES,
    detect_language,
    get_comment_syntax,
)


class TestDetectLanguage:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("Main.java", "Java"),
            ("main.py", "Python"),
            ("script.PY", "Python"),  # case-insensitive extension
            ("server.go", "Go"),
            ("app.rb", "Ruby"),
            ("lib.rs", "Rust"),
            ("core.c", "C"),
            ("engine.cpp", "C++"),
            ("Program.cs", "C#"),
            ("app.js", "JavaScript"),
            ("index.php", "PHP"),
            ("App.swift", "Swift"),
            ("Main.kt", "Kotlin"),
            ("script.pl", "Perl"),
            ("init.lua", "Lua"),
            ("Main.hs", "Haskell"),
            ("app.ex", "Elixir"),
            ("module.erl", "Erlang"),
            ("main.dart", "Dart"),
            ("analysis.r", "R"),
            ("deploy.sh", "Shell"),
            ("build.bat", "Batch"),
            ("run.cmd", "Batch"),
            ("script.ps1", "PowerShell"),
            ("query.sql", "SQL"),
            ("index.html", "HTML"),
            ("style.css", "CSS"),
            ("style.scss", "Sass"),
            ("data.yaml", "YAML"),
            ("data.yml", "YAML"),
            ("data.json", "JSON"),
            ("config.toml", "TOML"),
            ("README.md", "Markdown"),
            ("main.m", "Objective-C"),
            ("main.mm", "Objective-C++"),
            ("prog.asm", "Assembly"),
            ("main.jl", "Julia"),
            ("main.nim", "Nim"),
            ("main.cr", "Crystal"),
            ("main.ml", "OCaml"),
            ("main.zig", "Zig"),
            ("Contract.sol", "Solidity"),
        ],
    )
    def test_wide_range_of_supported_extensions(self, filename, expected):
        assert detect_language(filename) == expected

    def test_unrecognised_extension_returns_none(self):
        assert detect_language("archive.zip") is None
        assert detect_language("image.png") is None

    def test_no_extension_returns_none(self):
        assert detect_language("LICENSE") is None

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("Rakefile", "Ruby"),
            ("Gemfile", "Ruby"),
            ("Dockerfile", "Dockerfile"),
            ("Makefile", "Makefile"),
            ("CMakeLists.txt", "CMake"),
        ],
    )
    def test_special_filenames(self, filename, expected):
        assert detect_language(filename) == expected

    def test_full_path_is_handled(self):
        assert detect_language("/home/user/project/src/Main.java") == "Java"
        assert detect_language("project/lib/core.rs") == "Rust"

    def test_at_least_50_languages_supported(self):
        # This build significantly expands on the original 7-language
        # restriction -- assert we're well beyond that, without
        # hardcoding an exact number that'll need updating every time
        # a language is added.
        assert len(SUPPORTED_LANGUAGES) >= 50

    def test_every_supported_language_reachable_via_some_extension_or_filename(self):
        from src.languages import SPECIAL_FILENAMES
        reachable = set(LANGUAGE_EXTENSIONS.values()) | set(SPECIAL_FILENAMES.values())
        assert reachable == set(SUPPORTED_LANGUAGES)


class TestCommentSyntax:
    @pytest.mark.parametrize("lang", [
        "Java", "Python", "Go", "Ruby", "Rust", "C", "C++",
        "JavaScript", "TypeScript", "PHP", "Swift", "Kotlin",
        "Haskell", "Shell", "SQL",
    ])
    def test_every_supported_language_has_a_real_spec(self, lang):
        syntax = get_comment_syntax(lang)
        assert syntax == COMMENT_SYNTAX[lang]
        # every entry must have all three keys, even if some are empty
        assert set(syntax.keys()) == {"line", "block", "strings"}

    def test_every_language_in_the_table_has_a_spec_defined(self):
        # guards against silently adding a language to
        # LANGUAGE_EXTENSIONS without giving it a COMMENT_SYNTAX entry
        # (which would silently fall back to "no comments recognised")
        missing = [lang for lang in SUPPORTED_LANGUAGES if lang not in COMMENT_SYNTAX]
        assert missing == []

    def test_genuinely_unknown_language_returns_default(self):
        assert get_comment_syntax("Brainfuck") == DEFAULT_COMMENT_SYNTAX

    def test_none_language_returns_default(self):
        assert get_comment_syntax(None) == DEFAULT_COMMENT_SYNTAX

    def test_rust_block_comments_are_nestable(self):
        assert COMMENT_SYNTAX["Rust"]["block"][0][2] is True

    def test_java_block_comments_are_not_nestable(self):
        assert COMMENT_SYNTAX["Java"]["block"][0][2] is False

    def test_shell_single_quotes_have_no_escapes(self):
        # single-quoted strings in shell are fully literal
        squote = [s for s in COMMENT_SYNTAX["Shell"]["strings"] if s[0] == "'"][0]
        assert squote[2] is False


class TestBashShellSplit:
    """tokei classifies .bash files as a distinct "BASH" language from
    .sh files ("Shell") -- matched here, with tokei's exact naming
    (uppercase "BASH"), for closer parity.
    """

    def test_bash_extension_maps_to_bash(self):
        assert detect_language("script.bash") == "BASH"

    def test_sh_extension_maps_to_shell(self):
        assert detect_language("script.sh") == "Shell"

    def test_bash_has_its_own_comment_syntax_entry(self):
        assert "BASH" in COMMENT_SYNTAX
        assert COMMENT_SYNTAX["BASH"] == COMMENT_SYNTAX["Shell"]
