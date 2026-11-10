"""Language detection and comment/string syntax definitions.

Each language has three pieces of syntax info:
  - "line":    list of line-comment prefixes, e.g. ["//"]
  - "block":   list of (start, end, nestable) tuples
  - "strings": list of (start, end, has_escapes) tuples -- lets the
               counter tell a comment marker inside a string literal
               apart from a real comment (e.g. `x = "// not this"`)
"""

import os

# ---------------------------------------------------------------------------
# Reusable syntax fragments -- most languages are one of a few "families"
# (C-style, Python-style, shell-style, markup/data, etc.)
# ---------------------------------------------------------------------------

_DQUOTE_ESCAPED = ('"', '"', True)
_SQUOTE_ESCAPED = ("'", "'", True)
_SQUOTE_LITERAL = ("'", "'", False)

_C_STRINGS = [_DQUOTE_ESCAPED, _SQUOTE_ESCAPED]
_C_LINE = ["//"]
_C_BLOCK_PLAIN = [("/*", "*/", False)]
_C_BLOCK_NESTABLE = [("/*", "*/", True)]

_HASH_LINE = ["#"]
_NO_BLOCK = []


def _c_family(nestable=False, extra_strings=None, extra_line=None, prepend_strings=None):
    """Standard C-style spec: // line comments, /* */ block comments,
    "..."/'...' strings.

    `prepend_strings` go before the default ones -- longer markers
    that share a prefix with a shorter one (e.g. a triple-quote text
    block starting with the same `"` as a normal string) need to be
    checked first or the shorter marker always wins.
    """
    strings = list(prepend_strings) if prepend_strings else []
    strings += _C_STRINGS
    if extra_strings:
        strings += extra_strings
    line = list(_C_LINE)
    if extra_line:
        line += extra_line
    return {
        "line": line,
        "block": _C_BLOCK_NESTABLE if nestable else _C_BLOCK_PLAIN,
        "strings": strings,
    }


# ---------------------------------------------------------------------------
# Extension (lowercase, including the dot) -> language display name.
# ---------------------------------------------------------------------------
LANGUAGE_EXTENSIONS = {
    # Java / JVM family
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala", ".sc": "Scala",
    ".groovy": "Groovy",
    ".clj": "Clojure",
    # Python
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    # Go
    ".go": "Go",
    # Ruby
    ".rb": "Ruby",
    # Rust
    ".rs": "Rust",
    # C
    ".c": "C",
    ".h": "C Header",
    # C++
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".c++": "C++",
    ".hpp": "C++ Header", ".hh": "C++ Header", ".hxx": "C++ Header",
    # C#
    ".cs": "C#",
    # F#
    ".fs": "F#", ".fsx": "F#", ".fsi": "F#",
    # Visual Basic
    ".vb": "Visual Basic",
    # JavaScript / TypeScript
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript",
    # PHP
    ".php": "PHP",
    # Swift
    ".swift": "Swift",
    # Perl
    ".pl": "Perl", ".pm": "Perl",
    # Lua
    ".lua": "Lua",
    # Haskell
    ".hs": "Haskell",
    # Elixir / Erlang
    ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hrl": "Erlang",
    # Dart
    ".dart": "Dart",
    # R
    ".r": "R",
    # Shell family
    ".sh": "Shell",
    ".bash": "BASH",
    # Windows batch scripts
    ".bat": "Batch", ".cmd": "Batch",
    # PowerShell
    ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    # SQL
    ".sql": "SQL",
    # Web markup / styling
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS",
    # tokei classifies both .scss and .sass under the single "Sass" language
    ".scss": "Sass",
    ".sass": "Sass",
    ".less": "LESS",
    ".vue": "Vue",
    # Data / config
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON",
    ".xml": "XML",
    ".toml": "TOML",
    ".ini": "INI",
    # Docs
    ".md": "Markdown", ".markdown": "Markdown",
    ".txt": "Plain Text",
    ".adoc": "AsciiDoc", ".asciidoc": "AsciiDoc",
    # Build systems
    ".cmake": "CMake",
    # Objective-C
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    # Systems / niche
    ".asm": "Assembly",
    ".s": "GNU Style Assembly",
    ".cob": "COBOL", ".cbl": "COBOL",
    ".ada": "Ada", ".adb": "Ada", ".ads": "Ada",
    ".pas": "Pascal",
    ".jl": "Julia",
    ".nim": "Nim",
    ".cr": "Crystal",
    ".ml": "OCaml", ".mli": "OCaml",
    ".zig": "Zig",
    ".sol": "Solidity",
    ".hx": "Haxe",
    ".graphql": "GraphQL", ".gql": "GraphQL",
    # Templating
    ".ftl": "FreeMarker",
    ".vm": "Apache Velocity",
    ".erb": "Ruby HTML",
    # Interface definition / schema
    ".proto": "Protocol Buffers",
    # XML transforms / vector markup
    ".xsl": "XSL", ".xslt": "XSL",
    ".svg": "SVG",
}

