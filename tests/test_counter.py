import pytest

from src.counter import FileStats, count_file, count_lines, is_binary_file


class TestCountLines:
    def test_all_code_lines(self):
        lines = ["x = 1\n", "y = 2\n", "print(x + y)\n"]
        result = count_lines(lines, "Python")
        assert result == {"lines": 3, "blank": 0, "comment": 0, "code": 3}

    def test_blank_lines(self):
        lines = ["x = 1\n", "\n", "   \n", "y = 2\n"]
        result = count_lines(lines, "Python")
        assert result["lines"] == 4
        assert result["blank"] == 2
        assert result["code"] == 2

    def test_single_line_comments(self):
        lines = ["# this is a comment\n", "x = 1  \n", "# another comment\n"]
        result = count_lines(lines, "Python")
        assert result["comment"] == 2
        assert result["code"] == 1

    def test_python_docstring_single_line_counts_as_code(self):
        # Python has no block-comment syntax; a triple-quoted string is
        # a real string-literal expression, so it counts as code, not
        # comment -- matching tokei's convention.
        lines = ['"""a docstring"""\n', "x = 1\n"]
        result = count_lines(lines, "Python")
        assert result["code"] == 2
        assert result["comment"] == 0

    def test_python_docstring_multi_line_counts_as_code(self):
        lines = [
            '"""\n',
            "This is a multi-line\n",
            "docstring block\n",
            '"""\n',
            "x = 1\n",
        ]
        result = count_lines(lines, "Python")
        assert result["code"] == 5
        assert result["comment"] == 0

    def test_c_style_block_comment(self):
        lines = [
            "/* start of comment\n",
            " * still in comment\n",
            " */\n",
            "int x = 1;\n",
        ]
        result = count_lines(lines, "C")
        assert result["comment"] == 3
        assert result["code"] == 1

    def test_c_style_line_comment(self):
        lines = ["// a comment\n", "int x = 1;\n"]
        result = count_lines(lines, "C++")
        assert result["comment"] == 1
        assert result["code"] == 1

    def test_java_line_and_block_comments(self):
        lines = ["// header\n", "/* block */\n", "int x = 1;\n"]
        result = count_lines(lines, "Java")
        assert result["comment"] == 2
        assert result["code"] == 1

    def test_go_line_comment(self):
        lines = ["// package doc\n", "package main\n"]
        result = count_lines(lines, "Go")
        assert result["comment"] == 1
        assert result["code"] == 1

    def test_rust_line_comment(self):
        lines = ["// a rust comment\n", "fn main() {}\n"]
        result = count_lines(lines, "Rust")
        assert result["comment"] == 1
        assert result["code"] == 1

    def test_ruby_hash_comment(self):
        lines = ["# a ruby comment\n", "puts 1\n"]
        result = count_lines(lines, "Ruby")
        assert result["comment"] == 1
        assert result["code"] == 1

    def test_ruby_begin_end_block_comment(self):
        lines = ["=begin\n", "multi line\n", "comment block\n", "=end\n", "puts 1\n"]
        result = count_lines(lines, "Ruby")
        assert result["comment"] == 4
        assert result["code"] == 1

    def test_empty_file(self):
        result = count_lines([], "Python")
        assert result == {"lines": 0, "blank": 0, "comment": 0, "code": 0}

    def test_unknown_language_treats_everything_as_code(self):
        lines = ["# not a comment here since language is unknown\n", "some text\n"]
        result = count_lines(lines, "SomeUnknownLanguage")
        assert result["comment"] == 0
        assert result["code"] == 2

    def test_mixed_content(self):
        lines = [
            "# header comment\n",
            "\n",
            "def foo():\n",
            "    return 1  # inline logic marker line, but not a comment-only line\n",
            "\n",
        ]
        result = count_lines(lines, "Python")
        assert result["lines"] == 5
        assert result["blank"] == 2
        assert result["comment"] == 1
        # note: inline trailing comments on a code line are counted as code,
        # since the line does not *start* with the comment marker
        assert result["code"] == 2


