"""Per-file line counting: classifies each line as blank, comment, or
code.

This is a real character-level scanner with state carried across the
whole file, so it handles: multi-line block comments, nested block
comments (Rust etc), comment markers inside a string literal (not a
real comment), multi-line string literals (still code, not comment),
and escaped quotes inside strings. Same general approach tools like
tokei use, scoped to what this project needs.
"""

from dataclasses import dataclass
from typing import Optional, Union
from pathlib import Path
import re

from src.languages import get_comment_syntax

PathLike = Union[str, Path]


@dataclass
class FileStats:
    path: str  # stored as str, not Path, so it's JSON-serialisable
    language: str
    lines: int = 0
    blank: int = 0
    comment: int = 0
    code: int = 0


def _encoding_from_bom(data: bytes):
    """Encoding implied by a leading BOM, or "utf-8" if none. UTF-16
    text (common from Windows Notepad's "Unicode" save option) has
    every ASCII char null-padded, so a naive null-byte binary check
    would misclassify it as binary -- BOM detection avoids that.
    """
    if data[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    return "utf-8"


def _split_universal_newlines(text):
    """Split on \\n, \\r\\n, \\r only -- same rule readlines() uses.

    Deliberately not str.splitlines(), which also splits on several
    Unicode line separators readlines() doesn't treat as breaks. A
    file containing one of those would get an extra phantom line
    under splitlines() that readlines() wouldn't count.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text == "":
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _read_file_lines(filepath: PathLike):
    """Read a file once and return its lines (readlines()-style
    splitting), or None if it can't be read as text.

    Binary detection, encoding detection, and the real read all
    happen against one in-memory buffer from a single open()+read()
    -- the only place a source file gets opened for counting.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except OSError:
        return None

    encoding = _encoding_from_bom(data)
    if encoding == "utf-8" and b"\0" in data[:1024]:
        return None  # binary file, not text

    return _split_universal_newlines(data.decode(encoding, errors="ignore"))


def is_binary_file(filepath: PathLike, blocksize=1024):
    """Heuristic binary check: null bytes in the first chunk, except
    UTF-16 text (expected to have them). Standalone for callers that
    just need yes/no -- _read_file_lines does its own equivalent
    check inline, so it doesn't call this.
    """
    try:
        with open(filepath, "rb") as f:
            head = f.read(blocksize)
    except OSError:
        return True
    if _encoding_from_bom(head) != "utf-8":
        return False
    return b"\0" in head


class _ScanState:
    """State carried across lines in one file: inside a string
    literal? Inside a (possibly nested) block comment, how deep?
    """
    __slots__ = ("in_string_end", "in_string_escapes", "block_end", "block_start",
                 "block_nestable", "block_depth")

    def __init__(self):
        self.in_string_end = None       # closing delimiter, or None
        self.in_string_escapes = False  # does backslash escape the next char?
        self.block_end = None           # closing delimiter of current block comment
        self.block_start = None         # opening delimiter (needed to detect nesting)
        self.block_nestable = False
        self.block_depth = 0


_trigger_chars_cache = {}


def _spec_trigger_chars(spec):
    """Characters that could start a marker for this language, e.g.
    {'#'} for Shell. Lets _scan_line skip ordinary characters with a
    cheap set check instead of trying every marker at every position.
    Cached per spec (COMMENT_SYNTAX entries are fixed shared objects).

    None means "can't filter, check every char" -- Plain Text's
    catch-all `"line": [""]` marker has no meaningful trigger set.
    """
    key = id(spec)
    if key in _trigger_chars_cache:
        return _trigger_chars_cache[key]

    chars = set()
    for marker in spec["line"]:
        if marker == "":
            _trigger_chars_cache[key] = None
            return None
        chars.add(marker[0])
    for start, _end, _nestable in spec["block"]:
        if start:
            chars.add(start[0])
    for start, _end, _has_escapes in spec["strings"]:
        if start:
            chars.add(start[0])

    _trigger_chars_cache[key] = chars
    return chars


_trigger_regex_cache = {}


def _spec_trigger_regex(spec, triggers):
    """Compiled regex matching any trigger char, or None (Plain
    Text's catch-all case). Lets _scan_line jump straight to the next
    relevant character with one C-level search() instead of stepping
    through ordinary code one character at a time.
    """
    key = id(spec)
    if key in _trigger_regex_cache:
        return _trigger_regex_cache[key]
    if not triggers:
        _trigger_regex_cache[key] = None
        return None
    pattern = re.compile("[" + "".join(re.escape(c) for c in sorted(triggers)) + "]")
    _trigger_regex_cache[key] = pattern
    return pattern


def _scan_line(line, spec, state: _ScanState, triggers, trigger_regex):
    """Scan one line against the language spec, updating `state` in
    place (strings/comments can span lines) and returning
    (has_code, has_comment) for this line.
    """
    line_markers = spec["line"]
    block_markers = spec["block"]      # list of (start, end, nestable)
    string_markers = spec["strings"]   # list of (start, end, has_escapes)

    # A whitespace-only line is blank UNLESS it's inside an
    # already-open multi-line string or comment, in which case it's
    # still part of that construct's content (still code, or still
    # comment respectively) -- e.g. a blank line inside a docstring.
    if line.strip() == "":
        if state.in_string_end is not None:
            return True, False
        if state.block_end is not None:
            return False, True
        return False, False

    has_code = False
    has_comment = False

    # a line that starts already inside a multi-line construct
    # inherits that construct's category
    if state.block_end is not None:
        has_comment = True
    if state.in_string_end is not None:
        has_code = True

    i = 0
    n = len(line)
    while i < n:
        # inside a block comment
        if state.block_end is not None:
            has_comment = True
            # non-nestable comments can jump straight to the closing
            # delimiter; nestable ones need real char-by-char scanning
            if not state.block_nestable:
                idx = line.find(state.block_end, i)
                if idx == -1:
                    i = n
                else:
                    i = idx + len(state.block_end)
                    state.block_end = None
                    state.block_start = None
                    state.block_depth = 0
                continue
            ch = line[i]
            if ch == state.block_start[0] and line.startswith(state.block_start, i):
                state.block_depth += 1
                i += len(state.block_start)
                continue
            if ch == state.block_end[0] and line.startswith(state.block_end, i):
                state.block_depth -= 1
                i += len(state.block_end)
                if state.block_depth <= 0:
                    state.block_end = None
                    state.block_start = None
                    state.block_nestable = False
                    state.block_depth = 0
                continue
            i += 1
            continue

        # inside a string literal
        if state.in_string_end is not None:
            has_code = True
            if not state.in_string_escapes:
                idx = line.find(state.in_string_end, i)
                if idx == -1:
                    i = n
                else:
                    i = idx + len(state.in_string_end)
                    state.in_string_end = None
                continue
            ch = line[i]
            if state.in_string_escapes and ch == "\\":
                i += 2  # skip the escaped character too
                continue
            if ch == state.in_string_end[0] and line.startswith(state.in_string_end, i):
                i += len(state.in_string_end)
                state.in_string_end = None
                continue
            i += 1
            continue

        ch = line[i]

        # not inside anything: jump past a whole run of characters
        # that can't start any marker, instead of stepping one at a time
        if trigger_regex is not None and ch not in triggers:
            m = trigger_regex.search(line, i)
            end = m.start() if m else n
            if not has_code and line[i:end].strip():
                has_code = True
            i = end
            continue

        # line comment start?
        matched = False
        for marker in line_markers:
            if line.startswith(marker, i):
                has_comment = True
                i = n  # a line comment consumes the rest of the line
                matched = True
                break
        if matched:
            break

        # block comment start?
        for start, end, nestable in block_markers:
            if line.startswith(start, i):
                has_comment = True
                state.block_start = start
                state.block_end = end
                state.block_nestable = nestable
                state.block_depth = 1
                i += len(start)
                matched = True
                break
        if matched:
            continue

        # string literal start?
        for start, end, has_escapes in string_markers:
            if line.startswith(start, i):
                has_code = True
                state.in_string_end = end
                state.in_string_escapes = has_escapes
                i += len(start)
                matched = True
                break
        if matched:
            continue

        # ordinary character
        if not ch.isspace():
            has_code = True
        i += 1

    return has_code, has_comment


def count_lines(lines, language):
    """Classify lines into blank/comment/code counts via the
    character-level scan above.
    """
    spec = get_comment_syntax(language)
    triggers = _spec_trigger_chars(spec)
    trigger_regex = _spec_trigger_regex(spec, triggers)
    state = _ScanState()

    result = {"lines": 0, "blank": 0, "comment": 0, "code": 0}

    for raw_line in lines:
        result["lines"] += 1
        line = raw_line.rstrip("\n").rstrip("\r")

        has_code, has_comment = _scan_line(line, spec, state, triggers, trigger_regex)

        if has_code:
            result["code"] += 1
        elif has_comment:
            result["comment"] += 1
        else:
            result["blank"] += 1

    return result


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def count_markdown_lines(lines):
    """Markdown-specific classification: prose is documentation (so
    it counts as COMMENT, not code), content inside a ``` or ~~~
    fence counts as CODE, fence delimiter lines count as comment.

    Doesn't re-parse fenced content with its own language's rules --
    everything inside a fence just counts as code, no per-language
    breakdown within it. Close enough in practice since blank-line
    and prose/fence classification (the bulk of it) is unaffected.

    This needs its own pass rather than the generic count_lines
    engine because Markdown has no line-comment marker, only an
    HTML-style block one -- the generic engine defaults unmatched
    text to code, but Markdown needs the opposite default (comment
    unless inside a fence).
    """
    result = {"lines": 0, "blank": 0, "comment": 0, "code": 0}
    in_fence = False
    fence_char = None

    for raw_line in lines:
        result["lines"] += 1
        line = raw_line.rstrip("\n").rstrip("\r")

        if line.strip() == "":
            result["blank"] += 1
            continue

        m = _FENCE_RE.match(line)
        if m:
            marker_char = m.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_char = marker_char
                result["comment"] += 1
                continue
            if marker_char == fence_char:
                in_fence = False
                fence_char = None
                result["comment"] += 1
                continue
            # different fence char while already in a fence isn't a
            # real close -- it's just literal content

        if in_fence:
            result["code"] += 1
        else:
            result["comment"] += 1

    return result


def count_markdown_file(filepath: PathLike) -> Optional[FileStats]:
    """Read a Markdown file and count it with fence-aware
    classification instead of the generic comment-syntax engine.
    """
    raw_lines = _read_file_lines(filepath)
    if raw_lines is None:
        return None

    counts = count_markdown_lines(raw_lines)

    return FileStats(
        path=str(filepath),
        language="Markdown",
        lines=counts["lines"],
        blank=counts["blank"],
        comment=counts["comment"],
        code=counts["code"],
    )


def count_file(filepath: PathLike, language) -> Optional[FileStats]:
    """Read a file and return its FileStats, or None if it can't be
    read as text (binary / permission error / missing).
    """
    raw_lines = _read_file_lines(filepath)
    if raw_lines is None:
        return None

    counts = count_lines(raw_lines, language)

    return FileStats(
        path=str(filepath),
        language=language,
        lines=counts["lines"],
        blank=counts["blank"],
        comment=counts["comment"],
        code=counts["code"],
    )