# A few files are identified by exact filename, not extension.
SPECIAL_FILENAMES = {
    "Rakefile": "Ruby",
    "Gemfile": "Ruby",
    "Dockerfile": "Dockerfile",
    "Makefile": "Makefile",
    "CMakeLists.txt": "CMake",
}

# ---------------------------------------------------------------------------
# Comment / string syntax per language.
# ---------------------------------------------------------------------------
COMMENT_SYNTAX = {
    # Java/C# text-block """ strings have to come before the plain " pattern
    "Java": _c_family(prepend_strings=[('"""', '"""', False)]),
    "C": _c_family(),
    "C Header": _c_family(),
    "C++ Header": _c_family(),
    "C++": _c_family(),
    "C#": _c_family(prepend_strings=[('"""', '"""', False)]),
    "JavaScript": _c_family(extra_strings=[("`", "`", True)]),
    "TypeScript": _c_family(extra_strings=[("`", "`", True)]),
    "PHP": _c_family(extra_line=["#"], extra_strings=[]),
    "Go": _c_family(extra_strings=[("`", "`", False)]),  # backtick = raw string, no escapes
    "Scala": _c_family(nestable=True),
    "Dart": _c_family(nestable=True),
    "Groovy": _c_family(),
    "Solidity": _c_family(),
    "Haxe": _c_family(),

    "Rust": _c_family(nestable=True, extra_strings=[]),
    "Swift": _c_family(nestable=True),
    "Kotlin": _c_family(nestable=True, prepend_strings=[('"""', '"""', False)]),

    # Python has no block comments -- a docstring is just a string literal
    "Python": {
        "line": _HASH_LINE,
        "block": [],
        "strings": [('"""', '"""', False), ("'''", "'''", False)] + _C_STRINGS,
    },

    "Ruby": {
        "line": _HASH_LINE,
        "block": [("=begin", "=end", False)],
        "strings": [_DQUOTE_ESCAPED, _SQUOTE_ESCAPED],
    },

    "Shell": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": [_DQUOTE_ESCAPED, _SQUOTE_LITERAL]},
    "BASH": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": [_DQUOTE_ESCAPED, _SQUOTE_LITERAL]},
    # REM/rem/:: are all used in the wild, no block comment form
    "Batch": {"line": ["REM ", "Rem ", "rem ", "::"], "block": _NO_BLOCK, "strings": []},
    "PowerShell": {"line": _HASH_LINE, "block": [("<#", "#>", False)], "strings": [_DQUOTE_ESCAPED, _SQUOTE_LITERAL]},

    # --- Functional / Lisp-ish ---
    "Haskell": {"line": ["--"], "block": [("{-", "-}", True)], "strings": _C_STRINGS},
    "OCaml": {"line": [], "block": [("(*", "*)", True)], "strings": _C_STRINGS},
    "Clojure": {"line": [";"], "block": _NO_BLOCK, "strings": _C_STRINGS},
    "Erlang": {"line": ["%"], "block": _NO_BLOCK, "strings": _C_STRINGS},
    "Perl": {"line": _HASH_LINE, "block": [("=pod", "=cut", False)], "strings": [_DQUOTE_ESCAPED, _SQUOTE_LITERAL]},
    "Elixir": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": _C_STRINGS},
    "Lua": {"line": ["--"], "block": [("--[[", "]]", False)], "strings": [_DQUOTE_ESCAPED, _SQUOTE_ESCAPED]},

    # --- SQL / R / Julia / other -- family ---
    "SQL": {"line": ["--"], "block": _C_BLOCK_PLAIN, "strings": [_SQUOTE_LITERAL]},
    "R": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": _C_STRINGS},
    "Julia": {"line": _HASH_LINE, "block": [("#=", "=#", True)], "strings": _C_STRINGS},
    "Nim": {"line": ["#"], "block": [("#[", "]#", True)], "strings": _C_STRINGS},
    "Crystal": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": _C_STRINGS},

    # --- .NET extras ---
    "F#": _c_family(nestable=True, extra_line=[]),
    "Visual Basic": {"line": ["'"], "block": _NO_BLOCK, "strings": [_DQUOTE_ESCAPED]},

    # --- Objective-C(++) ---
    "Objective-C": _c_family(),
    "Objective-C++": _c_family(),

    # --- Web markup / styling ---
    "HTML": {"line": [], "block": [("<!--", "-->", False)], "strings": []},
    "Vue": {"line": [], "block": [("<!--", "-->", False)], "strings": []},
    "CSS": {"line": [], "block": _C_BLOCK_PLAIN, "strings": []},
    "Sass": {"line": ["//"], "block": _NO_BLOCK, "strings": []},
    "LESS": _c_family(),

    # --- Data / config (comments only, strings rarely matter) ---
    "YAML": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": []},
    "TOML": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": []},
    "INI": {"line": [";", "#"], "block": _NO_BLOCK, "strings": []},
    "JSON": {"line": [], "block": _NO_BLOCK, "strings": []},
    "XML": {"line": [], "block": [("<!--", "-->", False)], "strings": []},
    "GraphQL": {"line": ["#"], "block": _NO_BLOCK, "strings": _C_STRINGS},

    # --- Build systems ---
    "Dockerfile": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": _C_STRINGS},
    "Makefile": {"line": _HASH_LINE, "block": _NO_BLOCK, "strings": []},
    "CMake": {"line": ["#"], "block": _NO_BLOCK, "strings": _C_STRINGS},

    # --- Systems / niche ---
    "Assembly": {"line": [";"], "block": _NO_BLOCK, "strings": [_DQUOTE_ESCAPED]},
    "GNU Style Assembly": _c_family(),  # GAS/Go runtime .s files use C-style comments
    "COBOL": {"line": ["*"], "block": _NO_BLOCK, "strings": [_DQUOTE_ESCAPED]},
    "Ada": {"line": ["--"], "block": _NO_BLOCK, "strings": [_DQUOTE_ESCAPED]},
    "Pascal": {"line": ["//"], "block": [("{", "}", False), ("(*", "*)", False)], "strings": [("'", "'", False)]},
    "Zig": _c_family(),

    "Markdown": {"line": [], "block": [("<!--", "-->", False)], "strings": []},

    # no code concept for plain text -- "" as a line marker matches every
    # non-blank line, so it all counts as comment/documentation
    "Plain Text": {"line": [""], "block": [], "strings": []},

    # AsciiDoc's own prose counts as code (unlike Markdown) -- only an
    # explicit // or //// ... //// block is documentation
    "AsciiDoc": {"line": ["//"], "block": [("////", "////", False)], "strings": []},

    "FreeMarker": {"line": [], "block": [("<#--", "-->", False)], "strings": []},
    "Apache Velocity": {"line": ["##"], "block": [("#*", "*#", False)], "strings": []},

    # ERB: only <%# ... %> counts as comment, everything else (incl. the HTML) is code
    "Ruby HTML": {"line": [], "block": [("<%#", "%>", False)], "strings": []},

    "Protocol Buffers": _c_family(),

    "XSL": {"line": [], "block": [("<!--", "-->", False)], "strings": []},
    "SVG": {"line": [], "block": [("<!--", "-->", False)], "strings": []},
}