class TestIsBinaryFile:
    def test_text_file_is_not_binary(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        assert is_binary_file(str(f)) is False

    def test_file_with_null_byte_is_binary(self, tmp_path):
        f = tmp_path / "sample.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        assert is_binary_file(str(f)) is True

    def test_missing_file_treated_as_binary(self, tmp_path):
        missing = tmp_path / "does_not_exist.py"
        assert is_binary_file(str(missing)) is True

    def test_utf16_le_text_file_is_not_binary(self, tmp_path):
        # A UTF-16-encoded text file null-pads every ASCII character
        # (e.g. "REM" -> b"R\x00E\x00M\x00"), which would trip a naive
        # null-byte check even though the file is genuine text --
        # common for .bat/.sh/.txt files saved from Windows tools.
        f = tmp_path / "build.bat"
        f.write_bytes("REM comment\r\necho hi\r\n".encode("utf-16"))
        assert is_binary_file(str(f)) is False

    def test_utf8_sig_text_file_is_not_binary(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_bytes(b"\xef\xbb\xbfx = 1\n")
        assert is_binary_file(str(f)) is False


class TestCountFile:
    def test_counts_real_python_file(self, tmp_path):
        content = "# comment\nx = 1\n\ndef foo():\n    pass\n"
        f = tmp_path / "sample.py"
        f.write_text(content)

        stats = count_file(str(f), "Python")

        assert isinstance(stats, FileStats)
        assert stats.language == "Python"
        assert stats.lines == 5
        assert stats.blank == 1
        assert stats.comment == 1
        assert stats.code == 3

    def test_binary_file_returns_none(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_bytes(b"\x00\x01\x02binary-junk")
        assert count_file(str(f), "Python") is None

    def test_missing_file_returns_none(self, tmp_path):
        missing = tmp_path / "ghost.py"
        assert count_file(str(missing), "Python") is None

    def test_counts_utf16_encoded_batch_file(self, tmp_path):
        # Regression test: this used to be silently skipped as
        # "binary" because UTF-16 null-pads every ASCII character.
        f = tmp_path / "build.bat"
        content = "REM builds the project\r\necho building\r\n"
        f.write_bytes(content.encode("utf-16"))

        stats = count_file(str(f), "Batch")

        assert stats is not None
        assert stats.lines == 2
        assert stats.comment == 1
        assert stats.code == 1

    def test_accepts_path_object_not_just_str(self, tmp_path):
        # walker.py now returns pathlib.Path objects; counter must
        # accept them directly, on both Windows and Linux.
        f = tmp_path / "core.rs"
        f.write_text("// comment\nfn main() {}\n")
        stats = count_file(f, "Rust")  # note: Path object, not str(f)
        assert stats is not None
        assert stats.code == 1
        assert stats.comment == 1
        assert isinstance(stats.path, str)  # always normalised to str for JSON


class TestStringAwareness:
    """The core tokei-inspired feature: comment markers inside string
    literals must not be treated as real comments, and vice versa.
    """

    def test_comment_marker_inside_string_is_not_a_comment(self):
        lines = ['x = "// not a comment"\n', "y = 2\n"]
        result = count_lines(lines, "JavaScript")
        assert result["code"] == 2
        assert result["comment"] == 0

    def test_hash_inside_python_string_is_not_a_comment(self):
        lines = ['msg = "# not a comment"\n']
        result = count_lines(lines, "Python")
        assert result["code"] == 1
        assert result["comment"] == 0

    def test_escaped_quote_does_not_end_string_early(self):
        lines = ['msg = "she said \\"// hi\\" to me"  // real comment\n']
        result = count_lines(lines, "JavaScript")
        # the whole line is code (it has real code on it); crucially the
        # embedded "// hi" inside the string must NOT have been treated
        # as ending the string or as its own separate comment
        assert result["code"] == 1

    def test_multiline_template_literal_counts_as_code_not_blank_or_comment(self):
        lines = [
            "const s = `line one\n",
            "line two // not a comment, still inside the template\n",
            "line three`;\n",
        ]
        result = count_lines(lines, "JavaScript")
        assert result["code"] == 3
        assert result["comment"] == 0

    def test_shell_single_quotes_are_fully_literal(self):
        # '#' inside single quotes in shell is never a comment, ever
        lines = ["echo '# not a comment'\n"]
        result = count_lines(lines, "Shell")
        assert result["code"] == 1
        assert result["comment"] == 0


class TestNestedComments:
    """Languages that support nested block comments must correctly
    track comment depth; languages that don't must close on the first
    end-marker even if it looks like there's a nested start inside.
    """

    def test_rust_nested_block_comment_single_line(self):
        lines = ["/* outer /* inner */ still outer */\n"]
        result = count_lines(lines, "Rust")
        assert result["comment"] == 1
        assert result["code"] == 0

    def test_rust_nested_block_comment_multiline(self):
        lines = [
            "/* outer\n",
            "  /* inner */\n",
            "  still outer\n",
            "*/\n",
            "let x = 1;\n",
        ]
        result = count_lines(lines, "Rust")
        assert result["comment"] == 4
        assert result["code"] == 1

    def test_java_block_comment_is_not_nestable(self):
        # Java/C/C++ close at the FIRST */, unlike Rust -- this is the
        # correct, language-accurate distinction the old simple parser
        # couldn't make at all.
        lines = ["/* outer /* inner */ this text is now real code */\n"]
        result = count_lines(lines, "Java")
        assert result["code"] == 1  # line has real code after the comment closes

    def test_haskell_nested_block_comment(self):
        lines = ["{- outer {- inner -} still outer -}\n"]
        result = count_lines(lines, "Haskell")
        assert result["comment"] == 1
        assert result["code"] == 0


class TestBackwardCompatibleBehavior:
    """Confirm existing documented behavior from before the engine
    rewrite still holds.
    """

    def test_python_docstring_now_counts_as_code_matching_tokei(self):
        # This behavior was intentionally reversed from the original
        # "docstring = comment" convention to match tokei, since a
        # Python triple-quoted string is technically a real code
        # expression, not a comment.
        lines = ['"""\n', "a docstring\n", '"""\n', "x = 1\n"]
        result = count_lines(lines, "Python")
        assert result["code"] == 4
        assert result["comment"] == 0

    def test_line_starting_with_comment_marker_is_comment(self):
        lines = ["# a comment\n", "x = 1\n"]
        result = count_lines(lines, "Python")
        assert result["comment"] == 1
        assert result["code"] == 1


class TestPlainTextConvention:
    """.txt files: every non-blank line counts as comment (documentation),
    matching tokei's "Plain Text" convention -- there's no code concept
    for a plain text file.
    """

    def test_non_blank_lines_are_comments(self):
        lines = ["hello world\n", "\n", "more text\n"]
        result = count_lines(lines, "Plain Text")
        assert result["comment"] == 2
        assert result["blank"] == 1
        assert result["code"] == 0

    def test_whitespace_only_line_is_blank_not_comment(self):
        # regression guard for the "" catch-all line-marker trick:
        # a line with only spaces/tabs must still count as blank.
        lines = ["text\n", "   \n", "\t\n"]
        result = count_lines(lines, "Plain Text")
        assert result["blank"] == 2
        assert result["comment"] == 1