DEFAULT_COMMENT_SYNTAX = {"line": [], "block": [], "strings": []}

# interpreter name (from a #! line) -> language, for extensionless scripts
_SHEBANG_INTERPRETERS = {
    "sh": "Shell", "bash": "BASH", "zsh": "Shell", "ksh": "Shell", "dash": "Shell",
    "python": "Python", "python2": "Python", "python3": "Python",
    "perl": "Perl",
    "ruby": "Ruby",
    "node": "JavaScript",
}


def _detect_by_shebang(filepath):
    """Peek at a file's first line for a #! shebang and map the
    interpreter to a language. None if unreadable/no shebang/unknown.
    """
    try:
        with open(filepath, "rb") as f:
            first_line = f.readline(256)
    except OSError:
        return None

    if not first_line.startswith(b"#!"):
        return None

    line = first_line.decode("utf-8", errors="ignore").strip()
    parts = line[2:].split()
    if not parts:
        return None

    # "#!/usr/bin/env bash" -> interpreter is the 2nd token
    # "#!/bin/bash" -> interpreter is the last path segment of the 1st
    if parts[0].rsplit("/", 1)[-1] == "env" and len(parts) > 1:
        name = parts[1]
    else:
        name = parts[0].rsplit("/", 1)[-1]

    name = name.rstrip("0123456789.")  # "python3.11" -> "python"
    return _SHEBANG_INTERPRETERS.get(name)

SUPPORTED_LANGUAGES = sorted(set(LANGUAGE_EXTENSIONS.values()) | set(SPECIAL_FILENAMES.values()))


def detect_language(filepath):
    """Language name for a file path, or None if unrecognised.

    Uses os.path.basename/splitext rather than pathlib's .name/.suffix
    -- called once per file on every scan, and pathlib's object
    construction turned out to be a real cost at that scale.
    """
    filepath_str = os.fspath(filepath)
    filename = os.path.basename(filepath_str)

    if filename in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[filename]

    ext = os.path.splitext(filename)[1].lower()
    lang = LANGUAGE_EXTENSIONS.get(ext)
    if lang is not None:
        return lang

    if ext == "":  # no extension (e.g. gradlew) -- try a shebang instead
        return _detect_by_shebang(filepath_str)

    return None


def get_comment_syntax(language):
    """{"line", "block", "strings"} spec for a language, or an empty
    one (everything counts as code) if unknown.
    """
    return COMMENT_SYNTAX.get(language, DEFAULT_COMMENT_SYNTAX)
